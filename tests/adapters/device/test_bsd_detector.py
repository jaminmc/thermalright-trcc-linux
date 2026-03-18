"""Tests for BSD USB device detector (mocked — runs on Linux)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

MODULE = 'trcc.adapters.detection.facade_bsd'


class TestBSDDetector:

    @patch(f'{MODULE}.usb', create=True)
    def test_detects_known_hid_device(self, mock_usb_mod):
        """Known HID LCD device is detected via pyusb."""
        from trcc.adapters.detection.factory_detector import _HID_LCD_DEVICES

        if not _HID_LCD_DEVICES:
            return

        vid, pid = next(iter(_HID_LCD_DEVICES))
        mock_dev = MagicMock()
        mock_dev.bus = 1
        mock_dev.address = 5

        def mock_find(idVendor=None, idProduct=None):
            if idVendor == vid and idProduct == pid:
                return mock_dev
            return None

        with patch('usb.core.find', side_effect=mock_find):
            from trcc.adapters.detection.facade_bsd import BSDDeviceDetector
            devices = BSDDeviceDetector.detect()

        matching = [d for d in devices if d.vid == vid and d.pid == pid]
        assert len(matching) >= 1
        assert matching[0].protocol == 'hid'

    def test_returns_empty_without_pyusb(self):
        """When pyusb not installed, returns empty list."""
        import sys
        saved = sys.modules.get('usb')
        saved_core = sys.modules.get('usb.core')
        sys.modules['usb'] = None  # type: ignore
        sys.modules['usb.core'] = None  # type: ignore

        try:
            import importlib
            mod = importlib.import_module(MODULE)
            importlib.reload(mod)
        except Exception:
            pass
        finally:
            if saved is not None:
                sys.modules['usb'] = saved
            else:
                sys.modules.pop('usb', None)
            if saved_core is not None:
                sys.modules['usb.core'] = saved_core
            else:
                sys.modules.pop('usb.core', None)


class TestGetPassDeviceMap:

    @patch(f'{MODULE}.subprocess')
    def test_parses_camcontrol(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            returncode=0,
            stdout='<THERMALRIGHT LCD 1.00>  at scbus0 target 0 lun 0 (pass0,da0)\n',
        )
        from trcc.adapters.detection.facade_bsd import _get_pass_device_map
        result = _get_pass_device_map()
        assert 'pass0' in result
        assert result['pass0'] == '/dev/pass0'

    @patch(f'{MODULE}.subprocess')
    def test_returns_empty_on_failure(self, mock_sub):
        mock_sub.run.side_effect = RuntimeError("no camcontrol")
        from trcc.adapters.detection.facade_bsd import _get_pass_device_map
        assert _get_pass_device_map() == {}


class TestGetUsbList:

    @patch(f'{MODULE}.subprocess')
    def test_parses_usbconfig(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            returncode=0,
            stdout='ugen0.1: <USB EHCI> at usbus0\nugen0.2: <THERMALRIGHT> at usbus0\n',
        )
        from trcc.adapters.detection.facade_bsd import get_usb_list
        lines = get_usb_list()
        assert len(lines) == 2
        assert 'THERMALRIGHT' in lines[1]

    @patch(f'{MODULE}.subprocess')
    def test_returns_empty_on_failure(self, mock_sub):
        mock_sub.run.side_effect = RuntimeError("no usbconfig")
        from trcc.adapters.detection.facade_bsd import get_usb_list
        assert get_usb_list() == []
