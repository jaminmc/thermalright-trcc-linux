"""BSD platform adapter — implements PlatformAdapter for FreeBSD."""
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


class BSDPlatform(PlatformAdapter):
    """All BSD-specific adapter wiring in one place."""

    def create_detect_fn(self) -> Callable[[], List[DetectedDevice]]:
        log.debug("create_detect_fn: building BSD pyusb detect fn")
        from trcc.adapters.device.detector import DeviceDetector
        return DeviceDetector.make_detect_fn(scsi_resolver=None)  # BSD: pyusb direct

    def create_sensor_enumerator(self) -> SensorEnumerator:
        log.debug("create_sensor_enumerator: creating BSDSensorEnumerator")
        from trcc.adapters.system.bsd.sensors import BSDSensorEnumerator
        return BSDSensorEnumerator()

    def create_autostart_manager(self) -> AutostartManager:
        # BSD uses XDG .desktop — same as Linux
        log.debug("create_autostart_manager: creating LinuxAutostartManager (BSD)")
        from trcc.adapters.system.linux.autostart import LinuxAutostartManager
        return LinuxAutostartManager()

    def create_setup(self) -> PlatformSetup:
        log.debug("create_setup: creating BSDSetup")
        from trcc.adapters.system.bsd.setup import BSDSetup
        return BSDSetup()

    def get_memory_info_fn(self) -> GetMemoryInfoFn:
        from trcc.adapters.system.bsd.hardware import get_memory_info
        return get_memory_info

    def get_disk_info_fn(self) -> GetDiskInfoFn:
        from trcc.adapters.system.bsd.hardware import get_disk_info
        return get_disk_info

    def configure_scsi_protocol(self, factory: Any) -> None:
        log.debug("configure_scsi_protocol: wiring BSDScsiProtocol")
        from trcc.adapters.device.bsd.scsi_protocol import BSDScsiProtocol
        factory.configure_scsi(
            lambda di: BSDScsiProtocol(vid=di.vid, pid=di.pid)
        )
