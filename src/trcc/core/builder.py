"""ControllerBuilder — assembles devices with dependency injection.

Builder pattern: collects dependencies, validates, returns Device subclasses.
All three adapters (CLI, GUI, API) use this to construct devices.
"""
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from .ports import AutostartManager, PlatformSetup, Renderer

if TYPE_CHECKING:
    from ..services.system import SystemService
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

    @staticmethod
    def _make_build_services_fn():
        """Create a factory function that wires LCD services from a DeviceService.

        Returns a callable(device_svc, renderer) -> dict of services.
        Captures adapter imports in the closure so LCDDevice never imports them.
        """
        from ..adapters.infra.data_repository import DataManager
        from ..adapters.infra.dc_config import DcConfig
        from ..adapters.infra.dc_parser import load_config_json
        from ..adapters.infra.dc_writer import export_theme, import_theme
        from ..adapters.infra.media_player import ThemeZtDecoder, VideoDecoder
        from ..services import (
            DisplayService,
            MediaService,
            OverlayService,
            ThemeService,
        )
        from ..services.image import ImageService

        def _build(device_svc, renderer=None):
            r = renderer or ImageService._r()
            overlay_svc = OverlayService(
                renderer=r,
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
            return {
                'display_svc': display_svc,
                'theme_svc': theme_svc,
                'renderer': r,
                'dc_config_cls': DcConfig,
                'load_config_json_fn': load_config_json,
            }

        return _build

    def build_lcd(self) -> LCDDevice:
        """Build and return an LCDDevice.

        Requires: renderer (defaults to QtRenderer if not set).
        Optional: data_dir (triggers initialize).
        """
        from .platform import BSD, MACOS, WINDOWS

        if WINDOWS:
            from ..adapters.device.windows.detector import WindowsDeviceDetector
            detect_fn = WindowsDeviceDetector.detect
        elif MACOS:
            from ..adapters.device.macos.detector import MacOSDeviceDetector
            detect_fn = MacOSDeviceDetector.detect
        elif BSD:
            from ..adapters.device.bsd.detector import BSDDeviceDetector
            detect_fn = BSDDeviceDetector.detect
        else:
            from ..adapters.device.detector import DeviceDetector
            detect_fn = DeviceDetector.detect

        from ..adapters.device.factory import DeviceProtocolFactory
        from ..adapters.device.led import probe_led_model
        from ..services import DeviceService
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

        # Create DeviceService with platform-correct detector
        device_svc = DeviceService(
            detect_fn=detect_fn,
            probe_led_fn=probe_led_model,
            get_protocol=DeviceProtocolFactory.get_protocol,
            get_protocol_info=DeviceProtocolFactory.get_protocol_info,
        )

        # Build services factory (captures adapter imports in closure)
        build_services_fn = self._make_build_services_fn()

        # Wire services now
        result = build_services_fn(device_svc, renderer)

        # Build LCDDevice with pre-wired services
        lcd = LCDDevice(
            device_svc=device_svc,
            display_svc=result['display_svc'],
            theme_svc=result['theme_svc'],
            renderer=renderer,
            dc_config_cls=result['dc_config_cls'],
            load_config_json_fn=result['load_config_json_fn'],
            build_services_fn=build_services_fn,
        )

        # Initialize if data dir provided
        if self._data_dir:
            lcd.initialize(self._data_dir)

        return lcd

    def lcd_from_service(self, device_svc) -> LCDDevice:
        """Build an LCDDevice from an existing DeviceService.

        Used by CLI/API when the caller already has a connected DeviceService
        and needs the full DisplayService pipeline.
        """
        from .lcd_device import LCDDevice
        build_fn = self._make_build_services_fn()
        return LCDDevice.from_service(
            device_svc,
            renderer=self._renderer,
            build_services_fn=build_fn,
        )

    def build_system(self) -> SystemService:
        """Build and return a SystemService with injected enumerator."""
        from ..services.system import SystemService
        from .platform import BSD, MACOS, WINDOWS

        if WINDOWS:
            from ..adapters.system.windows.sensors import WindowsSensorEnumerator
            enumerator = WindowsSensorEnumerator()
        elif MACOS:
            from ..adapters.system.macos.sensors import MacOSSensorEnumerator
            enumerator = MacOSSensorEnumerator()
        elif BSD:
            from ..adapters.system.bsd.sensors import BSDSensorEnumerator
            enumerator = BSDSensorEnumerator()
        else:
            from ..adapters.system.linux.sensors import SensorEnumerator
            enumerator = SensorEnumerator()

        return SystemService(enumerator=enumerator)

    def build_led(self) -> LEDDevice:
        """Build and return a LEDDevice with injected dependencies."""
        from .platform import BSD, MACOS, WINDOWS

        if WINDOWS:
            from ..adapters.device.windows.detector import WindowsDeviceDetector
            detect_fn = WindowsDeviceDetector.detect
        elif MACOS:
            from ..adapters.device.macos.detector import MacOSDeviceDetector
            detect_fn = MacOSDeviceDetector.detect
        elif BSD:
            from ..adapters.device.bsd.detector import BSDDeviceDetector
            detect_fn = BSDDeviceDetector.detect
        else:
            from ..adapters.device.detector import DeviceDetector
            detect_fn = DeviceDetector.detect

        from ..adapters.device.factory import DeviceProtocolFactory
        from ..adapters.device.led import probe_led_model
        from ..services import DeviceService
        from .led_device import LEDDevice

        device_svc = DeviceService(
            detect_fn=detect_fn,
            probe_led_fn=probe_led_model,
            get_protocol=DeviceProtocolFactory.get_protocol,
            get_protocol_info=DeviceProtocolFactory.get_protocol_info,
        )
        return LEDDevice(
            device_svc=device_svc,
            get_protocol=DeviceProtocolFactory.get_protocol,
        )

    @staticmethod
    def build_autostart() -> AutostartManager:
        """Build and return the platform-specific autostart manager."""
        from .platform import MACOS, WINDOWS

        if WINDOWS:
            from ..adapters.system.windows.autostart import WindowsAutostartManager
            return WindowsAutostartManager()
        if MACOS:
            from ..adapters.system.macos.autostart import MacOSAutostartManager
            return MacOSAutostartManager()
        # Linux and BSD both use XDG .desktop
        from ..adapters.system.linux.autostart import LinuxAutostartManager
        return LinuxAutostartManager()

    @staticmethod
    def build_setup() -> PlatformSetup:
        """Build and return the platform-specific setup wizard."""
        from .platform import BSD, MACOS, WINDOWS

        if WINDOWS:
            from ..adapters.system.windows.setup import WindowsSetup
            return WindowsSetup()
        if MACOS:
            from ..adapters.system.macos.setup import MacOSSetup
            return MacOSSetup()
        if BSD:
            from ..adapters.system.bsd.setup import BSDSetup
            return BSDSetup()
        from ..adapters.system.linux.setup import LinuxSetup
        return LinuxSetup()
