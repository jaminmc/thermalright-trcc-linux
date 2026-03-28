"""Tests for gui/lcd_handler.py — LCDHandler lifecycle and routing.

Covers:
- Construction, properties, widget dict wiring
- apply_device_config: brightness, rotation, split mode restoration + RestoreLastThemeCommand dispatch
- Theme selection: path-based, cloud, animated, persist flag
- Mask application: apply_mask, persist mask_path (mask restore logic tested in test_lcd_device.py)
- Video: play_pause, stop, seek, tick routing
- Overlay: on_overlay_changed, on_overlay_tick, flash_element
- Display settings: set_brightness, set_rotation, set_split_mode
- Background toggle, screencast frame routing
- Slideshow: update state, tick, timer management
- Lifecycle: stop_timers, cleanup
"""
from __future__ import annotations

import os

os.environ["QT_QPA_PLATFORM"] = "offscreen"

from pathlib import Path
from unittest.mock import MagicMock, patch

from PySide6.QtCore import QTimer

from trcc.gui.lcd_handler import LCDHandler

# =========================================================================
# Helpers
# =========================================================================


def _make_widgets() -> dict:
    """Build a dict of mock widgets matching LCDHandler expectations."""
    return {
        'preview': MagicMock(),
        'image_cut': MagicMock(),
        'video_cut': MagicMock(),
        'theme_setting': MagicMock(),
        'theme_local': MagicMock(),
        'theme_web': MagicMock(),
        'theme_mask': MagicMock(),
        'rotation_combo': MagicMock(),
    }


def _make_timer_fn():
    """Return a make_timer callable that returns MagicMock QTimers."""
    def make_timer(callback, single_shot=False):
        t = MagicMock(spec=QTimer)
        t._callback = callback
        return t
    return make_timer


def _make_lcd() -> MagicMock:
    """Build a mock LCDDevice."""
    lcd = MagicMock()
    lcd.lcd_size = (320, 320)
    lcd.resolution = (320, 320)
    lcd.connected = True
    lcd.auto_send = True
    lcd.current_theme_path = None
    lcd.video.playing = False
    lcd.video.has_frames = False
    lcd.overlay.enabled = False
    lcd.overlay.has_changed.return_value = False
    lcd.overlay.render.return_value = {'image': MagicMock()}
    lcd.settings.set_brightness.return_value = {'success': True, 'message': 'OK'}
    lcd.settings.set_rotation.return_value = {'success': True, 'message': 'OK'}
    lcd.settings.set_split_mode.return_value = {'success': True, 'message': 'OK'}
    lcd.settings.set_resolution.return_value = {'success': True}
    lcd.theme.select.return_value = {'image': MagicMock(), 'is_animated': False}
    lcd.theme.save.return_value = {'success': True, 'message': 'Saved'}
    lcd.theme.export_config.return_value = {'success': True, 'message': 'Exported'}
    lcd.theme.import_config.return_value = {'success': True, 'message': 'Imported'}
    # Direct LCDDevice methods (used by command handlers)
    lcd.select.return_value = {'image': MagicMock(), 'is_animated': False}
    lcd.save.return_value = {'success': True, 'message': 'Saved'}
    lcd.export_config.return_value = {'success': True, 'message': 'Exported'}
    lcd.import_config.return_value = {'success': True, 'message': 'Imported'}
    lcd.set_config.return_value = {'success': True, 'message': 'Config set'}
    lcd.enable.return_value = {'success': True, 'enabled': True}
    lcd.frame.send.return_value = {'success': True}
    lcd.frame.reset.return_value = {'success': True, 'message': 'Reset'}
    lcd.overlay.render.return_value = {'image': MagicMock()}
    lcd.overlay.service = MagicMock()
    lcd.device_service = MagicMock()
    return lcd


def _make_bus(lcd: MagicMock | None = None) -> MagicMock:
    """Mock CommandBus whose dispatch returns a result wrapping the device call."""
    from trcc.core.command_bus import CommandResult

    bus = MagicMock()
    _lcd = lcd or _make_lcd()

    def _dispatch(cmd: object) -> CommandResult:
        from trcc.core.commands.lcd import (
            SetBrightnessCommand,
            SetResolutionCommand,
            SetRotationCommand,
            SetSplitModeCommand,
        )
        if isinstance(cmd, SetBrightnessCommand):
            return CommandResult.from_dict(_lcd.set_brightness(cmd.level))
        if isinstance(cmd, SetRotationCommand):
            return CommandResult.from_dict(_lcd.set_rotation(cmd.degrees))
        if isinstance(cmd, SetSplitModeCommand):
            return CommandResult.from_dict(_lcd.set_split_mode(cmd.mode))
        if isinstance(cmd, SetResolutionCommand):
            return CommandResult.from_dict(_lcd.set_resolution(cmd.width, cmd.height))
        from trcc.core.commands.lcd import (
            EnableOverlayCommand,
            ExportThemeCommand,
            ImportThemeCommand,
            LoadMaskCommand,
            RestoreLastThemeCommand,
            SaveThemeCommand,
            SelectThemeCommand,
            SetOverlayConfigCommand,
        )
        if isinstance(cmd, RestoreLastThemeCommand):
            return CommandResult.from_dict(_lcd.restore_last_theme())
        if isinstance(cmd, SelectThemeCommand):
            return CommandResult.from_dict(_lcd.select(cmd.theme))
        if isinstance(cmd, LoadMaskCommand):
            return CommandResult.from_dict(_lcd.load_mask_standalone(cmd.mask_path))
        if isinstance(cmd, SaveThemeCommand):
            return CommandResult.from_dict(_lcd.save(cmd.name, cmd.data_dir))
        if isinstance(cmd, ExportThemeCommand):
            return CommandResult.from_dict(_lcd.export_config(cmd.path))
        if isinstance(cmd, ImportThemeCommand):
            return CommandResult.from_dict(_lcd.import_config(cmd.path, cmd.data_dir))
        if isinstance(cmd, SetOverlayConfigCommand):
            return CommandResult.from_dict(_lcd.set_config(cmd.config))
        if isinstance(cmd, EnableOverlayCommand):
            return CommandResult.from_dict(_lcd.enable(cmd.on))
        return CommandResult.ok(message="ok")

    bus.dispatch.side_effect = _dispatch
    return bus


def _make_handler(**overrides) -> LCDHandler:
    """Create LCDHandler with all mocks."""
    lcd = overrides.pop('lcd', _make_lcd())
    kw = {
        'lcd': lcd,
        'widgets': _make_widgets(),
        'make_timer': _make_timer_fn(),
        'data_dir': Path('/tmp/trcc-test'),
        'bus': _make_bus(lcd),
    }
    kw.update(overrides)
    return LCDHandler(**kw)


# =========================================================================
# Construction
# =========================================================================


class TestConstruction:
    """LCDHandler construction and properties."""

    def test_stores_lcd(self):
        lcd = _make_lcd()
        h = _make_handler(lcd=lcd)
        assert h.display is lcd

    def test_device_key_starts_empty(self):
        h = _make_handler()
        assert h.device_key == ''

    def test_brightness_level_default(self):
        h = _make_handler()
        assert h.brightness_level == 3  # DEFAULT_BRIGHTNESS_LEVEL (100%)

    def test_split_mode_default(self):
        h = _make_handler()
        assert h.split_mode == 0

    def test_ldd_is_split_default_false(self):
        h = _make_handler()
        assert h.ldd_is_split is False

    def test_is_background_active_default_false(self):
        h = _make_handler()
        assert h.is_background_active is False

    def test_is_background_active_setter(self):
        h = _make_handler()
        h.is_background_active = True
        assert h.is_background_active is True

    def test_four_timers_created(self):
        calls = []
        def track_timer(cb, single_shot=False):
            calls.append((cb, single_shot))
            return MagicMock(spec=QTimer)
        _make_handler(make_timer=track_timer)
        assert len(calls) == 4
        # Flash and debounce timers are single_shot
        assert calls[2][1] is True
        assert calls[3][1] is True


# =========================================================================
# apply_device_config
# =========================================================================


class TestApplyDeviceConfig:
    """apply_device_config — restore brightness, rotation, split, theme."""

    def _device(self, resolution=(320, 320)):
        dev = MagicMock()
        dev.device_index = 0
        dev.vid = 0x0402
        dev.pid = 0x3922
        dev.resolution = resolution
        return dev

    @patch('trcc.gui.lcd_handler.Settings')
    def test_sets_device_key(self, mock_settings):
        mock_settings.device_config_key.return_value = 'test_key'
        mock_settings.get_device_config.return_value = {}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        assert h.device_key == 'test_key'

    @patch('trcc.gui.lcd_handler.Settings')
    def test_restores_brightness(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {'brightness_level': 1}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        assert h.brightness_level == 1
        h._lcd.set_brightness.assert_called_with(1)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_restores_rotation(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {'rotation': 90}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        h._lcd.set_rotation.assert_called_with(90)
        h._w['rotation_combo'].setCurrentIndex.assert_called_with(1)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_resolution_change_updates_widgets(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        lcd = _make_lcd()
        lcd.lcd_size = (320, 320)
        h = _make_handler(lcd=lcd)
        h.apply_device_config(self._device(), 480, 480)
        # Widgets always updated — InitializeDeviceCommand is owned by _wire_bus, not here
        h._w['preview'].set_resolution.assert_called_with(480, 480)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_widgets_always_updated(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        # Widget updates are unconditional — InitializeDeviceCommand not dispatched here
        h._w['preview'].set_resolution.assert_called_with(320, 320)
        h._w['image_cut'].set_resolution.assert_called_with(320, 320)
        h._w['video_cut'].set_resolution.assert_called_with(320, 320)
        h._w['theme_setting'].set_resolution.assert_called_with(320, 320)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_split_mode_restored_for_split_resolution(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {'split_mode': 1}
        lcd = _make_lcd()
        lcd.lcd_size = (320, 320)  # different from target to trigger change
        h = _make_handler(lcd=lcd)
        # 1600x720 is the split resolution (SPLIT_MODE_RESOLUTIONS)
        h.apply_device_config(self._device((1600, 720)), 1600, 720)
        assert h.ldd_is_split is True


# =========================================================================
# Theme selection
# =========================================================================


class TestThemeSelection:
    """select_theme_from_path, select_cloud_theme — routing + state."""

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler.ThemeInfo')
    def test_select_theme_from_path_calls_select(self, mock_ti, mock_settings):
        from trcc.core.commands.lcd import SelectThemeCommand
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

        h.select_theme_from_path(path)
        dispatched = [c.args[0] for c in h._bus.dispatch.call_args_list]
        assert any(isinstance(cmd, SelectThemeCommand) for cmd in dispatched)

    def test_select_theme_nonexistent_path_noop(self):
        from trcc.core.commands.lcd import SelectThemeCommand
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = False
        h.select_theme_from_path(path)
        dispatched = [c.args[0] for c in h._bus.dispatch.call_args_list]
        assert not any(isinstance(cmd, SelectThemeCommand) for cmd in dispatched)

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler.ThemeInfo')
    def test_select_theme_stops_video(self, mock_ti, mock_settings):
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

        h.select_theme_from_path(path)
        h._lcd.video.stop.assert_called_once()

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler.ThemeInfo')
    def test_select_theme_persists_path(self, mock_ti, mock_settings):
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        h._device_key = 'dev0'
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)
        path.__str__ = lambda self: '/themes/TestTheme'

        h.select_theme_from_path(path, persist=True)
        mock_settings.save_device_setting.assert_any_call(
            'dev0', 'theme_path', '/themes/TestTheme')

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler.ThemeInfo')
    def test_select_theme_no_persist(self, mock_ti, mock_settings):
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        h._device_key = 'dev0'
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

        h.select_theme_from_path(path, persist=False)
        mock_settings.save_device_setting.assert_not_called()


# =========================================================================
# Mask
# =========================================================================


class TestMask:
    """apply_mask — loads mask, updates preview, persists."""

    @patch('trcc.gui.lcd_handler.Settings')
    def test_apply_mask_with_path(self, mock_settings):
        from trcc.core.commands.lcd import LoadMaskCommand
        h = _make_handler()
        h._device_key = 'dev0'
        mask_info = MagicMock()
        mask_info.path = '/masks/01'
        h._lcd.load_mask_standalone.return_value = {
            'success': True, 'image': MagicMock()}
        h.apply_mask(mask_info)
        dispatched = [c.args[0] for c in h._bus.dispatch.call_args_list]
        assert any(isinstance(cmd, LoadMaskCommand) for cmd in dispatched)
        mock_settings.save_device_setting.assert_called_with(
            'dev0', 'mask_path', '/masks/01')

    def test_apply_mask_no_path_sets_status(self):
        h = _make_handler()
        mask_info = MagicMock()
        mask_info.path = None
        mask_info.name = "Empty"
        h.apply_mask(mask_info)
        h._w['preview'].set_status.assert_called_once()

    @patch('trcc.gui.lcd_handler.Settings')
    def test_restore_dispatches_restore_last_theme_command(self, mock_settings):
        """apply_device_config dispatches RestoreLastThemeCommand — shared path with CLI/API."""
        from trcc.core.commands.lcd import RestoreLastThemeCommand
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        lcd = _make_lcd()
        lcd.restore_last_theme.return_value = {'success': False, 'error': 'No saved theme'}
        h = _make_handler(lcd=lcd)
        h.apply_device_config(
            MagicMock(device_index=0, vid=0x0402, pid=0x3922), 320, 320)
        dispatched = [c.args[0] for c in h._bus.dispatch.call_args_list]
        assert any(isinstance(cmd, RestoreLastThemeCommand) for cmd in dispatched)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_restore_updates_preview_on_success(self, mock_settings):
        """apply_device_config updates preview widget when RestoreLastThemeCommand succeeds."""
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        lcd = _make_lcd()
        img = MagicMock()
        lcd.restore_last_theme.return_value = {
            'success': True, 'image': img, 'is_animated': False,
            'overlay_config': None, 'overlay_enabled': False,
        }
        h = _make_handler(lcd=lcd)
        h.apply_device_config(
            MagicMock(device_index=0, vid=0x0402, pid=0x3922), 320, 320)
        h._w['preview'].set_image.assert_called_once_with(img, fast=False)


# =========================================================================
# Video
# =========================================================================


class TestVideo:
    """play_pause, stop, seek, tick."""

    def test_play_pause_toggles(self):
        h = _make_handler()
        h._lcd.video.pause.return_value = {'state': 'playing'}
        h._lcd.video.interval = 33
        h.play_pause()
        h._w['preview'].set_playing.assert_called_with(True)
        h._animation_timer.start.assert_called_with(33)

    def test_play_pause_pauses(self):
        h = _make_handler()
        h._lcd.video.pause.return_value = {'state': 'paused'}
        h.play_pause()
        h._w['preview'].set_playing.assert_called_with(False)
        h._animation_timer.stop.assert_called()

    def test_stop_video(self):
        h = _make_handler()
        h.stop_video()
        h._lcd.video.stop.assert_called_once()
        h._animation_timer.stop.assert_called()
        h._w['preview'].set_playing.assert_called_with(False)
        h._w['preview'].show_video_controls.assert_called_with(False)

    def test_seek(self):
        h = _make_handler()
        h.seek(50.0)
        h._lcd.video.seek.assert_called_once_with(50.0)


# =========================================================================
# Overlay
# =========================================================================


class TestOverlay:
    """on_overlay_changed, on_overlay_tick, flash_element."""

    @patch('trcc.gui.lcd_handler.Settings')
    def test_overlay_changed_sets_config(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        h._lcd.overlay.enabled = False
        h._w['theme_setting'].overlay_grid.overlay_enabled = True
        data = {'elements': []}
        h.on_overlay_changed(data)
        h._lcd.overlay.enable.assert_called_with(True)
        h._lcd.overlay.set_config.assert_called_with(data)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_overlay_changed_empty_data_noop(self, mock_settings):
        h = _make_handler()
        h.on_overlay_changed({})
        h._lcd.overlay.set_config.assert_not_called()

    @patch('trcc.gui.lcd_handler.Settings')
    def test_overlay_changed_none_data_noop(self, mock_settings):
        h = _make_handler()
        h.on_overlay_changed(None)
        h._lcd.overlay.set_config.assert_not_called()

    @patch('trcc.gui.lcd_handler.Settings')
    def test_overlay_changed_persists(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        h._w['theme_setting'].overlay_grid.overlay_enabled = True
        data = {'elements': [{'type': 'text'}]}
        h.on_overlay_changed(data)
        mock_settings.save_device_setting.assert_called_once()
        saved = mock_settings.save_device_setting.call_args[0]
        assert saved[0] == 'dev0'
        assert saved[1] == 'overlay'

    def test_overlay_tick_noop_when_not_video_playing(self):
        """on_overlay_tick does nothing for static themes — tick() owns rendering."""
        h = _make_handler()
        h._lcd.overlay.enabled = True
        h._lcd.video.playing = False
        metrics = MagicMock()
        h.on_overlay_tick(metrics)
        # update_metrics is called by the background loop, not on_overlay_tick
        h._lcd.overlay.update_metrics.assert_not_called()
        h._lcd.overlay.render.assert_not_called()

    def test_overlay_tick_noop_when_overlay_disabled(self):
        """on_overlay_tick does nothing when overlay is off."""
        h = _make_handler()
        h._lcd.overlay.enabled = False
        h._lcd.video.playing = True
        metrics = MagicMock()
        h.on_overlay_tick(metrics)
        h._rebuild_debounce_timer.start.assert_not_called()

    def test_update_preview_sets_preview_image(self):
        """update_preview mirrors a frame rendered by tick() to the preview widget."""
        h = _make_handler()
        image = MagicMock()
        h.update_preview(image)
        h._w['preview'].set_image.assert_called_once_with(image)

    def test_overlay_tick_during_video_debounces_cache_rebuild(self):
        h = _make_handler()
        h._lcd.overlay.enabled = True
        h._lcd.video.playing = True
        h._lcd.overlay.has_changed.return_value = True
        metrics = MagicMock()
        h.on_overlay_tick(metrics)
        # rebuild is deferred — debounce timer starts, cache not rebuilt yet
        h._rebuild_debounce_timer.start.assert_called_with(300)
        h._lcd.overlay.rebuild_video_cache.assert_not_called()

    def test_rebuild_debounce_fires_cache_rebuild(self):
        h = _make_handler()
        h._pending_metrics = MagicMock()
        metrics = h._pending_metrics
        h._on_rebuild_debounce()
        h._lcd.overlay.rebuild_video_cache.assert_called_with(metrics)
        assert h._pending_metrics is None

    def test_flash_element_sets_skip_index(self):
        h = _make_handler()
        h._lcd.overlay.render.return_value = {'image': MagicMock()}
        h.flash_element(3)
        assert h._lcd.overlay.service.flash_skip_index == 3
        h._flash_timer.start.assert_called_with(980)


# =========================================================================
# Display settings
# =========================================================================


class TestDisplaySettings:
    """set_brightness, set_rotation, set_split_mode."""

    def test_set_brightness_updates_level(self):
        h = _make_handler()
        h._lcd.set_brightness.return_value = {'success': True, 'image': MagicMock()}
        h.set_brightness(1)
        assert h.brightness_level == 1

    def test_set_brightness_updates_preview(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.set_brightness.return_value = {'success': True, 'image': img}
        h.set_brightness(3)
        h._w['preview'].set_image.assert_called_with(img)

    def test_set_brightness_sends_if_auto_send(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.set_brightness.return_value = {'success': True, 'image': img}
        h._lcd.auto_send = True
        h.set_brightness(2)
        h._lcd.frame.send.assert_called_with(img)

    def test_set_brightness_no_send_if_no_auto(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.set_brightness.return_value = {'success': True, 'image': img}
        h._lcd.auto_send = False
        h.set_brightness(2)
        h._lcd.frame.send.assert_not_called()

    @patch('trcc.gui.lcd_handler.Settings')
    def test_set_rotation_persists(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        h._lcd.set_rotation.return_value = {'success': True, 'image': MagicMock()}
        h.set_rotation(90)
        mock_settings.save_device_setting.assert_called_with('dev0', 'rotation', 90)

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.conf.settings')
    def test_set_rotation_resolves_cloud_dirs(self, mock_conf, mock_settings):
        h = _make_handler()
        h._lcd.set_rotation.return_value = {'success': True}
        h.set_rotation(270)
        mock_conf.resolve_cloud_dirs.assert_called_with(270)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_set_split_mode_updates_state(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        h._lcd.set_split_mode.return_value = {'success': True, 'image': MagicMock()}
        h.set_split_mode(2)
        assert h.split_mode == 2
        mock_settings.save_device_setting.assert_called_with('dev0', 'split_mode', 2)


# =========================================================================
# Background / Screencast
# =========================================================================


class TestBackgroundScreencast:
    """on_background_toggle, on_screencast_frame."""

    def test_background_toggle_on_stops_video(self):
        h = _make_handler()
        h._lcd.overlay.render.return_value = {'image': MagicMock()}
        h.on_background_toggle(True)
        assert h.is_background_active is True
        h._animation_timer.stop.assert_called()
        h._lcd.video.stop.assert_called()

    def test_background_toggle_off(self):
        h = _make_handler()
        h._lcd.overlay.render.return_value = {'image': MagicMock()}
        h.on_background_toggle(False)
        assert h.is_background_active is False

    def test_screencast_frame_sends(self):
        h = _make_handler()
        img = MagicMock()
        h.on_screencast_frame(img)
        h._w['preview'].set_image.assert_called_with(img)
        h._lcd.frame.send.assert_called_with(img)


# =========================================================================
# Save / Export / Import
# =========================================================================


class TestThemeIO:
    """save_theme, export_config, import_config."""

    @patch('trcc.conf.settings')
    @patch('trcc.gui.lcd_handler.Settings')
    def test_save_theme_success(self, mock_settings_cls, mock_conf):
        from trcc.core.commands.lcd import SaveThemeCommand
        h = _make_handler()
        td = MagicMock()
        td.exists.return_value = True
        mock_conf.theme_dir = td
        h.save_theme("MyTheme")
        dispatched = [c.args[0] for c in h._bus.dispatch.call_args_list]
        assert any(isinstance(cmd, SaveThemeCommand) and cmd.name == "MyTheme"
                   for cmd in dispatched)
        h._w['preview'].set_status.assert_called_with('Saved')

    def test_export_config(self):
        from trcc.core.commands.lcd import ExportThemeCommand
        h = _make_handler()
        h.export_config(Path('/out/theme.tr'))
        dispatched = [c.args[0] for c in h._bus.dispatch.call_args_list]
        assert any(isinstance(cmd, ExportThemeCommand) for cmd in dispatched)

    @patch('trcc.conf.settings')
    def test_import_config_success_reloads(self, mock_conf):
        from trcc.core.commands.lcd import ImportThemeCommand
        h = _make_handler()
        td = MagicMock()
        td.exists.return_value = True
        mock_conf.theme_dir = td
        h.import_config(Path('/in/theme.tr'))
        dispatched = [c.args[0] for c in h._bus.dispatch.call_args_list]
        assert any(isinstance(cmd, ImportThemeCommand) for cmd in dispatched)
        h._w['theme_local'].set_theme_directory.assert_called_once()
        h._w['theme_local'].load_themes.assert_called_once()


# =========================================================================
# Render
# =========================================================================


class TestRender:
    """render_and_preview, _render_and_send."""

    def test_render_and_preview_returns_image(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.overlay.render.return_value = {'image': img}
        result = h.render_and_preview()
        assert result is img
        h._w['preview'].set_image.assert_called_with(img)

    def test_render_and_preview_no_image(self):
        h = _make_handler()
        h._lcd.overlay.render.return_value = {}
        result = h.render_and_preview()
        assert result is None


# =========================================================================
# Lifecycle
# =========================================================================


class TestLifecycle:
    """stop_timers, cleanup."""

    def test_stop_timers(self):
        h = _make_handler()
        h.stop_timers()
        h._animation_timer.stop.assert_called()
        h._slideshow_timer.stop.assert_called()

    def test_cleanup(self):
        h = _make_handler()
        h.cleanup()
        h._animation_timer.stop.assert_called()
        h._slideshow_timer.stop.assert_called()
        h._flash_timer.stop.assert_called()
        h._lcd.video.stop.assert_called()
        h._lcd.cleanup.assert_called()
