#!/usr/bin/env python3
"""Visual test harness for LED panel — all 12 device styles.

Uses the real LEDService to compute LED colors (segment masks,
mode effects, metrics-linked gradients). Buttons across the top
to switch devices. Gray backdrop behind UCScreenLED so
missing/misplaced LEDs are immediately obvious.

All panel buttons wired: mode, color, brightness, zones, on/off.

Usage:
    PYTHONPATH=src python3 tests/test_led_panel_visual.py          # real metrics
    PYTHONPATH=src python3 tests/test_led_panel_visual.py --fake    # fake cycling
"""
from __future__ import annotations

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

from trcc.core.models import LED_STYLES, HardwareMetrics, LEDMode
from trcc.qt_components.uc_led_control import PREVIEW_X, PREVIEW_Y, UCLedControl
from trcc.qt_components.uc_screen_led import STYLE_POSITIONS
from trcc.services.led import LEDService

# ── Metrics source ────────────────────────────────────────────────
_use_fake = '--fake' in sys.argv
_tick = 0


def _get_metrics() -> HardwareMetrics:
    """Return real system metrics, or fake cycling ones with --fake."""
    if not _use_fake:
        from trcc.services.system import get_all_metrics
        return get_all_metrics()

    global _tick
    _tick += 1
    phase = (_tick % 100) / 100.0  # 0.0 → 1.0 sawtooth
    return HardwareMetrics(
        cpu_temp=30 + phase * 60,
        cpu_freq=800 + phase * 4200,
        cpu_percent=phase * 100,
        cpu_power=30 + phase * 120,
        gpu_temp=25 + phase * 70,
        gpu_clock=300 + phase * 1700,
        gpu_usage=phase * 100,
        gpu_power=50 + phase * 250,
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
        self._svc = LEDService()  # real effect engine
        self._tick_count = 0

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

        # ── Wire ALL panel signals (matches LEDHandler._connect_signals) ─
        p = self._led_panel
        p.mode_changed.connect(self._on_mode)
        p.color_changed.connect(self._on_color)
        p.brightness_changed.connect(self._on_brightness)
        p.global_toggled.connect(lambda on: self._svc.toggle_global(on))
        p.segment_clicked.connect(self._on_segment_click)
        p.zone_selected.connect(self._on_zone_selected)
        p.zone_toggled.connect(lambda zi, on: self._svc.toggle_zone(zi, on))
        p.carousel_changed.connect(lambda on: self._svc.set_zone_sync(on))
        p.carousel_zone_changed.connect(
            lambda zi, sel: self._svc.set_zone_sync_zone(zi, sel))
        p.carousel_interval_changed.connect(
            lambda secs: self._svc.set_zone_sync_interval(secs))
        p.clock_format_changed.connect(
            lambda is_24h: self._svc.set_clock_format(is_24h))
        p.week_start_changed.connect(
            lambda is_sun: self._svc.set_week_start(is_sun))
        p.temp_unit_changed.connect(self._on_temp_unit)
        p.disk_index_changed.connect(
            lambda idx: self._svc.set_disk_index(idx))
        p.memory_ratio_changed.connect(self._on_memory_ratio)
        p.test_mode_changed.connect(
            lambda on: self._svc.set_test_mode(on))

        # ── Start with style 1 ───────────────────────────────────
        self._switch_style(1)

        # ── Timer: animate + metrics every 100ms ──────────────────
        self._timer = QTimer(self)
        self._timer.timeout.connect(self._tick)
        self._timer.start(100)

    # ================================================================
    # Signal handlers — zone-aware routing (matches LEDHandler)
    # ================================================================

    def _on_mode(self, mode: int):
        """Route mode: always global + also zone (matches qt_app_mvc LEDHandler)."""
        led_mode = LEDMode(mode)
        self._svc.set_mode(led_mode)
        if self._svc.state.zones:
            self._svc.set_zone_mode(self._led_panel.selected_zone, led_mode)

    def _on_color(self, r: int, g: int, b: int):
        """Route color: always global + also zone (matches qt_app_mvc LEDHandler)."""
        self._svc.set_color(r, g, b)
        if self._svc.state.zones:
            self._svc.set_zone_color(self._led_panel.selected_zone, r, g, b)

    def _on_brightness(self, val: int):
        """Route brightness: always global + also zone (matches qt_app_mvc LEDHandler)."""
        self._svc.set_brightness(val)
        if self._svc.state.zones:
            self._svc.set_zone_brightness(self._led_panel.selected_zone, val)

    def _on_segment_click(self, idx: int):
        seg_on = self._svc.state.segment_on
        if 0 <= idx < len(seg_on):
            self._svc.toggle_segment(idx, not seg_on[idx])
            self._led_panel._preview.set_segment_on(idx, seg_on[idx])

    def _on_zone_selected(self, zone: int):
        """Select zone + load its state into panel, matching LEDHandler._on_zone_selected."""
        self._svc.set_selected_zone(zone)
        zones = self._svc.state.zones
        if 0 <= zone < len(zones):
            z = zones[zone]
            self._led_panel.load_zone_state(
                zone, z.mode.value, z.color, z.brightness, z.on)

    def _on_temp_unit(self, unit: str):
        """Forward temp unit to segment display."""
        seg_unit = "F" if unit == "\u00b0F" else "C"
        self._svc.set_seg_temp_unit(seg_unit)

    def _on_memory_ratio(self, ratio: int):
        self._svc.set_memory_ratio(ratio)
        self._led_panel.set_memory_ratio(ratio)

    # ================================================================
    # Device switching
    # ================================================================

    def _switch_style(self, style_id: int):
        self._current_style = style_id
        style = LED_STYLES[style_id]

        # Reset LEDService for this style
        self._svc = LEDService()
        self._svc.configure_for_style(style_id)
        self._svc.set_color(255, 0, 0)

        # Update button checked state
        sorted_styles = sorted(LED_STYLES.keys())
        for i, sid in enumerate(sorted_styles):
            self._device_buttons[i].setChecked(sid == style_id)

        # Initialize panel (matches LEDHandler.show())
        self._led_panel.initialize(
            style_id=style.style_id,
            segment_count=style.segment_count,
            zone_count=style.zone_count,
            model=style.model_name,
        )
        self._led_panel.set_memory_ratio(self._svc.state.memory_ratio)

        # Reset overlay positions
        positions = STYLE_POSITIONS.get(style_id, ())
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
        s = self._svc.state
        mv = s.mode.value
        mode_name = self.MODE_NAMES[mv] if mv < len(self.MODE_NAMES) else "?"
        r, g, b = s.color
        on_count = sum(s.segment_on) if s.segment_on else 0
        total = len(s.segment_on)
        self._status_label.setText(
            f"Mode: {mv} ({mode_name}) | "
            f"Color: ({r},{g},{b}) | Bright: {s.brightness}% | "
            f"On: {'YES' if s.global_on else 'OFF'} | "
            f"Zone: {s.selected_zone}/{s.zone_count} | "
            f"Segments: {on_count}/{total} on"
        )

    def _tick(self):
        self._tick_count += 1

        # Update metrics → service + panel gauges
        m = _get_metrics()
        self._svc.update_metrics(m)
        self._led_panel.update_metrics(m)
        self._metrics_label.setText(
            f"CPU: {m.cpu_temp:.0f}°C {m.cpu_freq:.0f}MHz {m.cpu_percent:.0f}% | "
            f"GPU: {m.gpu_temp:.0f}°C {m.gpu_clock:.0f}MHz {m.gpu_usage:.0f}% | "
            f"MEM: {m.mem_temp:.0f}°C {m.mem_clock:.0f}MHz {m.mem_percent:.0f}% | "
            f"DISK: {m.disk_temp:.0f}°C {m.disk_activity:.0f}% "
            f"R:{m.disk_read:.0f}MB/s W:{m.disk_write:.0f}MB/s"
        )

        # Real LEDService tick → segment masks + mode effects
        colors = self._svc.tick()
        display_colors = self._svc.apply_mask(colors)
        self._led_panel.set_led_colors(display_colors)
        self._update_status()


def main():
    argv = [a for a in sys.argv if a != '--fake']
    app = QApplication(argv)
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
