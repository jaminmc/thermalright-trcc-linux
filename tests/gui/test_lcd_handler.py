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

from trcc.core.commands.lcd import (
    EnableOverlayCommand,
    PauseVideoCommand,
    RenderAndSendCommand,
    SendFrameCommand,
    SetBrightnessCommand,
    SetFlashIndexCommand,
    SetMaskPositionCommand,
    StopVideoCommand,
    UpdateVideoCacheTextCommand,
)
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
    """Build a mock LCDDevice.

    Sets the properties the handler reads directly (enabled, playing,
    has_frames, has_changed, render, interval, last_metrics) plus all the
    method return values that the command handler calls internally.
    """
    lcd = MagicMock()
    lcd.lcd_size = (320, 320)
    lcd.resolution = (320, 320)
    lcd.connected = True
    lcd.auto_send = True
    lcd.current_theme_path = None

    # Properties the handler reads directly (no sub-object indirection)
    lcd.enabled = False
    lcd.playing = False
    lcd.has_frames = False
    lcd.interval = 33
    lcd.last_metrics = None
    lcd.has_changed.return_value = False

    # render() is called directly by render_and_preview()
    lcd.render.return_value = {'image': MagicMock()}

    # Methods called by command handlers wired through _make_bus
    lcd.load_overlay_config_from_dir.return_value = None
    lcd.set_brightness.return_value = {'success': True, 'message': 'OK'}
    lcd.set_rotation.return_value = {'success': True, 'message': 'OK'}
    lcd.set_split_mode.return_value = {'success': True, 'message': 'OK'}
    lcd.set_resolution.return_value = {'success': True}
    lcd.select.return_value = {'image': MagicMock(), 'is_animated': False}
    lcd.save.return_value = {'success': True, 'message': 'Saved'}
    lcd.export_config.return_value = {'success': True, 'message': 'Exported'}
    lcd.import_config.return_value = {'success': True, 'message': 'Imported'}
    lcd.set_config.return_value = {'success': True, 'message': 'Config set'}
    lcd.enable.return_value = {'success': True, 'enabled': True}
    lcd.enable_overlay.return_value = {'success': True}
    lcd.pause.return_value = {'state': 'paused'}
    lcd.stop.return_value = {'success': True}
    lcd.seek.return_value = {'success': True}
    lcd.set_fit_mode.return_value = {'success': True, 'image': None}
    lcd.rebuild_video_cache.return_value = {'success': True}
    lcd.set_flash_index.return_value = {'success': True}
    lcd.set_mask_position.return_value = {'success': True}
    lcd.render_and_send.return_value = {'success': True, 'image': MagicMock()}
    lcd.send.return_value = None
    lcd.load_mask_standalone.return_value = {'success': True, 'image': None}
    lcd.restore_last_theme.return_value = {'success': False, 'error': 'No saved theme'}

    lcd.device_service = MagicMock()
    return lcd


def _make_bus(lcd: MagicMock | None = None) -> MagicMock:
    """Mock CommandBus whose dispatch returns a result wrapping the device call."""
    from trcc.core.command_bus import CommandResult

    bus = MagicMock()
    _lcd = lcd or _make_lcd()

    def _dispatch(cmd: object) -> CommandResult:
        from trcc.core.commands.lcd import (
            EnableOverlayCommand,
            ExportThemeCommand,
            ImportThemeCommand,
            LoadMaskCommand,
            PauseVideoCommand,
            RenderAndSendCommand,
            RestoreLastThemeCommand,
            SaveThemeCommand,
            SeekVideoCommand,
            SelectThemeCommand,
            SendColorCommand,
            SendFrameCommand,
            SetBrightnessCommand,
            SetFlashIndexCommand,
            SetMaskPositionCommand,
            SetOverlayConfigCommand,
            SetResolutionCommand,
            SetRotationCommand,
            SetSplitModeCommand,
            SetVideoFitModeCommand,
            StopVideoCommand,
            UpdateVideoCacheTextCommand,
        )
        if isinstance(cmd, SetBrightnessCommand):
            return CommandResult.from_dict(_lcd.set_brightness(cmd.level))
        if isinstance(cmd, SetRotationCommand):
            return CommandResult.from_dict(_lcd.set_rotation(cmd.degrees))
        if isinstance(cmd, SetSplitModeCommand):
            return CommandResult.from_dict(_lcd.set_split_mode(cmd.mode))
        if isinstance(cmd, SetResolutionCommand):
            return CommandResult.from_dict(_lcd.set_resolution(cmd.width, cmd.height))
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
            return CommandResult.from_dict(_lcd.enable_overlay(cmd.on))
        if isinstance(cmd, StopVideoCommand):
            return CommandResult.from_dict(_lcd.stop())
        if isinstance(cmd, PauseVideoCommand):
            return CommandResult.from_dict(_lcd.pause())
        if isinstance(cmd, SeekVideoCommand):
            return CommandResult.from_dict(_lcd.seek(cmd.percent))
        if isinstance(cmd, SetVideoFitModeCommand):
            return CommandResult.from_dict(_lcd.set_fit_mode(cmd.mode))
        if isinstance(cmd, UpdateVideoCacheTextCommand):
            return CommandResult.from_dict(_lcd.rebuild_video_cache(cmd.metrics))
        if isinstance(cmd, SetFlashIndexCommand):
            return CommandResult.from_dict(_lcd.set_flash_index(cmd.index))
        if isinstance(cmd, SetMaskPositionCommand):
            return CommandResult.from_dict(_lcd.set_mask_position(cmd.x, cmd.y))
        if isinstance(cmd, SendFrameCommand):
            _lcd.send(cmd.image)
            return CommandResult.ok(message="Frame sent")
        if isinstance(cmd, RenderAndSendCommand):
            return CommandResult.from_dict(_lcd.render_and_send(cmd.skip_if_video))
        if isinstance(cmd, SendColorCommand):
            return CommandResult.ok(message="Color sent")
        return CommandResult.ok(message="ok")

    bus.dispatch.side_effect = _dispatch
    return bus


def _dispatched(handler: LCDHandler, cmd_type: type) -> list:
    """Return all commands of cmd_type dispatched through the bus."""
    return [c.args[0] for c in handler._bus.dispatch.call_args_list
            if isinstance(c.args[0], cmd_type)]


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
        assert h.brightness_level == 100  # DEFAULT_BRIGHTNESS_LEVEL = 100%

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

    def test_three_timers_created(self):
        calls = []
        def track_timer(cb, single_shot=False):
            calls.append((cb, single_shot))
            return MagicMock(spec=QTimer)
        _make_handler(make_timer=track_timer)
        assert len(calls) == 3
        # Flash timer is single_shot
        assert calls[2][1] is True


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
        """Stored percent value restored directly — no level mapping."""
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {'brightness_level': 50}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        assert h.brightness_level == 50
        cmds = _dispatched(h, SetBrightnessCommand)
        assert cmds and cmds[0].level == 50

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
# _update_theme_directories — first-install auto-load guard
# =========================================================================


class TestUpdateThemeDirectories:
    """_update_theme_directories first-install auto-load and skip-if-saved-theme guard."""

    def _make_theme_dir(self, tmp_path: Path) -> MagicMock:
        """Build a mock ThemeDir with one valid theme subfolder."""
        theme1 = tmp_path / 'Theme1'
        theme1.mkdir()
        (theme1 / '00.png').touch()

        td = MagicMock()
        td.exists.return_value = True
        td.path = tmp_path
        return td

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler._conf')
    def test_auto_loads_first_theme_on_first_install(self, mock_conf, mock_settings, tmp_path):
        """With no current image and no saved theme_path, auto-loads the first theme folder."""
        from trcc.core.commands.lcd import SelectThemeCommand

        td = self._make_theme_dir(tmp_path)
        mock_conf.settings.width = 320
        mock_conf.settings.height = 320
        mock_conf.settings.theme_dir = td
        mock_conf.settings.web_dir = None
        mock_conf.settings.masks_dir = None

        mock_settings.get_device_config.return_value = {}  # no saved theme_path

        lcd = _make_lcd()
        lcd.current_image = None  # no image loaded yet

        with patch('trcc.gui.lcd_handler.ThemeInfo') as mock_ti:
            mock_ti.from_directory.return_value = MagicMock()
            h = _make_handler(lcd=lcd)
            h._device_key = 'dev0'
            h._update_theme_directories()

        assert _dispatched(h, SelectThemeCommand), "Should auto-load first theme on first install"

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler._conf')
    def test_skips_auto_load_when_saved_theme_exists(self, mock_conf, mock_settings, tmp_path):
        """With no current image but a saved theme_path, skips auto-load to preserve user selection."""
        from trcc.core.commands.lcd import SelectThemeCommand

        td = self._make_theme_dir(tmp_path)
        mock_conf.settings.width = 320
        mock_conf.settings.height = 320
        mock_conf.settings.theme_dir = td
        mock_conf.settings.web_dir = None
        mock_conf.settings.masks_dir = None

        # User has a saved theme — must not overwrite it
        mock_settings.get_device_config.return_value = {'theme_path': '/themes/MyTheme'}

        lcd = _make_lcd()
        lcd.current_image = None

        h = _make_handler(lcd=lcd)
        h._device_key = 'dev0'
        h._update_theme_directories()

        assert not _dispatched(h, SelectThemeCommand), \
            "Must not auto-load theme1 when user already has a saved theme_path"

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler._conf')
    def test_skips_auto_load_when_image_already_showing(self, mock_conf, mock_settings, tmp_path):
        """With a current image already loaded, skips auto-load regardless of saved config."""
        from trcc.core.commands.lcd import SelectThemeCommand

        td = self._make_theme_dir(tmp_path)
        mock_conf.settings.width = 320
        mock_conf.settings.height = 320
        mock_conf.settings.theme_dir = td
        mock_conf.settings.web_dir = None
        mock_conf.settings.masks_dir = None
        mock_settings.get_device_config.return_value = {}

        lcd = _make_lcd()
        lcd.current_image = MagicMock()  # image already showing

        h = _make_handler(lcd=lcd)
        h._device_key = 'dev0'
        h._update_theme_directories()

        assert not _dispatched(h, SelectThemeCommand), \
            "Must not auto-load when current_image is already set"


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
        assert _dispatched(h, SelectThemeCommand)

    def test_select_theme_nonexistent_path_noop(self):
        from trcc.core.commands.lcd import SelectThemeCommand
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = False
        h.select_theme_from_path(path)
        assert not _dispatched(h, SelectThemeCommand)

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler.ThemeInfo')
    def test_select_theme_stops_video(self, mock_ti, mock_settings):
        """Theme selection dispatches StopVideoCommand through the bus."""
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

        h.select_theme_from_path(path)
        assert _dispatched(h, StopVideoCommand)

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

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler.ThemeInfo')
    def test_no_double_send_when_overlay_follows(self, mock_ti, mock_settings):
        """select_theme_from_path must not dispatch SendFrameCommand when
        overlay config will follow — avoids double-send blink on theme switch."""
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)
        # overlay_config=True (default) and load_overlay_config_from_dir returns None
        # (theme has no overlay) — still must not SendFrameCommand; RenderAndSend owns the send
        h._lcd.load_overlay_config_from_dir.return_value = None

        h.select_theme_from_path(path)

        assert not _dispatched(h, SendFrameCommand), (
            "SendFrameCommand must not fire when overlay_config=True — "
            "_load_theme_overlay_config owns the single send to avoid blink"
        )

    @patch('trcc.gui.lcd_handler.Settings')
    @patch('trcc.gui.lcd_handler.ThemeInfo')
    def test_single_render_and_send_on_theme_switch(self, mock_ti, mock_settings):
        """Exactly one RenderAndSendCommand on a normal theme switch with overlay config."""
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)
        # Theme has an overlay config — full overlay path
        h._lcd.load_overlay_config_from_dir.return_value = {'elements': []}

        h.select_theme_from_path(path)

        renders = _dispatched(h, RenderAndSendCommand)
        sends = _dispatched(h, SendFrameCommand)
        assert len(renders) == 1, f"Expected 1 RenderAndSendCommand, got {len(renders)}"
        assert len(sends) == 0, f"Expected 0 SendFrameCommand, got {len(sends)}"


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
        assert _dispatched(h, LoadMaskCommand)
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
        assert _dispatched(h, RestoreLastThemeCommand)

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

    @patch('trcc.gui.lcd_handler.Settings')
    def test_restore_starts_animation_timer_for_video_theme(self, mock_settings):
        """apply_device_config starts animation timer when restoring a video theme."""
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        lcd = _make_lcd()
        lcd.playing = True
        img = MagicMock()
        lcd.restore_last_theme.return_value = {
            'success': True, 'image': img, 'is_animated': True,
            'overlay_config': None, 'overlay_enabled': False,
        }
        h = _make_handler(lcd=lcd)
        h.apply_device_config(
            MagicMock(device_index=0, vid=0x0402, pid=0x3922), 320, 320)
        h._animation_timer.start.assert_called_with(33)  # lcd.interval = 33
        h._w['preview'].set_playing.assert_called_with(True)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_restore_no_animation_timer_for_static_theme(self, mock_settings):
        """apply_device_config does NOT start animation timer for a static theme."""
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        lcd = _make_lcd()
        lcd.playing = False
        img = MagicMock()
        lcd.restore_last_theme.return_value = {
            'success': True, 'image': img, 'is_animated': False,
            'overlay_config': None, 'overlay_enabled': True,
        }
        h = _make_handler(lcd=lcd)
        h.apply_device_config(
            MagicMock(device_index=0, vid=0x0402, pid=0x3922), 320, 320)
        h._animation_timer.start.assert_not_called()


# =========================================================================
# Video
# =========================================================================


class TestVideo:
    """play_pause, stop, seek, tick."""

    def test_play_pause_toggles(self):
        """play_pause dispatches PauseVideoCommand; result state drives timer."""
        lcd = _make_lcd()
        lcd.pause.return_value = {'state': 'playing', 'success': True}
        h = _make_handler(lcd=lcd)
        h.play_pause()
        assert _dispatched(h, PauseVideoCommand)
        h._w['preview'].set_playing.assert_called_with(True)
        h._animation_timer.start.assert_called_with(33)  # lcd.interval = 33

    def test_play_pause_pauses(self):
        """play_pause dispatches PauseVideoCommand; paused state stops timer."""
        lcd = _make_lcd()
        lcd.pause.return_value = {'state': 'paused', 'success': True}
        h = _make_handler(lcd=lcd)
        h.play_pause()
        h._w['preview'].set_playing.assert_called_with(False)
        h._animation_timer.stop.assert_called()

    def test_stop_video_dispatches_command(self):
        """stop_video dispatches StopVideoCommand through the bus."""
        h = _make_handler()
        h.stop_video()
        assert _dispatched(h, StopVideoCommand)
        h._animation_timer.stop.assert_called()
        h._w['preview'].set_playing.assert_called_with(False)
        h._w['preview'].show_video_controls.assert_called_with(False)

    def test_seek_dispatches_command(self):
        """seek dispatches SeekVideoCommand with correct percent."""
        from trcc.core.commands.lcd import SeekVideoCommand
        h = _make_handler()
        h.seek(50.0)
        cmds = _dispatched(h, SeekVideoCommand)
        assert cmds and cmds[0].percent == 50.0


# =========================================================================
# Overlay
# =========================================================================


class TestOverlay:
    """on_overlay_changed, on_overlay_tick, flash_element."""

    @patch('trcc.gui.lcd_handler.Settings')
    def test_overlay_changed_dispatches_enable_and_config(self, mock_settings):
        from trcc.core.commands.lcd import SetOverlayConfigCommand
        h = _make_handler()
        h._device_key = 'dev0'
        h._lcd.enabled = False  # overlay disabled — should trigger EnableOverlayCommand
        h._w['theme_setting'].overlay_grid.overlay_enabled = True
        data = {'elements': []}
        h.on_overlay_changed(data)
        assert _dispatched(h, EnableOverlayCommand)
        cmds = _dispatched(h, SetOverlayConfigCommand)
        assert cmds and cmds[0].config == data

    @patch('trcc.gui.lcd_handler.Settings')
    def test_overlay_changed_empty_data_noop(self, mock_settings):
        from trcc.core.commands.lcd import SetOverlayConfigCommand
        h = _make_handler()
        h.on_overlay_changed({})
        assert not _dispatched(h, SetOverlayConfigCommand)

    @patch('trcc.gui.lcd_handler.Settings')
    def test_overlay_changed_none_data_noop(self, mock_settings):
        from trcc.core.commands.lcd import SetOverlayConfigCommand
        h = _make_handler()
        h.on_overlay_changed(None)
        assert not _dispatched(h, SetOverlayConfigCommand)

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

    def test_overlay_tick_no_overlay_no_send(self):
        """on_overlay_tick must NOT send for static no-overlay themes.

        Sending every refresh cycle (1–5 s) causes visible blinking.
        Static themes don't change — no periodic resend needed.
        """
        h = _make_handler()
        h._lcd.playing = False
        h._lcd.enabled = False
        h._lcd.connected = True
        h.on_overlay_tick(MagicMock())
        assert not _dispatched(h, RenderAndSendCommand)
        assert not _dispatched(h, UpdateVideoCacheTextCommand)

    def test_overlay_tick_overlay_enabled_no_send(self):
        """on_overlay_tick must NOT send when overlay is enabled.

        LCDDevice.tick() (background thread) renders+sends whenever metrics
        change. If on_overlay_tick also sends, every refresh cycle causes two
        frames to hit the device — visible as a blink/flicker.
        """
        h = _make_handler()
        h._lcd.playing = False
        h._lcd.enabled = True
        h._lcd.connected = True
        h.on_overlay_tick(MagicMock())
        assert not _dispatched(h, RenderAndSendCommand), (
            "on_overlay_tick must not send when overlay is enabled — "
            "tick() owns the send to avoid double-send blink"
        )
        assert not _dispatched(h, UpdateVideoCacheTextCommand)

    def test_overlay_tick_noop_when_disconnected(self):
        """on_overlay_tick does nothing when device is not connected."""
        h = _make_handler()
        h._lcd.playing = False
        h._lcd.connected = False
        h.on_overlay_tick(MagicMock())
        assert not _dispatched(h, RenderAndSendCommand)
        assert not _dispatched(h, UpdateVideoCacheTextCommand)

    def test_update_preview_sets_preview_image(self):
        """update_preview mirrors a frame rendered by tick() to the preview widget."""
        h = _make_handler()
        image = MagicMock()
        h.update_preview(image)
        h._w['preview'].set_image.assert_called_once_with(image)

    def test_overlay_tick_during_video_dispatches_update_cache_text(self):
        """on_overlay_tick while video plays dispatches UpdateVideoCacheTextCommand directly."""
        h = _make_handler()
        h._lcd.enabled = True
        h._lcd.playing = True
        metrics = MagicMock()
        h.on_overlay_tick(metrics)
        cmds = _dispatched(h, UpdateVideoCacheTextCommand)
        assert cmds and cmds[0].metrics is metrics

    def test_overlay_tick_video_no_render_and_send(self):
        """on_overlay_tick while video plays must not dispatch RenderAndSendCommand."""
        h = _make_handler()
        h._lcd.enabled = True
        h._lcd.playing = True
        h.on_overlay_tick(MagicMock())
        assert not _dispatched(h, RenderAndSendCommand)

    def test_flash_element_dispatches_set_flash_index(self):
        """flash_element dispatches SetFlashIndexCommand with the correct index."""
        h = _make_handler()
        h.flash_element(3)
        cmds = _dispatched(h, SetFlashIndexCommand)
        assert cmds and cmds[0].index == 3
        h._flash_timer.start.assert_called_with(980)

    def test_flash_timeout_clears_flash_index(self):
        """_on_flash_timeout dispatches SetFlashIndexCommand(index=-1)."""
        h = _make_handler()
        h._on_flash_timeout()
        cmds = _dispatched(h, SetFlashIndexCommand)
        assert cmds and cmds[0].index == -1

    def test_update_mask_position_dispatches_command(self):
        """update_mask_position dispatches SetMaskPositionCommand."""
        h = _make_handler()
        h.update_mask_position(10, 20)
        cmds = _dispatched(h, SetMaskPositionCommand)
        assert cmds and cmds[0].x == 10 and cmds[0].y == 20


# =========================================================================
# Display settings
# =========================================================================


class TestDisplaySettings:
    """set_brightness, set_rotation, set_split_mode."""

    def test_set_brightness_updates_level(self):
        h = _make_handler()
        h._lcd.set_brightness.return_value = {'success': True, 'image': MagicMock()}
        h.set_brightness(50)
        assert h.brightness_level == 50

    def test_set_brightness_updates_preview(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.set_brightness.return_value = {'success': True, 'image': img}
        h.set_brightness(3)
        h._w['preview'].set_image.assert_called_with(img)

    def test_set_brightness_sends_frame_if_auto_send(self):
        """set_brightness dispatches SendFrameCommand when auto_send is on."""
        h = _make_handler()
        img = MagicMock()
        h._lcd.set_brightness.return_value = {'success': True, 'image': img}
        h._lcd.auto_send = True
        h.set_brightness(2)
        cmds = _dispatched(h, SendFrameCommand)
        assert cmds and cmds[0].image is img

    def test_set_brightness_no_send_if_no_auto(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.set_brightness.return_value = {'success': True, 'image': img}
        h._lcd.auto_send = False
        h.set_brightness(2)
        assert not _dispatched(h, SendFrameCommand)

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
        """Background toggle dispatches StopVideoCommand through the bus."""
        h = _make_handler()
        h.on_background_toggle(True)
        assert h.is_background_active is True
        h._animation_timer.stop.assert_called()
        assert _dispatched(h, StopVideoCommand)

    def test_background_toggle_off(self):
        h = _make_handler()
        h.on_background_toggle(False)
        assert h.is_background_active is False

    def test_screencast_frame_dispatches_send_frame(self):
        """on_screencast_frame dispatches SendFrameCommand."""
        h = _make_handler()
        img = MagicMock()
        h.on_screencast_frame(img)
        h._w['preview'].set_image.assert_called_with(img)
        cmds = _dispatched(h, SendFrameCommand)
        assert cmds and cmds[0].image is img


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
        cmds = _dispatched(h, SaveThemeCommand)
        assert cmds and cmds[0].name == "MyTheme"
        h._w['preview'].set_status.assert_called_with('Saved')

    def test_export_config(self):
        from trcc.core.commands.lcd import ExportThemeCommand
        h = _make_handler()
        h.export_config(Path('/out/theme.tr'))
        assert _dispatched(h, ExportThemeCommand)

    @patch('trcc.conf.settings')
    def test_import_config_success_reloads(self, mock_conf):
        from trcc.core.commands.lcd import ImportThemeCommand
        h = _make_handler()
        td = MagicMock()
        td.exists.return_value = True
        mock_conf.theme_dir = td
        h.import_config(Path('/in/theme.tr'))
        assert _dispatched(h, ImportThemeCommand)
        h._w['theme_local'].set_theme_directory.assert_called_once()
        h._w['theme_local'].load_themes.assert_called_once()


# =========================================================================
# Render
# =========================================================================


class TestRender:
    """render_and_preview, _render_and_send."""

    def test_render_and_preview_returns_image(self):
        """render_and_preview calls lcd.render() directly (read-only, no bus)."""
        h = _make_handler()
        img = MagicMock()
        h._lcd.render.return_value = {'image': img}
        result = h.render_and_preview()
        assert result is img
        h._w['preview'].set_image.assert_called_with(img)

    def test_render_and_preview_no_image(self):
        h = _make_handler()
        h._lcd.render.return_value = {}
        result = h.render_and_preview()
        assert result is None

    def test_render_and_send_dispatches_command(self):
        """_render_and_send dispatches RenderAndSendCommand and updates preview."""
        h = _make_handler()
        img = MagicMock()
        h._lcd.render_and_send.return_value = {'success': True, 'image': img}
        h._render_and_send()
        assert _dispatched(h, RenderAndSendCommand)
        h._w['preview'].set_image.assert_called_with(img)


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

    def test_cleanup_dispatches_stop_video(self):
        """cleanup dispatches StopVideoCommand — ensures video state is consistent."""
        h = _make_handler()
        h.cleanup()
        h._animation_timer.stop.assert_called()
        h._slideshow_timer.stop.assert_called()
        h._flash_timer.stop.assert_called()
        assert _dispatched(h, StopVideoCommand)
        h._lcd.cleanup.assert_called()
