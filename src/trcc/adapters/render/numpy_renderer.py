"""NumPy-backed rendering backend — vectorized SIMD compositing.

Surfaces are ``np.ndarray`` (uint8, shape H×W×C).  Alpha compositing
uses NumPy vectorized ops which dispatch to AVX2/AVX/SSE2 automatically.

PIL is used only for two operations NumPy can't do natively:
  - ``draw_text()``  — freetype font rasterization (cache-miss only, ~1/sec)
  - ``resize()``     — LANCZOS resampling (cache-miss only, ~1/sec)
"""
from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ...core.ports import Renderer
from ..infra.font_resolver import FontResolver


class NumpyRenderer(Renderer):
    """NumPy-backed renderer — vectorized compositing, CPU SIMD.

    Drop-in replacement for PilRenderer via the Renderer ABC.
    Internal surfaces are ``np.ndarray`` instead of ``PIL.Image``.
    """

    def __init__(self) -> None:
        self._fonts = FontResolver()

    # ── Surface lifecycle ─────────────────────────────────────────

    def create_surface(self, width: int, height: int,
                       color: tuple[int, ...] | None = None) -> Any:
        if color:
            arr = np.empty((height, width, 3), dtype=np.uint8)
            arr[:] = color[:3]
            return arr
        return np.zeros((height, width, 4), dtype=np.uint8)

    def copy_surface(self, surface: Any) -> Any:
        return surface.copy()

    def convert_to_rgba(self, surface: Any) -> Any:
        arr: np.ndarray = surface
        if arr.ndim == 3 and arr.shape[2] == 4:
            return arr
        if arr.ndim == 3 and arr.shape[2] == 3:
            alpha = np.full((*arr.shape[:2], 1), 255, dtype=np.uint8)
            return np.concatenate([arr, alpha], axis=2)
        return arr

    def convert_to_rgb(self, surface: Any) -> Any:
        arr: np.ndarray = surface
        if arr.ndim == 3 and arr.shape[2] == 3:
            return arr
        if arr.ndim == 3 and arr.shape[2] == 4:
            return arr[:, :, :3].copy()
        return arr

    # ── Drawing ───────────────────────────────────────────────────

    def composite(self, base: Any, overlay: Any,
                  position: tuple[int, int],
                  mask: Any | None = None) -> Any:
        """Alpha-composite *overlay* onto *base* at *position*.

        Vectorized NumPy blend: ``out = bg * (1-α) + fg * α``.
        Operates in-place on *base* for zero-copy efficiency.
        """
        bg: np.ndarray = base
        fg: np.ndarray = overlay
        x, y = position
        oh, ow = fg.shape[:2]

        # Clip to base bounds
        sy, sx = max(0, y), max(0, x)
        ey = min(bg.shape[0], y + oh)
        ex = min(bg.shape[1], x + ow)
        oy, ox = sy - y, sx - x
        roi_h, roi_w = ey - sy, ex - sx
        if roi_h <= 0 or roi_w <= 0:
            return base

        fg_roi = fg[oy:oy + roi_h, ox:ox + roi_w]
        bg_roi = bg[sy:ey, sx:ex]

        if fg_roi.shape[2] == 4:
            # RGBA overlay — vectorized alpha blend
            alpha = fg_roi[:, :, 3:4].astype(np.float32) * (1.0 / 255.0)
            blended = (
                bg_roi[:, :, :3].astype(np.float32) * (1.0 - alpha)
                + fg_roi[:, :, :3].astype(np.float32) * alpha
            )
            bg_roi[:, :, :3] = blended.astype(np.uint8)
            # Combine alpha channels if base is also RGBA
            if bg_roi.shape[2] == 4:
                bg_roi[:, :, 3] = np.maximum(bg_roi[:, :, 3], fg_roi[:, :, 3])
        else:
            # Opaque overlay — direct copy
            channels = min(bg_roi.shape[2], fg_roi.shape[2])
            bg_roi[:, :, :channels] = fg_roi[:, :, :channels]

        return base

    def resize(self, surface: Any, width: int, height: int) -> Any:
        """Resize via PIL LANCZOS (boundary crossing, cache-miss only)."""
        pil = Image.fromarray(surface)
        resized = pil.resize((width, height), Image.Resampling.LANCZOS)
        return np.array(resized)

    def draw_text(self, surface: Any, x: int, y: int, text: str,
                  color: str, font: Any, anchor: str = 'mm') -> None:
        """Draw text via PIL ImageDraw (boundary crossing, cache-miss only)."""
        pil = Image.fromarray(surface)
        draw = ImageDraw.Draw(pil)
        draw.text((x, y), text, fill=color, font=font, anchor=anchor)
        surface[:] = np.array(pil)

    # ── Fonts ─────────────────────────────────────────────────────

    def get_font(self, size: int, bold: bool = False,
                 font_name: str | None = None) -> Any:
        return self._fonts.get(size, bold, font_name)

    def clear_font_cache(self) -> None:
        self._fonts.clear_cache()

    # ── PIL boundary ──────────────────────────────────────────────

    def to_pil(self, surface: Any) -> Any:
        """Convert numpy surface → PIL Image (boundary exit)."""
        return Image.fromarray(surface)

    def from_pil(self, image: Any) -> Any:
        """Convert PIL Image → numpy surface (boundary entry)."""
        return np.array(image)
