"""macOS platform adapter — implements PlatformAdapter for macOS."""
from __future__ import annotations

import logging
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

log = logging.getLogger(__name__)


class MacOSPlatform(PlatformAdapter):
    """All macOS-specific adapter wiring in one place."""

    def create_detect_fn(self) -> Callable[[], List[DetectedDevice]]:
        log.debug("create_detect_fn: building macOS pyusb detect fn")
        from trcc.adapters.device.detector import DeviceDetector
        return DeviceDetector.make_detect_fn(scsi_resolver=None)  # macOS: pyusb direct

    def create_sensor_enumerator(self) -> SensorEnumerator:
        log.debug("create_sensor_enumerator: creating MacOSSensorEnumerator")
        from trcc.adapters.system.macos.sensors import MacOSSensorEnumerator
        return MacOSSensorEnumerator()

    def create_autostart_manager(self) -> AutostartManager:
        log.debug("create_autostart_manager: creating MacOSAutostartManager")
        from trcc.adapters.system.macos.autostart import MacOSAutostartManager
        return MacOSAutostartManager()

    def create_setup(self) -> PlatformSetup:
        log.debug("create_setup: creating MacOSSetup")
        from trcc.adapters.system.macos.setup import MacOSSetup
        return MacOSSetup()

    def get_memory_info_fn(self) -> GetMemoryInfoFn:
        from trcc.adapters.system.macos.hardware import get_memory_info
        return get_memory_info

    def get_disk_info_fn(self) -> GetDiskInfoFn:
        from trcc.adapters.system.macos.hardware import get_disk_info
        return get_disk_info

    def configure_scsi_protocol(self, factory: Any) -> None:
        log.debug("configure_scsi_protocol: wiring MacOSScsiProtocol")
        from trcc.adapters.device.macos.scsi_protocol import MacOSScsiProtocol
        factory.configure_scsi(
            lambda di: MacOSScsiProtocol(di.path, vid=di.vid, pid=di.pid)
        )
