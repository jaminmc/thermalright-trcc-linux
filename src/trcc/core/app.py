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
    from .command_bus import CommandBus
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

        app = TrccApp.init(verbosity=verbosity)
        devices = app.scan()           # list[Device] — LCD or LED, ready to use
        lcd = devices[0]               # LCDDevice or LEDDevice, caller checks type
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
        # Active buses — built when a device connects, cleared when it disconnects
        self._os_bus: CommandBus | None = None
        self._lcd_bus: CommandBus | None = None
        self._led_bus: CommandBus | None = None
        self._lcd_device: LCDDevice | None = None
        self._led_device: LEDDevice | None = None
        # IPC handlers — injected by composition roots (CLI/API/GUI entry points)
        self._find_active_fn: FindActiveFn | None = None
        self._proxy_factory_fn: ProxyFactoryFn | None = None
        # Data extraction callable — injected via init() from builder (DIP)
        from .ports import EnsureDataFn
        self._ensure_data_fn: EnsureDataFn | None = None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    @classmethod
    def init(cls) -> TrccApp:
        """Create the singleton and wire the OS command bus.

        Intentionally minimal — no platform bootstrapping here. Composition
        roots dispatch InitPlatformCommand immediately after to do real init:
            logging → OS setup → settings → renderer.
        Then DiscoverDevicesCommand to find hardware.
        """
        if cls._instance is None:
            from .builder import ControllerBuilder
            builder = ControllerBuilder.for_current_os()
            cls._instance = cls(builder)
            cls._instance._ensure_data_fn = builder.build_ensure_data_fn()
            cls._instance._os_bus = cls._instance.build_os_bus()
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
        per device for connect + _wire_bus (USB handshakes run concurrently).
        _wire_bus fires EnsureDataCommand per resolution in a background thread.

        Sequence: bootstrap() or init() → OS → scan()
          - LCD found → lcd_bus built and stored
          - LED found → led_bus built and stored
          - Notifies observers with DEVICES_CHANGED
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
                self._wire_bus(device)

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

        After this returns:
          - Platform initialized (logging, OS, settings, renderer)
          - All devices connected and their buses ready
          - Theme data extracted/downloaded for each connected resolution

        Progress is reported via AppEvent.BOOTSTRAP_PROGRESS notifications.
        Register an AppObserver before calling bootstrap() to receive them.

        Returns the list of connected devices (same as scan()).
        """
        from .commands.initialize import InitPlatformCommand
        self.os_bus.dispatch(InitPlatformCommand(
            renderer_factory=renderer_factory,
        ))
        devices = self.scan()
        self._ensure_data_blocking()
        return devices

    def _ensure_data_blocking(self) -> None:
        """Run ensure_all() synchronously for each connected LCD resolution.

        Called at the end of bootstrap() so the UI starts with data present.
        Hotplug and SetResolutionCommand still use the background EnsureDataCommand.
        Progress is reported via AppEvent.BOOTSTRAP_PROGRESS notifications.
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
                import trcc.conf as _conf
                _conf.settings.set_resolution(w, h)
                device.notify_data_ready()

    def device_connected(self, detected: DetectedDevice) -> None:
        """Build, connect, and register a newly discovered device, notify observers.

        For hotplug (UI already running) we dispatch EnsureDataCommand so data
        is fetched in the background — no blocking here since the UI is live.
        """
        device = self._builder.build_device(detected)
        try:
            device.connect(detected)
        except Exception:
            log.warning("device_connected: connect failed for %s", detected.path)
            return
        self._devices[detected.path] = device
        self._wire_bus(device)
        # Hotplug: ensure data in background (UI already running, can't block).
        from .lcd_device import LCDDevice as _LCD
        if device.is_lcd and isinstance(device, _LCD) and self._lcd_bus is not None:
            from .commands.lcd import EnsureDataCommand
            w, h = device.device_info.resolution
            if w and h:
                self._lcd_bus.dispatch(EnsureDataCommand(width=w, height=h))
        self._notify(AppEvent.DEVICE_CONNECTED, device)

    def device_lost(self, path: str) -> None:
        """Remove a device by path, clear its bus, and notify observers."""
        device = self._devices.pop(path, None)
        if device is not None:
            if device.is_lcd:
                self._lcd_bus = None
                self._lcd_device = None
            elif device.is_led:
                self._led_bus = None
                self._led_device = None
            self._notify(AppEvent.DEVICE_LOST, device)

    def _wire_bus(self, device: Device) -> None:
        """Build and store the appropriate bus for a newly connected device.

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
            self._lcd_bus = self.build_lcd_bus(device)
            log.debug("lcd_bus ready for %s", getattr(device, 'device_path', '?'))
            # Initialize display pipeline with the resolution from the USB handshake.
            # This sets settings.resolution, media target size, and overlay resolution
            # so all subsequent commands (CLI send, API encode) work correctly.
            # The GUI re-dispatches InitializeDeviceCommand in apply_device_config —
            # safe because set_resolution has a no-op guard for same-value calls.
            info = device.device_info
            res = getattr(info, 'resolution', (0, 0))
            if res and res != (0, 0):
                from .commands.lcd import InitializeDeviceCommand as _Init
                self._lcd_bus.dispatch(_Init(width=res[0], height=res[1]))
        elif device.is_led and isinstance(device, _LED):
            self._led_device = device
            self._led_bus = self.build_led_bus(device)
            log.debug("led_bus ready for %s", getattr(device, 'device_path', '?'))

    @property
    def devices(self) -> list[Device]:
        """All currently known devices (snapshot). Call scan() first."""
        return list(self._devices.values())

    @property
    def has_lcd(self) -> bool:
        """True if an LCD device is connected and its bus is ready."""
        return self._lcd_bus is not None

    @property
    def has_led(self) -> bool:
        """True if an LED device is connected and its bus is ready."""
        return self._led_bus is not None

    @property
    def lcd_bus(self) -> CommandBus:
        """CommandBus for LCD operations. Raises if no LCD device connected.

        Sequence: TrccApp.init() → scan() → lcd_bus.dispatch(command)
        """
        if self._lcd_bus is None:
            raise RuntimeError(
                "No LCD device connected. Call scan() first.")
        return self._lcd_bus

    @property
    def led_bus(self) -> CommandBus:
        """CommandBus for LED operations. Raises if no LED device connected.

        Sequence: TrccApp.init() → scan() → led_bus.dispatch(command)
        """
        if self._led_bus is None:
            raise RuntimeError(
                "No LED device connected. Call scan() first.")
        return self._led_bus

    @property
    def os_bus(self) -> CommandBus:
        """CommandBus for OS/platform operations (connect, discover, init).

        Available immediately after TrccApp.init() — no device needed.
        """
        if self._os_bus is None:
            self._os_bus = self.build_os_bus()
        return self._os_bus

    def build_os_bus(self) -> CommandBus:
        """Return a CommandBus wired to OS/platform handlers."""
        from trcc.adapters.infra.theme_downloader import download_pack, list_available

        from .handlers.os import build_os_bus as _build
        return _build(
            bootstrap_fn=self._builder.bootstrap,
            set_renderer_fn=self.set_renderer,
            scan_fn=lambda: self.scan(),
            ensure_data_fn=lambda: self._ensure_data_blocking(),
            has_device_fn=lambda path: path in self._devices,
            build_setup_fn=self._builder.build_setup,
            list_themes_fn=list_available,
            download_pack_fn=download_pack,
        )

    # ── DI: device construction ──────────────────────────────────────────────

    def set_ipc_handlers(
        self,
        find_active_fn: FindActiveFn,
        proxy_factory_fn: ProxyFactoryFn,
    ) -> None:
        """Inject IPC handlers for multi-instance routing.

        Call from composition roots (CLI, API, GUI) before dispatching
        DiscoverDevicesCommand.  Handlers are injected into each device in
        _wire_bus() so devices can detect a running instance and proxy commands.
        """
        self._find_active_fn = find_active_fn
        self._proxy_factory_fn = proxy_factory_fn

    @property
    def lcd_device(self) -> LCDDevice | None:
        """The active LCD device, or None if not connected."""
        return self._lcd_device

    @property
    def led_device(self) -> LEDDevice | None:
        """The active LED device, or None if not connected."""
        return self._led_device

    def build_led(self) -> LEDDevice:
        """Build an unconnected LEDDevice (for IPC server use only).

        Composition roots that need a direct device reference (e.g. IPC server
        wiring) may call this.  Normal device access goes through scan() →
        DiscoverDevicesCommand → led_device.
        """
        return self._builder.build_led()

    def lcd_from_service(self, device_svc: Any) -> LCDDevice:
        """Build an LCDDevice from an existing DeviceService (API standalone mode)."""
        return self._builder.lcd_from_service(device_svc)

    # ── System service + metrics loop ────────────────────────────────────────

    def set_system(self, system_svc: SystemService) -> None:
        """Inject the SystemService. Call before start_metrics_loop()."""
        self._system_svc = system_svc

    def start_metrics_loop(self, interval: float = 1.0) -> None:
        """Start background loop: poll metrics → push to all devices via tick().

        OS-blind — metrics come from SystemService (wraps OS SensorEnumerator).
        Composition roots call this once after scan().
        """
        if self._system_svc is None:
            raise RuntimeError(
                "TrccApp.set_system() must be called before start_metrics_loop().")
        self.stop_metrics_loop()
        self._metrics_stop.clear()

        def _loop() -> None:
            while not self._metrics_stop.is_set():
                try:
                    metrics = self._system_svc.all_metrics  # type: ignore[union-attr]
                    for path, device in list(self._devices.items()):
                        try:
                            device.update_metrics(metrics)
                            image = device.tick()
                            if image is not None:
                                self._notify(AppEvent.FRAME_RENDERED,
                                             {'path': path, 'image': image})
                        except Exception:
                            log.exception("Device update error: %s", device)
                    self._notify(AppEvent.METRICS_UPDATED, metrics)
                except Exception:
                    log.exception("Metrics poll error")
                self._metrics_stop.wait(interval)

        self._metrics_thread = threading.Thread(
            target=_loop, daemon=True, name="trcc-metrics")
        self._metrics_thread.start()
        log.debug("Metrics loop started (interval=%.1fs)", interval)

    def stop_metrics_loop(self) -> None:
        """Stop the background metrics loop."""
        self._metrics_stop.set()
        if self._metrics_thread and self._metrics_thread.is_alive():
            self._metrics_thread.join(timeout=3)
        self._metrics_thread = None
        self._metrics_stop.clear()

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
        """Inject the renderer into the builder and ImageService.

        Called by InitPlatformCommand handler. Must wire ImageService immediately
        so that services (ThemeLoader, DisplayService) can use it before build_lcd()
        is called — e.g. CLI theme-load goes through DeviceService, not LCDDevice.
        """
        from ..services.image import ImageService
        self._builder.with_renderer(renderer)
        ImageService.set_renderer(renderer)

    # ── CommandBus factories ─────────────────────────────────────────────────

    def build_lcd_bus(self, lcd: LCDDevice) -> CommandBus:
        """Return a CommandBus wired to lcd — logging + timing middleware."""
        from .handlers.lcd import build_lcd_bus as _build
        return _build(lcd, self._ensure_data_fn)

    def build_lcd_gui_bus(self, lcd: LCDDevice) -> CommandBus:
        """Return a CommandBus wired for GUI — adds RateLimitMiddleware."""
        from .handlers.lcd import build_lcd_gui_bus as _build
        return _build(lcd, self._ensure_data_fn)

    def build_led_bus(self, led: LEDDevice) -> CommandBus:
        """Return a CommandBus wired to led — logging + timing middleware."""
        from .handlers.led import build_led_bus as _build
        return _build(led)

    def build_led_gui_bus(self, led: LEDDevice) -> CommandBus:
        """Return a CommandBus wired for GUI LED sliders — state-only update_* calls."""
        from .handlers.led import build_led_gui_bus as _build
        return _build(led)

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
