"""Image processing service — delegates to Renderer ABC.

Thin facade over the active Renderer.  Callers use ``ImageService.method()``
without knowing whether Qt or PIL is behind it.  The renderer is set once
at startup via ``set_renderer()``.
"""
from __future__ import annotations

import logging
from typing import Any, ClassVar

from PIL import Image as PILImage  # noqa: F401 — used in to_ansi/metrics_to_ansi

from ..core.ports import Renderer

log = logging.getLogger(__name__)

# Cap decompression to 4x the largest LCD (1920x720).
PILImage.MAX_IMAGE_PIXELS = 1920 * 720 * 4  # 5,529,600 pixels


def _get_draw(img: Any) -> Any:
    """Lazy-import ImageDraw and return a Draw object."""
    from PIL import ImageDraw
    return ImageDraw.Draw(img)


class ImageService:
    """Stateless image processing — delegates to the active Renderer."""

    _renderer: ClassVar[Renderer | None] = None

    @classmethod
    def set_renderer(cls, renderer: Renderer) -> None:
        """Set the active renderer (called once at startup)."""
        cls._renderer = renderer

    @classmethod
    def _r(cls) -> Renderer:
        """Get the active renderer (must be set via set_renderer first)."""
        if cls._renderer is None:
            raise RuntimeError(
                "ImageService.set_renderer() must be called before use. "
                "Use ControllerBuilder to wire dependencies.")
        return cls._renderer

    # ── Encoding (hot path) ───────────────────────────────────────

    @staticmethod
    def to_rgb565(img: Any, byte_order: str = '>') -> bytes:
        """Encode surface to RGB565 bytes."""
        return ImageService._r().encode_rgb565(img, byte_order)

    @staticmethod
    def to_jpeg(img: Any, quality: int = 95,
                max_size: int = 450_000) -> bytes:
        """Encode surface to JPEG bytes with size constraint."""
        return ImageService._r().encode_jpeg(img, quality, max_size)

    # ── Adjustments (hot path) ────────────────────────────────────

    @staticmethod
    def apply_rotation(image: Any, rotation: int) -> Any:
        """Apply display rotation (0/90/180/270)."""
        return ImageService._r().apply_rotation(image, rotation)

    @staticmethod
    def apply_brightness(image: Any, percent: int) -> Any:
        """Apply brightness (0-100, 100 = unchanged)."""
        return ImageService._r().apply_brightness(image, percent)

    # ── Surface creation ──────────────────────────────────────────

    @staticmethod
    def solid_color(r: int, g: int, b: int, w: int, h: int) -> Any:
        """Create a solid-color surface."""
        return ImageService._r().create_surface(w, h, (r, g, b))

    @staticmethod
    def resize(img: Any, w: int, h: int) -> Any:
        """Resize surface to target dimensions."""
        return ImageService._r().resize(img, w, h)

    @staticmethod
    def open_and_resize(path: Any, w: int, h: int) -> Any:
        """Open image file, resize to target dimensions."""
        r = ImageService._r()
        img = r.open_image(path)
        return r.resize(img, w, h)

    # Square resolutions that skip the 90° device pre-rotation.
    _SQUARE_NO_ROTATE = {(240, 240), (320, 320), (480, 480)}

    @staticmethod
    def byte_order_for(protocol: str, resolution: tuple[int, int],
                       fbl: int | None = None) -> str:
        """Determine RGB565 byte order for a device."""
        from ..core.encoding import byte_order_for
        return byte_order_for(protocol, resolution, fbl)

    @staticmethod
    def apply_device_rotation(image: Any,
                              resolution: tuple[int, int]) -> Any:
        """Apply device-level pre-rotation for non-square displays."""
        if resolution in ImageService._SQUARE_NO_ROTATE:
            return image
        return ImageService._r().apply_rotation(image, 90)

    @staticmethod
    def encode_for_device(img: Any, protocol: str,
                          resolution: tuple[int, int],
                          fbl: int | None,
                          use_jpeg: bool) -> bytes:
        """Encode surface for LCD device — JPEG or RGB565."""
        from ..core.models import get_profile

        profile = get_profile(fbl) if fbl is not None else None

        if use_jpeg or (profile and profile.jpeg):
            return ImageService.to_jpeg(img)

        if profile and profile.rotate:
            img = ImageService._r().apply_rotation(img, 90)
        byte_order = profile.byte_order if profile else '<'
        return ImageService.to_rgb565(img, byte_order)

    # ── ANSI preview (CLI cold path — still uses PIL directly) ────

    @staticmethod
    def to_ansi(img: Any, cols: int = 60) -> str:
        """Render surface as ANSI true-color block art for terminal preview."""
        # Convert to PIL for pixel access (CLI-only, not hot path)
        if isinstance(img, PILImage.Image):
            pil_img = img
        else:
            pil_img = ImageService._r().to_pil(img)
        if pil_img.mode != 'RGB':
            pil_img = pil_img.convert('RGB')

        w, h = pil_img.size
        rows = max(1, int(cols * h / w))
        rows += rows % 2
        thumb = pil_img.resize((cols, rows), PILImage.Resampling.LANCZOS)
        pixels = thumb.load()

        lines: list[str] = []
        for y in range(0, rows, 2):
            parts: list[str] = []
            for x in range(cols):
                tr, tg, tb = pixels[x, y]  # type: ignore[index]
                if y + 1 < rows:
                    br, bg_, bb = pixels[x, y + 1]  # type: ignore[index]
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
        """Same as to_ansi() but prefixed with cursor-home escape."""
        return '\033[H' + ImageService.to_ansi(img, cols)

    # Metric groups for ANSI dashboard
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
        """Render HardwareMetrics as ANSI terminal dashboard."""
        from .system import SystemService

        groups = ImageService._METRIC_GROUPS
        if group:
            key = group.lower()
            if key not in groups:
                return f"Unknown group '{group}'. Choose: {', '.join(groups)}"
            items = {key: groups[key]}
        else:
            items = groups

        line_h = 20
        padding = 8
        total_lines = 0
        for _, (_, fields, _) in items.items():
            total_lines += 1
            for f in fields:
                v = getattr(metrics, f, 0.0)
                if v != 0.0 or f in ('date', 'time', 'weekday'):
                    total_lines += 1
        h = max(40, padding + total_lines * line_h + padding)
        w = int(cols * 2.5)

        # ANSI dashboard uses PIL directly (cold path, terminal only)
        img = PILImage.new('RGB', (w, h), (10, 10, 30))
        draw = _get_draw(img)

        y = padding
        for _, (label, fields, color) in items.items():
            draw.text((8, y), label, fill=color)
            y += line_h
            for f in fields:
                v = getattr(metrics, f, 0.0)
                if v == 0.0 and f not in ('date', 'time', 'weekday'):
                    continue
                formatted = SystemService.format_metric(f, v)
                name = f.replace('_', ' ').title()
                draw.text((16, y), f'{name}:', fill=(140, 140, 160))
                draw.text((w // 2, y), formatted, fill=(220, 220, 220))
                if 'percent' in f or 'usage' in f or 'activity' in f:
                    bar_x = w * 3 // 4
                    bar_w = int((w - bar_x - 8) * min(v, 100) / 100)
                    draw.rectangle([bar_x, y + 2, bar_x + bar_w, y + 14],
                                   fill=color)
                    draw.rectangle([bar_x, y + 2, w - 8, y + 14],
                                   outline=(50, 50, 50))
                y += line_h

        return ImageService.to_ansi(img, cols=cols)
