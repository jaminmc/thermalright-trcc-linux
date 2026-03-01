"""
PyQt6 Main Application Window using MVC Architecture.

This is a View that uses LCDDeviceController for all business logic.
The controller can be reused with any GUI framework (Tkinter, GTK, etc.)

Visual polish matches Windows TRCC exactly:
- QPalette backgrounds (not stylesheets) for image backgrounds
- Localized backgrounds based on system language
- Windows asset images for buttons, tabs, panels
- Exact coordinate positioning matching Windows InitializeComponent()
"""
from __future__ import annotations

import logging
import os
import sys
from pathlib import Path

from PySide6.QtCore import QRegularExpression as QRE
from PySide6.QtCore import QSize, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIcon, QPalette, QRegularExpressionValidator
from PySide6.QtWidgets import (
    QApplication,
    QComboBox,
    QFileDialog,
    QLineEdit,
    QMainWindow,
    QMenu,
    QPushButton,
    QStackedWidget,
    QSystemTrayIcon,
    QWidget,
)

from ..adapters.device.scsi import find_lcd_devices
from ..adapters.infra.dc_writer import CarouselConfig, read_carousel_config, write_carousel_config
from ..adapters.system.sensors import SensorEnumerator
from ..conf import Settings, settings

# Import MVC core
from ..core.controllers import LEDDeviceController, create_controller
from ..core.models import SPLIT_MODE_RESOLUTIONS, DeviceInfo, PlaybackState, ThemeInfo
from ..services.system import get_all_metrics

# Import view components
from .assets import Assets
from .base import create_image_button, set_background_pixmap
from .constants import Colors, Layout, Sizes, Styles
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

log = logging.getLogger(__name__)


# =============================================================================
# LED Handler — Mediator between UCLedControl panel and LEDDeviceController
# =============================================================================

class LEDHandler:
    """Mediator for LED device control.

    Owns the LEDDeviceController lifecycle, animation timer, sensor polling,
    and signal wiring. Extracted from TRCCMainWindowMVC to reduce God Object.
    """

    def __init__(self, panel: UCLedControl, on_temp_unit_changed):
        self._panel = panel
        self._on_temp_unit_changed = on_temp_unit_changed
        self._controller: LEDDeviceController | None = None
        self._active = False
        self._style_id = 0
        self._sensor_counter = 0

        # Timers (owned by handler, parented to panel for Qt lifecycle)
        self._timer = QTimer(panel)
        self._timer.timeout.connect(self._on_tick)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def has_controller(self) -> bool:
        return self._controller is not None

    def show(self, device: DeviceInfo):
        """Initialize LED controller for device and start animation."""
        if self._controller is None:
            self._controller = LEDDeviceController()
            self._connect_signals()

        from ..services.led import LEDService
        model = device.model or ''
        led_style = device.led_style_id or LEDService.resolve_style_id(model)

        self._controller.initialize(device, led_style)
        self._style_id = led_style
        self._sensor_counter = 0

        style_info = LEDService.get_style_info(led_style)
        if style_info:
            self._panel.initialize(
                led_style, style_info.segment_count, style_info.zone_count,
                model=model,
            )
        self._panel.set_memory_ratio(self._controller.state.memory_ratio)
        self._sync_ui_from_state()

        seg_unit = "F" if settings.temp_unit == 1 else "C"
        self._controller.set_seg_temp_unit(seg_unit)

        self._active = True
        self._timer.start(150)

    def stop(self):
        """Stop LED mode — save config, stop timers, release protocol."""
        self._timer.stop()
        self._active = False
        if self._controller:
            self._controller.cleanup()

    def cleanup(self):
        """Full cleanup for application shutdown."""
        self._timer.stop()
        if self._controller:
            self._controller.cleanup()

    def set_temp_unit(self, unit: str):
        """Forward temperature unit change to segment display."""
        if self._controller:
            self._controller.set_seg_temp_unit(unit)

    def _sync_ui_from_state(self):
        """Sync panel controls to loaded LED state after initialization.

        load_config() populates the service state from config.json, but
        panel.initialize() creates controls with defaults.  This pushes
        the loaded state into the UI so controls reflect the saved config.
        """
        if not self._controller:
            return
        state = self._controller.state

        # For zone devices, sync zone 0 (default selected zone after init)
        if state.zones:
            z = state.zones[0]
            self._panel.load_zone_state(
                0, z.mode.value, z.color, z.brightness, z.on)
        else:
            # Single-zone: sync global state
            self._panel.load_zone_state(
                0, state.mode.value, state.color, state.brightness,
                state.global_on)

    # ── Signal wiring ────────────────────────────────────────────────

    def _connect_signals(self):
        """Wire UCLedControl signals to LEDDeviceController."""
        if not self._controller:
            return

        ctrl = self._controller
        panel = self._panel

        panel.mode_changed.connect(self._on_mode_changed)
        panel.color_changed.connect(self._on_color_changed)
        panel.brightness_changed.connect(self._on_brightness_changed)
        panel.global_toggled.connect(
            lambda on: ctrl.toggle_global(on))
        panel.segment_clicked.connect(
            lambda idx: ctrl.toggle_segment(idx, not ctrl.state.segment_on[idx]))

        panel.zone_selected.connect(self._on_zone_selected)
        panel.zone_toggled.connect(
            lambda zi, on: ctrl.toggle_zone(zi, on))
        panel.carousel_changed.connect(
            lambda on: ctrl.set_zone_sync(on))
        panel.carousel_zone_changed.connect(
            lambda zi, sel: ctrl.set_zone_sync_zone(zi, sel))
        panel.carousel_interval_changed.connect(
            lambda secs: ctrl.set_zone_sync_interval(secs))

        panel.clock_format_changed.connect(
            lambda is_24h: ctrl.set_clock_format(is_24h))
        panel.week_start_changed.connect(
            lambda is_sun: ctrl.set_week_start(is_sun))

        panel.temp_unit_changed.connect(self._on_temp_unit_changed)
        panel.disk_index_changed.connect(
            lambda idx: ctrl.set_disk_index(idx))
        panel.memory_ratio_changed.connect(
            lambda ratio: ctrl.set_memory_ratio(ratio))
        panel.test_mode_changed.connect(
            lambda on: ctrl.set_test_mode(on))

        ctrl.on_preview_update = self._on_colors_update
        ctrl.on_status_update = lambda text: panel.set_status(text)

    # ── Zone-aware routing ───────────────────────────────────────────

    def _on_mode_changed(self, mode):
        ctrl = self._controller
        if not ctrl:
            return
        # C# always sets global myLedMode, AND per-zone for zone styles.
        ctrl.set_mode(mode)
        if ctrl.state.zones:
            ctrl.set_zone_mode(self._panel.selected_zone, mode)

    def _on_color_changed(self, r, g, b):
        ctrl = self._controller
        if not ctrl:
            return
        # C# always sets global rgbR1/G1/B1, AND per-zone for zone styles.
        ctrl.set_color(r, g, b)
        if ctrl.state.zones:
            ctrl.set_zone_color(self._panel.selected_zone, r, g, b)

    def _on_brightness_changed(self, val):
        ctrl = self._controller
        if not ctrl:
            return
        # C# always sets global myBrightness, AND per-zone for zone styles.
        ctrl.set_brightness(val)
        if ctrl.state.zones:
            ctrl.set_zone_brightness(self._panel.selected_zone, val)

    def _on_zone_selected(self, zone_index):
        ctrl = self._controller
        if not ctrl or not ctrl.state.zones:
            return
        ctrl.set_selected_zone(zone_index)
        zones = ctrl.state.zones
        if 0 <= zone_index < len(zones):
            z = zones[zone_index]
            self._panel.load_zone_state(
                zone_index, z.mode.value, z.color, z.brightness, z.on)

    # ── Animation tick + sensor polling ──────────────────────────────

    def _on_tick(self):
        if not (self._controller and self._active):
            return
        self._controller.tick()

        self._sensor_counter += 1
        if self._sensor_counter >= 7:
            self._sensor_counter = 0
            self._poll_sensors()

    def _poll_sensors(self):
        if not self._controller:
            return
        try:
            metrics = get_all_metrics()
        except Exception:
            return
        self._controller.update_metrics(metrics)
        self._panel.update_metrics(metrics)

    # ── LED colors ──────────────────────────────────────────────────

    def _on_colors_update(self, colors):
        self._panel.set_led_colors(colors)


# =============================================================================
# Screencast Handler — owns PipeWire capture, region coords, render loop
# =============================================================================

class ScreencastHandler:
    """Mediator for screencast (screen capture → LCD) functionality.

    Owns the capture timer, PipeWire session, and region coordinates.
    Extracted from TRCCMainWindowMVC to reduce God Object.
    """

    def __init__(self, parent: QWidget, controller, on_frame):
        self._controller = controller
        self._on_frame = on_frame  # callback(pil_img) for preview + send
        self._active = False
        self._x = 0
        self._y = 0
        self._w = 0
        self._h = 0
        self._border = True  # Windows myYcbk
        self._pipewire_cast = None

        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._active

    @active.setter
    def active(self, value: bool):
        self._active = value

    @property
    def border(self) -> bool:
        return self._border

    def toggle(self, enabled: bool):
        """Start or stop screencast mode."""
        self._active = enabled
        if enabled:
            from .screen_capture import is_wayland
            if is_wayland() and self._pipewire_cast is None:
                self._try_start_pipewire()
            self._timer.start(150)  # ~6.67 FPS
        else:
            self._timer.stop()
            self._stop_pipewire()

    def stop(self):
        """Force-stop screencast (called when switching modes)."""
        self._timer.stop()
        self._active = False

    def set_params(self, x: int, y: int, w: int, h: int):
        self._x = x
        self._y = y
        self._w = w
        self._h = h

    def set_border(self, visible: bool):
        self._border = visible

    def cleanup(self):
        """Full cleanup for application shutdown."""
        self._timer.stop()
        self._stop_pipewire()

    def _try_start_pipewire(self):
        """Attempt to start PipeWire portal capture (non-blocking)."""
        from .pipewire_capture import PIPEWIRE_AVAILABLE, PipeWireScreenCast
        if not PIPEWIRE_AVAILABLE:
            return

        import threading
        cast = PipeWireScreenCast()
        self._pipewire_cast = cast

        def _start():
            if not cast.start(timeout=30):
                self._pipewire_cast = None

        threading.Thread(target=_start, daemon=True).start()

    def _stop_pipewire(self):
        if self._pipewire_cast is not None:
            self._pipewire_cast.stop()
            self._pipewire_cast = None

    def _tick(self):
        """Capture screen, scale to LCD, composite overlay, deliver via callback."""
        if not self._active or self._w <= 0 or self._h <= 0:
            return

        from PIL import Image as PILImage

        pil_img = None

        # Try PipeWire first (Wayland GNOME/KDE)
        if self._pipewire_cast is not None and self._pipewire_cast.is_running:
            frame = self._pipewire_cast.grab_frame()
            if frame is not None:
                fw, fh, rgb_bytes = frame
                full = PILImage.frombytes('RGB', (fw, fh), rgb_bytes)
                x2 = min(self._x + self._w, fw)
                y2 = min(self._y + self._h, fh)
                x1 = min(self._x, fw)
                y1 = min(self._y, fh)
                if x2 > x1 and y2 > y1:
                    pil_img = full.crop((x1, y1, x2, y2))

        # Fallback: X11 / grim direct capture
        if pil_img is None:
            from .base import pixmap_to_pil
            from .screen_capture import grab_screen_region

            pixmap = grab_screen_region(self._x, self._y, self._w, self._h)
            if pixmap.isNull():
                return
            pil_img = pixmap_to_pil(pixmap)

        ctrl = self._controller
        lcd_w, lcd_h = ctrl.lcd_width, ctrl.lcd_height
        pil_img = pil_img.resize((lcd_w, lcd_h), PILImage.Resampling.LANCZOS)

        if ctrl.is_overlay_enabled():
            pil_img = ctrl.render_overlay(pil_img)

        self._on_frame(pil_img)


class TRCCMainWindowMVC(QMainWindow):
    """
    Main TRCC application window (singleton).

    This View:
    - Owns the LCDDeviceController for business logic
    - Renders UI with Windows-matching backgrounds via QPalette
    - Forwards user events to controller
    - Subscribes to controller callbacks for updates
    """

    # Signal emitted from background handshake thread → main thread
    _handshake_done = Signal(object, object)  # (DeviceInfo, resolution tuple or None)

    _instance: 'TRCCMainWindowMVC | None' = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is not None:
            raise RuntimeError("TRCCMainWindowMVC is a singleton — use instance()")
        inst = super().__new__(cls)
        cls._instance = inst
        return inst

    @classmethod
    def instance(cls) -> 'TRCCMainWindowMVC | None':
        """Return the existing window instance, or None."""
        return cls._instance

    def __init__(self, data_dir: Path | None = None, decorated: bool = False):
        super().__init__()

        self._decorated = decorated
        self._drag_pos = None
        self._force_quit = False

        self.setWindowTitle("TRCC Linux - Thermalright LCD Control Center")
        self.setFixedSize(Sizes.WINDOW_W, Sizes.WINDOW_H)

        if not decorated:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window
            )

        # Create controller (business logic lives here)
        self._data_dir = data_dir or Path(__file__).parent.parent / 'data'
        self.controller = create_controller(self._data_dir)

        # Timers (view owns timers, controller owns logic)
        def _video_tick_wrapper():
            self.controller.video_tick()
        self._animation_timer = self._make_timer(_video_tick_wrapper)
        self._metrics_timer = self._make_timer(self._on_metrics_tick)
        self._device_timer = self._make_timer(self._on_device_poll)
        self._flash_timer = self._make_timer(self._on_flash_timeout, single_shot=True)
        self._slideshow_timer = self._make_timer(self._on_slideshow_tick)
        # Handshake result signal (background thread → main thread)
        self._handshake_done.connect(self._on_handshake_done)

        self._background_active = False  # C# myBjxs — background display mode

        # Slideshow state
        self._slideshow_index = 0

        # Per-device config tracking
        self._active_device_key = ''

        # Pixmap references to prevent GC
        self._pixmap_refs = []

        # Setup UI
        self._apply_dark_theme()
        self._setup_ui()
        self._led = LEDHandler(self.uc_led_control, self._on_temp_unit_changed)
        self._screencast = ScreencastHandler(self, self.controller, self._on_screencast_frame)
        self._connect_controller_callbacks()
        self._connect_view_signals()

        # Restore saved temperature unit preference
        saved_unit = settings.temp_unit
        self.controller.set_overlay_temp_unit(saved_unit)
        self.uc_system_info.set_temp_unit(saved_unit)
        self.uc_led_control.set_temp_unit(saved_unit)
        if saved_unit == 1:
            self.uc_about._set_temp('F')

        # Auto-enable autostart on first launch (matches Windows KaijiQidong)
        autostart_state = ensure_autostart()
        self.uc_about._autostart = autostart_state
        self.uc_about.startup_btn.setChecked(autostart_state)

        # System tray icon
        self._setup_systray()

        # Suspend/resume handler (C# OnPowerModeChanged → ResetAllDevice)
        self._setup_sleep_monitor()

        # Detect devices immediately, then poll every 5s
        self._on_device_poll()
        self._device_timer.start(5000)

        # Device may have been auto-selected during create_controller() before
        # view callbacks were wired. Re-trigger the view's _on_device_selected
        # directly so _active_device_key gets set and saved theme is restored.
        if not self._active_device_key:
            selected = self.controller.get_selected_device()
            if selected:
                self._on_device_selected(selected)

    def _apply_dark_theme(self):
        """Apply dark theme via QPalette (not stylesheet - blocks palette on children)."""
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(Colors.WINDOW_BG))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(Colors.WINDOW_TEXT))
        palette.setColor(QPalette.ColorRole.Base, QColor(Colors.BASE_BG))
        palette.setColor(QPalette.ColorRole.Text, QColor(Colors.TEXT))
        palette.setColor(QPalette.ColorRole.Button, QColor(Colors.BUTTON_BG))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(Colors.BUTTON_TEXT))
        self.setPalette(palette)

    def _setup_systray(self):
        """Create system tray icon with context menu."""
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

    def _setup_sleep_monitor(self):
        """Listen for system suspend/resume via QDBus (C# OnPowerModeChanged).

        Uses Qt's native QDBusConnection instead of dbus-python + GLib main
        loop.  The old dbus-python approach called DBusGMainLoop() which
        integrates the GLib event loop into the Qt event loop — a well-known
        source of excessive CPU wakeups (~10-15% idle overhead).
        """
        try:
            from PySide6.QtDBus import QDBusConnection  # pyright: ignore[reportMissingImports]
            bus = QDBusConnection.systemBus()
            if not bus.isConnected():
                log.debug("Sleep monitor: QDBus system bus not connected")
                return
            bus.connect(  # pyright: ignore[reportCallIssue]
                'org.freedesktop.login1',           # service
                '/org/freedesktop/login1',           # path
                'org.freedesktop.login1.Manager',    # interface
                'PrepareForSleep',                   # signal
                self._on_sleep_signal,
            )
            log.info("Sleep monitor: QDBus PrepareForSleep listener active")
        except Exception:
            log.debug("Sleep monitor: QDBus not available, skipping")

    def _on_sleep_signal(self, sleeping: bool):
        """Handle suspend (sleeping=True) / resume (sleeping=False)."""
        if sleeping:
            log.info("System suspending — stopping timers")
            self._device_timer.stop()
            self._animation_timer.stop()
            self._metrics_timer.stop()
            self._screencast.stop()
        else:
            log.info("System resuming — invalidating USB handles")
            from ..adapters.device.factory import DeviceProtocolFactory
            DeviceProtocolFactory.close_all()
            self._device_timer.start(5000)
            self._on_device_poll()

    def _on_tray_activated(self, reason):
        """Handle tray icon click — left-click toggles visibility."""
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visibility()

    def _toggle_visibility(self):
        """Toggle window visibility."""
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()
            self.raise_()

    def _quit_app(self):
        """Quit application from tray menu."""
        self._force_quit = True
        self.close()

    def _make_timer(self, callback, *, single_shot: bool = False) -> QTimer:
        """Create a QTimer connected to callback."""
        timer = QTimer(self)
        if single_shot:
            timer.setSingleShot(True)
        timer.timeout.connect(callback)
        return timer

    def _set_panel_background(self, widget: QWidget, asset_name: str):
        """Set background image on a panel via QPalette."""
        pix = set_background_pixmap(widget, asset_name)
        if pix:
            self._pixmap_refs.append(pix)

    def _setup_ui(self):
        """
        Build the main UI layout matching Windows TRCC exactly.

        Windows Layout (Form1 + FormCZTV):
        - Form1: 1454x800
        - UCDevice sidebar: x=0, width=180
        - FormCZTV content: x=180, size=1274x800
          - Preview: (16, 88) size 500x560
          - Mode tabs: y=90
          - Theme panels: (532, 128) size 732x652
          - Bottom controls: y=680
        """
        central = QWidget()
        self.setCentralWidget(central)
        # No stylesheet on central - would override QPalette on children

        # Form1 background: A0无设备.png (sidebar + gold bar + sensor grid)
        # ImageLayout.None in Windows — placed at origin, no scaling
        pix_form1 = set_background_pixmap(central, Assets.FORM1_BG,
            width=Sizes.WINDOW_W, height=Sizes.WINDOW_H,
            fallback_style=f"background-color: {Colors.WINDOW_BG};")
        if pix_form1:
            self._pixmap_refs.append(pix_form1)

        # === Left: Device sidebar (180px) ===
        self.uc_device = UCDevice(central)
        self.uc_device.setGeometry(*Layout.SIDEBAR)

        # === FormCZTV content area (x=180, 1274x800) ===
        self.form_container = QWidget(central)
        self.form_container.setGeometry(*Layout.FORM_CONTAINER)

        # Set FormCZTV background image (localized)
        form_bg_name = Assets.get_localized(Assets.FORM_CZTV_BG, settings.lang)
        pix = set_background_pixmap(self.form_container, form_bg_name,
            fallback_style=f"background-color: {Colors.WINDOW_BG};")
        if pix:
            self._pixmap_refs.append(pix)

        # Preview
        lcd_w, lcd_h = self.controller.lcd_width, self.controller.lcd_height
        self.uc_preview = UCPreview(lcd_w, lcd_h, self.form_container)
        self.uc_preview.setGeometry(*Layout.PREVIEW)

        # Info module (compact sensor bar above preview, hidden by default)
        self.uc_info_module = UCInfoModule(self.form_container)
        self.uc_info_module.setGeometry(16, 16, 500, 70)
        self.uc_info_module.setVisible(False)

        # Image cropper (replaces preview when cropping, hidden by default)
        self.uc_image_cut = UCImageCut(self.form_container)
        self.uc_image_cut.setGeometry(16, 88, 500, 702)
        self.uc_image_cut.setVisible(False)

        # Video trimmer (replaces preview when trimming, hidden by default)
        self.uc_video_cut = UCVideoCut(self.form_container)
        self.uc_video_cut.setGeometry(16, 88, 500, 702)
        self.uc_video_cut.setVisible(False)

        # Mode tab buttons at y=90
        self._create_mode_tabs()

        # Theme panels container
        self.panel_stack = QStackedWidget(self.form_container)
        self.panel_stack.setGeometry(*Layout.PANEL_STACK)
        # No stylesheet on stack - would override QPalette on children

        # Create theme panels with localized backgrounds
        self.uc_theme_local = UCThemeLocal()
        self._set_panel_background(self.uc_theme_local, Assets.get_localized(Assets.THEME_LOCAL_BG, settings.lang))
        self.panel_stack.addWidget(self.uc_theme_local)

        self.uc_theme_web = UCThemeWeb()
        self._set_panel_background(self.uc_theme_web, Assets.get_localized(Assets.THEME_WEB_BG, settings.lang))
        self.panel_stack.addWidget(self.uc_theme_web)

        self.uc_theme_mask = UCThemeMask()
        self._set_panel_background(self.uc_theme_mask, Assets.get_localized(Assets.THEME_MASK_BG, settings.lang))
        self.panel_stack.addWidget(self.uc_theme_mask)

        self.uc_theme_setting = UCThemeSetting()
        self.panel_stack.addWidget(self.uc_theme_setting)

        # Activity sidebar (sensor list for overlay element addition, hidden)
        self.uc_activity_sidebar = UCActivitySidebar(self.form_container)
        self.uc_activity_sidebar.setGeometry(532, 128, 250, 500)
        self.uc_activity_sidebar.setVisible(False)

        # Bottom control buttons at y=680
        self._create_bottom_controls()

        # Title bar buttons (Help, Close)
        self._create_title_buttons()

        # Apply localized display mode backgrounds to settings panel
        self._apply_settings_backgrounds()

        # === About / Control Center panel (sibling of form_container) ===
        self.uc_about = UCAbout(parent=central)
        self.uc_about.setGeometry(*Layout.FORM_CONTAINER)
        self.uc_about.setVisible(False)

        # === Sensor Enumerator (hardware sensor discovery) ===
        self._system_sensors = SensorEnumerator()
        self._system_sensors.discover()

        # === System Info dashboard (sibling of form_container) ===
        self.uc_system_info = UCSystemInfo(self._system_sensors, parent=central)
        self.uc_system_info.setGeometry(*Layout.SYSINFO_PANEL)
        self.uc_system_info.setVisible(False)

        # === LED Control panel (hidden, shown when LED device is selected) ===
        self.uc_led_control = UCLedControl(central)
        self.uc_led_control.setGeometry(*Layout.FORM_CONTAINER)
        self.uc_led_control.setVisible(False)

        # === Form1-level buttons (on central, visible in sensor/home view) ===
        # Windows: buttonPower at (1392, 24), buttonHelp at (1342, 24)
        self.form1_close_btn = create_image_button(
            central, *Layout.FORM1_CLOSE_BTN,
            Assets.BTN_POWER, Assets.BTN_POWER_HOVER, fallback_text="X"
        )
        self.form1_close_btn.setToolTip("Close")
        self.form1_close_btn.clicked.connect(self.close)

        self.form1_help_btn = create_image_button(
            central, *Layout.FORM1_HELP_BTN,
            Assets.BTN_HELP, None, fallback_text="?"
        )
        self.form1_help_btn.setToolTip("Help")
        self.form1_help_btn.clicked.connect(self._on_help_clicked)

        # Initialize theme directories
        self._init_theme_directories()

    def _create_mode_tabs(self):
        """Create mode tab buttons matching Windows positions."""
        self.mode_buttons = []

        # (layout_rect, normal_img, active_img, panel_index, tooltip)
        tab_configs = [
            (Layout.TAB_LOCAL, Assets.TAB_LOCAL, Assets.TAB_LOCAL_ACTIVE, 0, "Local themes"),
            (Layout.TAB_MASK, Assets.TAB_MASK, Assets.TAB_MASK_ACTIVE, 2, "Mask overlays"),
            (Layout.TAB_CLOUD, Assets.TAB_CLOUD, Assets.TAB_CLOUD_ACTIVE, 1, "Cloud themes"),
            (Layout.TAB_SETTINGS, Assets.TAB_SETTINGS, Assets.TAB_SETTINGS_ACTIVE, 3, "Settings"),
        ]

        for rect, normal_img, active_img, panel_idx, tooltip in tab_configs:
            x, y, w, h = rect
            btn = create_image_button(
                self.form_container, x, y, w, h,
                normal_img, active_img, checkable=True
            )
            btn.setToolTip(tooltip)
            btn.clicked.connect(lambda checked, idx=panel_idx: self._show_panel(idx))
            self.mode_buttons.append(btn)

        if self.mode_buttons:
            self.mode_buttons[0].setChecked(True)

    def _show_panel(self, index):
        """Show panel at index and update button states."""
        panel_names = {0: "Local", 1: "Cloud", 2: "Mask", 3: "Settings"}
        log.debug("Tab switched: %s (panel %d)", panel_names.get(index, "?"), index)
        self.panel_stack.setCurrentIndex(index)
        panel_to_button = {0: 0, 1: 2, 2: 1, 3: 3}
        active_btn = panel_to_button.get(index, 0)
        for i, btn in enumerate(self.mode_buttons):
            btn.setChecked(i == active_btn)

    def _show_view(self, view: str):
        """Switch between the four content views.

        Args:
            view: 'form' (device/themes), 'about' (control center),
                  'sysinfo' (dashboard), or 'led' (LED control)

        All panels are siblings on central — only one visible at a time.
        Matches Windows: Form1 hides/shows FormCZTV, UCAbout,
        UCSystemInfoOptions, FormLED as siblings.
        """
        self.form_container.setVisible(view == 'form')
        self.uc_about.setVisible(view == 'about')
        self.uc_system_info.setVisible(view == 'sysinfo')
        self.uc_led_control.setVisible(view == 'led')

        # Form1-level buttons: visible in sensor/home view only
        # Windows: cmd 512 shows buttonPower/Help, cmd 256/240 hides them
        show_form1_btns = (view == 'sysinfo')
        self.form1_close_btn.setVisible(show_form1_btns)
        self.form1_help_btn.setVisible(show_form1_btns)

        if view == 'sysinfo':
            self.uc_system_info.start_updates()
        else:
            self.uc_system_info.stop_updates()

        # Stop LED timer when leaving LED view
        if view != 'led' and self._led.active:
            self._led.stop()

    def _show_about(self):
        """Show the About / Control Center panel."""
        self._show_view('about')

    def _show_system_info(self):
        """Show the System Info dashboard."""
        self._show_view('sysinfo')

    def _show_form(self):
        """Show the main form (device/themes) view."""
        self._show_view('form')
        self.uc_device.restore_device_selection()

    def _on_temp_unit_changed(self, unit: str):
        """Handle temperature unit change from Control Center."""
        temp_int = 1 if unit == 'F' else 0
        self.controller.set_overlay_temp_unit(temp_int)
        self.uc_system_info.set_temp_unit(temp_int)
        self.uc_led_control.set_temp_unit(temp_int)
        self._led.set_temp_unit(unit)
        settings.set_temp_unit(temp_int)
        self.uc_preview.set_status(f"Temperature: °{unit}")

    def _on_hdd_toggle_changed(self, on: bool):
        """Handle HDD info toggle from Control Center — persist and gate disk reads."""
        settings.set_hdd_enabled(on)
        self.uc_preview.set_status(f"HDD info: {'Enabled' if on else 'Disabled'}")

    def _on_refresh_changed(self, interval: int):
        """Handle data refresh interval change from Control Center.

        Updates the metrics timer that drives overlay system info updates.
        Windows: value is 1-100 (seconds).
        """
        ms = interval * 1000
        if self._metrics_timer.isActive():
            self._metrics_timer.setInterval(ms)
        self.uc_preview.set_status(f"Refresh: {interval}s")

    def _on_resolution_changed(self, width: int, height: int):
        """Handle LCD resolution change from settings.

        Updates controller, preview frame, image/video cutters,
        theme directories, and cloud theme URLs.
        """
        self.controller.set_resolution(width, height)

        # Update preview frame for new resolution
        self.uc_preview.set_resolution(width, height)

        # Update image/video cutters
        self.uc_image_cut.set_resolution(width, height)
        self.uc_video_cut.set_resolution(width, height)

        # Update settings panel (screencast aspect ratio)
        self.uc_theme_setting.set_resolution(width, height)

        # Reload theme directories for new resolution (paths auto-resolved in settings)
        td = settings.theme_dir
        if td and td.exists():
            self.uc_theme_local.set_theme_directory(td.path)
            self._load_carousel_config(td.path)

        # Cloud themes — per-resolution Web directory (matches Windows Web/{W}{H}/)
        if settings.web_dir:
            self.uc_theme_web.set_web_directory(settings.web_dir)
        self.uc_theme_web.set_resolution(f'{width}x{height}')

        if settings.masks_dir:
            self.uc_theme_mask.set_mask_directory(settings.masks_dir)
        self.uc_theme_mask.set_resolution(f'{width}x{height}')

        # Configure buttonLDD as split mode or brightness
        self._configure_ldd_for_resolution(width, height)

        self.uc_preview.set_status(f"Resolution: {width}×{height}")

    def _create_bottom_controls(self):
        """Create bottom control bar matching Windows FormCZTV positions.

        Windows layout at y=680:
        - ucComboBoxA1 (rotation): Point(39, 680), Size(108, 24)
        - buttonLDD (brightness): Point(157, 680), Size(52, 24)
        - textBoxCMM (theme name): Point(278, 684), Size(102, 16)
        - buttonBCZT (save): Point(383, 680), Size(24, 24)
        - buttonDaoChu (export): Point(412, 680), Size(40, 24)
        - buttonDaoRu (import): Point(453, 680), Size(40, 24)
        """
        # === Rotation combobox (ucComboBoxA1) ===
        self.rotation_combo = QComboBox(self.form_container)
        self.rotation_combo.setGeometry(*Layout.ROTATION_COMBO)
        self.rotation_combo.addItems(["0°", "90°", "180°", "270°"])
        self.rotation_combo.setStyleSheet(
            "QComboBox { background-color: #2A2A2A; color: white; border: 1px solid #555;"
            " font-size: 10px; padding-left: 5px; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
            "QComboBox QAbstractItemView { background-color: #2A2A2A; color: white;"
            " selection-background-color: #4A6FA5; }"
        )
        self.rotation_combo.setToolTip("LCD rotation")
        self.rotation_combo.currentIndexChanged.connect(self._on_rotation_change)

        # === buttonLDD — dual purpose based on device resolution ===
        # Widescreen 1600x720: split mode button (C# buttonLDD cycles myLddVal 1→2→3)
        # Other resolutions: brightness button (our UX addition, not in C#)
        self._brightness_level = 2  # Default L2 (50%)
        self._split_mode = 0  # myLddVal: 0=off, 1-3 for widescreen split
        self._ldd_is_split = False  # True when button acts as split mode
        self._ldd_pixmaps: dict = {}
        for level in range(4):
            pix = Assets.load_pixmap(f'PL{level}.png')
            if not pix.isNull():
                self._ldd_pixmaps[level] = pix

        self.ldd_btn = QPushButton(self.form_container)
        self.ldd_btn.setGeometry(*Layout.BRIGHTNESS_BTN)
        self.ldd_btn.setToolTip("Cycle brightness (Low / Medium / High)")
        self._update_ldd_icon()
        self.ldd_btn.clicked.connect(self._on_ldd_click)

        # === Theme name input (textBoxCMM) ===
        self.theme_name_input = QLineEdit(self.form_container)
        self.theme_name_input.setGeometry(*Layout.THEME_NAME_INPUT)
        self.theme_name_input.setText("Theme1")
        self.theme_name_input.setMaxLength(10)
        self.theme_name_input.setToolTip("Theme name for saving")
        self.theme_name_input.setAlignment(Qt.AlignmentFlag.AlignRight)
        self.theme_name_input.setStyleSheet(
            "background-color: #232227; color: white; border: none;"
            " font-family: 'Microsoft YaHei'; font-size: 9pt;"
        )
        # Block invalid filename chars (Windows Path.GetInvalidFileNameChars)
        self.theme_name_input.setValidator(
            QRegularExpressionValidator(QRE(r'[^/\\:*?"<>|\x00-\x1f]+')))

        # === Icon buttons (save/export/import) with text fallback ===
        self.save_btn = self._create_icon_or_text_btn(
            *Layout.SAVE_BTN, Assets.BTN_SAVE, "S")
        self.save_btn.setToolTip("Save theme")
        self.save_btn.clicked.connect(self._on_save_clicked)

        self.export_btn = self._create_icon_or_text_btn(
            *Layout.EXPORT_BTN, Assets.BTN_EXPORT, "Exp")
        self.export_btn.setToolTip("Export theme to file")
        self.export_btn.clicked.connect(self._on_export_clicked)

        self.import_btn = self._create_icon_or_text_btn(
            *Layout.IMPORT_BTN, Assets.BTN_IMPORT, "Imp")
        self.import_btn.setToolTip("Import theme from file")
        self.import_btn.clicked.connect(self._on_import_clicked)

    def _create_icon_or_text_btn(self, x, y, w, h, icon_name, fallback_text):
        """Create a button that shows an icon if available, or text fallback."""
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

    def _create_title_buttons(self):
        """Create title bar buttons (Help, Power/Close)."""
        # Help button — Windows opens LCDHelp.pdf; we open the install guide
        help_btn = create_image_button(
            self.form_container, *Layout.HELP_BTN,
            Assets.BTN_HELP, None, fallback_text="?"
        )
        help_btn.setToolTip("Help")
        help_btn.clicked.connect(self._on_help_clicked)

        # Close/Power button
        close_btn = create_image_button(
            self.form_container, *Layout.CLOSE_BTN,
            Assets.BTN_POWER, Assets.BTN_POWER_HOVER, fallback_text="X"
        )
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.close)

    def _on_help_clicked(self):
        """Open troubleshooting guide on GitHub."""
        import webbrowser
        webbrowser.open('https://github.com/Lexonight1/thermalright-trcc-linux/blob/main/doc/TROUBLESHOOTING.md')

    def _apply_settings_backgrounds(self):
        """Apply localized P01 backgrounds to display mode panels in UCThemeSetting.

        Windows pattern: FormCZTV.set_panel_images() sets backgrounds on
        UCThemeSetting sub-panels based on language.
        """
        setting = self.uc_theme_setting

        # Mask/Layout panel at (10, 441) - P01布局蒙板{lang}.png
        mask_bg = Assets.get_localized('P01布局蒙板.png', settings.lang)
        self._set_panel_background(setting.mask_panel, mask_bg)

        # Background panel at (371, 441) - P01背景显示{lang}.png
        bg_bg = Assets.get_localized('P01背景显示.png', settings.lang)
        self._set_panel_background(setting.background_panel, bg_bg)

        # Screencast panel at (10, 551) - P01投屏显示xy{lang}.png
        sc_bg = Assets.get_localized('P01投屏显示xy.png', settings.lang)
        self._set_panel_background(setting.screencast_panel, sc_bg)

        # Video player panel at (371, 551) - P01播放器{lang}.png
        vp_bg = Assets.get_localized('P01播放器.png', settings.lang)
        self._set_panel_background(setting.video_panel, vp_bg)

        # Overlay grid (ucXiTongXianShi1) at (10, 1) - P01内容{lang}.png
        content_bg = Assets.get_localized('P01内容.png', settings.lang)
        self._set_panel_background(setting.overlay_grid, content_bg)

        # Color picker (ucXiTongXianShiColor1) at (492, 1) - P01参数面板{lang}.png
        params_bg = Assets.get_localized('P01参数面板.png', settings.lang)
        self._set_panel_background(setting.color_panel, params_bg)

    def set_language(self, lang: str):
        """Switch all localized backgrounds to a new language.

        Persists to settings, then re-applies all localized backgrounds.

        Args:
            lang: Language suffix ('en', 'tc', 'd', 'e', 'f', 'p', 'r', 'x', '' for Chinese)
        """
        settings.lang = lang

        # Re-apply main background
        self._set_panel_background(self.form_container, Assets.get_localized(Assets.FORM_CZTV_BG, settings.lang))

        # Re-apply theme panel backgrounds
        self._set_panel_background(self.uc_theme_local, Assets.get_localized(Assets.THEME_LOCAL_BG, settings.lang))
        self._set_panel_background(self.uc_theme_web, Assets.get_localized(Assets.THEME_WEB_BG, settings.lang))
        self._set_panel_background(self.uc_theme_mask, Assets.get_localized(Assets.THEME_MASK_BG, settings.lang))

        # Re-apply settings sub-panel backgrounds
        self._apply_settings_backgrounds()

        # Sync about panel (updates button checked states + background)
        self.uc_about.sync_language()

        # Sync LED panel background
        self.uc_led_control.apply_localized_background()

    def _init_theme_directories(self):
        """Initialize theme browser directories."""
        w, h = settings.width, settings.height
        td = settings.theme_dir

        if td:
            self.uc_theme_local.set_theme_directory(td.path)
            if td.exists():
                self._load_carousel_config(td.path)

        if settings.web_dir:
            self.uc_theme_web.set_web_directory(settings.web_dir)
        self.uc_theme_web.set_resolution(f'{w}x{h}')

        if settings.masks_dir:
            self.uc_theme_mask.set_mask_directory(settings.masks_dir)
        self.uc_theme_mask.set_resolution(f'{w}x{h}')

    # =========================================================================
    # Controller Callbacks (controller -> view updates)
    # =========================================================================

    def _connect_controller_callbacks(self):
        """Subscribe to controller callbacks."""
        # Main controller — thin forwards to preview widget
        self.controller.on_preview_update = lambda img: self.uc_preview.set_image(
            img, fast=self.controller.is_video_playing())
        self.controller.on_status_update = self.uc_preview.set_status
        self.controller.on_error = lambda msg: self.uc_preview.set_status(f"Error: {msg}")

        # Video
        self.controller.on_video_state_changed = self._on_video_state_changed
        self.controller.on_video_progress_update = self.uc_preview.set_progress
        self.controller.on_video_loaded = lambda _: self.uc_preview.show_video_controls(True)

        # Devices
        self.controller.on_device_selected = self._on_device_selected
        self.controller.on_send_complete = self._on_send_complete

        # Overlay
        self.controller.on_overlay_config_changed = self.controller.render_overlay_and_preview

    def _on_video_state_changed(self, state: PlaybackState):
        """Handle video state change."""
        if state == PlaybackState.PLAYING:
            self.uc_preview.set_playing(True)
            self.uc_preview.show_video_controls(True)
            interval = self.controller.get_video_interval()
            self._animation_timer.start(interval)
        elif state == PlaybackState.PAUSED:
            self.uc_preview.set_playing(False)
            self._animation_timer.stop()
        else:  # STOPPED
            self.uc_preview.set_playing(False)
            self.uc_preview.show_video_controls(False)
            self._animation_timer.stop()

    def _on_device_selected(self, device: DeviceInfo):
        """Handle device selection — restore per-device config."""
        log.info("Device selected: %s [%04X:%04X] %s %s",
                 device.path, device.vid, device.pid, device.protocol, device.resolution)
        self._active_device_key = Settings.device_config_key(
            device.device_index, device.vid, device.pid)

        # LED devices have no LCD resolution — route to LED panel directly.
        if device.implementation == 'hid_led':
            self._led.show(device)
            self._show_view('led')
            return

        self.uc_preview.set_status(f"Device: {device.path}")

        # Resolution (0,0) = not yet discovered — handshake to find it.
        w, h = device.resolution
        if (w, h) == (0, 0):
            self.uc_preview.set_status("Connecting to device...")
            self._start_handshake(device)
            return

        self._apply_device_config(device, w, h)

    def _start_handshake(self, device: DeviceInfo):
        """Launch background thread to perform HID/Bulk handshake."""
        import threading

        def worker():
            try:
                from ..adapters.device.factory import DeviceProtocolFactory
                protocol = DeviceProtocolFactory.get_protocol(device)
                result = protocol.handshake()
                if result:
                    resolution = getattr(result, 'resolution', None)
                    fbl = getattr(result, 'fbl', None) or getattr(result, 'model_id', None)
                    # Bulk PM=32 uses RGB565, not JPEG
                    bulk_dev = getattr(protocol, '_device', None)
                    use_jpeg = getattr(bulk_dev, 'use_jpeg', True)
                    self._handshake_done.emit(device, (resolution, fbl, use_jpeg))
                else:
                    self._handshake_done.emit(device, None)
            except Exception as e:
                log.warning("Background handshake failed: %s", e)
                self._handshake_done.emit(device, None)

        threading.Thread(target=worker, daemon=True).start()

    def _on_handshake_done(self, device: DeviceInfo, handshake_data: tuple | None):
        """Handle handshake result on the main thread."""
        if not handshake_data:
            log.warning("Handshake failed for %s — no response", device.path)
            self.uc_preview.set_status("Handshake failed — replug device and restart")
            return

        resolution, fbl, *rest = handshake_data
        if not resolution or resolution == (0, 0):
            log.warning("Handshake failed for %s — no resolution", device.path)
            self.uc_preview.set_status("Handshake failed — replug device and restart")
            return

        log.info("Handshake OK: %s → %s (FBL=%s)", device.path, resolution, fbl)
        device.resolution = resolution
        if fbl:
            device.fbl_code = fbl
        if rest:
            device.use_jpeg = rest[0]

        # Resolve product button image from PM/FBL (C# SetButtonImage)
        if fbl:
            self._resolve_device_identity(device, fbl)

        self._apply_device_config(device, *resolution)

    def _resolve_device_identity(self, device: DeviceInfo, fbl: int) -> None:
        """Resolve product button image + name from PM/FBL (C# SetButtonImage).

        After handshake, the PM byte identifies the specific product (e.g. Elite
        Vision vs Frozen Warframe). Updates the sidebar button and persists to
        config so next launch shows the correct image immediately.
        """
        from ..core.models import get_button_image

        btn_img = get_button_image(fbl)
        if not btn_img:
            return

        # Derive product name: "A1ELITE VISION" → "ELITE VISION"
        product = btn_img.replace('A1', '', 1).replace('_', ' ')

        # Update device dict in sidebar
        for dev in self.uc_device.devices:
            if dev.get('path') == device.path:
                dev['button_image'] = btn_img
                dev['product'] = product
                dev['name'] = f"Thermalright {product}"
                self.uc_device.update_device_button(dev)
                break

        # Persist for next launch
        Settings.save_device_setting(
            self._active_device_key, 'resolved_button_image', btn_img)
        Settings.save_device_setting(
            self._active_device_key, 'resolved_product', product)
        log.info("Device identity: FBL=%d → %s (%s)", fbl, product, btn_img)

    def _apply_device_config(self, device: DeviceInfo, w: int, h: int):
        """Apply device resolution, theme, overlay, and carousel config."""
        # Sensor metrics bar — controlled by config.json "show_info_module" (default: off)
        if Settings.show_info_module():
            self.uc_info_module.setVisible(True)
            self.uc_info_module.start_updates(3000)

        if (w, h) != (self.controller.lcd_width, self.controller.lcd_height):
            self._on_resolution_changed(w, h)

        # Restore per-device brightness, rotation, and split mode
        cfg = Settings.get_device_config(self._active_device_key)
        brightness_level = cfg.get('brightness_level', 2)
        rotation_index = cfg.get('rotation', 0) // 90

        self._brightness_level = brightness_level
        brightness_values = {1: 25, 2: 50, 3: 100}
        self.controller.set_brightness(brightness_values.get(brightness_level, 50))

        self.rotation_combo.blockSignals(True)
        self.rotation_combo.setCurrentIndex(rotation_index)
        self.rotation_combo.blockSignals(False)
        rotation = rotation_index * 90
        self.controller.set_rotation(rotation)
        self._resolve_cloud_dirs_for_rotation(rotation)

        # Restore split mode for widescreen devices
        self._split_mode = cfg.get('split_mode', 2)  # Default style B
        self._configure_ldd_for_resolution(w, h)

        # Restore per-device theme (or auto-load first available)
        saved_theme = cfg.get('theme_path')
        theme_loaded = False
        if saved_theme:
            theme_path = Path(saved_theme)
            if theme_path.exists():
                log.info("Restoring saved theme: %s", theme_path)
                if theme_path.suffix in ('.mp4', '.avi', '.mkv', '.webm'):
                    preview = theme_path.parent / f"{theme_path.stem}.png"
                    theme = ThemeInfo.from_video(
                        theme_path, preview if preview.exists() else None)
                    self.controller.select_theme(theme)
                else:
                    self._select_theme_from_path(theme_path)
                theme_loaded = True
            else:
                log.warning("Saved theme path not found: %s", saved_theme)

        if not theme_loaded:
            # Auto-load first local theme for display (don't persist —
            # fallback must not overwrite the user's saved theme preference)
            theme_base = settings.theme_dir
            if theme_base and theme_base.exists():
                for item in sorted(theme_base.path.iterdir()):
                    if item.is_dir() and (item / '00.png').exists():
                        self._select_theme_from_path(item, persist=False)
                        break

        # Restore per-device carousel
        carousel = cfg.get('carousel')
        if carousel and isinstance(carousel, dict):
            self.uc_theme_local._lunbo_array = carousel.get('themes', [])
            self.uc_theme_local._slideshow = carousel.get('enabled', False)
            self.uc_theme_local._slideshow_interval = carousel.get('interval', 3)
            self.uc_theme_local.timer_input.setText(
                str(carousel.get('interval', 3)))
            px = (self.uc_theme_local._lunbo_on if carousel.get('enabled')
                  else self.uc_theme_local._lunbo_off)
            if not px.isNull():
                self.uc_theme_local.slideshow_btn.setIcon(QIcon(px))
                self.uc_theme_local.slideshow_btn.setIconSize(
                    self.uc_theme_local.slideshow_btn.size())
            self.uc_theme_local._apply_decorations()
            self._update_slideshow_state()
        else:
            # No carousel config — stop slideshow, clear badges
            self._slideshow_timer.stop()
            self.uc_theme_local._lunbo_array = []
            self.uc_theme_local._slideshow = False
            self.uc_theme_local._apply_decorations()

        # Restore per-device overlay config
        overlay = cfg.get('overlay')
        if overlay and isinstance(overlay, dict):
            enabled = overlay.get('enabled', False)
            config = overlay.get('config', {})
            log.debug("Restoring overlay: enabled=%s, %d elements", enabled, len(config))
            if config:
                self.uc_theme_setting.load_from_overlay_config(config)
                self.controller.set_overlay_config(config)
            self.uc_theme_setting.set_overlay_enabled(enabled)
            self.controller.enable_overlay(enabled)
            if enabled:
                self.start_metrics()
            else:
                self.stop_metrics()
        else:
            log.debug("No saved overlay config — keeping theme defaults")

    def _on_send_complete(self, success: bool):
        """Handle LCD send completion."""
        if success:
            self.uc_preview.set_status("Sent to LCD")
        else:
            self.uc_preview.set_status("Send failed — run 'trcc hid-debug' for details")

    def _render_and_send(self, skip_if_video: bool = False) -> None:
        """Render overlay preview and send to LCD if auto-send is on."""
        img = self.controller.render_overlay_and_preview()
        if not img or not self.controller.auto_send:
            return
        if skip_if_video and self.controller.is_video_playing():
            return
        self.controller._send_frame_to_lcd(img)

    # =========================================================================
    # View Signals (view -> controller actions)
    # =========================================================================

    def _connect_view_signals(self):
        """Connect view widget signals to controller actions."""
        self.uc_device.device_selected.connect(self._on_device_widget_clicked)
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
        self.uc_preview.delegate.connect(self._on_preview_delegate)

        # Settings panel mode toggles and delegate
        self.uc_theme_setting.background_changed.connect(self._on_background_toggle)
        self.uc_theme_setting.screencast_changed.connect(self._on_screencast_toggle)
        self.uc_theme_setting.delegate.connect(self._on_settings_delegate)

        # Image/video cutters
        self.uc_image_cut.image_cut_done.connect(self._on_image_cut_done)
        self.uc_video_cut.video_cut_done.connect(self._on_video_cut_done)

        # Activity sidebar → overlay grid
        self.uc_activity_sidebar.sensor_clicked.connect(self._on_sensor_element_add)
        self.uc_theme_setting.overlay_grid.add_requested.connect(self._on_overlay_add_requested)

        # Overlay on/off toggle → info module visibility
        self.uc_theme_setting.overlay_grid.toggle_changed.connect(self._on_overlay_toggle)

        # Screencast coordinate changes + border toggle
        self.uc_theme_setting.screencast_params_changed.connect(
            lambda x, y, w, h: (self._screencast.set_params(x, y, w, h),
                                self.uc_preview.set_status(f"Cast: {x},{y} {w}x{h}")))
        self.uc_theme_setting.screencast_panel.border_toggled.connect(
            self._screencast.set_border)

        # Element flash on select (Windows shanPingCount/shanPingTimer)
        self.uc_theme_setting.overlay_grid.element_selected.connect(
            self._on_element_flash)

        # Preview drag → overlay element position (C# UCScreenImage.SetTextPos)
        self.uc_preview.element_drag_start.connect(self._on_drag_start)
        self.uc_preview.element_drag_move.connect(self._on_drag_move)
        self.uc_preview.element_drag_end.connect(self._on_drag_end)
        self.uc_preview.element_nudge.connect(self._on_nudge)
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._drag_elem_x = 0
        self._drag_elem_y = 0

        # Screen capture and eyedropper
        self.uc_theme_setting.capture_requested.connect(self._on_capture_requested)
        self.uc_theme_setting.eyedropper_requested.connect(self._on_eyedropper_requested)

        # Mask download feedback
        self.uc_theme_mask.download_started.connect(
            lambda mask_id: self.uc_preview.set_status(f"Downloading: {mask_id}..."))
        self.uc_theme_mask.download_finished.connect(
            lambda mask_id, ok: self.uc_preview.set_status(
                f"{'Downloaded' if ok else 'Failed'}: {mask_id}"))

        # Sidebar navigation
        self.uc_device.home_clicked.connect(self._show_system_info)
        self.uc_device.about_clicked.connect(self._show_about)
        # Note: _on_device_widget_clicked handles routing to form vs LED view
        self.uc_about.close_requested.connect(self._show_form)
        self.uc_led_control.close_requested.connect(self._show_form)
        self.uc_about.language_changed.connect(self.set_language)
        self.uc_about.temp_unit_changed.connect(self._on_temp_unit_changed)
        self.uc_about.hdd_toggle_changed.connect(self._on_hdd_toggle_changed)
        self.uc_about.refresh_changed.connect(self._on_refresh_changed)

    def _on_device_widget_clicked(self, device_info: dict):
        """Forward device selection to controller.

        Routes to LED panel for LED devices, LCD form for everything else.
        """
        device = DeviceInfo.from_dict(device_info)

        if device.implementation == 'hid_led':
            # Stop LCD timers before switching to LED view
            self._animation_timer.stop()
            self._slideshow_timer.stop()
            self._screencast.stop()
            self.controller.stop_video()
            self._led.show(device)
            self._show_view('led')
        else:
            # Stop LED mode if switching from LED to LCD device
            if self._led.active:
                self._led.stop()
            self._show_view('form')
            # Skip full reload if same device already selected
            current = self.controller.get_selected_device()
            if current and current.path == device.path:
                return
            self.controller.select_device(device)

    def _select_theme_from_path(self, path: Path, persist: bool = True):
        """Load a local/mask theme by directory path.

        Shared by local theme clicks and mask clicks — both have the same
        structure (01.png, config1.dc, optional 00.png). from_directory()
        detects mask-only (no 00.png) and load_local_theme() handles it.

        C# Theme_Click_Event → ReadSystemConfiguration: fully overrides
        myBjxs, myMode, myUIMode from config1.dc. We reset all mode toggles.

        Args:
            persist: Save theme_path to config. False for auto-fallback
                     to avoid overwriting the user's saved preference.
        """
        if not path.exists():
            return
        self._slideshow_timer.stop()
        self.stop_metrics()
        # Reset background/screencast/video modes (C# ReadSystemConfiguration override)
        self._background_active = False
        self._screencast.stop()
        self._animation_timer.stop()
        self.uc_theme_setting.background_panel.set_enabled(False)
        self.uc_theme_setting.screencast_panel.set_enabled(False)
        self.uc_theme_setting.video_panel.set_enabled(False)
        theme = ThemeInfo.from_directory(path)
        self.controller.select_theme(theme)
        self._load_theme_overlay_config(path)
        if persist and self._active_device_key:
            Settings.save_device_setting(self._active_device_key, 'theme_path', str(path))

    def _on_local_theme_clicked(self, theme_info):
        """Forward local theme selection to controller."""
        self._select_theme_from_path(Path(theme_info.path))
        # Update name input so re-saving overwrites the same theme
        name = theme_info.name
        if name.startswith('Custom_'):
            name = name[len('Custom_'):]
        self.theme_name_input.setText(name)

    def _on_cloud_theme_clicked(self, theme_info):
        """Forward cloud theme selection to controller.

        Cloud videos are backgrounds — overlay (mask + metrics) persists.
        Don't stop metrics; they keep rendering on top of video frames.
        """
        # Stop slideshow — cloud video must not be overwritten by carousel
        self._slideshow_timer.stop()
        # Reset background/screencast modes (cloud theme overrides)
        self._background_active = False
        self._screencast.stop()
        self.uc_theme_setting.background_panel.set_enabled(False)
        self.uc_theme_setting.screencast_panel.set_enabled(False)
        if theme_info.video:
            video_path = Path(theme_info.video)
            preview_path = video_path.parent / f"{video_path.stem}.png"
            theme = ThemeInfo.from_video(video_path, preview_path if preview_path.exists() else None)
            self.controller.select_theme(theme)
            if self._active_device_key:
                Settings.save_device_setting(self._active_device_key, 'theme_path',
                                    str(video_path))

    def _on_mask_clicked(self, mask_info):
        """Apply mask overlay on top of current content (preserves video)."""
        if mask_info.path:
            mask_dir = Path(mask_info.path)
            self.controller.apply_mask(mask_dir)
            self._load_theme_overlay_config(mask_dir)
        else:
            self.uc_preview.set_status(f"Mask: {mask_info.name}")

    def _on_overlay_changed(self, element_data: dict):
        """Forward overlay change to controller for live preview + LCD."""
        if not element_data:
            return
        # Ensure overlay is enabled when user is actively editing elements
        # (grid toggle is ON — to_overlay_config() returns {} when OFF,
        #  caught by the empty check above)
        if not self.controller.is_overlay_enabled():
            self.controller.enable_overlay(True)
            self.start_metrics()
        self.controller.set_overlay_config(element_data)
        self._render_and_send(skip_if_video=True)

        # Save overlay config per-device
        if self._active_device_key:
            Settings.save_device_setting(self._active_device_key, 'overlay', {
                'enabled': self.uc_theme_setting.overlay_grid.overlay_enabled,
                'config': element_data,
            })

    def _on_background_toggle(self, enabled: bool):
        """Handle background display toggle from settings (C# myBjxs / myMode=0).

        ON:  Stop other modes, render background+overlays, start continuous
             sending via metrics timer (C# isToTimer=true, myMode=0).
        OFF: Keep timer running but render black+overlays (C# myBjxs=false,
             isDrawBkImage=false — timer continues, background not drawn).
        """
        self._background_active = enabled
        if enabled:
            # Stop other modes (C# exclusive toggle — only one mode active)
            self._animation_timer.stop()
            self.controller.stop_video()
            self._screencast.stop()
            self._render_and_send()
            # Start continuous rendering (C# isToTimer=true — timer sends every tick)
            if not self._metrics_timer.isActive():
                self._metrics_timer.start(1000)
        else:
            # C# toggle OFF: myBjxs=false → black canvas + overlays
            self.controller.set_overlay_background(None)
            self.controller._display._create_black_background()
            self._render_and_send()
            # Stop continuous background sending if overlay isn't independently enabled
            if not self.controller.is_overlay_enabled():
                self._metrics_timer.stop()
        self.uc_preview.set_status(f"Background: {'On' if enabled else 'Off'}")

    def _on_screencast_toggle(self, enabled: bool):
        """Handle screencast toggle — delegate to ScreencastHandler."""
        if enabled:
            self._animation_timer.stop()
            self.controller.stop_video()
        self._screencast.toggle(enabled)
        self.uc_preview.set_status(f"Screencast: {'On' if enabled else 'Off'}")

    def _on_mask_display_toggle(self, enabled):
        """Toggle mask visibility on preview/LCD (Windows SetDrawMengBan)."""
        self.controller.set_overlay_mask_visible(enabled)
        self._render_and_send()
        self.uc_preview.set_status(f"Mask: {'On' if enabled else 'Off'}")

    def _switch_to_mask_tab(self):
        """Switch to Mask browser tab (panel index 2)."""
        self._show_panel(2)

    def _on_mask_reset(self):
        """Clear mask from preview (Windows buttonYDMB_Click / cmd 99)."""
        self.controller.set_overlay_theme_mask(None)
        self._render_and_send()
        self.uc_preview.set_status("Mask cleared")

    def _on_video_display_toggle(self, enabled):
        """Toggle video playback mode (Windows cmd 3 / myMode=48)."""
        if enabled:
            # Resume playback if video is loaded (Windows: ucBoFangQiKongZhi1.Player())
            if self.controller.video_has_frames():
                self.controller.play_pause()
            self.uc_preview.set_status("Video mode: On")
        else:
            self.controller.stop_video()
            self._animation_timer.stop()
            self.uc_preview.set_status("Video mode: Off")

    def _on_settings_delegate(self, cmd, info, data):
        """Handle delegate events from settings panel."""
        if cmd == UCThemeSetting.CMD_BACKGROUND_LOAD_IMAGE:
            self._on_load_image_clicked()
        elif cmd == UCThemeSetting.CMD_BACKGROUND_LOAD_VIDEO:
            self._on_load_video_clicked()
        elif cmd == UCThemeSetting.CMD_MASK_TOGGLE:
            self._on_mask_display_toggle(info)
        elif cmd == UCThemeSetting.CMD_MASK_LOAD:
            self._switch_to_mask_tab()
        elif cmd == UCThemeSetting.CMD_MASK_RESET:
            self._on_mask_reset()
        elif cmd == UCThemeSetting.CMD_VIDEO_LOAD:
            self._on_load_video_clicked()
        elif cmd == UCThemeSetting.CMD_VIDEO_TOGGLE:
            self._on_video_display_toggle(info)
        elif cmd == UCThemeSetting.CMD_OVERLAY_CHANGED:
            self._on_overlay_changed(info if isinstance(info, dict) else {})

    def _on_preview_delegate(self, cmd, info, data):
        """Handle preview panel commands."""
        if cmd == UCPreview.CMD_VIDEO_PLAY_PAUSE:
            self.controller.play_pause()
        elif cmd == UCPreview.CMD_VIDEO_SEEK:
            self.controller.seek_video(info)
        elif cmd == UCPreview.CMD_VIDEO_FIT_WIDTH:
            self.controller.set_video_fit_mode('width')
        elif cmd == UCPreview.CMD_VIDEO_FIT_HEIGHT:
            self.controller.set_video_fit_mode('height')

    def _on_load_video_clicked(self):
        """Handle load video → open file dialog → show video cutter."""
        web_dir = str(settings.web_dir) if settings.web_dir else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", web_dir,
            "Video Files (*.mp4 *.avi *.mov *.gif);;All Files (*)"
        )
        if path:
            w, h = self.controller.lcd_width, self.controller.lcd_height
            self.uc_video_cut.set_resolution(w, h)
            self.uc_video_cut.load_video(path)
            self._show_video_cutter()

    def _on_load_image_clicked(self):
        """Handle load image → open file dialog → show image cutter."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)"
        )
        if path:
            try:
                from PIL import Image as PILImage
                pil_img = PILImage.open(path)
                w, h = self.controller.lcd_width, self.controller.lcd_height
                self.uc_image_cut.load_image(pil_img, w, h)
                self._show_image_cutter()
            except Exception as e:
                self.uc_preview.set_status(f"Error: {e}")

    def _on_save_clicked(self):
        """Handle save theme button click (Windows buttonBCZT_Click)."""
        name = self.theme_name_input.text().strip()
        if not name:
            self.uc_preview.set_status("Enter a theme name first")
            return
        success, msg = self.controller.save_theme(name, settings.user_data_dir)
        self.uc_preview.set_status(msg)
        if success:
            td = settings.theme_dir
            if td:
                self.uc_theme_local.set_theme_directory(td.path)
            self.uc_theme_local.load_themes()
            # Persist saved theme path for --last-one resume
            if self._active_device_key and self.controller.current_theme_path:
                Settings.save_device_setting(self._active_device_key, 'theme_path',
                                    str(self.controller.current_theme_path))

    def _on_export_clicked(self):
        """Handle export theme button click."""
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Theme", "",
            "Theme files (*.tr);;JSON (*.json);;All Files (*)"
        )
        if path:
            success, msg = self.controller.export_config(Path(path))
            self.uc_preview.set_status(msg)

    def _on_import_clicked(self):
        """Handle import theme button click."""
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Theme", "",
            "Theme files (*.tr);;JSON (*.json);;All Files (*)"
        )
        if path:
            success, msg = self.controller.import_config(Path(path), self._data_dir)
            self.uc_preview.set_status(msg)
            if success:
                td = settings.theme_dir
                if td:
                    self.uc_theme_local.set_theme_directory(td.path)
                self.uc_theme_local.load_themes()

    # =========================================================================
    # Image/Video Cutters
    # =========================================================================

    def _show_image_cutter(self):
        """Show the image cropper, hiding the preview."""
        self.uc_preview.setVisible(False)
        self.uc_video_cut.setVisible(False)
        self.uc_image_cut.setVisible(True)
        self.uc_image_cut.raise_()

    def _show_video_cutter(self):
        """Show the video trimmer, hiding the preview."""
        self.uc_preview.setVisible(False)
        self.uc_image_cut.setVisible(False)
        self.uc_video_cut.setVisible(True)
        self.uc_video_cut.raise_()

    def _hide_cutters(self):
        """Hide cutters and restore preview."""
        self.uc_image_cut.setVisible(False)
        self.uc_video_cut.setVisible(False)
        self.uc_preview.setVisible(True)

    def _on_image_cut_done(self, result):
        """Handle image crop completion.

        Args:
            result: Cropped PIL Image at target resolution, or None on cancel.
        """
        self._hide_cutters()
        if result is not None:
            # Save cropped image as background (Windows: ImageCut_OK_Write)
            self.controller.current_image = result
            # Save to working dir for later theme save
            bg_path = self.controller.working_dir / '00.png'
            result.save(str(bg_path))
            # Set as overlay background so mask/overlays render on top
            self.controller.set_overlay_background(result)
            self._render_and_send()
            self.uc_preview.set_status("Image cropped and saved")
        else:
            self.uc_preview.set_status("Image crop cancelled")

    def _on_video_cut_done(self, zt_path):
        """Handle video export completion.

        Args:
            zt_path: Path to exported Theme.zt, or '' on cancel.
        """
        self._hide_cutters()
        if zt_path:
            # Copy Theme.zt to working dir for later theme save
            import shutil
            dest_path = self.controller.working_dir / 'Theme.zt'
            shutil.copy(zt_path, dest_path)
            # Load and play
            self.controller.load_video(dest_path)
            self.controller.play_video()
            self.uc_preview.set_status("Video exported and saved")
        else:
            self.uc_preview.set_status("Video cut cancelled")

    # =========================================================================
    # Activity Sidebar / Overlay Elements
    # =========================================================================

    def _on_overlay_add_requested(self):
        """Show activity sidebar when overlay grid requests add."""
        self.uc_activity_sidebar.setVisible(True)
        self.uc_activity_sidebar.raise_()
        self.uc_activity_sidebar.start_updates()

    def _on_sensor_element_add(self, config):
        """Add sensor element to overlay grid from activity sidebar."""
        self.uc_theme_setting.overlay_grid.add_element(config)
        self.uc_activity_sidebar.setVisible(False)
        self.uc_activity_sidebar.stop_updates()

    def _on_overlay_toggle(self, enabled):
        """Toggle overlay display."""
        if enabled:
            self.start_metrics()
        else:
            self.stop_metrics()

        # Save overlay enabled state per-device
        if self._active_device_key:
            cfg = Settings.get_device_config(self._active_device_key)
            overlay = cfg.get('overlay', {})
            overlay['enabled'] = enabled
            Settings.save_device_setting(self._active_device_key, 'overlay', overlay)

    def _on_element_flash(self, index: int, config: dict):
        """Flash/blink selected overlay element on preview (Windows shanPingCount).

        Hides the element for ~1 second so the user can spot its position.
        """
        self.controller.overlay_flash_skip_index = index
        self._flash_timer.start(980)  # 14 ticks * 70ms = 980ms
        self.controller.render_overlay_and_preview()

    def _on_flash_timeout(self):
        """End element flash — restore normal rendering."""
        self.controller.overlay_flash_skip_index = -1
        self.controller.render_overlay_and_preview()

    # ── Preview drag → overlay element position (C# UCScreenImage.SetTextPos) ──

    def _on_drag_start(self, lcd_x: int, lcd_y: int):
        """Record drag origin and current element position."""
        cfg = self.uc_theme_setting.overlay_grid.get_selected_config()
        if cfg is None:
            return
        self._drag_origin_x = lcd_x
        self._drag_origin_y = lcd_y
        self._drag_elem_x = cfg.x
        self._drag_elem_y = cfg.y

    def _on_drag_move(self, lcd_x: int, lcd_y: int):
        """Move selected element by drag delta (C# SetTextPos delta logic)."""
        cfg = self.uc_theme_setting.overlay_grid.get_selected_config()
        if cfg is None:
            return
        dx = lcd_x - self._drag_origin_x
        dy = lcd_y - self._drag_origin_y
        new_x = max(0, min(self._drag_elem_x + dx, self.controller.lcd_width))
        new_y = max(0, min(self._drag_elem_y + dy, self.controller.lcd_height))
        self.uc_theme_setting.color_panel.set_position(new_x, new_y)
        self.uc_theme_setting._on_position_changed(new_x, new_y)

    def _on_drag_end(self):
        """Drag complete — position already saved via _on_position_changed."""
        pass

    def _on_nudge(self, dx: int, dy: int):
        """WASD/arrow key nudge: move selected element by delta."""
        cfg = self.uc_theme_setting.overlay_grid.get_selected_config()
        if cfg is None:
            return
        new_x = max(0, min(cfg.x + dx, self.controller.lcd_width))
        new_y = max(0, min(cfg.y + dy, self.controller.lcd_height))
        self.uc_theme_setting.color_panel.set_position(new_x, new_y)
        self.uc_theme_setting._on_position_changed(new_x, new_y)

    # =========================================================================
    # Delete Theme (Windows cmd=32)
    # =========================================================================

    def _on_delete_theme(self, theme_info):
        """Handle theme delete request — show confirmation, delete directory."""
        from PySide6.QtWidgets import QMessageBox
        name = theme_info.name
        reply = QMessageBox.question(
            self, "Delete Theme",
            f"Delete theme '{name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )
        if reply == QMessageBox.StandardButton.Yes:
            self.uc_theme_local.delete_theme(theme_info)
            # If deleted theme was the current one, clear preview
            if (self.controller.current_theme_path and
                    str(self.controller.current_theme_path) == theme_info.path):
                self.controller.current_image = None
                self.uc_preview.set_image(None)
            self.uc_preview.set_status(f"Deleted: {name}")

    # =========================================================================
    # Slideshow / Carousel (Windows cmd=48, myLunBoTimer)
    # =========================================================================

    def _on_local_delegate(self, cmd, info, data):
        """Handle delegate events from local themes panel."""
        if cmd == UCThemeLocal.CMD_SLIDESHOW:
            self._update_slideshow_state()

    def _update_slideshow_state(self):
        """Update slideshow timer based on current UCThemeLocal state."""
        if (self.uc_theme_local.is_slideshow()
                and self.uc_theme_local.get_slideshow_themes()):
            interval_s = self.uc_theme_local.get_slideshow_interval()
            self._slideshow_index = 0
            self._slideshow_timer.start(interval_s * 1000)
        else:
            self._slideshow_timer.stop()

        # Save carousel config (Theme.dc) - Windows cmd=48
        self._save_carousel_config()

        # Persist carousel state per-device
        if self._active_device_key:
            themes = self.uc_theme_local.get_slideshow_themes()
            Settings.save_device_setting(self._active_device_key, 'carousel', {
                'enabled': self.uc_theme_local.is_slideshow(),
                'interval': self.uc_theme_local.get_slideshow_interval(),
                'themes': [t.name for t in themes],
            })

    def _get_theme_dir(self) -> Path:
        """Get current theme directory for this resolution."""
        td = settings.theme_dir
        return td.path if td else Path(".")

    def _save_carousel_config(self):
        """Save carousel/slideshow config to Theme.dc (Windows cmd=48)."""
        theme_dir = self._get_theme_dir()
        if not theme_dir.exists():
            return

        # Build theme index list from selected themes
        all_themes = self.uc_theme_local._all_themes
        slideshow_themes = self.uc_theme_local.get_slideshow_themes()
        theme_indices = []
        for t in slideshow_themes:
            for i, at in enumerate(all_themes):
                if at.name == t.name:
                    theme_indices.append(i)
                    break

        # Pad to 6 slots with -1
        while len(theme_indices) < 6:
            theme_indices.append(-1)

        # Get current theme index
        selected = self.uc_theme_local.get_selected_theme()
        current_idx = 0
        if selected:
            for i, at in enumerate(all_themes):
                if at.name == selected.name:
                    current_idx = i
                    break

        # Build config
        config = CarouselConfig(
            current_theme=current_idx,
            enabled=self.uc_theme_local.is_slideshow(),
            interval_seconds=self.uc_theme_local.get_slideshow_interval(),
            count=len([i for i in theme_indices if i >= 0]),
            theme_indices=theme_indices[:6],
            lcd_rotation=self._split_mode if self._ldd_is_split else 1,  # myLddVal
        )

        # Write to Theme.dc
        try:
            write_carousel_config(config, str(theme_dir / 'Theme.dc'))
        except Exception as e:
            log.error("Failed to save carousel config: %s", e)

    def _load_carousel_config(self, theme_dir: Path):
        """Load carousel/slideshow config from Theme.dc."""
        config_path = theme_dir / 'Theme.dc'
        config = read_carousel_config(str(config_path))
        if config is None:
            return

        # Get all themes list
        all_themes = self.uc_theme_local._all_themes

        # Restore slideshow theme selections
        slideshow_names = []
        for idx in config.theme_indices:
            if 0 <= idx < len(all_themes):
                slideshow_names.append(all_themes[idx].name)
        self.uc_theme_local._lunbo_array = slideshow_names
        self.uc_theme_local._slideshow = config.enabled
        self.uc_theme_local._slideshow_interval = config.interval_seconds

        # Update UI
        self.uc_theme_local.timer_input.setText(str(config.interval_seconds))
        px = (self.uc_theme_local._lunbo_on if config.enabled
              else self.uc_theme_local._lunbo_off)
        if not px.isNull():
            self.uc_theme_local.slideshow_btn.setIcon(QIcon(px))
            self.uc_theme_local.slideshow_btn.setIconSize(
                self.uc_theme_local.slideshow_btn.size())

        # Refresh decorations to show badges
        self.uc_theme_local._apply_decorations()

        # Start timer if enabled
        self._update_slideshow_state()

        # Restore split mode from Theme.dc (myLddVal stored in lcd_rotation field)
        if 1 <= config.lcd_rotation <= 3:
            self._split_mode = config.lcd_rotation
            if self._ldd_is_split:
                self.controller.set_split_mode(self._split_mode)
                self._update_ldd_icon()

    def _on_slideshow_tick(self):
        """Auto-rotate to next theme in slideshow (Windows Timer_event lunbo)."""
        # Don't override a playing cloud video with slideshow themes
        if self.controller.is_video_playing():
            return

        themes = self.uc_theme_local.get_slideshow_themes()
        if not themes:
            self._slideshow_timer.stop()
            return

        self._slideshow_index = (self._slideshow_index + 1) % len(themes)
        theme_info = themes[self._slideshow_index]

        # Load theme without resetting slideshow state
        path = Path(theme_info.path)
        if path.exists():
            theme = ThemeInfo.from_directory(path)
            self.controller.select_theme(theme)
            self._load_theme_overlay_config(path)

    def _on_screencast_frame(self, pil_img):
        """Handle captured screencast frame — preview + send to LCD."""
        self.uc_preview.set_image(pil_img)
        self.controller._send_frame_to_lcd(pil_img)

    def _on_capture_requested(self):
        """Launch screen capture overlay → feed to image cutter."""
        from .screen_capture import ScreenCaptureOverlay
        self._capture_overlay = ScreenCaptureOverlay()
        self._capture_overlay.captured.connect(self._on_screen_captured)
        self._capture_overlay.show()

    def _on_screen_captured(self, pil_img):
        """Handle captured screen region."""
        self._capture_overlay = None
        if pil_img is None:
            return
        w, h = self.controller.lcd_width, self.controller.lcd_height
        self.uc_image_cut.load_image(pil_img, w, h)
        self._show_image_cutter()

    def _on_eyedropper_requested(self):
        """Launch eyedropper color picker overlay."""
        from .eyedropper import EyedropperOverlay
        self._eyedropper_overlay = EyedropperOverlay()
        self._eyedropper_overlay.color_picked.connect(self._eyedropper_pick)
        self._eyedropper_overlay.cancelled.connect(
            lambda: setattr(self, '_eyedropper_overlay', None))
        self._eyedropper_overlay.show()

    def _eyedropper_pick(self, r, g, b):
        """Handle picked color from eyedropper."""
        self._eyedropper_overlay = None
        self.uc_theme_setting.color_panel._apply_color(r, g, b)

    # =========================================================================
    # DC File Loading
    # =========================================================================

    def _load_theme_overlay_config(self, theme_dir: Path):
        """Load overlay config from theme's config.json or config1.dc into settings panel."""
        overlay_config = None

        # Try reference config.json first (Custom_ themes saved with path refs)
        json_path = theme_dir / 'config.json'
        if json_path.exists():
            try:
                from ..adapters.infra.dc_parser import load_config_json
                result = load_config_json(str(json_path))
                if result is not None:
                    overlay_config = result[0]  # (overlay_config, display_options)
            except Exception:
                pass

        # Fall back to binary config1.dc
        if overlay_config is None:
            dc_path = theme_dir / 'config1.dc'
            if not dc_path.exists():
                return
            try:
                from ..adapters.infra.dc_config import DcConfig
                dc = DcConfig(dc_path)
                overlay_config = dc.to_overlay_config()
                # Apply screen capture region from DC (JpX/JpY/JpW/JpH)
                self._screencast.set_params(
                    dc.overlay_x, dc.overlay_y, dc.overlay_w, dc.overlay_h)
            except Exception:
                return

        if overlay_config:
            # Apply user's saved format preferences (time/date/temp)
            Settings.apply_format_prefs(overlay_config)

            self.uc_theme_setting.set_overlay_enabled(True)
            self.uc_theme_setting.load_from_overlay_config(overlay_config)
            self.controller.set_overlay_config(overlay_config)
            self.controller.enable_overlay(True)
            self.start_metrics()

            # Persist to per-device config so overlay survives device re-selection
            if self._active_device_key:
                Settings.save_device_setting(self._active_device_key, 'overlay', {
                    'enabled': True,
                    'config': overlay_config,
                })

    # =========================================================================
    # Device Hot-Plug
    # =========================================================================

    def _on_device_poll(self):
        """Poll for LCD and LED device connections.

        Adaptive interval: 15s when a device is connected (hot-unplug detect),
        5s when searching for a device (faster initial connect).
        """
        try:
            devices = find_lcd_devices()

            # Update sidebar (handles both connect and disconnect)
            self.uc_device.update_devices(devices)

            # Auto-select first device if none selected
            if devices and not self.controller.get_selected_device() and not self._led.active:
                device = DeviceInfo.from_dict(devices[0])
                if device.implementation == 'hid_led':
                    self._led.show(device)
                    self._show_view('led')
                else:
                    self.controller.select_device(device)
                    self.uc_preview.set_status(f"Device: {device.path}")

            # Adaptive poll: slow when connected, fast when searching
            has_device = bool(
                self.controller.get_selected_device() or self._led.active)
            interval = 15000 if has_device else 5000
            if self._device_timer.interval() != interval:
                self._device_timer.start(interval)
        except Exception as e:
            log.error("Device poll error: %s", e)

    def _on_rotation_change(self, index):
        """Handle rotation combobox change (Windows UpDateUCComboBox1).

        Windows maps: mode 1→0°, 2→90°, 3→180°, 4→270°
        We use 0-indexed: 0→0°, 1→90°, 2→180°, 3→270°
        """
        rotation = index * 90
        self.controller.set_rotation(rotation)
        if self._active_device_key:
            Settings.save_device_setting(self._active_device_key, 'rotation', rotation)
        # C# GetWebBackgroundImageDirectory: swap dims for portrait rotation
        self._resolve_cloud_dirs_for_rotation(rotation)
        self.uc_preview.set_status(f"Rotation: {rotation}°")

    def _resolve_cloud_dirs_for_rotation(self, rotation: int):
        """Re-resolve cloud background/mask dirs and reload panels.

        C# GetWebBackgroundImageDirectory / GetFileListMBDir: non-square
        displays swap width/height when directionB is 90 or 270.
        """
        settings.resolve_cloud_dirs(rotation)
        w, h = settings.width, settings.height
        if w != h and rotation in (90, 270):
            w, h = h, w
        if settings.web_dir:
            self.uc_theme_web.set_web_directory(settings.web_dir)
        self.uc_theme_web.set_resolution(f'{w}x{h}')
        if settings.masks_dir:
            self.uc_theme_mask.set_mask_directory(settings.masks_dir)
        self.uc_theme_mask.set_resolution(f'{w}x{h}')

    def _on_ldd_click(self):
        """Handle buttonLDD click — split mode for widescreen, brightness for others."""
        if self._ldd_is_split:
            self._split_mode = (self._split_mode % 3) + 1  # 1→2→3→1
            self.controller.set_split_mode(self._split_mode)
            self._update_ldd_icon()
            if self._active_device_key:
                Settings.save_device_setting(
                    self._active_device_key, 'split_mode', self._split_mode)
            self.uc_preview.set_status(f"Split mode: {self._split_mode}")
        else:
            self._brightness_level = (self._brightness_level % 3) + 1  # 1→2→3→1
            self._update_ldd_icon()
            brightness_values = {1: 25, 2: 50, 3: 100}
            brightness = brightness_values[self._brightness_level]
            self.controller.set_brightness(brightness)
            if self._active_device_key:
                Settings.save_device_setting(
                    self._active_device_key, 'brightness_level',
                    self._brightness_level)
            self.uc_preview.set_status(
                f"Brightness: L{self._brightness_level} ({brightness}%)")

    def _update_ldd_icon(self):
        """Update buttonLDD icon for current mode."""
        level = self._split_mode if self._ldd_is_split else self._brightness_level
        pix = self._ldd_pixmaps.get(level)
        if pix and not pix.isNull():
            self.ldd_btn.setIcon(QIcon(pix))
            self.ldd_btn.setIconSize(QSize(52, 24))
            self.ldd_btn.setStyleSheet(Styles.ICON_BUTTON_HOVER)
        else:
            label = f"S{level}" if self._ldd_is_split else f"L{level}"
            self.ldd_btn.setText(label)
            self.ldd_btn.setStyleSheet(Styles.TEXT_BUTTON)

    def _configure_ldd_for_resolution(self, width: int, height: int):
        """Configure buttonLDD as split mode or brightness based on resolution."""
        is_split = (width, height) in SPLIT_MODE_RESOLUTIONS
        self._ldd_is_split = is_split
        if is_split:
            self.ldd_btn.setToolTip("Split overlay style (Dynamic Island)")
            if not self._split_mode:
                self._split_mode = 2  # C# default: style B
            self.controller.set_split_mode(self._split_mode)
        else:
            self.ldd_btn.setToolTip("Cycle brightness (Low / Medium / High)")
            self.controller.set_split_mode(0)  # Disable split for non-widescreen
        self._update_ldd_icon()

    def _on_metrics_tick(self):
        """Collect system metrics and re-render overlay, send to LCD.

        C# Timer_event myMode=0: renders every 10 ticks (~160ms).
        We tick every 1s (sufficient for sensor refresh) and always send
        when background mode is active OR overlay is enabled.
        """
        try:
            metrics = get_all_metrics()
        except Exception:
            return
        self.controller.update_overlay_metrics(metrics)
        should_render = (
            (self.controller.current_image and self.controller.is_overlay_enabled())
            or self._background_active
        )
        if not should_render:
            return
        self._render_and_send(skip_if_video=True)

    def start_metrics(self):
        """Start live metrics collection for overlay display."""
        log.info("Metrics timer started (1s interval)")
        self.controller.enable_overlay(True)
        self._metrics_timer.start(1000)

    def stop_metrics(self):
        """Stop live metrics collection."""
        log.info("Metrics timer stopped")
        self.controller.enable_overlay(False)
        self._metrics_timer.stop()

    # =========================================================================
    # Borderless Window Drag
    # =========================================================================

    def mousePressEvent(self, event):
        """Start drag when clicking title bar area (borderless mode only)."""
        if self._decorated or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        # Drag from sidebar top (x<180, y<95) or FormCZTV header (y<80)
        if pos.y() < 80 or (pos.x() < 180 and pos.y() < 95):
            self._drag_pos = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
        event.accept()

    def mouseMoveEvent(self, event):
        """Move window while dragging (borderless mode only)."""
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        event.accept()

    def mouseReleaseEvent(self, event):
        """End drag."""
        self._drag_pos = None
        event.accept()

    # =========================================================================
    # Cleanup
    # =========================================================================

    def closeEvent(self, event):
        """Hide to tray on window close; full quit only via tray Exit.

        If system tray is not available (e.g. GNOME without AppIndicator),
        close the window instead of hiding to an invisible tray.
        """
        if not self._force_quit and self._tray.isSystemTrayAvailable() and self._tray.isVisible():
            event.ignore()
            self.hide()
            return

        # Full quit — stop timers and clean up
        self._tray.hide()
        self._animation_timer.stop()
        self._slideshow_timer.stop()
        self._screencast.cleanup()
        self._metrics_timer.stop()
        self._device_timer.stop()
        self._led.cleanup()
        self.uc_system_info.stop_updates()
        self.uc_info_module.stop_updates()
        self.uc_activity_sidebar.stop_updates()
        self.controller.stop_video()
        self.controller.cleanup()
        TRCCMainWindowMVC._instance = None
        event.accept()
        app = QApplication.instance()
        if app:
            app.quit()


def _lock_path() -> Path:
    """Lock file path for single-instance guard."""
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "trcc-linux.lock"


def _acquire_instance_lock() -> object | None:
    """Try to acquire a single-instance lock file.

    Returns the open file handle (must stay alive) or None if another instance
    is already running.  Uses fcntl.flock — the OS releases the lock
    automatically when the process exits, even on crash/SIGKILL.
    """
    import fcntl
    try:
        fh = open(_lock_path(), "w")  # noqa: SIM115
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh  # caller must keep a reference so the lock stays held
    except OSError:
        return None


def _raise_existing_instance() -> None:
    """Send SIGUSR1 to the running instance so it raises its window."""
    import signal
    try:
        pid = int(_lock_path().read_text().strip())
        os.kill(pid, signal.SIGUSR1)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        pass


def run_mvc_app(data_dir: Path | None = None, decorated: bool = False,
                start_hidden: bool = False):
    """Run the MVC PyQt6 application.

    Args:
        data_dir: Override data directory path.
        decorated: Use decorated window with titlebar.
        start_hidden: Start minimized to system tray (--last-one autostart).
    """
    import os
    lock = _acquire_instance_lock()
    if lock is None:
        _raise_existing_instance()
        return 0

    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.services=false")
    # Disable Qt6 auto high-DPI scaling — our GUI uses absolute pixel
    # positioning with image backgrounds (like the C# Windows app).
    # Without this, HiDPI displays (e.g. 2x scale) double all coordinates,
    # clipping the 1454x800 window to show only a quarter.
    # Force-set (not setdefault) — desktop environments and system updates
    # (e.g. CachyOS Qt6 packages) may set this to "1" in the environment.
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    QApplication.setDesktopFileName("trcc-linux")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setProperty("_instance_lock", lock)  # prevent GC from releasing the file lock

    font = QFont("Microsoft YaHei", 10)
    if not font.exactMatch():
        font = QFont("Sans Serif", 10)
    app.setFont(font)

    window = TRCCMainWindowMVC(data_dir, decorated=decorated)

    # SIGUSR1 handler: second launch raises the existing window.
    # Unix signals can't call Qt directly — bridge via socketpair.
    import signal
    import socket
    rsock, wsock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
    rsock.setblocking(False)
    wsock.setblocking(False)

    def _on_sigusr1(signum, frame):
        try:
            wsock.send(b'\x01')
        except OSError:
            pass

    signal.signal(signal.SIGUSR1, _on_sigusr1)

    from PySide6.QtCore import QSocketNotifier
    notifier = QSocketNotifier(rsock.fileno(), QSocketNotifier.Type.Read, app)

    def _raise_window():
        try:
            rsock.recv(1)
        except OSError:
            pass
        window.showNormal()
        window.raise_()
        window.activateWindow()

    notifier.activated.connect(_raise_window)

    if not start_hidden:
        window.show()

    return app.exec()


if __name__ == '__main__':
    sys.exit(run_mvc_app())
