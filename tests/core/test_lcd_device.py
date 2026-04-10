"""Tests for core/device.py — Device (LCD mode) application facade."""

import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import get_pixel, make_test_surface

from trcc.core.device import Device
from trcc.core.instance import InstanceKind
from trcc.core.orientation import Orientation
from trcc.services.display import DisplayService
from trcc.services.image import ImageService
from trcc.services.overlay import OverlayService


def _make_lcd(**overrides) -> Device:
    """Create Device with mock services."""
    defaults = {
        'device_svc': MagicMock(),
        'display_svc': MagicMock(),
        'theme_svc': MagicMock(),
        'renderer': MagicMock(),
        'dc_config_cls': MagicMock(),
        'load_config_json_fn': MagicMock(),
        'theme_info_from_dir_fn': MagicMock(),
        'lcd_config': MagicMock(**{
            'device_key.return_value': '0',
            'get_config.return_value': {},
        }),
    }
    defaults.update(overrides)
    return Device(**defaults)


def _make_real_lcd() -> tuple[Device, MagicMock]:
    """Create Device with real DisplayService + OverlayService.

    Only DeviceService is mocked (USB boundary).
    Returns (lcd, mock_device_svc) so tests can verify send_frame calls.
    """
    renderer = ImageService._r()
    device_svc = MagicMock()
    device_svc.selected = MagicMock()
    device_svc.selected.encoding_params = ('scsi', (320, 320), None, False)
    device_svc.selected.path = '/dev/sg0'
    device_svc.selected.vid = 0x0402
    device_svc.selected.pid = 0x3922
    device_svc.selected.device_index = 0
    device_svc.send_frame.return_value = True
    device_svc.send_frame_async.return_value = None
    device_svc.is_busy = False
    mock_media = MagicMock()
    mock_media._frames = []
    mock_media.has_frames = False
    mock_media.is_playing = False
    mock_media.source_path = None
    mock_media.get_frame.return_value = None
    mock_media.frame_interval_ms = 33
    overlay = OverlayService(320, 320, renderer=renderer)
    display_svc = DisplayService(device_svc, overlay, mock_media)
    display_svc.set_resolution(320, 320)
    lcd = Device(
        device_svc=device_svc,
        display_svc=display_svc,
        theme_svc=MagicMock(),
        renderer=renderer,
    )
    lcd.orientation = display_svc.orientation
    return lcd, device_svc


# =============================================================================
# Construction
# =============================================================================


class TestDeviceConstruction(unittest.TestCase):
    """Device construction and self-referencing accessors."""

    def test_stores_injected_services(self):
        svc = MagicMock()
        disp = MagicMock()
        theme = MagicMock()
        lcd = _make_lcd(device_svc=svc, display_svc=disp, theme_svc=theme)
        self.assertIs(lcd._device_svc, svc)
        self.assertIs(lcd._display_svc, disp)
        self.assertIs(lcd._theme_svc, theme)

    def test_default_no_services(self):
        """Device() with no args starts empty."""
        lcd = Device()
        self.assertIsNone(lcd._device_svc)
        self.assertIsNone(lcd._display_svc)
        self.assertIsNone(lcd._theme_svc)

    def test_connect_requires_device_svc(self):
        """connect() raises RuntimeError without injected device_svc."""
        lcd = Device()
        with self.assertRaises(RuntimeError, msg="ControllerBuilder"):
            lcd.connect()

    def test_build_services_requires_factory(self):
        """_build_services() raises RuntimeError without build_services_fn."""
        lcd = Device(device_svc=MagicMock())
        with self.assertRaises(RuntimeError, msg="ControllerBuilder"):
            lcd._build_services(MagicMock())


# =============================================================================
# Device ABC — connected, device_info, cleanup
# =============================================================================


class TestDeviceABC(unittest.TestCase):
    """Device ABC methods on Device."""

    def test_connected_true_when_device_selected(self):
        svc = MagicMock()
        svc.selected = MagicMock()  # has a selected device
        lcd = _make_lcd(device_svc=svc)
        self.assertTrue(lcd.connected)

    def test_connected_false_when_no_device_svc(self):
        lcd = Device()
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
        lcd = Device()
        self.assertIsNone(lcd.device_info)

    def test_cleanup_calls_display_svc(self):
        disp = MagicMock()
        lcd = _make_lcd(display_svc=disp)
        lcd.cleanup()
        disp.cleanup.assert_called_once()

    def test_cleanup_safe_when_no_display_svc(self):
        lcd = Device()
        lcd.cleanup()  # should not raise


# =============================================================================
# Properties
# =============================================================================


class TestDeviceProperties(unittest.TestCase):
    """LCD-specific properties delegating to services."""

    def test_lcd_size_from_display_svc(self):
        disp = MagicMock()
        disp.lcd_width = 480
        disp.lcd_height = 480
        lcd = _make_lcd(display_svc=disp)
        self.assertEqual(lcd.lcd_size, (480, 480))

    def test_lcd_size_zero_when_no_display_svc(self):
        lcd = Device()
        self.assertEqual(lcd.lcd_size, (0, 0))

    def test_resolution_equals_lcd_size(self):
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        lcd = _make_lcd(display_svc=disp)
        self.assertEqual(lcd.resolution, lcd.lcd_size)

    def test_collect_other_resolutions_empty_when_no_devices(self):
        lcd = Device()
        assert lcd.collect_other_device_resolutions() == []

    def test_collect_other_resolutions_skips_current(self):
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        dev_svc = MagicMock()
        dev0 = MagicMock()
        dev0.resolution = (320, 320)
        dev_svc.devices = [dev0]
        lcd = _make_lcd(device_svc=dev_svc, display_svc=disp)
        assert lcd.collect_other_device_resolutions() == []

    def test_collect_other_resolutions_includes_both_orientations(self):
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        dev_svc = MagicMock()
        dev0 = MagicMock()
        dev0.resolution = (320, 320)
        dev1 = MagicMock()
        dev1.resolution = (480, 1280)
        dev_svc.devices = [dev0, dev1]
        lcd = _make_lcd(device_svc=dev_svc, display_svc=disp)
        result = sorted(lcd.collect_other_device_resolutions())
        assert result == [(480, 1280), (1280, 480)]

    def test_collect_other_resolutions_square_single_entry(self):
        disp = MagicMock()
        disp.lcd_width = 320
        disp.lcd_height = 320
        dev_svc = MagicMock()
        dev0 = MagicMock()
        dev0.resolution = (320, 320)
        dev1 = MagicMock()
        dev1.resolution = (480, 480)
        dev_svc.devices = [dev0, dev1]
        lcd = _make_lcd(device_svc=dev_svc, display_svc=disp)
        assert lcd.collect_other_device_resolutions() == [(480, 480)]

    def test_device_path_from_device_info(self):
        dev = MagicMock()
        dev.path = '/dev/sg0'
        svc = MagicMock()
        svc.selected = dev
        lcd = _make_lcd(device_svc=svc)
        self.assertEqual(lcd.device_path, '/dev/sg0')

    def test_device_path_none_when_no_device(self):
        lcd = Device()
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
        lcd = Device()
        self.assertIsNone(lcd.current_image)

    def test_current_theme_path(self):
        disp = MagicMock()
        disp.current_theme_path = '/themes/test'
        lcd = _make_lcd(display_svc=disp)
        self.assertEqual(lcd.current_theme_path, '/themes/test')

    def test_auto_send_default_false(self):
        lcd = Device()
        self.assertFalse(lcd.auto_send)


# =============================================================================
# Frame operations — send_image, send_color, send
# =============================================================================


class TestDeviceFrame(unittest.TestCase):
    """Frame send operations — real image processing, mocked USB send."""

    def test_send_image_file_not_found(self):
        lcd = _make_lcd()
        result = lcd.send_image('/nonexistent/test.png')
        self.assertFalse(result['success'])
        self.assertIn('not found', result['error'])

    def test_send_image_success(self):
        """send_image with valid PNG processes through real services."""
        import tempfile
        from pathlib import Path
        lcd, device_svc = _make_real_lcd()
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            make_test_surface(320, 320, (0, 0, 255)).save(f.name, "PNG")
            path = f.name
        try:
            result = lcd.send_image(path)
            self.assertTrue(result['success'])
            device_svc.send_frame.assert_called_once()
            # Verify actual blue pixels were sent
            img = device_svc.send_frame.call_args[0][0]
            r, g, b = get_pixel(img, 160, 160)[:3]
            self.assertGreater(b, 200)
        finally:
            Path(path).unlink(missing_ok=True)

    def test_send_color_creates_correct_pixels(self):
        """send_color creates a real solid-color image."""
        lcd, device_svc = _make_real_lcd()
        result = lcd.send_color(255, 0, 0)
        self.assertTrue(result['success'])
        device_svc.send_frame.assert_called_once()
        img = device_svc.send_frame.call_args[0][0]
        r, g, b = get_pixel(img, 0, 0)[:3]
        self.assertEqual((r, g, b), (255, 0, 0))

    def test_send_no_device_selected(self):
        svc = MagicMock()
        svc.selected = None
        lcd = _make_lcd(device_svc=svc)
        result = lcd.send(MagicMock())
        self.assertFalse(result['success'])

    def test_send_with_device(self):
        lcd, device_svc = _make_real_lcd()
        img = make_test_surface(320, 320, (128, 128, 128))
        result = lcd.send(img)
        self.assertTrue(result['success'])
        device_svc.send_frame_async.assert_called_once()


# =============================================================================
# Settings — brightness, rotation, split mode, resolution
# =============================================================================


class TestDeviceSettings(unittest.TestCase):
    """Settings operations — real DisplayService verifies actual state changes."""

    @patch.object(Device, '_persist')
    def test_set_brightness_percent(self, _):
        lcd, _ = _make_real_lcd()
        result = lcd.set_brightness(75)
        self.assertTrue(result['success'])
        self.assertEqual(lcd._display_svc.brightness, 75)

    @patch.object(Device, '_persist')
    def test_set_brightness_1_percent(self, _):
        lcd, _ = _make_real_lcd()
        result = lcd.set_brightness(1)
        self.assertTrue(result['success'])
        self.assertEqual(lcd._display_svc.brightness, 1)

    @patch.object(Device, '_persist')
    def test_set_brightness_100_percent(self, _):
        lcd, _ = _make_real_lcd()
        result = lcd.set_brightness(100)
        self.assertTrue(result['success'])
        self.assertEqual(lcd._display_svc.brightness, 100)

    def test_set_brightness_invalid(self):
        lcd = _make_lcd()
        result = lcd.set_brightness(-5)
        self.assertFalse(result['success'])

    @patch.object(Device, '_persist')
    def test_set_rotation_valid(self, _):
        lcd, _ = _make_real_lcd()
        for deg in (0, 90, 180, 270):
            with self.subTest(deg=deg):
                result = lcd.set_rotation(deg)
                self.assertTrue(result['success'])
                self.assertEqual(lcd._display_svc.rotation, deg)

    def test_set_rotation_invalid(self):
        lcd = _make_lcd()
        result = lcd.set_rotation(45)
        self.assertFalse(result['success'])

    @patch.object(Device, '_persist')
    def test_set_rotation_swaps_output_resolution(self, _):
        """Non-square device rotation swaps output resolution."""
        lcd, _ = _make_real_lcd()
        lcd._display_svc.set_resolution(800, 480)
        lcd._display_svc.current_theme_path = None  # No theme loaded
        result = lcd.set_rotation(90)
        self.assertTrue(result['success'])
        # Output always swaps for non-square at 90/270
        self.assertEqual(lcd._display_svc.output_resolution, (480, 800))

    @patch.object(Device, '_persist')
    def test_rotation_reloads_mask_from_new_dir(self, _):
        """Non-square rotation reloads mask from new zt directory."""
        import tempfile
        from pathlib import Path
        lcd, _ = _make_real_lcd()
        lcd._display_svc.set_resolution(1280, 480)

        with tempfile.TemporaryDirectory() as td:
            old_mask = Path(td) / 'web' / 'zt1280480' / 'Mask01'
            old_mask.mkdir(parents=True)
            (old_mask / '01.png').write_bytes(b'fake')
            lcd._display_svc.mask_source_dir = old_mask

            new_mask = Path(td) / 'web' / 'zt4801280' / 'Mask01'
            new_mask.mkdir(parents=True)
            (new_mask / '01.png').write_bytes(b'fake')
            lcd._display_svc.orientation.data_root = Path(td)
            lcd._display_svc.orientation.rotation = 90

            with patch.object(lcd, 'load_mask_standalone',
                              return_value={'success': True}) as mock_load:
                lcd._reload_mask_for_rotation(lcd._display_svc)
                mock_load.assert_called_once_with(str(new_mask))

    @patch.object(Device, '_persist')
    def test_rotation_clears_mask_when_no_rotated_variant(self, _):
        """Non-square rotation clears mask if new zt dir has no match."""
        import tempfile
        from pathlib import Path
        lcd, _ = _make_real_lcd()
        lcd._display_svc.set_resolution(1280, 480)

        with tempfile.TemporaryDirectory() as td:
            old_mask = Path(td) / 'web' / 'zt1280480' / 'Mask01'
            old_mask.mkdir(parents=True)
            lcd._display_svc.mask_source_dir = old_mask

            new_masks = Path(td) / 'web' / 'zt4801280'
            new_masks.mkdir(parents=True)
            lcd._display_svc.orientation.data_root = Path(td)
            lcd._display_svc.orientation.rotation = 90

            lcd._reload_mask_for_rotation(lcd._display_svc)
            self.assertIsNone(lcd._display_svc.overlay.theme_mask)
            self.assertIsNone(lcd._display_svc.mask_source_dir)

    @patch.object(Device, '_persist')
    def test_rotation_skips_theme_reload_when_only_web_mask_dirs(self, _):
        """No theme reload when only web/mask portrait dirs exist.

        Canvas stays landscape (no portrait theme dir), so the canvas
        doesn't change and _reload_theme_for_rotation is never called.
        Local themes pixel-rotate via image_rotation instead.
        """
        lcd, _ = _make_real_lcd()
        lcd._display_svc.set_resolution(1280, 480)
        lcd.orientation = lcd._display_svc.orientation
        # has_portrait_themes stays False (default) — no portrait theme dir

        with patch.object(lcd, '_reload_theme_for_rotation') as mock_reload:
            result = lcd.set_rotation(90)
        self.assertTrue(result['success'])
        mock_reload.assert_not_called()
        # Canvas stays landscape — no portrait theme dir
        self.assertEqual(lcd._display_svc.canvas_size, (1280, 480))

    @patch.object(Device, '_persist')
    def test_rotation_fires_theme_reload_when_portrait_theme_dir(self, _):
        """Theme reload fires when portrait theme dir exists."""
        import tempfile
        from pathlib import Path
        lcd, _ = _make_real_lcd()
        lcd._display_svc.set_resolution(1280, 480)
        lcd.orientation = lcd._display_svc.orientation
        o = lcd.orientation

        with tempfile.TemporaryDirectory() as td:
            o.has_portrait_themes = True
            o.data_root = Path(td)
            # Create portrait theme dir so theme_dir resolves
            (Path(td) / 'theme4801280').mkdir()
            lcd._display_svc.current_theme_path = Path('/fake/theme1280480/Theme1')

            with patch.object(lcd, '_reload_theme_for_rotation',
                              return_value=None) as mock_reload:
                lcd.set_rotation(90)
            mock_reload.assert_called_once()

    @patch.object(Device, '_persist')
    def test_rotation_mask_uses_saved_dir_not_clobbered(self, _):
        """Full set_rotation() uses saved mask dir, not the one select() clobbers."""
        import tempfile
        from pathlib import Path
        lcd, _ = _make_real_lcd()
        lcd._display_svc.set_resolution(1280, 480)
        lcd.orientation = lcd._display_svc.orientation
        o = lcd.orientation

        with tempfile.TemporaryDirectory() as td:
            o.data_root = Path(td)
            # Set up masks dirs under web/ for both orientations
            old_mask = Path(td) / 'web' / 'zt1280480' / 'Mask01'
            old_mask.mkdir(parents=True)
            (old_mask / '01.png').write_bytes(b'fake')
            new_mask = Path(td) / 'web' / 'zt4801280' / 'Mask01'
            new_mask.mkdir(parents=True)
            (new_mask / '01.png').write_bytes(b'fake')

            lcd._display_svc.mask_source_dir = old_mask

            with patch.object(lcd, 'load_mask_standalone',
                              return_value={'success': True}) as mock_load:
                lcd.set_rotation(90)
            mock_load.assert_called_once_with(str(new_mask))

    @patch.object(Device, '_persist')
    def test_set_split_mode_valid(self, _):
        lcd, _ = _make_real_lcd()
        for mode in (0, 1, 2, 3):
            with self.subTest(mode=mode):
                result = lcd.set_split_mode(mode)
                self.assertTrue(result['success'])
                self.assertEqual(lcd._display_svc.split_mode, mode)

    def test_set_split_mode_invalid(self):
        lcd = _make_lcd()
        result = lcd.set_split_mode(5)
        self.assertFalse(result['success'])


# =============================================================================
# Overlay operations
# =============================================================================


class TestDeviceOverlay(unittest.TestCase):
    """Overlay enable/disable/config operations — real OverlayService."""

    def test_enable_overlay(self):
        lcd, _ = _make_real_lcd()
        result = lcd.enable(True)
        self.assertTrue(result['success'])
        self.assertTrue(lcd._display_svc.overlay.enabled)

    def test_disable_overlay(self):
        lcd, _ = _make_real_lcd()
        lcd.enable(True)
        result = lcd.enable(False)
        self.assertTrue(result['success'])
        self.assertFalse(lcd._display_svc.overlay.enabled)

    def test_set_config(self):
        lcd, _ = _make_real_lcd()
        config = {'cpu_temp': {'x': 10, 'y': 20, 'color': 'ffffff', 'size': 14}}
        result = lcd.set_config(config)
        self.assertTrue(result['success'])
        self.assertEqual(lcd._display_svc.overlay.config, config)


# =============================================================================
# from_service / restore_device_settings / load_last_theme
# =============================================================================


class TestFromService(unittest.TestCase):
    """Device.from_service() classmethod."""

    def test_from_service_builds_services(self):
        svc = MagicMock()
        with patch.object(Device, '_build_services') as mock_build:
            lcd = Device.from_service(svc)
        mock_build.assert_called_once_with(svc)
        self.assertTrue(lcd.is_lcd)


class TestRestoreDeviceSettings(unittest.TestCase):
    """Device.restore_device_settings()."""

    def test_restores_brightness_and_rotation(self):
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        disp = MagicMock()
        lcd = _make_lcd(device_svc=svc, display_svc=disp)
        with patch('trcc.conf.Settings.device_config_key',
                   return_value="0"), \
             patch('trcc.conf.Settings.get_device_config',
                   return_value={'brightness_level': 50, 'rotation': 90}):
            lcd.restore_device_settings()
        # set_brightness calls DisplayService
        self.assertEqual(disp.set_brightness.call_count, 1)
        self.assertEqual(disp.set_rotation.call_count, 1)

    def test_no_device_does_nothing(self):
        lcd = _make_lcd(device_svc=MagicMock(selected=None))
        lcd.restore_device_settings()  # should not raise


class TestLoadLastTheme(unittest.TestCase):
    """Device.load_last_theme()."""

    def test_no_theme_returns_error(self):
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        lcd = _make_lcd(device_svc=svc)
        result = lcd.load_last_theme()
        self.assertFalse(result['success'])
        self.assertIn("No saved theme", result['error'])

    def test_nonexistent_local_theme_returns_error(self):
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        lcd = _make_lcd(
            device_svc=svc,
            lcd_config=MagicMock(**{'get_config.return_value': {
                'theme_name': 'NonExistent', 'theme_type': 'local',
            }}),
        )
        import tempfile
        from pathlib import Path
        with tempfile.TemporaryDirectory() as td:
            # theme_dir derives as data_root / 'theme00' for Orientation(0,0)
            (Path(td) / 'theme00').mkdir()
            lcd.orientation.data_root = Path(td)
            result = lcd.load_last_theme()
        self.assertFalse(result['success'])
        self.assertIn("not found", result['error'])

    def test_migration_old_theme_path(self):
        """Old config with theme_path auto-migrates to name-based lookup."""
        import tempfile
        from pathlib import Path
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        disp = MagicMock()
        disp.load_image_file.return_value = MagicMock()
        with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
            tmp = Path(f.name)
        try:
            lcd = _make_lcd(
                device_svc=svc, display_svc=disp,
                lcd_config=MagicMock(**{'get_config.return_value': {
                    'theme_path': str(tmp),  # old format
                }}),
            )
            result = lcd.load_last_theme()
            self.assertTrue(result['success'])
        finally:
            tmp.unlink(missing_ok=True)

    def test_local_theme_resolves_by_name(self):
        import tempfile
        from pathlib import Path
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        disp = MagicMock()
        with tempfile.TemporaryDirectory() as td:
            # theme_dir derives as data_root / 'theme00' for Orientation(0,0)
            theme_base = Path(td) / 'theme00'
            theme_base.mkdir()
            theme_dir = theme_base / "Theme1"
            theme_dir.mkdir()
            (theme_dir / "00.png").write_bytes(b"fake")
            lcd = _make_lcd(
                device_svc=svc, display_svc=disp,
                lcd_config=MagicMock(**{'get_config.return_value': {
                    'theme_name': 'Theme1', 'theme_type': 'local',
                }}),
            )
            lcd.orientation.data_root = Path(td)
            result = lcd.load_last_theme()
            self.assertTrue(result['success'])

    def test_restore_sends_static_frame_to_device(self):
        """Static theme → render_and_send() composites mask/overlay + sends."""
        import tempfile
        from pathlib import Path
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        fake_image = MagicMock()
        rendered_image = MagicMock()
        disp = MagicMock(
            lcd_width=320, lcd_height=320, auto_send=True,
            load_local_theme=MagicMock(return_value={
                'image': fake_image, 'is_animated': False,
            }),
            render_overlay=MagicMock(return_value=rendered_image),
        )
        with tempfile.TemporaryDirectory() as td:
            # theme_dir derives as data_root / 'theme00' for Orientation(0,0)
            theme_base = Path(td) / 'theme00'
            theme_base.mkdir()
            theme_dir = theme_base / "Theme1"
            theme_dir.mkdir()
            (theme_dir / "00.png").write_bytes(b"fake")
            lcd = _make_lcd(
                device_svc=svc, display_svc=disp,
                lcd_config=MagicMock(**{'get_config.return_value': {
                    'theme_name': 'Theme1', 'theme_type': 'local',
                }}),
            )
            lcd.orientation.data_root = Path(td)
            result = lcd.restore_last_theme()
            self.assertTrue(result['success'])
            disp.render_overlay.assert_called_once()
            svc.send_frame_async.assert_called_once()

    def test_restore_renders_and_sends_overlay(self):
        """Static theme with overlay → render_and_send() called."""
        import tempfile
        from pathlib import Path
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        fake_image = MagicMock()
        rendered_image = MagicMock()
        disp = MagicMock(
            lcd_width=320, lcd_height=320, auto_send=True,
            load_local_theme=MagicMock(return_value={
                'image': fake_image, 'is_animated': False,
            }),
            render_overlay=MagicMock(return_value=rendered_image),
        )
        with tempfile.TemporaryDirectory() as td:
            # theme_dir derives as data_root / 'theme00' for Orientation(0,0)
            theme_base = Path(td) / 'theme00'
            theme_base.mkdir()
            theme_dir = theme_base / "Theme1"
            theme_dir.mkdir()
            (theme_dir / "00.png").write_bytes(b"fake")
            lcd = _make_lcd(
                device_svc=svc, display_svc=disp,
                lcd_config=MagicMock(**{'get_config.return_value': {
                    'theme_name': 'Theme1', 'theme_type': 'local',
                    'overlay': {'enabled': True, 'config': {'elements': []}},
                }}),
            )
            lcd.orientation.data_root = Path(td)
            result = lcd.restore_last_theme()
            self.assertTrue(result['success'])
            self.assertTrue(result['overlay_enabled'])
            disp.render_overlay.assert_called_once()

    def test_restore_skips_send_for_animated(self):
        """Animated theme → no send() call (caller runs the loop)."""
        import tempfile
        from pathlib import Path
        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        fake_image = MagicMock()
        disp = MagicMock(
            lcd_width=320, lcd_height=320,
            load_local_theme=MagicMock(return_value={
                'image': fake_image, 'is_animated': True,
            }),
        )
        with tempfile.TemporaryDirectory() as td:
            # theme_dir derives as data_root / 'theme00' for Orientation(0,0)
            theme_base = Path(td) / 'theme00'
            theme_base.mkdir()
            theme_dir = theme_base / "Theme1"
            theme_dir.mkdir()
            (theme_dir / "00.png").write_bytes(b"fake")
            lcd = _make_lcd(
                device_svc=svc, display_svc=disp,
                lcd_config=MagicMock(**{'get_config.return_value': {
                    'theme_name': 'Theme1', 'theme_type': 'local',
                }}),
            )
            lcd.orientation.data_root = Path(td)
            result = lcd.restore_last_theme()
            self.assertTrue(result['success'])
            self.assertTrue(result['is_animated'])
            svc.send_frame_async.assert_not_called()
            svc.send_frame.assert_not_called()

    def test_restore_uses_mask_dc_for_overlay(self):
        """When mask_id is set, overlay config comes from mask's config1.dc."""
        import tempfile

        dev = MagicMock(device_index=0, vid=0x0402, pid=0x3922)
        svc = MagicMock(selected=dev)
        fake_image = MagicMock()
        rendered_image = MagicMock()
        mask_overlay = {'elements': [{'type': 'time', 'x': 10, 'y': 20}]}
        saved_overlay = {'elements': [{'type': 'cpu_temp', 'x': 100, 'y': 200}]}
        disp = MagicMock(
            lcd_width=320, lcd_height=320, auto_send=True,
            mask_source_dir=None,
            canvas_size=(320, 320),
            output_resolution=(320, 320),
            load_local_theme=MagicMock(return_value={
                'image': fake_image, 'is_animated': False,
            }),
            render_overlay=MagicMock(return_value=rendered_image),
        )
        with tempfile.TemporaryDirectory() as td:
            theme_base = Path(td) / 'theme320320'
            theme_base.mkdir()
            theme_dir = theme_base / "Theme1"
            theme_dir.mkdir()
            (theme_dir / "00.png").write_bytes(b"fake")
            # Mask dir with config1.dc
            masks_base = Path(td) / 'web' / 'zt320320'
            masks_base.mkdir(parents=True)
            mask_dir = masks_base / "Mask1"
            mask_dir.mkdir()
            (mask_dir / "01.png").write_bytes(b"fake_mask")
            (mask_dir / "config1.dc").write_bytes(b"fake_dc")

            dc_cls = MagicMock()
            dc_cls.return_value.to_overlay_config.return_value = mask_overlay

            lcd = _make_lcd(
                device_svc=svc, display_svc=disp,
                dc_config_cls=dc_cls,
                lcd_config=MagicMock(**{'get_config.return_value': {
                    'theme_name': 'Theme1', 'theme_type': 'local',
                    'mask_id': 'Mask1',
                    'overlay': {'enabled': True, 'config': saved_overlay},
                }}),
            )
            lcd.orientation.data_root = Path(td)
            lcd.orientation.native = (320, 320)
            result = lcd.restore_last_theme()
            self.assertTrue(result['success'], result.get('error'))
            # Mask DC overlay should be used, not the saved overlay
            self.assertEqual(result['overlay_config'], mask_overlay)
            self.assertTrue(result['overlay_enabled'])


# =============================================================================
# load_theme_by_name — routes through discover + select
# =============================================================================


@pytest.fixture
def lcd_with_mocks():
    """Device with mock services, 320x320 resolution."""
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
    lcd.orientation = Orientation(320, 320)
    lcd.orientation.data_root = Path('/tmp')
    return lcd


class TestLoadThemeByName:
    """Device.load_theme_by_name — core theme loading by name."""

    def test_found_theme_calls_select(self, lcd_with_mocks):
        from trcc.core.models import ThemeInfo, ThemeType

        theme = ThemeInfo(name="CyberPunk", theme_type=ThemeType.LOCAL)
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = [theme]

        result = lcd_with_mocks.load_theme_by_name("CyberPunk")

        assert result["success"] is True
        lcd_with_mocks._theme_svc.select.assert_called_once_with(theme)

    def test_not_found_returns_error(self, lcd_with_mocks):
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = []
        result = lcd_with_mocks.load_theme_by_name("NonExistent")

        assert result["success"] is False
        assert "not found" in result["error"]

    def test_explicit_resolution_passes_to_discover(self, lcd_with_mocks):
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = []

        lcd_with_mocks.load_theme_by_name("Theme001", 480, 480)

        lcd_with_mocks._theme_svc.discover_local_merged.assert_called_once()
        assert lcd_with_mocks._theme_svc.discover_local_merged.call_args[0][2] == (480, 480)

    def test_zero_resolution_uses_device_size(self, lcd_with_mocks):
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = []

        lcd_with_mocks.load_theme_by_name("Theme001", 0, 0)

        lcd_with_mocks._theme_svc.discover_local_merged.assert_called_once()
        assert lcd_with_mocks._theme_svc.discover_local_merged.call_args[0][2] == (320, 320)

    def test_sends_static_image_to_device(self, lcd_with_mocks):
        """Static theme image is sent to device after select()."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        fake_image = MagicMock()
        theme = ThemeInfo(
            name="Static001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Static001"),
        )
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": fake_image, "is_animated": False,
        }

        result = lcd_with_mocks.load_theme_by_name("Static001")

        assert result["success"] is True
        lcd_with_mocks._device_svc.send_frame_async.assert_called_once()

    def test_does_not_send_animated_theme(self, lcd_with_mocks):
        """Animated themes return image but don't call send (caller loops)."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        theme = ThemeInfo(
            name="Video001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Video001"),
        )
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": MagicMock(), "is_animated": True,
        }

        result = lcd_with_mocks.load_theme_by_name("Video001")

        assert result["success"] is True
        assert result["is_animated"] is True
        lcd_with_mocks._device_svc.send_frame_async.assert_not_called()

    def test_persists_theme_name(self, lcd_with_mocks):
        """Theme name + type saved to per-device config, mask cleared."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        theme = ThemeInfo(
            name="Saved001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Saved001"),
        )
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": MagicMock(), "is_animated": False,
        }

        lcd_with_mocks.load_theme_by_name("Saved001")

        calls = lcd_with_mocks._lcd_config.persist.call_args_list
        assert any(
            c.args[1] == 'theme_name' and c.args[2] == 'Saved001'
            for c in calls
        ), f"Expected theme_name save, got: {calls}"
        assert any(
            c.args[1] == 'theme_type' and c.args[2] == 'local'
            for c in calls
        ), f"Expected theme_type save, got: {calls}"
        assert any(
            c.args[1] == 'mask_id' and c.args[2] == ''
            for c in calls
        ), f"Expected mask_id clear, got: {calls}"

    def test_result_includes_theme_and_config_paths(self, lcd_with_mocks):
        """Result dict includes theme_path and config_path for caller."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        dc_path = Path("/tmp/themes/WithDC/config1.dc")
        theme = ThemeInfo(
            name="WithDC", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/WithDC"),
            config_path=dc_path,
        )
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": MagicMock(), "is_animated": False,
        }

        result = lcd_with_mocks.load_theme_by_name("WithDC")

        assert result["theme_path"] == theme.path
        assert result["config_path"] == dc_path


# =============================================================================
# IPC routes — load_theme_by_name and load_mask_standalone registered
# =============================================================================


class TestIPCDeviceMethods:
    """IPC _DEVICE_METHODS includes theme and mask methods."""

    def test_load_theme_by_name_in_methods(self):
        from trcc.ipc import _DEVICE_METHODS
        assert "load_theme_by_name" in _DEVICE_METHODS

    def test_load_mask_standalone_in_methods(self):
        from trcc.ipc import _DEVICE_METHODS
        assert "load_mask_standalone" in _DEVICE_METHODS


# =============================================================================
# Instance detection DI — proxy routing
# =============================================================================


class TestDeviceProxyRouting:
    """Device.connect() routes through proxy when another instance active."""

    def test_connect_routes_through_proxy_when_active(self):
        """When find_active_fn returns an instance, connect() sets proxy."""
        proxy = MagicMock()
        proxy.connected = True
        proxy.resolution = (320, 320)
        proxy.device_path = '/dev/sg0'

        lcd = Device(
            find_active_fn=lambda: InstanceKind.GUI,
            proxy_factory_fn=lambda kind: proxy,
        )
        result = lcd.connect()
        assert result["success"]
        assert result["proxy"] == InstanceKind.GUI
        assert lcd._proxy is proxy

    def test_connect_direct_when_no_active_instance(self):
        """When find_active_fn returns None, connect() goes direct."""
        svc = MagicMock()
        svc.selected = None
        lcd = Device(
            device_svc=svc,
            build_services_fn=MagicMock(),
            find_active_fn=lambda: None,
            proxy_factory_fn=lambda kind: MagicMock(),
        )
        result = lcd.connect()
        assert not result["success"]  # No device found
        assert lcd._proxy is None  # No proxy set

    def test_connect_skips_detection_without_di(self):
        """Without DI params, connect() never checks for active instances."""
        svc = MagicMock()
        svc.selected = None
        lcd = Device(device_svc=svc, build_services_fn=MagicMock())
        result = lcd.connect()
        assert not result["success"]
        assert lcd._proxy is None

    def test_connected_true_via_proxy(self):
        """connected property returns True when proxy is set."""
        proxy = MagicMock()
        proxy.connected = True
        lcd = Device(
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
        lcd = Device(
            device_svc=svc,
            build_services_fn=MagicMock(),
            find_active_fn=find_fn,
            proxy_factory_fn=MagicMock(),
        )
        lcd.connect("/dev/sg0")
        find_fn.assert_not_called()


# =============================================================================
# keep_alive_loop + load_theme_by_name overlay activation
# =============================================================================


class TestKeepAliveLoop:
    """Device.keep_alive_loop — delegates to DisplayService.run_static_loop."""

    def test_delegates_to_display_service(self):
        disp = MagicMock()
        disp.run_static_loop.return_value = {"success": True, "message": "Stopped"}
        lcd = _make_lcd(display_svc=disp)

        result = lcd.keep_alive_loop(interval=0.2, duration=1.0)

        disp.run_static_loop.assert_called_once_with(
            interval=0.2, duration=1.0, metrics_fn=None, on_frame=None,
        )
        assert result["success"] is True

    def test_passes_metrics_fn(self):
        disp = MagicMock()
        disp.run_static_loop.return_value = {"success": True, "message": "Done"}
        lcd = _make_lcd(display_svc=disp)
        fn = MagicMock()

        lcd.keep_alive_loop(metrics_fn=fn)

        assert disp.run_static_loop.call_args[1]["metrics_fn"] is fn

    def test_no_display_svc_returns_error(self):
        lcd = _make_lcd(display_svc=None)

        result = lcd.keep_alive_loop()

        assert result["success"] is False
        assert "not initialized" in result["error"].lower()


class TestLoadThemeByNameOverlay:
    """load_theme_by_name enables overlay when theme has config."""

    def test_enables_overlay_when_config_exists(
        self,
        lcd_with_mocks,
    ):
        """Static theme with config1.dc → overlay enabled + render_and_send called."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        theme = ThemeInfo(
            name="Overlay001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Overlay001"),
        )
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": MagicMock(), "is_animated": False,
        }
        # Theme has overlay config
        lcd_with_mocks.load_overlay_config_from_dir = MagicMock(
            return_value={"elem0": {"x": 10, "y": 20, "text": "CPU"}})
        lcd_with_mocks.set_config = MagicMock(return_value={"success": True})
        lcd_with_mocks.enable_overlay = MagicMock(return_value={"success": True})
        lcd_with_mocks.render_and_send = MagicMock(
            return_value={"success": True, "image": MagicMock()})

        result = lcd_with_mocks.load_theme_by_name("Overlay001")

        assert result["success"] is True
        lcd_with_mocks.set_config.assert_called_once()
        lcd_with_mocks.enable_overlay.assert_called_once_with(True)
        lcd_with_mocks.render_and_send.assert_called_once()

    def test_disables_overlay_when_no_config(
        self,
        lcd_with_mocks,
    ):
        """Static theme without config → overlay disabled, image sent directly."""
        from pathlib import Path

        from trcc.core.models import ThemeInfo, ThemeType

        fake_image = MagicMock()
        theme = ThemeInfo(
            name="Plain001", theme_type=ThemeType.LOCAL,
            path=Path("/tmp/themes/Plain001"),
        )
        lcd_with_mocks._theme_svc.discover_local_merged.return_value = [theme]
        lcd_with_mocks._display_svc.load_local_theme.return_value = {
            "image": fake_image, "is_animated": False,
        }
        lcd_with_mocks.load_overlay_config_from_dir = MagicMock(return_value=None)
        lcd_with_mocks.enable_overlay = MagicMock(return_value={"success": True})

        result = lcd_with_mocks.load_theme_by_name("Plain001")

        assert result["success"] is True
        lcd_with_mocks.enable_overlay.assert_called_once_with(False)
        lcd_with_mocks._device_svc.send_frame_async.assert_called_once()


if __name__ == '__main__':
    unittest.main()
