#!/usr/bin/env python3
"""
LED control panel (FormLED equivalent).

Full LED control UI matching Windows FormLED layout:
- Left side: Device preview (UCScreenLED circles or UCSevenSegment for HR10)
- Right side: Mode buttons, color wheel, RGB controls, presets, brightness
- Bottom: Zone selection buttons (for multi-zone devices)
- HR10-specific: Drive metrics panel, display selection, circulate mode

Layout coordinates from FormLED.cs InitializeComponent / FormLED.resx.
All LED devices (styles 1-13) use this single panel — matching Windows
FormLED.cs which is one form for all LED device types.
"""

from typing import Dict, List, Tuple

from PySide6.QtCore import QRect, Qt, QTimer, Signal
from PySide6.QtGui import QColor, QFont, QIntValidator, QPainter, QPalette, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QFrame,
    QLabel,
    QLineEdit,
    QPushButton,
    QSlider,
    QSpinBox,
    QWidget,
)

from ..core.models import HardwareMetrics
from .assets import Assets
from .base import set_background_pixmap
from .uc_color_wheel import UCColorWheel
from .uc_screen_led import UCScreenLED
from .uc_seven_segment import UCSevenSegment

# =========================================================================
# Layout constants (from FormLED.cs InitializeComponent, ClientSize 1274x800)
#
# C# uses FlatStyle.Flat + BorderSize=0 + BorderColor=transparent on ALL
# buttons.  The background PNG IS the UI; Qt widgets are transparent
# hitboxes placed at exact pixel coordinates on top.
# =========================================================================

PANEL_WIDTH = 1274
PANEL_HEIGHT = 800

# UCScreenLED preview — C#: ucScreenLED1 at (36, 128) 460x460
PREVIEW_X, PREVIEW_Y = 36, 128
PREVIEW_W, PREVIEW_H = 460, 460

# 7-segment preview (HR10)
SEG_PREVIEW_X, SEG_PREVIEW_Y = 30, 100
SEG_PREVIEW_W, SEG_PREVIEW_H = 500, 400

# Mode buttons — C#: buttonDSCL..FZLD at (590..1105, 227) each 93x62
MODE_Y = 227
MODE_X_START = 590
MODE_W, MODE_H = 93, 62
MODE_SPACING = 10

# Color wheel — C#: ucColorA1 at (617, 335) 216x216, shown for ALL styles
# Background image: D3旋钮 (216x216 rainbow ring)
WHEEL_X, WHEEL_Y = 617, 335
WHEEL_W, WHEEL_H = 216, 216

# RGB controls — C#: textBoxR/G/B at (926, 333/363/393) 47x19
#                     ucScrollAR/G/B at (976, 333/363/393) 190x20
# The background image provides R/G/B letter labels; no Qt labels needed.
RGB_SPINBOX_X = 926
RGB_Y_START = 333
RGB_SLIDER_X = 976
RGB_SLIDER_W = 190
RGB_SLIDER_H = 20
RGB_SPACING = 30
RGB_SPINBOX_W = 47

# Preset color buttons — C#: buttonC1-C8, exact X positions from InitializeComponent
PRESET_X_POSITIONS = [901, 935, 970, 1004, 1039, 1073, 1108, 1142]
PRESET_Y = 444
PRESET_SIZE = 24
# C# image assets: D3红/橙/黄/绿/湖/蓝/紫/白
PRESET_ASSETS = ['D3红', 'D3橙', 'D3黄', 'D3绿', 'D3湖', 'D3蓝', 'D3紫', 'D3白']

# Brightness slider — C#: ucScrollA at (976, 537) 190x20
BRIGHT_X = 976
BRIGHT_Y = 537
BRIGHT_W = 190

# °C/°F buttons — C#: buttonC at (699, 144) 14x14, buttonF at (759, 144)
TEMP_BTN_Y = 144
TEMP_BTN_C_X = 699
TEMP_BTN_F_X = 759
TEMP_BTN_SIZE = 14

# Temperature color legend (modes 5-6: temp/load reactive)
TEMP_LEGEND_X = 590
TEMP_LEGEND_Y = 480
TEMP_LEGEND_W = 560
TEMP_LEGEND_H = 18

# Drive metrics panel (HR10, bottom left below preview)
METRICS_X = 30
METRICS_Y = 540
METRICS_W = 500
METRICS_H = 130

# Display selection buttons (HR10, bottom right)
DISPLAY_SEL_X = 590
DISPLAY_SEL_Y = 710
DISPLAY_SEL_W = 120
DISPLAY_SEL_H = 45
DISPLAY_SEL_SPACING = 8

# Circulate checkbox (HR10)
CIRCULATE_X = 590
CIRCULATE_Y = 670

# Zone buttons — C#: button1-4 at (590/748/902/1058, 707) 140x50
# FormLEDInit repositions button5/6 and buttonN1-4 to button1.Top (=707)
# for ALL styles, so every variant ends up at Y=707.
ZONE_Y = 707
ZONE_X_POSITIONS = [590, 748, 902, 1058]
ZONE_W, ZONE_H = 140, 50

# Zone button C# image assets — 3 variants depending on style.
# button1-4 (D4模式1-4): styles 1, 2
# button5-6 (D4模式5-6): styles 3, 5, 6, 11
# buttonN1-4 (D4按钮1-4): styles 4, 7, 8, 10
ZONE_ASSETS_BTN14 = [('D4模式1', 'D4模式1a'), ('D4模式2', 'D4模式2a'),
                     ('D4模式3', 'D4模式3a'), ('D4模式4', 'D4模式4a')]
ZONE_ASSETS_BTN56 = [('D4模式5', 'D4模式5a'), ('D4模式6', 'D4模式6a')]
ZONE_ASSETS_BTNN = [('D4按钮1', 'D4按钮1a'), ('D4按钮2', 'D4按钮2a'),
                    ('D4按钮3', 'D4按钮3a'), ('D4按钮4', 'D4按钮4a')]
_ZONE_STYLE_TO_ASSETS: dict = {
    1: ZONE_ASSETS_BTN14, 2: ZONE_ASSETS_BTN14,
    3: ZONE_ASSETS_BTN56, 5: ZONE_ASSETS_BTN56,
    6: ZONE_ASSETS_BTN56, 11: ZONE_ASSETS_BTN56,
    4: ZONE_ASSETS_BTNN, 7: ZONE_ASSETS_BTNN,
    8: ZONE_ASSETS_BTNN, 10: ZONE_ASSETS_BTNN,
}

# Power/close button — C#: buttonPower at (1212, 24) 40x40
POWER_X, POWER_Y = 1212, 24
POWER_W, POWER_H = 40, 40

# Status label
STATUS_X = 590
STATUS_Y = 770
STATUS_W = 600

# --- HR10-specific overrides ---
HR10_BRIGHT_X = 590
HR10_BRIGHT_Y = 600
HR10_BRIGHT_W = 560

# Mode button labels (English)
MODE_LABELS = [
    "Static",
    "Breathing",
    "Colorful",
    "Rainbow",
    "Temp Link",
    "Load Link",
]

# Preset colors (from FormLED.cs buttonC1-C8)
PRESET_COLORS = [
    (255, 0, 42),     # Red-pink
    (255, 110, 0),    # Orange
    (255, 255, 0),    # Yellow
    (0, 255, 0),      # Green
    (0, 255, 255),    # Cyan
    (0, 91, 255),     # Blue
    (214, 0, 255),    # Purple
    (255, 255, 255),  # White
]

# Display selection options (HR10)
DISPLAY_METRICS = [
    ("Temp\n(\u00b0C/\u00b0F)", "temp"),
    ("Activity\n(%)", "activity"),
    ("Read Rate\n(MB/s)", "read"),
    ("Write Rate\n(MB/s)", "write"),
]

# Circulate interval range (seconds)
CIRCULATE_MIN_S = 2
CIRCULATE_MAX_S = 10
CIRCULATE_DEFAULT_S = 5

# Shared stylesheet fragments (used by multiple widgets in this module)
_STYLE_MUTED_LABEL = "color: #aaa; font-size: 12px;"

# Flat transparent button — matches C# FlatStyle.Flat + BorderSize=0.
# Background PNG has the button visual; Qt widget is an invisible hitbox.
_STYLE_FLAT_BTN = (
    "QPushButton { background: transparent; border: none; color: transparent; }"
    "QPushButton:hover { background: rgba(255, 255, 255, 20); }"
    "QPushButton:pressed { background: rgba(255, 255, 255, 40); }"
)
_STYLE_FLAT_CHECKABLE_BTN = (
    "QPushButton { background: transparent; border: none; color: transparent; }"
    "QPushButton:checked { background: rgba(33, 150, 243, 60); }"
    "QPushButton:hover { background: rgba(255, 255, 255, 20); }"
)
_STYLE_CHECKABLE_BTN = (
    "QPushButton { background: transparent; color: #aaa; border: none; "
    "font-size: 11px; }"
    "QPushButton:checked { background: rgba(33, 150, 243, 60); color: white; }"
    "QPushButton:hover { background: rgba(255, 255, 255, 20); }"
)


def _checkbox_image_style() -> str:
    """Build stylesheet for P点选框/P点选框A radio-style buttons (°C/°F, 24H/12H, etc.)."""
    normal = Assets.get('P点选框')
    active = Assets.get('P点选框A')
    if normal and active:
        return (
            f"QPushButton {{ border: none; "
            f"background-image: url({normal}); "
            f"background-repeat: no-repeat; }}"
            f"QPushButton:checked {{ "
            f"background-image: url({active}); }}"
        )
    return _STYLE_FLAT_CHECKABLE_BTN


class UCInfoImage(QWidget):
    """Sensor gauge widget matching Windows UCInfoImage.cs.

    Shows a background label image (P0M{n}.png), a progress bar fill
    (P环H{n}.png) drawn at variable width, and a numeric value overlay.
    Each widget is 240x30 pixels.

    From FormLED.cs: ucInfoImage1-6 display CPU/GPU temp/clock/usage.
    """

    def __init__(self, index: int, parent=None):
        super().__init__(parent)
        self.setFixedSize(240, 30)

        self._index = index  # 1-6
        self._value = 0.0
        self._text = "--"
        self._unit = ""
        self._mode = 1  # 1=temp/percent, 2=MHz/RPM

        # Load assets
        self._bg_pixmap = Assets.load_pixmap(f"P0M{index}.png")
        self._bar_pixmap = Assets.load_pixmap(f"P环H{index}.png")

    def set_value(self, value: float, text: str, unit: str = "") -> None:
        """Update displayed value.

        Args:
            value: Numeric value (0-100 for temp/percent, 0-5000 for MHz).
            text: Formatted display string (e.g. "65").
            unit: Unit suffix (e.g. "°C", "%", "MHz").
        """
        self._value = value
        self._text = text
        self._unit = unit
        self.update()

    def set_mode(self, mode: int) -> None:
        """Set value scaling mode: 1=temp/percent (0-100), 2=MHz/RPM (0-5000)."""
        self._mode = mode

    def paintEvent(self, event):
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)

        # Background image
        if self._bg_pixmap and not self._bg_pixmap.isNull():
            p.drawPixmap(0, 0, self._bg_pixmap)

        # Progress bar (x=35, y=22, max width=200, height=3)
        if self._bar_pixmap and not self._bar_pixmap.isNull():
            if self._mode == 1:  # temp or percent: 0-100 → 0-200px
                bar_w = max(0, min(200, int(self._value * 2)))
            else:  # MHz/RPM: 0-5000 → 0-200px
                bar_w = max(0, min(200, int(self._value / 25)))
            if bar_w > 0:
                p.drawPixmap(
                    35, 22, bar_w, 3,
                    self._bar_pixmap,
                    0, 0, bar_w, 3,
                )

        # Value text overlay
        font = QFont("Segoe UI", 9)
        font.setBold(True)
        p.setFont(font)
        p.setPen(QColor(255, 255, 255))
        p.drawText(QRect(115, 5, 80, 20), Qt.AlignmentFlag.AlignLeft, self._text)
        p.setPen(QColor(180, 180, 180))
        p.drawText(QRect(170, 5, 60, 20), Qt.AlignmentFlag.AlignLeft, self._unit)

        p.end()

class UCLedControl(QWidget):
    """LED control panel matching Windows FormLED.

    Contains device preview, mode buttons, color wheel, color picker,
    brightness, and zone selection. Handles all LED device styles
    including HR10 (style 13) with 7-segment preview and drive metrics.
    """

    # Signals for controller binding
    mode_changed = Signal(int)              # LEDMode value
    color_changed = Signal(int, int, int)   # R, G, B
    brightness_changed = Signal(int)         # 0-100
    global_toggled = Signal(bool)            # on/off
    segment_clicked = Signal(int)            # segment index
    # HR10-specific signals
    display_metric_changed = Signal(str)     # "temp", "activity", ...
    circulate_toggled = Signal(bool)
    # Zone signals
    zone_selected = Signal(int)              # zone index (0-based)
    zone_toggled = Signal(int, bool)         # zone index, on/off
    carousel_changed = Signal(bool)          # carousel mode toggled
    carousel_zone_changed = Signal(int, bool)  # zone index, in carousel
    carousel_interval_changed = Signal(int)  # interval in seconds
    # LC2 clock signals (style 9)
    clock_format_changed = Signal(bool)      # True = 24h
    week_start_changed = Signal(bool)        # True = Sunday
    # Temperature unit signal
    temp_unit_changed = Signal(str)          # "C" or "F"
    # Disk selector (LF11 style 10)
    disk_index_changed = Signal(int)         # disk index (0-based)
    # DDR multiplier (LC1 style 4)
    memory_ratio_changed = Signal(int)       # 1, 2, or 4
    # Test mode
    test_mode_changed = Signal(bool)         # test mode toggled

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setFixedSize(PANEL_WIDTH, PANEL_HEIGHT)

        self._current_mode = 0
        self._zone_count = 1
        self._style_id = 0
        self._is_hr10 = False

        # Zone state
        self._selected_zone = 0
        self._carousel_mode = False

        # HR10 state
        self._current_metric = "temp"
        self._metrics: HardwareMetrics = HardwareMetrics()
        self._temp_unit = "\u00b0C"

        # LC2 clock state (style 9)
        self._is_timer_24h = True
        self._is_week_sunday = False

        # Circulate timer (HR10)
        self._circulate_timer = QTimer(self)
        self._circulate_timer.timeout.connect(self._on_circulate_tick)
        self._circulate_index = 0

        self._setup_ui()

    def _setup_ui(self):
        """Create all UI elements."""
        # Dark background
        self.setAutoFillBackground(True)
        palette = self.palette()
        palette.setColor(QPalette.ColorRole.Window, QColor(30, 30, 30))
        self.setPalette(palette)

        # Shared P点选框 checkbox style (used by °C/°F, 24H/12H, Sun/Mon buttons)
        _cb_style = _checkbox_image_style()

        # -- LED Preview (standard: circles) --
        self._preview = UCScreenLED(self)
        self._preview.move(PREVIEW_X, PREVIEW_Y)
        self._preview.segment_clicked.connect(self.segment_clicked.emit)

        # -- 7-Segment Preview (HR10 — hidden by default) --
        self._seg_display = UCSevenSegment(self)
        self._seg_display.move(SEG_PREVIEW_X, SEG_PREVIEW_Y)
        self._seg_display.set_value("---", "\u00b0C")
        self._seg_display.setVisible(False)

        # -- Title label (hidden when background is loaded — bg has device name) --
        self._title = QLabel("RGB LED Control", self)
        self._title.setGeometry(PREVIEW_X, 20, PREVIEW_W, 40)
        self._title.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._title.setStyleSheet(
            "color: white; font-size: 20px; font-weight: bold;"
        )
        self._title.setVisible(False)

        # -- Mode buttons --
        self._mode_buttons: List[QPushButton] = []
        for i, label in enumerate(MODE_LABELS):
            btn = QPushButton(label, self)
            x = MODE_X_START + i * (MODE_W + MODE_SPACING)
            btn.setGeometry(x, MODE_Y, MODE_W, MODE_H)
            btn.setCheckable(True)
            btn.setStyleSheet(self._mode_button_style(False))
            btn.clicked.connect(lambda checked, idx=i: self._on_mode_clicked(idx))

            # Try to load mode button image
            normal_name = f"D2\u706f\u5149{i + 1}"
            active_name = f"D2\u706f\u5149{i + 1}a"
            normal_path = Assets.get(normal_name)
            active_path = Assets.get(active_name)
            if normal_path and active_path:
                btn.setText("")  # Clear text, use images
                btn.setStyleSheet(
                    f"QPushButton {{ border: none; "
                    f"background-image: url({normal_path}); "
                    f"background-repeat: no-repeat; }}"
                    f"QPushButton:checked {{ "
                    f"background-image: url({active_path}); }}"
                )

            btn.setToolTip(label)
            self._mode_buttons.append(btn)

        # Set initial mode
        if self._mode_buttons:
            self._mode_buttons[0].setChecked(True)

        # -- Color Wheel (C# ucColorA1 — shown for ALL styles) --
        self._color_wheel = UCColorWheel(self)
        self._color_wheel.setGeometry(WHEEL_X, WHEEL_Y, WHEEL_W, WHEEL_H)
        self._color_wheel.hue_changed.connect(self._on_hue_changed)

        # -- RGB Controls (C# ucScrollAR/G/B + textBoxR/G/B) --
        # Background PNG provides R/G/B letter labels — no Qt labels needed.
        self._rgb_sliders: List[QSlider] = []
        self._rgb_spinboxes: List[QSpinBox] = []
        self._rgb_labels: List[QLabel] = []  # kept empty for compat
        rgb_colors = ["#ff4444", "#44ff44", "#4444ff"]

        for i, color in enumerate(rgb_colors):
            y = RGB_Y_START + i * RGB_SPACING

            # Spinbox (left of slider — C# textBoxR/G/B)
            spinbox = QSpinBox(self)
            spinbox.setGeometry(RGB_SPINBOX_X, y, RGB_SPINBOX_W, RGB_SLIDER_H)
            spinbox.setRange(0, 255)
            spinbox.setValue(255 if i == 0 else 0)
            spinbox.setStyleSheet(
                "color: white; background: rgba(40, 40, 40, 180); "
                "border: none; font-size: 11px;"
            )
            spinbox.valueChanged.connect(
                lambda val, idx=i: self._on_spinbox_changed(idx, val)
            )
            self._rgb_spinboxes.append(spinbox)

            # Slider (right of spinbox — C# ucScrollAR/G/B)
            slider = QSlider(Qt.Orientation.Horizontal, self)
            slider.setGeometry(RGB_SLIDER_X, y, RGB_SLIDER_W, RGB_SLIDER_H)
            slider.setRange(0, 255)
            slider.setValue(255 if i == 0 else 0)
            slider.setStyleSheet(
                f"QSlider::groove:horizontal {{ background: transparent; "
                f"height: 8px; }}"
                f"QSlider::handle:horizontal {{ background: {color}; "
                f"width: 14px; margin: -3px 0; border-radius: 7px; }}"
                f"QSlider::sub-page:horizontal {{ background: {color}; "
                f"border-radius: 4px; opacity: 0.7; }}"
            )
            slider.valueChanged.connect(self._on_rgb_changed)
            self._rgb_sliders.append(slider)

        # -- Color preview swatch (hidden — color wheel serves this role) --
        self._color_swatch = QFrame(self)
        self._color_swatch.setGeometry(0, 0, 1, 1)
        self._color_swatch.setVisible(False)

        # -- Preset color buttons (C# buttonC1-C8 with D3* image assets) --
        self._preset_buttons: List[QPushButton] = []
        for i, (r, g, b) in enumerate(PRESET_COLORS):
            btn = QPushButton(self)
            x = PRESET_X_POSITIONS[i]
            btn.setGeometry(x, PRESET_Y, PRESET_SIZE, PRESET_SIZE)
            asset_path = Assets.get(PRESET_ASSETS[i])
            if asset_path:
                btn.setStyleSheet(
                    f"QPushButton {{ border: none; "
                    f"background-image: url({asset_path}); "
                    f"background-repeat: no-repeat; }}"
                    f"QPushButton:hover {{ border: 1px solid white; "
                    f"border-radius: {PRESET_SIZE // 2}px; }}"
                )
            else:
                btn.setStyleSheet(
                    f"QPushButton {{ "
                    f"background-color: rgb({r},{g},{b}); "
                    f"border: 1px solid #555; "
                    f"border-radius: {PRESET_SIZE // 2}px; }}"
                    f"QPushButton:hover {{ border: 2px solid white; }}"
                )
            btn.setFlat(True)
            btn.clicked.connect(
                lambda checked, cr=r, cg=g, cb=b: self._set_color(cr, cg, cb)
            )
            self._preset_buttons.append(btn)

        # -- Temperature color legend (modes 5-6, hidden by default) --
        self._temp_legend = QLabel(self)
        self._temp_legend.setGeometry(
            TEMP_LEGEND_X, TEMP_LEGEND_Y, TEMP_LEGEND_W, TEMP_LEGEND_H
        )
        self._temp_legend.setStyleSheet(
            "background: qlineargradient(x1:0, y1:0, x2:1, y2:0, "
            "stop:0 #00CCFF, stop:0.33 #00FF00, stop:0.55 #FFFF00, "
            "stop:0.78 #FF8800, stop:1 #FF0000); "
            "border-radius: 3px;"
        )
        self._temp_legend.setVisible(False)

        self._temp_legend_labels = QLabel(
            "<30\u00b0         <50\u00b0         <70\u00b0         <90\u00b0         >90\u00b0", self
        )
        self._temp_legend_labels.setGeometry(
            TEMP_LEGEND_X, TEMP_LEGEND_Y + TEMP_LEGEND_H + 2,
            TEMP_LEGEND_W, 14
        )
        self._temp_legend_labels.setStyleSheet(
            "color: #aaa; font-size: 10px; background: transparent;"
        )
        self._temp_legend_labels.setVisible(False)

        # -- Brightness (C# ucScrollA at (976, 537) — bg has label/icon) --
        self._bright_label = QLabel(self)
        self._bright_label.setVisible(False)  # Background has brightness icon

        self._brightness_slider = QSlider(Qt.Orientation.Horizontal, self)
        self._brightness_slider.setGeometry(BRIGHT_X, BRIGHT_Y, BRIGHT_W, 20)
        self._brightness_slider.setRange(0, 100)
        self._brightness_slider.setValue(100)
        self._brightness_slider.setStyleSheet(
            "QSlider::groove:horizontal { background: transparent; "
            "height: 8px; }"
            "QSlider::handle:horizontal { background: #fff; width: 14px; "
            "margin: -3px 0; border-radius: 7px; }"
            "QSlider::sub-page:horizontal { background: rgba(170, 170, 170, "
            "180); border-radius: 4px; }"
        )
        self._brightness_slider.setToolTip("LED brightness")
        self._brightness_slider.valueChanged.connect(self.brightness_changed.emit)

        self._brightness_label = QLabel("100%", self)
        self._brightness_label.setGeometry(
            BRIGHT_X + BRIGHT_W + 5, BRIGHT_Y, 40, 20)
        self._brightness_label.setStyleSheet(
            "color: white; font-size: 11px; background: transparent;")
        self._brightness_slider.valueChanged.connect(
            lambda v: self._brightness_label.setText(f"{v}%")
        )

        # -- Power/close button (C# buttonPower at (1212, 24) 40x40) --
        # Uses Alogout默認 (normal) / Alogout选中 (hover/pressed)
        self._onoff_btn = QPushButton(self)
        self._onoff_btn.setGeometry(POWER_X, POWER_Y, POWER_W, POWER_H)
        self._onoff_btn.setCheckable(True)
        self._onoff_btn.setChecked(True)
        self._onoff_btn.setFlat(True)
        _pwr_normal = Assets.get('Alogout默认')
        _pwr_active = Assets.get('Alogout选中')
        if _pwr_normal and _pwr_active:
            self._onoff_btn.setStyleSheet(
                f"QPushButton {{ border: none; "
                f"background-image: url({_pwr_normal}); "
                f"background-repeat: no-repeat; }}"
                f"QPushButton:checked {{ "
                f"background-image: url({_pwr_active}); }}"
            )
        else:
            self._onoff_btn.setStyleSheet(_STYLE_FLAT_CHECKABLE_BTN)
        self._onoff_btn.setToolTip("Turn LED on / off")
        self._onoff_btn.clicked.connect(self._on_toggle_clicked)

        # -- Test mode checkbox (C# checkBox1 at (36, 78)) --
        self._test_cb = QCheckBox("", self)
        self._test_cb.setGeometry(36, 78, 20, 20)
        self._test_cb.setStyleSheet(
            "QCheckBox::indicator { width: 14px; height: 14px; }"
            "QCheckBox::indicator:unchecked { border: 1px solid #666; "
            "background: transparent; }"
            "QCheckBox::indicator:checked { border: 1px solid #FF9800; "
            "background: #FF9800; }"
        )
        self._test_cb.setToolTip("LED test mode — cycles white/red/green/blue")
        self._test_cb.toggled.connect(
            lambda on: self.test_mode_changed.emit(on))
        self._test_cb.setVisible(False)  # C# checkBox1.Visible = false

        # -- Zone buttons (C# button1-4/5-6/N1-4 — images swapped per style) --
        self._zone_buttons: List[QPushButton] = []
        for i in range(4):
            btn = QPushButton(self)
            x = ZONE_X_POSITIONS[i] if i < len(ZONE_X_POSITIONS) else 590
            btn.setGeometry(x, ZONE_Y, ZONE_W, ZONE_H)
            btn.setCheckable(True)
            btn.setFlat(True)
            btn.setToolTip(f"Select zone {i + 1}")
            btn.setStyleSheet(_STYLE_FLAT_CHECKABLE_BTN)
            btn.clicked.connect(
                lambda checked, idx=i: self._on_zone_clicked(idx)
            )
            btn.setVisible(False)
            self._zone_buttons.append(btn)

        # Carousel toggle button (C# buttonLB at (739, 680), 14x14)
        # Background PNG has "Circulate" label baked in — this is just the checkbox image
        self._carousel_btn = QPushButton(self)
        self._carousel_btn.setGeometry(739, 680, 14, 14)
        self._carousel_btn.setCheckable(True)
        self._carousel_btn.setFlat(True)
        _cb_normal = Assets.get('P点选框')
        _cb_active = Assets.get('P点选框A')
        if _cb_normal and _cb_active:
            self._carousel_btn.setStyleSheet(
                f"QPushButton {{ border: none; "
                f"background-image: url({_cb_normal}); "
                f"background-repeat: no-repeat; }}"
                f"QPushButton:checked {{ "
                f"background-image: url({_cb_active}); }}"
            )
        self._carousel_btn.setToolTip("Cycle through selected zones")
        self._carousel_btn.toggled.connect(self._on_sync_toggled)
        self._carousel_btn.setVisible(False)

        # Carousel interval input (C# textBoxTimer at (843, 678), 36x16)
        # Background PNG has "⏱ ___ S" baked in — just the number input
        self._carousel_interval = QLineEdit(self)
        self._carousel_interval.setGeometry(843, 678, 36, 16)
        self._carousel_interval.setText("6")
        self._carousel_interval.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self._carousel_interval.setValidator(QIntValidator(1, 60, self))
        self._carousel_interval.setStyleSheet(
            "QLineEdit { background: rgb(67, 67, 67); color: white; "
            "border: none; font-size: 11px; }")
        self._carousel_interval.setToolTip("Carousel rotation interval (seconds)")
        self._carousel_interval.editingFinished.connect(
            self._on_carousel_interval_changed)
        self._carousel_interval.setVisible(False)

        # ============================================================
        # HR10-specific widgets (hidden by default)
        # ============================================================

        # -- Drive Metrics Panel (bottom left, below preview) --
        self._metrics_bg = QFrame(self)
        self._metrics_bg.setGeometry(METRICS_X, METRICS_Y, METRICS_W, METRICS_H)
        self._metrics_bg.setStyleSheet(
            "background-color: rgba(20, 20, 20, 200); "
            "border: 1px solid #444; border-radius: 6px;"
        )
        self._metrics_bg.setVisible(False)

        self._metric_labels: Dict[str, QLabel] = {}
        self._metric_name_labels: List[QLabel] = []
        metric_defs = [
            ("Drive Temp:", "disk_temp", "-- \u00b0C"),
            ("Total Activity:", "disk_activity", "-- %"),
            ("Read Rate:", "disk_read", "-- MB/s"),
            ("Write Rate:", "disk_write", "-- MB/s"),
        ]
        for i, (label_text, key, default) in enumerate(metric_defs):
            y = METRICS_Y + 12 + i * 28

            name_label = QLabel(label_text, self)
            name_label.setGeometry(METRICS_X + 15, y, 140, 24)
            name_label.setStyleSheet("color: #aaa; font-size: 13px;")
            name_label.setVisible(False)
            self._metric_name_labels.append(name_label)

            value_label = QLabel(default, self)
            value_label.setGeometry(METRICS_X + 160, y, 120, 24)
            value_label.setStyleSheet(
                "color: white; font-size: 13px; font-weight: bold;"
            )
            value_label.setVisible(False)
            self._metric_labels[key] = value_label

        # NVMe device label
        self._nvme_label = QLabel("", self)
        self._nvme_label.setGeometry(METRICS_X + 200, METRICS_Y + 10, 280, 20)
        self._nvme_label.setStyleSheet("color: #666; font-size: 11px;")
        self._nvme_label.setVisible(False)

        # -- Display Selection section --
        self._ds_label = QLabel("Display selection", self)
        self._ds_label.setGeometry(DISPLAY_SEL_X, DISPLAY_SEL_Y - 30, 200, 20)
        self._ds_label.setStyleSheet("color: #aaa; font-size: 12px;")
        self._ds_label.setVisible(False)

        # Circulate checkbox
        self._circulate_cb = QCheckBox("Circulate", self)
        self._circulate_cb.setGeometry(CIRCULATE_X, CIRCULATE_Y, 100, 20)
        self._circulate_cb.setStyleSheet(
            "QCheckBox { color: #aaa; font-size: 12px; }"
            "QCheckBox::indicator { width: 14px; height: 14px; }"
            "QCheckBox::indicator:unchecked { border: 1px solid #666; background: #333; }"
            "QCheckBox::indicator:checked { border: 1px solid #4CAF50; background: #4CAF50; }"
        )
        self._circulate_cb.setToolTip("Cycle through display modes")
        self._circulate_cb.toggled.connect(self._on_circulate_toggled)
        self._circulate_cb.setVisible(False)

        # Circulate interval spinbox
        self._circulate_interval_label = QLabel("Interval:", self)
        self._circulate_interval_label.setGeometry(CIRCULATE_X + 110, CIRCULATE_Y, 55, 20)
        self._circulate_interval_label.setStyleSheet("color: #888; font-size: 11px;")
        self._circulate_interval_label.setVisible(False)

        self._circulate_interval = QSpinBox(self)
        self._circulate_interval.setGeometry(CIRCULATE_X + 170, CIRCULATE_Y - 2, 45, 22)
        self._circulate_interval.setRange(CIRCULATE_MIN_S, CIRCULATE_MAX_S)
        self._circulate_interval.setValue(CIRCULATE_DEFAULT_S)
        self._circulate_interval.setSuffix("s")
        self._circulate_interval.setToolTip("Circulate interval (seconds)")
        self._circulate_interval.setStyleSheet(
            "color: white; background: #333; border: 1px solid #555; "
            "border-radius: 3px; font-size: 11px;"
        )
        self._circulate_interval.valueChanged.connect(
            self._on_circulate_interval_changed
        )
        self._circulate_interval.setVisible(False)

        # Display selection buttons
        self._display_buttons: List[QPushButton] = []
        for i, (label, metric_key) in enumerate(DISPLAY_METRICS):
            btn = QPushButton(label, self)
            x = DISPLAY_SEL_X + i * (DISPLAY_SEL_W + DISPLAY_SEL_SPACING)
            btn.setGeometry(x, DISPLAY_SEL_Y, DISPLAY_SEL_W, DISPLAY_SEL_H)
            btn.setCheckable(True)
            btn.setToolTip(f"Show {label}")
            btn.setStyleSheet(self._display_button_style())
            btn.clicked.connect(
                lambda checked, key=metric_key, idx=i: self._on_display_selected(key, idx)
            )
            btn.setVisible(False)
            self._display_buttons.append(btn)

        # ============================================================
        # LC2 clock widgets (style 9 — hidden by default)
        # ============================================================

        # LC2 clock buttons — C#: 14x14 P点选框 checkboxes at exact positions.
        # Background PNG has "24H"/"12H"/"Sun"/"Mon" labels baked in.
        self._lc2_label = QLabel(self)  # hidden — bg has labels
        self._lc2_label.setVisible(False)

        self._btn_24h = QPushButton(self)
        self._btn_24h.setGeometry(592, 711, 14, 14)
        self._btn_24h.setCheckable(True)
        self._btn_24h.setChecked(True)
        self._btn_24h.setFlat(True)
        self._btn_24h.setStyleSheet(_cb_style)
        self._btn_24h.setToolTip("24-hour format")
        self._btn_24h.clicked.connect(lambda: self._set_clock_format(True))
        self._btn_24h.setVisible(False)

        self._btn_12h = QPushButton(self)
        self._btn_12h.setGeometry(592, 729, 14, 14)
        self._btn_12h.setCheckable(True)
        self._btn_12h.setFlat(True)
        self._btn_12h.setStyleSheet(_cb_style)
        self._btn_12h.setToolTip("12-hour format")
        self._btn_12h.clicked.connect(lambda: self._set_clock_format(False))
        self._btn_12h.setVisible(False)

        self._week_label = QLabel(self)  # hidden — bg has labels
        self._week_label.setVisible(False)

        self._btn_sun = QPushButton(self)
        self._btn_sun.setGeometry(741, 729, 14, 14)
        self._btn_sun.setCheckable(True)
        self._btn_sun.setFlat(True)
        self._btn_sun.setStyleSheet(_cb_style)
        self._btn_sun.setToolTip("Week starts on Sunday")
        self._btn_sun.clicked.connect(lambda: self._set_week_start(True))
        self._btn_sun.setVisible(False)

        self._btn_mon = QPushButton(self)
        self._btn_mon.setGeometry(741, 711, 14, 14)
        self._btn_mon.setCheckable(True)
        self._btn_mon.setChecked(True)
        self._btn_mon.setFlat(True)
        self._btn_mon.setStyleSheet(_cb_style)
        self._btn_mon.setToolTip("Week starts on Monday")
        self._btn_mon.clicked.connect(lambda: self._set_week_start(False))
        self._btn_mon.setVisible(False)

        # ============================================================
        # UCInfoImage sensor gauges (styles 1-3, 5-8, 11)
        # Matches Windows FormLED ucInfoImage1-6 layout.
        # ============================================================

        # 6 UCInfoImage widgets: CPU temp/clock/usage, GPU temp/clock/usage
        # Windows layout: col1 x=16, col2 x=276, rows y=659/707/755
        INFO_DEFS = [
            (1, "cpu_temp", 1),   # M1 CPU Temp (mode=1: temp/percent)
            (2, "cpu_clock", 2),  # M2 CPU Clock (mode=2: MHz)
            (3, "cpu_usage", 1),  # M3 CPU Usage (mode=1: percent)
            (4, "gpu_temp", 1),   # M4 GPU Temp
            (5, "gpu_clock", 2),  # M5 GPU Clock
            (6, "gpu_usage", 1),  # M6 GPU Usage
        ]
        self._info_images: Dict[str, UCInfoImage] = {}
        for idx, (img_num, key, mode) in enumerate(INFO_DEFS):
            col = idx // 3
            row = idx % 3
            x = 16 + col * 260
            y = 659 + row * 36
            widget = UCInfoImage(img_num, self)
            widget.setGeometry(x, y, 240, 30)
            widget.set_mode(mode)
            widget.setVisible(False)
            self._info_images[key] = widget

        # °C/°F toggle buttons — C#: buttonC at (699, 144) 14x14, buttonF at (759, 144)
        # Uses P点选框 (unchecked) / P点选框A (checked) images like C#.
        self._btn_celsius = QPushButton(self)
        self._btn_celsius.setGeometry(
            TEMP_BTN_C_X, TEMP_BTN_Y, TEMP_BTN_SIZE, TEMP_BTN_SIZE)
        self._btn_celsius.setCheckable(True)
        self._btn_celsius.setChecked(True)
        self._btn_celsius.setFlat(True)
        self._btn_celsius.setStyleSheet(_cb_style)
        self._btn_celsius.setToolTip("Celsius")
        self._btn_celsius.clicked.connect(lambda: self._set_temp_unit_btn(False))
        self._btn_celsius.setVisible(False)

        self._btn_fahrenheit = QPushButton(self)
        self._btn_fahrenheit.setGeometry(
            TEMP_BTN_F_X, TEMP_BTN_Y, TEMP_BTN_SIZE, TEMP_BTN_SIZE)
        self._btn_fahrenheit.setCheckable(True)
        self._btn_fahrenheit.setFlat(True)
        self._btn_fahrenheit.setStyleSheet(_cb_style)
        self._btn_fahrenheit.setToolTip("Fahrenheit")
        self._btn_fahrenheit.clicked.connect(lambda: self._set_temp_unit_btn(True))
        self._btn_fahrenheit.setVisible(False)

        # ============================================================
        # LC1 memory info panel (style 4 — C# UCLEDMemoryInfo)
        # Panel at (13, 656) 506x132, transparent bg (bg PNG has labels)
        # ============================================================
        _mem_lbl_style = (
            "color: rgb(180, 150, 83); font-size: 13px;"
            " background: transparent;")

        self._mem_bg = QFrame(self)
        self._mem_bg.setGeometry(13, 656, 506, 132)
        self._mem_bg.setStyleSheet("background: transparent; border: none;")
        self._mem_bg.setVisible(False)

        # C# label positions: internal (x, y) → absolute (13+x, 656+y)
        # label1=temp  label2=clock(MHz)  label2_1=clock(MT/s)
        # label3=used(GB)  label4=ratio(X)
        # label5-10=timings (tCAS/tRCD/tRP/tRAS/tRC/tRFC)
        self._mem_labels: Dict[str, QLabel] = {}
        _mem_layout = [
            ("mem_temp",    136, 15, 166, 23),
            ("mem_clock",   136, 35, 166, 23),
            ("mem_mts",     311, 35, 128, 23),
            ("mem_used",    136, 54, 166, 23),
            ("mem_ratio",   136, 74, 166, 23),
            ("mem_tcas",    169, 94,  38, 23),
            ("mem_trcd",    228, 94,  38, 23),
            ("mem_trp",     283, 94,  38, 23),
            ("mem_tras",    346, 94,  38, 23),
            ("mem_trc",     401, 94,  38, 23),
            ("mem_trfc",    464, 94,  38, 23),
        ]
        for key, ix, iy, w, h in _mem_layout:
            lbl = QLabel("NC", self)
            lbl.setGeometry(13 + ix, 656 + iy, w, h)
            lbl.setStyleSheet(_mem_lbl_style)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter)
            lbl.setVisible(False)
            self._mem_labels[key] = lbl
        self._mem_slots: list[dict] = []

        # DDR multiplier combo (C# ucComboBoxB at internal 430,35)
        self._ddr_combo = QComboBox(self)
        self._ddr_combo.setGeometry(13 + 430, 656 + 35, 58, 20)
        self._ddr_combo.addItem("\u00d71", 1)
        self._ddr_combo.addItem("\u00d72", 2)
        self._ddr_combo.addItem("\u00d74", 4)
        self._ddr_combo.setCurrentIndex(1)  # Default: ×2 (DDR)
        self._ddr_combo.setStyleSheet(
            "QComboBox { background: #333; color: rgb(180, 150, 83); "
            "border: 1px solid #555; font-size: 11px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #333; "
            "color: rgb(180, 150, 83); selection-background-color: #555; }")
        self._ddr_combo.currentIndexChanged.connect(self._on_ddr_changed)
        self._ddr_combo.setVisible(False)
        self._memory_ratio = 2

        # ============================================================
        # LF11 disk info panel (style 10 — C# UCLEDHarddiskInfo)
        # Panel at (13, 656) 506x132, transparent bg (bg PNG has labels)
        # ============================================================

        self._disk_bg = QFrame(self)
        self._disk_bg.setGeometry(13, 656, 506, 132)
        self._disk_bg.setStyleSheet("background: transparent; border: none;")
        self._disk_bg.setVisible(False)

        # C# label positions: internal (x, y) → absolute (13+x, 656+y)
        # label1=temp  label2=health%  label3=read  label4=write
        self._disk_labels: Dict[str, QLabel] = {}
        _disk_layout = [
            ("lf11_disk_temp",  170, 21, 166, 23),
            ("lf11_disk_usage", 170, 43, 166, 23),
            ("lf11_disk_read",  170, 66, 166, 23),
            ("lf11_disk_write", 170, 88, 166, 23),
        ]
        for key, ix, iy, w, h in _disk_layout:
            lbl = QLabel("NC", self)
            lbl.setGeometry(13 + ix, 656 + iy, w, h)
            lbl.setStyleSheet(_mem_lbl_style)
            lbl.setAlignment(Qt.AlignmentFlag.AlignLeft
                             | Qt.AlignmentFlag.AlignVCenter)
            lbl.setVisible(False)
            self._disk_labels[key] = lbl
        self._disk_slots: list[dict] = []

        # Disk selector combo (C# ucComboBoxC at internal 304,21)
        self._disk_selector = QComboBox(self)
        self._disk_selector.setGeometry(13 + 304, 656 + 21, 180, 24)
        self._disk_selector.setStyleSheet(
            "QComboBox { background: #333; color: rgb(180, 150, 83); "
            "border: 1px solid #555; font-size: 11px; }"
            "QComboBox::drop-down { border: none; }"
            "QComboBox QAbstractItemView { background: #333; "
            "color: rgb(180, 150, 83); selection-background-color: #555; }")
        self._disk_selector.currentIndexChanged.connect(self._on_disk_selected)
        self._disk_selector.setVisible(False)

        # -- Status label --
        self._status = QLabel("", self)
        self._status.setGeometry(STATUS_X, STATUS_Y, STATUS_W, 24)
        self._status.setStyleSheet(_STYLE_MUTED_LABEL)

    # ================================================================
    # Public API
    # ================================================================

    def initialize(self, style_id: int, segment_count: int,
                   zone_count: int = 1,
                   model: str = '') -> None:
        """Configure for a specific LED device style.

        Args:
            style_id: LED device style (1-13).
            segment_count: Number of LED segments.
            zone_count: Number of independent zones.
            model: Device model name (for PM-specific preview image).
        """
        self._style_id = style_id
        self._zone_count = zone_count
        self._model = model
        self._is_hr10 = False  # HR10 renders as standard LED panel

        # Toggle preview widgets
        self._preview.setVisible(True)
        self._seg_display.setVisible(False)

        self._preview.set_style(style_id, segment_count)

        # Load device preview background (PM-specific or style default)
        from ..adapters.device.led import LED_STYLES, PmRegistry
        style = LED_STYLES.get(style_id)
        if style:
            # Resolve preview: check PmRegistry for model-specific image,
            # fall back to style default (Windows: FormLEDInit per-NO)
            preview_name = style.preview_image
            if model:
                for pm, entry in PmRegistry._REGISTRY.items():
                    if entry.model_name == model and entry.preview_image:
                        preview_name = entry.preview_image
                        break
            preview_pixmap = Assets.get(preview_name)
            if preview_pixmap:
                self._preview.set_overlay(QPixmap(preview_pixmap))

            # Set panel background (localized with fallback)
            from ..conf import settings
            bg_name = Assets.get_localized(style.background_base, settings.lang)
            if Assets.get(bg_name):
                set_background_pixmap(self, bg_name)

            self._title.setText(f"RGB LED Control \u2014 {style.model_name}")

        # Layout shift for HR10 (color wheel takes space)
        self._apply_layout()

        # Show/hide HR10-specific controls
        self._set_hr10_visibility(self._is_hr10)

        # Apply zone button images for this style, then show/hide
        self._apply_zone_images(style_id)
        for i, btn in enumerate(self._zone_buttons):
            btn.setVisible(i < zone_count and zone_count > 1)
        self._carousel_btn.setVisible(zone_count > 1)
        self._carousel_interval.setVisible(False)
        self._selected_zone = 0
        self._carousel_mode = False
        self._carousel_btn.setChecked(False)
        if zone_count > 1 and self._zone_buttons:
            self._zone_buttons[0].setChecked(True)

        # Show/hide device-specific info panels (mutually exclusive)
        is_lc2 = (style_id == 9)
        is_lc1 = (style_id == 4)
        is_lf11 = (style_id == 10)
        # C# shows ucInfoImage1-6 for ALL styles except LC1 (4) and LF11 (10)
        show_sensors = style_id not in (4, 10)

        self._set_lc2_visibility(is_lc2)
        self._set_sensor_visibility(show_sensors)
        self._set_mem_visibility(is_lc1)
        self._set_disk_visibility(is_lf11)

        # Populate static hardware identity info (once per device switch)
        if is_lc1:
            self._populate_memory_identity()
        elif is_lf11:
            self._populate_disk_identity()

    def set_led_colors(self, colors: List[Tuple[int, int, int]]) -> None:
        """Update LED preview from controller tick."""
        if self._is_hr10:
            # Use the first LED color to tint the 7-segment display
            if colors:
                r, g, b = colors[0]
                self._seg_display.set_color(r, g, b)
        else:
            self._preview.set_colors(colors)

    def set_status(self, text: str) -> None:
        """Update status text."""
        self._status.setText(text)

    def apply_localized_background(self) -> None:
        """Re-apply localized background for current settings.lang."""
        from ..adapters.device.led import LED_STYLES
        from ..conf import settings
        style = LED_STYLES.get(self._style_id)
        if style:
            bg_name = Assets.get_localized(style.background_base, settings.lang)
            if Assets.get(bg_name):
                set_background_pixmap(self, bg_name)

    def set_temp_unit(self, unit_int: int) -> None:
        """Set temperature unit from app settings.

        Args:
            unit_int: 0 = °C, 1 = °F (matches app config).
        """
        self._temp_unit = "\u00b0F" if unit_int == 1 else "\u00b0C"
        # Sync °C/°F button visuals
        self._btn_celsius.setChecked(unit_int == 0)
        self._btn_fahrenheit.setChecked(unit_int == 1)
        if self._is_hr10:
            self._update_display_value()

    def update_drive_metrics(self, metrics: HardwareMetrics) -> None:
        """Update live drive metrics from system_info polling (HR10)."""
        self._metrics = metrics

        temp = metrics.disk_temp
        if self._temp_unit == "\u00b0F":
            temp = temp * 9 / 5 + 32
        self._metric_labels['disk_temp'].setText(
            f"{temp:.0f} {self._temp_unit}"
        )
        self._metric_labels['disk_activity'].setText(
            f"{metrics.disk_activity:.0f}%"
        )
        self._metric_labels['disk_read'].setText(
            f"{metrics.disk_read:.1f} MB/s"
        )
        self._metric_labels['disk_write'].setText(
            f"{metrics.disk_write:.1f} MB/s"
        )

        self._update_display_value()

    def get_display_value(self) -> Tuple[str, str]:
        """Return (value_text, unit_text) for the current 7-segment display.

        Used by the controller to push the display text to the LED
        hardware without reaching into private widget attributes.
        """
        return self._seg_display.get_display_text()

    @property
    def is_hr10(self) -> bool:
        """Whether the panel is currently showing an HR10 device."""
        return self._is_hr10

    # ================================================================
    # Layout management
    # ================================================================

    def _apply_zone_images(self, style_id: int) -> None:
        """Swap zone button images to match the C# button variant for this style.

        C# has 3 separate sets of zone buttons with different images:
        - button1-4 (D4模式1-4): styles 1, 2
        - button5-6 (D4模式5-6): styles 3, 5, 6, 11
        - buttonN1-4 (D4按钮1-4): styles 4, 7, 8, 10
        """
        assets = _ZONE_STYLE_TO_ASSETS.get(style_id)
        if not assets:
            return
        for i, btn in enumerate(self._zone_buttons):
            if i < len(assets):
                normal_name, active_name = assets[i]
                normal_path = Assets.get(normal_name)
                active_path = Assets.get(active_name)
                if normal_path and active_path:
                    btn.setStyleSheet(
                        f"QPushButton {{ border: none; "
                        f"background-image: url({normal_path}); "
                        f"background-repeat: no-repeat; }}"
                        f"QPushButton:checked {{ "
                        f"background-image: url({active_path}); }}"
                    )
                else:
                    btn.setStyleSheet(_STYLE_FLAT_CHECKABLE_BTN)

    def _apply_layout(self):
        """Reposition controls.  All backgrounds include a color wheel area,
        so the layout is unified: wheel left, RGB/presets/brightness right.
        Only HR10-specific widgets (drive metrics, display selection) differ.
        """
        if self._is_hr10:
            bright_x = HR10_BRIGHT_X
            bright_y = HR10_BRIGHT_Y
            bright_w = HR10_BRIGHT_W
        else:
            bright_x = BRIGHT_X
            bright_y = BRIGHT_Y
            bright_w = BRIGHT_W

        # RGB controls — positions set in _setup_ui at C# coordinates;
        # no repositioning needed (unified layout).

        # Brightness
        self._brightness_slider.setGeometry(bright_x, bright_y, bright_w, 20)
        self._brightness_label.setGeometry(
            bright_x + bright_w + 5, bright_y, 40, 20)

        # ON button visible for non-HR10 (HR10 has no separate on/off)
        self._onoff_btn.setVisible(not self._is_hr10)

        self._status.setGeometry(STATUS_X, STATUS_Y, STATUS_W, 24)

    def _set_hr10_visibility(self, visible: bool):
        """Show/hide all HR10-specific widgets."""
        self._seg_display.setVisible(visible)
        self._metrics_bg.setVisible(visible)
        self._nvme_label.setVisible(visible)
        self._ds_label.setVisible(visible)
        self._circulate_cb.setVisible(visible)
        self._circulate_interval_label.setVisible(visible)
        self._circulate_interval.setVisible(visible)

        for lbl in self._metric_name_labels:
            lbl.setVisible(visible)
        for lbl in self._metric_labels.values():
            lbl.setVisible(visible)
        for btn in self._display_buttons:
            btn.setVisible(visible)

        if not visible:
            self._circulate_timer.stop()
            self._temp_legend.setVisible(False)
            self._temp_legend_labels.setVisible(False)

    # ================================================================
    # Internal handlers
    # ================================================================

    def _on_mode_clicked(self, index: int):
        """Handle mode button click."""
        self._current_mode = index
        for i, btn in enumerate(self._mode_buttons):
            btn.setChecked(i == index)
        if self._is_hr10:
            self._update_mode_visibility()
        else:
            self._preview.set_led_mode(index)
        self.mode_changed.emit(index)

    def _update_mode_visibility(self):
        """Toggle control visibility based on selected mode (HR10).

        For HR10, modes 0-1 (static/breathing) use the color wheel + RGB
        controls.  Modes 2-5 hide them and may show the temp legend.
        For non-HR10, all controls stay visible (C# behaviour).
        """
        mode = self._current_mode
        show_color = mode in (0, 1)
        show_temp_legend = mode in (4, 5)

        self._color_wheel.setVisible(show_color)
        self._temp_legend.setVisible(show_temp_legend)
        self._temp_legend_labels.setVisible(show_temp_legend)

        for slider in self._rgb_sliders:
            slider.setVisible(show_color)
        for spinbox in self._rgb_spinboxes:
            spinbox.setVisible(show_color)
        for btn in self._preset_buttons:
            btn.setVisible(show_color)

    def _on_hue_changed(self, hue: int):
        """Handle color wheel hue selection -> update RGB sliders."""
        color = QColor.fromHsv(hue, 255, 255)
        self._set_color(color.red(), color.green(), color.blue())

    def _on_rgb_changed(self):
        """Handle RGB slider change."""
        r = self._rgb_sliders[0].value()
        g = self._rgb_sliders[1].value()
        b = self._rgb_sliders[2].value()
        for i, val in enumerate([r, g, b]):
            self._rgb_spinboxes[i].blockSignals(True)
            self._rgb_spinboxes[i].setValue(val)
            self._rgb_spinboxes[i].blockSignals(False)
        self._sync_wheel_from_rgb(r, g, b)
        if self._is_hr10:
            self._seg_display.set_color(r, g, b)
        self.color_changed.emit(r, g, b)

    def _on_spinbox_changed(self, index: int, value: int):
        """Handle RGB spinbox change."""
        self._rgb_sliders[index].blockSignals(True)
        self._rgb_sliders[index].setValue(value)
        self._rgb_sliders[index].blockSignals(False)
        r = self._rgb_spinboxes[0].value()
        g = self._rgb_spinboxes[1].value()
        b = self._rgb_spinboxes[2].value()
        self._sync_wheel_from_rgb(r, g, b)
        if self._is_hr10:
            self._seg_display.set_color(r, g, b)
        self.color_changed.emit(r, g, b)

    def _set_color(self, r: int, g: int, b: int):
        """Set color from preset button or color wheel."""
        for i, val in enumerate([r, g, b]):
            self._rgb_sliders[i].blockSignals(True)
            self._rgb_sliders[i].setValue(val)
            self._rgb_sliders[i].blockSignals(False)
            self._rgb_spinboxes[i].blockSignals(True)
            self._rgb_spinboxes[i].setValue(val)
            self._rgb_spinboxes[i].blockSignals(False)
        self._sync_wheel_from_rgb(r, g, b)
        if self._is_hr10:
            self._seg_display.set_color(r, g, b)
        self.color_changed.emit(r, g, b)

    def _sync_wheel_from_rgb(self, r: int, g: int, b: int):
        """Update wheel indicator from RGB values without triggering loop."""
        hue = QColor(r, g, b).hsvHue()
        if hue < 0:
            hue = 0  # achromatic
        self._color_wheel.blockSignals(True)
        self._color_wheel.set_hue(hue)
        self._color_wheel.blockSignals(False)

    def _on_toggle_clicked(self):
        """Handle on/off toggle."""
        on = self._onoff_btn.isChecked()
        self._onoff_btn.setText("ON" if on else "OFF")
        self.global_toggled.emit(on)

    def _update_color_swatch(self):
        """No-op — color swatch removed (color wheel shows selected hue)."""

    # -- HR10 display selection --

    def _on_display_selected(self, metric_key: str, button_index: int):
        """Handle display selection button click (HR10)."""
        self._current_metric = metric_key
        for i, btn in enumerate(self._display_buttons):
            btn.setChecked(i == button_index)
        self._update_display_value()
        self.display_metric_changed.emit(metric_key)

    def _update_display_value(self):
        """Update the 7-segment display with the current metric value (HR10)."""
        if not self._is_hr10:
            return

        metric = self._current_metric
        if metric == "temp":
            val = self._metrics.disk_temp
            if self._temp_unit == "\u00b0F":
                val = val * 9 / 5 + 32
            self._seg_display.set_value(f"{val:.0f}", self._temp_unit)
        elif metric == "activity":
            self._seg_display.set_value(f"{self._metrics.disk_activity:.0f}", "%")
        elif metric == "read":
            self._seg_display.set_value(f"{self._metrics.disk_read:.0f}", "MB/s")
        elif metric == "write":
            self._seg_display.set_value(f"{self._metrics.disk_write:.0f}", "MB/s")

    # -- HR10 circulate --

    def _on_circulate_toggled(self, enabled: bool):
        if enabled:
            interval_ms = self._circulate_interval.value() * 1000
            self._circulate_timer.start(interval_ms)
            self._circulate_index = 0
        else:
            self._circulate_timer.stop()
        self.circulate_toggled.emit(enabled)

    def _on_circulate_interval_changed(self, value: int):
        if self._circulate_timer.isActive():
            self._circulate_timer.start(value * 1000)

    def _on_circulate_tick(self):
        self._circulate_index = (self._circulate_index + 1) % len(DISPLAY_METRICS)
        _label, key = DISPLAY_METRICS[self._circulate_index]
        self._on_display_selected(key, self._circulate_index)

    # -- Zone selection --

    def _on_zone_clicked(self, zone_index: int):
        """Handle zone button click.

        Carousel OFF: radio-select (one zone at a time).
        Carousel ON: multi-select (toggle zone in/out of rotation).
        """
        if self._carousel_mode:
            # Multi-select: toggle this zone's carousel participation
            btn = self._zone_buttons[zone_index]
            selected = btn.isChecked()
            self.carousel_zone_changed.emit(zone_index, selected)
        else:
            # Radio-select: one zone at a time
            self._selected_zone = zone_index
            for i, btn in enumerate(self._zone_buttons):
                btn.setChecked(i == zone_index)
            self.zone_selected.emit(zone_index)

    def _on_sync_toggled(self, carousel: bool):
        """Handle carousel checkbox toggle (C# buttonLB_Click)."""
        self._carousel_mode = carousel
        self._carousel_interval.setVisible(carousel and self._zone_count > 1)
        if not carousel:
            # Revert to radio-select: only selected zone checked
            for i, btn in enumerate(self._zone_buttons):
                btn.setChecked(i == self._selected_zone)
        self.carousel_changed.emit(carousel)

    def _on_carousel_interval_changed(self):
        """Handle carousel interval input change."""
        text = self._carousel_interval.text()
        if text.isdigit() and int(text) > 0:
            self.carousel_interval_changed.emit(int(text))

    def load_zone_state(self, zone_index: int, mode: int,
                        color: tuple, brightness: int,
                        on: bool = True):
        """Load a zone's state into the UI controls."""
        for slider in self._rgb_sliders:
            slider.blockSignals(True)
        for spinbox in self._rgb_spinboxes:
            spinbox.blockSignals(True)
        self._brightness_slider.blockSignals(True)

        r, g, b = color
        self._rgb_sliders[0].setValue(r)
        self._rgb_sliders[1].setValue(g)
        self._rgb_sliders[2].setValue(b)
        for i, val in enumerate([r, g, b]):
            self._rgb_spinboxes[i].setValue(val)

        self._brightness_slider.setValue(brightness)
        self._brightness_label.setText(f"{brightness}%")

        for i, btn in enumerate(self._mode_buttons):
            btn.setChecked(i == mode)
        self._current_mode = mode

        for slider in self._rgb_sliders:
            slider.blockSignals(False)
        for spinbox in self._rgb_spinboxes:
            spinbox.blockSignals(False)
        self._brightness_slider.blockSignals(False)

        self._update_color_swatch()

    @property
    def selected_zone(self) -> int:
        return self._selected_zone

    @property
    def carousel_mode(self) -> bool:
        return self._carousel_mode

    # -- LC2 clock handlers --

    def _set_clock_format(self, is_24h: bool):
        self._is_timer_24h = is_24h
        self._btn_24h.setChecked(is_24h)
        self._btn_12h.setChecked(not is_24h)
        self.clock_format_changed.emit(is_24h)

    def _set_week_start(self, is_sunday: bool):
        self._is_week_sunday = is_sunday
        self._btn_sun.setChecked(is_sunday)
        self._btn_mon.setChecked(not is_sunday)
        self.week_start_changed.emit(is_sunday)

    def _set_temp_unit_btn(self, is_fahrenheit: bool):
        """Handle °C/°F toggle button click."""
        self._btn_celsius.setChecked(not is_fahrenheit)
        self._btn_fahrenheit.setChecked(is_fahrenheit)
        self._temp_unit = "\u00b0F" if is_fahrenheit else "\u00b0C"
        self.temp_unit_changed.emit("F" if is_fahrenheit else "C")

    # -- Visibility helpers --

    def _set_lc2_visibility(self, visible: bool):
        """Show/hide LC2 clock widgets."""
        self._lc2_label.setVisible(visible)
        self._btn_24h.setVisible(visible)
        self._btn_12h.setVisible(visible)
        self._week_label.setVisible(visible)
        self._btn_sun.setVisible(visible)
        self._btn_mon.setVisible(visible)

    def _set_sensor_visibility(self, visible: bool):
        """Show/hide UCInfoImage sensor gauges and °C/°F buttons."""
        for widget in self._info_images.values():
            widget.setVisible(visible)
        self._btn_celsius.setVisible(visible)
        self._btn_fahrenheit.setVisible(visible)

    def _set_mem_visibility(self, visible: bool):
        """Show/hide LC1 memory info panel (C# ucledMemoryInfo1)."""
        self._mem_bg.setVisible(visible)
        for lbl in self._mem_labels.values():
            lbl.setVisible(visible)
        self._ddr_combo.setVisible(visible)

    def _set_disk_visibility(self, visible: bool):
        """Show/hide LF11 disk info panel (C# ucledHarddiskInfo1)."""
        self._disk_bg.setVisible(visible)
        for lbl in self._disk_labels.values():
            lbl.setVisible(visible)
        self._disk_selector.setVisible(visible)

    # -- Sensor/memory/disk update methods --

    def update_sensor_metrics(self, metrics: HardwareMetrics) -> None:
        """Update UCInfoImage sensor gauges (for non-HR10 styles)."""
        unit = self._temp_unit
        t = metrics.cpu_temp
        if unit == "\u00b0F":
            t = t * 9 / 5 + 32
        self._info_images['cpu_temp'].set_value(t, f"{t:.0f}", unit)
        self._info_images['cpu_clock'].set_value(
            metrics.cpu_freq, f"{metrics.cpu_freq:.0f}", "MHz")
        self._info_images['cpu_usage'].set_value(
            metrics.cpu_percent, f"{metrics.cpu_percent:.0f}", "%")
        t = metrics.gpu_temp
        if unit == "\u00b0F":
            t = t * 9 / 5 + 32
        self._info_images['gpu_temp'].set_value(t, f"{t:.0f}", unit)
        self._info_images['gpu_clock'].set_value(
            metrics.gpu_clock, f"{metrics.gpu_clock:.0f}", "MHz")
        self._info_images['gpu_usage'].set_value(
            metrics.gpu_usage, f"{metrics.gpu_usage:.0f}", "%")

    def update_memory_metrics(self, metrics: HardwareMetrics) -> None:
        """Update memory info labels (LC1 style 4, C# UCLEDMemoryInfo)."""
        unit = self._temp_unit
        t = metrics.mem_temp
        if unit == "\u00b0F":
            t = t * 9 / 5 + 32
        if t == 0:
            self._mem_labels['mem_temp'].setText("NC")
        else:
            self._mem_labels['mem_temp'].setText(
                f"{t:.0f}\u2103" if unit == "\u00b0C" else f"{t:.0f}\u2109")
        mhz = metrics.mem_clock
        self._mem_labels['mem_clock'].setText(
            f"{mhz:.0f}MHz" if mhz else "NC")
        effective = mhz * self._memory_ratio
        self._mem_labels['mem_mts'].setText(
            f"{effective:.0f}MT/S" if mhz else "NC")
        # C# shows MemUsed/1000 in GB — derive from available + percent
        if metrics.mem_percent > 0 and metrics.mem_available > 0:
            total = metrics.mem_available / (1.0 - metrics.mem_percent / 100.0)
            used_gb = (total - metrics.mem_available) / 1000.0
            self._mem_labels['mem_used'].setText(f"{used_gb:.1f}GB")
        else:
            self._mem_labels['mem_used'].setText("NC")
        ratio = self._memory_ratio
        self._mem_labels['mem_ratio'].setText(f"{ratio}X")

    def _populate_memory_identity(self) -> None:
        """Populate memory timing labels from DRAM SPD info."""
        try:
            from ..services.system import SystemService
            self._mem_slots = SystemService.get_memory_info()
            if self._mem_slots:
                s = self._mem_slots[0]
                for key in ('mem_tcas', 'mem_trcd', 'mem_trp',
                            'mem_tras', 'mem_trc', 'mem_trfc'):
                    field = key.replace('mem_t', 't').replace('mem_', '')
                    val = s.get(field, '')
                    self._mem_labels[key].setText(str(val) if val else "NC")
        except Exception:
            self._mem_slots = []

    def _on_ddr_changed(self, index: int) -> None:
        """Handle DDR multiplier combo selection."""
        ratio = self._ddr_combo.itemData(index)
        if ratio and isinstance(ratio, int):
            self._memory_ratio = ratio
            self.memory_ratio_changed.emit(ratio)

    def set_memory_ratio(self, ratio: int) -> None:
        """Set DDR combo from saved state (without emitting signal)."""
        self._memory_ratio = ratio
        idx = {1: 0, 2: 1, 4: 2}.get(ratio, 1)
        self._ddr_combo.blockSignals(True)
        self._ddr_combo.setCurrentIndex(idx)
        self._ddr_combo.blockSignals(False)

    def _populate_disk_identity(self) -> None:
        """Populate disk selector dropdown (C# ucComboBoxC)."""
        try:
            from ..services.system import SystemService
            self._disk_slots = SystemService.get_disk_info()

            self._disk_selector.blockSignals(True)
            self._disk_selector.clear()
            for d in self._disk_slots:
                name = d.get('name', d.get('model', '?'))
                # C# shows name up to '(' character
                if '(' in name:
                    name = name[:name.index('(') - 1]
                self._disk_selector.addItem(name)
            self._disk_selector.blockSignals(False)
        except Exception:
            self._disk_slots = []

    def _on_disk_selected(self, idx: int) -> None:
        """Handle disk selector change — emit signal."""
        self.disk_index_changed.emit(idx)

    def update_lf11_disk_metrics(self, metrics: HardwareMetrics) -> None:
        """Update disk info labels (LF11 style 10, C# UCLEDHarddiskInfo)."""
        unit = self._temp_unit
        t = metrics.disk_temp
        if unit == "\u00b0F":
            t = t * 9 / 5 + 32
        if t == 0:
            self._disk_labels['lf11_disk_temp'].setText("NC")
        else:
            self._disk_labels['lf11_disk_temp'].setText(
                f"{t:.0f}\u2103" if unit == "\u00b0C" else f"{t:.0f}\u2109")
        self._disk_labels['lf11_disk_usage'].setText(
            f"{metrics.disk_activity:.0f}%")
        self._disk_labels['lf11_disk_read'].setText(
            f"{metrics.disk_read:.0f}MB/S")
        self._disk_labels['lf11_disk_write'].setText(
            f"{metrics.disk_write:.0f}MB/S")

    # ================================================================
    # Styles
    # ================================================================

    @staticmethod
    def _mode_button_style(active: bool) -> str:
        # Fallback when mode button images (D2灯光) don't load.
        # Transparent background — the background PNG has button visuals.
        if active:
            return (
                "QPushButton { background: rgba(33, 150, 243, 60); "
                "color: transparent; border: none; }"
            )
        return (
            "QPushButton { background: transparent; color: transparent; "
            "border: none; }"
            "QPushButton:checked { background: rgba(33, 150, 243, 60); }"
            "QPushButton:hover { background: rgba(255, 255, 255, 20); }"
        )

    @staticmethod
    def _display_button_style() -> str:
        return (
            "QPushButton { background: transparent; color: transparent; "
            "border: none; }"
            "QPushButton:checked { background: rgba(33, 150, 243, 60); }"
            "QPushButton:hover { background: rgba(255, 255, 255, 20); }"
        )
