"""PIL/Pillow rendering backend — CPU-only, headless.

Extracts the PIL calls previously inline in OverlayService into the
Renderer ABC interface.  Behaviour is identical to the original code.
"""
from __future__ import annotations

from typing import Any

from PIL import Image, ImageDraw

from ...core.ports import Renderer
from ..infra.font_resolver import FontResolver


class PilRenderer(Renderer):
    """CPU-only renderer using PIL/Pillow.

    Used by CLI, API, and as default fallback when no Qt is available.
    """

    def __init__(self) -> None:
        self._fonts = FontResolver()

    # ── Surface lifecycle ─────────────────────────────────────────

    def create_surface(self, width: int, height: int,
                       color: tuple[int, ...] | None = None) -> Any:
        if color:
            return Image.new('RGB', (width, height), color)
        return Image.new('RGBA', (width, height), (0, 0, 0, 0))

    def copy_surface(self, surface: Any) -> Any:
        return surface.copy()

    def convert_to_rgba(self, surface: Any) -> Any:
        return surface.convert('RGBA') if surface.mode != 'RGBA' else surface

    def convert_to_rgb(self, surface: Any) -> Any:
        return surface.convert('RGB') if surface.mode != 'RGB' else surface

    # ── Drawing ───────────────────────────────────────────────────

    def composite(self, base: Any, overlay: Any,
                  position: tuple[int, int],
                  mask: Any | None = None) -> Any:
        base.paste(overlay, position, mask or overlay)
        return base

    def resize(self, surface: Any, width: int, height: int) -> Any:
        return surface.resize((width, height), Image.Resampling.LANCZOS)

    def draw_text(self, surface: Any, x: int, y: int, text: str,
                  color: str, font: Any, anchor: str = 'mm') -> None:
        draw = ImageDraw.Draw(surface)
        draw.text((x, y), text, fill=color, font=font, anchor=anchor)

    # ── Fonts ─────────────────────────────────────────────────────

    def get_font(self, size: int, bold: bool = False,
                 font_name: str | None = None) -> Any:
        return self._fonts.get(size, bold, font_name)

    def clear_font_cache(self) -> None:
        self._fonts.clear_cache()

    # ── PIL boundary (identity — already PIL) ─────────────────────

    def to_pil(self, surface: Any) -> Any:
        return surface

    def from_pil(self, image: Any) -> Any:
        return image
