"""Tests for Windows SCSI passthrough transport (mocked — runs on Linux).

Tests verify the ctypes structure layout and transport logic without
requiring Windows. Actual DeviceIoControl calls are mocked.
"""
from __future__ import annotations

import ctypes
from unittest.mock import MagicMock, patch

import pytest

MODULE = 'trcc.adapters.device.windows.scsi'


# ── Structure Layout Tests ────────────────────────────────────────────


class TestScsiStructures:
    """Verify ctypes structure sizes and field offsets."""

    @pytest.fixture(autouse=True)
    def _skip_on_linux(self):
        """Skip structure tests on Linux (ctypes.wintypes not available)."""
        try:
            import ctypes.wintypes  # noqa: F401
        except (ImportError, ValueError):
            pytest.skip("ctypes.wintypes not available on Linux")

    def test_sptd_has_cdb_field(self):
        from trcc.adapters.transport.bridge_windows import SCSI_PASS_THROUGH_DIRECT
        sptd = SCSI_PASS_THROUGH_DIRECT()
        assert hasattr(sptd, 'Cdb')
        assert len(sptd.Cdb) == 16

    def test_sptd_with_buffer_has_sense(self):
        from trcc.adapters.transport.bridge_windows import (
            SCSI_PASS_THROUGH_DIRECT_WITH_BUFFER,
        )
        sptdwb = SCSI_PASS_THROUGH_DIRECT_WITH_BUFFER()
        assert hasattr(sptdwb, 'sense')
        assert len(sptdwb.sense) == 32


# ── Transport Logic Tests (all platforms) ─────────────────────────────


class TestWindowsScsiTransport:
    """Test transport logic with mocked Windows API."""

    def _make_transport(self):
        """Create transport, mocking ctypes.wintypes import."""
        wintypes = MagicMock()
        wintypes.USHORT = ctypes.c_ushort
        wintypes.ULONG = ctypes.c_ulong
        wintypes.DWORD = ctypes.c_ulong

        import sys
        sys.modules['ctypes.wintypes'] = wintypes

        try:
            # Re-import to pick up mocked wintypes
            import importlib
            mod = importlib.import_module(MODULE)
            importlib.reload(mod)
            return mod.WindowsScsiTransport('\\\\.\\PhysicalDrive2')
        finally:
            sys.modules.pop('ctypes.wintypes', None)

    def test_init_stores_path(self):
        transport = self._make_transport()
        assert transport._device_path == '\\\\.\\PhysicalDrive2'
        assert transport._handle is None

    def test_send_cdb_fails_when_not_open(self):
        transport = self._make_transport()
        result = transport.send_cdb(b'\xef\x01', b'\x00' * 512)
        assert result is False

    def test_close_noop_when_not_open(self):
        transport = self._make_transport()
        transport.close()  # Should not raise
        assert transport._handle is None

    def test_context_manager(self):
        transport = self._make_transport()
        with patch.object(transport, 'open') as mock_open, \
             patch.object(transport, 'close') as mock_close:
            with transport:
                pass
            mock_open.assert_called_once()
            mock_close.assert_called_once()

    def test_open_sets_handle_none_on_failure(self):
        transport = self._make_transport()
        # Simulate CreateFileW returning -1 (INVALID_HANDLE_VALUE)
        mock_kernel32 = MagicMock()
        mock_kernel32.CreateFileW.return_value = -1

        mock_windll = MagicMock()
        mock_windll.kernel32 = mock_kernel32

        with patch('ctypes.windll', mock_windll, create=True):
            result = transport.open()

        assert result is False
        assert transport._handle is None
