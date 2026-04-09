"""macOS SCSI protocol — pyusb USB BOT implementation.

Implements DeviceProtocol for SCSI LCD devices on macOS using
MacOSScsiTransport (pyusb bulk transfers) instead of Linux sg_raw/SG_IO.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from trcc.core.models import HandshakeResult, fbl_to_resolution

from ..factory import DeviceProtocol, ProtocolInfo

log = logging.getLogger(__name__)


class MacOSScsiProtocol(DeviceProtocol):
    """LCD communication via macOS SCSI passthrough (pyusb USB BOT).

    Unlike Linux (sg_raw subprocess) or Windows (DeviceIoControl),
    macOS detaches the kernel driver and sends raw SCSI CDBs as USB
    Bulk-Only Transport transfers via pyusb.

    Requires root privileges and libusb (brew install libusb).
    """

    def __init__(self, device_path: str, vid: int = 0, pid: int = 0):
        super().__init__()
        self._path = device_path
        self._vid = vid
        self._pid = pid
        self._transport: Any = None

    def _get_transport(self):
        """Get or create persistent MacOSScsiTransport handle."""
        if self._transport is None:
            from .scsi import MacOSScsiTransport
            self._transport = MacOSScsiTransport(vid=self._vid, pid=self._pid)
            if not self._transport.open():
                log.error("Failed to open macOS SCSI device (VID=%04X PID=%04X)",
                          self._vid, self._pid)
                self._transport = None
                return None
        return self._transport

    def _do_handshake(self) -> Optional[HandshakeResult]:
        """Init macOS SCSI device and resolve FBL from registry.

        macOS cannot read SCSI poll responses via pyusb bulk transfers,
        so FBL is resolved from the SCSI_DEVICES registry (all known SCSI
        devices are 320x320). Init write (cmd=0x1F5) wakes the device.
        """
        from ..scsi import _POST_INIT_DELAY, ScsiDevice

        transport = self._get_transport()
        if transport is None:
            return None

        try:
            # macOS transport uses pyusb bulk transfers and cannot read
            # SCSI poll responses (send_cdb returns bool, not data).
            # Resolve FBL from the SCSI device registry instead.
            from trcc.core.models import SCSI_DEVICES
            if (entry := SCSI_DEVICES.get((self._vid, self._pid))) is not None:
                fbl = entry.fbl
                log.info(
                    "macOS SCSI using registry FBL %d for VID=%04X PID=%04X",
                    fbl, self._vid, self._pid,
                )
            else:
                fbl = 100  # Default: 320x320 RGB565
                log.warning(
                    "macOS SCSI device VID=%04X PID=%04X not in registry "
                    "-- defaulting to FBL %d",
                    self._vid, self._pid, fbl,
                )

            # Step 2: Init write -- wakes device for frame reception
            init_header = ScsiDevice._build_header(0x1F5, 0xE100)
            transport.send_cdb(init_header[:16], b'\x00' * 0xE100)
            time.sleep(_POST_INIT_DELAY)

            width, height = fbl_to_resolution(fbl)
            return HandshakeResult(
                model_id=fbl,
                resolution=(width, height),
                pm_byte=fbl,
                sub_byte=0,
                raw_response=b'',
            )
        except Exception:
            log.exception("macOS SCSI handshake failed (VID=%04X PID=%04X)",
                          self._vid, self._pid)
            return None

    def send_image(self, image_data: bytes, width: int, height: int) -> bool:
        from ..scsi import ScsiDevice

        transport = self._get_transport()
        if transport is None:
            return False

        try:
            chunks = ScsiDevice._get_frame_chunks(width, height)
            total_size = sum(size for _, size in chunks)
            if len(image_data) < total_size:
                image_data += b'\x00' * (total_size - len(image_data))

            offset = 0
            for cmd, size in chunks:
                header = ScsiDevice._build_header(cmd, size)
                ok = transport.send_cdb(header[:16], image_data[offset:offset + size])
                if not ok:
                    return False
                offset += size
            return True
        except Exception:
            log.exception("macOS SCSI send_image failed")
            return False

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def get_info(self) -> ProtocolInfo:
        return ProtocolInfo(
            protocol="scsi",
            device_type=1,
            protocol_display="SCSI (macOS pyusb BOT)",
            device_type_display="SCSI RGB565",
            active_backend="pyusb",
            backends={"pyusb": True, "sg_raw": False},
        )

    @property
    def protocol_name(self) -> str:
        return "scsi"

    @property
    def is_available(self) -> bool:
        try:
            import usb.core  # pyright: ignore[reportMissingImports]  # noqa: F401
            return True
        except ImportError:
            return False

    def __repr__(self) -> str:
        return (
            f"MacOSScsiProtocol(vid=0x{self._vid:04x}, pid=0x{self._pid:04x})"
        )
