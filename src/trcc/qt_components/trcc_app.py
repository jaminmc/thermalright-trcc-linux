"""TRCCApp — thin shell main window (C# Form1 equivalent).

Owns: window chrome, tray, device sidebar, panel stack, timers.
Creates one LCDHandler or LEDHandler per connected device.
All business logic lives in handlers — this is pure shell.
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
from ..adapters.infra.dc_writer import read_carousel_config
from ..adapters.system.sensors import SensorEnumerator
from ..conf import Settings, settings
from ..core.builder import ControllerBuilder
from ..core.led_device import LEDDevice
from ..core.models import DeviceInfo
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

log = logging.getLogger(__name__)


# =============================================================================
# LED Handler — uses LEDDevice (no callbacks, result dicts only)
# =============================================================================

class LEDHandler:
    """Mediator for LED device control.

    Owns LEDDevice lifecycle, animation timer, sensor polling,
    and signal wiring. No callbacks — uses result dicts from LEDDevice.
    """

    def __init__(self, panel: UCLedControl, on_temp_unit_changed):
        self._panel = panel
        self._on_temp_unit_changed = on_temp_unit_changed
        self._led: LEDDevice | None = None
        self._active = False
        self._style_id = 0

        self._timer = QTimer(panel)
        self._timer.timeout.connect(self._on_tick)

    @property
    def active(self) -> bool:
        return self._active

    @property
    def has_controller(self) -> bool:
        return self._led is not None

    @property
    def led_port(self) -> LEDDevice | None:
        return self._led

    def show(self, device: DeviceInfo):
        """Initialize LED device and start animation."""
        if self._led is None:
            self._led = LEDDevice()
            self._connect_signals()

        from ..services.led import LEDService
        model = device.model or ''
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

        seg_unit = "F" if settings.temp_unit == 1 else "C"
        self._led.set_seg_temp_unit(seg_unit)

        self._active = True
        self._timer.start(150)

    def stop(self):
        self._timer.stop()
        self._active = False
        if self._led:
            self._led.cleanup()

    def cleanup(self):
        self._timer.stop()
        if self._led:
            self._led.cleanup()

    def set_temp_unit(self, unit: str):
        if self._led:
            self._led.set_seg_temp_unit(unit)

    def _sync_ui_from_state(self):
        if not self._led:
            return
        state = self._led.state
        if state.zones:
            z = state.zones[0]
            self._panel.load_zone_state(
                0, z.mode.value, z.color, z.brightness, z.on)
        else:
            self._panel.load_zone_state(
                0, state.mode.value, state.color, state.brightness,
                state.global_on)

    def _connect_signals(self):
        if not self._led:
            return
        led = self._led
        panel = self._panel

        panel.mode_changed.connect(self._on_mode_changed)
        panel.color_changed.connect(self._on_color_changed)
        panel.brightness_changed.connect(self._on_brightness_changed)
        panel.global_toggled.connect(lambda on: led.toggle_global(on))
        panel.segment_clicked.connect(
            lambda idx: led.toggle_segment(idx, not led.state.segment_on[idx]))
        panel.zone_selected.connect(self._on_zone_selected)
        panel.zone_toggled.connect(lambda zi, on: led.toggle_zone(zi, on))
        panel.carousel_changed.connect(lambda on: led.set_zone_sync(on))
        panel.carousel_zone_changed.connect(
            lambda zi, sel: led.set_zone_sync_zone(zi, sel))
        panel.carousel_interval_changed.connect(
            lambda secs: led.set_zone_sync_interval(secs))
        panel.clock_format_changed.connect(
            lambda is_24h: led.set_clock_format(is_24h))
        panel.week_start_changed.connect(
            lambda is_sun: led.set_week_start(is_sun))
        panel.temp_unit_changed.connect(self._on_temp_unit_changed)
        panel.disk_index_changed.connect(lambda idx: led.set_disk_index(idx))
        panel.memory_ratio_changed.connect(
            lambda ratio: led.set_memory_ratio(ratio))
        panel.test_mode_changed.connect(lambda on: led.set_test_mode(on))

    def _on_mode_changed(self, mode):
        led = self._led
        if not led:
            return
        led.set_mode(mode)
        if led.state.zones:
            led.set_zone_mode(self._panel.selected_zone, mode)

    def _on_color_changed(self, r, g, b):
        led = self._led
        if not led:
            return
        led.set_color(r, g, b)
        if led.state.zones:
            led.set_zone_color(self._panel.selected_zone, r, g, b)

    def _on_brightness_changed(self, val):
        led = self._led
        if not led:
            return
        led.set_brightness(val)
        if led.state.zones:
            led.set_zone_brightness(self._panel.selected_zone, val)

    def _on_zone_selected(self, zone_index):
        led = self._led
        if not led or not led.state.zones:
            return
        led.set_selected_zone(zone_index)
        zones = led.state.zones
        if 0 <= zone_index < len(zones):
            z = zones[zone_index]
            self._panel.load_zone_state(
                zone_index, z.mode.value, z.color, z.brightness, z.on)

    def _on_tick(self):
        if not (self._led and self._active):
            return
        result = self._led.tick()
        display_colors = result.get('display_colors')
        if display_colors is not None:
            self._panel.set_led_colors(display_colors)

    def update_from_metrics(self, metrics) -> None:
        if not self._led:
            return
        self._led.update_metrics(metrics)
        self._panel.update_metrics(metrics)


# =============================================================================
# Screencast Handler
# =============================================================================

class ScreencastHandler:
    """Mediator for screencast (screen capture -> LCD)."""

    def __init__(self, parent: QWidget, on_frame):
        self._on_frame = on_frame
        self._active = False
        self._x = 0
        self._y = 0
        self._w = 0
        self._h = 0
        self._border = True
        self._pipewire_cast = None
        self._lcd_w = 320
        self._lcd_h = 320

        self._timer = QTimer(parent)
        self._timer.timeout.connect(self._tick)

    @property
    def active(self) -> bool:
        return self._active

    def set_lcd_size(self, w: int, h: int):
        self._lcd_w = w
        self._lcd_h = h

    def toggle(self, enabled: bool):
        self._active = enabled
        if enabled:
            from .screen_capture import is_wayland
            if is_wayland() and self._pipewire_cast is None:
                self._try_start_pipewire()
            self._timer.start(150)
        else:
            self._timer.stop()
            self._stop_pipewire()

    def stop(self):
        self._timer.stop()
        self._active = False

    def set_params(self, x: int, y: int, w: int, h: int):
        self._x, self._y, self._w, self._h = x, y, w, h

    def set_border(self, visible: bool):
        self._border = visible

    def cleanup(self):
        self._timer.stop()
        self._stop_pipewire()

    def _try_start_pipewire(self):
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
        if not self._active or self._w <= 0 or self._h <= 0:
            return
        from PIL import Image as PILImage
        pil_img = None

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

        if pil_img is None:
            from .base import pixmap_to_pil
            from .screen_capture import grab_screen_region
            pixmap = grab_screen_region(self._x, self._y, self._w, self._h)
            if pixmap.isNull():
                return
            pil_img = pixmap_to_pil(pixmap)

        pil_img = pil_img.resize(
            (self._lcd_w, self._lcd_h), PILImage.Resampling.LANCZOS)
        self._on_frame(pil_img)


# =============================================================================
# TRCCApp — Main Window (C# Form1 equivalent)
# =============================================================================

class TRCCApp(QMainWindow):
    """Main TRCC window — thin shell like C# Form1.

    Owns window chrome, tray, device sidebar, panel stack.
    Creates one handler per connected device via _handlers dict
    (C# formDeviceArray equivalent).
    """

    _handshake_done = Signal(object, object)
    _instance: TRCCApp | None = None

    def __new__(cls, *args, **kwargs):
        if cls._instance is not None:
            raise RuntimeError("TRCCApp is a singleton — use instance()")
        inst = super().__new__(cls)
        cls._instance = inst
        return inst

    @classmethod
    def instance(cls) -> TRCCApp | None:
        return cls._instance

    def __init__(self, data_dir: Path | None = None, decorated: bool = False):
        super().__init__()

        self._decorated = decorated
        self._drag_pos = None
        self._force_quit = False
        from ..adapters.infra.data_repository import USER_DATA_DIR
        self._data_dir = data_dir or Path(USER_DATA_DIR)

        self.setWindowTitle("TRCC Linux - Thermalright LCD Control Center")
        self.setFixedSize(Sizes.WINDOW_W, Sizes.WINDOW_H)
        if not decorated:
            self.setWindowFlags(
                Qt.WindowType.FramelessWindowHint | Qt.WindowType.Window)

        # Per-device handlers (C# formDeviceArray)
        self._lcd_handler: LCDHandler | None = None
        self._active_device_key = ''
        self._handshake_pending = False  # guard against duplicate handshakes

        # Pixmap refs to prevent GC
        self._pixmap_refs: list = []

        # IPC server (set by run_app after window creation)
        from ..ipc import IPCServer
        self._ipc_server: IPCServer | None = None

        # Build UI
        self._apply_dark_theme()
        self._setup_ui()

        # Build initial display controller for the default resolution
        self._build_lcd_handler()

        # LED handler
        self._led = LEDHandler(self.uc_led_control, self._on_temp_unit_changed)

        # Screencast handler
        self._screencast = ScreencastHandler(self, self._on_screencast_frame)

        # Connect widget signals
        self._connect_view_signals()

        # Metrics mediator
        self._setup_mediator()

        # Restore temp unit
        saved_unit = settings.temp_unit
        if self._lcd_handler:
            self._lcd_handler.display.set_overlay_temp_unit(saved_unit)
        self.uc_system_info.set_temp_unit(saved_unit)
        self.uc_led_control.set_temp_unit(saved_unit)
        if saved_unit == 1:
            self.uc_about._set_temp('F')

        # Autostart
        autostart_state = ensure_autostart()
        self.uc_about._autostart = autostart_state
        self.uc_about.startup_btn.setChecked(autostart_state)

        # System tray
        self._setup_systray()

        # Sleep monitor
        self._setup_sleep_monitor()

        # Handshake signal
        self._handshake_done.connect(self._on_handshake_done)

        # Device poll timer
        self._device_timer = self._make_timer(self._on_device_poll)
        self._on_device_poll()
        self._device_timer.start(5000)

    def _build_lcd_handler(self) -> None:
        """Build LCDDevice + LCDHandler for initial resolution."""
        from ..adapters.render.qt import QtRenderer
        display = (ControllerBuilder()
            .with_renderer(QtRenderer())
            .with_data_dir(self._data_dir)
            .build_lcd())

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
        self._lcd_handler = LCDHandler(
            display, widgets, self._make_timer, self._data_dir,
            is_visible_fn=lambda: not self.isMinimized())

    # ── Timers ─────────────────────────────────────────────────────

    def _make_timer(self, callback, *, single_shot: bool = False) -> QTimer:
        timer = QTimer(self)
        if single_shot:
            timer.setSingleShot(True)
        timer.timeout.connect(callback)
        return timer

    # ── Dark theme ─────────────────────────────────────────────────

    def _apply_dark_theme(self):
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(Colors.WINDOW_BG))
        palette.setColor(QPalette.ColorRole.WindowText, QColor(Colors.WINDOW_TEXT))
        palette.setColor(QPalette.ColorRole.Base, QColor(Colors.BASE_BG))
        palette.setColor(QPalette.ColorRole.Text, QColor(Colors.TEXT))
        palette.setColor(QPalette.ColorRole.Button, QColor(Colors.BUTTON_BG))
        palette.setColor(QPalette.ColorRole.ButtonText, QColor(Colors.BUTTON_TEXT))
        self.setPalette(palette)

    # ── System tray ────────────────────────────────────────────────

    def _setup_systray(self):
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

    def _on_sleep_signal(self, sleeping: bool):
        if sleeping:
            log.info("System suspending — stopping timers")
            self._device_timer.stop()
            if self._lcd_handler:
                self._lcd_handler.stop_timers()
            self._mediator.stop()
            self._screencast.stop()
        else:
            log.info("System resuming — invalidating USB handles")
            from ..adapters.device.factory import DeviceProtocolFactory
            DeviceProtocolFactory.close_all()
            self._device_timer.start(5000)
            self._mediator.ensure_running()
            self._on_device_poll()

    def _on_tray_activated(self, reason):
        if reason == QSystemTrayIcon.ActivationReason.Trigger:
            self._toggle_visibility()

    def _toggle_visibility(self):
        if self.isVisible():
            self.hide()
        else:
            self.show()
            self.activateWindow()
            self.raise_()

    def _quit_app(self):
        self._force_quit = True
        self.close()

    # ── UI Setup ───────────────────────────────────────────────────

    def _setup_ui(self):
        """Build main UI layout matching Windows TRCC."""
        central = QWidget()
        self.setCentralWidget(central)

        pix_form1 = set_background_pixmap(central, Assets.FORM1_BG,
            width=Sizes.WINDOW_W, height=Sizes.WINDOW_H,
            fallback_style=f"background-color: {Colors.WINDOW_BG};")
        if pix_form1:
            self._pixmap_refs.append(pix_form1)

        # Device sidebar
        self.uc_device = UCDevice(central)
        self.uc_device.setGeometry(*Layout.SIDEBAR)

        # FormCZTV container
        self.form_container = QWidget(central)
        self.form_container.setGeometry(*Layout.FORM_CONTAINER)

        form_bg = Assets.get_localized(Assets.FORM_CZTV_BG, settings.lang)
        pix = set_background_pixmap(self.form_container, form_bg,
            fallback_style=f"background-color: {Colors.WINDOW_BG};")
        if pix:
            self._pixmap_refs.append(pix)

        # Preview
        self.uc_preview = UCPreview(
            settings.width, settings.height, self.form_container)
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

        # Theme panels
        self.panel_stack = QStackedWidget(self.form_container)
        self.panel_stack.setGeometry(*Layout.PANEL_STACK)

        # C# ButtonNewMode order: 1=Local, 2=CloudBG, 3=Settings, 4=CloudMasks
        self.uc_theme_local = UCThemeLocal()              # panel 0
        self._set_panel_bg(self.uc_theme_local,
            Assets.get_localized(Assets.THEME_LOCAL_BG, settings.lang))
        self.panel_stack.addWidget(self.uc_theme_local)

        self.uc_theme_web = UCThemeWeb()                  # panel 1
        self._set_panel_bg(self.uc_theme_web,
            Assets.get_localized(Assets.THEME_WEB_BG, settings.lang))
        self.panel_stack.addWidget(self.uc_theme_web)

        self.uc_theme_setting = UCThemeSetting()          # panel 2
        self.panel_stack.addWidget(self.uc_theme_setting)

        self.uc_theme_mask = UCThemeMask()                # panel 3
        self._set_panel_bg(self.uc_theme_mask,
            Assets.get_localized(Assets.THEME_MASK_BG, settings.lang))
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
        self.uc_about = UCAbout(parent=central)
        self.uc_about.setGeometry(*Layout.FORM_CONTAINER)
        self.uc_about.setVisible(False)

        # Sensor enumerator
        self._system_sensors = SensorEnumerator()
        self._system_sensors.discover()

        # System info dashboard
        self.uc_system_info = UCSystemInfo(self._system_sensors, parent=central)
        self.uc_system_info.setGeometry(*Layout.SYSINFO_PANEL)
        self.uc_system_info.setVisible(False)

        # LED panel
        self.uc_led_control = UCLedControl(central)
        self.uc_led_control.setGeometry(*Layout.FORM_CONTAINER)
        self.uc_led_control.setVisible(False)

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

        # Theme directories
        self._init_theme_directories()

    def _set_panel_bg(self, widget: QWidget, asset_name: str):
        pix = set_background_pixmap(widget, asset_name)
        if pix:
            self._pixmap_refs.append(pix)

    def _create_mode_tabs(self):
        self.mode_buttons = []
        # C# visual x-order: BDZT(542)=Local, YDMB(612)=Masks, YDZT(682)=CloudBG, ZTSZ(882)=Settings
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
            btn.clicked.connect(
                lambda checked, idx=panel_idx: self._show_panel(idx))
            self.mode_buttons.append(btn)
        if self.mode_buttons:
            self.mode_buttons[0].setChecked(True)

    def _create_bottom_controls(self):
        # Rotation combo
        self.rotation_combo = QComboBox(self.form_container)
        self.rotation_combo.setGeometry(*Layout.ROTATION_COMBO)
        self.rotation_combo.addItems(["0\u00b0", "90\u00b0", "180\u00b0", "270\u00b0"])
        self.rotation_combo.setStyleSheet(
            "QComboBox { background-color: #2A2A2A; color: white; border: 1px solid #555;"
            " font-size: 10px; padding-left: 5px; }"
            "QComboBox::drop-down { border: none; width: 20px; }"
            "QComboBox QAbstractItemView { background-color: #2A2A2A; color: white;"
            " selection-background-color: #4A6FA5; }")
        self.rotation_combo.setToolTip("LCD rotation")
        self.rotation_combo.currentIndexChanged.connect(self._on_rotation_change)

        # Brightness/split button
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

        # Theme name input
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

        # Save/Export/Import buttons
        self.save_btn = self._icon_btn(
            *Layout.SAVE_BTN, Assets.BTN_SAVE, "S")
        self.save_btn.setToolTip("Save theme")
        self.save_btn.clicked.connect(self._on_save_clicked)

        self.export_btn = self._icon_btn(
            *Layout.EXPORT_BTN, Assets.BTN_EXPORT, "Exp")
        self.export_btn.setToolTip("Export theme to file")
        self.export_btn.clicked.connect(self._on_export_clicked)

        self.import_btn = self._icon_btn(
            *Layout.IMPORT_BTN, Assets.BTN_IMPORT, "Imp")
        self.import_btn.setToolTip("Import theme from file")
        self.import_btn.clicked.connect(self._on_import_clicked)

    def _icon_btn(self, x, y, w, h, icon_name, fallback_text):
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
        help_btn = create_image_button(
            self.form_container, *Layout.HELP_BTN,
            Assets.BTN_HELP, None, fallback_text="?")
        help_btn.setToolTip("Help")
        help_btn.clicked.connect(self._on_help_clicked)

        close_btn = create_image_button(
            self.form_container, *Layout.CLOSE_BTN,
            Assets.BTN_POWER, Assets.BTN_POWER_HOVER, fallback_text="X")
        close_btn.setToolTip("Close")
        close_btn.clicked.connect(self.close)

    def _apply_settings_backgrounds(self):
        s = self.uc_theme_setting
        for panel, base in [
            (s.mask_panel, '\u5e03\u5c40\u8499\u677f'),
            (s.background_panel, '\u80cc\u666f\u663e\u793a'),
            (s.screencast_panel, '\u6295\u5c4f\u663e\u793axy'),
            (s.video_panel, '\u64ad\u653e\u5668'),
            (s.overlay_grid, '\u5185\u5bb9'),
            (s.color_panel, '\u53c2\u6570\u9762\u677f'),
        ]:
            bg = Assets.get_localized(f'P01{base}.png', settings.lang)
            self._set_panel_bg(panel, bg)

    def _init_theme_directories(self):
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

    # ── View Navigation ────────────────────────────────────────────

    def _show_panel(self, index):
        # Panel stack: 0=Local, 1=CloudBG, 2=Settings, 3=Masks
        # Button order: 0=Local, 1=Masks, 2=CloudBG, 3=Settings
        self.panel_stack.setCurrentIndex(index)
        panel_to_button = {0: 0, 1: 2, 2: 3, 3: 1}
        active_btn = panel_to_button.get(index, 0)
        for i, btn in enumerate(self.mode_buttons):
            btn.setChecked(i == active_btn)

    def _show_view(self, view: str):
        self.form_container.setVisible(view == 'form')
        self.uc_about.setVisible(view == 'about')
        self.uc_system_info.setVisible(view == 'sysinfo')
        self.uc_led_control.setVisible(view == 'led')

        show_form1_btns = (view == 'sysinfo')
        self.form1_close_btn.setVisible(show_form1_btns)
        self.form1_help_btn.setVisible(show_form1_btns)

        if view == 'sysinfo':
            self.uc_system_info.start_updates()
        else:
            self.uc_system_info.stop_updates()

        if view != 'led' and self._led.active:
            self._led.stop()

    # ── Signal Wiring ──────────────────────────────────────────────

    def _connect_view_signals(self):
        # Device
        self.uc_device.device_selected.connect(self._on_device_widget_clicked)
        self.uc_device.home_clicked.connect(lambda: self._show_view('sysinfo'))
        self.uc_device.about_clicked.connect(lambda: self._show_view('about'))

        # Theme panels
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

        # Preview
        self.uc_preview.delegate.connect(self._on_preview_delegate)
        self.uc_preview.element_drag_start.connect(self._on_drag_start)
        self.uc_preview.element_drag_move.connect(self._on_drag_move)
        self.uc_preview.element_drag_end.connect(lambda: None)
        self.uc_preview.element_nudge.connect(self._on_nudge)
        self._drag_origin_x = 0
        self._drag_origin_y = 0
        self._drag_elem_x = 0
        self._drag_elem_y = 0

        # Settings panel
        self.uc_theme_setting.background_changed.connect(self._on_background_toggle)
        self.uc_theme_setting.screencast_changed.connect(self._on_screencast_toggle)
        self.uc_theme_setting.delegate.connect(self._on_settings_delegate)
        self.uc_theme_setting.overlay_grid.add_requested.connect(
            self._on_overlay_add_requested)
        self.uc_theme_setting.overlay_grid.toggle_changed.connect(
            self._on_overlay_toggle)
        self.uc_theme_setting.overlay_grid.element_selected.connect(
            self._on_element_flash)
        self.uc_theme_setting.screencast_params_changed.connect(
            lambda x, y, w, h: self._screencast.set_params(x, y, w, h))
        self.uc_theme_setting.screencast_panel.border_toggled.connect(
            self._screencast.set_border)
        self.uc_theme_setting.capture_requested.connect(self._on_capture_requested)
        self.uc_theme_setting.eyedropper_requested.connect(
            self._on_eyedropper_requested)

        # Image/video cutters
        self.uc_image_cut.image_cut_done.connect(self._on_image_cut_done)
        self.uc_video_cut.video_cut_done.connect(self._on_video_cut_done)

        # Activity sidebar
        self.uc_activity_sidebar.sensor_clicked.connect(
            self._on_sensor_element_add)

        # About/LED close
        self.uc_about.close_requested.connect(
            lambda: (self._show_view('form'),
                     self.uc_device.restore_device_selection()))
        self.uc_led_control.close_requested.connect(
            lambda: (self._show_view('form'),
                     self.uc_device.restore_device_selection()))
        self.uc_about.language_changed.connect(self._set_language)
        self.uc_about.temp_unit_changed.connect(self._on_temp_unit_changed)
        self.uc_about.hdd_toggle_changed.connect(self._on_hdd_toggle_changed)
        self.uc_about.refresh_changed.connect(self._on_refresh_changed)

    # ── Device Selection ───────────────────────────────────────────

    def _on_device_widget_clicked(self, device_info: dict):
        device = DeviceInfo.from_dict(device_info)
        if device.implementation == 'hid_led':
            if self._lcd_handler:
                self._lcd_handler.stop_timers()
            self._screencast.stop()
            self._led.show(device)
            self._show_view('led')
            self._mediator.ensure_running()
            # Wire IPC LED device
            led = self._led.led_port
            if self._ipc_server and led:
                from ..core.led_device import LEDDevice as LEDDev
                self._ipc_server.led = LEDDev(svc=led.service)
        else:
            if self._led.active:
                self._led.stop()
            self._show_view('form')
            self._on_device_selected(device)

    def _on_device_selected(self, device: DeviceInfo):
        log.info("Device selected: %s [%04X:%04X] %s %s",
                 device.path, device.vid, device.pid,
                 device.protocol, device.resolution)
        self._active_device_key = Settings.device_config_key(
            device.device_index, device.vid, device.pid)

        self.uc_preview.set_status(f"Device: {device.path}")

        # Resolution (0,0) = needs handshake
        w, h = device.resolution
        if (w, h) == (0, 0):
            self.uc_preview.set_status("Connecting to device...")
            self._start_handshake(device)
            return

        if self._lcd_handler:
            self._lcd_handler.display.select_device(device)
            self._lcd_handler.apply_device_config(device, w, h)
            self._update_ldd_icon()
            # Show info module if configured
            if Settings.show_info_module():
                self.uc_info_module.setVisible(True)
            self._mediator.ensure_running()

    def _start_handshake(self, device: DeviceInfo):
        if self._handshake_pending:
            log.debug("Handshake already in progress, skipping")
            return
        self._handshake_pending = True

        import threading
        def worker():
            try:
                from ..adapters.device.factory import DeviceProtocolFactory
                protocol = DeviceProtocolFactory.get_protocol(device)
                result = protocol.handshake()
                if result:
                    resolution = getattr(result, 'resolution', None)
                    fbl = getattr(result, 'fbl', None) or getattr(
                        result, 'model_id', None)
                    self._handshake_done.emit(device, (resolution, fbl))
                else:
                    self._handshake_done.emit(device, None)
            except Exception as e:
                log.warning("Background handshake failed: %s", e)
                self._handshake_done.emit(device, None)
        threading.Thread(target=worker, daemon=True).start()

    def _on_handshake_done(self, device: DeviceInfo, data: tuple | None):
        self._handshake_pending = False
        if not data:
            self.uc_preview.set_status("Handshake failed — replug device")
            return
        resolution, fbl = data
        if not resolution or resolution == (0, 0):
            self.uc_preview.set_status("Handshake failed — no resolution")
            return
        log.info("Handshake OK: %s -> %s (FBL=%s)", device.path, resolution, fbl)
        device.resolution = resolution
        if fbl:
            device.fbl_code = fbl
            self._resolve_device_identity(device, fbl)
        # use_jpeg is computed from protocol + fbl — no propagation needed
        self._on_device_selected(device)

    def _resolve_device_identity(self, device: DeviceInfo, fbl: int):
        from ..core.models import get_button_image
        btn_img = get_button_image(fbl)
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
        Settings.save_device_setting(
            self._active_device_key, 'resolved_button_image', btn_img)
        Settings.save_device_setting(
            self._active_device_key, 'resolved_product', product)

    # ── Device Poll ────────────────────────────────────────────────

    def _on_device_poll(self):
        try:
            devices = find_lcd_devices()
            self.uc_device.update_devices(devices)

            # Auto-select first device
            has_lcd = self._lcd_handler and self._lcd_handler.display.connected
            if devices and not has_lcd and not self._led.active:
                device = DeviceInfo.from_dict(devices[0])
                if device.implementation == 'hid_led':
                    self._led.show(device)
                    self._show_view('led')
                else:
                    self._on_device_selected(device)

            has_device = has_lcd or self._led.active
            interval = 15000 if has_device else 5000
            if self._device_timer.interval() != interval:
                self._device_timer.start(interval)
        except Exception as e:
            log.error("Device poll error: %s", e)

    # ── Theme Event Handlers ───────────────────────────────────────

    def _on_local_theme_clicked(self, theme_info):
        if self._lcd_handler:
            self._lcd_handler.select_theme_from_path(Path(theme_info.path))
            self._mediator.ensure_running()
            name = theme_info.name
            if name.startswith('Custom_'):
                name = name[len('Custom_'):]
            self.theme_name_input.setText(name)

    def _on_cloud_theme_clicked(self, theme_info):
        if self._lcd_handler:
            self._lcd_handler.select_cloud_theme(theme_info)
            self._mediator.ensure_running()

    def _on_mask_clicked(self, mask_info):
        if self._lcd_handler:
            self._lcd_handler.apply_mask(mask_info)

    def _on_local_delegate(self, cmd, info, data):
        if cmd == UCThemeLocal.CMD_SLIDESHOW and self._lcd_handler:
            self._lcd_handler.on_slideshow_delegate()

    def _on_delete_theme(self, theme_info):
        from PySide6.QtWidgets import QMessageBox
        reply = QMessageBox.question(
            self, "Delete Theme", f"Delete theme '{theme_info.name}'?",
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No)
        if reply == QMessageBox.StandardButton.Yes:
            self.uc_theme_local.delete_theme(theme_info)
            if (self._lcd_handler
                    and self._lcd_handler.display.current_theme_path
                    and str(self._lcd_handler.display.current_theme_path) == theme_info.path):
                self._lcd_handler.display.current_image = None
                self.uc_preview.set_image(None)
            self.uc_preview.set_status(f"Deleted: {theme_info.name}")

    # ── Settings Delegates ─────────────────────────────────────────

    def _on_settings_delegate(self, cmd, info, data):
        if cmd == UCThemeSetting.CMD_BACKGROUND_LOAD_IMAGE:
            self._on_load_image_clicked()
        elif cmd == UCThemeSetting.CMD_BACKGROUND_LOAD_VIDEO:
            self._on_load_video_clicked()
        elif cmd == UCThemeSetting.CMD_MASK_TOGGLE:
            if self._lcd_handler:
                self._lcd_handler.display.set_overlay_mask_visible(info)
                self._lcd_handler._render_and_send()
        elif cmd == UCThemeSetting.CMD_MASK_LOAD:
            self._show_panel(3)
        elif cmd == UCThemeSetting.CMD_MASK_CLOUD:
            self._show_panel(3)  # C# buttonYDMB_Click — cloud masks
        elif cmd == UCThemeSetting.CMD_VIDEO_LOAD:
            self._on_load_video_clicked()
        elif cmd == 51:  # C# buttonYDZT_Click — switch to cloud theme panel
            self._show_panel(1)
        elif cmd == UCThemeSetting.CMD_VIDEO_TOGGLE:
            self._on_video_display_toggle(info)
        elif cmd == UCThemeSetting.CMD_OVERLAY_CHANGED:
            if self._lcd_handler:
                self._lcd_handler.on_overlay_changed(
                    info if isinstance(info, dict) else {})

    def _on_preview_delegate(self, cmd, info, data):
        if not self._lcd_handler:
            return
        if cmd == UCPreview.CMD_VIDEO_PLAY_PAUSE:
            self._lcd_handler.play_pause()
        elif cmd == UCPreview.CMD_VIDEO_SEEK:
            self._lcd_handler.seek(info)
        elif cmd == UCPreview.CMD_VIDEO_FIT_WIDTH:
            self._lcd_handler.set_video_fit_mode('width')
        elif cmd == UCPreview.CMD_VIDEO_FIT_HEIGHT:
            self._lcd_handler.set_video_fit_mode('height')

    # ── Background / Screencast / Video Toggles ────────────────────
    # C# mutual exclusion: each mode sets the other two to false.
    # UI panels already disable each other in _on_mode_changed;
    # these handlers clean up the backend state of the displaced mode.

    def _on_background_toggle(self, enabled: bool):
        if not self._lcd_handler:
            return
        if enabled:
            # C# case 1: myTpxs=false, mySpxs=false
            self._screencast.toggle(False)
        self._lcd_handler.on_background_toggle(enabled)
        self._mediator.ensure_running()

    def _on_screencast_toggle(self, enabled: bool):
        if not self._lcd_handler:
            return
        if enabled:
            # C# case 2: myBjxs=false, mySpxs=false
            self._lcd_handler.stop_timers()
            self._lcd_handler.display.stop_video()
            self._lcd_handler.is_background_active = False
            w, h = self._lcd_handler.display.lcd_size
            self._screencast.set_lcd_size(w, h)
        self._screencast.toggle(enabled)
        self.uc_preview.set_status(
            f"Screencast: {'On' if enabled else 'Off'}")

    def _on_video_display_toggle(self, enabled):
        if not self._lcd_handler:
            return
        if enabled:
            # C# case 3: myBjxs=false, myTpxs=false
            self._screencast.toggle(False)
            self._lcd_handler.is_background_active = False
            if self._lcd_handler.display.video_has_frames():
                self._lcd_handler.play_pause()
        else:
            self._lcd_handler.stop_video()

    def _on_screencast_frame(self, pil_img):
        if self._lcd_handler:
            self._lcd_handler.on_screencast_frame(pil_img)

    # ── File Dialogs ───────────────────────────────────────────────

    def _on_load_video_clicked(self):
        web_dir = str(settings.web_dir) if settings.web_dir else ""
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Video", web_dir,
            "Video Files (*.mp4 *.avi *.mov *.gif);;All Files (*)")
        if path and self._lcd_handler:
            w, h = self._lcd_handler.display.lcd_size
            self.uc_video_cut.set_resolution(w, h)
            self.uc_video_cut.load_video(path)
            self._show_cutter('video')

    def _on_load_image_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Open Image", "",
            "Image Files (*.png *.jpg *.jpeg *.bmp);;All Files (*)")
        if path and self._lcd_handler:
            try:
                from PIL import Image as PILImage
                pil_img = PILImage.open(path)
                w, h = self._lcd_handler.display.lcd_size
                self.uc_image_cut.load_image(pil_img, w, h)
                self._show_cutter('image')
            except Exception as e:
                self.uc_preview.set_status(f"Error: {e}")

    def _on_save_clicked(self):
        name = self.theme_name_input.text().strip()
        if not name:
            self.uc_preview.set_status("Enter a theme name first")
            return
        if self._lcd_handler:
            self._lcd_handler.save_theme(name)

    def _on_export_clicked(self):
        path, _ = QFileDialog.getSaveFileName(
            self, "Export Theme", "",
            "Theme files (*.tr);;JSON (*.json);;All Files (*)")
        if path and self._lcd_handler:
            self._lcd_handler.export_config(Path(path))

    def _on_import_clicked(self):
        path, _ = QFileDialog.getOpenFileName(
            self, "Import Theme", "",
            "Theme files (*.tr);;JSON (*.json);;All Files (*)")
        if path and self._lcd_handler:
            self._lcd_handler.import_config(Path(path))

    # ── Image/Video Cutters ────────────────────────────────────────

    def _show_cutter(self, kind: str):
        self.uc_preview.setVisible(False)
        self.uc_image_cut.setVisible(kind == 'image')
        self.uc_video_cut.setVisible(kind == 'video')
        (self.uc_image_cut if kind == 'image' else self.uc_video_cut).raise_()

    def _hide_cutters(self):
        self.uc_image_cut.setVisible(False)
        self.uc_video_cut.setVisible(False)
        self.uc_preview.setVisible(True)

    def _on_image_cut_done(self, result):
        self._hide_cutters()
        if result is not None and self._lcd_handler:
            # C# UpDateUCImageCut: kill video, set static image
            self._lcd_handler.stop_video()
            self._lcd_handler.display.set_overlay_background(result)
            self._lcd_handler._render_and_send()
            self.uc_preview.set_status("Image loaded")
        else:
            self.uc_preview.set_status("Image crop cancelled")

    def _on_video_cut_done(self, zt_path):
        self._hide_cutters()
        if zt_path and self._lcd_handler:
            # C# UpDateUCVideoCut: load video, start animated playback
            self._lcd_handler.display.load_video(Path(zt_path))
            self._lcd_handler.display.play_video()
            interval = self._lcd_handler.display.video.interval
            self._lcd_handler._animation_timer.start(interval)
            self.uc_preview.set_playing(True)
            self.uc_preview.show_video_controls(True)
            self.uc_preview.set_status("Video loaded")
        else:
            self.uc_preview.set_status("Video cut cancelled")

    # ── Activity Sidebar / Overlay ─────────────────────────────────

    def _on_overlay_add_requested(self):
        self.uc_activity_sidebar.setVisible(True)
        self.uc_activity_sidebar.raise_()
        self._mediator.ensure_running()

    def _on_sensor_element_add(self, config):
        self.uc_theme_setting.overlay_grid.add_element(config)
        self.uc_activity_sidebar.setVisible(False)

    def _on_overlay_toggle(self, enabled):
        if self._lcd_handler:
            self._lcd_handler.display.enable_overlay(enabled)
            self._mediator.ensure_running()
        if self._active_device_key:
            cfg = Settings.get_device_config(self._active_device_key)
            overlay = cfg.get('overlay', {})
            overlay['enabled'] = enabled
            Settings.save_device_setting(
                self._active_device_key, 'overlay', overlay)

    def _on_element_flash(self, index: int, config: dict):
        if self._lcd_handler:
            self._lcd_handler.flash_element(index)

    # ── Drag / Nudge ───────────────────────────────────────────────

    def _on_drag_start(self, lcd_x: int, lcd_y: int):
        grid = self.uc_theme_setting.overlay_grid
        cfg = grid.get_selected_config()
        if cfg is None:
            # Auto-select nearest element to click position
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

    def _on_drag_move(self, lcd_x: int, lcd_y: int):
        cfg = self.uc_theme_setting.overlay_grid.get_selected_config()
        if cfg is None or not self._lcd_handler:
            return
        w, h = self._lcd_handler.display.lcd_size
        dx = lcd_x - self._drag_origin_x
        dy = lcd_y - self._drag_origin_y
        new_x = max(0, min(self._drag_elem_x + dx, w))
        new_y = max(0, min(self._drag_elem_y + dy, h))
        self.uc_theme_setting.color_panel.set_position(new_x, new_y)
        self.uc_theme_setting._on_position_changed(new_x, new_y)

    def _on_nudge(self, dx: int, dy: int):
        grid = self.uc_theme_setting.overlay_grid
        cfg = grid.get_selected_config()
        if cfg is None:
            return
        if not self._lcd_handler:
            return
        w, h = self._lcd_handler.display.lcd_size
        new_x = max(0, min(cfg.x + dx, w))
        new_y = max(0, min(cfg.y + dy, h))
        self.uc_theme_setting.color_panel.set_position(new_x, new_y)
        self.uc_theme_setting._on_position_changed(new_x, new_y)

    # ── Display Settings (rotation, brightness, split) ─────────────

    def _on_rotation_change(self, index):
        if self._lcd_handler:
            self._lcd_handler.set_rotation(index * 90)
            self.uc_preview.set_status(f"Rotation: {index * 90}\u00b0")

    def _on_ldd_click(self):
        if not self._lcd_handler:
            return
        h = self._lcd_handler
        if h.ldd_is_split:
            mode = (h.split_mode % 3) + 1
            h.set_split_mode(mode)
            self._update_ldd_icon()
            self.uc_preview.set_status(f"Split mode: {mode}")
        else:
            level = (h.brightness_level % 3) + 1
            h.set_brightness(level)
            self._update_ldd_icon()
            percent = {1: 25, 2: 50, 3: 100}[level]
            self.uc_preview.set_status(
                f"Brightness: L{level} ({percent}%)")

    def _update_ldd_icon(self):
        if not self._lcd_handler:
            return
        h = self._lcd_handler
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

    # ── Global Settings ────────────────────────────────────────────

    def _on_temp_unit_changed(self, unit: str):
        temp_int = 1 if unit == 'F' else 0
        if self._lcd_handler:
            self._lcd_handler.display.set_overlay_temp_unit(temp_int)
        self.uc_system_info.set_temp_unit(temp_int)
        self.uc_led_control.set_temp_unit(temp_int)
        self._led.set_temp_unit(unit)
        settings.set_temp_unit(temp_int)
        self.uc_preview.set_status(f"Temperature: \u00b0{unit}")

    def _on_hdd_toggle_changed(self, on: bool):
        settings.set_hdd_enabled(on)
        self.uc_preview.set_status(
            f"HDD info: {'Enabled' if on else 'Disabled'}")

    def _on_refresh_changed(self, interval: int):
        self._mediator.set_interval(interval * 1000)
        self.uc_preview.set_status(f"Refresh: {interval}s")

    def _set_language(self, lang: str):
        settings.lang = lang
        self._set_panel_bg(self.form_container,
            Assets.get_localized(Assets.FORM_CZTV_BG, settings.lang))
        self._set_panel_bg(self.uc_theme_local,
            Assets.get_localized(Assets.THEME_LOCAL_BG, settings.lang))
        self._set_panel_bg(self.uc_theme_web,
            Assets.get_localized(Assets.THEME_WEB_BG, settings.lang))
        self._set_panel_bg(self.uc_theme_mask,
            Assets.get_localized(Assets.THEME_MASK_BG, settings.lang))
        self._apply_settings_backgrounds()
        self.uc_about.sync_language()
        self.uc_led_control.apply_localized_background()

    def _on_help_clicked(self):
        import webbrowser
        webbrowser.open(
            'https://github.com/Lexonight1/thermalright-trcc-linux'
            '/blob/main/doc/TROUBLESHOOTING.md')

    def _on_capture_requested(self):
        from .screen_capture import ScreenCaptureOverlay
        self._capture_overlay = ScreenCaptureOverlay()
        self._capture_overlay.captured.connect(self._on_screen_captured)
        self._capture_overlay.show()

    def _on_screen_captured(self, pil_img):
        self._capture_overlay = None
        if pil_img is None or not self._lcd_handler:
            return
        w, h = self._lcd_handler.display.lcd_size
        self.uc_image_cut.load_image(pil_img, w, h)
        self._show_cutter('image')

    def _on_eyedropper_requested(self):
        from .eyedropper import EyedropperOverlay
        self._eyedropper_overlay = EyedropperOverlay()
        self._eyedropper_overlay.color_picked.connect(self._eyedropper_pick)
        self._eyedropper_overlay.cancelled.connect(
            lambda: setattr(self, '_eyedropper_overlay', None))
        self._eyedropper_overlay.show()

    def _eyedropper_pick(self, r, g, b):
        self._eyedropper_overlay = None
        self.uc_theme_setting.color_panel._apply_color(r, g, b)

    # ── Carousel Config ────────────────────────────────────────────

    def _load_carousel_config(self, theme_dir: Path):
        config_path = theme_dir / 'Theme.dc'
        config = read_carousel_config(str(config_path))
        if config is None:
            return
        all_themes = self.uc_theme_local._all_themes
        slideshow_names = []
        for idx in config.theme_indices:
            if 0 <= idx < len(all_themes):
                slideshow_names.append(all_themes[idx].name)
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

    # ── MetricsMediator ────────────────────────────────────────────

    def _setup_mediator(self):
        from .metrics_mediator import MetricsMediator
        self._mediator = MetricsMediator(self)
        self._mediator.subscribe(
            self._on_overlay_tick, period=1,
            guard=lambda: (
                (self._lcd_handler is not None
                 and self._lcd_handler.display.is_overlay_enabled)
                or (self._lcd_handler is not None
                    and self._lcd_handler.is_background_active)))
        self._mediator.subscribe(
            self._on_led_metrics, period=1,
            guard=lambda: self._led.active)
        self._mediator.subscribe(
            self.uc_info_module.update_from_metrics, period=3,
            guard=lambda: self.uc_info_module.isVisible())
        self._mediator.subscribe(
            self.uc_activity_sidebar.update_from_metrics, period=1,
            guard=lambda: self.uc_activity_sidebar.isVisible())

    def _on_overlay_tick(self, metrics) -> None:
        if self._lcd_handler:
            self._lcd_handler.on_overlay_tick(metrics)

    def _on_led_metrics(self, metrics) -> None:
        if self._led.has_controller:
            self._led.update_from_metrics(metrics)

    # ── Window Events ──────────────────────────────────────────────

    def hideEvent(self, event):
        super().hideEvent(event)
        self._device_timer.stop()

    def showEvent(self, event):
        super().showEvent(event)
        if not self._device_timer.isActive():
            self._device_timer.start(5000)
            self._on_device_poll()

    def mousePressEvent(self, event):
        if self._decorated or event.button() != Qt.MouseButton.LeftButton:
            return super().mousePressEvent(event)
        pos = event.position().toPoint()
        if pos.y() < 80 or (pos.x() < 180 and pos.y() < 95):
            self._drag_pos = (
                event.globalPosition().toPoint() - self.frameGeometry().topLeft())
        event.accept()

    def mouseMoveEvent(self, event):
        if self._drag_pos is not None:
            self.move(event.globalPosition().toPoint() - self._drag_pos)
        event.accept()

    def mouseReleaseEvent(self, event):
        self._drag_pos = None
        event.accept()

    def closeEvent(self, event):
        if (not self._force_quit
                and self._tray.isSystemTrayAvailable()
                and self._tray.isVisible()):
            event.ignore()
            self.hide()
            return

        # Full quit
        self._tray.hide()
        self._device_timer.stop()
        self._screencast.cleanup()
        self._mediator.stop()
        self._led.cleanup()
        self.uc_system_info.stop_updates()
        self.uc_info_module.stop_updates()
        self.uc_activity_sidebar.stop_updates()
        if self._lcd_handler:
            self._lcd_handler.cleanup()
        if self._ipc_server:
            self._ipc_server.shutdown()
        TRCCApp._instance = None
        event.accept()
        app = QApplication.instance()
        if app:
            app.quit()


# =============================================================================
# Entry point
# =============================================================================

def _lock_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / "trcc-linux.lock"


def _acquire_instance_lock() -> object | None:
    import fcntl
    try:
        fh = open(_lock_path(), "w")  # noqa: SIM115
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except OSError:
        return None


def _raise_existing_instance() -> None:
    import signal
    try:
        pid = int(_lock_path().read_text().strip())
        os.kill(pid, signal.SIGUSR1)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        pass


def run_app(data_dir: Path | None = None, decorated: bool = False,
            start_hidden: bool = False):
    """Run the TRCC application."""
    lock = _acquire_instance_lock()
    if lock is None:
        _raise_existing_instance()
        return 0

    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.services=false")
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"
    QApplication.setDesktopFileName("trcc-linux")
    app = QApplication(sys.argv)
    app.setQuitOnLastWindowClosed(False)
    app.setProperty("_instance_lock", lock)

    font = QFont("Microsoft YaHei", 10)
    if not font.exactMatch():
        font = QFont("Sans Serif", 10)
    app.setFont(font)

    window = TRCCApp(data_dir, decorated=decorated)

    # IPC server
    from ..core.lcd_device import LCDDevice
    from ..core.led_device import LEDDevice as LEDDev
    from ..ipc import IPCServer

    ipc_display = LCDDevice(
        device_svc=window._lcd_handler.display.device_service
        if window._lcd_handler else None)
    ipc_led = LEDDev()
    ipc_server = IPCServer(ipc_display, ipc_led)
    ipc_server.start()
    window._ipc_server = ipc_server

    # Frame capture for API preview
    if window._lcd_handler:
        window._lcd_handler.display.device_service.on_frame_sent = (
            ipc_server.capture_frame)

    # SIGUSR1 handler
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
