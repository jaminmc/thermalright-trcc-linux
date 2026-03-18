"""Tests for macOS USB device detector (mocked — runs on Linux)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

MODULE = 'trcc.adapters.detection.facade_macos'


class TestMacOSDetector:

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
            from trcc.adapters.detection.facade_macos import MacOSDeviceDetector
            devices = MacOSDeviceDetector.detect()

        matching = [d for d in devices if d.vid == vid and d.pid == pid]
        assert len(matching) >= 1
        assert matching[0].protocol == 'hid'

    def test_returns_empty_without_pyusb(self):
        """When pyusb not installed, returns empty list."""
        import sys
        # Temporarily hide usb module
        saved = sys.modules.get('usb')
        saved_core = sys.modules.get('usb.core')
        sys.modules['usb'] = None  # type: ignore
        sys.modules['usb.core'] = None  # type: ignore

        try:
            import importlib
            mod = importlib.import_module(MODULE)
            importlib.reload(mod)
            # This will hit ImportError
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


class TestGetUsbTree:

    @patch(f'{MODULE}.subprocess')
    def test_parses_json(self, mock_sub):
        import json
        mock_sub.run.return_value = MagicMock(
            returncode=0,
            stdout=json.dumps({'SPUSBDataType': [{'_name': 'USB 3.0 Bus'}]}),
        )
        from trcc.adapters.detection.facade_macos import get_usb_tree
        tree = get_usb_tree()
        assert len(tree) == 1
        assert tree[0]['_name'] == 'USB 3.0 Bus'

    @patch(f'{MODULE}.subprocess')
    def test_returns_empty_on_failure(self, mock_sub):
        mock_sub.run.side_effect = RuntimeError("no system_profiler")
        from trcc.adapters.detection.facade_macos import get_usb_tree
        assert get_usb_tree() == []
