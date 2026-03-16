"""Windows SCSI passthrough transport.

Replaces Linux sg_raw subprocess calls with Windows DeviceIoControl
IOCTL_SCSI_PASS_THROUGH_DIRECT for sending raw SCSI CDBs to USB
mass-storage LCD devices.

References:
    - C# TRCC: USBLCDNEW.SendSCSICommand() uses CreateFile + DeviceIoControl
    - Windows API: IOCTL_SCSI_PASS_THROUGH_DIRECT (0x4D014)
    - ctypes structs: SCSI_PASS_THROUGH_DIRECT_WITH_BUFFER
"""
from __future__ import annotations

import ctypes
import ctypes.wintypes  # pyright: ignore[reportMissingImports]
import logging
from typing import Optional

log = logging.getLogger(__name__)

# Windows IOCTL codes
IOCTL_SCSI_PASS_THROUGH_DIRECT = 0x4D014

# SCSI directions
SCSI_IOCTL_DATA_OUT = 0  # Host → Device (sending frame data)
SCSI_IOCTL_DATA_IN = 1   # Device → Host (reading response)


class SCSI_PASS_THROUGH_DIRECT(ctypes.Structure):
    """Windows SCSI_PASS_THROUGH_DIRECT structure."""
    _fields_ = [
        ('Length', ctypes.wintypes.USHORT),
        ('ScsiStatus', ctypes.c_ubyte),
        ('PathId', ctypes.c_ubyte),
        ('TargetId', ctypes.c_ubyte),
        ('Lun', ctypes.c_ubyte),
        ('CdbLength', ctypes.c_ubyte),
        ('SenseInfoLength', ctypes.c_ubyte),
        ('DataIn', ctypes.c_ubyte),
        ('DataTransferLength', ctypes.wintypes.ULONG),
        ('TimeOutValue', ctypes.wintypes.ULONG),
        ('DataBuffer', ctypes.c_void_p),
        ('SenseInfoOffset', ctypes.wintypes.ULONG),
        ('Cdb', ctypes.c_ubyte * 16),
    ]


class SCSI_PASS_THROUGH_DIRECT_WITH_BUFFER(ctypes.Structure):
    """SCSI_PASS_THROUGH_DIRECT + sense buffer."""
    _fields_ = [
        ('sptd', SCSI_PASS_THROUGH_DIRECT),
        ('sense', ctypes.c_ubyte * 32),
    ]


class WindowsScsiTransport:
    """Send raw SCSI commands to a USB device on Windows.

    Equivalent to Linux's `sg_raw` subprocess calls but using
    Windows DeviceIoControl with IOCTL_SCSI_PASS_THROUGH_DIRECT.

    Usage:
        transport = WindowsScsiTransport('\\\\.\\PhysicalDrive2')
        transport.open()
        transport.send_cdb(cdb_bytes, data_bytes)
        transport.close()
    """

    def __init__(self, device_path: str) -> None:
        self._device_path = device_path
        self._handle: Optional[int] = None

    def open(self) -> bool:
        """Open the physical drive for SCSI passthrough."""
        try:
            kernel32 = ctypes.windll.kernel32  # pyright: ignore[reportAttributeAccessIssue]
            GENERIC_READ_WRITE = 0xC0000000
            FILE_SHARE_READ_WRITE = 0x3
            OPEN_EXISTING = 3

            self._handle = kernel32.CreateFileW(
                self._device_path,
                GENERIC_READ_WRITE,
                FILE_SHARE_READ_WRITE,
                None,
                OPEN_EXISTING,
                0,
                None,
            )
            if self._handle == -1:
                self._handle = None
                log.error("Failed to open %s", self._device_path)
                return False
            return True
        except Exception:
            log.exception("Failed to open SCSI device %s", self._device_path)
            return False

    def close(self) -> None:
        """Close the device handle."""
        if self._handle is not None:
            try:
                ctypes.windll.kernel32.CloseHandle(self._handle)  # pyright: ignore[reportAttributeAccessIssue]
            except Exception:
                pass
            self._handle = None

    def send_cdb(
        self,
        cdb: bytes,
        data: bytes,
        *,
        timeout: int = 5,
    ) -> bool:
        """Send a SCSI CDB with data payload.

        Args:
            cdb: SCSI Command Descriptor Block (6-16 bytes)
            data: Data to send (frame bytes for LCD)
            timeout: Timeout in seconds

        Returns:
            True if DeviceIoControl succeeded
        """
        if self._handle is None:
            log.error("SCSI device not open")
            return False

        # Allocate data buffer
        data_buf = (ctypes.c_ubyte * len(data))(*data)

        # Build SCSI_PASS_THROUGH_DIRECT
        sptdwb = SCSI_PASS_THROUGH_DIRECT_WITH_BUFFER()
        sptd = sptdwb.sptd
        sptd.Length = ctypes.sizeof(SCSI_PASS_THROUGH_DIRECT)
        sptd.CdbLength = len(cdb)
        sptd.SenseInfoLength = 32
        sptd.DataIn = SCSI_IOCTL_DATA_OUT
        sptd.DataTransferLength = len(data)
        sptd.TimeOutValue = timeout
        sptd.DataBuffer = ctypes.addressof(data_buf)
        sptd.SenseInfoOffset = ctypes.sizeof(SCSI_PASS_THROUGH_DIRECT)

        # Copy CDB bytes
        for i, b in enumerate(cdb[:16]):
            sptd.Cdb[i] = b

        # DeviceIoControl
        bytes_returned = ctypes.wintypes.DWORD(0)
        try:
            ok = ctypes.windll.kernel32.DeviceIoControl(  # pyright: ignore[reportAttributeAccessIssue]
                self._handle,
                IOCTL_SCSI_PASS_THROUGH_DIRECT,
                ctypes.byref(sptdwb),
                ctypes.sizeof(sptdwb),
                ctypes.byref(sptdwb),
                ctypes.sizeof(sptdwb),
                ctypes.byref(bytes_returned),
                None,
            )
            if not ok:
                error = ctypes.GetLastError()  # pyright: ignore[reportAttributeAccessIssue]
                log.error("DeviceIoControl failed: error %d", error)
                return False
            if sptd.ScsiStatus != 0:
                log.warning("SCSI status %d", sptd.ScsiStatus)
                return False
            return True
        except Exception:
            log.exception("SCSI passthrough failed")
            return False

    def read_cdb(
        self,
        cdb: bytes,
        length: int,
        *,
        timeout: int = 5,
    ) -> bytes:
        """Send a SCSI CDB and read response data.

        Args:
            cdb: SCSI Command Descriptor Block (6-16 bytes)
            length: Expected response length in bytes
            timeout: Timeout in seconds

        Returns:
            Response bytes, or empty bytes on failure.
        """
        if self._handle is None:
            log.error("SCSI device not open")
            return b''

        # Allocate receive buffer
        data_buf = (ctypes.c_ubyte * length)()

        # Build SCSI_PASS_THROUGH_DIRECT for read
        sptdwb = SCSI_PASS_THROUGH_DIRECT_WITH_BUFFER()
        sptd = sptdwb.sptd
        sptd.Length = ctypes.sizeof(SCSI_PASS_THROUGH_DIRECT)
        sptd.CdbLength = len(cdb)
        sptd.SenseInfoLength = 32
        sptd.DataIn = SCSI_IOCTL_DATA_IN
        sptd.DataTransferLength = length
        sptd.TimeOutValue = timeout
        sptd.DataBuffer = ctypes.addressof(data_buf)
        sptd.SenseInfoOffset = ctypes.sizeof(SCSI_PASS_THROUGH_DIRECT)

        # Copy CDB bytes
        for i, b in enumerate(cdb[:16]):
            sptd.Cdb[i] = b

        # DeviceIoControl
        bytes_returned = ctypes.wintypes.DWORD(0)
        try:
            ok = ctypes.windll.kernel32.DeviceIoControl(  # pyright: ignore[reportAttributeAccessIssue]
                self._handle,
                IOCTL_SCSI_PASS_THROUGH_DIRECT,
                ctypes.byref(sptdwb),
                ctypes.sizeof(sptdwb),
                ctypes.byref(sptdwb),
                ctypes.sizeof(sptdwb),
                ctypes.byref(bytes_returned),
                None,
            )
            if not ok:
                error = ctypes.GetLastError()  # pyright: ignore[reportAttributeAccessIssue]
                log.error("DeviceIoControl read failed: error %d", error)
                return b''
            if sptd.ScsiStatus != 0:
                log.warning("SCSI read status %d", sptd.ScsiStatus)
                return b''
            return bytes(data_buf)
        except Exception:
            log.exception("SCSI read passthrough failed")
            return b''

    def __enter__(self):
        self.open()
        return self

    def __exit__(self, *exc):
        self.close()
