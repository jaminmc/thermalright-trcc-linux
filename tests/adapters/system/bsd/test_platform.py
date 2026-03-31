"""Contract tests for BSDPlatform — verifies it fulfils PlatformAdapter.

Runs on Linux. Each OS-specific concrete class is mocked at its import
path so the lazy `from X import Y` inside each factory method resolves
to a controllable spec-mock that inherits from the correct port ABC.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from trcc.adapters.system.bsd.platform import BSDPlatform
from trcc.core.ports import (
    AutostartManager,
    PlatformAdapter,
    PlatformSetup,
    SensorEnumerator,
)


class TestBSDPlatformIsAdapter:
    def test_is_platform_adapter(self):
        assert isinstance(BSDPlatform(), PlatformAdapter)


class TestBSDPlatformContract:
    """Each factory method calls the right constructor and returns its result."""

    def setup_method(self):
        self._p = BSDPlatform()

    def test_create_detect_fn_returns_callable(self):
        mock_detect_fn = MagicMock(return_value=[])
        with patch(
            'trcc.adapters.device.detector.DeviceDetector.make_detect_fn',
            return_value=mock_detect_fn,
        ):
            fn = self._p.create_detect_fn()
        assert callable(fn)

    def test_create_detect_fn_passes_no_scsi_resolver(self):
        """BSD uses pyusb direct — must pass scsi_resolver=None."""
        with patch(
            'trcc.adapters.device.detector.DeviceDetector.make_detect_fn',
        ) as mock_make:
            mock_make.return_value = MagicMock()
            self._p.create_detect_fn()
        mock_make.assert_called_once_with(scsi_resolver=None)

    def test_create_sensor_enumerator_returns_sensor_enumerator(self):
        mock_instance = MagicMock(spec=SensorEnumerator)
        with patch(
            'trcc.adapters.system.bsd.sensors.BSDSensorEnumerator',
            return_value=mock_instance,
        ):
            result = self._p.create_sensor_enumerator()
        assert result is mock_instance

    def test_create_autostart_manager_returns_linux_manager(self):
        """BSD reuses LinuxAutostartManager (XDG .desktop)."""
        result = self._p.create_autostart_manager()
        assert isinstance(result, AutostartManager)
        # Confirm it's the Linux XDG implementation, not a BSD-specific one
        assert type(result).__name__ == 'LinuxAutostartManager'

    def test_create_setup_returns_platform_setup(self):
        mock_instance = MagicMock(spec=PlatformSetup)
        with patch(
            'trcc.adapters.system.bsd.setup.BSDSetup',
            return_value=mock_instance,
        ):
            result = self._p.create_setup()
        assert result is mock_instance

    def test_get_memory_info_fn_returns_callable(self):
        mock_fn = MagicMock(return_value=[])
        with patch('trcc.adapters.system.bsd.hardware.get_memory_info', mock_fn):
            fn = self._p.get_memory_info_fn()
        assert callable(fn)

    def test_get_disk_info_fn_returns_callable(self):
        mock_fn = MagicMock(return_value=[])
        with patch('trcc.adapters.system.bsd.hardware.get_disk_info', mock_fn):
            fn = self._p.get_disk_info_fn()
        assert callable(fn)

    def test_configure_scsi_protocol_wires_bsd_protocol(self):
        """BSD must wire BSDScsiProtocol into the factory."""
        factory = MagicMock()
        self._p.configure_scsi_protocol(factory)
        factory.configure_scsi.assert_called_once()
        # Verify the lambda produces a BSDScsiProtocol with correct vid/pid
        factory_fn = factory.configure_scsi.call_args[0][0]
        mock_di = MagicMock(path='usb:1:2', vid=0x0402, pid=0x3922)
        from trcc.adapters.device.bsd.scsi_protocol import BSDScsiProtocol
        result = factory_fn(mock_di)
        assert isinstance(result, BSDScsiProtocol)
        assert result._vid == 0x0402
        assert result._pid == 0x3922
