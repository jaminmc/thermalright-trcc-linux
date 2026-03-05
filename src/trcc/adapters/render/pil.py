"""PIL/Pillow rendering backend — CPU-only, headless fallback.

Kept as a concrete Renderer for environments where PySide6 is not
initialized.  In practice, QtRenderer is the primary implementation.
"""
from __future__ import annotations

import io
from typing import Any

import numpy as np
from PIL import Image, ImageDraw, ImageEnhance

from ...core.ports import Renderer
from ..infra.font_resolver import FontResolver


class PilRenderer(Renderer):
    """CPU-only renderer using PIL/Pillow (fallback)."""

    def __init__(self) -> None:
        self._fonts = FontResolver()
        self._jpeg_quality_hint: int = 95

    # ── Surface lifecycle ─────────────────────────────────────────

    def create_surface(self, width: int, height: int,
                       color: tuple[int, ...] | None = None) -> Any:
        if color is not None and len(color) > 3:
            return Image.new('RGBA', (width, height), color)
        if color is not None:
            return Image.new('RGB', (width, height), color)
        return Image.new('RGBA', (width, height), (0, 0, 0, 0))

    def copy_surface(self, surface: Any) -> Any:
        return surface.copy()

    def convert_to_rgba(self, surface: Any) -> Any:
        return surface.convert('RGBA') if surface.mode != 'RGBA' else surface

    def convert_to_rgb(self, surface: Any) -> Any:
        return surface.convert('RGB') if surface.mode != 'RGB' else surface

    def surface_size(self, surface: Any) -> tuple[int, int]:
        return surface.size

    # ── Compositing ───────────────────────────────────────────────

    def composite(self, base: Any, overlay: Any,
                  position: tuple[int, int],
                  mask: Any | None = None) -> Any:
        base.paste(overlay, position, mask or overlay)
        return base

    def resize(self, surface: Any, width: int, height: int) -> Any:
        return surface.resize((width, height), Image.Resampling.LANCZOS)

    # ── Text ──────────────────────────────────────────────────────

    def draw_text(self, surface: Any, x: int, y: int, text: str,
                  color: str, font: Any, anchor: str = 'mm') -> None:
        draw = ImageDraw.Draw(surface)
        draw.text((x, y), text, fill=color, font=font, anchor=anchor)

    def get_font(self, size: int, bold: bool = False,
                 font_name: str | None = None) -> Any:
        return self._fonts.get(size, bold, font_name)

    def clear_font_cache(self) -> None:
        self._fonts.clear_cache()

    # ── Image adjustments ─────────────────────────────────────────

    def apply_brightness(self, surface: Any, percent: int) -> Any:
        if percent >= 100:
            return surface
        return ImageEnhance.Brightness(surface).enhance(percent / 100.0)

    def apply_rotation(self, surface: Any, degrees: int) -> Any:
        if degrees == 0:
            return surface
        if degrees == 90:
            return surface.transpose(Image.Transpose.ROTATE_270)
        if degrees == 180:
            return surface.transpose(Image.Transpose.ROTATE_180)
        if degrees == 270:
            return surface.transpose(Image.Transpose.ROTATE_90)
        return surface

    # ── Device encoding ───────────────────────────────────────────

    def encode_rgb565(self, surface: Any, byte_order: str = '>') -> bytes:
        if surface.mode != 'RGB':
            surface = surface.convert('RGB')
        arr = np.array(surface, dtype=np.uint16)
        r = (arr[:, :, 0] >> 3) & 0x1F
        g = (arr[:, :, 1] >> 2) & 0x3F
        b = (arr[:, :, 2] >> 3) & 0x1F
        rgb565 = (r << 11) | (g << 5) | b
        return rgb565.astype(f'{byte_order}u2').tobytes()

    def encode_jpeg(self, surface: Any, quality: int = 95,
                    max_size: int = 450_000) -> bytes:
        if surface.mode != 'RGB':
            surface = surface.convert('RGB')
        hint = self._jpeg_quality_hint

        # Fast path: try cached quality first
        if hint < quality:
            buf = io.BytesIO()
            surface.save(buf, format='JPEG', quality=hint)
            data = buf.getvalue()
            if len(data) < max_size:
                for q in range(min(quality, hint + 10), hint, -5):
                    buf2 = io.BytesIO()
                    surface.save(buf2, format='JPEG', quality=q)
                    d2 = buf2.getvalue()
                    if len(d2) < max_size:
                        self._jpeg_quality_hint = q
                        return d2
                return data

        # Normal path: scan from top quality down
        for q in range(quality, 4, -5):
            buf = io.BytesIO()
            surface.save(buf, format='JPEG', quality=q)
            data = buf.getvalue()
            if len(data) < max_size:
                self._jpeg_quality_hint = q
                return data

        # Fallback: minimum quality
        buf = io.BytesIO()
        surface.save(buf, format='JPEG', quality=5)
        self._jpeg_quality_hint = 5
        return buf.getvalue()

    # ── File I/O ──────────────────────────────────────────────────

    def open_image(self, path: Any) -> Any:
        img = Image.open(path)
        if img.mode != 'RGB':
            img = img.convert('RGB')
        return img

    # ── Legacy boundary (identity — already PIL) ──────────────────

    def to_pil(self, surface: Any) -> Any:
        return surface

    def from_pil(self, image: Any) -> Any:
        return image
