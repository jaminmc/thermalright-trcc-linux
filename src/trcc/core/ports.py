"""Core ports — ABCs that define contracts for adapter implementations.

Ports live in core/ so both services/ and adapters/ can import them
without violating hexagonal dependency direction.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Renderer(ABC):
    """Port: rendering backend for overlay compositing.

    Concrete implementations:
        - PilRenderer  (adapters/render/pil.py)  — PIL/Pillow, CPU-only
        - QPainterRenderer (adapters/render/qt.py) — PySide6 QPainter, GPU-capable
    """

    @abstractmethod
    def create_surface(self, width: int, height: int,
                       color: tuple[int, ...] | None = None) -> Any:
        """Create a new rendering surface (blank transparent or solid color)."""

    @abstractmethod
    def copy_surface(self, surface: Any) -> Any:
        """Defensive copy of a surface."""

    @abstractmethod
    def convert_to_rgba(self, surface: Any) -> Any:
        """Ensure surface has alpha channel."""

    @abstractmethod
    def convert_to_rgb(self, surface: Any) -> Any:
        """Ensure surface is RGB (strip alpha)."""

    @abstractmethod
    def composite(self, base: Any, overlay: Any,
                  position: tuple[int, int],
                  mask: Any | None = None) -> Any:
        """Alpha-composite *overlay* onto *base* at *position*."""

    @abstractmethod
    def resize(self, surface: Any, width: int, height: int) -> Any:
        """Resize surface with high-quality resampling."""

    @abstractmethod
    def draw_text(self, surface: Any, x: int, y: int, text: str,
                  color: str, font: Any, anchor: str = 'mm') -> None:
        """Draw text onto surface at (x, y)."""

    @abstractmethod
    def get_font(self, size: int, bold: bool = False,
                 font_name: str | None = None) -> Any:
        """Resolve and cache a font at given size."""

    @abstractmethod
    def clear_font_cache(self) -> None:
        """Flush font cache (e.g. after resolution change)."""

    @abstractmethod
    def to_pil(self, surface: Any) -> Any:
        """Convert native surface → PIL Image (boundary output)."""

    @abstractmethod
    def from_pil(self, image: Any) -> Any:
        """Convert PIL Image → native surface."""
