"""RGB565 encoding utilities — pure functions, no I/O.

These live in core so both services and adapters can import them
without violating hexagonal dependency direction.
"""
from __future__ import annotations

import struct

# SCSI resolutions that use big-endian RGB565 (is320x320 in C#).
# FBL 100/101/102 → 320x320 → big-endian.
# FBL 51 → 320x240 also big-endian (SPIMode=2), but handled via fbl param.
# FBL 50 → 320x240 does NOT trigger SPIMode=2 (little-endian).
_SCSI_BIG_ENDIAN = {(320, 320)}


def byte_order_for(protocol: str, resolution: tuple[int, int],
                   fbl: int | None = None) -> str:
    """Determine RGB565 byte order for a device.

    C# ImageTo565 byte-order logic:
      - is320x320 (FBL 100/101/102) → big-endian
      - myDeviceSPIMode==2 → big-endian (SCSI FBL 51, HID Type 3 FBL 53)
      - else → little-endian

    SCSI: big-endian for 320x320 (FBL 100/101/102) and FBL 51 (320x240
    SPIMode=2).  FBL 50 → 320x240 does NOT trigger SPIMode=2 → little-endian.
    HID/Bulk: big-endian for 320x320 (is320x320) and FBL 53 (SPIMode=2).
    """
    if protocol == 'scsi':
        if fbl == 51:  # SPIMode=2: 320x240 big-endian
            return '>'
        return '>' if resolution in _SCSI_BIG_ENDIAN else '<'
    # HID/Bulk: 320x320 or FBL 53 (Type 3 SPIMode=2) → big-endian
    if fbl == 53:
        return '>'
    return '>' if resolution == (320, 320) else '<'


def rgb_to_bytes(r: int, g: int, b: int, byte_order: str = '>') -> bytes:
    """Convert single RGB pixel to RGB565 bytes."""
    pixel = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
    return struct.pack(f'{byte_order}H', pixel)
