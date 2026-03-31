"""FreeBSD SCSI protocol — pyusb USB BOT implementation.

Implements DeviceProtocol for SCSI LCD devices on FreeBSD using
BSDScsiTransport (pyusb bulk transfers) instead of Linux sg_raw/SG_IO.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from trcc.core.models import HandshakeResult, fbl_to_resolution

from ..factory import DeviceProtocol, ProtocolInfo

log = logging.getLogger(__name__)


class BSDScsiProtocol(DeviceProtocol):
    """LCD communication via FreeBSD SCSI passthrough (pyusb USB BOT).

    Addresses device by VID:PID (no /dev/passN path needed).
    Keeps the transport open for the lifetime of the protocol.
    """

    def __init__(self, vid: int, pid: int) -> None:
        super().__init__()
        self._vid = vid
        self._pid = pid
        self._transport: Any = None

    def _get_transport(self):
        """Get or create persistent BSDScsiTransport handle."""
        if self._transport is None:
            from .scsi import BSDScsiTransport
            self._transport = BSDScsiTransport(self._vid, self._pid)
            if not self._transport.open():
                log.error("Failed to open BSD SCSI device %04X:%04X",
                          self._vid, self._pid)
                self._transport = None
                return None
        return self._transport

    def _do_handshake(self) -> Optional[HandshakeResult]:
        """Poll + init BSD SCSI device — same sequence as Linux.

        1. Poll (cmd=0xF5) -> read 0xE100 bytes -> FBL = response[0]
        2. Boot state check (bytes[4:8] == 0xA1A2A3A4 -> wait, re-poll)
        3. Init (cmd=0x1F5) -> write 0xE100 zeros
        """
        from ..scsi import (
            _BOOT_MAX_RETRIES,
            _BOOT_SIGNATURE,
            _BOOT_WAIT_SECONDS,
            _POST_INIT_DELAY,
            ScsiDevice,
        )

        transport = self._get_transport()
        if transport is None:
            return None

        try:
            # Step 1: Poll with boot state check
            poll_header = ScsiDevice._build_header(0xF5, 0xE100)
            response = b''
            for attempt in range(_BOOT_MAX_RETRIES):
                response = transport.read_cdb(poll_header[:16], 0xE100)
                if len(response) >= 8 and response[4:8] == _BOOT_SIGNATURE:
                    log.info(
                        "BSD SCSI %04X:%04X still booting (attempt %d/%d)",
                        self._vid, self._pid, attempt + 1, _BOOT_MAX_RETRIES,
                    )
                    time.sleep(_BOOT_WAIT_SECONDS)
                else:
                    break

            if response:
                fbl = response[0]
                log.info(
                    "BSD SCSI poll OK: FBL=%d (VID=%04X PID=%04X)",
                    fbl, self._vid, self._pid,
                )
            else:
                from trcc.core.models import SCSI_DEVICES
                entry = SCSI_DEVICES[(self._vid, self._pid)]
                fbl = entry.fbl
                log.warning(
                    "BSD SCSI poll returned empty (VID=%04X PID=%04X)"
                    " — using registry FBL %d",
                    self._vid, self._pid, fbl,
                )

            # Step 2: Init write — wakes device for frame reception
            init_header = ScsiDevice._build_header(0x1F5, 0xE100)
            transport.send_cdb(init_header[:16], b'\x00' * 0xE100)
            time.sleep(_POST_INIT_DELAY)

            width, height = fbl_to_resolution(fbl)
            return HandshakeResult(
                model_id=fbl,
                resolution=(width, height),
                pm_byte=fbl,
                sub_byte=0,
                raw_response=response[:64],
            )
        except Exception:
            log.exception("BSD SCSI handshake failed (%04X:%04X)",
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
            log.exception("BSD SCSI send_image failed")
            return False

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def get_info(self) -> ProtocolInfo:
        return ProtocolInfo(
            protocol="scsi",
            device_type=1,
            protocol_display="SCSI (FreeBSD pyusb BOT)",
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
        return f"BSDScsiProtocol(vid={self._vid:#06x}, pid={self._pid:#06x})"
