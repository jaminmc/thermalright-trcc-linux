"""Contract tests for MacOSPlatform — verifies it fulfils PlatformAdapter.

Runs on Linux. Each OS-specific concrete class is mocked at its import
path so the lazy `from X import Y` inside each factory method resolves
to a controllable spec-mock that inherits from the correct port ABC.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from trcc.adapters.system.macos.platform import MacOSPlatform
from trcc.core.ports import (
    AutostartManager,
    PlatformAdapter,
    PlatformSetup,
    SensorEnumerator,
)


class TestMacOSPlatformIsAdapter:
    def test_is_platform_adapter(self):
        assert isinstance(MacOSPlatform(), PlatformAdapter)


class TestMacOSPlatformContract:
    """Each factory method calls the right constructor and returns its result."""

    def setup_method(self):
        self._p = MacOSPlatform()

    def test_create_detect_fn_returns_callable(self):
        mock_detect_fn = MagicMock(return_value=[])
        with patch(
            'trcc.adapters.device.detector.DeviceDetector.make_detect_fn',
            return_value=mock_detect_fn,
        ):
            fn = self._p.create_detect_fn()
        assert callable(fn)

    def test_create_detect_fn_passes_none_scsi_resolver(self):
        """macOS uses pyusb direct — scsi_resolver must be None."""
        with patch(
            'trcc.adapters.device.detector.DeviceDetector.make_detect_fn',
        ) as mock_make:
            mock_make.return_value = MagicMock()
            self._p.create_detect_fn()
        mock_make.assert_called_once_with(scsi_resolver=None)

    def test_create_sensor_enumerator_returns_sensor_enumerator(self):
        mock_instance = MagicMock(spec=SensorEnumerator)
        with patch(
            'trcc.adapters.system.macos.sensors.MacOSSensorEnumerator',
            return_value=mock_instance,
        ):
            result = self._p.create_sensor_enumerator()
        assert result is mock_instance

    def test_create_autostart_manager_returns_autostart_manager(self):
        mock_instance = MagicMock(spec=AutostartManager)
        with patch(
            'trcc.adapters.system.macos.autostart.MacOSAutostartManager',
            return_value=mock_instance,
        ):
            result = self._p.create_autostart_manager()
        assert result is mock_instance

    def test_create_setup_returns_platform_setup(self):
        mock_instance = MagicMock(spec=PlatformSetup)
        with patch(
            'trcc.adapters.system.macos.setup.MacOSSetup',
            return_value=mock_instance,
        ):
            result = self._p.create_setup()
        assert result is mock_instance

    def test_get_memory_info_fn_returns_callable(self):
        mock_fn = MagicMock(return_value=[])
        with patch('trcc.adapters.system.macos.hardware.get_memory_info', mock_fn):
            fn = self._p.get_memory_info_fn()
        assert callable(fn)

    def test_get_disk_info_fn_returns_callable(self):
        mock_fn = MagicMock(return_value=[])
        with patch('trcc.adapters.system.macos.hardware.get_disk_info', mock_fn):
            fn = self._p.get_disk_info_fn()
        assert callable(fn)

    def test_configure_scsi_protocol_wires_macos_scsi(self):
        """macOS must call factory.configure_scsi with a MacOSScsiProtocol factory."""
        import sys
        factory = MagicMock()
        mock_scsi_module = MagicMock()
        sys.modules['trcc.adapters.device.macos.scsi_protocol'] = mock_scsi_module
        try:
            self._p.configure_scsi_protocol(factory)
        finally:
            sys.modules.pop('trcc.adapters.device.macos.scsi_protocol', None)

        factory.configure_scsi.assert_called_once()
        scsi_factory_fn = factory.configure_scsi.call_args[0][0]
        assert callable(scsi_factory_fn)

    def test_configure_scsi_protocol_passes_path_vid_pid(self):
        """The SCSI factory lambda extracts path/vid/pid from DeviceInfo."""
        import sys
        factory = MagicMock()
        mock_protocol_cls = MagicMock()
        mock_scsi_module = MagicMock()
        mock_scsi_module.MacOSScsiProtocol = mock_protocol_cls
        sys.modules['trcc.adapters.device.macos.scsi_protocol'] = mock_scsi_module
        try:
            self._p.configure_scsi_protocol(factory)
        finally:
            sys.modules.pop('trcc.adapters.device.macos.scsi_protocol', None)

        scsi_factory_fn = factory.configure_scsi.call_args[0][0]
        device_info = MagicMock()
        device_info.path = '/dev/disk2'
        device_info.vid = 0x0402
        device_info.pid = 0x3922
        scsi_factory_fn(device_info)

        mock_protocol_cls.assert_called_once_with(
            device_info.path, vid=device_info.vid, pid=device_info.pid
        )
