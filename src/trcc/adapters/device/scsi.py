"""SCSI LCD protocol adapter — command blocks, frame chunking, boot animation.

Platform-agnostic SCSI protocol logic. Linux SG_IO ioctl lives in
bridge_linux.py; this adapter calls it with sg_raw subprocess fallback.
"""
from __future__ import annotations

import binascii
import logging
import struct
import subprocess
import tempfile
import time
import zlib
from typing import Set

from trcc.adapters.device.frame import FrameDevice
from trcc.adapters.device.linux.scsi import LinuxScsiTransport
from trcc.adapters.infra.data_repository import SysUtils
from trcc.core.models import HandshakeResult, fbl_to_resolution

log = logging.getLogger(__name__)

# Fallback state: None = untested, True/False = tested.
# Controls whether _scsi_read/_scsi_write try SG_IO or fall back to sg_raw.
_sg_io_available: bool | None = None

# Per-device transport instances (keyed by /dev/sgX path)
_transports: dict[str, LinuxScsiTransport] = {}


def _get_transport(dev: str) -> LinuxScsiTransport:
    if dev not in _transports:
        t = LinuxScsiTransport(dev)
        t.open()
        _transports[dev] = t
    return _transports[dev]

# Boot signature: device still initializing its display controller
_BOOT_SIGNATURE = b'\xa1\xa2\xa3\xa4'
_BOOT_WAIT_SECONDS = 3.0
_BOOT_MAX_RETRIES = 5
# Brief pause after init before first frame (lets controller settle)
_POST_INIT_DELAY = 0.1

# Base command for frame data chunks; chunk index goes in bits [27:24]
_FRAME_CMD_BASE = 0x101F5
_CHUNK_SIZE_LARGE = 0x10000  # 64 KiB per chunk for large displays (320x320+)
_CHUNK_SIZE_SMALL = 0xE100   # 57,600 bytes per chunk for small displays (≤320x240)
# Threshold: displays with ≤76,800 pixels (320x240=76,800) use small chunks.
# USBLCD.exe Mode 1 (240x240) and Mode 2 (320x240) use 0xE100 chunks;
# Mode 3 (320x320+) uses 0x10000 chunks.
_SMALL_DISPLAY_PIXELS = 76800

# Boot animation SCSI commands (from USBLCD.exe reverse engineering)
_ANIM_FIRST_FRAME = 0x000201F5   # Compressed first frame (CDB[8]=frame_count)
_ANIM_CAROUSEL = 0x000301F5      # Compressed carousel frame (CDB[3]=delay, CDB[8]=frame_index)
_ANIM_COMPRESS_LEVEL = 3         # zlib compression level (fast, matches USBLCD.exe)
_ANIM_FIRST_DELAY_S = 0.5       # 500ms sleep after first frame
_ANIM_FRAME_DELAY_S = 0.01      # 10ms sleep between carousel frames
_ANIM_MAX_FRAMES = 249           # C# rejects >= 250

# Boot animation supported resolutions (C# returns immediately for others)
_BOOT_ANIM_RESOLUTIONS = {
    (240, 240), (240, 320), (320, 240), (320, 320),
}


# =========================================================================
# SCSI device class
# =========================================================================


class ScsiDevice(FrameDevice):
    """SCSI LCD device handler wrapping sg_raw subprocess calls."""

    # Track which devices have been initialized (poll + init sent)
    _initialized_devices: Set[str] = set()

    def __init__(self, device_path: str, width: int = 0, height: int = 0):
        self.device_path = device_path
        self.width = width
        self.height = height
        self._initialized = False

    # --- Low-level SCSI helpers (Mode 3 protocol) ---

    @staticmethod
    def _get_frame_chunks(width: int, height: int) -> list:
        """Calculate frame chunk commands for a given resolution.

        USBLCD.exe uses different chunk sizes per resolution mode:
          Mode 1/2 (≤320x240): 0xE100 (57,600) byte chunks
          Mode 3   (320x320+): 0x10000 (65,536) byte chunks

        For 240x240: 2 chunks (2×0xE100 = 115,200 bytes)
        For 320x240: 3 chunks (2×0xE100 + 0x9600 = 153,600 bytes)
        For 320x320: 4 chunks (3×0x10000 + 0x2000 = 204,800 bytes)
        For 480x480: 8 chunks (7×0x10000 + 0x2800 = 460,800 bytes)
        """
        pixels = width * height
        chunk_size = (_CHUNK_SIZE_SMALL if pixels <= _SMALL_DISPLAY_PIXELS
                      else _CHUNK_SIZE_LARGE)
        total = pixels * 2  # RGB565: 2 bytes per pixel
        chunks = []
        offset = 0
        idx = 0
        while offset < total:
            size = min(chunk_size, total - offset)
            cmd = _FRAME_CMD_BASE | (idx << 24)
            chunks.append((cmd, size))
            offset += size
            idx += 1
        return chunks

    @staticmethod
    def _crc32(data: bytes) -> int:
        return binascii.crc32(data) & 0xFFFFFFFF

    @staticmethod
    def _build_header(cmd: int, size: int) -> bytes:
        """Build 20-byte SCSI command header: cmd(4) + zeros(8) + size(4) + crc32(4)."""
        header_16 = struct.pack('<I', cmd) + b'\x00' * 8 + struct.pack('<I', size)
        crc = ScsiDevice._crc32(header_16)
        return header_16 + struct.pack('<I', crc)

    @staticmethod
    def _scsi_read(dev: str, cdb: bytes, length: int) -> bytes:
        """Execute SCSI READ via SG_IO ioctl (or sg_raw fallback)."""
        global _sg_io_available
        if _sg_io_available is not False:
            try:
                result = _get_transport(dev).read_cdb(cdb, length)
                _sg_io_available = True
                return result
            except OSError as e:
                if _sg_io_available is None:
                    log.warning("SG_IO read failed (%s: %s), falling back to sg_raw",
                                type(e).__name__, e)
                    _sg_io_available = False

        SysUtils.require_sg_raw()
        cdb_hex = ' '.join(f'{b:02x}' for b in cdb)
        cmd = ['sg_raw', '-r', str(length), dev] + cdb_hex.split()
        result = subprocess.run(cmd, capture_output=True, timeout=10)
        return result.stdout if result.returncode == 0 else b''

    @staticmethod
    def _scsi_write(dev: str, header: bytes, data: bytes) -> bool:
        """Execute SCSI WRITE via SG_IO ioctl (or sg_raw fallback)."""
        global _sg_io_available
        cdb = header[:16]

        if _sg_io_available is not False:
            try:
                ok = _get_transport(dev).send_cdb(cdb, data)
                _sg_io_available = True
                return ok
            except OSError as e:
                if _sg_io_available is None:
                    log.warning("SG_IO ioctl failed (%s: %s), falling back to sg_raw",
                                type(e).__name__, e)
                    _sg_io_available = False

        SysUtils.require_sg_raw()
        cdb_hex = ' '.join(f'{b:02x}' for b in cdb)

        with tempfile.NamedTemporaryFile(delete=True) as f:
            f.write(data)
            f.flush()
            cmd = ['sg_raw', '-s', str(len(data)), '-i', f.name, dev] + cdb_hex.split()
            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            return result.returncode == 0

    @staticmethod
    def _init_device(dev: str) -> tuple[int, bytes]:
        """Poll + init handshake (must be called before first frame send).

        Matches USBLCD.exe initialization sequence:
        1. Poll (cmd=0xF5) -> read 0xE100 bytes
        2. If bytes[4:8] == 0xA1A2A3A4, device is still booting -> wait 3s, re-poll
        3. Init (cmd=0x1F5) -> write 0xE100 zeros
        4. Brief delay to let display controller settle before first frame

        Returns:
            (FBL byte, raw poll response first 64 bytes).
        """
        poll_header = ScsiDevice._build_header(0xF5, 0xE100)

        # Step 1: Poll with boot state check
        response = b''
        for attempt in range(_BOOT_MAX_RETRIES):
            response = ScsiDevice._scsi_read(dev, poll_header[:16], 0xE100)
            if len(response) >= 8 and response[4:8] == _BOOT_SIGNATURE:
                log.info("Device %s still booting (attempt %d/%d), waiting %.0fs...",
                         dev, attempt + 1, _BOOT_MAX_RETRIES, _BOOT_WAIT_SECONDS)
                time.sleep(_BOOT_WAIT_SECONDS)
            else:
                break

        # Extract FBL from poll response byte[0]
        if not response:
            log.warning("SCSI poll returned empty response on %s", dev)
            raise RuntimeError(
                f"SCSI poll returned empty response on {dev}. "
                "Device may not be connected or may need a reboot."
            )
        fbl = response[0]
        log.debug("SCSI poll byte[0] = %d (FBL)", fbl)

        # Step 2: Init
        init_header = ScsiDevice._build_header(0x1F5, 0xE100)
        ScsiDevice._scsi_write(dev, init_header, b'\x00' * 0xE100)

        # Step 3: Brief delay to let display controller settle
        time.sleep(_POST_INIT_DELAY)

        return fbl, response[:64]

    @staticmethod
    def _send_frame(dev: str, rgb565_data: bytes, width: int, height: int):
        """Send one RGB565 frame in SCSI chunks sized for the resolution."""
        chunks = ScsiDevice._get_frame_chunks(width, height)
        total_size = sum(size for _, size in chunks)
        if len(rgb565_data) < total_size:
            rgb565_data += b'\x00' * (total_size - len(rgb565_data))

        offset = 0
        for cmd, size in chunks:
            header = ScsiDevice._build_header(cmd, size)
            ScsiDevice._scsi_write(dev, header, rgb565_data[offset:offset + size])
            offset += size

    @staticmethod
    def _build_anim_header(cmd: int, word2: int, compressed_size: int) -> bytes:
        """Build 20-byte CDB for compressed animation commands (no CRC).

        Layout: [cmd:4][0:4][word2:4][compressed_size:4][0:4]
        Used for 0x201F5 (first frame) and 0x301F5 (carousel frames).
        """
        return struct.pack('<IIIII', cmd, 0, word2, compressed_size, 0)

    @staticmethod
    def _send_boot_animation(
        dev: str,
        frames: list[bytes],
        delays: list[int],
        width: int,
        height: int,
    ) -> bool:
        """Send multi-frame boot animation to device flash via SCSI.

        Matches USBLCD.exe compressed animation upload protocol:
        1. Compress first frame with zlib, send with 0x201F5 (frame_count in CDB[8])
        2. For each subsequent frame, compress and send with 0x301F5
           (delay in CDB[3], frame_index in CDB[8])

        Args:
            dev: SCSI device path (/dev/sgX).
            frames: List of RGB565 byte arrays (one per animation frame).
            delays: Per-frame delays in centiseconds (from GIF metadata).
            width: Frame width in pixels.
            height: Frame height in pixels.

        Returns:
            True if all frames sent successfully.
        """
        if (width, height) not in _BOOT_ANIM_RESOLUTIONS:
            log.warning("Boot animation not supported for %dx%d", width, height)
            return False

        n = len(frames)
        if n == 0 or n >= _ANIM_MAX_FRAMES:
            log.warning("Boot animation frame count %d out of range (1-%d)", n, _ANIM_MAX_FRAMES - 1)
            return False

        # Phase 1: Compress and send first frame
        compressed = zlib.compress(frames[0], _ANIM_COMPRESS_LEVEL)
        header = ScsiDevice._build_anim_header(_ANIM_FIRST_FRAME, n, len(compressed))
        if not ScsiDevice._scsi_write(dev, header, compressed):
            log.error("Boot animation: failed to send first frame")
            return False
        log.info("Boot animation: sent first frame (%d bytes compressed, %d frames total)",
                 len(compressed), n)
        time.sleep(_ANIM_FIRST_DELAY_S)

        # Phase 2: Send each carousel frame
        for i in range(n):
            compressed = zlib.compress(frames[i], _ANIM_COMPRESS_LEVEL)
            # Delay: centiseconds * 10 → milliseconds, capped at 250
            delay_raw = delays[i] if i < len(delays) else 10
            delay_byte = min(delay_raw * 10, 250) & 0xFF
            cmd = _ANIM_CAROUSEL | (delay_byte << 24)
            header = ScsiDevice._build_anim_header(cmd, i, len(compressed))
            if not ScsiDevice._scsi_write(dev, header, compressed):
                log.error("Boot animation: failed to send frame %d", i)
                return False
            time.sleep(_ANIM_FRAME_DELAY_S)

        log.info("Boot animation: all %d frames sent successfully", n)
        return True

    # --- Instance methods ---

    def handshake(self) -> HandshakeResult:
        """Poll + init the SCSI device.

        Reads FBL from poll response byte[0] and resolves
        the actual LCD resolution via fbl_to_resolution().
        """
        fbl, raw = ScsiDevice._init_device(self.device_path)
        resolution = fbl_to_resolution(fbl)
        self.width, self.height = resolution
        self._initialized = True
        log.info("SCSI handshake OK: FBL=%d, resolution=%s", fbl, resolution)
        return HandshakeResult(resolution=resolution, model_id=fbl, raw_response=raw)

    def send_frame(self, rgb565_data: bytes) -> bool:
        """Send one RGB565 frame."""
        if not self._initialized:
            self.handshake()
        ScsiDevice._send_frame(self.device_path, rgb565_data, self.width, self.height)
        return True

    def send_boot_animation(
        self, frames: list[bytes], delays: list[int],
    ) -> bool:
        """Send boot animation to device flash.

        Args:
            frames: List of RGB565 byte arrays (one per frame).
            delays: Per-frame delays in centiseconds (from GIF metadata).
        """
        if not self._initialized:
            self.handshake()
        return ScsiDevice._send_boot_animation(
            self.device_path, frames, delays, self.width, self.height,
        )

    def close(self) -> None:
        """Mark as uninitialized (no persistent resources to release)."""
        self._initialized = False
        ScsiDevice._initialized_devices.discard(self.device_path)


# Detection functions moved to adapters/detection/facade_linux.py.
# Re-exported here for backward compatibility.
from trcc.adapters.device.linux.detector import (  # noqa: F401,E402
    _load_saved_identity,
    find_lcd_devices,
    send_image_to_device,
)
