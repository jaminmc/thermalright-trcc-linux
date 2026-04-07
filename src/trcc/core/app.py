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
    from .device import Device
    from .models import DetectedDevice
    from .ports import (
        AutostartManager,
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
        dev = app.device(0)            # first device by index
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
        # Active devices live in self._devices dict — no separate references
        # IPC handlers — injected by composition roots (CLI/API/GUI entry points)
        self._find_active_fn: FindActiveFn | None = None
        self._proxy_factory_fn: ProxyFactoryFn | None = None
        # Settings — injected after bootstrap (DIP, no lazy conf imports)
        self._settings: Any = None
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
        log.info("scan: detected %d device(s): %s", len(found),
                 ", ".join(f"{d.path} ({d.protocol})" for d in found) or "(none)")

        self._devices = {}
        lock = threading.Lock()

        def _connect_one(detected: DetectedDevice) -> None:
            device = self._builder.build_device(detected)
            try:
                device.connect(detected)
            except Exception:
                log.warning("scan: connect failed for %s — skipping", detected.path)
                return
            info = device.device_info
            res = getattr(info, 'resolution', (0, 0)) if info else (0, 0)
            log.info("scan: connected %s %dx%d", detected.path, *res)
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

        log.info("scan: %d of %d device(s) connected", len(self._devices), len(found))
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
        log.info("bootstrap: init_platform")
        self.init_platform(renderer_factory=renderer_factory)
        log.info("bootstrap: scanning devices")
        devices = self.scan()
        log.info("bootstrap: ensuring data for %d device(s)", len(devices))
        self._ensure_data_blocking()
        log.info("bootstrap: complete")
        return devices

    def init_platform(
        self,
        verbosity: int = 0,
        renderer_factory: Any = None,
    ) -> None:
        """Bootstrap OS platform: logging, OS setup, settings, renderer."""
        self._builder.bootstrap(verbosity)
        import trcc.conf as _conf
        self._settings = _conf.settings
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
        ensure_fn = self._ensure_data_fn
        if ensure_fn is None:
            log.warning("_ensure_data_blocking: no ensure_fn injected — skipping")
            return
        log.info("_ensure_data_blocking: processing %d device(s)", len(self._devices))
        seen: set[tuple[int, int]] = set()
        for device in self._devices.values():
            path = getattr(device.device_info, 'path', '?') if device.device_info else '?'
            if not device.is_lcd:
                log.debug("_ensure_data_blocking: skip non-LCD %s", path)
                continue
            info = device.device_info
            w, h = getattr(info, 'resolution', (0, 0))
            if not (w and h):
                log.warning("_ensure_data_blocking: skip %s — resolution (0,0)", path)
                continue
            if (w, h) in seen:
                log.debug("_ensure_data_blocking: skip %s — duplicate %dx%d", path, w, h)
                continue
            seen.add((w, h))
            log.info("_ensure_data_blocking: ensuring data %dx%d for %s", w, h, path)
            ensure_fn(w, h, progress_fn=lambda msg: self._notify(AppEvent.BOOTSTRAP_PROGRESS, msg))
            device.notify_data_ready()
        log.info("_ensure_data_blocking: done — %d resolution(s) processed", len(seen))

    def _ensure_data_background(self, device: Device, w: int, h: int) -> None:
        """Ensure theme data in a background thread (hotplug path)."""
        ensure_fn = self._ensure_data_fn
        path = getattr(device.device_info, 'path', '?') if device.device_info else '?'
        log.info("_ensure_data_background: starting %dx%d for %s", w, h, path)

        def _bg() -> None:
            try:
                if ensure_fn is not None:
                    ensure_fn(w, h)
                else:
                    log.warning("_ensure_data_background: no ensure_fn for %s", path)
                device.notify_data_ready()
                log.info("_ensure_data_background: done %dx%d for %s", w, h, path)
            except Exception:
                log.exception("_ensure_data_background: failed %dx%d for %s", w, h, path)

        threading.Thread(target=_bg, daemon=True, name="data-extract").start()

    def device_connected(self, detected: DetectedDevice) -> None:
        """Build, connect, and register a newly discovered device, notify observers."""
        log.info("device_connected: hotplug %s (%s)", detected.path, detected.protocol)
        device = self._builder.build_device(detected)
        try:
            device.connect(detected)
        except Exception:
            log.warning("device_connected: connect failed for %s", detected.path)
            return
        info = device.device_info
        res = getattr(info, 'resolution', (0, 0)) if info else (0, 0)
        log.info("device_connected: connected %s %dx%d", detected.path, *res)
        self._devices[detected.path] = device
        self._wire_device(device)
        # Hotplug: ensure data in background (UI already running, can't block).
        if device.is_lcd:
            w, h = res
            if w and h:
                log.info("device_connected: triggering data download %dx%d", w, h)
                self._ensure_data_background(device, w, h)
            else:
                log.warning("device_connected: LCD %s has no resolution — skipping data download", detected.path)
        else:
            log.debug("device_connected: non-LCD %s — no data download needed", detected.path)
        self._notify(AppEvent.DEVICE_CONNECTED, device)

    def device_lost(self, path: str) -> None:
        """Remove a device by path and notify observers."""
        device = self._devices.pop(path, None)
        if device is not None:
            self._notify(AppEvent.DEVICE_LOST, device)

    def _wire_device(self, device: Device) -> None:
        """Initialize device pipeline and inject IPC handlers.

        IPC handlers (set via set_ipc_handlers) are injected here so that
        devices built by scan() can proxy to a running GUI/API instance.
        """
        path = getattr(device, 'device_path', '?')
        device.wire_ipc(self._find_active_fn, self._proxy_factory_fn)
        if self._settings is not None:
            device.initialize_pipeline(self._settings)
        else:
            log.warning("_wire_device: settings not initialized — skipping pipeline init for %s", path)
        log.debug("device ready: %s (lcd=%s)", path, device.is_lcd)

    @property
    def devices(self) -> list[Device]:
        """All currently known devices (snapshot). Call scan() first."""
        return list(self._devices.values())

    def device(self, index: int = 0) -> Device:
        """Device by position. Raises if out of range."""
        devs = list(self._devices.values())
        if index < 0 or index >= len(devs):
            raise RuntimeError(
                f"Device index {index} out of range ({len(devs)} connected).")
        return devs[index]

    def device_by_path(self, path: str) -> Device | None:
        """Look up device by USB path, or None."""
        return self._devices.get(path)

    def has_device(self, *, lcd: bool | None = None) -> bool:
        """True if a matching device is connected.

        lcd=True: any LCD.  lcd=False: any LED.  lcd=None: any device.
        """
        if lcd is None:
            return bool(self._devices)
        return any(d.is_lcd == lcd for d in self._devices.values())

    # ── Backward-compat aliases (deprecation cycle) ─────────────────────────

    @property
    def has_lcd(self) -> bool:
        return self.has_device(lcd=True)

    @property
    def has_led(self) -> bool:
        return self.has_device(lcd=False)

    @property
    def lcd_device(self) -> Device | None:
        return next((d for d in self._devices.values() if d.is_lcd), None)

    @property
    def led_device(self) -> Device | None:
        return next((d for d in self._devices.values() if d.is_led), None)

    @property
    def lcd(self) -> Device:
        d = self.lcd_device
        if d is None:
            raise RuntimeError("No LCD device connected.")
        return d

    @property
    def led(self) -> Device:
        d = self.led_device
        if d is None:
            raise RuntimeError("No LED device connected.")
        return d

    # ── DI: device construction ──────────────────────────────────────────────

    def set_ipc_handlers(
        self,
        find_active_fn: FindActiveFn,
        proxy_factory_fn: ProxyFactoryFn,
    ) -> None:
        """Inject IPC handlers for multi-instance routing."""
        self._find_active_fn = find_active_fn
        self._proxy_factory_fn = proxy_factory_fn

    def build_led_device(self) -> Device:
        """Build an unconnected LED Device (for IPC server use only)."""
        from .models import DetectedDevice
        # Build with LED protocol traits — detected=None triggers auto-detect on connect
        dummy = DetectedDevice(vid=0x0416, pid=0x8001, vendor_name='',
                               product_name='', usb_path='',
                               implementation='hid_led', protocol='led')
        return self._builder.build_device(dummy)

    def device_from_service(self, device_svc: Any) -> Device:
        """Build a Device from an existing DeviceService (API standalone mode)."""
        return self._builder.device_from_service(device_svc)

    # ── OS / platform operations (previously OSCommandHandler) ───────────────

    def set_language(self, code: str) -> dict[str, Any]:
        """Set app language by ISO 639-1 code."""
        from .i18n import LANGUAGE_NAMES
        if code not in LANGUAGE_NAMES:
            return {"success": False, "error": f"Unknown language code: {code}"}
        self._settings.lang = code
        return {"success": True, "message": f"Language set to {code}"}

    def set_metrics_refresh(self, interval: int) -> dict[str, Any]:
        """Set metrics polling interval (seconds)."""
        clamped = max(1, min(100, interval))
        self._settings.set_refresh_interval(clamped)
        self.wake_metrics_loop()
        return {"success": True, "message": f"Refresh interval set to {clamped}s"}

    def apply_temp_unit(self, unit: int) -> dict[str, Any]:
        """Set temperature unit system-wide: persist, update all devices, wake metrics.

        Args:
            unit: 0 = Celsius, 1 = Fahrenheit.
        """
        from .models import HardwareMetrics

        self._settings.set_temp_unit(unit)

        # Fetch fresh metrics with new unit applied
        fresh = None
        if self._system_svc is not None:
            raw = self._system_svc.all_metrics  # type: ignore[union-attr]
            fresh = HardwareMetrics.with_temp_unit(raw, unit)
            self._current_metrics = fresh

        # Push to all connected devices
        unit_str = 'F' if unit else 'C'
        for device in self._devices.values():
            device.set_temp_unit(unit)
            if fresh is not None:
                device.update_metrics(fresh)

        self.wake_metrics_loop()
        return {"success": True, "message": f"Temperature unit set to °{unit_str}"}

    def set_hdd_enabled(self, enabled: bool) -> dict[str, Any]:
        """Set HDD info toggle and persist."""
        self._settings.set_hdd_enabled(enabled)
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

    _TICK_INTERVAL = 0.05  # 50ms — animation-grade tick rate

    def start_metrics_loop(self, interval: float | None = None) -> None:
        """Start background loop: tick devices at 50ms, poll metrics at refresh_interval.

        Two cadences in one thread:
        - **Tick**: every 50ms — advance animation, send frames, emit FRAME_RENDERED.
        - **Poll**: every `refresh_interval` seconds — read sensors, update devices,
          emit METRICS_UPDATED. Configurable via settings (GUI about panel).

        All UIs (GUI, CLI, API) observe events — none run their own tick loops.
        """
        if self._system_svc is None:
            raise RuntimeError(
                "TrccApp.set_system() must be called before start_metrics_loop().")
        self.stop_metrics_loop()
        self._metrics_stop.clear()

        def _loop() -> None:
            from .models import HardwareMetrics
            tick_count = 0
            while not self._metrics_stop.is_set():
                try:
                    # Poll sensors at configured interval
                    poll_interval = interval if interval is not None else max(
                        1, self._settings.refresh_interval)
                    metrics_every = max(1, int(poll_interval / self._TICK_INTERVAL))
                    if tick_count % metrics_every == 0:
                        try:
                            raw = self._system_svc.all_metrics  # type: ignore[union-attr]
                            metrics = HardwareMetrics.with_temp_unit(
                                raw, self._settings.temp_unit)
                            self._current_metrics = metrics
                            for device in list(self._devices.values()):
                                try:
                                    device.update_metrics(metrics)
                                except Exception:
                                    log.exception("Metrics update error")
                            self._notify(AppEvent.METRICS_UPDATED, metrics)
                        except Exception:
                            log.exception("Metrics poll error")

                    # Tick all devices every iteration
                    for path, device in list(self._devices.items()):
                        try:
                            result = device.tick()
                            if result is not None:
                                self._notify(AppEvent.FRAME_RENDERED,
                                             {'path': path, 'image': result})
                            elif getattr(device, 'playing', False):
                                device.update_video_cache_text(
                                    self._current_metrics)  # type: ignore[arg-type]
                        except Exception:
                            log.exception("Device tick error: %s", path)
                except Exception:
                    log.exception("Tick loop error")
                tick_count += 1
                self._metrics_wake.wait(self._TICK_INTERVAL)
                self._metrics_wake.clear()

        self._metrics_thread = threading.Thread(
            target=_loop, daemon=True, name="trcc-metrics")
        self._metrics_thread.start()
        log.debug("Metrics loop started (tick=%.0fms, poll=settings.refresh_interval)",
                  self._TICK_INTERVAL * 1000)

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
