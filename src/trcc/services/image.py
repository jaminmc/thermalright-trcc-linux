"""Image processing service — RGB565, JPEG, rotation, brightness.

Pure Python (PIL + numpy), no Qt or GUI dependencies.
Absorbed from controllers.py: image_to_rgb565(), apply_rotation(),
_apply_brightness(), byte_order_for().
"""
from __future__ import annotations

import io
import struct
from typing import Any

import numpy as np
from PIL import Image as PILImage

# Cap decompression to 4x the largest LCD (1920x720). Prevents decompression
# bombs from crafted theme images causing OOM.
PILImage.MAX_IMAGE_PIXELS = 1920 * 720 * 4  # 5,529,600 pixels


class ImageService:
    """Stateless image processing utilities."""

    @staticmethod
    def to_rgb565(img: Any, byte_order: str = '>') -> bytes:
        """Convert PIL Image to RGB565 bytes.

        Windows TRCC ImageTo565: big-endian for 320x320 SCSI,
        little-endian otherwise.

        Args:
            img: PIL Image.
            byte_order: '>' for big-endian, '<' for little-endian.
        """
        if img.mode != 'RGB':
            img = img.convert('RGB')

        arr = np.array(img, dtype=np.uint16)
        r = (arr[:, :, 0] >> 3) & 0x1F
        g = (arr[:, :, 1] >> 2) & 0x3F
        b = (arr[:, :, 2] >> 3) & 0x1F
        rgb565 = (r << 11) | (g << 5) | b
        return rgb565.astype(f'{byte_order}u2').tobytes()

    @staticmethod
    def to_jpeg(img: Any, quality: int = 95, max_size: int = 450_000) -> bytes:
        """Compress PIL Image to JPEG bytes.

        Matches C# CompressionImage(): starts at *quality*, reduces by 5
        until output < *max_size*.  USBLCDNew bulk devices expect JPEG
        (cmd=2) instead of raw RGB565.
        """
        if img.mode != 'RGB':
            img = img.convert('RGB')

        for q in range(quality, 4, -5):
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=q)
            data = buf.getvalue()
            if len(data) < max_size:
                return data

        # Fallback: minimum quality
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=5)
        return buf.getvalue()

    @staticmethod
    def apply_rotation(image: Any, rotation: int) -> Any:
        """Apply display rotation to a PIL Image.

        Windows ImageTo565 for square displays:
          directionB 0   → no rotation
          directionB 90  → RotateImg(270°CW) = PIL ROTATE_90 (CCW)
          directionB 180 → RotateImg(180°)   = PIL ROTATE_180
          directionB 270 → RotateImg(90°CW)  = PIL ROTATE_270 (CCW)
        """
        from PIL import Image as PILImage

        if rotation == 90:
            return image.transpose(PILImage.Transpose.ROTATE_270)
        elif rotation == 180:
            return image.transpose(PILImage.Transpose.ROTATE_180)
        elif rotation == 270:
            return image.transpose(PILImage.Transpose.ROTATE_90)
        return image

    @staticmethod
    def apply_brightness(image: Any, percent: int) -> Any:
        """Apply brightness adjustment to image.

        L1=25%, L2=50%, L3=100%. At 100% the image is unchanged.
        """
        if percent >= 100:
            return image
        from PIL import ImageEnhance

        return ImageEnhance.Brightness(image).enhance(percent / 100.0)

    @staticmethod
    def solid_color(r: int, g: int, b: int, w: int, h: int) -> Any:
        """Create a solid-color PIL Image."""
        from PIL import Image as PILImage

        return PILImage.new('RGB', (w, h), (r, g, b))

    @staticmethod
    def resize(img: Any, w: int, h: int) -> Any:
        """Resize PIL Image to target dimensions."""
        from PIL import Image as PILImage

        return img.resize((w, h), PILImage.Resampling.LANCZOS)

    @staticmethod
    def open_and_resize(path: Any, w: int, h: int) -> Any:
        """Open image file, resize to target dimensions, ensure RGB mode."""
        img = PILImage.open(path)
        img = img.resize((w, h), PILImage.Resampling.LANCZOS)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return img

    @staticmethod
    def rgb_to_bytes(r: int, g: int, b: int, byte_order: str = '>') -> bytes:
        """Convert single RGB pixel to RGB565 bytes."""
        pixel = ((r & 0xF8) << 8) | ((g & 0xFC) << 3) | (b >> 3)
        return struct.pack(f'{byte_order}H', pixel)

    # SCSI resolutions that use big-endian RGB565 (is320x320 in C#).
    # FBL 100/101/102 → 320x320 → big-endian.
    # FBL 51 → 320x240 also big-endian (SPIMode=2), but handled via fbl param.
    # FBL 50 → 320x240 does NOT trigger SPIMode=2 (little-endian).
    _SCSI_BIG_ENDIAN = {(320, 320)}

    # Square resolutions that skip the 90° device pre-rotation.
    # C# ImageTo565: (is240x240 || is320x320 || is480x480) → use directionB directly.
    # All other resolutions rotate +90° CW before encoding (non-square branch).
    _SQUARE_NO_ROTATE = {(240, 240), (320, 320), (480, 480)}

    @staticmethod
    def byte_order_for(protocol: str, resolution: tuple[int, int],
                       fbl: int | None = None) -> str:
        """Determine RGB565 byte order for a device.

        C# ImageTo565 byte-order logic:
          - is320x320 (FBL 100/101/102) → big-endian
          - myDeviceSPIMode==2 → big-endian (SCSI mode 1 + FBL 51)
          - else → little-endian

        SCSI: big-endian for 320x320 (FBL 100/101/102) and FBL 51 (320x240
        SPIMode=2).  FBL 50 → 320x240 does NOT trigger SPIMode=2 → little-endian.
        HID/Bulk: big-endian only for 320x320 (is320x320 in C#).
        """
        if protocol == 'scsi':
            if fbl == 51:  # SPIMode=2: 320x240 big-endian
                return '>'
            return '>' if resolution in ImageService._SCSI_BIG_ENDIAN else '<'
        # HID/Bulk: only 320x320 uses big-endian (is320x320 in C#)
        return '>' if resolution == (320, 320) else '<'

    @staticmethod
    def apply_device_rotation(image: Any, resolution: tuple[int, int]) -> Any:
        """Apply device-level pre-rotation for non-square displays.

        C# ImageTo565 rotation for directionB=0:
          - Square (240x240, 320x320, 480x480): no rotation
          - Non-square: +90° CW (RotateImg(90°))

        This base rotation is applied AFTER user rotation (directionB) and
        BEFORE RGB565/JPEG encoding.  Non-square LCD panels are physically
        mounted in portrait orientation; the 90° rotation converts landscape
        frame data to the portrait layout the firmware expects.
        """
        if resolution in ImageService._SQUARE_NO_ROTATE:
            return image
        return image.transpose(PILImage.Transpose.ROTATE_270)
