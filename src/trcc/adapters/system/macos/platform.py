"""macOS platform adapter — implements PlatformAdapter for macOS."""
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


class MacOSPlatform(PlatformAdapter):
    """All macOS-specific adapter wiring in one place."""

    def create_detect_fn(self) -> Callable[[], List[DetectedDevice]]:
        from trcc.adapters.device.detector import DeviceDetector
        return DeviceDetector.make_detect_fn(scsi_resolver=None)  # macOS: pyusb direct

    def create_sensor_enumerator(self) -> SensorEnumerator:
        from trcc.adapters.system.macos.sensors import MacOSSensorEnumerator
        return MacOSSensorEnumerator()

    def create_autostart_manager(self) -> AutostartManager:
        from trcc.adapters.system.macos.autostart import MacOSAutostartManager
        return MacOSAutostartManager()

    def create_setup(self) -> PlatformSetup:
        from trcc.adapters.system.macos.setup import MacOSSetup
        return MacOSSetup()

    def get_memory_info_fn(self) -> GetMemoryInfoFn:
        from trcc.adapters.system.macos.hardware import get_memory_info
        return get_memory_info

    def get_disk_info_fn(self) -> GetDiskInfoFn:
        from trcc.adapters.system.macos.hardware import get_disk_info
        return get_disk_info

    def configure_scsi_protocol(self, factory: Any) -> None:
        pass  # macOS uses pyusb direct — no SCSI protocol needed
