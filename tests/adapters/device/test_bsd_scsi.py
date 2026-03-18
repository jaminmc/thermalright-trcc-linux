"""Tests for BSD SCSI transport (mocked — runs on Linux)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

MODULE = 'trcc.adapters.transport.bridge_bsd'


class TestBSDScsiTransport:

    def test_init(self):
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        assert t._device == '/dev/pass0'
        assert t._is_open is False

    def test_send_cdb_fails_when_not_open(self):
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        assert t.send_cdb(b'\xef', b'\x00' * 512) is False

    def test_close_noop_when_not_open(self):
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        t.close()  # Should not raise

    def test_context_manager(self):
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        with patch.object(t, 'open') as m_open, \
             patch.object(t, 'close') as m_close:
            with t:
                pass
            m_open.assert_called_once()
            m_close.assert_called_once()

    @patch(f'{MODULE}.os')
    def test_open_checks_device_exists(self, mock_os):
        mock_os.path.exists.return_value = True
        mock_os.stat.return_value = MagicMock()
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        assert t.open() is True
        assert t._is_open is True

    @patch(f'{MODULE}.os')
    def test_open_fails_if_not_exists(self, mock_os):
        mock_os.path.exists.return_value = False
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        assert t.open() is False

    @patch(f'{MODULE}.subprocess')
    def test_send_cdb_calls_camcontrol(self, mock_sub):
        mock_sub.run.return_value = MagicMock(returncode=0)
        mock_sub.TimeoutExpired = TimeoutError
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        t._is_open = True
        assert t.send_cdb(b'\xef', b'\x00' * 512) is True
        mock_sub.run.assert_called_once()
        call_args = mock_sub.run.call_args
        cmd = call_args[0][0]
        assert cmd[0] == 'camcontrol'
        assert cmd[1] == 'cmd'
        assert cmd[2] == '/dev/pass0'

    @patch(f'{MODULE}.subprocess')
    def test_send_cdb_handles_failure(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            returncode=1,
            stderr=b'CAM error',
        )
        mock_sub.TimeoutExpired = TimeoutError
        from trcc.adapters.transport.bridge_bsd import BSDScsiTransport
        t = BSDScsiTransport('/dev/pass0')
        t._is_open = True
        assert t.send_cdb(b'\xef', b'\x00' * 512) is False
