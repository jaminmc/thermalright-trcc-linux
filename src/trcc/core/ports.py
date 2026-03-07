"""Core ports — ABCs that define contracts for adapter implementations.

Ports live in core/ so both services/ and adapters/ can import them
without violating hexagonal dependency direction.

SOLID:
    S — Each ABC has one responsibility
    O — New device types extend Device without modifying existing code
    L — LCDDevice/LEDDevice fully substitutable as Device
    I — Device ABC: 4 methods. Renderer ABC: domain-focused groups.
        Replaces DisplayPort (47) and LEDPort (30) — ISP violations.
    D — All adapters depend on these core abstractions
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Protocol, runtime_checkable


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


# =========================================================================
# Device ABC — minimal contract for all Thermalright devices (ISP)
# =========================================================================


class Device(ABC):
    """Base device contract — sidebar, CLI, API all depend on this.

    Minimal interface (ISP): only what ALL devices share.
    Brightness is device-type-specific (LCD backlight vs LED strip),
    so it lives on LCDDevice/LEDDevice, not here.

    Concrete implementations:
        - LCDDevice (core/lcd_device.py) — LCD display devices
        - LEDDevice (core/led_device.py) — LED segment display devices
    """

    @abstractmethod
    def connect(self, detected: Any = None) -> dict:
        """Connect to device. Handshakes via protocol, fills DeviceInfo from models.

        Returns: {"success": bool, "message": str, ...}
        """

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether device is connected and ready."""

    @property
    @abstractmethod
    def device_info(self) -> Any:
        """DeviceInfo — models hold all device state."""

    @abstractmethod
    def cleanup(self) -> None:
        """Release resources on shutdown."""


# =========================================================================
# Infrastructure port types — injected into services via DI
# =========================================================================

# Type alias for device detection callable.
# Concrete: DeviceDetector.detect
DetectDevicesFn = Callable[[], list[Any]]

# Type alias for LED model probe callable.
# Concrete: probe_led_model
ProbeLedModelFn = Callable[..., Any]


@runtime_checkable
class DeviceProtocol(Protocol):
    """Port: protocol for communicating with a USB device."""

    def handshake(self) -> Any: ...
    def send_image(self, data: bytes, width: int, height: int) -> bool: ...


# Type alias for protocol factory callable.
# Concrete: DeviceProtocolFactory.get_protocol
GetProtocolFn = Callable[[Any], DeviceProtocol]

