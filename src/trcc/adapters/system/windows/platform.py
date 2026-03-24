"""Windows platform adapter — implements PlatformAdapter for Windows."""
from __future__ import annotations

from typing import Any, Callable, List

from trcc.core.models import DetectedDevice
from trcc.core.ports import (
    AutostartManager,
    GetDiskInfoFn,
    GetMemoryInfoFn,
    PlatformAdapter,
    PlatformSetup,
    SensorEnumerator,
)


class WindowsPlatform(PlatformAdapter):
    """All Windows-specific adapter wiring in one place."""

    def create_detect_fn(self) -> Callable[[], List[DetectedDevice]]:
        from trcc.adapters.device.windows.detector import WindowsDeviceDetector
        return WindowsDeviceDetector.detect

    def create_sensor_enumerator(self) -> SensorEnumerator:
        from trcc.adapters.system.windows.sensors import WindowsSensorEnumerator
        return WindowsSensorEnumerator()

    def create_autostart_manager(self) -> AutostartManager:
        from trcc.adapters.system.windows.autostart import WindowsAutostartManager
        return WindowsAutostartManager()

    def create_setup(self) -> PlatformSetup:
        from trcc.adapters.system.windows.setup import WindowsSetup
        return WindowsSetup()

    def get_memory_info_fn(self) -> GetMemoryInfoFn:
        from trcc.adapters.system.windows.hardware import get_memory_info
        return get_memory_info

    def get_disk_info_fn(self) -> GetDiskInfoFn:
        from trcc.adapters.system.windows.hardware import get_disk_info
        return get_disk_info

    def configure_scsi_protocol(self, factory: Any) -> None:
        from trcc.adapters.device.windows.scsi_protocol import WindowsScsiProtocol
        factory.configure_scsi(
            lambda di: WindowsScsiProtocol(di.path, vid=di.vid, pid=di.pid)
        )
