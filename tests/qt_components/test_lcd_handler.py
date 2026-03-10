"""Tests for qt_components/lcd_handler.py — LCDHandler lifecycle and routing.

Covers:
- Construction, properties, widget dict wiring
- apply_device_config: brightness, rotation, split mode restoration
- Theme selection: path-based, cloud, animated, persist flag
- Mask application: apply_mask, persist mask_path
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

from trcc.qt_components.lcd_handler import LCDHandler

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
    lcd.frame.send.return_value = {'success': True}
    lcd.frame.reset.return_value = {'success': True, 'message': 'Reset'}
    lcd.overlay.render.return_value = {'image': MagicMock()}
    lcd.overlay.service = MagicMock()
    lcd.device_service = MagicMock()
    return lcd


def _make_handler(**overrides) -> LCDHandler:
    """Create LCDHandler with all mocks."""
    kw = {
        'lcd': _make_lcd(),
        'widgets': _make_widgets(),
        'make_timer': _make_timer_fn(),
        'data_dir': Path('/tmp/trcc-test'),
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
        assert h.brightness_level == 2

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

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_sets_device_key(self, mock_settings):
        mock_settings.device_config_key.return_value = 'test_key'
        mock_settings.get_device_config.return_value = {}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        assert h.device_key == 'test_key'

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_restores_brightness(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {'brightness_level': 1}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        assert h.brightness_level == 1
        h._lcd.settings.set_brightness.assert_called_with(1)

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_restores_rotation(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {'rotation': 90}
        h = _make_handler()
        h.apply_device_config(self._device(), 320, 320)
        h._lcd.settings.set_rotation.assert_called_with(90)
        h._w['rotation_combo'].setCurrentIndex.assert_called_with(1)

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_resolution_change_updates_widgets(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        lcd = _make_lcd()
        lcd.lcd_size = (320, 320)
        h = _make_handler(lcd=lcd)
        h.apply_device_config(self._device(), 480, 480)
        lcd.settings.set_resolution.assert_called_with(480, 480)
        h._w['preview'].set_resolution.assert_called_with(480, 480)

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_same_resolution_skips_update(self, mock_settings):
        mock_settings.device_config_key.return_value = 'k'
        mock_settings.get_device_config.return_value = {}
        lcd = _make_lcd()
        lcd.lcd_size = (320, 320)
        h = _make_handler(lcd=lcd)
        h.apply_device_config(self._device(), 320, 320)
        lcd.settings.set_resolution.assert_not_called()

    @patch('trcc.qt_components.lcd_handler.Settings')
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

    @patch('trcc.qt_components.lcd_handler.Settings')
    @patch('trcc.qt_components.lcd_handler.ThemeInfo')
    def test_select_theme_from_path_calls_select(self, mock_ti, mock_settings):
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

        h.select_theme_from_path(path)
        h._lcd.theme.select.assert_called_once()

    def test_select_theme_nonexistent_path_noop(self):
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = False
        h.select_theme_from_path(path)
        h._lcd.theme.select.assert_not_called()

    @patch('trcc.qt_components.lcd_handler.Settings')
    @patch('trcc.qt_components.lcd_handler.ThemeInfo')
    def test_select_theme_stops_video(self, mock_ti, mock_settings):
        mock_ti.from_directory.return_value = MagicMock()
        h = _make_handler()
        path = MagicMock(spec=Path)
        path.exists.return_value = True
        path.__truediv__ = lambda self, x: MagicMock(exists=lambda: False)

        h.select_theme_from_path(path)
        h._lcd.video.stop.assert_called_once()

    @patch('trcc.qt_components.lcd_handler.Settings')
    @patch('trcc.qt_components.lcd_handler.ThemeInfo')
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

    @patch('trcc.qt_components.lcd_handler.Settings')
    @patch('trcc.qt_components.lcd_handler.ThemeInfo')
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

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_apply_mask_with_path(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        mask_info = MagicMock()
        mask_info.path = '/masks/01'
        h._lcd.load_mask_standalone.return_value = {
            'success': True, 'image': MagicMock()}
        h.apply_mask(mask_info)
        h._lcd.load_mask_standalone.assert_called_once()
        h._w['preview'].set_image.assert_called_once()
        mock_settings.save_device_setting.assert_called_with(
            'dev0', 'mask_path', '/masks/01')

    def test_apply_mask_no_path_sets_status(self):
        h = _make_handler()
        mask_info = MagicMock()
        mask_info.path = None
        mask_info.name = "Empty"
        h.apply_mask(mask_info)
        h._w['preview'].set_status.assert_called_once()


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

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_overlay_changed_sets_config(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        h._lcd.overlay.enabled = False
        h._w['theme_setting'].overlay_grid.overlay_enabled = True
        data = {'elements': []}
        h.on_overlay_changed(data)
        h._lcd.overlay.enable.assert_called_with(True)
        h._lcd.overlay.set_config.assert_called_with(data)

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_overlay_changed_empty_data_noop(self, mock_settings):
        h = _make_handler()
        h.on_overlay_changed({})
        h._lcd.overlay.set_config.assert_not_called()

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_overlay_changed_none_data_noop(self, mock_settings):
        h = _make_handler()
        h.on_overlay_changed(None)
        h._lcd.overlay.set_config.assert_not_called()

    @patch('trcc.qt_components.lcd_handler.Settings')
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

    def test_overlay_tick_no_change_noop(self):
        h = _make_handler()
        h._lcd.overlay.has_changed.return_value = False
        h._lcd.video.playing = False
        metrics = MagicMock()
        h.on_overlay_tick(metrics)
        h._lcd.overlay.update_metrics.assert_called_with(metrics)
        # No render since nothing changed
        h._lcd.overlay.render.assert_not_called()

    def test_overlay_tick_with_change_renders(self):
        h = _make_handler()
        h._lcd.overlay.has_changed.return_value = True
        h._lcd.video.playing = False
        h._lcd.overlay.render.return_value = {'image': MagicMock()}
        metrics = MagicMock()
        h.on_overlay_tick(metrics)
        h._lcd.overlay.render.assert_called_once()

    def test_overlay_tick_during_video_rebuilds_cache(self):
        h = _make_handler()
        h._lcd.video.playing = True
        h._lcd.overlay.has_changed.return_value = True
        metrics = MagicMock()
        h.on_overlay_tick(metrics)
        h._lcd.overlay.rebuild_video_cache.assert_called_with(metrics)

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
        h._lcd.settings.set_brightness.return_value = {
            'success': True, 'image': MagicMock()}
        h.set_brightness(1)
        assert h.brightness_level == 1

    def test_set_brightness_updates_preview(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.settings.set_brightness.return_value = {
            'success': True, 'image': img}
        h.set_brightness(3)
        h._w['preview'].set_image.assert_called_with(img)

    def test_set_brightness_sends_if_auto_send(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.settings.set_brightness.return_value = {
            'success': True, 'image': img}
        h._lcd.auto_send = True
        h.set_brightness(2)
        h._lcd.frame.send.assert_called_with(img)

    def test_set_brightness_no_send_if_no_auto(self):
        h = _make_handler()
        img = MagicMock()
        h._lcd.settings.set_brightness.return_value = {
            'success': True, 'image': img}
        h._lcd.auto_send = False
        h.set_brightness(2)
        h._lcd.frame.send.assert_not_called()

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_set_rotation_persists(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        h._lcd.settings.set_rotation.return_value = {
            'success': True, 'image': MagicMock()}
        h.set_rotation(90)
        mock_settings.save_device_setting.assert_called_with('dev0', 'rotation', 90)

    @patch('trcc.qt_components.lcd_handler.Settings')
    @patch('trcc.qt_components.lcd_handler.settings')
    def test_set_rotation_resolves_cloud_dirs(self, mock_conf, mock_settings):
        h = _make_handler()
        h._lcd.settings.set_rotation.return_value = {'success': True}
        h.set_rotation(270)
        mock_conf.resolve_cloud_dirs.assert_called_with(270)

    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_set_split_mode_updates_state(self, mock_settings):
        h = _make_handler()
        h._device_key = 'dev0'
        h._lcd.settings.set_split_mode.return_value = {
            'success': True, 'image': MagicMock()}
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

    @patch('trcc.qt_components.lcd_handler.settings')
    @patch('trcc.qt_components.lcd_handler.Settings')
    def test_save_theme_success(self, mock_settings_cls, mock_conf):
        h = _make_handler()
        td = MagicMock()
        td.exists.return_value = True
        mock_conf.theme_dir = td
        h._lcd.theme.save.return_value = {'success': True, 'message': 'Saved'}
        h.save_theme("MyTheme")
        h._lcd.theme.save.assert_called_once_with("MyTheme", h._data_dir)
        h._w['preview'].set_status.assert_called_with('Saved')

    def test_export_config(self):
        h = _make_handler()
        h.export_config(Path('/out/theme.tr'))
        h._lcd.theme.export_config.assert_called_once_with(Path('/out/theme.tr'))

    @patch('trcc.qt_components.lcd_handler.settings')
    def test_import_config_success_reloads(self, mock_conf):
        h = _make_handler()
        td = MagicMock()
        td.exists.return_value = True
        mock_conf.theme_dir = td
        h._lcd.theme.import_config.return_value = {
            'success': True, 'message': 'Imported'}
        h.import_config(Path('/in/theme.tr'))
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
