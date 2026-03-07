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
        from ..adapters.device.detector import DeviceDetector
        from ..adapters.device.factory import DeviceProtocolFactory
        from ..adapters.device.led import probe_led_model
        from ..adapters.infra.data_repository import DataManager
        from ..adapters.infra.dc_config import DcConfig
        from ..adapters.infra.dc_parser import load_config_json
        from ..adapters.infra.dc_writer import export_theme, import_theme
        from ..adapters.infra.media_player import ThemeZtDecoder, VideoDecoder
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

        # Create services with injected adapter dependencies
        device_svc = DeviceService(
            detect_fn=DeviceDetector.detect,
            probe_led_fn=probe_led_model,
            get_protocol=DeviceProtocolFactory.get_protocol,
            get_protocol_info=DeviceProtocolFactory.get_protocol_info,
        )
        overlay_svc = OverlayService(
            renderer=renderer,
            load_config_json_fn=load_config_json,
            dc_config_cls=DcConfig,
        )
        media_svc = MediaService(
            video_decoder_cls=VideoDecoder,
            zt_decoder_cls=ThemeZtDecoder,
        )
        theme_svc = ThemeService(
            ensure_data_fn=DataManager.ensure_all,
            export_theme_fn=export_theme,
            import_theme_fn=import_theme,
            load_config_json_fn=load_config_json,
            dc_config_cls=DcConfig,
        )
        display_svc = DisplayService(
            device_svc, overlay_svc, media_svc,
            ensure_data_fn=DataManager.ensure_all,
            theme_svc=theme_svc,
        )

        # Build LCDDevice with pre-wired services
        lcd = LCDDevice(
            device_svc=device_svc,
            display_svc=display_svc,
            theme_svc=theme_svc,
            renderer=renderer,
            dc_config_cls=DcConfig,
            load_config_json_fn=load_config_json,
        )

        # Initialize if data dir provided
        if self._data_dir:
            lcd.initialize(self._data_dir)

        return lcd

    def build_led(self) -> LEDDevice:
        """Build and return a LEDDevice.

        No required dependencies — LEDService is created on connect.
        """
        from ..adapters.device.factory import DeviceProtocolFactory
        from .led_device import LEDDevice
        return LEDDevice(get_protocol=DeviceProtocolFactory.get_protocol)
