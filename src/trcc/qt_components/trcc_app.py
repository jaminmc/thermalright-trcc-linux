"""TRCCApp — thin shell main window (AppObserver).

Pure GUI adapter. Knows nothing about builders, detectors, or OS adapters.
Receives Device objects injected via on_app_event() from TrccApp (core).

One LCDHandler or LEDHandler per connected device, keyed by USB path.
Panel stack shows the currently selected device; all devices tick in background.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING, Any

from PySide6.QtCore import QRegularExpression as QRE
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QIcon, QPalette, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLabel,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

import trcc.conf as _conf
from trcc.conf import Settings

from ..adapters.infra.dc_writer import read_carousel_config
from ..core.app import AppEvent
from ..core.lcd_device import LCDDevice
from ..core.led_device import LEDDevice
from ..core.models import DeviceInfo
from ..core.ports import AutostartManager, GetDiskInfoFn, GetMemoryInfoFn, PlatformSetup
from ..services.system import SystemService
from .assets import Assets
from .base import create_image_button, set_background_pixmap
from .constants import Colors, Layout, Sizes, Styles
from .lcd_handler import LCDHandler
from .uc_about import UCAbout, ensure_autostart
from .uc_activity_sidebar import UCActivitySidebar
from .uc_device import UCDevice
from .uc_image_cut import UCImageCut
from .uc_info_module import UCInfoModule
from .uc_led_control import UCLedControl
from .uc_preview import UCPreview
from .uc_system_info import UCSystemInfo
from .uc_theme_local import UCThemeLocal
from .uc_theme_mask import UCThemeMask
from .uc_theme_setting import UCThemeSetting
from .uc_theme_web import UCThemeWeb
from .uc_video_cut import UCVideoCut

if TYPE_CHECKING:
    pass

log = logging.getLogger(__name__)


# =============================================================================
# LED Handler — mediator for one LED device
# =============================================================================

class LEDHandler:
    """Mediator for a single LED device.

    Owns LEDDevice lifecycle, animation timer, signal wiring.
    GUI signal handlers update state only — the 150ms tick handles animation + send.
    """

    _SAVE_INTERVAL = 20  # save config every N ticks (~3 s)

    def __init__(self, led: LEDDevice, panel: UCLedControl, on_temp_unit_changed: Any):
        self._panel = panel
        self._on_temp_unit_changed = on_temp_unit_changed
        self._led = led
        self._active = False
        self._style_id = 0
        self._save_counter = 0

        self._timer = QTimer(panel)
        self._timer.timeout.connect(self._on_tick)
        self._connect_signals()

    @property
    def active(self) -> bool:
        return self._active

    @property
    def has_controller(self) -> bool:
        return self._led is not None

    @property
    def led_port(self) -> LEDDevice | None:
        return self._led

    def show(self, device: DeviceInfo) -> None:
        """Initialize LED device and start animation."""
        model = device.model or ''
        from ..services.led import LEDService
        led_style = device.led_style_id or LEDService.resolve_style_id(model)

        self._led.initialize(device, led_style)
        self._style_id = led_style

        style_info = LEDService.get_style_info(led_style)
        if style_info:
            self._panel.initialize(
                led_style, style_info.segment_count, style_info.zone_count,
                model=model,
            )
        self._panel.set_memory_ratio(self._led.state.memory_ratio)
        self._sync_ui_from_state()

        seg_unit = "F" if _conf.settings.temp_unit == 1 else "C"
        self._led.set_seg_temp_unit(seg_unit)

        self._active = True
        self._timer.start(150)
        log.info("LED: show model=%s style=%d, tick timer started (150ms)", model, led_style)

    def stop(self) -> None:
        log.info("LED: stop (active=%s)", self._active)
        self._timer.stop()
        self._active = False
        if self._led:
            self._led.save_config()
            self._led.cleanup()

    def cleanup(self) -> None:
        log.info("LED: cleanup")
        self._timer.stop()
        if self._led:
            self._led.save_config()
            self._led.cleanup()

    def set_temp_unit(self, unit: str) -> None:
        if self._led:
            log.debug("LED: temp_unit=%s", unit)
            self._led.set_seg_temp_unit(unit)

    def update_from_metrics(self, metrics: Any) -> None:
        if not self._led:
            return
        self._led.update_metrics(metrics)
        self._panel.update_metrics(metrics)

    def _sync_ui_from_state(self) -> None:
        if not self._led:
            return
        state = self._led.state
        if state.zones:
            z = state.zones[0]
            self._panel.load_zone_state(0, z.mode.value, z.color, z.brightness, z.on)
        else:
            self._panel.load_zone_state(
                0, state.mode.value, state.color, state.brightness, state.global_on)
        log.debug("LED: synced UI from state (zones=%d)", len(state.zones))

    def _connect_signals(self) -> None:
        if not self._led:
            return
        p = self._panel
        p.mode_changed.connect(self._on_mode_changed)
        p.color_changed.connect(self._on_color_changed)
        p.brightness_changed.connect(self._on_brightness_changed)
        p.global_toggled.connect(self._on_global_toggled)
        p.segment_clicked.connect(self._on_segment_clicked)
        p.zone_selected.connect(self._on_zone_selected)
        p.zone_toggled.connect(self._on_zone_toggled)
        p.carousel_changed.connect(self._on_carousel_changed)
        p.carousel_zone_changed.connect(self._on_carousel_zone_changed)
        p.carousel_interval_changed.connect(self._on_carousel_interval_changed)
        p.clock_format_changed.connect(self._on_clock_format_changed)
        p.week_start_changed.connect(self._on_week_start_changed)
        p.temp_unit_changed.connect(self._on_temp_unit_changed)
        p.disk_index_changed.connect(self._on_disk_index_changed)
        p.memory_ratio_changed.connect(self._on_memory_ratio_changed)
        p.test_mode_changed.connect(self._on_test_mode_changed)

    # -- GUI signal handlers (state-only, timer sends) --

    def _on_mode_changed(self, mode: Any) -> None:
        if not self._led:
            return
        self._led.update_mode(mode)
        if self._led.state.zones:
            self._led.update_zone_mode(self._panel.selected_zone, mode)
        self._save_counter = self._SAVE_INTERVAL

    def _on_color_changed(self, r: int, g: int, b: int) -> None:
        if not self._led:
            return
        self._led.update_color(r, g, b)
        if self._led.state.zones:
            self._led.update_zone_color(self._panel.selected_zone, r, g, b)

    def _on_brightness_changed(self, val: int) -> None:
        if not self._led:
            return
        self._led.update_brightness(val)
        if self._led.state.zones:
            self._led.update_zone_brightness(self._panel.selected_zone, val)

    def _on_global_toggled(self, on: bool) -> None:
        if self._led:
            self._led.update_global_on(on)

    def _on_segment_clicked(self, idx: int) -> None:
        if self._led and 0 <= idx < len(self._led.state.segment_on):
            self._led.update_segment(idx, not self._led.state.segment_on[idx])

    def _on_zone_selected(self, zone_index: int) -> None:
        if not self._led or not self._led.state.zones:
            return
        self._led.update_selected_zone(zone_index)
        zones = self._led.state.zones
        if 0 <= zone_index < len(zones):
            z = zones[zone_index]
            self._panel.load_zone_state(zone_index, z.mode.value, z.color, z.brightness, z.on)

    def _on_zone_toggled(self, zi: int, on: bool) -> None:
        if self._led:
            self._led.update_zone_on(zi, on)

    def _on_carousel_changed(self, on: bool) -> None:
        if self._led:
            self._led.update_zone_sync(on)

    def _on_carousel_zone_changed(self, zi: int, sel: Any) -> None:
        if self._led:
            self._led.update_zone_sync_zone(zi, sel)

    def _on_carousel_interval_changed(self, secs: int) -> None:
        if self._led:
            self._led.update_zone_sync_interval(secs)

    def _on_clock_format_changed(self, is_24h: bool) -> None:
        if self._led:
            self._led.update_clock_format(is_24h)

    def _on_week_start_changed(self, is_sun: bool) -> None:
        if self._led:
            self._led.update_week_start(is_sun)

    def _on_disk_index_changed(self, idx: int) -> None:
        if self._led:
            self._led.update_disk_index(idx)

    def _on_memory_ratio_changed(self, ratio: int) -> None:
        if self._led:
            self._led.update_memory_ratio(ratio)

    def _on_test_mode_changed(self, on: bool) -> None:
        if self._led:
            self._led.update_test_mode(on)

    def _on_tick(self) -> None:
        if not (self._led and self._active):
            return
        try:
            result = self._led.tick_with_result()
            display_colors = result.get('display_colors')
            if display_colors is not None:
                self._panel.set_led_colors(display_colors)
            self._save_counter += 1
            if self._save_counter >= self._SAVE_INTERVAL:
                self._save_counter = 0
                self._led.save_config()
        except Exception:
            log.exception("LED tick error")


# =============================================================================
# Screencast Handler
# =============================================================================

class ScreencastHandler:
    """Mediator for screencast (screen capture → LCD)."""

    def __init__(self, parent: QWidget, on_frame: Any):
        self._on_frame = on_frame
        self._active = False
        self._x = self._y = self._w = self._h = 0
        self._border = True
        self._pipewire_cast = None
        self._lcd_w = 320
        self._lcd_h = 320
        self._capture_warn_logged = False

        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._active

    def set_lcd_size(self, w: int, h: int) -> None:
        self._lcd_w = w
        self._lcd_h = h

    def toggle(self, enabled: bool) -> None:
        self._active = enabled
        if enabled:
            from .screen_capture import is_wayland
            if is_wayland() and self._pipewire_cast is None:
                self._try_start_pipewire()
            self._timer.start(150)
        else:
            self._timer.stop()
            self._stop_pipewire()

    def stop(self) -> None:
        self._timer.stop()
        self._active = False

    def set_params(self, x: int, y: int, w: int, h: int) -> None:
        self._x, self._y, self._w, self._h = x, y, w, h

    def set_border(self, visible: bool) -> None:
        self._border = visible

    def cleanup(self) -> None:
        self._timer.stop()
        self._stop_pipewire()

    def _try_start_pipewire(self) -> None:
        from .pipewire_capture import PIPEWIRE_AVAILABLE, PipeWireScreenCast
        if not PIPEWIRE_AVAILABLE:
            return
        import threading
        cast = PipeWireScreenCast()
        self._pipewire_cast = cast
        def _start() -> None:
            if not cast.start(timeout=30):
                self._pipewire_cast = None
        threading.Thread(target=_start, daemon=True).start()

    def _stop_pipewire(self) -> None:
        if self._pipewire_cast is not None:
            self._pipewire_cast.stop()
            self._pipewire_cast = None

    def _tick(self) -> None:
        if not self._active or self._w <= 0 or self._h <= 0:
            return
        from PySide6.QtCore import QRect
        from PySide6.QtGui import QImage
        from PySide6.QtGui import Qt as QtGui_Qt
        frame_img: QImage | None = None

        if self._pipewire_cast is not None and self._pipewire_cast.is_running:
            frame = self._pipewire_cast.grab_frame()
            if frame is not None:
                fw, fh, rgb_bytes = frame
                full = QImage(rgb_bytes, fw, fh, fw * 3, QImage.Format.Format_RGB888)
                x1, y1 = min(self._x, fw), min(self._y, fh)
                x2, y2 = min(self._x + self._w, fw), min(self._y + self._h, fh)
                if x2 > x1 and y2 > y1:
                    frame_img = full.copy(QRect(x1, y1, x2 - x1, y2 - y1))

        if frame_img is None:
            from .screen_capture import grab_screen_region
            pixmap = grab_screen_region(self._x, self._y, self._w, self._h)
            if pixmap.isNull():
                if not self._capture_warn_logged:
                    log.warning("Screencast: all capture methods failed")
                    self._capture_warn_logged = True
                return
            self._capture_warn_logged = False
            frame_img = pixmap.toImage()

        frame_img = frame_img.scaled(
            self._lcd_w, self._lcd_h,
            QtGui_Qt.AspectRatioMode.IgnoreAspectRatio,
            QtGui_Qt.TransformationMode.SmoothTransformation)
        self._on_frame(frame_img)


# =============================================================================
# TRCCApp — Main Window / AppObserver
# =============================================================================

class TRCCApp(QMainWindow):
    """Main TRCC window — pure GUI adapter, AppObserver.

    Receives Device objects injected by TrccApp via on_app_event().
    Knows nothing about builders, detectors, or OS internals.

    One handler per device keyed by USB path:
      _lcd_handlers: dict[str, LCDHandler]
      _led_handlers: dict[str, LEDHandler]

    Panel stack shows the active device; all devices tick in background.
    """

    # Thread-safe bridge: core metrics loop → Qt main thread
    _metrics_signal: Signal = Signal(object)
    _device_added_signal: Signal = Signal(object)   # Device
    _device_removed_signal: Signal = Signal(object) # Device

    _instance: TRCCApp | None = None

    def __new__(cls, *args: Any, **kwargs: Any) -> TRCCApp:
        if cls._instance is not None:
            raise RuntimeError("TRCCApp is a singleton — use instance()")
        inst = super().__new__(cls)
        cls._instance = inst
        return inst

    @classmethod
    def instance(cls) -> TRCCApp | None:
        return cls._instance

    def is_app_visible(self) -> bool:
        return self.isVisible() and not self._minimized_to_taskbar

    def __init__(
        self,
        system_svc: SystemService,
        setup: PlatformSetup,
        autostart: AutostartManager,
        mem_fn: GetMemoryInfoFn,
        disk_fn: GetDiskInfoFn,
        decorated: bool = False,
    ) -> None:
        super().__init__()
        from trcc.__version__ import __version__
        log.info("TRCC v%s starting", __version__)

        # Injected platform deps — no builder, no OS imports
        self._system_svc = system_svc
        self._minimize_on_close = setup.minimize_on_close()
        self._autostart_manager = autostart

        self._decorated = decorated
        self._drag_pos = None
        self._force_quit = False
        self._minimized_to_taskbar = False
        self._data_dir = _conf.settings.user_data_dir

        self.setWindowTitle("TRCC-Linux - Thermalright LCD Control Center")
        self.setFixedSize(Sizes.WINDOW_W, Sizes.WINDOW_H)
        if not decorated:
            self.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        # Per-device handlers keyed by USB path
        self._lcd_handlers: dict[str, LCDHandler] = {}
        self._led_handlers: dict[str, LEDHandler] = {}
        self._active_path = ''       # path of device currently shown in panel stack

        self._handshake_pending = False
        self._cut_mode = 'background'
        self._mask_upload_filename = ''
        self._pixmap_refs: list = []

        # IPC server (set by composition root after construction)
        from ..ipc import IPCServer
        self._ipc_server: IPCServer | None = None

        # Build UI
        self._apply_dark_theme()
        self._setup_ui(mem_fn, disk_fn)

        # Screencast handler
        self._screencast = ScreencastHandler(self, self._on_screencast_frame)

        # Connect widget signals
        self._connect_view_signals()

        # Thread-safe signal bridges
        self._metrics_signal.connect(self._on_metrics_main_thread)
        self._device_added_signal.connect(self._on_device_added_main_thread)
        self._device_removed_signal.connect(self._on_device_removed_main_thread)

        # Handshake signal
        self._handshake_done = Signal(object, object)  # type: ignore[assignment]
        # Use a QObject notifier for handshake (thread → main thread)
        from PySide6.QtCore import QObject
        from PySide6.QtCore import Signal as _Signal
        class _HandshakeNotifier(QObject):
            done = _Signal(object, object)
        self._hs_notifier = _HandshakeNotifier(self)
        self._hs_notifier.done.connect(self._on_handshake_done)

        # Restore temp unit
        saved_unit = _conf.settings.temp_unit
        self.uc_system_info.set_temp_unit(saved_unit)
        self.uc_led_control.set_temp_unit(saved_unit)
        if saved_unit == 1:
            self.uc_about._set_temp('F')

        # Autostart
        autostart_state = ensure_autostart(self._autostart_manager)
        self.uc_about._autostart = autostart_state
        self.uc_about.startup_btn.setChecked(autostart_state)

        # System tray
        self._setup_systray()

        # Sleep monitor
        self._setup_sleep_monitor()

    # ── AppObserver ─────────────────────────────────────────────────

    def on_app_event(self, event: AppEvent, data: Any) -> None:
        """Receive events from TrccApp (called from any thread)."""
        if event == AppEvent.DEVICES_CHANGED:
            # data = list[Device] — full rescan result
            self._device_added_signal.emit(('changed', data))
        elif event == AppEvent.DEVICE_CONNECTED:
            self._device_added_signal.emit(('connected', data))
        elif event == AppEvent.DEVICE_LOST:
            self._device_removed_signal.emit(data)
        elif event == AppEvent.METRICS_UPDATED:
            self._metrics_signal.emit(data)

    # ── Device event handlers (main thread) ─────────────────────────

    def _on_device_added_main_thread(self, payload: Any) -> None:
        kind, data = payload
        if kind == 'changed':
            self._rebuild_all_handlers(data)
        else:
            self._add_handler(data)

    def _on_device_removed_main_thread(self, device: Any) -> None:
        path = device.device_info.path if device.device_info else ''
        self._remove_handler(path)

    def _rebuild_all_handlers(self, devices: list) -> None:
        """Replace all handlers with new device list from scan()."""
        # Stop and remove existing
        for handler in list(self._lcd_handlers.values()):
            handler.cleanup()
        for handler in list(self._led_handlers.values()):
            handler.cleanup()
        self._lcd_handlers.clear()
        self._led_handlers.clear()
        self._active_path = ''

        for device in devices:
            self._add_handler(device)

        self._refresh_sidebar()

        # Auto-select first device
        if self._lcd_handlers:
            first_path = next(iter(self._lcd_handlers))
            self._activate_device(first_path)
        elif self._led_handlers:
            first_path = next(iter(self._led_handlers))
            self._activate_device(first_path)

    def _add_handler(self, device: Any) -> None:
        """Create handler for one new device."""
        info = device.device_info
        if info is None:
            log.warning("Device has no device_info, skipping")
            return
        path = info.path

        if isinstance(device, LEDDevice):
            if path not in self._led_handlers:
                handler = LEDHandler(device, self.uc_led_control, self._on_temp_unit_changed)
                self._led_handlers[path] = handler
                log.info("LED handler added: %s", path)
        elif isinstance(device, LCDDevice):
            if path not in self._lcd_handlers:
                widgets = {
                    'preview': self.uc_preview,
                    'theme_setting': self.uc_theme_setting,
                    'theme_local': self.uc_theme_local,
                    'theme_web': self.uc_theme_web,
                    'theme_mask': self.uc_theme_mask,
                    'image_cut': self.uc_image_cut,
                    'video_cut': self.uc_video_cut,
                    'rotation_combo': self.rotation_combo,
                }
                handler = LCDHandler(
                    device, widgets, self._make_timer, self._data_dir,
                    is_visible_fn=self.is_app_visible)
                self._lcd_handlers[path] = handler
                log.info("LCD handler added: %s", path)
                # Wire IPC frame capture if server is already running
                if self._ipc_server and handler.display.device_service:
                    handler.display.device_service.on_frame_sent = self._ipc_server.capture_frame

        self._refresh_sidebar()

    def _remove_handler(self, path: str) -> None:
        """Remove and cleanup one device handler."""
        if path in self._lcd_handlers:
            self._lcd_handlers.pop(path).cleanup()
            log.info("LCD handler removed: %s", path)
        elif path in self._led_handlers:
            self._led_handlers.pop(path).cleanup()
            log.info("LED handler removed: %s", path)

        if self._active_path == path:
            self._active_path = ''
            # Auto-switch to first remaining device
            remaining = list(self._lcd_handlers) + list(self._led_handlers)
            if remaining:
                self._activate_device(remaining[0])

        self._refresh_sidebar()

    def _refresh_sidebar(self) -> None:
        """Update UCDevice with current device list."""
        devices: list[dict] = []
        for path, handler in self._lcd_handlers.items():
            info = handler.display.device_info if handler.display else None
            if info:
                devices.append(info.to_dict() if hasattr(info, 'to_dict') else {'path': path})
        for path, handler in self._led_handlers.items():
            info = handler.led_port.device_info if handler.led_port else None
            if info:
                devices.append(info.to_dict() if hasattr(info, 'to_dict') else {'path': path})
        self.uc_device.update_devices(devices)

    def _activate_device(self, path: str) -> None:
        """Switch panel stack to show the given device."""
        self._active_path = path

        if path in self._lcd_handlers:
            handler = self._lcd_handlers[path]
            if handler.display.connected:
                info = handler.display.device_info
                if info:
                    w, h = info.resolution
                    if (w, h) == (0, 0):
                        self._start_handshake(info)
                    else:
                        handler.apply_device_config(info, w, h)
                        self._update_ldd_icon()
            if self._led_handlers:
                # Keep LED ticking but hide its panel
                pass
            self._show_view('form')

        elif path in self._led_handlers:
            handler = self._led_handlers[path]
            info = handler.led_port.device_info if handler.led_port else None
            if info and not handler.active:
                handler.show(info)
            self._show_view('led')

    # ── Metrics (main thread only) ───────────────────────────────────

    def _on_metrics_main_thread(self, metrics: Any) -> None:
        """Update GUI-only subscribers. Devices are already ticked by TrccApp."""
        if self.uc_info_module.isVisible():
            self.uc_info_module.update_from_metrics(metrics)
        if self.is_app_visible() and self.uc_activity_sidebar.isVisible():
            self.uc_activity_sidebar.update_from_metrics(metrics)

        # Active LCD overlay tick
        if self._active_path in self._lcd_handlers:
            self._lcd_handlers[self._active_path].on_overlay_tick(metrics)

        # Periodic keepalive for active LCD
        # (keepalive is handled inside LCDHandler on its own timer)

    # ── Sleep monitor ───────────────────────────────────────────────

    def _setup_sleep_monitor(self) -> None:
        try:
            from PySide6.QtDBus import QDBusConnection  # pyright: ignore[reportMissingImports]
            bus = QDBusConnection.systemBus()
            if not bus.isConnected():
                return
            bus.connect(  # pyright: ignore[reportCallIssue]
                'org.freedesktop.login1', '/org/freedesktop/login1',
                'org.freedesktop.login1.Manager', 'PrepareForSleep',
                self._on_sleep_signal)
            log.info("Sleep monitor: QDBus listener active")
        except Exception:
            log.debug("Sleep monitor: QDBus not available")

    def _on_sleep_signal(self, sleeping: bool) -> None:
        if sleeping:
            log.info("System suspending — stopping timers")
            for h in self._lcd_handlers.values():
                h.stop_timers()
            self._screencast.stop()
        else:
            log.info("System resuming — TrccApp metrics loop handles device ticking")

    # ── Timers ──────────────────────────────────────────────────────

    def _make_timer(self, callback: Any, *, single_shot: bool = False) -> QTimer:
        timer = QTimer(self)
        if single_shot:
            timer.setSingleShot(True)
        timer.timeout.connect(callback)
        return timer

    # ── Dark theme ──────────────────────────────────────────────────

    def _apply_dark_theme(self) -> None:
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(Colors.WINDOW_BG))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(Colors.WINDOW_TEXT))
        palette.setColor(QPalette.ColorRole.Base, QColor(Colors.BASE_BG))
        palette.setColor(QPalette.ColorRole.Text, QColor(Colors.TEXT))
        palette.setColor(QPalette.ColorRole.Button, QColor(Colors.BUTTON_BG))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(Colors.BUTTON_TEXT))
        self.setPalette(palette)

    # ── System tray ─────────────────────────────────────────────────

    def _setup_systray(self) -> None:
        icon_path = Path(__file__).parent.parent / 'assets' / 'icons' / 'trcc.png'
        icon = QIcon(str(icon_path)) if icon_path.exists() else QIcon()
        self.setWindowIcon(icon)

        self._tray = QSystemTrayIcon(icon, self)
        self._tray.setToolTip("TRCC Linux")

        menu = QMenu()
        show_action = menu.addAction("Show/Hide")
        if show_action:
            show_action.triggered.connect(self._toggle_visibility)
        menu.addSeparator()
        exit_action = menu.addAction("Exit")
        if exit_action:
            exit_action.triggered.connect(self._quit_app)
        self._tray.setContextMenu(menu)
        self._tray.activated.connect(self._on_tray_activated)
        self._tray.show()

    def _on_tray_activated(self, reason: Any) -> None:
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visibility()

    def _toggle_visibility(self) -> None:
        if self.isVisible():
            self.hide()
        else:
            self._minimized_to_taskbar = False
            self.show()
            self.activateWindow()
            self.raise_()

    def _quit_app(self) -> None:
        self._force_quit = True
        self.close()

    # ── UI Setup ────────────────────────────────────────────────────

    def _setup_ui(self, mem_fn: GetMemoryInfoFn, disk_fn: GetDiskInfoFn) -> None:
        """Build main UI layout."""
        central = QWidget()
        self.setCentralWidget(central)

        pix_form1 = set_background_pixmap(central, Assets.FORM1_BG,
            width=Sizes.WINDOW_W, height=Sizes.WINDOW_H,
            fallback_style=f"background-color: {Colors.WINDOW_BG};")
        if pix_form1:
            self._pixmap_refs.append(pix_form1)

        # Device sidebar — no detect_fn, populated via on_app_event
        self.uc_device = UCDevice(central)
        self.uc_device.setGeometry(*Layout.SIDEBAR)

        # FormCZTV container
        self.form_container = QWidget(central)
        self.form_container.setGeometry(*Layout.FORM_CONTAINER)
        pix = set_background_pixmap(self.form_container, Assets.FORM_CZTV_BG,
            fallback_style=f"background-color: {Colors.WINDOW_BG};")
        if pix:
            self._pixmap_refs.append(pix)

        # Preview
        self.uc_preview = UCPreview(
            _conf.settings.width, _conf.settings.height, self.form_container)
        self.uc_preview.setGeometry(*Layout.PREVIEW)

        # Info module
        self.uc_info_module = UCInfoModule(self.form_container)
        self.uc_info_module.setGeometry(16, 16, 500, 70)
        self.uc_info_module.setVisible(False)

        # Image/video cutters
        self.uc_image_cut = UCImageCut(self.form_container)
        self.uc_image_cut.setGeometry(16, 88, 500, 702)
        self.uc_image_cut.setVisible(False)

        self.uc_video_cut = UCVideoCut(self.form_container)
        self.uc_video_cut.setGeometry(16, 88, 500, 702)
        self.uc_video_cut.setVisible(False)

        # Mode tabs
        self._create_mode_tabs()

        # Theme panel stack
        self.panel_stack = QStackedWidget(self.form_container)
        self.panel_stack.setGeometry(*Layout.PANEL_STACK)

        self.uc_theme_local = UCThemeLocal()
        self._set_panel_bg(self.uc_theme_local, Assets.THEME_LOCAL_BG)
        self.panel_stack.addWidget(self.uc_theme_local)

        from ..adapters.infra.data_repository import DataManager
        from ..adapters.infra.theme_cloud import CloudThemeDownloader
        def _download_theme(theme_id: str, resolution: str, cache_dir: str) -> str | None:
            return CloudThemeDownloader(resolution=resolution, cache_dir=cache_dir).download_theme(theme_id)
        def _extract_theme(archive: str, dest: str) -> None:
            DataManager.extract_7z(archive, dest)
            DataManager._unwrap_nested_dir(dest)
        self.uc_theme_web = UCThemeWeb(download_fn=_download_theme, extract_fn=_extract_theme)
        self._set_panel_bg(self.uc_theme_web, Assets.THEME_WEB_BG)
        self.panel_stack.addWidget(self.uc_theme_web)

        self.uc_theme_setting = UCThemeSetting()
        self.panel_stack.addWidget(self.uc_theme_setting)

        self.uc_theme_mask = UCThemeMask()
        self._set_panel_bg(self.uc_theme_mask, Assets.THEME_MASK_BG)
        self.panel_stack.addWidget(self.uc_theme_mask)

        # Activity sidebar
        self.uc_activity_sidebar = UCActivitySidebar(self.form_container)
        self.uc_activity_sidebar.setGeometry(532, 128, 250, 500)
        self.uc_activity_sidebar.setVisible(False)

        # Bottom controls + title buttons
        self._create_bottom_controls()
        self._create_title_buttons()
        self._apply_settings_backgrounds()

        # About panel
        self.uc_about = UCAbout(parent=central, autostart_manager=self._autostart_manager)
        self.uc_about.setGeometry(*Layout.FORM_CONTAINER)
        self.uc_about.setVisible(False)

        # System info dashboard
        from ..adapters.system.config import SysInfoConfig
        self.uc_system_info = UCSystemInfo(
            self._system_svc.enumerator,
            sysinfo_config=SysInfoConfig(),
            parent=central)
        self.uc_system_info.setGeometry(*Layout.SYSINFO_PANEL)
        self.uc_system_info.setVisible(False)

        # LED panel — hardware fns injected
        self.uc_led_control = UCLedControl(central)
        self.uc_led_control.setGeometry(*Layout.FORM_CONTAINER)
        self.uc_led_control.setVisible(False)
        self.uc_led_control.set_hardware_fns(mem_fn, disk_fn)

        # Form1 buttons
        self.form1_close_btn = create_image_button(
            central, *Layout.FORM1_CLOSE_BTN,
            Assets.BTN_POWER, Assets.BTN_POWER_HOVER, fallback_text="X")
        self.form1_close_btn.setToolTip("Close")
        self.form1_close_btn.clicked.connect(self.close)

        self.form1_help_btn = create_image_button(
            central, *Layout.FORM1_HELP_BTN,
            Assets.BTN_HELP, None, fallback_text="?")
        self.form1_help_btn.setToolTip("Help")
        self.form1_help_btn.clicked.connect(self._on_help_clicked)

        self._create_i18n_overlays()
        self._init_theme_directories()

    def _set_panel_bg(self, widget: QWidget, asset_name: str) -> None:
        pix = set_background_pixmap(widget, asset_name)
        if pix:
            self._pixmap_refs.append(pix)

    def _create_mode_tabs(self) -> None:
        self.mode_buttons = []
        tab_configs = [
            (Layout.TAB_LOCAL, Assets.TAB_LOCAL, Assets.TAB_LOCAL_ACTIVE, 0, "Local themes"),
            (Layout.TAB_MASK, Assets.TAB_MASK, Assets.TAB_MASK_ACTIVE, 3, "Cloud masks"),
            (Layout.TAB_CLOUD, Assets.TAB_CLOUD, Assets.TAB_CLOUD_ACTIVE, 1, "Cloud backgrounds"),
            (Layout.TAB_SETTINGS, Assets.TAB_SETTINGS, Assets.TAB_SETTINGS_ACTIVE, 2, "Settings"),
        ]
        for rect, normal_img, active_img, panel_idx, tooltip in tab_configs:
            x, y, w, h = rect
            btn = create_image_button(
                self.form_container, x, y, w, h,
                normal_img, active_img, checkable=True)
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, idx=panel_idx: self._show_panel(idx))
            self.mode_buttons.append(btn)
        if self.mode_buttons:
            self.mode_buttons[0].setChecked(True)

    def _create_bottom_controls(self) -> None:
        self.rotation_combo = QComboBox(self.form_container)
        self.rotation_combo.setGeometry(*Layout.ROTATION_COMBO)
        self.rotation_combo.addItems(["0°", "90°", "180°", "270°"])
        self.rotation_combo.setStyleSheet(
            "QComboBox { background-color: #2A2A2A; color: white; border: 1px solid #555;"
            " font-size: 10px; padding-left: 5px; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
            "QComboBox QAbstractItemView { background-color: #2A2A2A; color: white;"
            " selection-background-color: #4A6FA5; }")
        self.rotation_combo.setToolTip("LCD rotation")
        self.rotation_combo.currentIndexChanged.connect(self._on_rotation_change)

        self._ldd_pixmaps: dict = {}
        for level in range(4):
            pix = Assets.load_pixmap(f'PL{level}.png')
            if not pix.isNull():
                self._ldd_pixmaps[level] = pix

        self.ldd_btn = QPushButton(self.form_container)
        self.ldd_btn.setGeometry(*Layout.BRIGHTNESS_BTN)
        self.ldd_btn.setToolTip("Cycle brightness (Low / Medium / High)")
        self.ldd_btn.clicked.connect(self._on_ldd_click)
        self._update_ldd_icon()

        self.theme_name_input = QLineEdit(self.form_container)
        self.theme_name_input.setGeometry(*Layout.THEME_NAME_INPUT)
        self.theme_name_input.setText("Theme1")
        self.theme_name_input.setMaxLength(10)
        self.theme_name_input.setToolTip("Theme name for saving")
        self.theme_name_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.theme_name_input.setStyleSheet(
            "background-color: #232227; color: white; border: none;"
            " font-family: 'Microsoft YaHei'; font-size: 9pt;")
        self.theme_name_input.setValidator(
            QRegularExpressionValidator(QRE(r'[^/\\:*?"<>|\x00-\x1f]+')))

        self.save_btn = self._icon_btn(*Layout.SAVE_BTN, Assets.BTN_SAVE, "S")
        self.save_btn.setToolTip("Save theme")
        self.save_btn.clicked.connect(self._on_save_clicked)

        self.export_btn = self._icon_btn(*Layout.EXPORT_BTN, Assets.BTN_EXPORT, "Exp")
        self.export_btn.setToolTip("Export theme to file")
        self.export_btn.clicked.connect(self._on_export_clicked)

        self.import_btn = self._icon_btn(*Layout.IMPORT_BTN, Assets.BTN_IMPORT, "Imp")
        self.import_btn.setToolTip("Import theme from file")
        self.import_btn.clicked.connect(self._on_import_clicked)

    def _icon_btn(self, x: int, y: int, w: int, h: int,
                  icon_name: str, fallback_text: str) -> QPushButton:
        btn = QPushButton(self.form_container)
        btn.setGeometry(x, y, w, h)
        pix = Assets.load_pixmap(icon_name, w, h)
        if not pix.isNull():
            btn.setIcon(QIcon(pix))
            btn.setIconSize(btn.size())
            btn.setStyleSheet(Styles.ICON_BUTTON_HOVER)
            self._pixmap_refs.append(pix)
        else:
            btn.setText(fallback_text)
            btn.setStyleSheet(Styles.TEXT_BUTTON)
        return btn

    def _create_title_buttons(self) -> None:
        help_btn = create_image_button(
            self.form_container, *Layout.HELP_BTN, Assets.BTN_HELP, None, fallback_text="?")
        help_btn.setToolTip("Help")
        help_btn.clicked.connect(self._on_help_clicked)

        close_btn = create_image_button(
            self.form_container, *Layout.CLOSE_BTN,
            Assets.BTN_POWER, Assets.BTN_POWER_HOVER, fallback_text="X")
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.close)

    def _apply_settings_backgrounds(self) -> None:
        s = self.uc_theme_setting
        for panel, bg_name in [
            (s.mask_panel, 'Panel_background.png'),
            (s.background_panel, 'Panel_background.png'),
            (s.screencast_panel, 'Panel_background.png'),
            (s.video_panel, 'Panel_background.png'),
            (s.overlay_grid, 'Panel_overlay.png'),
            (s.color_panel, 'Panel_params.png'),
        ]:
            self._set_panel_bg(panel, bg_name)

    def _init_theme_directories(self) -> None:
        w, h = _conf.settings.width, _conf.settings.height
        td = _conf.settings.theme_dir
        if td:
            self.uc_theme_local.set_theme_directory(td.path)
            if td.exists():
                self._load_carousel_config(td.path)
        if _conf.settings.web_dir:
            self.uc_theme_web.set_web_directory(_conf.settings.web_dir)
        self.uc_theme_web.set_resolution(f'{w}x{h}')
        if _conf.settings.masks_dir:
            self.uc_theme_mask.set_mask_directory(_conf.settings.masks_dir)
        self.uc_theme_mask.set_resolution(f'{w}x{h}')

    # ── i18n overlays ───────────────────────────────────────────────

    def _create_i18n_overlays(self) -> None:
        from ..core.i18n import (
            ABOUT_AUTOSTART_POS,
            ABOUT_HDD_POS,
            ABOUT_HDD_WARN_POS,
            ABOUT_LANG_POS,
            ABOUT_MULTI_THREAD_POS,
            ABOUT_REFRESH_POS,
            ABOUT_RUNNING_MODE_POS,
            ABOUT_SINGLE_THREAD_POS,
            ABOUT_UNIT_POS,
            ABOUT_UPDATE_POS,
            ABOUT_VERSION_POS,
            BACKGROUND_LOAD_IMG_POS,
            BACKGROUND_LOAD_VIDEO_POS,
            DISPLAY_ANGLE_POS,
            EXPORT_IMPORT_POS,
            GALLERY_TAB_FONT,
            GALLERY_TAB_H,
            GALLERY_TAB_Y,
            GALLERY_TITLE_POS,
            LANGUAGE_NAMES,
            LOCAL_THEME_POS,
            MASK_DESC_POS,
            MASK_LOAD_POS,
            MASK_UPLOAD_POS,
            MEDIA_PLAYER_LOAD_POS,
            ONLINE_THEME_POS,
            OVERLAY_GRID_HINT_POS,
            PARAM_COLOUR_POS,
            PARAM_COORDINATE_POS,
            PARAM_FONT_POS,
            SAVE_AS_POS,
            SYSINFO_NAME_POS,
            SYSINFO_VALUE_POS,
            TITLE_BAR_POS,
            TITLE_BAR_TEXT,
            tr,
        )
        lang = _conf.settings.lang
        self._i18n_labels: list[tuple[QLabel, str | None]] = []

        def _lbl(parent: QWidget, text: str, x: int, y: int, w: int, h: int,
                 pt: int, key: str | None = None,
                 bold: bool = False, color: str = 'white',
                 wrap: bool = False, center: bool = False) -> QLabel:
            y_offset = max(2, pt // 4)
            lbl = QLabel(text, parent)
            lbl.setGeometry(x, y - y_offset, w, h)
            weight = " font-weight: bold;" if bold else ""
            lbl.setStyleSheet(
                f"color: {color}; font-family: 'Microsoft YaHei';"
                f" font-size: {pt}pt;{weight} background: transparent;")
            if wrap:
                lbl.setWordWrap(True)
            if center:
                lbl.setAlignment(Qt.AlignmentFlag.AlignHCenter)
            lbl.raise_()
            self._i18n_labels.append((lbl, key))
            return lbl

        x, y, w, h, pt = TITLE_BAR_POS
        _lbl(self.form_container, TITLE_BAR_TEXT, x, y, w, h, pt, bold=True, color='#434343')

        for key, pos in [
            ('Display Angle', DISPLAY_ANGLE_POS),
            ('Save As', SAVE_AS_POS),
            ('Export/Import', EXPORT_IMPORT_POS),
        ]:
            x, y, w, h, pt = pos
            _lbl(self.form_container, tr(key, lang), x, y, w, h, pt, key)

        grid = self.uc_theme_setting.data_table
        x, y, w, h, pt = OVERLAY_GRID_HINT_POS
        _lbl(grid, tr('Double-click to delete card', lang), x, y, w, h, pt,
             'Double-click to delete card')

        rpanel = self.uc_theme_setting.right_stack
        for key, pos in [
            ('Coordinate', PARAM_COORDINATE_POS),
            ('Font', PARAM_FONT_POS),
            ('Colour', PARAM_COLOUR_POS),
        ]:
            x, y, w, h, pt = pos
            _lbl(rpanel, tr(key, lang), x, y, w, h, pt, key)

        s = self.uc_theme_setting
        s.mask_panel.set_title(tr('Layer Mask', lang))
        s.background_panel.set_title(tr('Background', lang))
        s.screencast_panel.set_title(tr('Screencast', lang))
        s.video_panel.set_title(tr('Media Player', lang))
        self._i18n_panel_tables = [
            (s.mask_panel, 'Layer Mask'),
            (s.background_panel, 'Background'),
            (s.screencast_panel, 'Screencast'),
            (s.video_panel, 'Media Player'),
        ]

        mp = s.mask_panel
        x, y, w, h, pt = MASK_LOAD_POS
        _lbl(mp, tr('Masks', lang), x, y, w, h, pt, 'Masks', center=True)
        x, y, w, h, pt = MASK_UPLOAD_POS
        _lbl(mp, tr('Upload', lang), x, y, w, h, pt, 'Upload', center=True)
        x, y, w, h, pt = MASK_DESC_POS
        _lbl(mp, tr('PNG format, resolution must not exceed screen resolution', lang),
             x, y, w, h, pt,
             'PNG format, resolution must not exceed screen resolution', wrap=True)

        bp = s.background_panel
        for key, pos in [('Load Image', BACKGROUND_LOAD_IMG_POS),
                         ('Load Video', BACKGROUND_LOAD_VIDEO_POS)]:
            x, y, w, h, pt = pos
            _lbl(bp, tr(key, lang), x, y, w, h, pt, key)

        vp = s.video_panel
        x, y, w, h, pt = MEDIA_PLAYER_LOAD_POS
        _lbl(vp, tr('Load Video', lang), x, y, w, h, pt, 'Load Video')

        x, y, w, h, pt = LOCAL_THEME_POS
        _lbl(self.uc_theme_local, tr('Local Theme', lang), x, y, w, h, pt, 'Local Theme')

        x, y, w, h, pt = ONLINE_THEME_POS
        _lbl(self.uc_theme_mask, tr('Cloud Masks', lang), x, y, w, h, pt, 'Cloud Masks')

        x, y, w, h, pt = GALLERY_TITLE_POS
        _lbl(self.uc_theme_web, tr('Gallery', lang), x, y, w, h, pt, 'Gallery')
        tab_x_positions = [45, 135, 235, 335, 430, 525, 635]
        tab_keys: list[str | None] = ['All', 'Tech', None, 'Light', 'Nature', 'Aesthetic', 'Other']
        for tx, key in zip(tab_x_positions, tab_keys):
            text = 'HUD' if key is None else tr(key, lang)
            lbl = _lbl(self.uc_theme_web, text,
                       tx, GALLERY_TAB_Y, 90, GALLERY_TAB_H, GALLERY_TAB_FONT, key)
            lbl.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)

        about_items: list[tuple[str, tuple[int, ...]]] = [
            ('Start automatically', ABOUT_AUTOSTART_POS),
            ('Unit', ABOUT_UNIT_POS),
            ('Hard disk information', ABOUT_HDD_POS),
            ('Reading hard disk information may cause some mechanical hard drives to read and write frequently. If you encounter this issue, please close the project.',
             ABOUT_HDD_WARN_POS),
            ('Data refresh time', ABOUT_REFRESH_POS),
            ('Running Mode', ABOUT_RUNNING_MODE_POS),
            ('Single-threaded (low resource usage)', ABOUT_SINGLE_THREAD_POS),
            ('Multi-threaded (high resource usage)', ABOUT_MULTI_THREAD_POS),
            ('Software Update', ABOUT_UPDATE_POS),
            ('Language selection', ABOUT_LANG_POS),
            ('Software version:', ABOUT_VERSION_POS),
        ]
        for key, pos in about_items:
            x, y, w, h, pt = pos
            _lbl(self.uc_about, tr(key, lang), x, y, w, h, pt, key)

        lang_combo = QComboBox(self.uc_about)
        lang_combo.setGeometry(297, 413, 200, 28)
        for code in sorted(LANGUAGE_NAMES, key=lambda c: LANGUAGE_NAMES[c]):
            lang_combo.addItem(LANGUAGE_NAMES[code], code)
        idx = lang_combo.findData(lang)
        if idx >= 0:
            lang_combo.setCurrentIndex(idx)
        lang_combo.setStyleSheet(
            "QComboBox { background: #2A2A2A; color: white; border: 1px solid #555;"
            " font-size: 10pt; padding-left: 5px; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
            "QComboBox QAbstractItemView { background: #2A2A2A; color: white;"
            " selection-background-color: #3A3A3A; }")
        lang_combo.raise_()

        def _on_preview_lang(index: int) -> None:
            new_lang = lang_combo.itemData(index)
            for lbl, key in self._i18n_labels:
                if key is not None:
                    lbl.setText(tr(key, new_lang))
            for panel, key in self._i18n_panel_tables:
                panel.set_title(tr(key, new_lang))
            self.uc_about._on_lang_clicked(new_lang)

        lang_combo.currentIndexChanged.connect(_on_preview_lang)

        for key, pos in [('NAME', SYSINFO_NAME_POS), ('Value', SYSINFO_VALUE_POS)]:
            x, y, w, h, pt = pos
            _lbl(self.uc_system_info, tr(key, lang), x, y, w, h, pt, key)

    # ── View Navigation ─────────────────────────────────────────────

    def _show_panel(self, index: int) -> None:
        self.panel_stack.setCurrentIndex(index)
        panel_to_button = {0: 0, 1: 2, 2: 3, 3: 1}
        active_btn = panel_to_button.get(index, 0)
        for i, btn in enumerate(self.mode_buttons):
            btn.setChecked(i == active_btn)
        if index != 2:
            self.uc_activity_sidebar.setVisible(False)

    def _show_view(self, view: str) -> None:
        self.form_container.setVisible(view == 'form')
        self.uc_about.setVisible(view == 'about')
        self.uc_system_info.setVisible(view == 'sysinfo')
        self.uc_led_control.setVisible(view == 'led')
        self.uc_activity_sidebar.setVisible(False)

        show_form1_btns = (view == 'sysinfo')
        self.form1_close_btn.setVisible(show_form1_btns)
        self.form1_help_btn.setVisible(show_form1_btns)

        if view == 'sysinfo':
            self.uc_system_info.start_updates()
        else:
            self.uc_system_info.stop_updates()

    # ── Signal Wiring ───────────────────────────────────────────────

    def _connect_view_signals(self) -> None:
        self.uc_device.device_selected.connect(self._on_device_widget_clicked)
        self.uc_device.home_clicked.connect(lambda: self._show_view('sysinfo'))
        self.uc_device.about_clicked.connect(lambda: self._show_view('about'))

        self.uc_theme_local.theme_selected.connect(self._on_local_theme_clicked)
        self.uc_theme_local.delete_requested.connect(self._on_delete_theme)
        self.uc_theme_local.delegate.connect(self._on_local_delegate)
        self.uc_theme_web.theme_selected.connect(self._on_cloud_theme_clicked)
        self.uc_theme_web.download_started.connect(
            lambda tid: self.uc_preview.set_status(f"Downloading: {tid}..."))
        self.uc_theme_web.download_finished.connect(
            lambda tid, ok: self.uc_preview.set_status(
                f"{'Downloaded' if ok else 'Download failed'}: {tid}"))
        self.uc_theme_mask.mask_selected.connect(self._on_mask_clicked)
        self.uc_theme_mask.download_started.connect(
            lambda mask_id: self.uc_preview.set_status(f"Downloading: {mask_id}..."))
        self.uc_theme_mask.download_finished.connect(
            lambda mask_id, ok: self.uc_preview.set_status(
                f"{'Downloaded' if ok else 'Failed'}: {mask_id}"))

        self.uc_preview.delegate.connect(self._on_preview_delegate)
        self.uc_preview.element_drag_start.connect(self._on_drag_start)
        self.uc_preview.element_drag_move.connect(self._on_drag_move)
        self.uc_preview.element_drag_end.connect(lambda: None)
        self.uc_preview.element_nudge.connect(self._on_nudge)
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._drag_elem_x = 0
        self._drag_elem_y = 0

        self.uc_theme_setting.background_changed.connect(self._on_background_toggle)
        self.uc_theme_setting.screencast_changed.connect(self._on_screencast_toggle)
        self.uc_theme_setting.delegate.connect(self._on_settings_delegate)
        self.uc_theme_setting.add_panel.hardware_requested.connect(
            self._on_overlay_add_requested)
        self.uc_theme_setting.add_panel.element_added.connect(
            lambda _: self.uc_activity_sidebar.setVisible(False))
        self.uc_theme_setting.overlay_grid.toggle_changed.connect(self._on_overlay_toggle)
        self.uc_theme_setting.overlay_grid.element_selected.connect(self._on_element_flash)
        self.uc_theme_setting.screencast_params_changed.connect(
            lambda x, y, w, h: self._screencast.set_params(x, y, w, h))
        self.uc_theme_setting.screencast_panel.border_toggled.connect(self._screencast.set_border)
        self.uc_theme_setting.capture_requested.connect(self._on_capture_requested)
        self.uc_theme_setting.eyedropper_requested.connect(self._on_eyedropper_requested)

        self.uc_image_cut.image_cut_done.connect(self._on_image_cut_done)
        self.uc_video_cut.video_cut_done.connect(self._on_video_cut_done)

        self.uc_activity_sidebar.sensor_clicked.connect(self._on_sensor_element_add)

        self.uc_about.close_requested.connect(
            lambda: (self._show_view('form'), self.uc_device.restore_device_selection()))
        self.uc_led_control.close_requested.connect(
            lambda: (self._show_view('form'), self.uc_device.restore_device_selection()))
        self.uc_about.language_changed.connect(self._set_language)
        self.uc_about.temp_unit_changed.connect(self._on_temp_unit_changed)
        self.uc_about.hdd_toggle_changed.connect(self._on_hdd_toggle_changed)
        self.uc_about.refresh_changed.connect(self._on_refresh_changed)

    # ── Device Selection ────────────────────────────────────────────

    def _on_device_widget_clicked(self, device_info: dict) -> None:
        """User clicked a device in the sidebar."""
        path = device_info.get('path', '')
        if path:
            self._activate_device(path)

    def _active_lcd(self) -> LCDHandler | None:
        return self._lcd_handlers.get(self._active_path)

    def _active_led(self) -> LEDHandler | None:
        return self._led_handlers.get(self._active_path)

    # ── Handshake (LCD resolution discovery) ────────────────────────

    def _start_handshake(self, device: DeviceInfo) -> None:
        if self._handshake_pending:
            return
        self._handshake_pending = True
        self.uc_preview.set_status("Connecting to device...")

        import threading
        def worker() -> None:
            try:
                from ..adapters.device.factory import DeviceProtocolFactory
                protocol = DeviceProtocolFactory.get_protocol(device)
                result = protocol.handshake()
                if result:
                    resolution = getattr(result, 'resolution', None)
                    fbl = getattr(result, 'fbl', None) or getattr(result, 'model_id', None)
                    pm = getattr(result, 'pm_byte', 0)
                    sub = getattr(result, 'sub_byte', 0)
                    self._hs_notifier.done.emit(device, (resolution, fbl, pm, sub))
                else:
                    self._hs_notifier.done.emit(device, None)
            except Exception as e:
                log.warning("Handshake failed: %s", e)
                self._hs_notifier.done.emit(device, None)
        threading.Thread(target=worker, daemon=True).start()

    def _on_handshake_done(self, device: DeviceInfo, data: tuple | None) -> None:
        self._handshake_pending = False
        if not data:
            self.uc_preview.set_status("Handshake failed — replug device")
            return
        resolution, fbl, pm, sub = data
        if not resolution or resolution == (0, 0):
            self.uc_preview.set_status("Handshake failed — no resolution")
            return
        log.info("Handshake OK: %s -> %s (FBL=%s)", device.path, resolution, fbl)
        device.resolution = resolution
        if fbl:
            device.fbl_code = fbl
            self._resolve_device_identity(device, pm or fbl, sub)

        handler = self._lcd_handlers.get(device.path)
        if handler:
            w, h = resolution
            handler.apply_device_config(device, w, h)
            self._update_ldd_icon()
            if Settings.show_info_module():
                self.uc_info_module.setVisible(True)

    def _resolve_device_identity(self, device: DeviceInfo, pm: int, sub: int = 0) -> None:
        from ..core.models import get_button_image
        btn_img = get_button_image(pm, sub)
        if not btn_img:
            return
        product = btn_img.replace('A1', '', 1).replace('_', ' ')
        for dev in self.uc_device.devices:
            if dev.get('path') == device.path:
                dev['button_image'] = btn_img
                dev['product'] = product
                dev['name'] = f"Thermalright {product}"
                self.uc_device.update_device_button(dev)
                break
        active_key = Settings.device_config_key(device.device_index, device.vid, device.pid)
        Settings.save_device_setting(active_key, 'resolved_button_image', btn_img)
        Settings.save_device_setting(active_key, 'resolved_product', product)

    # ── Theme Event Handlers ─────────────────────────────────────────

    def _on_local_theme_clicked(self, theme_info: Any) -> None:
        h = self._active_lcd()
        if h:
            h.select_theme_from_path(Path(theme_info.path))
            name = theme_info.name
            if name.startswith('Custom_'):
                name = name[len('Custom_'):]
            self.theme_name_input.setText(name)

    def _on_cloud_theme_clicked(self, theme_info: Any) -> None:
        h = self._active_lcd()
        if h:
            h.select_cloud_theme(theme_info)

    def _on_mask_clicked(self, mask_info: Any) -> None:
        h = self._active_lcd()
        if h:
            h.apply_mask(mask_info)

    def _on_local_delegate(self, cmd: Any, info: Any, data: Any) -> None:
        if cmd == UCThemeLocal.CMD_SLIDESHOW:
            h = self._active_lcd()
            if h:
                h.on_slideshow_delegate()

    def _on_delete_theme(self, theme_info: Any) -> None:
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Delete Theme", f"Delete theme '{theme_info.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.uc_theme_local.delete_theme(theme_info)
            h = self._active_lcd()
            if (h and h.display.current_theme_path
                    and str(h.display.current_theme_path) == theme_info.path):
                h.display.current_image = None
                self.uc_preview.set_image(None)
            self.uc_preview.set_status(f"Deleted: {theme_info.name}")

    # ── Settings Delegates ──────────────────────────────────────────

    def _on_settings_delegate(self, cmd: Any, info: Any, data: Any) -> None:
        h = self._active_lcd()
        if cmd == UCThemeSetting.CMD_BACKGROUND_LOAD_IMAGE:
            self._on_load_image_clicked()
        elif cmd == UCThemeSetting.CMD_BACKGROUND_LOAD_VIDEO:
            self._on_load_video_clicked()
        elif cmd == UCThemeSetting.CMD_MASK_TOGGLE:
            if h:
                h.display.set_overlay_mask_visible(info)
                h._render_and_send()
        elif cmd == UCThemeSetting.CMD_MASK_UPLOAD:
            self._on_mask_upload_clicked()
        elif cmd == UCThemeSetting.CMD_MASK_POSITION:
            if h and info:
                h.update_mask_position(info[0], info[1])
        elif cmd == UCThemeSetting.CMD_MASK_VISIBILITY:
            if h:
                h.display.set_overlay_mask_visible(info)
                h._render_and_send()
        elif cmd == UCThemeSetting.CMD_MASK_LOAD:
            self._show_panel(3)
        elif cmd == UCThemeSetting.CMD_MASK_CLOUD:
            self._show_panel(3)
        elif cmd == UCThemeSetting.CMD_VIDEO_LOAD:
            self._on_media_player_load_clicked()
        elif cmd == 51:
            self._show_panel(1)
        elif cmd == UCThemeSetting.CMD_VIDEO_TOGGLE:
            self._on_video_display_toggle(info)
        elif cmd == UCThemeSetting.CMD_OVERLAY_CHANGED:
            if h:
                h.on_overlay_changed(info if isinstance(info, dict) else {})

    def _on_preview_delegate(self, cmd: Any, info: Any, data: Any) -> None:
        h = self._active_lcd()
        if not h:
            return
        if cmd == UCPreview.CMD_VIDEO_PLAY_PAUSE:
            h.play_pause()
        elif cmd == UCPreview.CMD_VIDEO_SEEK:
            h.seek(info)
        elif cmd == UCPreview.CMD_VIDEO_FIT_WIDTH:
            h.set_video_fit_mode('width')
        elif cmd == UCPreview.CMD_VIDEO_FIT_HEIGHT:
            h.set_video_fit_mode('height')

    # ── Background / Screencast / Video Toggles ─────────────────────

    def _on_background_toggle(self, enabled: bool) -> None:
        h = self._active_lcd()
        if not h:
            return
        if enabled:
            self._screencast.toggle(False)
        h.on_background_toggle(enabled)

    def _on_screencast_toggle(self, enabled: bool) -> None:
        h = self._active_lcd()
        if not h:
            return
        if enabled:
            h.stop_timers()
            h.display.stop_video()
            h.is_background_active = False
            w, hw = h.display.lcd_size
            self._screencast.set_lcd_size(w, hw)
        self._screencast.toggle(enabled)
        self.uc_preview.set_status(f"Screencast: {'On' if enabled else 'Off'}")

    def _on_video_display_toggle(self, enabled: bool) -> None:
        h = self._active_lcd()
        if not h:
            return
        if not enabled:
            if h.display.video_has_frames():
                h._animation_timer.stop()
                h.display.stop_video()
                self.uc_preview.set_playing(False)
                self.uc_preview.show_video_controls(False)
            last_path = h.display.current_theme_path
            if last_path:
                h.select_theme_from_path(Path(last_path))

    def _on_screencast_frame(self, image: Any) -> None:
        h = self._active_lcd()
        if h:
            h.on_screencast_frame(image)

    # ── File Dialogs ────────────────────────────────────────────────

    def _on_load_video_clicked(self) -> None:
        web_dir = str(_conf.settings.web_dir) if _conf.settings.web_dir else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", web_dir,
            "Video Files (*.mp4 *.avi *.mov *.gif);;All Files (*)")
        h = self._active_lcd()
        if path and h:
            w, hw = h.display.lcd_size
            self.uc_video_cut.set_resolution(w, hw)
            self.uc_video_cut.load_video(path)
            self._show_cutter('video')

    def _on_media_player_load_clicked(self) -> None:
        web_dir = str(_conf.settings.web_dir) if _conf.settings.web_dir else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", web_dir,
            "Video Files (*.mp4 *.avi *.mkv *.mov *.gif);;All Files (*)")
        h = self._active_lcd()
        if not path or not h:
            return
        self._screencast.toggle(False)
        h.is_background_active = False
        h._animation_timer.stop()
        h.display.stop_video()
        h.display.enable(False)
        result = h.display.load_video(path)
        if not result.get("success"):
            self.uc_preview.set_status(f"Error: {result.get('error', 'Failed to load video')}")
            return
        h.display.play_video()
        h._animation_timer.start(h.display.interval)
        self.uc_preview.set_playing(True)
        self.uc_preview.show_video_controls(True)
        self.uc_preview.set_status(f"Playing: {Path(path).name}")

    def _on_load_image_clicked(self) -> None:
        self._cut_mode = 'background'
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)")
        h = self._active_lcd()
        if path and h:
            from PySide6.QtGui import QImage as _QImage
            img = _QImage(path)
            if img.isNull():
                self.uc_preview.set_status("Error: could not load image")
            else:
                w, hw = h.display.lcd_size
                self.uc_image_cut.load_image(img, w, hw)
                self._show_cutter('image')

    def _on_mask_upload_clicked(self) -> None:
        self._cut_mode = 'mask'
        path, _ = QFileDialog.getOpenFileName(
            self, "Upload Mask Image", "",
            "PNG Images (*.png);;All Files (*)")
        h = self._active_lcd()
        if path and h:
            from PySide6.QtGui import QImage as _QImage
            img = _QImage(path)
            if img.isNull():
                self.uc_preview.set_status("Error: could not load image")
                self._cut_mode = 'background'
            else:
                self._mask_upload_filename = Path(path).stem
                w, hw = h.display.lcd_size
                self.uc_image_cut.load_image(img, w, hw)
                self._show_cutter('image')

    def _on_save_clicked(self) -> None:
        name = self.theme_name_input.text().strip()
        if not name:
            self.uc_preview.set_status("Enter a theme name first")
            return
        h = self._active_lcd()
        if h:
            h.save_theme(name)

    def _on_export_clicked(self) -> None:
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Theme", "",
            "Theme files (*.tr);;JSON (*.json);;All Files (*)")
        h = self._active_lcd()
        if path and h:
            h.export_config(Path(path))

    def _on_import_clicked(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Theme", "",
            "Theme files (*.tr);;JSON (*.json);;All Files (*)")
        h = self._active_lcd()
        if path and h:
            h.import_config(Path(path))

    # ── Image/Video Cutters ─────────────────────────────────────────

    def _show_cutter(self, kind: str) -> None:
        self.uc_preview.setVisible(False)
        self.uc_image_cut.setVisible(kind == 'image')
        self.uc_video_cut.setVisible(kind == 'video')
        (self.uc_image_cut if kind == 'image' else self.uc_video_cut).raise_()

    def _hide_cutters(self) -> None:
        self.uc_image_cut.setVisible(False)
        self.uc_video_cut.setVisible(False)
        self.uc_preview.setVisible(True)

    def _on_image_cut_done(self, result: Any) -> None:
        self._hide_cutters()
        h = self._active_lcd()
        if result is None or not h:
            self.uc_preview.set_status("Image crop cancelled")
            self._cut_mode = 'background'
            return
        if self._cut_mode == 'mask':
            self._save_and_apply_custom_mask(result)
        else:
            h.stop_video()
            h.display.set_overlay_background(result)
            h._render_and_send()
            self.uc_preview.set_status("Image loaded")
        self._cut_mode = 'background'

    def _save_and_apply_custom_mask(self, cropped: Any) -> None:
        import re

        from PySide6.QtGui import QImage as _QImage
        from PySide6.QtGui import QPainter as _QPainter

        from ..core.models import MaskItem
        h = self._active_lcd()
        if not h:
            return
        if not isinstance(cropped, _QImage) or cropped.isNull():
            return
        w, hw = h.display.lcd_size
        user_dir = Path(_conf.settings._path_resolver.user_masks_dir(w, hw))
        user_dir.mkdir(parents=True, exist_ok=True)

        raw_name = self._mask_upload_filename or 'custom_001'
        mask_name = re.sub(r'[^\w\-]', '_', raw_name).strip('_') or 'custom'
        base_name = mask_name
        counter = 1
        while (user_dir / mask_name).exists():
            counter += 1
            mask_name = f"{base_name}_{counter}"

        mask_dir = user_dir / mask_name
        mask_dir.mkdir(parents=True, exist_ok=True)

        from PySide6.QtCore import Qt as _Qt
        img = cropped.convertToFormat(_QImage.Format.Format_ARGB32)
        if img.width() != w or img.height() != hw:
            img = img.scaled(w, hw, _Qt.AspectRatioMode.IgnoreAspectRatio,
                             _Qt.TransformationMode.SmoothTransformation)
        img.save(str(mask_dir / '01.png'))

        thumb_size = 120
        scale = min(thumb_size / max(img.width(), 1), thumb_size / max(img.height(), 1))
        tw = int(img.width() * scale)
        th = int(img.height() * scale)
        thumb = img.scaled(tw, th, _Qt.AspectRatioMode.IgnoreAspectRatio,
                           _Qt.TransformationMode.SmoothTransformation)
        bg = _QImage(thumb_size, thumb_size, _QImage.Format.Format_RGB32)
        bg.fill(0)
        painter = _QPainter(bg)
        painter.drawImage((thumb_size - tw) // 2, (thumb_size - th) // 2, thumb)
        painter.end()
        bg.save(str(mask_dir / 'Theme.png'))
        log.info("Imported custom mask: %s", mask_name)

        new_item = MaskItem(
            name=mask_name, path=str(mask_dir),
            preview=str(mask_dir / 'Theme.png'),
            is_local=True, is_custom=True)
        h.apply_mask(new_item)
        if hasattr(self, 'uc_theme_mask'):
            self.uc_theme_mask.refresh_masks()
        self.uc_preview.set_status(f"Custom mask '{mask_name}' uploaded")

    def _on_video_cut_done(self, zt_path: Any) -> None:
        self._hide_cutters()
        h = self._active_lcd()
        if zt_path and h:
            h.display.load_video(Path(zt_path))
            h.display.play_video()
            h._animation_timer.start(h.display.video.interval)
            self.uc_preview.set_playing(True)
            self.uc_preview.show_video_controls(True)
            self.uc_preview.set_status("Video loaded")
        else:
            self.uc_preview.set_status("Video cut cancelled")

    # ── Activity Sidebar / Overlay ───────────────────────────────────

    def _on_overlay_add_requested(self) -> None:
        self.uc_activity_sidebar.setVisible(True)
        self.uc_activity_sidebar.raise_()

    def _on_sensor_element_add(self, config: Any) -> None:
        self.uc_theme_setting.overlay_grid.add_element(config)
        self.uc_activity_sidebar.setVisible(False)

    def _on_overlay_toggle(self, enabled: bool) -> None:
        h = self._active_lcd()
        if h:
            h.display.enable_overlay(enabled)

        active_key = Settings.device_config_key(
            *self._active_device_index_vid_pid())
        if active_key:
            cfg = Settings.get_device_config(active_key)
            overlay = cfg.get('overlay', {})
            overlay['enabled'] = enabled
            Settings.save_device_setting(active_key, 'overlay', overlay)

    def _active_device_index_vid_pid(self) -> tuple[int, int, int]:
        h = self._active_lcd()
        if h and h.display and h.display.device_info:
            info = h.display.device_info
            return info.device_index, info.vid, info.pid
        return 0, 0, 0

    def _on_element_flash(self, index: int, config: dict) -> None:
        h = self._active_lcd()
        if h:
            h.flash_element(index)

    # ── Drag / Nudge ────────────────────────────────────────────────

    def _on_drag_start(self, lcd_x: int, lcd_y: int) -> None:
        grid = self.uc_theme_setting.overlay_grid
        cfg = grid.get_selected_config()
        if cfg is None:
            idx = grid.find_nearest_element(lcd_x, lcd_y)
            if idx < 0:
                return
            grid.select_element(idx)
            cfg = grid.get_selected_config()
            if cfg is None:
                return
        self._drag_origin_x = lcd_x
        self._drag_origin_y = lcd_y
        self._drag_elem_x = cfg.x
        self._drag_elem_y = cfg.y

    def _on_drag_move(self, lcd_x: int, lcd_y: int) -> None:
        cfg = self.uc_theme_setting.overlay_grid.get_selected_config()
        h = self._active_lcd()
        if cfg is None or not h:
            return
        w, hw = h.display.lcd_size
        new_x = max(0, min(self._drag_elem_x + (lcd_x - self._drag_origin_x), w))
        new_y = max(0, min(self._drag_elem_y + (lcd_y - self._drag_origin_y), hw))
        self.uc_theme_setting.color_panel.set_position(new_x, new_y)
        self.uc_theme_setting._on_position_changed(new_x, new_y)

    def _on_nudge(self, dx: int, dy: int) -> None:
        cfg = self.uc_theme_setting.overlay_grid.get_selected_config()
        h = self._active_lcd()
        if cfg is None or not h:
            return
        w, hw = h.display.lcd_size
        new_x = max(0, min(cfg.x + dx, w))
        new_y = max(0, min(cfg.y + dy, hw))
        self.uc_theme_setting.color_panel.set_position(new_x, new_y)
        self.uc_theme_setting._on_position_changed(new_x, new_y)

    # ── Display Settings ────────────────────────────────────────────

    def _on_rotation_change(self, index: int) -> None:
        h = self._active_lcd()
        if h:
            h.set_rotation(index * 90)
            self.uc_preview.set_status(f"Rotation: {index * 90}°")

    def _on_ldd_click(self) -> None:
        h = self._active_lcd()
        if not h:
            return
        if h.ldd_is_split:
            mode = (h.split_mode % 3) + 1
            h.set_split_mode(mode)
            self._update_ldd_icon()
            self.uc_preview.set_status(f"Split mode: {mode}")
        else:
            level = (h.brightness_level % 3) + 1
            h.set_brightness(level)
            self._update_ldd_icon()
            from ..core.models import BRIGHTNESS_LEVELS
            self.uc_preview.set_status(f"Brightness: L{level} ({BRIGHTNESS_LEVELS[level]}%)")

    def _update_ldd_icon(self) -> None:
        h = self._active_lcd()
        if not h:
            return
        level = h.split_mode if h.ldd_is_split else h.brightness_level
        pix = self._ldd_pixmaps.get(level)
        if pix and not pix.isNull():
            self.ldd_btn.setIcon(QIcon(pix))
            self.ldd_btn.setIconSize(QSize(52, 24))
            self.ldd_btn.setStyleSheet(Styles.ICON_BUTTON_HOVER)
        else:
            label = f"S{level}" if h.ldd_is_split else f"L{level}"
            self.ldd_btn.setText(label)
            self.ldd_btn.setStyleSheet(Styles.TEXT_BUTTON)

    # ── Global Settings ─────────────────────────────────────────────

    def _on_temp_unit_changed(self, unit: str) -> None:
        temp_int = 1 if unit == 'F' else 0
        h = self._active_lcd()
        if h:
            h.display.set_overlay_temp_unit(temp_int)
        self.uc_system_info.set_temp_unit(temp_int)
        self.uc_led_control.set_temp_unit(temp_int)
        for led_h in self._led_handlers.values():
            led_h.set_temp_unit(unit)
        _conf.settings.set_temp_unit(temp_int)
        self.uc_preview.set_status(f"Temperature: °{unit}")

    def _on_hdd_toggle_changed(self, on: bool) -> None:
        _conf.settings.set_hdd_enabled(on)
        self.uc_preview.set_status(f"HDD info: {'Enabled' if on else 'Disabled'}")

    def _on_refresh_changed(self, interval: int) -> None:
        _conf.settings.set_refresh_interval(interval)
        self.uc_preview.set_status(f"Refresh: {interval}s")

    def _set_language(self, lang: str) -> None:
        _conf.settings.lang = lang
        self._apply_settings_backgrounds()
        self.uc_about.sync_language()
        self.uc_led_control.apply_localized_background()

    def _on_help_clicked(self) -> None:
        import webbrowser
        webbrowser.open(
            'https://github.com/Lexonight1/thermalright-trcc-linux'
            '/blob/main/doc/TROUBLESHOOTING.md')

    def _on_capture_requested(self) -> None:
        from .screen_capture import ScreenCaptureOverlay
        self._capture_overlay = ScreenCaptureOverlay()
        self._capture_overlay.captured.connect(self._on_screen_captured)
        self._capture_overlay.show()

    def _on_screen_captured(self, pixmap: Any) -> None:
        self._capture_overlay = None
        h = self._active_lcd()
        if pixmap is None or not h:
            return
        from PySide6.QtGui import QPixmap as _QPixmap
        img = pixmap.toImage() if isinstance(pixmap, _QPixmap) else pixmap
        if img.isNull():
            return
        w, hw = h.display.lcd_size
        self.uc_image_cut.load_image(img, w, hw)
        self._show_cutter('image')

    def _on_eyedropper_requested(self) -> None:
        from .eyedropper import EyedropperOverlay
        self._eyedropper_overlay = EyedropperOverlay()
        self._eyedropper_overlay.color_picked.connect(self._eyedropper_pick)
        self._eyedropper_overlay.cancelled.connect(
            lambda: setattr(self, '_eyedropper_overlay', None))
        self._eyedropper_overlay.show()

    def _eyedropper_pick(self, r: int, g: int, b: int) -> None:
        self._eyedropper_overlay = None
        self.uc_theme_setting.color_panel._apply_color(r, g, b)

    # ── Carousel Config ─────────────────────────────────────────────

    def _load_carousel_config(self, theme_dir: Path) -> None:
        config = read_carousel_config(str(theme_dir / 'Theme.dc'))
        if config is None:
            return
        all_themes = self.uc_theme_local._all_themes
        slideshow_names = [
            all_themes[idx].name
            for idx in config.theme_indices
            if 0 <= idx < len(all_themes)
        ]
        self.uc_theme_local._lunbo_array = slideshow_names
        self.uc_theme_local._slideshow = config.enabled
        self.uc_theme_local._slideshow_interval = config.interval_seconds
        self.uc_theme_local.timer_input.setText(str(config.interval_seconds))
        px = (self.uc_theme_local._lunbo_on if config.enabled
              else self.uc_theme_local._lunbo_off)
        if not px.isNull():
            self.uc_theme_local.slideshow_btn.setIcon(QIcon(px))
            self.uc_theme_local.slideshow_btn.setIconSize(
                self.uc_theme_local.slideshow_btn.size())
        self.uc_theme_local._apply_decorations()

    # ── Window Events ───────────────────────────────────────────────

    def showEvent(self, event: Any) -> None:
        super().showEvent(event)
        # Safety: restart LED tick timers if stopped while hidden
        for led_h in self._led_handlers.values():
            if led_h.active and not led_h._timer.isActive():
                log.warning("LED tick timer was stopped while hidden — restarting")
                led_h._timer.start(150)

    def mousePressEvent(self, event: Any) -> None:
        if self._decorated or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        if pos.y() < 80 or (pos.x() < 180 and pos.y() < 95):
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft())
        event.accept()

    def mouseMoveEvent(self, event: Any) -> None:
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        event.accept()

    def mouseReleaseEvent(self, event: Any) -> None:
        self._drag_pos = None
        event.accept()

    def closeEvent(self, event: Any) -> None:
        if (not self._force_quit
                and self._tray.isSystemTrayAvailable()
                and self._tray.isVisible()
                and not (self._minimize_on_close and self._minimized_to_taskbar)):
            event.ignore()
            if self._minimize_on_close:
                self._minimized_to_taskbar = True
                self.showMinimized()
            else:
                self.hide()
            return
        self._minimized_to_taskbar = False

        self._tray.hide()
        self._screencast.cleanup()
        for h in list(self._led_handlers.values()):
            h.cleanup()
        for h in list(self._lcd_handlers.values()):
            h.cleanup()
        self.uc_system_info.stop_updates()
        self.uc_info_module.stop_updates()
        self.uc_activity_sidebar.stop_updates()
        if self._ipc_server:
            self._ipc_server.shutdown()
        from ..adapters.device.factory import DeviceProtocolFactory
        DeviceProtocolFactory.close_all()
        TRCCApp._instance = None
        event.accept()
        app = QApplication.instance()
        if app:
            app.quit()
