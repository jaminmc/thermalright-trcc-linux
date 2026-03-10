"""Tests for core/lcd_device.py — LCDDevice application facade."""

import unittest
from unittest.mock import MagicMock, patch

from trcc.core.lcd_device import LCDDevice


def _make_lcd(**overrides) -> LCDDevice:
    """Create LCDDevice with mock services."""
    defaults = {
        'device_svc': MagicMock(),
        'display_svc': MagicMock(),
        'theme_svc': MagicMock(),
        'renderer': MagicMock(),
        'dc_config_cls': MagicMock(),
        'load_config_json_fn': MagicMock(),
    }
    defaults.update(overrides)
    return LCDDevice(**defaults)


# =============================================================================
# Construction
# =============================================================================


class TestLCDDeviceConstruction(unittest.TestCase):
    """LCDDevice construction and self-referencing accessors."""

    def test_capability_accessors_point_to_self(self):
        """frame/video/overlay/theme/settings all point to self."""
        lcd = _make_lcd()
        self.assertIs(lcd.frame, lcd)
        self.assertIs(lcd.video, lcd)
        self.assertIs(lcd.overlay, lcd)
        self.assertIs(lcd.theme, lcd)
        self.assertIs(lcd.settings, lcd)

    def test_stores_injected_services(self):
        svc = MagicMock()
        disp = MagicMock()
        theme = MagicMock()
        lcd = _make_lcd(device_svc=svc, display_svc=disp, theme_svc=theme)
        self.assertIs(lcd._device_svc, svc)
        self.assertIs(lcd._display_svc, disp)
        self.assertIs(lcd._theme_svc, theme)

    def test_default_no_services(self):
        """LCDDevice() with no args starts empty."""
        lcd = LCDDevice()
        self.assertIsNone(lcd._device_svc)
        self.assertIsNone(lcd._display_svc)
        self.assertIsNone(lcd._theme_svc)


# =============================================================================
# Device ABC — connected, device_info, cleanup
# =============================================================================


class TestLCDDeviceABC(unittest.TestCase):
    """Device ABC methods on LCDDevice."""

    def test_connected_true_when_device_selected(self):
        svc = MagicMock()
        svc.selected = MagicMock()  # has a selected device
        lcd = _make_lcd(device_svc=svc)
        self.assertTrue(lcd.connected)

    def test_connected_false_when_no_device_svc(self):
        lcd = LCDDevice()
        self.assertFalse(lcd.connected)

    def test_connected_false_when_no_selected_device(self):
        svc = MagicMock()
        svc.selected = None
        lcd = _make_lcd(device_svc=svc)
        self.assertFalse(lcd.connected)

    def test_device_info_returns_selected(self):
        dev = MagicMock(name='LCD', path='/dev/sg0')
        svc = MagicMock()
        svc.selected = dev
        lcd = _make_lcd(device_svc=svc)
        self.assertIs(lcd.device_info, dev)

    def test_device_info_none_when_no_svc(self):
        lcd = LCDDevice()
        self.assertIsNone(lcd.device_info)

    def test_cleanup_calls_display_svc(self):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        lcd.cleanup()
        disp.cleanup.assert_called_once()

    def test_cleanup_safe_when_no_display_svc(self):
        lcd = LCDDevice()
        lcd.cleanup()  # should not raise


# =============================================================================
# Properties
# =============================================================================


class TestLCDDeviceProperties(unittest.TestCase):
    """LCD-specific properties delegating to services."""

    def test_lcd_size_from_display_svc(self):
        disp = MagicMock()
        disp.lcd_width = 480
        disp.lcd_height = 480
        lcd = _make_lcd(display_svc=disp)
        self.assertEqual(lcd.lcd_size, (480, 480))

    def test_lcd_size_zero_when_no_display_svc(self):
        lcd = LCDDevice()
        self.assertEqual(lcd.lcd_size, (0, 0))

    def test_resolution_equals_lcd_size(self):
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        lcd = _make_lcd(display_svc=disp)
        self.assertEqual(lcd.resolution, lcd.lcd_size)

    def test_device_path_from_device_info(self):
        dev = MagicMock()
        dev.path = '/dev/sg0'
        svc = MagicMock()
        svc.selected = dev
        lcd = _make_lcd(device_svc=svc)
        self.assertEqual(lcd.device_path, '/dev/sg0')

    def test_device_path_none_when_no_device(self):
        lcd = LCDDevice()
        self.assertIsNone(lcd.device_path)

    def test_current_image_delegates_to_display(self):
        disp = MagicMock()
        disp.current_image = 'test_image'
        lcd = _make_lcd(display_svc=disp)
        self.assertEqual(lcd.current_image, 'test_image')

    def test_current_image_setter(self):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        lcd.current_image = 'new_image'
        self.assertEqual(disp.current_image, 'new_image')

    def test_current_image_none_when_no_display(self):
        lcd = LCDDevice()
        self.assertIsNone(lcd.current_image)

    def test_current_theme_path(self):
        disp = MagicMock()
        disp.current_theme_path = '/themes/test'
        lcd = _make_lcd(display_svc=disp)
        self.assertEqual(lcd.current_theme_path, '/themes/test')

    def test_auto_send_default_false(self):
        lcd = LCDDevice()
        self.assertFalse(lcd.auto_send)


# =============================================================================
# Frame operations — send_image, send_color, send
# =============================================================================


class TestLCDDeviceFrame(unittest.TestCase):
    """Frame send operations."""

    def test_send_image_file_not_found(self):
        lcd = _make_lcd()
        result = lcd.send_image('/nonexistent/test.png')
        self.assertFalse(result['success'])
        self.assertIn('not found', result['error'])

    @patch('trcc.core.lcd_device.os.path.exists', return_value=True)
    @patch('trcc.services.image.ImageService.open_and_resize')
    def test_send_image_success(self, mock_resize, mock_exists):
        """send_image with valid path delegates to device service."""
        mock_resize.return_value = MagicMock()
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        lcd = _make_lcd(display_svc=disp)
        result = lcd.send_image('/tmp/test.png')
        self.assertTrue(result['success'])
        lcd._device_svc.send_pil.assert_called_once()

    @patch('trcc.services.image.ImageService.solid_color')
    def test_send_color_delegates(self, mock_solid):
        mock_solid.return_value = MagicMock()
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        lcd = _make_lcd(display_svc=disp)
        result = lcd.send_color(255, 0, 0)
        self.assertTrue(result['success'])
        lcd._device_svc.send_pil.assert_called_once()

    def test_send_no_device_selected(self):
        svc = MagicMock()
        svc.selected = None
        lcd = _make_lcd(device_svc=svc)
        result = lcd.send(MagicMock())
        self.assertFalse(result['success'])

    def test_send_with_device(self):
        svc = MagicMock()
        svc.selected = MagicMock()
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        lcd = _make_lcd(device_svc=svc, display_svc=disp)
        result = lcd.send(MagicMock())
        self.assertTrue(result['success'])
        svc.send_pil_async.assert_called_once()


# =============================================================================
# Settings — brightness, rotation, split mode, resolution
# =============================================================================


class TestLCDDeviceSettings(unittest.TestCase):
    """Settings operations returning result dicts."""

    @patch.object(LCDDevice, '_persist')
    def test_set_brightness_percent(self, _):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        result = lcd.set_brightness(75)
        self.assertTrue(result['success'])
        disp.set_brightness.assert_called_once_with(75)

    @patch.object(LCDDevice, '_persist')
    def test_set_brightness_level_1(self, _):
        """Level 1 → 25%."""
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        result = lcd.set_brightness(1)
        self.assertTrue(result['success'])
        disp.set_brightness.assert_called_once_with(25)

    @patch.object(LCDDevice, '_persist')
    def test_set_brightness_level_3(self, _):
        """Level 3 → 100%."""
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        result = lcd.set_brightness(3)
        self.assertTrue(result['success'])
        disp.set_brightness.assert_called_once_with(100)

    def test_set_brightness_invalid(self):
        lcd = _make_lcd()
        result = lcd.set_brightness(-5)
        self.assertFalse(result['success'])

    @patch.object(LCDDevice, '_persist')
    def test_set_rotation_valid(self, _):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        for deg in (0, 90, 180, 270):
            with self.subTest(deg=deg):
                result = lcd.set_rotation(deg)
                self.assertTrue(result['success'])

    def test_set_rotation_invalid(self):
        lcd = _make_lcd()
        result = lcd.set_rotation(45)
        self.assertFalse(result['success'])

    @patch.object(LCDDevice, '_persist')
    def test_set_split_mode_valid(self, _):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        for mode in (0, 1, 2, 3):
            with self.subTest(mode=mode):
                result = lcd.set_split_mode(mode)
                self.assertTrue(result['success'])

    def test_set_split_mode_invalid(self):
        lcd = _make_lcd()
        result = lcd.set_split_mode(5)
        self.assertFalse(result['success'])


# =============================================================================
# Overlay operations
# =============================================================================


class TestLCDDeviceOverlay(unittest.TestCase):
    """Overlay enable/disable/config operations."""

    def test_enable_overlay(self):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        result = lcd.enable(True)
        self.assertTrue(result['success'])

    def test_set_config(self):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        result = lcd.set_config({'key': 'val'})
        self.assertTrue(result['success'])


if __name__ == '__main__':
    unittest.main()
