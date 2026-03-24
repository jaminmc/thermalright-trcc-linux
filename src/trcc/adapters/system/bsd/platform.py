"""BSD platform adapter — implements PlatformAdapter for FreeBSD."""
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


class BSDPlatform(PlatformAdapter):
    """All BSD-specific adapter wiring in one place."""

    def create_detect_fn(self) -> Callable[[], List[DetectedDevice]]:
        from trcc.adapters.device.bsd.scsi import bsd_scsi_resolver
        from trcc.adapters.device.detector import DeviceDetector
        return DeviceDetector.make_detect_fn(scsi_resolver=bsd_scsi_resolver)

    def create_sensor_enumerator(self) -> SensorEnumerator:
        from trcc.adapters.system.bsd.sensors import BSDSensorEnumerator
        return BSDSensorEnumerator()

    def create_autostart_manager(self) -> AutostartManager:
        # BSD uses XDG .desktop — same as Linux
        from trcc.adapters.system.linux.autostart import LinuxAutostartManager
        return LinuxAutostartManager()

    def create_setup(self) -> PlatformSetup:
        from trcc.adapters.system.bsd.setup import BSDSetup
        return BSDSetup()

    def get_memory_info_fn(self) -> GetMemoryInfoFn:
        from trcc.adapters.system.bsd.hardware import get_memory_info
        return get_memory_info

    def get_disk_info_fn(self) -> GetDiskInfoFn:
        from trcc.adapters.system.bsd.hardware import get_disk_info
        return get_disk_info

    def configure_scsi_protocol(self, factory: Any) -> None:
        pass  # BSD uses camcontrol — handled by bsd_scsi_resolver in detect_fn
