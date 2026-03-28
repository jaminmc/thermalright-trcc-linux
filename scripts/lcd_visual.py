#!/usr/bin/env python3
"""Visual harness for LCD preview — all resolutions and themes.

Exercises the rendering pipeline without a real USB device:
UCPreview widget, theme loading, overlay compositing, rotation,
brightness, and resolution switching.

Themes are loaded from ~/.trcc/.lcd_test/theme{W}{H}/ directories.
Copy or symlink theme folders there to test them.

Usage:
    PYTHONPATH=src python3 scripts/lcd_visual.py
    PYTHONPATH=src python3 scripts/lcd_visual.py --overlay   # start with overlay
"""
from __future__ import annotations

import os
import shutil
import sys
import tempfile

os.environ.setdefault('QT_QPA_PLATFORM', '')  # use real display

sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..', 'src'))

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QColor, QImage, QPainter, QPalette
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QScrollArea,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from trcc.adapters.infra.data_repository import ThemeDir
from trcc.adapters.render.qt import QtRenderer
from trcc.conf import init_settings
from trcc.core.builder import ControllerBuilder
from trcc.core.models import FBL_TO_RESOLUTION
from trcc.gui.uc_preview import UCPreview
from trcc.services.image import ImageService
from trcc.services.overlay import OverlayService
from trcc.services.theme import ThemeInfo, ThemeService

_start_with_overlay = '--overlay' in sys.argv

# Test themes live here — separate from real app data
_TEST_DIR = Path.home() / '.trcc' / '.lcd_test'

# Button style shared across all buttons
_BTN_STYLE = (
    "QPushButton { background: #333; color: #ccc; border: 1px solid #555; "
    "border-radius: 4px; font-size: 10px; padding: 2px 6px; }"
    "QPushButton:checked { background: #1565C0; color: white; "
    "border: 2px solid #42A5F5; }"
    "QPushButton:hover { background: #444; }"
)


# ── Test pattern generation ──────────────────────────────────────────

def _checkerboard(w: int, h: int, block: int = 16) -> QImage:
    """Generate a checkerboard test pattern at the given resolution."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    for y in range(0, h, block):
        for x in range(0, w, block):
            c = QColor(200, 200, 200) if (x // block + y // block) % 2 == 0 else QColor(80, 80, 80)
            p.fillRect(x, y, block, block, c)
    p.setPen(QColor(255, 100, 100))
    font = p.font()
    font.setPixelSize(max(16, min(w, h) // 8))
    p.setFont(font)
    p.drawText(img.rect(), Qt.AlignmentFlag.AlignCenter, f"{w}x{h}")
    p.end()
    return img


def _gradient(w: int, h: int) -> QImage:
    """Generate a horizontal RGB gradient test pattern."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    for x in range(w):
        r = int(255 * x / max(w - 1, 1))
        g = int(255 * (1 - x / max(w - 1, 1)))
        b = 128
        p.setPen(QColor(r, g, b))
        p.drawLine(x, 0, x, h)
    p.end()
    return img


# ── Main harness ─────────────────────────────────────────────────────

class LCDPanelTestHarness(QWidget):
    """LCD preview harness — vertical layout matching LED visual style.

    - Resolution buttons across the top
    - Status + info labels
    - UCPreview centered on gray backdrop in scroll area
    - Theme list + controls in bottom bar
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LCD Panel Visual — All Resolutions")
        self.setMinimumSize(1300, 900)

        # Persistent working dir for copy-based theme loading
        self._working_dir = Path(tempfile.mkdtemp(prefix='trcc_lcd_test_'))

        # State
        self._width, self._height = 320, 320
        self._rotation = 0
        self._brightness = 100
        self._overlay_svc = OverlayService(renderer=ImageService._r())
        self._overlay_enabled = _start_with_overlay
        self._current_bg: QImage | None = None
        self._themes: list[ThemeInfo] = []

        # Dark background
        self.setAutoFillBackground(True)
        pal = self.palette()
        pal.setColor(QPalette.ColorRole.Window, QColor(50, 50, 50))
        self.setPalette(pal)

        layout = QVBoxLayout(self)
        layout.setContentsMargins(4, 4, 4, 4)
        layout.setSpacing(4)

        # ── Resolution buttons bar ─────────────────────────────────
        btn_bar = QWidget()
        btn_layout = QHBoxLayout(btn_bar)
        btn_layout.setContentsMargins(0, 0, 0, 0)
        btn_layout.setSpacing(2)

        unique_res = sorted(set(FBL_TO_RESOLUTION.values()),
                            key=lambda r: (r[0] * r[1], r[0]))

        self._res_buttons: list[QPushButton] = []
        for w, h in unique_res:
            btn = QPushButton(f"{w}x{h}")
            btn.setCheckable(True)
            btn.setMinimumHeight(44)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(lambda _, r=(w, h): self._switch_resolution(*r))
            btn_layout.addWidget(btn)
            self._res_buttons.append(btn)

        layout.addWidget(btn_bar)

        # ── Status bar ─────────────────────────────────────────────
        self._status = QLabel()
        self._status.setStyleSheet(
            "color: #ff8; font-size: 11px; font-family: monospace; "
            "background: #222; padding: 4px; border-radius: 3px;"
        )
        layout.addWidget(self._status)

        # ── Info label ─────────────────────────────────────────────
        self._info = QLabel()
        self._info.setStyleSheet(
            "color: #8f8; font-size: 11px; font-family: monospace; "
            "background: #1a1a1a; padding: 4px; border-radius: 3px;"
        )
        self._info.setWordWrap(True)
        self._info.setMaximumHeight(80)
        layout.addWidget(self._info)

        # ── Scroll area with gray backdrop for UCPreview ───────────
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

        self._preview = UCPreview(320, 320)
        container_layout.addWidget(self._preview)

        scroll.setWidget(self._container)
        layout.addWidget(scroll, 1)

        # ── Bottom bar: themes + controls ──────────────────────────
        bottom = QHBoxLayout()
        bottom.setSpacing(6)

        # Theme list
        theme_col = QVBoxLayout()
        theme_col.setSpacing(2)
        theme_label = QLabel("Themes")
        theme_label.setStyleSheet("color: #ccc; font-weight: bold; font-size: 12px;")
        theme_col.addWidget(theme_label)

        self._theme_list = QListWidget()
        self._theme_list.setFixedHeight(140)
        self._theme_list.setStyleSheet(
            "QListWidget { background: #2a2a2a; color: #ccc; border: 1px solid #555; }"
            "QListWidget::item:selected { background: #1565C0; }"
        )
        self._theme_list.currentRowChanged.connect(self._on_theme_selected)
        theme_col.addWidget(self._theme_list)
        bottom.addLayout(theme_col, 2)

        # Test patterns
        pat_col = QVBoxLayout()
        pat_col.setSpacing(2)
        pat_label = QLabel("Patterns")
        pat_label.setStyleSheet("color: #ccc; font-weight: bold; font-size: 12px;")
        pat_col.addWidget(pat_label)
        for label, fn in [("Checkerboard", self._show_checkerboard),
                          ("Gradient", self._show_gradient),
                          ("Black", self._show_black),
                          ("White", self._show_white)]:
            btn = QPushButton(label)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(fn)
            pat_col.addWidget(btn)
        bottom.addLayout(pat_col, 1)

        # Rotation
        rot_col = QVBoxLayout()
        rot_col.setSpacing(2)
        rot_label = QLabel("Rotation")
        rot_label.setStyleSheet("color: #ccc; font-weight: bold; font-size: 12px;")
        rot_col.addWidget(rot_label)
        self._rot_buttons: list[QPushButton] = []
        for deg in [0, 90, 180, 270]:
            btn = QPushButton(f"{deg}°")
            btn.setCheckable(True)
            btn.setChecked(deg == 0)
            btn.setStyleSheet(_BTN_STYLE)
            btn.clicked.connect(lambda _, d=deg: self._set_rotation(d))
            rot_col.addWidget(btn)
            self._rot_buttons.append(btn)
        bottom.addLayout(rot_col, 1)

        # Brightness
        br_col = QVBoxLayout()
        br_col.setSpacing(2)
        self._br_label = QLabel("Brightness: 100%")
        self._br_label.setStyleSheet("color: #ccc; font-weight: bold; font-size: 12px;")
        br_col.addWidget(self._br_label)
        self._br_slider = QSlider(Qt.Orientation.Horizontal)
        self._br_slider.setRange(10, 100)
        self._br_slider.setValue(100)
        self._br_slider.valueChanged.connect(self._set_brightness)
        br_col.addWidget(self._br_slider)
        br_col.addStretch(1)
        bottom.addLayout(br_col, 1)

        # Overlay toggle
        ov_col = QVBoxLayout()
        ov_col.setSpacing(2)
        ov_label = QLabel("Overlay")
        ov_label.setStyleSheet("color: #ccc; font-weight: bold; font-size: 12px;")
        ov_col.addWidget(ov_label)
        self._ov_btn = QPushButton("OFF")
        self._ov_btn.setCheckable(True)
        self._ov_btn.setChecked(self._overlay_enabled)
        self._ov_btn.setMinimumHeight(44)
        self._ov_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; border: 1px solid #555; "
            "border-radius: 4px; padding: 6px; font-size: 12px; }"
            "QPushButton:checked { background: #2E7D32; color: white; "
            "border: 2px solid #66BB6A; }"
            "QPushButton:hover { background: #444; }"
        )
        self._ov_btn.toggled.connect(self._toggle_overlay)
        ov_col.addWidget(self._ov_btn)
        ov_col.addStretch(1)
        bottom.addLayout(ov_col, 1)

        layout.addLayout(bottom)

        # ── Initialize ─────────────────────────────────────────────
        self._switch_resolution(320, 320)
        self._show_checkerboard()

        # Overlay metrics timer (updates time/date/temp if overlay active)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.timeout.connect(self._tick_overlay)
        self._metrics_timer.start(1000)

    def closeEvent(self, event):  # noqa: N802
        self._metrics_timer.stop()
        if self._working_dir.exists():
            shutil.rmtree(self._working_dir, ignore_errors=True)
        super().closeEvent(event)

    # ── Status helpers ────────────────────────────────────────────

    def _update_status(self):
        overlay_text = "ON" if self._overlay_enabled else "OFF"
        theme_dir = _TEST_DIR / f'theme{self._width}{self._height}'
        self._status.setText(
            f"Resolution: {self._width}x{self._height} | "
            f"Rotation: {self._rotation}° | "
            f"Brightness: {self._brightness}% | "
            f"Overlay: {overlay_text} | "
            f"Themes: {len(self._themes)} | "
            f"Dir: {theme_dir}"
        )

    def _update_info(self):
        offset = UCPreview.RESOLUTION_OFFSETS.get(
            (self._width, self._height), UCPreview.DEFAULT_OFFSET)
        left, top, pw, ph, frame = offset
        self._info.setText(
            f"Preview: pos=({left},{top})  size={pw}x{ph}  "
            f"frame={frame}  scale={pw / self._width:.2f}x{ph / self._height:.2f}"
        )

    def _render_and_show(self):
        if self._current_bg is None:
            return

        r = ImageService._r()
        img = self._current_bg

        if self._overlay_enabled and self._overlay_svc.enabled:
            overlay = self._overlay_svc.render()
            if overlay:
                img = r.composite(img, overlay, (0, 0))

        if self._brightness < 100:
            img = r.apply_brightness(img, self._brightness)

        if self._rotation:
            img = r.apply_rotation(img, self._rotation)

        self._preview.set_image(img)

    # ── Resolution switching ──────────────────────────────────────

    def _switch_resolution(self, w: int, h: int):
        self._width, self._height = w, h

        unique_res = sorted(set(FBL_TO_RESOLUTION.values()),
                            key=lambda r: (r[0] * r[1], r[0]))
        for i, (rw, rh) in enumerate(unique_res):
            self._res_buttons[i].setChecked(rw == w and rh == h)

        self._preview.set_resolution(w, h)
        self._overlay_svc.set_config({})
        self._overlay_svc.enabled = False
        self._load_themes()
        self._show_checkerboard()
        self._update_info()

    # ── Theme loading ─────────────────────────────────────────────

    def _load_themes(self):
        self._theme_list.clear()
        self._themes = []

        theme_dir = _TEST_DIR / f'theme{self._width}{self._height}'
        if theme_dir.exists():
            self._themes = ThemeService.discover_local(
                theme_dir, (self._width, self._height))

        for theme in self._themes:
            item = QListWidgetItem(theme.name)
            item.setToolTip(str(theme.path))
            self._theme_list.addItem(item)

        self._update_status()

    def _on_theme_selected(self, row: int):
        if row < 0 or row >= len(self._themes):
            return
        theme = self._themes[row]
        try:
            if self._working_dir.exists():
                shutil.rmtree(self._working_dir)
            self._working_dir.mkdir(parents=True, exist_ok=True)

            lcd_size = (self._width, self._height)
            data = ThemeService.load(theme, self._working_dir, lcd_size)

            if data.background is not None:
                self._current_bg = data.background
            elif data.is_animated and data.animation_path:
                self._preview.set_status(f"Video: {data.animation_path.name}")
                return
            else:
                self._current_bg = _checkerboard(self._width, self._height)

            if data.mask is not None:
                r = ImageService._r()
                mask_img = r.from_pil(data.mask)
                self._overlay_svc.set_mask(mask_img, data.mask_position)
                self._overlay_svc.enabled = True
                self._overlay_enabled = True
                self._ov_btn.setChecked(True)

            td = ThemeDir(self._working_dir)
            if td.dc.exists():
                self._overlay_svc.load_from_dc(td.dc)
                if self._overlay_svc.config:
                    self._overlay_svc.enabled = True
                    self._overlay_enabled = True
                    self._ov_btn.setChecked(True)

            self._render_and_show()
            self._preview.set_status(f"Theme: {theme.name}")
        except Exception as e:
            import traceback
            traceback.print_exc()
            self._preview.set_status(f"Error: {e}")

    # ── Test patterns ─────────────────────────────────────────────

    def _show_checkerboard(self):
        self._current_bg = _checkerboard(self._width, self._height)
        self._render_and_show()
        self._preview.set_status(f"Checkerboard {self._width}x{self._height}")

    def _show_gradient(self):
        self._current_bg = _gradient(self._width, self._height)
        self._render_and_show()
        self._preview.set_status(f"Gradient {self._width}x{self._height}")

    def _show_black(self):
        img = QImage(self._width, self._height, QImage.Format.Format_RGB32)
        img.fill(QColor(0, 0, 0))
        self._current_bg = img
        self._render_and_show()
        self._preview.set_status("Black")

    def _show_white(self):
        img = QImage(self._width, self._height, QImage.Format.Format_RGB32)
        img.fill(QColor(255, 255, 255))
        self._current_bg = img
        self._render_and_show()
        self._preview.set_status("White")

    # ── Controls ──────────────────────────────────────────────────

    def _set_rotation(self, degrees: int):
        self._rotation = degrees
        for i, btn in enumerate(self._rot_buttons):
            btn.setChecked(i * 90 == degrees)
        self._render_and_show()
        self._update_status()

    def _set_brightness(self, val: int):
        self._brightness = val
        self._br_label.setText(f"Brightness: {val}%")
        self._render_and_show()
        self._update_status()

    def _toggle_overlay(self, on: bool):
        self._overlay_enabled = on
        self._ov_btn.setText("ON" if on else "OFF")
        self._render_and_show()
        self._update_status()

    def _tick_overlay(self):
        if self._overlay_enabled and self._overlay_svc.enabled and self._current_bg is not None:
            self._render_and_show()


def main():
    argv = [a for a in sys.argv if not a.startswith('--')]
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

    init_settings(ControllerBuilder.build_setup())
    ImageService.set_renderer(QtRenderer())

    _TEST_DIR.mkdir(parents=True, exist_ok=True)

    window = LCDPanelTestHarness()
    window.show()
    print(f"Theme dir: {_TEST_DIR}")
    print("Copy theme folders to ~/.trcc/.lcd_test/theme{{W}}{{H}}/ to test them.")
    print("e.g. cp -r ~/.trcc/data/theme320320/Theme1 ~/.trcc/.lcd_test/theme320320/Theme1")
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
