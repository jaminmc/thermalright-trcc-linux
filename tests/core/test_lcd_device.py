"""Tests for core/lcd_device.py — LCDDevice application facade."""

import unittest
from unittest.mock import MagicMock, patch

import pytest

from trcc.core.instance import InstanceKind
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


# =============================================================================
# from_service / restore_device_settings / load_last_theme
# =============================================================================


class TestFromService(unittest.TestCase):
    """LCDDevice.from_service() classmethod."""

    def test_from_service_builds_services(self):
        svc = MagicMock()
        with patch.object(LCDDevice, '_build_services') as mock_build:
            lcd = LCDDevice.from_service(svc)
        mock_build.assert_called_once_with(svc)
        self.assertIsInstance(lcd, LCDDevice)


class TestRestoreDeviceSettings(unittest.TestCase):
    """LCDDevice.restore_device_settings()."""

    def test_restores_brightness_and_rotation(self):
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        disp = MagicMock()
        lcd = _make_lcd(device_svc=svc, display_svc=disp)
        with patch('trcc.conf.Settings.device_config_key',
                   return_value="0"), \
             patch('trcc.conf.Settings.get_device_config',
                   return_value={'brightness_level': 1, 'rotation': 90}):
            lcd.restore_device_settings()
        # set_brightness calls DisplayService
        self.assertEqual(disp.set_brightness.call_count, 1)
        self.assertEqual(disp.set_rotation.call_count, 1)

    def test_no_device_does_nothing(self):
        lcd = _make_lcd(device_svc=MagicMock(selected=None))
        lcd.restore_device_settings()  # should not raise


class TestLoadLastTheme(unittest.TestCase):
    """LCDDevice.load_last_theme()."""

    def test_no_theme_path_returns_error(self):
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        lcd = _make_lcd(device_svc=svc)
        with patch('trcc.conf.Settings.device_config_key',
                   return_value="key"), \
             patch('trcc.conf.Settings.get_device_config',
                   return_value={}):
            result = lcd.load_last_theme()
        self.assertFalse(result['success'])
        self.assertIn("No saved theme", result['error'])

    def test_nonexistent_path_returns_error(self):
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        lcd = _make_lcd(device_svc=svc)
        with patch('trcc.conf.Settings.device_config_key',
                   return_value="key"), \
             patch('trcc.conf.Settings.get_device_config',
                   return_value={'theme_path': '/nonexistent/path'}):
            result = lcd.load_last_theme()
        self.assertFalse(result['success'])
        self.assertIn("not found", result['error'])

    def test_image_file_loads(self, ):
        import tempfile
        from pathlib import Path
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        disp = MagicMock()
        disp.load_image_file.return_value = MagicMock()
        lcd = _make_lcd(device_svc=svc, display_svc=disp)
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            tmp = Path(f.name)
        try:
            with patch('trcc.conf.Settings.device_config_key',
                       return_value="key"), \
                 patch('trcc.conf.Settings.get_device_config',
                       return_value={'theme_path': str(tmp)}):
                result = lcd.load_last_theme()
            self.assertTrue(result['success'])
            disp.load_image_file.assert_called_once()
        finally:
            tmp.unlink(missing_ok=True)

    def test_theme_dir_with_00_png(self):
        import tempfile
        from pathlib import Path
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        disp = MagicMock()
        disp.load_image_file.return_value = MagicMock()
        lcd = _make_lcd(device_svc=svc, display_svc=disp)
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "00.png").write_bytes(b"fake")
            with patch('trcc.conf.Settings.device_config_key',
                       return_value="key"), \
                 patch('trcc.conf.Settings.get_device_config',
                       return_value={'theme_path': td}):
                result = lcd.load_last_theme()
            self.assertTrue(result['success'])


# =============================================================================
# load_theme_by_name — routes through discover + select
# =============================================================================


@pytest.fixture
def lcd_with_mocks():
    """LCDDevice with mock services, 320x320 resolution."""
    svc = MagicMock()
    svc.selected = MagicMock(
        resolution=(320, 320), device_index=0, vid=0x0402, pid=0x3922,
    )
    disp = MagicMock()
    disp.lcd_width = 320
    disp.lcd_height = 320
    disp.load_local_theme.return_value = {
        "image": MagicMock(), "is_animated": False,
    }
    disp.get_video_interval.return_value = 0
    theme = MagicMock()
    lcd = _make_lcd(device_svc=svc, display_svc=disp, theme_svc=theme)
    return lcd


class TestLoadThemeByName:
    """LCDDevice.load_theme_by_name — core theme loading by name."""

    @patch("trcc.services.ThemeService.discover_local")
    @patch("trcc.core.models.ThemeDir.for_resolution")
    def test_found_theme_calls_select(self, mock_for_res, mock_discover, lcd_with_mocks):
        from trcc.core.models import ThemeInfo, ThemeType

        theme = ThemeInfo(name="CyberPunk", theme_type=ThemeType.LOCAL)
        mock_for_res.return_value = MagicMock(path="/tmp/themes", __str__=lambda s: "/tmp/themes")
        mock_discover.return_value = [theme]

        result = lcd_with_mocks.load_theme_by_name("CyberPunk")

        assert result["success"] is True
        lcd_with_mocks._theme_svc.select.assert_called_once_with(theme)

    @patch("trcc.services.ThemeService.discover_local", return_value=[])
    @patch("trcc.core.models.ThemeDir.for_resolution",
           return_value=MagicMock(path="/tmp/themes", __str__=lambda s: "/tmp/themes"))
    def test_not_found_returns_error(self, mock_for_res, mock_discover, lcd_with_mocks):
        result = lcd_with_mocks.load_theme_by_name("NonExistent")

        assert result["success"] is False
        assert "not found" in result["error"]

    @patch("trcc.services.ThemeService.discover_local")
    @patch("trcc.core.models.ThemeDir.for_resolution")
    def test_explicit_resolution_overrides_device(self, mock_for_res, mock_discover, lcd_with_mocks):
        mock_for_res.return_value = MagicMock(path="/tmp/themes", __str__=lambda s: "/tmp/themes")
        mock_discover.return_value = []

        lcd_with_mocks.load_theme_by_name("Theme001", 480, 480)

        mock_for_res.assert_called_once_with(480, 480)
        mock_discover.assert_called_once()
        # Second arg is the resolution tuple
        assert mock_discover.call_args[0][1] == (480, 480)

    @patch("trcc.services.ThemeService.discover_local")
    @patch("trcc.core.models.ThemeDir.for_resolution")
    def test_zero_resolution_uses_device_size(self, mock_for_res, mock_discover, lcd_with_mocks):
        mock_for_res.return_value = MagicMock(path="/tmp/themes", __str__=lambda s: "/tmp/themes")
        mock_discover.return_value = []

        lcd_with_mocks.load_theme_by_name("Theme001", 0, 0)

        # Should use device resolution (320, 320)
        mock_for_res.assert_called_once_with(320, 320)

    @patch("trcc.conf.Settings.save_device_setting")
    @patch("trcc.conf.Settings.device_config_key", return_value="0")
    @patch("trcc.services.ThemeService.discover_local")
    @patch("trcc.core.models.ThemeDir.for_resolution")
    def test_sends_static_image_to_device(
        self, mock_for_res, mock_discover, mock_key, mock_save, lcd_with_mocks,
    ):
        """Static theme image is sent to device after select()."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        fake_image = MagicMock()
        theme = ThemeInfo(
            name="Static001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Static001"),
        )
        mock_for_res.return_value = MagicMock(
            path="/tmp/themes", __str__=lambda s: "/tmp/themes")
        mock_discover.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": fake_image, "is_animated": False,
        }

        result = lcd_with_mocks.load_theme_by_name("Static001")

        assert result["success"] is True
        # send_pil_async called (via LCDDevice.send → device_svc.send_pil_async)
        lcd_with_mocks._device_svc.send_pil_async.assert_called_once()

    @patch("trcc.conf.Settings.save_device_setting")
    @patch("trcc.conf.Settings.device_config_key", return_value="0")
    @patch("trcc.services.ThemeService.discover_local")
    @patch("trcc.core.models.ThemeDir.for_resolution")
    def test_does_not_send_animated_theme(
        self, mock_for_res, mock_discover, mock_key, mock_save, lcd_with_mocks,
    ):
        """Animated themes return image but don't call send (caller loops)."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        theme = ThemeInfo(
            name="Video001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Video001"),
        )
        mock_for_res.return_value = MagicMock(
            path="/tmp/themes", __str__=lambda s: "/tmp/themes")
        mock_discover.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": MagicMock(), "is_animated": True,
        }

        result = lcd_with_mocks.load_theme_by_name("Video001")

        assert result["success"] is True
        assert result["is_animated"] is True
        # send_pil_async NOT called — caller handles video loop
        lcd_with_mocks._device_svc.send_pil_async.assert_not_called()

    @patch("trcc.conf.Settings.save_device_setting")
    @patch("trcc.conf.Settings.device_config_key", return_value="0")
    @patch("trcc.services.ThemeService.discover_local")
    @patch("trcc.core.models.ThemeDir.for_resolution")
    def test_persists_theme_path(
        self, mock_for_res, mock_discover, mock_key, mock_save, lcd_with_mocks,
    ):
        """Theme path saved to per-device config, mask cleared."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        theme = ThemeInfo(
            name="Saved001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Saved001"),
        )
        mock_for_res.return_value = MagicMock(
            path="/tmp/themes", __str__=lambda s: "/tmp/themes")
        mock_discover.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": MagicMock(), "is_animated": False,
        }

        lcd_with_mocks.load_theme_by_name("Saved001")

        # theme_path persisted, mask_path cleared
        calls = mock_save.call_args_list
        assert any(
            c.args[1] == 'theme_path' and c.args[2] == str(theme.path)
            for c in calls
        ), f"Expected theme_path save, got: {calls}"
        assert any(
            c.args[1] == 'mask_path' and c.args[2] == ''
            for c in calls
        ), f"Expected mask_path clear, got: {calls}"

    @patch("trcc.conf.Settings.save_device_setting")
    @patch("trcc.conf.Settings.device_config_key", return_value="0")
    @patch("trcc.services.ThemeService.discover_local")
    @patch("trcc.core.models.ThemeDir.for_resolution")
    def test_result_includes_theme_and_config_paths(
        self, mock_for_res, mock_discover, mock_key, mock_save, lcd_with_mocks,
    ):
        """Result dict includes theme_path and config_path for caller."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        dc_path = Path("/tmp/themes/WithDC/config1.dc")
        theme = ThemeInfo(
            name="WithDC", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/WithDC"),
            config_path=dc_path,
        )
        mock_for_res.return_value = MagicMock(
            path="/tmp/themes", __str__=lambda s: "/tmp/themes")
        mock_discover.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": MagicMock(), "is_animated": False,
        }

        result = lcd_with_mocks.load_theme_by_name("WithDC")

        assert result["theme_path"] == theme.path
        assert result["config_path"] == dc_path


# =============================================================================
# IPC routes — load_theme_by_name and load_mask_standalone registered
# =============================================================================


class TestIPCDisplayRoutes:
    """IPC _DISPLAY_ROUTES includes theme and mask methods."""

    def test_load_theme_by_name_in_routes(self):
        from trcc.ipc import _DISPLAY_ROUTES
        assert "load_theme_by_name" in _DISPLAY_ROUTES
        assert _DISPLAY_ROUTES["load_theme_by_name"] == ("theme", "load_theme_by_name")

    def test_load_mask_standalone_in_routes(self):
        from trcc.ipc import _DISPLAY_ROUTES
        assert "load_mask_standalone" in _DISPLAY_ROUTES
        assert _DISPLAY_ROUTES["load_mask_standalone"] == ("overlay", "load_mask_standalone")


# =============================================================================
# Instance detection DI — proxy routing
# =============================================================================


class TestLCDDeviceProxyRouting:
    """LCDDevice.connect() routes through proxy when another instance active."""

    def test_connect_routes_through_proxy_when_active(self):
        """When find_active_fn returns an instance, connect() sets proxy."""
        proxy = MagicMock()
        proxy.connected = True
        proxy.resolution = (320, 320)
        proxy.device_path = '/dev/sg0'

        lcd = LCDDevice(
            find_active_fn=lambda: InstanceKind.GUI,
            proxy_factory_fn=lambda kind: proxy,
        )
        result = lcd.connect()
        assert result["success"]
        assert result["proxy"] == InstanceKind.GUI
        # Capability accessors redirected to proxy
        assert lcd.frame is proxy
        assert lcd.theme is proxy
        assert lcd.settings is proxy

    def test_connect_direct_when_no_active_instance(self):
        """When find_active_fn returns None, connect() goes direct."""
        svc = MagicMock()
        svc.selected = None
        lcd = LCDDevice(
            find_active_fn=lambda: None,
            proxy_factory_fn=lambda kind: MagicMock(),
        )
        with patch("trcc.adapters.device.detector.detect_devices"), \
             patch("trcc.services.DeviceService", return_value=svc):
            result = lcd.connect()
        assert not result["success"]  # No device found
        assert lcd._proxy is None  # No proxy set

    def test_connect_skips_detection_without_di(self):
        """Without DI params, connect() never checks for active instances."""
        svc = MagicMock()
        svc.selected = None
        lcd = LCDDevice()
        with patch("trcc.adapters.device.detector.detect_devices"), \
             patch("trcc.services.DeviceService", return_value=svc):
            result = lcd.connect()
        assert not result["success"]
        assert lcd._proxy is None

    def test_connected_true_via_proxy(self):
        """connected property returns True when proxy is set."""
        proxy = MagicMock()
        proxy.connected = True
        lcd = LCDDevice(
            find_active_fn=lambda: InstanceKind.GUI,
            proxy_factory_fn=lambda kind: proxy,
        )
        lcd.connect()
        assert lcd.connected

    def test_connect_with_explicit_device_skips_detection(self):
        """When detected= is provided, skip instance detection."""
        find_fn = MagicMock(return_value=InstanceKind.GUI)
        svc = MagicMock()
        svc.selected = None
        lcd = LCDDevice(
            find_active_fn=find_fn,
            proxy_factory_fn=MagicMock(),
        )
        with patch("trcc.adapters.device.detector.detect_devices"), \
             patch("trcc.services.DeviceService", return_value=svc):
            lcd.connect("/dev/sg0")
        find_fn.assert_not_called()


if __name__ == '__main__':
    unittest.main()
