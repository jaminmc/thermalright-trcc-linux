"""ControllerBuilder — assembles devices with dependency injection.

PlatformAdapter is injected via constructor. The factory classmethod
for_current_os() is the single OS check — overrideable by subclasses
for testing or platform extension.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from .ports import (
    AutostartManager,
    Device,
    GetDiskInfoFn,
    GetMemoryInfoFn,
    PlatformAdapter,
    PlatformSetup,
    Renderer,
)

if TYPE_CHECKING:
    from ..services.system import SystemService
    from .lcd_device import LCDDevice
    from .led_device import LEDDevice

log = logging.getLogger(__name__)


class ControllerBuilder:
    """Assembles LCDDevice / LEDDevice / SystemService with injected deps.

    PlatformAdapter is injected at construction — all build methods use
    self._platform. No OS checks anywhere except for_current_os().

    Usage::

        builder = ControllerBuilder.for_current_os().with_renderer(renderer)
        lcd     = builder.build_lcd()
        system  = builder.build_system()
        setup   = builder.build_setup()
    """

    def __init__(self, platform: PlatformAdapter) -> None:
        self._platform = platform
        self._renderer: Renderer | None = None
        self._data_dir: Path | None = None

    # ── Factory entry point (overrideable) ─────────────────────────

    @classmethod
    def for_current_os(cls) -> 'ControllerBuilder':
        """Create a builder with the OS-appropriate platform adapter.

        Single OS check for the entire application. Overrideable by
        subclasses to inject a custom or test platform.
        """
        from .platform import BSD, MACOS, WINDOWS

        if WINDOWS:
            from ..adapters.system.windows.platform import WindowsPlatform
            return cls(WindowsPlatform())
        if MACOS:
            from ..adapters.system.macos.platform import MacOSPlatform
            return cls(MacOSPlatform())
        if BSD:
            from ..adapters.system.bsd.platform import BSDPlatform
            return cls(BSDPlatform())
        from ..adapters.system.linux.platform import LinuxPlatform
        return cls(LinuxPlatform())

    def bootstrap(self, verbosity: int = 0) -> None:
        """Bootstrap the platform: logging → OS setup → settings.

        Called by the InitPlatformCommand handler in TrccApp — never directly
        by composition roots. Commands are boss.
        """
        from ..adapters.infra.logging_setup import StandardLoggingConfigurator
        from ..conf import init_settings

        StandardLoggingConfigurator().configure(verbosity=verbosity)
        setup = self.build_setup()
        setup.configure_stdout()
        init_settings(setup)

    # ── Fluent setters ─────────────────────────────────────────────

    def with_renderer(self, renderer: Renderer) -> ControllerBuilder:
        self._renderer = renderer
        return self

    def with_data_dir(self, data_dir: Path) -> ControllerBuilder:
        self._data_dir = data_dir
        return self

    # ── Shared wiring helpers ─────────────────────────────────────

    def _build_device_svc(self) -> Any:
        """Create DeviceService with platform-injected callables."""
        from ..adapters.device.factory import DeviceProtocolFactory
        from ..adapters.device.led import probe_led_model
        from ..services import DeviceService
        self._platform.configure_scsi_protocol(DeviceProtocolFactory)
        return DeviceService(
            detect_fn=self._platform.create_detect_fn(),
            probe_led_fn=probe_led_model,
            get_protocol=DeviceProtocolFactory.get_protocol,
            get_protocol_info=DeviceProtocolFactory.get_protocol_info,
        )

    def _build_config_callables(self) -> dict:
        """Return Settings config callables for device persistence."""
        from ..conf import Settings
        return {
            'config_key_fn': Settings.device_config_key,
            'save_setting_fn': Settings.save_device_setting,
            'get_config_fn': Settings.get_device_config,
        }

    # ── Build methods ──────────────────────────────────────────────

    def build_lcd(self) -> LCDDevice:
        """Build and return an LCDDevice."""
        from ..conf import Settings
        from ..services.image import ImageService
        from ..services.lcd_config import LCDConfigService
        from ..services.theme import theme_info_from_directory
        from .lcd_device import LCDDevice

        renderer = self._renderer
        if renderer is None:
            raise RuntimeError(
                "ControllerBuilder.with_renderer() must be called before build_lcd().")
        ImageService.set_renderer(renderer)

        device_svc = self._build_device_svc()
        build_services_fn = self._make_build_services_fn()
        result = build_services_fn(device_svc, renderer)

        lcd_config = LCDConfigService(
            **self._build_config_callables(),
            apply_format_prefs_fn=Settings.apply_format_prefs,
        )
        lcd = LCDDevice(
            device_svc=device_svc,
            display_svc=result['display_svc'],
            theme_svc=result['theme_svc'],
            renderer=renderer,
            dc_config_cls=result['dc_config_cls'],
            load_config_json_fn=result['load_config_json_fn'],
            theme_info_from_dir_fn=theme_info_from_directory,
            lcd_config=lcd_config,
            build_services_fn=build_services_fn,
        )

        if self._data_dir:
            lcd.initialize(self._data_dir)

        return lcd

    def build_led(self) -> LEDDevice:
        """Build and return a LEDDevice."""
        from ..adapters.device.factory import DeviceProtocolFactory
        from ..services import LEDService
        from ..services.led_config import LEDConfigService
        from .led_device import LEDDevice

        led_config = LEDConfigService(**self._build_config_callables())
        return LEDDevice(
            device_svc=self._build_device_svc(),
            get_protocol=DeviceProtocolFactory.get_protocol,
            led_svc_factory=LEDService,
            led_config=led_config,
        )

    def build_device(self, detected: Any = None) -> 'Device':
        """Build and return the correct Device for the detected hardware.

        Reads PROTOCOL_TRAITS.is_led to decide LCDDevice vs LEDDevice.
        If detected is None, creates an unconnected device that auto-detects on connect().
        Adapters depend only on Device — never on LCDDevice or LEDDevice.
        """
        from ..adapters.device.factory import DeviceProtocolFactory
        from .models import PROTOCOL_TRAITS

        device_svc = self._build_device_svc()
        cfg = self._build_config_callables()

        is_led = (
            detected is not None
            and PROTOCOL_TRAITS.get(detected.protocol, PROTOCOL_TRAITS['scsi']).is_led
        )

        if is_led:
            from ..services import LEDService
            from ..services.led_config import LEDConfigService
            from .led_device import LEDDevice
            return LEDDevice(
                device_svc=device_svc,
                get_protocol=DeviceProtocolFactory.get_protocol,
                led_svc_factory=LEDService,
                led_config=LEDConfigService(**cfg),
            )

        from ..conf import Settings
        from ..services.image import ImageService
        from ..services.lcd_config import LCDConfigService
        from ..services.theme import theme_info_from_directory
        from .lcd_device import LCDDevice
        build_fn = self._make_build_services_fn()
        renderer = self._renderer
        if renderer is None:
            raise RuntimeError(
                "ControllerBuilder: renderer not set. "
                "Dispatch InitPlatformCommand with renderer_factory before building devices.")
        ImageService.set_renderer(renderer)
        lcd_config = LCDConfigService(
            **cfg,
            apply_format_prefs_fn=Settings.apply_format_prefs,
        )
        return LCDDevice(
            device_svc=device_svc,
            build_services_fn=build_fn,
            renderer=renderer,
            theme_info_from_dir_fn=theme_info_from_directory,
            lcd_config=lcd_config,
        )

    def build_system(self) -> SystemService:
        """Build and return a SystemService."""
        from ..services.system import SystemService
        return SystemService(enumerator=self._platform.create_sensor_enumerator())

    def build_setup(self) -> PlatformSetup:
        """Return the platform-specific setup wizard."""
        return self._platform.create_setup()

    def build_ensure_data_fn(self):
        """Return DataManager.ensure_all — the data extraction callable.

        Isolated here so core/app.py never imports infra adapters directly.
        """
        from ..adapters.infra.data_repository import DataManager
        return DataManager.ensure_all

    def build_download_fns(self):
        """Return (download_pack, list_available) callables for theme downloads.

        Isolated here so core/app.py never imports infra adapters directly.
        """
        from ..adapters.infra.theme_downloader import download_pack, list_available
        return download_pack, list_available

    def build_autostart(self) -> AutostartManager:
        """Return the platform-specific autostart manager."""
        return self._platform.create_autostart_manager()

    def build_detect_fn(self):
        """Return the platform-appropriate device detect callable."""
        return self._platform.create_detect_fn()

    def build_device_svc(self):
        """Build a DeviceService wired with platform-appropriate adapters."""
        return self._build_device_svc()

    def build_hardware_fns(self) -> tuple[GetMemoryInfoFn, GetDiskInfoFn]:
        """Return platform-specific (get_memory_info, get_disk_info) callables."""
        return self._platform.get_memory_info_fn(), self._platform.get_disk_info_fn()

    def lcd_from_service(self, device_svc) -> LCDDevice:
        """Build an LCDDevice from an existing DeviceService."""
        from .lcd_device import LCDDevice
        build_fn = self._make_build_services_fn()
        return LCDDevice.from_service(
            device_svc,
            renderer=self._renderer,
            build_services_fn=build_fn,
        )

    # ── Internal ───────────────────────────────────────────────────

    def _make_build_services_fn(self):
        """Create a factory that wires LCD services from a DeviceService."""
        from ..adapters.infra.dc_config import DcConfig
        from ..adapters.infra.dc_parser import load_config_json
        from ..adapters.infra.dc_writer import export_theme, import_theme
        from ..adapters.infra.media_player import ThemeZtDecoder, VideoDecoder
        from ..services import DisplayService, MediaService, OverlayService, ThemeService
        from ..services.image import ImageService

        setup = self.build_setup()

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
                export_theme_fn=export_theme,
                import_theme_fn=import_theme,
                load_config_json_fn=load_config_json,
                dc_config_cls=DcConfig,
            )
            try:
                import psutil as _psutil
                _proc = _psutil.Process()
                def _cpu_percent() -> float:
                    return _proc.cpu_percent(interval=0.5)
            except ImportError:
                log.warning("psutil not available — CPU baseline logging disabled")
                _cpu_percent = None  # type: ignore[assignment]
            display_svc = DisplayService(
                device_svc, overlay_svc, media_svc,
                theme_svc=theme_svc,
                cpu_percent_fn=_cpu_percent,
                path_resolver=setup,
            )
            return {
                'display_svc': display_svc,
                'theme_svc': theme_svc,
                'renderer': r,
                'dc_config_cls': DcConfig,
                'load_config_json_fn': load_config_json,
            }

        return _build
