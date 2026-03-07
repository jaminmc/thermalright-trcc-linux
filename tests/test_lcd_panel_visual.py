#!/usr/bin/env python3
"""Visual test harness for LCD preview — all resolutions and themes.

Exercises the rendering pipeline without a real USB device:
UCPreview widget, theme loading, overlay compositing, rotation,
brightness, and resolution switching.

Themes are loaded from ~/.trcc/.lcd_test/theme{W}{H}/ directories.
Copy or symlink theme folders there to test them.

Resolution buttons across the top, theme list on the left,
large preview center, controls on the right.

Usage:
    PYTHONPATH=src python3 tests/test_lcd_panel_visual.py
    PYTHONPATH=src python3 tests/test_lcd_panel_visual.py --overlay   # start with overlay
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
    QComboBox,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from trcc.adapters.infra.data_repository import ThemeDir
from trcc.core.models import FBL_TO_RESOLUTION
from trcc.qt_components.uc_preview import UCPreview
from trcc.services.image import ImageService
from trcc.services.overlay import OverlayService
from trcc.services.theme import ThemeInfo, ThemeService

_start_with_overlay = '--overlay' in sys.argv

# Test themes live here — separate from real app data
_TEST_DIR = Path.home() / '.trcc' / '.lcd_test'


# ── Test pattern generation ──────────────────────────────────────────

def _checkerboard(w: int, h: int, block: int = 16) -> QImage:
    """Generate a checkerboard test pattern at the given resolution."""
    img = QImage(w, h, QImage.Format.Format_RGB32)
    p = QPainter(img)
    for y in range(0, h, block):
        for x in range(0, w, block):
            c = QColor(200, 200, 200) if (x // block + y // block) % 2 == 0 else QColor(80, 80, 80)
            p.fillRect(x, y, block, block, c)
    # Draw resolution text in center
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
    """Main test window for LCD preview verification.

    - Resolution buttons: switch between all known FBL resolutions
    - Theme list: load real themes from ~/.trcc/.lcd_test/theme{W}{H}/
    - Test patterns: checkerboard / gradient for pixel-perfect checks
    - Overlay toggle, rotation, brightness controls
    """

    def __init__(self):
        super().__init__()
        self.setWindowTitle("LCD Panel Visual Test — All Resolutions")
        self.setMinimumSize(1200, 800)

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

        root = QHBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        # ── Left: theme list ─────────────────────────────────────
        left = QVBoxLayout()
        left.setSpacing(4)

        left.addWidget(self._make_label("Themes", bold=True))
        self._theme_list = QListWidget()
        self._theme_list.setStyleSheet(
            "QListWidget { background: #2a2a2a; color: #ccc; border: 1px solid #555; }"
            "QListWidget::item:selected { background: #1565C0; }"
        )
        self._theme_list.currentRowChanged.connect(self._on_theme_selected)
        left.addWidget(self._theme_list, 1)

        # Test pattern buttons
        pat_group = QGroupBox("Test Patterns")
        pat_group.setStyleSheet("QGroupBox { color: #aaa; border: 1px solid #555; padding-top: 14px; }")
        pat_layout = QVBoxLayout(pat_group)
        for label, fn in [("Checkerboard", self._show_checkerboard),
                          ("Gradient", self._show_gradient),
                          ("Black", self._show_black),
                          ("White", self._show_white)]:
            btn = QPushButton(label)
            btn.setStyleSheet("QPushButton { background: #333; color: #ccc; padding: 4px; }"
                              "QPushButton:hover { background: #444; }")
            btn.clicked.connect(fn)
            pat_layout.addWidget(btn)
        left.addWidget(pat_group)

        root.addLayout(left, 1)

        # ── Center: preview + resolution bar ─────────────────────
        center = QVBoxLayout()
        center.setSpacing(4)

        # Resolution buttons (two rows)
        res_group = QGroupBox("Resolution (FBL)")
        res_group.setStyleSheet("QGroupBox { color: #aaa; border: 1px solid #555; padding-top: 14px; }")
        res_layout = QVBoxLayout(res_group)

        # Deduplicate resolutions, sort by area
        unique_res = sorted(set(FBL_TO_RESOLUTION.values()),
                            key=lambda r: (r[0] * r[1], r[0]))

        self._res_buttons: list[QPushButton] = []
        row = QHBoxLayout()
        for i, (w, h) in enumerate(unique_res):
            btn = QPushButton(f"{w}x{h}")
            btn.setCheckable(True)
            btn.setMinimumHeight(28)
            btn.setStyleSheet(
                "QPushButton { background: #333; color: #ccc; border: 1px solid #555; "
                "border-radius: 3px; font-size: 10px; padding: 2px 6px; }"
                "QPushButton:checked { background: #1565C0; color: white; border: 2px solid #42A5F5; }"
                "QPushButton:hover { background: #444; }"
            )
            btn.clicked.connect(lambda _, r=(w, h): self._switch_resolution(*r))
            row.addWidget(btn)
            self._res_buttons.append(btn)
            if (i + 1) % 6 == 0:
                res_layout.addLayout(row)
                row = QHBoxLayout()
        if row.count():
            res_layout.addLayout(row)

        center.addWidget(res_group)

        # Status
        self._status = QLabel()
        self._status.setStyleSheet(
            "color: #ff8; font-size: 11px; font-family: monospace; "
            "background: #222; padding: 4px; border-radius: 3px;"
        )
        center.addWidget(self._status)

        # Preview widget
        self._preview = UCPreview(320, 320)
        center.addWidget(self._preview, 1, Qt.AlignmentFlag.AlignCenter)

        root.addLayout(center, 3)

        # ── Right: controls ──────────────────────────────────────
        right = QVBoxLayout()
        right.setSpacing(8)

        # Rotation
        rot_group = QGroupBox("Rotation")
        rot_group.setStyleSheet("QGroupBox { color: #aaa; border: 1px solid #555; padding-top: 14px; }")
        rot_layout = QVBoxLayout(rot_group)
        self._rot_combo = QComboBox()
        self._rot_combo.addItems(["0°", "90°", "180°", "270°"])
        self._rot_combo.setStyleSheet("background: #333; color: #ccc;")
        self._rot_combo.currentIndexChanged.connect(
            lambda i: self._set_rotation(i * 90))
        rot_layout.addWidget(self._rot_combo)
        right.addWidget(rot_group)

        # Brightness
        br_group = QGroupBox("Brightness")
        br_group.setStyleSheet("QGroupBox { color: #aaa; border: 1px solid #555; padding-top: 14px; }")
        br_layout = QVBoxLayout(br_group)
        self._br_slider = QSlider(Qt.Orientation.Horizontal)
        self._br_slider.setRange(10, 100)
        self._br_slider.setValue(100)
        self._br_slider.valueChanged.connect(self._set_brightness)
        br_layout.addWidget(self._br_slider)
        self._br_label = QLabel("100%")
        self._br_label.setStyleSheet("color: #ccc;")
        br_layout.addWidget(self._br_label)
        right.addWidget(br_group)

        # Overlay
        ov_group = QGroupBox("Overlay")
        ov_group.setStyleSheet("QGroupBox { color: #aaa; border: 1px solid #555; padding-top: 14px; }")
        ov_layout = QVBoxLayout(ov_group)
        self._ov_btn = QPushButton("Overlay: OFF")
        self._ov_btn.setCheckable(True)
        self._ov_btn.setChecked(self._overlay_enabled)
        self._ov_btn.setStyleSheet(
            "QPushButton { background: #333; color: #ccc; padding: 6px; }"
            "QPushButton:checked { background: #2E7D32; color: white; }"
        )
        self._ov_btn.toggled.connect(self._toggle_overlay)
        ov_layout.addWidget(self._ov_btn)
        right.addWidget(ov_group)

        # Info
        self._info = QLabel()
        self._info.setStyleSheet(
            "color: #8f8; font-size: 11px; font-family: monospace; "
            "background: #1a1a1a; padding: 6px; border-radius: 3px;"
        )
        self._info.setWordWrap(True)
        right.addWidget(self._info)

        right.addStretch(1)
        root.addLayout(right, 1)

        # ── Initialize ───────────────────────────────────────────
        self._switch_resolution(320, 320)
        self._show_checkerboard()

        # Overlay metrics timer (updates time/date/temp if overlay active)
        self._metrics_timer = QTimer(self)
        self._metrics_timer.timeout.connect(self._tick_overlay)
        self._metrics_timer.start(1000)

    def closeEvent(self, event):  # noqa: N802
        """Clean up working dir on close."""
        self._metrics_timer.stop()
        if self._working_dir.exists():
            shutil.rmtree(self._working_dir, ignore_errors=True)
        super().closeEvent(event)

    # ── Helpers ───────────────────────────────────────────────────

    @staticmethod
    def _make_label(text: str, bold: bool = False) -> QLabel:
        lbl = QLabel(text)
        weight = "bold" if bold else "normal"
        lbl.setStyleSheet(f"color: #ccc; font-weight: {weight}; font-size: 12px;")
        return lbl

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
        # Show preview offset info
        offset = UCPreview.RESOLUTION_OFFSETS.get(
            (self._width, self._height), UCPreview.DEFAULT_OFFSET)
        left, top, pw, ph, frame = offset
        self._info.setText(
            f"Preview offset:\n"
            f"  pos=({left},{top})\n"
            f"  size={pw}x{ph}\n"
            f"  frame={frame}\n"
            f"  scale={pw/self._width:.2f}x{ph/self._height:.2f}"
        )

    def _render_and_show(self):
        """Render current background with overlay/brightness and show in preview."""
        if self._current_bg is None:
            return

        r = ImageService._r()
        img = self._current_bg

        # Apply overlay if enabled
        if self._overlay_enabled and self._overlay_svc.enabled:
            overlay = self._overlay_svc.render()
            if overlay:
                img = r.composite(img, overlay, (0, 0))

        # Apply brightness
        if self._brightness < 100:
            img = r.apply_brightness(img, self._brightness)

        # Apply rotation
        if self._rotation:
            img = r.apply_rotation(img, self._rotation)

        self._preview.set_image(img)

    # ── Resolution switching ─────────────────────────────────────

    def _switch_resolution(self, w: int, h: int):
        self._width, self._height = w, h

        # Update button states
        unique_res = sorted(set(FBL_TO_RESOLUTION.values()),
                            key=lambda r: (r[0] * r[1], r[0]))
        for i, (rw, rh) in enumerate(unique_res):
            self._res_buttons[i].setChecked(rw == w and rh == h)

        # Recreate preview at new resolution
        self._preview.set_resolution(w, h)

        # Reset overlay for new resolution
        self._overlay_svc.set_config({})
        self._overlay_svc.enabled = False

        # Reload themes for this resolution
        self._load_themes()

        # Show checkerboard at new resolution
        self._show_checkerboard()
        self._update_info()

    # ── Theme loading ────────────────────────────────────────────

    def _load_themes(self):
        """Discover themes from ~/.trcc/.lcd_test/theme{W}{H}/."""
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
            # Clear working dir for this theme
            if self._working_dir.exists():
                shutil.rmtree(self._working_dir)
            self._working_dir.mkdir(parents=True, exist_ok=True)

            lcd_size = (self._width, self._height)
            data = ThemeService.load(theme, self._working_dir, lcd_size)

            if data.background is not None:
                # ThemeService.load returns QImage (via QtRenderer)
                self._current_bg = data.background
            elif data.is_animated and data.animation_path:
                self._preview.set_status(f"Video: {data.animation_path.name}")
                return
            else:
                self._current_bg = _checkerboard(self._width, self._height)

            # Load mask into overlay if theme has one
            if data.mask is not None:
                r = ImageService._r()
                mask_img = r.from_pil(data.mask)  # mask is PIL Image
                self._overlay_svc.set_mask(mask_img, data.mask_position)
                self._overlay_svc.enabled = True
                self._overlay_enabled = True
                self._ov_btn.setChecked(True)

            # Load overlay config from theme's DC file
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

    # ── Test patterns ────────────────────────────────────────────

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

    # ── Controls ─────────────────────────────────────────────────

    def _set_rotation(self, degrees: int):
        self._rotation = degrees
        self._render_and_show()
        self._update_status()

    def _set_brightness(self, val: int):
        self._brightness = val
        self._br_label.setText(f"{val}%")
        self._render_and_show()
        self._update_status()

    def _toggle_overlay(self, on: bool):
        self._overlay_enabled = on
        self._ov_btn.setText(f"Overlay: {'ON' if on else 'OFF'}")
        self._render_and_show()
        self._update_status()

    def _tick_overlay(self):
        """Update overlay metrics (time/date/temp) if active."""
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

    # Create test dir if it doesn't exist
    _TEST_DIR.mkdir(parents=True, exist_ok=True)

    window = LCDPanelTestHarness()
    window.show()
    print(f"Theme dir: {_TEST_DIR}")
    print("Copy theme folders to ~/.trcc/.lcd_test/theme{{W}}{{H}}/ to test them.")
    print("e.g. cp -r ~/.trcc/data/theme320320/Theme1 ~/.trcc/.lcd_test/theme320320/Theme1")
    sys.exit(app.exec())


if __name__ == '__main__':
    main()
