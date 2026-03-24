"""Windows SCSI protocol — DeviceIoControl implementation.

Implements DeviceProtocol for SCSI LCD devices on Windows using
WindowsScsiTransport (DeviceIoControl) instead of Linux sg_raw/SG_IO.
"""
from __future__ import annotations

import logging
import time
from typing import Any, Optional

from trcc.core.models import HandshakeResult, fbl_to_resolution

from ..factory import DeviceProtocol, ProtocolInfo

log = logging.getLogger(__name__)


class WindowsScsiProtocol(DeviceProtocol):
    """LCD communication via Windows SCSI passthrough (DeviceIoControl).

    The device_path is a PhysicalDrive path (e.g. \\\\.\\PhysicalDrive1).
    Keeps the transport handle open for the lifetime of the protocol.
    """

    def __init__(self, device_path: str, vid: int = 0, pid: int = 0):
        super().__init__()
        self._path = device_path
        self._vid = vid
        self._pid = pid
        self._transport: Any = None

    def _get_transport(self):
        """Get or create persistent WindowsScsiTransport handle."""
        if self._transport is None or self._transport._handle is None:
            from .scsi import WindowsScsiTransport
            self._transport = WindowsScsiTransport(self._path)
            if not self._transport.open():
                log.error("Failed to open Windows SCSI device %s", self._path)
                self._transport = None
                return None
        return self._transport

    def _do_handshake(self) -> Optional[HandshakeResult]:
        """Poll + init Windows SCSI device — same sequence as Linux.

        1. Poll (cmd=0xF5) → read 0xE100 bytes → FBL = response[0]
        2. Boot state check (bytes[4:8] == 0xA1A2A3A4 → wait, re-poll)
        3. Init (cmd=0x1F5) → write 0xE100 zeros
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
                        "Windows SCSI %s still booting (attempt %d/%d)",
                        self._path, attempt + 1, _BOOT_MAX_RETRIES,
                    )
                    time.sleep(_BOOT_WAIT_SECONDS)
                else:
                    break

            if response:
                fbl = response[0]
                log.info(
                    "Windows SCSI poll OK: FBL=%d (VID=%04X PID=%04X)",
                    fbl, self._vid, self._pid,
                )
            else:
                from trcc.core.models import SCSI_DEVICES
                entry = SCSI_DEVICES[(self._vid, self._pid)]
                fbl = entry.fbl
                log.warning(
                    "Windows SCSI poll returned empty on %s (VID=%04X PID=%04X)"
                    " — using registry FBL %d",
                    self._path, self._vid, self._pid, fbl,
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
            log.exception("Windows SCSI handshake failed on %s", self._path)
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
            log.exception("Windows SCSI send_image failed")
            return False

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def get_info(self) -> ProtocolInfo:
        return ProtocolInfo(
            protocol="scsi",
            device_type=1,
            protocol_display="SCSI (Windows DeviceIoControl)",
            device_type_display="SCSI RGB565",
            active_backend="DeviceIoControl",
            backends={"DeviceIoControl": True, "sg_raw": False},
        )

    @property
    def protocol_name(self) -> str:
        return "scsi"

    @property
    def is_available(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"WindowsScsiProtocol(path={self._path!r})"
