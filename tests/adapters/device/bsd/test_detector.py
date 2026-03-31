"""Tests for BSD device detection utilities (mocked — runs on Linux)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

MODULE = 'trcc.adapters.device.bsd.detector'


class TestGetUsbList:

    @patch(f'{MODULE}.subprocess')
    def test_parses_usbconfig(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            returncode=0,
            stdout='ugen0.1: <USB EHCI> at usbus0\nugen0.2: <THERMALRIGHT> at usbus0\n',
        )
        from trcc.adapters.device.bsd.detector import get_usb_list
        lines = get_usb_list()
        assert len(lines) == 2
        assert 'THERMALRIGHT' in lines[1]

    @patch(f'{MODULE}.subprocess')
    def test_returns_empty_on_failure(self, mock_sub):
        mock_sub.run.side_effect = RuntimeError("no usbconfig")
        from trcc.adapters.device.bsd.detector import get_usb_list
        assert get_usb_list() == []
