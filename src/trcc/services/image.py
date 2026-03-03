"""Image processing service — RGB565, JPEG, rotation, brightness.

Pure Python (PIL + numpy), no Qt or GUI dependencies.
Absorbed from controllers.py: image_to_rgb565(), apply_rotation(),
_apply_brightness(), byte_order_for().
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image as PILImage

# Cap decompression to 4x the largest LCD (1920x720). Prevents decompression
# bombs from crafted theme images causing OOM.
PILImage.MAX_IMAGE_PIXELS = 1920 * 720 * 4  # 5,529,600 pixels


def _get_draw(img: Any) -> Any:
    """Lazy-import ImageDraw and return a Draw object."""
    from PIL import ImageDraw
    return ImageDraw.Draw(img)


class ImageService:
    """Stateless image processing utilities."""

    # Cached JPEG quality from last successful encode.  Avoids repeated
    # trial encodes for video/screencast where frame complexity is stable.
    # C# CompressionImage() does the same loop from 95→5 every frame;
    # we short-circuit by starting at the last-known-good quality.
    _jpeg_quality_hint: int = 95

    @staticmethod
    def to_rgb565(img: Any, byte_order: str = '>') -> bytes:
        """Convert image to RGB565 bytes.

        Accepts numpy arrays (RGB/RGBA) or PIL Images.
        Windows TRCC ImageTo565: big-endian for 320x320 SCSI,
        little-endian otherwise.

        Args:
            img: numpy array (H×W×3 RGB) or PIL Image.
            byte_order: '>' for big-endian, '<' for little-endian.
        """
        if isinstance(img, np.ndarray):
            arr = img
            if arr.ndim == 3 and arr.shape[2] == 4:
                arr = arr[:, :, :3]  # strip alpha
        else:
            if img.mode != 'RGB':
                img = img.convert('RGB')
            arr = np.array(img)

        arr = arr.astype(np.uint16)
        r = (arr[:, :, 0] >> 3) & 0x1F
        g = (arr[:, :, 1] >> 2) & 0x3F
        b = (arr[:, :, 2] >> 3) & 0x1F
        rgb565 = (r << 11) | (g << 5) | b
        return rgb565.astype(f'{byte_order}u2').tobytes()

    @staticmethod
    def to_jpeg(img: Any, quality: int = 95, max_size: int = 450_000) -> bytes:
        """Compress image to JPEG bytes.

        Accepts numpy arrays (RGB/RGBA) or PIL Images. Numpy is converted
        to PIL at the encode boundary (PIL/turbojpeg needed for JPEG codec).

        Matches C# CompressionImage(): starts at *quality*, reduces by 5
        until output < *max_size*.  USBLCDNew bulk devices expect JPEG
        (cmd=2) instead of raw RGB565.

        Optimization: starts at the last successful quality level instead
        of always from 95.  For video/screencast where consecutive frames
        have similar complexity, this typically hits on the first try
        (1 encode instead of 4).  If the cached quality is too low (scene
        change to simpler content), we retry from *quality* to find a
        higher-quality encode.
        """
        if isinstance(img, np.ndarray):
            arr = img[:, :, :3] if img.ndim == 3 and img.shape[2] == 4 else img
            img = PILImage.fromarray(arr)
        elif img.mode != 'RGB':
            img = img.convert('RGB')

        hint = ImageService._jpeg_quality_hint

        # Fast path: try cached quality first
        if hint < quality:
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=hint)
            data = buf.getvalue()
            if len(data) < max_size:
                # Scene got simpler — try higher quality
                for q in range(min(quality, hint + 10), hint, -5):
                    buf2 = io.BytesIO()
                    img.save(buf2, format='JPEG', quality=q)
                    d2 = buf2.getvalue()
                    if len(d2) < max_size:
                        ImageService._jpeg_quality_hint = q
                        return d2
                return data

        # Normal path: scan from top quality down
        for q in range(quality, 4, -5):
            buf = io.BytesIO()
            img.save(buf, format='JPEG', quality=q)
            data = buf.getvalue()
            if len(data) < max_size:
                ImageService._jpeg_quality_hint = q
                return data

        # Fallback: minimum quality
        buf = io.BytesIO()
        img.save(buf, format='JPEG', quality=5)
        ImageService._jpeg_quality_hint = 5
        return buf.getvalue()

    @staticmethod
    def apply_rotation(image: Any, rotation: int) -> Any:
        """Apply display rotation to image (numpy or PIL).

        Windows ImageTo565 for square displays:
          directionB 0   → no rotation
          directionB 90  → RotateImg(270°CW) = PIL ROTATE_90 (CCW)
          directionB 180 → RotateImg(180°)   = PIL ROTATE_180
          directionB 270 → RotateImg(90°CW)  = PIL ROTATE_270 (CCW)
        """
        if isinstance(image, np.ndarray):
            if rotation == 90:
                return np.rot90(image, k=-1)  # 90° CW
            elif rotation == 180:
                return np.rot90(image, k=2)
            elif rotation == 270:
                return np.rot90(image, k=1)   # 270° CW = 90° CCW
            return image

        # PIL fallback (CLI one-shot paths)
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
        """Apply brightness adjustment to image (numpy or PIL).

        L1=25%, L2=50%, L3=100%. At 100% the image is unchanged.
        """
        if percent >= 100:
            return image

        if isinstance(image, np.ndarray):
            return (image.astype(np.uint16) * percent // 100).clip(0, 255).astype(np.uint8)

        # PIL fallback (CLI one-shot paths)
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
        """Convert single RGB pixel to RGB565 bytes.

        Delegates to core.encoding (canonical location).
        """
        from ..core.encoding import rgb_to_bytes
        return rgb_to_bytes(r, g, b, byte_order)

    # Square resolutions that skip the 90° device pre-rotation.
    # C# ImageTo565: (is240x240 || is320x320 || is480x480) → use directionB directly.
    # All other resolutions rotate +90° CW before encoding (non-square branch).
    _SQUARE_NO_ROTATE = {(240, 240), (320, 320), (480, 480)}

    @staticmethod
    def byte_order_for(protocol: str, resolution: tuple[int, int],
                       fbl: int | None = None) -> str:
        """Determine RGB565 byte order for a device.

        Delegates to core.encoding (canonical location).
        """
        from ..core.encoding import byte_order_for
        return byte_order_for(protocol, resolution, fbl)

    @staticmethod
    def to_ansi(img: Any, cols: int = 60) -> str:
        """Render image as ANSI true-color block art for terminal preview.

        Uses Unicode half-block (U+2580) to encode two pixel rows per
        terminal line.  Foreground = top pixel, background = bottom pixel.

        Args:
            img: numpy array or PIL Image.
            cols: Output width in terminal columns (height scales proportionally).
        """
        if isinstance(img, np.ndarray):
            img = PILImage.fromarray(img[:, :, :3] if img.ndim == 3 and img.shape[2] == 4 else img)
        if img.mode != 'RGB':
            img = img.convert('RGB')

        w, h = img.size
        rows = max(1, int(cols * h / w))
        # Round rows to even so half-block pairs are complete
        rows += rows % 2
        thumb = img.resize((cols, rows), PILImage.Resampling.LANCZOS)
        pixels = thumb.load()

        lines: list[str] = []
        for y in range(0, rows, 2):
            parts: list[str] = []
            for x in range(cols):
                tr, tg, tb = pixels[x, y]          # top pixel → foreground
                if y + 1 < rows:
                    br, bg_, bb = pixels[x, y + 1]  # bottom pixel → background
                else:
                    br, bg_, bb = 0, 0, 0
                parts.append(
                    f'\033[38;2;{tr};{tg};{tb}m'
                    f'\033[48;2;{br};{bg_};{bb}m\u2580'
                )
            lines.append(''.join(parts) + '\033[0m')
        return '\n'.join(lines)

    @staticmethod
    def to_ansi_cursor_home(img: Any, cols: int = 60) -> str:
        """Same as to_ansi() but prefixed with cursor-home escape for animation."""
        return '\033[H' + ImageService.to_ansi(img, cols)

    # Metric groups for dashboard rendering (label, fields, color)
    _METRIC_GROUPS: dict[str, tuple[str, list[str], tuple[int, int, int]]] = {
        'cpu':  ('CPU',  ['cpu_temp', 'cpu_percent', 'cpu_freq', 'cpu_power'], (0, 200, 255)),
        'gpu':  ('GPU',  ['gpu_temp', 'gpu_usage', 'gpu_clock', 'gpu_power'], (0, 255, 100)),
        'mem':  ('MEM',  ['mem_temp', 'mem_percent', 'mem_clock', 'mem_available'], (255, 200, 0)),
        'disk': ('DISK', ['disk_temp', 'disk_activity', 'disk_read', 'disk_write'], (200, 100, 255)),
        'net':  ('NET',  ['net_up', 'net_down', 'net_total_up', 'net_total_down'], (100, 255, 200)),
        'fan':  ('FAN',  ['fan_cpu', 'fan_gpu', 'fan_ssd', 'fan_sys2'], (255, 80, 80)),
        'time': ('TIME', ['date', 'time', 'weekday'], (180, 180, 255)),
    }

    @staticmethod
    def metrics_to_ansi(metrics: Any, cols: int = 60,
                        group: str | None = None) -> str:
        """Render HardwareMetrics as ANSI terminal dashboard.

        Args:
            metrics: HardwareMetrics dataclass instance.
            cols: Terminal width in columns.
            group: Optional filter — 'cpu', 'gpu', 'mem', 'disk', 'net',
                   'fan', 'time', or None for all.
        """
        from .system import SystemService

        groups = ImageService._METRIC_GROUPS
        if group:
            key = group.lower()
            if key not in groups:
                return f"Unknown group '{group}'. Choose: {', '.join(groups)}"
            items = {key: groups[key]}
        else:
            items = groups

        # Build text dashboard image
        line_h = 20
        padding = 8
        h = padding + len(items) * (line_h + padding)
        # Count non-zero fields to size height properly
        total_lines = 0
        for _, (_, fields, _) in items.items():
            total_lines += 1  # header
            for f in fields:
                v = getattr(metrics, f, 0.0)
                if v != 0.0 or f in ('date', 'time', 'weekday'):
                    total_lines += 1
        h = max(40, padding + total_lines * line_h + padding)
        w = int(cols * 2.5)  # approximate pixel width from cols

        img = PILImage.new('RGB', (w, h), (10, 10, 30))
        draw = _get_draw(img)

        y = padding
        for _, (label, fields, color) in items.items():
            # Group header
            draw.text((8, y), label, fill=color)
            y += line_h
            # Field values
            for f in fields:
                v = getattr(metrics, f, 0.0)
                if v == 0.0 and f not in ('date', 'time', 'weekday'):
                    continue
                formatted = SystemService.format_metric(f, v)
                name = f.replace('_', ' ').title()
                draw.text((16, y), f'{name}:', fill=(140, 140, 160))
                draw.text((w // 2, y), formatted, fill=(220, 220, 220))
                # Bar for percentage metrics
                if 'percent' in f or 'usage' in f or 'activity' in f:
                    bar_x = w * 3 // 4
                    bar_w = int((w - bar_x - 8) * min(v, 100) / 100)
                    draw.rectangle([bar_x, y + 2, bar_x + bar_w, y + 14],
                                   fill=color)
                    draw.rectangle([bar_x, y + 2, w - 8, y + 14],
                                   outline=(50, 50, 50))
                y += line_h

        return ImageService.to_ansi(img, cols=cols)

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

        if isinstance(image, np.ndarray):
            return np.rot90(image, k=-1)  # 90° CW

        return image.transpose(PILImage.Transpose.ROTATE_270)

    @staticmethod
    def encode_for_device(img: Any, protocol: str,
                          resolution: tuple[int, int],
                          fbl: int | None,
                          use_jpeg: bool) -> bytes:
        """Encode PIL image for LCD device — JPEG or RGB565 based on device properties.

        Strategy: Bulk/LY (JPEG-capable) and HID JPEG-mode FBLs use JPEG.
        All others use RGB565 with device pre-rotation and protocol byte order.
        """
        from ..core.models import JPEG_MODE_FBLS, PROTOCOL_TRAITS

        traits = PROTOCOL_TRAITS.get(protocol)
        if (traits and traits.supports_jpeg and use_jpeg) or (
                protocol == 'hid' and fbl in JPEG_MODE_FBLS):
            return ImageService.to_jpeg(img)

        img = ImageService.apply_device_rotation(img, resolution)
        byte_order = ImageService.byte_order_for(protocol, resolution, fbl)
        return ImageService.to_rgb565(img, byte_order)
