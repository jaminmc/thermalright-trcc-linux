"""TrccApp — application singleton / DI container.

Single object all interfaces (CLI, GUI, API) observe and send messages to.
Initialized once via TrccApp.init(). Scans for devices, classifies them as
LCD or LED using PROTOCOL_TRAITS, builds the correct device object, and
hands it to callers. Composition roots import only TrccApp and Device types.

Observer pattern: interfaces register via register(observer). State changes
(device found/lost) notify all registered observers automatically.
"""
from __future__ import annotations

import logging
import threading
from abc import ABC, abstractmethod
from enum import Enum, auto
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..services.system import SystemService
    from .builder import ControllerBuilder
    from .lcd_device import LCDDevice
    from .led_device import LEDDevice
    from .models import DetectedDevice
    from .ports import (
        AutostartManager,
        Device,
        FindActiveFn,
        GetDiskInfoFn,
        GetMemoryInfoFn,
        PlatformSetup,
        ProxyFactoryFn,
    )

log = logging.getLogger(__name__)


# ── Observer contract ────────────────────────────────────────────────────────

class AppEvent(Enum):
    DEVICES_CHANGED     = auto()  # device list rescanned
    DEVICE_CONNECTED    = auto()  # single device came online
    FRAME_RENDERED      = auto()  # overlay frame rendered — data is {'path': str, 'image': Any}
    DEVICE_LOST         = auto()  # single device went offline
    METRICS_UPDATED     = auto()  # metrics polled — data is SystemMetrics
    BOOTSTRAP_PROGRESS  = auto()  # download/extract progress — data is str message


class AppObserver(ABC):
    """Implement and register with TrccApp to receive device/state events."""

    @abstractmethod
    def on_app_event(self, event: AppEvent, data: Any) -> None: ...


# ── Singleton / DI container ─────────────────────────────────────────────────

class TrccApp:
    """Application-wide DI container and singleton.

    One per process. Detects devices, classifies them via PROTOCOL_TRAITS,
    builds LCDDevice or LEDDevice, and hands them to callers. Composition
    roots import only TrccApp — they never import builder, services, or
    adapters directly.

    Typical usage in a composition root::

        app = TrccApp.init()
        devices = app.scan()           # list[Device] — LCD or LED, ready to use
        lcd = app.lcd_device           # LCDDevice or None
    """

    _instance: TrccApp | None = None

    def __init__(self, builder: ControllerBuilder) -> None:
        self._builder = builder
        # path → Device (LCDDevice or LEDDevice, keyed by USB path)
        self._devices: dict[str, Device] = {}
        self._observers: list[AppObserver] = []
        self._system_svc: SystemService | None = None
        self._metrics_thread: threading.Thread | None = None
        self._metrics_stop: threading.Event = threading.Event()
        self._metrics_wake: threading.Event = threading.Event()
        self._current_metrics: Any = None
        # Active devices — set when a device connects, cleared when it disconnects
        self._lcd_device: LCDDevice | None = None
        self._led_device: LEDDevice | None = None
        # IPC handlers — injected by composition roots (CLI/API/GUI entry points)
        self._find_active_fn: FindActiveFn | None = None
        self._proxy_factory_fn: ProxyFactoryFn | None = None
        # Data extraction callable — injected via init() from builder (DIP)
        from .ports import EnsureDataFn
        self._ensure_data_fn: EnsureDataFn | None = None
        # Theme download callables — injected via init() from builder (DIP)
        self._download_pack_fn: Any = None
        self._list_available_fn: Any = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @classmethod
    def init(cls) -> TrccApp:
        """Create the singleton. Intentionally minimal — composition roots
        call bootstrap() or scan() after this."""
        if cls._instance is None:
            from .builder import ControllerBuilder
            builder = ControllerBuilder.for_current_os()
            cls._instance = cls(builder)
            cls._instance._ensure_data_fn = builder.build_ensure_data_fn()
            dl_pack, dl_list = builder.build_download_fns()
            cls._instance._download_pack_fn = dl_pack
            cls._instance._list_available_fn = dl_list
            log.debug("TrccApp initialized")
        return cls._instance

    @classmethod
    def get(cls) -> TrccApp:
        """Return the singleton. Raises if init() was never called."""
        if cls._instance is None:
            raise RuntimeError(
                "TrccApp not initialized — call TrccApp.init() from a composition root.")
        return cls._instance

    @classmethod
    def reset(cls) -> None:
        """Reset the singleton (tests only)."""
        cls._instance = None

    # ── Device scanning ──────────────────────────────────────────────────────

    def scan(self) -> list[Device]:
        """Detect hardware, build and connect LCDDevice/LEDDevice in parallel.

        Detection is sequential (single USB enumerate call), then one thread
        per device for connect + _wire_device (USB handshakes run concurrently).
        """
        detect_fn = self._builder.build_detect_fn()
        found: list[DetectedDevice] = detect_fn()

        self._devices = {}
        lock = threading.Lock()

        def _connect_one(detected: DetectedDevice) -> None:
            device = self._builder.build_device(detected)
            try:
                device.connect(detected)
            except Exception:
                log.warning("scan: connect failed for %s — skipping", detected.path)
                return
            with lock:
                self._devices[detected.path] = device
                self._wire_device(device)

        threads = [
            threading.Thread(target=_connect_one, args=(d,), daemon=True)
            for d in found
        ]
        for t in threads:
            t.start()
        for t in threads:
            t.join(timeout=30)

        log.debug("scan: %d device(s) found", len(self._devices))
        self._notify(AppEvent.DEVICES_CHANGED, list(self._devices.values()))
        return list(self._devices.values())

    def bootstrap(
        self,
        renderer_factory: Any = None,
    ) -> list[Device]:
        """Init platform + connect all devices + ensure theme data.

        Single call that every composition root (GUI, API, CLI serve) makes
        before starting its UI.  Blocks until data is ready so the UI always
        starts with themes present — no empty-list-then-populate flash.
        """
        self.init_platform(renderer_factory=renderer_factory)
        devices = self.scan()
        self._ensure_data_blocking()
        return devices

    def init_platform(
        self,
        verbosity: int = 0,
        renderer_factory: Any = None,
    ) -> None:
        """Bootstrap OS platform: logging, OS setup, settings, renderer."""
        self._builder.bootstrap(verbosity)
        if renderer_factory is not None:
            self.set_renderer(renderer_factory())

    def discover(self, path: str | None = None) -> dict[str, Any]:
        """Scan for devices and ensure data is ready.

        Returns a result dict with success, message, devices list.
        Used by CLI and API _connect_or_fail patterns.
        """
        devices = self.scan()
        if path and path not in self._devices:
            return {"success": False, "error": f"Device not found: {path}"}
        self._ensure_data_blocking()
        return {
            "success": True,
            "message": f"{len(devices)} device(s) found",
            "devices": [getattr(d, 'device_path', str(d)) for d in devices],
        }

    def _ensure_data_blocking(self) -> None:
        """Run ensure_all() synchronously for each connected LCD resolution.

        Called at the end of bootstrap() so the UI starts with data present.
        Hotplug uses _ensure_data_background() instead.
        """
        from .lcd_device import LCDDevice as _LCD
        ensure_fn = self._ensure_data_fn
        if ensure_fn is None:
            return
        seen: set[tuple[int, int]] = set()
        for device in self._devices.values():
            if not (device.is_lcd and isinstance(device, _LCD)):
                continue
            w, h = device.device_info.resolution
            if w and h and (w, h) not in seen:
                seen.add((w, h))
                ensure_fn(w, h, progress_fn=lambda msg: self._notify(AppEvent.BOOTSTRAP_PROGRESS, msg))
                device.notify_data_ready()

    def _ensure_data_background(self, lcd: LCDDevice, w: int, h: int) -> None:
        """Ensure theme data in a background thread (hotplug path)."""
        ensure_fn = self._ensure_data_fn

        def _bg() -> None:
            if ensure_fn is not None:
                ensure_fn(w, h)
            lcd.notify_data_ready()

        threading.Thread(target=_bg, daemon=True, name="data-extract").start()

    def device_connected(self, detected: DetectedDevice) -> None:
        """Build, connect, and register a newly discovered device, notify observers."""
        device = self._builder.build_device(detected)
        try:
            device.connect(detected)
        except Exception:
            log.warning("device_connected: connect failed for %s", detected.path)
            return
        self._devices[detected.path] = device
        self._wire_device(device)
        # Hotplug: ensure data in background (UI already running, can't block).
        from .lcd_device import LCDDevice as _LCD
        if device.is_lcd and isinstance(device, _LCD):
            w, h = device.device_info.resolution
            if w and h:
                self._ensure_data_background(device, w, h)
        self._notify(AppEvent.DEVICE_CONNECTED, device)

    def device_lost(self, path: str) -> None:
        """Remove a device by path and notify observers."""
        device = self._devices.pop(path, None)
        if device is not None:
            if device.is_lcd:
                self._lcd_device = None
            elif device.is_led:
                self._led_device = None
            self._notify(AppEvent.DEVICE_LOST, device)

    def _wire_device(self, device: Device) -> None:
        """Store device reference and initialize if LCD.

        IPC handlers (set via set_ipc_handlers) are injected here so that
        devices built by scan() can proxy to a running GUI/API instance.
        """
        from .lcd_device import LCDDevice as _LCD
        from .led_device import LEDDevice as _LED
        if device.is_lcd and isinstance(device, _LCD):
            if self._find_active_fn is not None:
                device._find_active_fn = self._find_active_fn
            if self._proxy_factory_fn is not None:
                device._proxy_factory_fn = self._proxy_factory_fn
            self._lcd_device = device
            log.debug("LCD device ready: %s", getattr(device, 'device_path', '?'))
            # Initialize display pipeline with the resolution from USB handshake.
            info = device.device_info
            res = getattr(info, 'resolution', (0, 0))
            if res and res != (0, 0):
                self._initialize_lcd(device, res[0], res[1])
        elif device.is_led and isinstance(device, _LED):
            self._led_device = device
            log.debug("LED device ready: %s", getattr(device, 'device_path', '?'))

    def _initialize_lcd(self, lcd: LCDDevice, w: int, h: int) -> None:
        """Initialize LCD device pipeline: settings, data dir, ensure data."""
        import trcc.conf as _conf
        log.debug("_initialize_lcd: width=%d height=%d", w, h)
        _conf.settings.set_resolution(w, h)
        lcd.initialize(_conf.settings.user_data_dir)
        self._ensure_data_background(lcd, w, h)

    @property
    def devices(self) -> list[Device]:
        """All currently known devices (snapshot). Call scan() first."""
        return list(self._devices.values())

    @property
    def has_lcd(self) -> bool:
        """True if an LCD device is connected."""
        return self._lcd_device is not None

    @property
    def has_led(self) -> bool:
        """True if an LED device is connected."""
        return self._led_device is not None

    @property
    def lcd_device(self) -> LCDDevice | None:
        """The active LCD device, or None if not connected."""
        return self._lcd_device

    @property
    def led_device(self) -> LEDDevice | None:
        """The active LED device, or None if not connected."""
        return self._led_device

    @property
    def lcd(self) -> LCDDevice:
        """The active LCD device. Raises if not connected."""
        if self._lcd_device is None:
            raise RuntimeError("No LCD device connected. Call scan() first.")
        return self._lcd_device

    @property
    def led(self) -> LEDDevice:
        """The active LED device. Raises if not connected."""
        if self._led_device is None:
            raise RuntimeError("No LED device connected. Call scan() first.")
        return self._led_device

    # ── DI: device construction ──────────────────────────────────────────────

    def set_ipc_handlers(
        self,
        find_active_fn: FindActiveFn,
        proxy_factory_fn: ProxyFactoryFn,
    ) -> None:
        """Inject IPC handlers for multi-instance routing."""
        self._find_active_fn = find_active_fn
        self._proxy_factory_fn = proxy_factory_fn

    def build_led(self) -> LEDDevice:
        """Build an unconnected LEDDevice (for IPC server use only)."""
        return self._builder.build_led()

    def lcd_from_service(self, device_svc: Any) -> LCDDevice:
        """Build an LCDDevice from an existing DeviceService (API standalone mode)."""
        return self._builder.lcd_from_service(device_svc)

    # ── OS / platform operations (previously OSCommandHandler) ───────────────

    def set_language(self, code: str) -> dict[str, Any]:
        """Set app language by ISO 639-1 code."""
        import trcc.conf as _conf

        from .i18n import LANGUAGE_NAMES
        if code not in LANGUAGE_NAMES:
            return {"success": False, "error": f"Unknown language code: {code}"}
        _conf.settings.lang = code
        return {"success": True, "message": f"Language set to {code}"}

    def set_metrics_refresh(self, interval: int) -> dict[str, Any]:
        """Set metrics polling interval (seconds)."""
        import trcc.conf as _conf
        clamped = max(1, min(100, interval))
        _conf.settings.set_refresh_interval(clamped)
        self.wake_metrics_loop()
        return {"success": True, "message": f"Refresh interval set to {clamped}s"}

    def apply_temp_unit(self, unit: int) -> dict[str, Any]:
        """Set temperature unit system-wide: persist, update all devices, wake metrics.

        Args:
            unit: 0 = Celsius, 1 = Fahrenheit.
        """
        import trcc.conf as _conf

        from .models import HardwareMetrics

        _conf.settings.set_temp_unit(unit)

        # Fetch fresh metrics with new unit applied
        fresh = None
        if self._system_svc is not None:
            raw = self._system_svc.all_metrics  # type: ignore[union-attr]
            fresh = HardwareMetrics.with_temp_unit(raw, unit)
            self._current_metrics = fresh

        # Push to all connected devices
        unit_str = 'F' if unit else 'C'
        from .lcd_device import LCDDevice as _LCD
        from .led_device import LEDDevice as _LED
        for device in self._devices.values():
            if isinstance(device, _LCD):
                device.set_temp_unit(unit)
                if fresh is not None:
                    device.update_metrics(fresh)
            elif isinstance(device, _LED):
                device.set_temp_unit(unit_str)

        self.wake_metrics_loop()
        return {"success": True, "message": f"Temperature unit set to °{unit_str}"}

    def set_hdd_enabled(self, enabled: bool) -> dict[str, Any]:
        """Set HDD info toggle and persist."""
        import trcc.conf as _conf
        _conf.settings.set_hdd_enabled(enabled)
        return {"success": True,
                "message": f"HDD info {'enabled' if enabled else 'disabled'}"}

    def setup_platform(self, auto_yes: bool = False) -> int:
        """Run interactive platform setup wizard. Returns exit code."""
        return self._builder.build_setup().run(auto_yes=auto_yes)

    def setup_udev(self, dry_run: bool = False) -> int:
        """Install udev rules. Returns exit code."""
        return self._builder.build_setup().setup_udev(dry_run=dry_run)

    def setup_selinux(self) -> int:
        """Install SELinux policy. Returns exit code."""
        return self._builder.build_setup().setup_selinux()

    def setup_polkit(self) -> int:
        """Install polkit policy. Returns exit code."""
        return self._builder.build_setup().setup_polkit()

    def install_desktop(self) -> int:
        """Install .desktop entry. Returns exit code."""
        return self._builder.build_setup().install_desktop()

    def setup_winusb(self) -> int:
        """Guide WinUSB installation. Returns exit code."""
        return self._builder.build_setup().setup_winusb()

    def download_themes(self, pack: str = "", force: bool = False) -> int:
        """Download theme packs. Empty pack = list available. Returns exit code."""
        if not pack:
            if self._list_available_fn:
                self._list_available_fn()
            return 0
        if self._download_pack_fn:
            return self._download_pack_fn(pack, force)
        return 1

    # ── System service + metrics loop ────────────────────────────────────────

    def set_system(self, system_svc: SystemService) -> None:
        """Inject the SystemService. Call before start_metrics_loop()."""
        self._system_svc = system_svc

    @property
    def current_metrics(self) -> Any:
        """Most recently polled metrics (with temp unit applied), or None."""
        return self._current_metrics

    def start_metrics_loop(self, interval: float | None = None) -> None:
        """Start background loop: poll metrics → push to all devices via tick()."""
        if self._system_svc is None:
            raise RuntimeError(
                "TrccApp.set_system() must be called before start_metrics_loop().")
        self.stop_metrics_loop()
        self._metrics_stop.clear()

        def _loop() -> None:
            import trcc.conf as _conf

            from .models import HardwareMetrics
            while not self._metrics_stop.is_set():
                try:
                    raw = self._system_svc.all_metrics  # type: ignore[union-attr]
                    metrics = HardwareMetrics.with_temp_unit(
                        raw, _conf.settings.temp_unit)
                    self._current_metrics = metrics
                    for path, device in list(self._devices.items()):
                        try:
                            device.update_metrics(metrics)
                            image = device.tick()
                            if image is not None:
                                self._notify(AppEvent.FRAME_RENDERED,
                                             {'path': path, 'image': image})
                            elif getattr(device, 'playing', False):
                                device.update_video_cache_text(metrics)  # type: ignore[union-attr]
                        except Exception:
                            log.exception("Device update error: %s", device)
                    self._notify(AppEvent.METRICS_UPDATED, metrics)
                except Exception:
                    log.exception("Metrics poll error")
                sleep = interval if interval is not None else max(1, _conf.settings.refresh_interval)
                self._metrics_wake.wait(sleep)
                self._metrics_wake.clear()

        self._metrics_thread = threading.Thread(
            target=_loop, daemon=True, name="trcc-metrics")
        self._metrics_thread.start()
        log.debug("Metrics loop started (reads interval from settings)")

    def stop_metrics_loop(self) -> None:
        """Stop the background metrics loop."""
        self._metrics_stop.set()
        self._metrics_wake.set()
        if self._metrics_thread and self._metrics_thread.is_alive():
            self._metrics_thread.join(timeout=3)
        self._metrics_thread = None
        self._metrics_wake.clear()
        self._metrics_stop.clear()

    def wake_metrics_loop(self) -> None:
        """Wake the sleeping metrics loop immediately."""
        self._metrics_wake.set()

    # ── DI: infrastructure ───────────────────────────────────────────────────

    def build_system(self) -> SystemService:
        """Build a SystemService wired with OS-appropriate sensor enumerator."""
        return self._builder.build_system()

    def build_setup(self) -> PlatformSetup:
        """Return the OS-appropriate setup wizard."""
        return self._builder.build_setup()

    def build_autostart(self) -> AutostartManager:
        """Return the OS-appropriate autostart manager."""
        return self._builder.build_autostart()

    def build_hardware_fns(self) -> tuple[GetMemoryInfoFn, GetDiskInfoFn]:
        """Return (get_memory_info, get_disk_info) for the current OS."""
        return self._builder.build_hardware_fns()

    def set_renderer(self, renderer: Any) -> None:
        """Inject the renderer into the builder and ImageService."""
        from ..services.image import ImageService
        self._builder.with_renderer(renderer)
        ImageService.set_renderer(renderer)

    # ── Observer registration ────────────────────────────────────────────────

    def register(self, observer: AppObserver) -> None:
        self._observers.append(observer)

    def unregister(self, observer: AppObserver) -> None:
        self._observers = [o for o in self._observers if o is not observer]

    def _notify(self, event: AppEvent, data: Any) -> None:
        for obs in self._observers:
            try:
                obs.on_app_event(event, data)
            except Exception:
                log.exception("Observer %s raised on %s", obs, event)
