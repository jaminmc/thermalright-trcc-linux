"""Linux platform adapter — implements PlatformAdapter for Linux."""
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


class LinuxPlatform(PlatformAdapter):
    """All Linux-specific adapter wiring in one place."""

    def create_detect_fn(self) -> Callable[[], List[DetectedDevice]]:
        from trcc.adapters.device.detector import DeviceDetector
        from trcc.adapters.device.linux.detector import linux_scsi_resolver
        return DeviceDetector.make_detect_fn(scsi_resolver=linux_scsi_resolver)

    def create_sensor_enumerator(self) -> SensorEnumerator:
        from trcc.adapters.system.linux.sensors import SensorEnumerator as LinuxSensorEnumerator
        return LinuxSensorEnumerator()

    def create_autostart_manager(self) -> AutostartManager:
        from trcc.adapters.system.linux.autostart import LinuxAutostartManager
        return LinuxAutostartManager()

    def create_setup(self) -> PlatformSetup:
        from trcc.adapters.system.linux.setup import LinuxSetup
        return LinuxSetup()

    def get_memory_info_fn(self) -> GetMemoryInfoFn:
        from trcc.adapters.system.linux.hardware import get_memory_info
        return get_memory_info

    def get_disk_info_fn(self) -> GetDiskInfoFn:
        from trcc.adapters.system.linux.hardware import get_disk_info
        return get_disk_info

    def configure_scsi_protocol(self, factory: Any) -> None:
        pass  # Linux uses the default SCSI protocol
