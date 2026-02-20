#!/usr/bin/env python3
"""
Visual test harness for LED panel — all 12 device styles.

Buttons across the top to switch devices. Gray backdrop behind
UCScreenLED so missing/misplaced LEDs are immediately obvious.
Fake metrics pumped every second so sensor gauges are live.
All panel buttons wired: mode, color, brightness, zones, on/off.

Usage:
    PYTHONPATH=src python3 tests/test_led_panel_visual.py
"""

import math
import os
import sys

os.environ.setdefault('QT_QPA_PLATFORM', '')  # use real display

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from PySide6.QtCore import QRect, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPalette, QPen
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QScrollArea,
    QVBoxLayout,
    QWidget,
)

from trcc.core.models import LED_STYLES, HardwareMetrics
from trcc.qt_components.uc_led_control import PREVIEW_X, PREVIEW_Y, UCLedControl
from trcc.qt_components.uc_screen_led import STYLE_POSITIONS

# ── Fake metrics that cycle so gauges animate ──────────────────────
_tick = 0


def _fake_metrics() -> HardwareMetrics:
    global _tick
    _tick += 1
    phase = (_tick % 100) / 100.0  # 0.0 → 1.0 sawtooth
    return HardwareMetrics(
        cpu_temp=30 + phase * 60,
        cpu_freq=800 + phase * 4200,
        cpu_percent=phase * 100,
        gpu_temp=25 + phase * 70,
        gpu_clock=300 + phase * 1700,
        gpu_usage=phase * 100,
        mem_temp=35 + phase * 30,
        mem_clock=1600 + phase * 1200,
        mem_percent=20 + phase * 60,
        mem_available=16000,
        disk_temp=30 + phase * 30,
        disk_activity=phase * 100,
        disk_read=phase * 500,
        disk_write=phase * 300,
    )


class LEDIndexOverlay(QWidget):
    """Transparent overlay that draws LED index numbers on each rect."""

    def __init__(self, parent: QWidget | None = None):
        super().__init__(parent)
        self.setFixedSize(460, 460)
        self.setAttribute(Qt.WidgetAttribute.WA_TransparentForMouseEvents)
        self._positions: tuple[tuple[int, int, int, int], ...] = ()

    def set_positions(self, positions: tuple[tuple[int, int, int, int], ...]) -> None:
        self._positions = positions
        self.update()

    def paintEvent(self, event: object) -> None:
        if not self._positions:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.RenderHint.TextAntialiasing)
        font = QFont("monospace", 3)
        font.setPixelSize(7)
        p.setFont(font)
        for i, (x, y, w, h) in enumerate(self._positions):
            rect = QRect(x, y, w, h)
            text = str(i)
            p.setPen(QPen(QColor(0, 0, 0), 1))
            for dx in (-1, 0, 1):
                for dy in (-1, 0, 1):
                    if dx or dy:
                        p.drawText(rect.adjusted(dx, dy, dx, dy),
                                   Qt.AlignmentFlag.AlignCenter, text)
            p.setPen(QColor(255, 255, 255))
            p.drawText(rect, Qt.AlignmentFlag.AlignCenter, text)
        p.end()


class LEDPanelTestHarness(QWidget):
    """Main test window: device buttons at top, LED panel below.

    All panel signals wired — modes, color, brightness, zones, on/off
    all work interactively. Each mode generates different color patterns:
      0=Static (solid color), 1=Breathing (pulse), 2=Colorful (per-LED rainbow),
      3=Rainbow (shifting rainbow), 4=Temp link (gradient), 5=Load link (gradient).
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LED Panel Visual Test — All 12 Styles")
        self.setMinimumSize(1300, 900)

        # ── State ─────────────────────────────────────────────────
        self._current_style = 0
        self._mode = 0           # 0=static 1=breathing 2=colorful 3=rainbow 4=temp 5=load
        self._color = (255, 0, 0)  # user-chosen RGB
        self._brightness = 100     # 0-100
        self._global_on = True
        self._selected_zone = 0
        self._zone_count = 1
        self._tick_count = 0
        self._segment_on: list[bool] = []  # per-LED on/off

        # Dark background
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(50, 50, 50))
        self.setPalette(pal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Device buttons bar ────────────────────────────────────
        btn_bar = QWidget()
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(2)

        self._device_buttons: list[QPushButton] = []
        sorted_styles = sorted(LED_STYLES.items())
        for style_id, style in sorted_styles:
            btn = QPushButton(
                f"{style_id}: {style.model_name}\n"
                f"{style.led_count}L/{style.segment_count}S/{style.zone_count}Z"
            )
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.setStyleSheet(
                "QPushButton { background: #333; color: #ccc; border: 1px solid #555; "
                "border-radius: 4px; font-size: 10px; padding: 2px 6px; }"
                "QPushButton:checked { background: #1565C0; color: white; "
                "border: 2px solid #42A5F5; }"
                "QPushButton:hover { background: #444; }"
            )
            btn.clicked.connect(lambda _, sid=style_id: self._switch_style(sid))
            btn_layout.addWidget(btn)
            self._device_buttons.append(btn)

        layout.addWidget(btn_bar)

        # ── Status bar ────────────────────────────────────────────
        self._status_label = QLabel()
        self._status_label.setStyleSheet(
            "color: #ff8; font-size: 11px; font-family: monospace; "
            "background: #222; padding: 4px; border-radius: 3px;"
        )
        layout.addWidget(self._status_label)

        # ── Metrics label ─────────────────────────────────────────
        self._metrics_label = QLabel()
        self._metrics_label.setStyleSheet(
            "color: #aaa; font-size: 11px; font-family: monospace; "
            "background: #222; padding: 4px; border-radius: 3px;"
        )
        self._metrics_label.setWordWrap(True)
        layout.addWidget(self._metrics_label)

        # ── LED position metrics ──────────────────────────────────
        self._pos_label = QLabel()
        self._pos_label.setStyleSheet(
            "color: #8f8; font-size: 11px; font-family: monospace; "
            "background: #1a1a1a; padding: 4px; border-radius: 3px;"
        )
        self._pos_label.setWordWrap(True)
        self._pos_label.setMaximumHeight(80)
        layout.addWidget(self._pos_label)

        # ── Scroll area with gray backdrop for the panel ──────────
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setStyleSheet(
            "QScrollArea { background: #808080; border: none; }"
            "QWidget#panelContainer { background: #808080; }"
        )

        self._container = QWidget()
        self._container.setObjectName("panelContainer")
        container_layout = QVBoxLayout(self._container)
        container_layout.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self._led_panel = UCLedControl()
        container_layout.addWidget(self._led_panel)

        # ── Index overlay ─────────────────────────────────────────
        self._index_overlay = LEDIndexOverlay(self._led_panel)
        self._index_overlay.move(PREVIEW_X, PREVIEW_Y)
        self._index_overlay.raise_()

        scroll.setWidget(self._container)
        layout.addWidget(scroll, 1)

        # ── Wire ALL panel signals ────────────────────────────────
        p = self._led_panel
        p.mode_changed.connect(self._on_mode)
        p.color_changed.connect(self._on_color)
        p.brightness_changed.connect(self._on_brightness)
        p.global_toggled.connect(self._on_global_toggle)
        p.segment_clicked.connect(self._on_segment_click)
        p.zone_selected.connect(self._on_zone_selected)
        p.zone_toggled.connect(self._on_zone_toggled)
        p.carousel_changed.connect(self._on_carousel)
        p.carousel_interval_changed.connect(self._on_carousel_interval)
        p.temp_unit_changed.connect(self._on_temp_unit)
        p.close_requested.connect(self._on_close)
        p.test_mode_changed.connect(self._on_test_mode)

        # ── Start with style 1 ───────────────────────────────────
        self._switch_style(1)

        # ── Timer: animate + metrics every 100ms ──────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)

    # ================================================================
    # Signal handlers — buttons actually work now
    # ================================================================

    def _on_mode(self, mode: int):
        self._mode = mode
        self._update_status()

    def _on_color(self, r: int, g: int, b: int):
        self._color = (r, g, b)
        self._update_status()

    def _on_brightness(self, val: int):
        self._brightness = val
        self._update_status()

    def _on_global_toggle(self, on: bool):
        self._global_on = on
        self._update_status()

    def _on_segment_click(self, idx: int):
        if 0 <= idx < len(self._segment_on):
            self._segment_on[idx] = not self._segment_on[idx]
            self._led_panel._preview.set_segment_on(idx, self._segment_on[idx])
        self._update_status()

    def _on_zone_selected(self, zone: int):
        self._selected_zone = zone
        self._update_status()

    def _on_zone_toggled(self, zone: int, on: bool):
        self._update_status()

    def _on_carousel(self, on: bool):
        self._update_status()

    def _on_carousel_interval(self, secs: int):
        self._update_status()

    def _on_temp_unit(self, unit: str):
        self._update_status()

    def _on_close(self):
        self._update_status()

    def _on_test_mode(self, on: bool):
        self._update_status()

    # ================================================================
    # Device switching
    # ================================================================

    def _switch_style(self, style_id: int):
        self._current_style = style_id
        style = LED_STYLES[style_id]
        self._zone_count = style.zone_count
        self._selected_zone = 0
        self._mode = 0
        self._global_on = True

        # Update button checked state
        sorted_styles = sorted(LED_STYLES.keys())
        for i, sid in enumerate(sorted_styles):
            self._device_buttons[i].setChecked(sid == style_id)

        # Initialize panel
        self._led_panel.initialize(
            style_id=style.style_id,
            segment_count=style.segment_count,
            zone_count=style.zone_count,
            model=style.model_name,
        )

        # Reset segment on/off state
        positions = STYLE_POSITIONS.get(style_id, ())
        self._segment_on = [True] * len(positions)
        self._index_overlay.set_positions(positions)

        # Position metrics
        led_count = len(positions)
        if positions:
            xs = [p[0] for p in positions]
            ys = [p[1] for p in positions]
            ws = [p[2] for p in positions]
            hs = [p[3] for p in positions]
            bbox = f"x:[{min(xs)}-{max(xs)+max(ws)}] y:[{min(ys)}-{max(ys)+max(hs)}]"
            sizes = f"w:[{min(ws)}-{max(ws)}] h:[{min(hs)}-{max(hs)}]"
            area = sum(w * h for _, _, w, h in positions)
        else:
            bbox = sizes = "N/A"
            area = 0

        self._pos_label.setText(
            f"Style {style_id} ({style.model_name}) | "
            f"LEDs: {led_count} (model says {style.led_count}) | "
            f"Segments: {style.segment_count} | Zones: {style.zone_count}\n"
            f"Bounding box: {bbox} | Sizes: {sizes} | "
            f"Total LED area: {area}px² / {460*460}px² panel = "
            f"{area*100/(460*460):.1f}%"
        )

        self._tick_count = 0
        self._update_status()

    # ================================================================
    # Animation tick — respects mode, color, brightness, zones, on/off
    # ================================================================

    MODE_NAMES = ["Static", "Breathing", "Colorful", "Rainbow", "Temp Link", "Load Link"]

    def _update_status(self):
        mode_name = self.MODE_NAMES[self._mode] if self._mode < len(self.MODE_NAMES) else "?"
        r, g, b = self._color
        on_count = sum(self._segment_on) if self._segment_on else 0
        total = len(self._segment_on)
        self._status_label.setText(
            f"Mode: {self._mode} ({mode_name}) | "
            f"Color: ({r},{g},{b}) | Bright: {self._brightness}% | "
            f"On: {'YES' if self._global_on else 'OFF'} | "
            f"Zone: {self._selected_zone}/{self._zone_count} | "
            f"Segments: {on_count}/{total} on"
        )

    def _tick(self):
        self._tick_count += 1

        # Update metrics
        m = _fake_metrics()
        self._led_panel.update_metrics(m)
        self._metrics_label.setText(
            f"CPU: {m.cpu_temp:.0f}°C {m.cpu_freq:.0f}MHz {m.cpu_percent:.0f}% | "
            f"GPU: {m.gpu_temp:.0f}°C {m.gpu_clock:.0f}MHz {m.gpu_usage:.0f}% | "
            f"MEM: {m.mem_temp:.0f}°C {m.mem_clock:.0f}MHz {m.mem_percent:.0f}% | "
            f"DISK: {m.disk_temp:.0f}°C {m.disk_activity:.0f}% "
            f"R:{m.disk_read:.0f}MB/s W:{m.disk_write:.0f}MB/s"
        )

        # Generate colors based on current mode
        positions = STYLE_POSITIONS.get(self._current_style, ())
        count = len(positions)
        if count == 0:
            return

        colors = self._generate_colors(count, m)

        # Apply brightness scaling
        bri = self._brightness / 100.0
        colors = [(int(r * bri), int(g * bri), int(b * bri)) for r, g, b in colors]

        # Global off → all black
        if not self._global_on:
            colors = [(0, 0, 0)] * count

        # Segment on/off → black out individual LEDs
        for i in range(min(count, len(self._segment_on))):
            if not self._segment_on[i]:
                colors[i] = (0, 0, 0)

        self._led_panel.set_led_colors(colors)

    def _generate_colors(self, count: int, m: HardwareMetrics) -> list[tuple[int, int, int]]:
        """Generate LED colors based on current mode."""
        r, g, b = self._color
        t = self._tick_count

        if self._mode == 0:
            # Static — solid user color
            return [(r, g, b)] * count

        elif self._mode == 1:
            # Breathing — pulse user color via sine wave
            pulse = (math.sin(t * 0.1) + 1) / 2  # 0.0 → 1.0
            pr = int(r * pulse)
            pg = int(g * pulse)
            pb = int(b * pulse)
            return [(pr, pg, pb)] * count

        elif self._mode == 2:
            # Colorful — each LED gets a different static hue
            colors = []
            for i in range(count):
                hue = (i * 360 // max(count, 1)) % 360
                c = QColor.fromHsv(hue, 255, 255)
                colors.append((c.red(), c.green(), c.blue()))
            return colors

        elif self._mode == 3:
            # Rainbow — shifting hues
            colors = []
            for i in range(count):
                hue = ((i + t) * 360 // max(count, 1)) % 360
                c = QColor.fromHsv(hue, 255, 255)
                colors.append((c.red(), c.green(), c.blue()))
            return colors

        elif self._mode == 4:
            # Temp link — blue→green→yellow→red based on CPU temp
            temp = m.cpu_temp
            return [self._temp_color(temp)] * count

        elif self._mode == 5:
            # Load link — blue→green→yellow→red based on CPU usage
            load = m.cpu_percent
            return [self._temp_color(load)] * count

        return [(r, g, b)] * count

    @staticmethod
    def _temp_color(value: float) -> tuple[int, int, int]:
        """Map 0-100 value to blue→cyan→green→yellow→red gradient."""
        value = max(0, min(100, value))
        if value < 25:
            t = value / 25
            return (0, int(255 * t), 255)          # blue → cyan
        elif value < 50:
            t = (value - 25) / 25
            return (0, 255, int(255 * (1 - t)))     # cyan → green
        elif value < 75:
            t = (value - 50) / 25
            return (int(255 * t), 255, 0)           # green → yellow
        else:
            t = (value - 75) / 25
            return (255, int(255 * (1 - t)), 0)     # yellow → red


def main():
    app = QApplication(sys.argv)
    app.setStyle('Fusion')

    dark = QPalette()
    dark.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark.setColor(QPalette.ColorRole.WindowText, QColor(200, 200, 200))
    dark.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    dark.setColor(QPalette.ColorRole.Text, QColor(200, 200, 200))
    dark.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark.setColor(QPalette.ColorRole.ButtonText, QColor(200, 200, 200))
    app.setPalette(dark)

    window = LEDPanelTestHarness()
    window.show()
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
