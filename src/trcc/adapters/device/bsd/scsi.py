"""FreeBSD SCSI passthrough via pyusb bulk transfers.

On FreeBSD, the umass kernel driver claims USB mass-storage devices.
There is no reliable way to pipe SCSI data-out via camcontrol's CLI,
so we detach the kernel driver and send raw SCSI CDBs as USB
Bulk-Only Transport (BOT) transfers via pyusb.

Same approach as the macOS adapter — pyusb works on FreeBSD because
libusb is part of the base system.

Requires: pkg install py-pyusb (libusb is in base FreeBSD)
"""
from __future__ import annotations

import logging
import struct
from typing import Any, Optional

log = logging.getLogger(__name__)

# USB Bulk-Only Transport (BOT) constants
CBW_SIGNATURE = 0x43425355  # Command Block Wrapper
CBW_SIZE = 31
CSW_SIZE = 13


class BSDScsiTransport:
    """Send raw SCSI commands to a USB mass-storage device on FreeBSD.

    Uses pyusb bulk transfers with USB BOT (Bulk-Only Transport) protocol.
    The umass kernel driver must be detached first (requires root).

    Usage:
        transport = BSDScsiTransport(vid=0x0416, pid=0x5020)
        transport.open()
        transport.send_cdb(cdb_bytes, data_bytes)
        transport.close()
    """

    def __init__(self, vid: int, pid: int) -> None:
        self._vid = vid
        self._pid = pid
        self._dev: Any = None
        self._ep_out: Optional[int] = None
        self._ep_in: Optional[int] = None
        self._tag = 0

    def open(self) -> bool:
        """Find device, detach kernel driver, claim interface."""
        try:
            import usb.core  # pyright: ignore[reportMissingImports]
            import usb.util  # pyright: ignore[reportMissingImports]
        except ImportError:
            log.error("pyusb not installed — pkg install py-pyusb")
            return False

        dev: Any = usb.core.find(idVendor=self._vid, idProduct=self._pid)
        if dev is None:
            log.error("Device %04X:%04X not found", self._vid, self._pid)
            return False

        try:
            # FreeBSD umass driver claims USB mass-storage — detach it
            if dev.is_kernel_driver_active(0):
                dev.detach_kernel_driver(0)
                log.info("Detached FreeBSD kernel driver for %04X:%04X",
                         self._vid, self._pid)

            dev.set_configuration()

            # Find bulk endpoints
            cfg = dev.get_active_configuration()
            intf = cfg[(0, 0)]
            for ep in intf:
                if usb.util.endpoint_direction(ep.bEndpointAddress) == \
                        usb.util.ENDPOINT_OUT:
                    self._ep_out = ep.bEndpointAddress
                elif usb.util.endpoint_direction(ep.bEndpointAddress) == \
                        usb.util.ENDPOINT_IN:
                    self._ep_in = ep.bEndpointAddress

            if self._ep_out is None or self._ep_in is None:
                log.error("Could not find bulk endpoints")
                return False

            self._dev = dev
            return True

        except Exception:
            log.exception("Failed to open BSD SCSI device %04X:%04X",
                          self._vid, self._pid)
            return False

    def close(self) -> None:
        """Release interface and re-attach kernel driver."""
        if self._dev is not None:
            try:
                import usb.util  # pyright: ignore[reportMissingImports]
                usb.util.dispose_resources(self._dev)
                try:
                    self._dev.attach_kernel_driver(0)
                except Exception:
                    pass
            except Exception:
                pass
            self._dev = None

    def send_cdb(
        self,
        cdb: bytes,
        data: bytes,
        *,
        timeout: int = 5000,
    ) -> bool:
        """Send a SCSI CDB with data payload via USB BOT.

        Args:
            cdb: SCSI Command Descriptor Block (6-16 bytes)
            data: Data to send (frame bytes for LCD)
            timeout: Timeout in milliseconds

        Returns:
            True if transfer succeeded
        """
        if self._dev is None or self._ep_out is None:
            log.error("BSD SCSI device not open")
            return False

        self._tag += 1

        # Build Command Block Wrapper (CBW)
        cbw = struct.pack(
            '<IIIBBB',
            CBW_SIGNATURE,
            self._tag,
            len(data),
            0x00,  # Direction: host-to-device
            0,     # LUN
            len(cdb),
        )
        cbw += cdb.ljust(16, b'\x00')

        try:
            # Send CBW
            self._dev.write(self._ep_out, cbw, timeout=timeout)

            # Send data
            if data:
                self._dev.write(self._ep_out, data, timeout=timeout)

            # Read CSW (Command Status Wrapper)
            csw = self._dev.read(self._ep_in, CSW_SIZE, timeout=timeout)
            if len(csw) >= CSW_SIZE:
                status = csw[12]
                if status != 0:
                    log.warning("SCSI command status %d", status)
                    return False
            return True

        except Exception:
            log.exception("BSD SCSI transfer failed")
            return False

    def read_cdb(
        self,
        cdb: bytes,
        length: int,
        *,
        timeout: int = 5000,
    ) -> bytes:
        """Send a SCSI CDB and read data-in via USB BOT.

        Args:
            cdb: SCSI Command Descriptor Block (6-16 bytes)
            length: Number of bytes to read
            timeout: Timeout in milliseconds

        Returns:
            Response bytes, or empty bytes on failure.
        """
        if self._dev is None or self._ep_out is None or self._ep_in is None:
            log.error("BSD SCSI device not open")
            return b''

        self._tag += 1

        # Build CBW for data-in transfer
        cbw = struct.pack(
            '<IIIBBB',
            CBW_SIGNATURE,
            self._tag,
            length,
            0x80,  # Direction: device-to-host
            0,     # LUN
            len(cdb),
        )
        cbw += cdb.ljust(16, b'\x00')

        try:
            # Send CBW
            self._dev.write(self._ep_out, cbw, timeout=timeout)

            # Read data
            data = bytes(self._dev.read(self._ep_in, length, timeout=timeout))

            # Read CSW
            csw = self._dev.read(self._ep_in, CSW_SIZE, timeout=timeout)
            if len(csw) >= CSW_SIZE and csw[12] != 0:
                log.warning("SCSI read command status %d", csw[12])
                return b''

            return data

        except Exception:
            log.exception("BSD SCSI read failed")
            return b''

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
