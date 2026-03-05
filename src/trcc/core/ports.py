"""Core ports — ABCs that define contracts for adapter implementations.

Ports live in core/ so both services/ and adapters/ can import them
without violating hexagonal dependency direction.
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class Renderer(ABC):
    """Port: rendering backend for the full image pipeline.

    Covers overlay compositing, image adjustments (brightness, rotation),
    device encoding (RGB565, JPEG), and file I/O.

    Concrete implementation:
        - QtRenderer (adapters/render/qt.py) — PySide6 QImage/QPainter
    """

    # ── Surface lifecycle ─────────────────────────────────────────

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
    def surface_size(self, surface: Any) -> tuple[int, int]:
        """Return (width, height) of a surface."""

    # ── Compositing ───────────────────────────────────────────────

    @abstractmethod
    def composite(self, base: Any, overlay: Any,
                  position: tuple[int, int],
                  mask: Any | None = None) -> Any:
        """Alpha-composite *overlay* onto *base* at *position*."""

    @abstractmethod
    def resize(self, surface: Any, width: int, height: int) -> Any:
        """Resize surface with high-quality resampling."""

    # ── Text ──────────────────────────────────────────────────────

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

    # ── Image adjustments ─────────────────────────────────────────

    @abstractmethod
    def apply_brightness(self, surface: Any, percent: int) -> Any:
        """Apply brightness adjustment (100 = unchanged, 0 = black)."""

    @abstractmethod
    def apply_rotation(self, surface: Any, degrees: int) -> Any:
        """Rotate surface by 0/90/180/270 degrees."""

    # ── Device encoding ───────────────────────────────────────────

    @abstractmethod
    def encode_rgb565(self, surface: Any, byte_order: str = '>') -> bytes:
        """Encode surface to RGB565 bytes for LCD device."""

    @abstractmethod
    def encode_jpeg(self, surface: Any, quality: int = 95,
                    max_size: int = 450_000) -> bytes:
        """Encode surface to JPEG bytes with size constraint."""

    # ── File I/O ──────────────────────────────────────────────────

    @abstractmethod
    def open_image(self, path: Any) -> Any:
        """Load image file into native surface."""

    # ── Legacy boundary ───────────────────────────────────────────

    @abstractmethod
    def to_pil(self, surface: Any) -> Any:
        """Convert native surface → PIL Image (legacy callers only)."""

    @abstractmethod
    def from_pil(self, image: Any) -> Any:
        """Convert PIL Image → native surface (legacy input only)."""
