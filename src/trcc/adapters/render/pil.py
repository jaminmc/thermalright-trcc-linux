"""PIL/Pillow rendering backend — CPU-only, headless.

Extracts the PIL calls previously inline in OverlayService into the
Renderer ABC interface.  Now accepts numpy arrays at all entry points
and returns numpy — matching the numpy-native OverlayService contract.
PIL is used internally for drawing ops; numpy↔PIL conversion happens
at this adapter boundary (CLI cold path, not performance-critical).
"""
from __future__ import annotations

from typing import Any

import numpy as np
from PIL import Image, ImageDraw

from ...core.ports import Renderer
from ..infra.font_resolver import FontResolver


def _ensure_pil(surface: Any, mode: str = 'RGBA') -> Image.Image:
    """Convert numpy array to PIL if needed."""
    if isinstance(surface, np.ndarray):
        return Image.fromarray(surface)
    return surface


def _ensure_numpy(surface: Any) -> np.ndarray:
    """Convert PIL Image to numpy if needed."""
    if isinstance(surface, np.ndarray):
        return surface
    return np.array(surface)


class PilRenderer(Renderer):
    """CPU-only renderer using PIL/Pillow.

    Used by CLI, API, and as default fallback when no Qt is available.
    Accepts and returns numpy arrays — converts to PIL internally for ops.
    """

    def __init__(self) -> None:
        self._fonts = FontResolver()

    # ── Surface lifecycle ─────────────────────────────────────────

    def create_surface(self, width: int, height: int,
                       color: tuple[int, ...] | None = None) -> Any:
        if color:
            return np.array(Image.new('RGB', (width, height), color))
        return np.zeros((height, width, 4), dtype=np.uint8)

    def copy_surface(self, surface: Any) -> Any:
        if isinstance(surface, np.ndarray):
            return surface.copy()
        return np.array(surface.copy())

    def convert_to_rgba(self, surface: Any) -> Any:
        if isinstance(surface, np.ndarray):
            if surface.ndim == 3 and surface.shape[2] == 4:
                return surface
            rgba = np.zeros((*surface.shape[:2], 4), dtype=np.uint8)
            rgba[:, :, :3] = surface[:, :, :3]
            rgba[:, :, 3] = 255
            return rgba
        pil = surface.convert('RGBA') if surface.mode != 'RGBA' else surface
        return np.array(pil)

    def convert_to_rgb(self, surface: Any) -> Any:
        if isinstance(surface, np.ndarray):
            if surface.ndim == 3 and surface.shape[2] == 3:
                return surface
            return surface[:, :, :3].copy()
        pil = surface.convert('RGB') if surface.mode != 'RGB' else surface
        return np.array(pil)

    # ── Drawing ───────────────────────────────────────────────────

    def composite(self, base: Any, overlay: Any,
                  position: tuple[int, int],
                  mask: Any | None = None) -> Any:
        pil_base = _ensure_pil(base)
        pil_overlay = _ensure_pil(overlay)
        pil_mask = _ensure_pil(mask) if mask is not None else None
        pil_base.paste(pil_overlay, position, pil_mask or pil_overlay)
        return _ensure_numpy(pil_base)

    def resize(self, surface: Any, width: int, height: int) -> Any:
        pil = _ensure_pil(surface)
        resized = pil.resize((width, height), Image.Resampling.LANCZOS)
        return _ensure_numpy(resized)

    def draw_text(self, surface: Any, x: int, y: int, text: str,
                  color: str, font: Any, anchor: str = 'mm') -> None:
        # draw_text modifies surface in-place — need to handle numpy
        if isinstance(surface, np.ndarray):
            pil = Image.fromarray(surface)
            draw = ImageDraw.Draw(pil)
            draw.text((x, y), text, fill=color, font=font, anchor=anchor)
            surface[:] = np.array(pil)
        else:
            draw = ImageDraw.Draw(surface)
            draw.text((x, y), text, fill=color, font=font, anchor=anchor)

    # ── Fonts ─────────────────────────────────────────────────────

    def get_font(self, size: int, bold: bool = False,
                 font_name: str | None = None) -> Any:
        return self._fonts.get(size, bold, font_name)

    def clear_font_cache(self) -> None:
        self._fonts.clear_cache()

    # ── PIL boundary ──────────────────────────────────────────────

    def to_pil(self, surface: Any) -> Any:
        if isinstance(surface, np.ndarray):
            return Image.fromarray(surface)
        return surface

    def from_pil(self, image: Any) -> Any:
        if isinstance(image, np.ndarray):
            return image
        return np.array(image)
