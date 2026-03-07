"""ControllerBuilder — assembles devices with dependency injection.

Builder pattern: collects dependencies, validates, returns Device subclasses.
All three adapters (CLI, GUI, API) use this to construct devices.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .ports import Renderer

if TYPE_CHECKING:
    from .lcd_device import LCDDevice
    from .led_device import LEDDevice


class ControllerBuilder:
    """Assembles LCDDevice / LEDDevice with injected deps.

    Usage::

        lcd = (ControllerBuilder()
            .with_renderer(QtRenderer())
            .with_data_dir(data_dir)
            .build_lcd())

        led = ControllerBuilder().build_led()
    """

    def __init__(self) -> None:
        self._renderer: Renderer | None = None
        self._data_dir: Path | None = None

    # ── Fluent setters ─────────────────────────────────────────────

    def with_renderer(self, renderer: Renderer) -> ControllerBuilder:
        """Set rendering backend (QtRenderer for GUI, PIL for CLI/API)."""
        self._renderer = renderer
        return self

    def with_data_dir(self, data_dir: Path) -> ControllerBuilder:
        """Set application data directory (themes, config, masks)."""
        self._data_dir = data_dir
        return self

    # ── Build methods ──────────────────────────────────────────────

    def build_lcd(self) -> LCDDevice:
        """Build and return an LCDDevice.

        Requires: renderer (defaults to QtRenderer if not set).
        Optional: data_dir (triggers initialize).
        """
        from ..services import (
            DeviceService,
            DisplayService,
            MediaService,
            OverlayService,
            ThemeService,
        )
        from ..services.image import ImageService
        from .lcd_device import LCDDevice

        # Renderer must be injected via with_renderer()
        renderer = self._renderer
        if renderer is None:
            raise RuntimeError(
                "ControllerBuilder.with_renderer() must be called before "
                "build_lcd(). Adapters create the renderer.")

        # Wire renderer into ImageService (global facade)
        ImageService.set_renderer(renderer)

        # Create services
        device_svc = DeviceService()
        overlay_svc = OverlayService(renderer=renderer)
        media_svc = MediaService()
        display_svc = DisplayService(device_svc, overlay_svc, media_svc)
        theme_svc = ThemeService()

        # Build LCDDevice with pre-wired services
        lcd = LCDDevice(
            device_svc=device_svc,
            display_svc=display_svc,
            theme_svc=theme_svc,
            renderer=renderer,
        )

        # Initialize if data dir provided
        if self._data_dir:
            lcd.initialize(self._data_dir)

        return lcd

    def build_led(self) -> LEDDevice:
        """Build and return a LEDDevice.

        No required dependencies — LEDService is created on connect.
        """
        from .led_device import LEDDevice
        return LEDDevice()
