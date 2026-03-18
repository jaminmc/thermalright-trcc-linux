"""Tests for CLI main() dispatch and commands not covered by split files.

Split CLI test files provide comprehensive coverage for submodules:
- test_cli_device.py  → detect, select, probe, format, _get_service, etc.
- test_cli_display.py → send, color, brightness, rotation, mask, overlay, etc.
- test_cli_led.py     → led-color, led-mode, led-brightness, led-off, led-sensor
- test_cli_theme.py   → theme-list, theme-load, theme-save, theme-export, theme-import
- test_cli_system.py  → info, download, setup-udev, report, uninstall, etc.

This file covers:
- main() dispatch (argument parsing → correct submodule function)
- gui() command
- hid-debug / led-debug diagnostic commands
- screencast command
- mask --clear flag
- test-display command
- Settings helpers (get/save selected device, corrupt JSON)
"""

import io
import os
import tempfile
import unittest
from contextlib import redirect_stdout
from unittest.mock import MagicMock, patch

from tests.conftest import make_mock_service as _mock_service
from trcc.cli import (
    _display,
    gui,
    hid_debug,
    led_debug,
    main,
)
from trcc.cli import test_display as cli_test_display

# =========================================================================
# main() dispatch — verifies argument parsing routes to correct functions
# =========================================================================

class TestMainEntryPoint(unittest.TestCase):
    """Test main() CLI dispatch."""

    def test_no_args_prints_help(self):
        """No subcommand -> print help, return 0."""
        with patch('sys.argv', ['trcc']):
            result = main()
        self.assertEqual(result, 0)

    def test_version_flag(self):
        """--version prints version and exits."""
        with patch('sys.argv', ['trcc', '--version']):
            result = main()
            self.assertEqual(result, 0)

    def test_detect_dispatches(self):
        """'detect' subcommand calls _device.detect()."""
        with patch('sys.argv', ['trcc', 'detect']), \
             patch('trcc.cli._device.detect', return_value=0) as mock_detect:
            result = main()
            mock_detect.assert_called_once_with(show_all=False)
            self.assertEqual(result, 0)

    def test_detect_all_flag(self):
        """'detect --all' passes show_all=True."""
        with patch('sys.argv', ['trcc', 'detect', '--all']), \
             patch('trcc.cli._device.detect', return_value=0) as mock_detect:
            main()
            mock_detect.assert_called_once_with(show_all=True)

    def test_select_dispatches(self):
        """'select 2' dispatches with number=2."""
        with patch('sys.argv', ['trcc', 'select', '2']), \
             patch('trcc.cli._device.select', return_value=0) as mock_sel:
            main()
            mock_sel.assert_called_once_with(2)

    def test_color_dispatches(self):
        """'color ff0000' passes hex and device."""
        with patch('sys.argv', ['trcc', 'color', 'ff0000']), \
             patch('trcc.cli._display.send_color', return_value=0) as mock_color:
            main()
            mock_color.assert_called_once_with('ff0000', device=None, preview=False)

    def test_info_dispatches(self):
        """'info' subcommand dispatches to _system.show_info."""
        with patch('sys.argv', ['trcc', 'info']), \
             patch('trcc.cli._system.show_info', return_value=0) as mock_info:
            main()
            mock_info.assert_called_once()

    def test_gui_dispatches(self):
        """'gui' subcommand dispatches to gui()."""
        with patch('sys.argv', ['trcc', 'gui']), \
             patch('trcc.cli.gui', return_value=0) as mock_gui:
            main()
            mock_gui.assert_called_once()

    def test_download_list(self):
        """'download --list' dispatches with show_list=True."""
        with patch('sys.argv', ['trcc', 'download', '--list']), \
             patch('trcc.cli._system.download_themes', return_value=0) as mock_dl:
            main()
            mock_dl.assert_called_once_with(
                pack=None, show_list=True, force=False, show_info=False
            )

    def test_download_pack(self):
        with patch('sys.argv', ['trcc', 'download', 'themes-320', '--force']), \
             patch('trcc.cli._system.download_themes', return_value=0) as mock_dl:
            main()
            mock_dl.assert_called_once_with(
                pack='themes-320', show_list=False, force=True, show_info=False
            )


class TestMainDispatch(unittest.TestCase):
    """Cover main() dispatch branches for test, send, color, info, reset, setup-udev."""

    @patch('trcc.cli._display.test', return_value=0)
    def test_dispatch_test(self, mock_fn):
        with patch('sys.argv', ['trcc', 'test']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._display.send_image', return_value=0)
    def test_dispatch_send(self, mock_fn):
        with patch('sys.argv', ['trcc', 'send', 'image.png']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._display.send_color', return_value=0)
    def test_dispatch_color(self, mock_fn):
        with patch('sys.argv', ['trcc', 'color', 'ff0000']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._system.show_info', return_value=0)
    def test_dispatch_info(self, mock_fn):
        with patch('sys.argv', ['trcc', 'info']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._display.reset', return_value=0)
    def test_dispatch_reset(self, mock_fn):
        with patch('sys.argv', ['trcc', 'reset']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._system.setup_udev', return_value=0)
    def test_dispatch_setup_udev(self, mock_fn):
        with patch('sys.argv', ['trcc', 'setup-udev', '--dry-run']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._system.download_themes', return_value=0)
    def test_dispatch_download(self, mock_fn):
        with patch('sys.argv', ['trcc', 'download', '--list']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)


class TestNewCommandDispatch(unittest.TestCase):
    """Verify Typer wrappers dispatch to correct methods."""

    def test_brightness_dispatches(self):
        """'brightness 2' calls _display.set_brightness(2)."""
        with patch('sys.argv', ['trcc', 'brightness', '2']), \
             patch('trcc.cli._display.set_brightness',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with(2, device=None)

    def test_rotation_dispatches(self):
        """'rotation 90' calls _display.set_rotation(90)."""
        with patch('sys.argv', ['trcc', 'rotation', '90']), \
             patch('trcc.cli._display.set_rotation',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with(90, device=None)

    def test_theme_list_dispatches(self):
        """'theme-list' calls _theme.list_themes()."""
        with patch('sys.argv', ['trcc', 'theme-list']), \
             patch('trcc.cli._theme.list_themes',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with(cloud=False, category=None)

    def test_theme_load_dispatches(self):
        """'theme-load myTheme' calls _theme.load_theme()."""
        with patch('sys.argv', ['trcc', 'theme-load', 'myTheme']), \
             patch('trcc.cli._theme.load_theme',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('myTheme', device=None, preview=False)

    def test_led_color_dispatches(self):
        """'led-color ff0000' calls _led.set_color()."""
        with patch('sys.argv', ['trcc', 'led-color', 'ff0000']), \
             patch('trcc.cli._led.set_color',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('ff0000', preview=False)

    def test_led_mode_dispatches(self):
        """'led-mode rainbow' calls _led.set_mode()."""
        with patch('sys.argv', ['trcc', 'led-mode', 'rainbow']), \
             patch('trcc.cli._led.set_mode',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('rainbow', preview=False)

    def test_led_brightness_dispatches(self):
        """'led-brightness 50' calls _led.set_led_brightness()."""
        with patch('sys.argv', ['trcc', 'led-brightness', '50']), \
             patch('trcc.cli._led.set_led_brightness',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with(50, preview=False)

    def test_led_off_dispatches(self):
        """'led-off' calls _led.led_off()."""
        with patch('sys.argv', ['trcc', 'led-off']), \
             patch('trcc.cli._led.led_off',
                          return_value=0) as mock:
            main()
            mock.assert_called_once()

    def test_screencast_dispatches(self):
        """'screencast' calls _display.screencast()."""
        with patch('sys.argv', ['trcc', 'screencast']), \
             patch('trcc.cli._display.screencast',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with(
                device=None, x=0, y=0, w=0, h=0, fps=10, preview=False)

    def test_mask_dispatches(self):
        """'mask /tmp/m.png' calls _display.load_mask()."""
        with patch('sys.argv', ['trcc', 'mask', '/tmp/m.png']), \
             patch('trcc.cli._display.load_mask',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('/tmp/m.png', device=None, preview=False)

    def test_overlay_dispatches(self):
        """'overlay /tmp/dc' calls _display.render_overlay()."""
        with patch('sys.argv', ['trcc', 'overlay', '/tmp/dc']), \
             patch('trcc.cli._display.render_overlay',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with(
                '/tmp/dc', device=None, send=False, output=None, preview=False)

    def test_theme_save_dispatches(self):
        """'theme-save MyTheme' routes through _cmd_theme(save='MyTheme')."""
        with patch('sys.argv', ['trcc', 'theme-save', 'MyTheme']), \
             patch('trcc.cli._theme.save_theme',
                          return_value=0) as mock:
            main()
            mock.assert_called_once()
            assert mock.call_args[0][0] == 'MyTheme'

    def test_theme_export_dispatches(self):
        """'theme-export Foo /tmp/out.tr' calls _theme.export_theme()."""
        with patch('sys.argv', ['trcc', 'theme-export', 'Foo', '/tmp/out.tr']), \
             patch('trcc.cli._theme.export_theme',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('Foo', '/tmp/out.tr')

    def test_theme_import_dispatches(self):
        """'theme-import /tmp/t.tr' calls _theme.import_theme()."""
        with patch('sys.argv', ['trcc', 'theme-import', '/tmp/t.tr']), \
             patch('trcc.cli._theme.import_theme',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('/tmp/t.tr', device=None)

    def test_led_sensor_dispatches(self):
        """'led-sensor cpu' calls _led.set_sensor_source()."""
        with patch('sys.argv', ['trcc', 'led-sensor', 'cpu']), \
             patch('trcc.cli._led.set_sensor_source',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('cpu')


# =========================================================================
# gui() command
# =========================================================================

class TestGui(unittest.TestCase):
    """Test gui() command."""

    def test_gui_generic_exception(self):
        """Non-import exception -> returns 1."""
        mock_qt = MagicMock()
        mock_qt.run_app.side_effect = RuntimeError('display error')
        with patch.dict('sys.modules', {'trcc.qt_components.trcc_app': mock_qt}):
            result = gui()
        self.assertEqual(result, 1)

    def test_gui_success(self):
        """Successful launch returns run_app's value."""
        mock_qt = MagicMock()
        mock_qt.run_app.return_value = 0
        with patch.dict('sys.modules', {'trcc.qt_components.trcc_app': mock_qt}):
            result = gui()
        self.assertEqual(result, 0)


class TestGuiExtra(unittest.TestCase):

    def test_gui_import_error(self):
        """PySide6 not importable -> returns 1."""
        with patch.dict('sys.modules', {
            'trcc.qt_components.trcc_app': None,
        }):
            result = gui()
        self.assertEqual(result, 1)


# =========================================================================
# test-display command
# =========================================================================

class TestTestDisplay(unittest.TestCase):
    """Test test_display() command."""

    def test_display_success(self):
        """Cycles through colors and returns 0."""
        svc = _mock_service()
        with patch('trcc.cli._device._get_service', return_value=svc), \
             patch('time.sleep'):
            result = cli_test_display(device='/dev/sg0', loop=False)
        self.assertEqual(result, 0)
        # 7 colors displayed
        self.assertEqual(svc.send_pil.call_count, 7)

    def test_display_error(self):
        """Exception returns 1."""
        with patch('trcc.cli._device._get_service',
                          side_effect=RuntimeError('no device')):
            result = cli_test_display()
        self.assertEqual(result, 1)


class TestTestDisplayExtra(unittest.TestCase):

    def test_keyboard_interrupt(self):
        svc = _mock_service()
        svc.send_pil.side_effect = KeyboardInterrupt
        with patch('trcc.cli._device._get_service', return_value=svc):
            result = cli_test_display()
        self.assertEqual(result, 0)


# =========================================================================
# screencast command
# =========================================================================

class TestScreencast(unittest.TestCase):
    """Tests for _display.screencast()."""

    def test_no_device(self):
        """No device returns 1."""
        svc = _mock_service()
        svc.selected = None
        with patch('trcc.cli._device._get_service', return_value=svc):
            self.assertEqual(_display.screencast(), 1)

    def test_keyboard_interrupt(self):
        """Ctrl+C stops cleanly."""
        svc = _mock_service()
        mock_img = MagicMock()
        with patch('trcc.cli._device._get_service', return_value=svc), \
             patch('PIL.ImageGrab.grab', side_effect=KeyboardInterrupt), \
             patch('trcc.services.ImageService.resize', return_value=mock_img):
            result = _display.screencast()
            self.assertEqual(result, 0)


# =========================================================================
# mask --clear
# =========================================================================

class TestMaskClear(unittest.TestCase):
    """Tests for mask --clear flag."""

    def test_mask_clear_dispatches_to_send_color(self):
        """'mask --clear' sends solid black."""
        with patch('sys.argv', ['trcc', 'mask', '--clear']), \
             patch('trcc.cli._display.send_color',
                          return_value=0) as mock:
            main()
            mock.assert_called_once_with('#000000', device=None, preview=False)

    def test_mask_no_args_errors(self):
        """'mask' with no path and no --clear prints error."""
        buf = io.StringIO()
        with patch('sys.argv', ['trcc', 'mask']), redirect_stdout(buf):
            main()
        self.assertIn('Error: Provide a mask path or use --clear', buf.getvalue())


# =========================================================================
# hid-debug / led-debug diagnostic commands
# =========================================================================

class TestHidDebug(unittest.TestCase):
    """Tests for hid_debug() command."""

    @patch('trcc.adapters.device.detector.detect_devices', return_value=[])
    def test_no_hid_devices(self, _):
        result = hid_debug()
        self.assertEqual(result, 0)

    def test_exception_returns_1(self):
        with patch('trcc.adapters.device.detector.detect_devices', side_effect=Exception("fail")):
            result = hid_debug()
        self.assertEqual(result, 1)

    def test_hid_device_handshake_none(self):
        """LED device found but handshake returns None."""
        from trcc.adapters.detection.factory_detector import DetectedDevice
        dev = DetectedDevice(
            vid=0x0416, pid=0x8001, vendor_name="Winbond",
            product_name="LED Controller", usb_path="1-2",
            implementation="hid_led", protocol="hid", device_type=1,
        )
        mock_protocol = MagicMock()
        mock_protocol.handshake.return_value = None
        mock_protocol.last_error = None
        with patch('trcc.adapters.device.detector.detect_devices', return_value=[dev]), \
             patch('trcc.adapters.device.factory.LedProtocol', return_value=mock_protocol):
            result = hid_debug()
        self.assertEqual(result, 0)
        mock_protocol.close.assert_called_once()

    def test_hid_device_handshake_success(self):
        """LCD device found and handshake succeeds."""
        from trcc.adapters.detection.factory_detector import DetectedDevice
        from trcc.adapters.transport.adapter_hid import HidHandshakeInfo
        dev = DetectedDevice(
            vid=0x0416, pid=0x5302, vendor_name="Winbond",
            product_name="USBDISPLAY", usb_path="1-2",
            implementation="hid_type2", protocol="hid", device_type=2,
        )
        info = HidHandshakeInfo(
            device_type=2, mode_byte_1=100, mode_byte_2=0,
            serial="ABCDEF0123456789", fbl=100,
            resolution=(320, 320), raw_response=bytes(64),
        )
        mock_protocol = MagicMock()
        mock_protocol.handshake.return_value = info
        with patch('trcc.adapters.device.detector.detect_devices', return_value=[dev]), \
             patch('trcc.adapters.device.factory.HidProtocol', return_value=mock_protocol):
            result = hid_debug()
        self.assertEqual(result, 0)

    def test_led_device_handshake_success(self):
        """LED device found and handshake succeeds."""
        from trcc.adapters.detection.factory_detector import DetectedDevice
        from trcc.adapters.transport.adapter_led import LedDeviceStyle, LedHandshakeInfo
        dev = DetectedDevice(
            vid=0x0416, pid=0x8001, vendor_name="Winbond",
            product_name="LED Controller", usb_path="1-2",
            implementation="hid_led", protocol="hid", device_type=1,
        )
        style = LedDeviceStyle(1, 30, 10, 1, "AX120_DIGITAL")
        info = LedHandshakeInfo(
            pm=3, sub_type=0, style=style,
            model_name="AX120_DIGITAL", raw_response=bytes(64),
        )
        mock_protocol = MagicMock()
        mock_protocol.handshake.return_value = info
        with patch('trcc.adapters.device.detector.detect_devices', return_value=[dev]), \
             patch('trcc.adapters.device.factory.LedProtocol', return_value=mock_protocol):
            result = hid_debug()
        self.assertEqual(result, 0)

    def test_hid_device_import_error(self):
        """Import error for pyusb/hidapi shows helpful message."""
        from trcc.adapters.detection.factory_detector import DetectedDevice
        dev = DetectedDevice(
            vid=0x0416, pid=0x8001, vendor_name="Winbond",
            product_name="LED Controller", usb_path="1-2",
            implementation="hid_led", protocol="hid", device_type=1,
        )
        with patch('trcc.adapters.device.detector.detect_devices', return_value=[dev]), \
             patch('trcc.adapters.device.factory.LedProtocol',
                   side_effect=ImportError("No module named 'usb'")):
            result = hid_debug()
        self.assertEqual(result, 0)

    def test_dispatch_hid_debug(self):
        """main() dispatches 'hid-debug' to _diag.hid_debug()."""
        with patch('trcc.cli._diag.hid_debug', return_value=0) as mock_fn, \
             patch('sys.argv', ['trcc', 'hid-debug']):
            result = main()
        self.assertEqual(result, 0)
        mock_fn.assert_called_once()


class TestLedDebug(unittest.TestCase):
    """Tests for led_debug() command."""

    def test_exception_returns_1(self):
        with patch('trcc.adapters.device.factory.LedProtocol',
                   side_effect=Exception("fail")):
            result = led_debug()
        self.assertEqual(result, 1)

    def test_handshake_success(self):
        """Successful LED handshake prints device info."""
        from trcc.adapters.transport.adapter_led import LedDeviceStyle, LedHandshakeInfo
        style = LedDeviceStyle(1, 30, 10, 1, "AX120_DIGITAL")
        info = LedHandshakeInfo(
            pm=3, sub_type=0, style=style,
            model_name="AX120_DIGITAL", raw_response=bytes(64),
        )
        mock_protocol = MagicMock()
        mock_protocol.handshake.return_value = info
        with patch('trcc.adapters.device.factory.LedProtocol', return_value=mock_protocol):
            result = led_debug(test=False)
        self.assertEqual(result, 0)
        mock_protocol.close.assert_called_once()

    def test_handshake_returns_none(self):
        """Handshake returns None -> returns 1."""
        mock_protocol = MagicMock()
        mock_protocol.handshake.return_value = None
        mock_protocol.last_error = RuntimeError("timeout")
        with patch('trcc.adapters.device.factory.LedProtocol', return_value=mock_protocol):
            result = led_debug(test=False)
        self.assertEqual(result, 1)
        mock_protocol.close.assert_called_once()

    def test_test_colors(self):
        """test=True sends test colors via protocol.send_led_data."""
        from trcc.adapters.transport.adapter_led import LedDeviceStyle, LedHandshakeInfo
        style = LedDeviceStyle(1, 30, 10, 1, "AX120_DIGITAL")
        info = LedHandshakeInfo(
            pm=3, sub_type=0, style=style,
            model_name="AX120_DIGITAL", raw_response=bytes(64),
        )
        mock_protocol = MagicMock()
        mock_protocol.handshake.return_value = info
        with patch('trcc.adapters.device.factory.LedProtocol', return_value=mock_protocol), \
             patch('time.sleep'):
            result = led_debug(test=True)
        self.assertEqual(result, 0)
        # 4 colors + OFF = 5 send_led_data calls
        self.assertEqual(mock_protocol.send_led_data.call_count, 5)

    def test_dispatch_led_debug(self):
        """main() dispatches 'led-debug' to _diag.led_debug()."""
        with patch('trcc.cli._diag.led_debug', return_value=0) as mock_fn, \
             patch('sys.argv', ['trcc', 'led-debug']):
            result = main()
        self.assertEqual(result, 0)
        mock_fn.assert_called_once()


# =========================================================================
# Settings helpers (unique — not in test_conf.py)
# =========================================================================

class TestSettingsHelpers(unittest.TestCase):
    """Test conf.py settings persistence helpers."""

    def test_get_selected_no_file(self):
        """Returns None when no config file."""
        with patch('trcc.conf.CONFIG_PATH', '/nonexistent/config.json'):
            from trcc.conf import Settings
            self.assertIsNone(Settings.get_selected_device())

    def test_set_and_get_selected(self):
        """Round-trip: set then get selected device."""
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, 'config.json')
            with patch('trcc.conf.CONFIG_PATH', config_path), \
                 patch('trcc.conf.CONFIG_DIR', tmp):
                from trcc.conf import Settings
                Settings.save_selected_device('/dev/sg1')
                result = Settings.get_selected_device()
            self.assertEqual(result, '/dev/sg1')

    def test_set_preserves_other_keys(self):
        """save_selected_device preserves existing config keys."""
        import json
        with tempfile.TemporaryDirectory() as tmp:
            config_path = os.path.join(tmp, 'config.json')
            # Pre-populate with another key
            with open(config_path, 'w') as f:
                json.dump({'theme': 'dark'}, f)

            with patch('trcc.conf.CONFIG_PATH', config_path), \
                 patch('trcc.conf.CONFIG_DIR', tmp):
                from trcc.conf import Settings
                Settings.save_selected_device('/dev/sg2')

            with open(config_path) as f:
                data = json.load(f)
            self.assertEqual(data['theme'], 'dark')
            self.assertEqual(data['selected_device'], '/dev/sg2')


class TestSettingsCorruptJSON(unittest.TestCase):

    def test_get_corrupt_json(self):
        """Corrupt JSON -> returns None."""
        with tempfile.NamedTemporaryFile(mode='w', suffix='.json', delete=False) as f:
            f.write('{bad json')
            path = f.name
        try:
            with patch('trcc.conf.CONFIG_PATH', path):
                from trcc.conf import Settings
                result = Settings.get_selected_device()
            self.assertIsNone(result)
        finally:
            os.unlink(path)

    def test_set_with_corrupt_existing(self):
        """Set device with corrupt existing file -> overwrites cleanly."""
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, 'config.json')
            with open(path, 'w') as f:
                f.write('{bad')
            with patch('trcc.conf.CONFIG_PATH', path), \
                 patch('trcc.conf.CONFIG_DIR', tmp):
                from trcc.conf import Settings
                Settings.save_selected_device('/dev/sg0')
                result = Settings.get_selected_device()
            self.assertEqual(result, '/dev/sg0')


# ── i18n CLI commands ─────────────────────────────────────────────────


class TestI18nDispatch(unittest.TestCase):
    """Test main() dispatch for lang/lang-set/lang-list commands."""

    @patch('trcc.cli._i18n.get_languages', return_value=0)
    def test_dispatch_lang_list(self, mock_fn):
        with patch('sys.argv', ['trcc', 'lang-list']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._i18n.get_language', return_value=0)
    def test_dispatch_lang(self, mock_fn):
        with patch('sys.argv', ['trcc', 'lang']):
            result = main()
        mock_fn.assert_called_once()
        self.assertEqual(result, 0)

    @patch('trcc.cli._i18n.set_language', return_value=0)
    def test_dispatch_lang_set(self, mock_fn):
        with patch('sys.argv', ['trcc', 'lang-set', 'de']):
            result = main()
        mock_fn.assert_called_once_with('de')
        self.assertEqual(result, 0)


class TestI18nCommands(unittest.TestCase):
    """Test i18n CLI command implementations."""

    @patch('trcc.cli._ensure_renderer')
    @patch('trcc.cli._ensure_settings')
    def test_get_languages_lists_all(self, mock_settings, mock_renderer):
        buf = io.StringIO()
        with redirect_stdout(buf):
            from trcc.cli._i18n import get_languages
            result = get_languages()
        self.assertEqual(result, 0)
        output = buf.getvalue()
        self.assertIn("en", output)
        self.assertIn("English", output)
        self.assertIn("de", output)
        self.assertIn("Deutsch", output)

    @patch('trcc.conf.settings')
    @patch('trcc.cli._ensure_renderer')
    @patch('trcc.cli._ensure_settings')
    def test_get_language_shows_current(self, mock_settings_fn, mock_renderer,
                                        mock_settings):
        mock_settings.lang = 'ja'
        buf = io.StringIO()
        with redirect_stdout(buf):
            from trcc.cli._i18n import get_language
            result = get_language()
        self.assertEqual(result, 0)
        output = buf.getvalue()
        self.assertIn("ja", output)

    @patch('trcc.conf.settings')
    @patch('trcc.cli._ensure_renderer')
    @patch('trcc.cli._ensure_settings')
    def test_set_language_valid(self, mock_settings_fn, mock_renderer,
                                mock_settings):
        buf = io.StringIO()
        with redirect_stdout(buf):
            from trcc.cli._i18n import set_language
            result = set_language('de')
        self.assertEqual(result, 0)
        self.assertEqual(mock_settings.lang, 'de')
        self.assertIn("Deutsch", buf.getvalue())

    @patch('trcc.cli._ensure_renderer')
    @patch('trcc.cli._ensure_settings')
    def test_set_language_invalid(self, mock_settings, mock_renderer):
        buf = io.StringIO()
        with redirect_stdout(buf):
            from trcc.cli._i18n import set_language
            result = set_language('zzz')
        self.assertEqual(result, 1)
        self.assertIn("Unknown", buf.getvalue())


if __name__ == '__main__':
    unittest.main()
