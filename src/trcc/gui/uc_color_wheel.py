#!/usr/bin/env python3
"""
Interactive HSV color wheel widget for LED control panels.

Matches C# UCColorA: rainbow ring image (D3旋钮), click/drag hue
selection, and center on/off toggle button (D3开关/D3开关a).

The D3旋钮 image has colors going clockwise from Red at top:
  Red → Magenta → Blue → Cyan → Green → Yellow → Red
This is the reverse of standard HSV hue order.

Mapping: HSV hue = (math_angle + 270) % 360, where math_angle is
standard atan2 (0°=right, CCW positive).  Inverse for dot placement:
math_angle = (hue - 270) % 360.

Original color ring by Lcstyle (GitHub PR #9).
"""

import math
from typing import Optional

from PySide6.QtCore import QPointF, QRectF, Qt, Signal
from PySide6.QtGui import (
    QBrush,
    QColor,
    QConicalGradient,
    QPainter,
    QPainterPath,
    QPen,
    QPixmap,
)
from PySide6.QtWidgets import QPushButton, QWidget

from .assets import Assets


class UCColorWheel(QWidget):
    """Circular hue ring with click/drag selection and center on/off toggle.

    Uses C# D3旋钮 image as the ring visual (falls back to QPainter
    conical gradient if asset is missing).  Center button toggles LED
    on/off (C# UCColorA.buttonDSHX with D3开关/D3开关a images).

    Attributes:
        hue_changed: Emitted when the user selects a hue (0-360).
        onoff_changed: Emitted when center on/off button is toggled (0 or 1).
    """

    hue_changed = Signal(int)
    onoff_changed = Signal(int)

    # Ring geometry (relative to widget center) — matches D3旋钮 (216x216)
    OUTER_RADIUS = 105
    INNER_RADIUS = 78
    SELECTOR_RADIUS = 8

    # C# UCColorA: clicks accepted in ring between MinR=60 and MaxR=110
    _MIN_RING_R = 60
    _MAX_RING_R = 110

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._hue = 0
        self._dragging = False
        self._onoff = 1  # 1=ON, 0=OFF (C# default: ON)

        # Load C# color wheel asset
        path = Assets.get('D3旋钮')
        self._ring_pixmap: Optional[QPixmap] = QPixmap(path) if path else None

        # Center on/off button (C# UCColorA.buttonDSHX — D3开关/D3开关a)
        self._onoff_btn = QPushButton(self)
        btn_size = 50
        self._onoff_btn.setFixedSize(btn_size, btn_size)
        self._onoff_btn.setFlat(True)
        off_path = Assets.get('D3开关')
        on_path = Assets.get('D3开关a')
        if off_path and on_path:
            self._onoff_btn.setStyleSheet(
                f"QPushButton {{ border: none; "
                f"background-image: url({on_path}); "
                f"background-repeat: no-repeat; "
                f"background-position: center; }}"
                f"QPushButton:hover {{ background-color: rgba(255,255,255,20); }}"
            )
        else:
            self._onoff_btn.setStyleSheet(
                "QPushButton { background: rgba(60,60,60,180); border: none; "
                "color: #0ff; font-size: 16px; border-radius: 25px; }"
                "QPushButton:hover { background: rgba(80,80,80,200); }"
            )
            self._onoff_btn.setText("\u23FB")  # Power symbol
        self._onoff_btn.setToolTip("Turn LEDs on / off")
        self._onoff_btn.clicked.connect(self._toggle_onoff)

        # Store asset paths for toggling
        self._on_img = on_path
        self._off_img = off_path

    def resizeEvent(self, event):
        super().resizeEvent(event)
        # Center the on/off button
        btn = self._onoff_btn
        btn.move(
            (self.width() - btn.width()) // 2,
            (self.height() - btn.height()) // 2,
        )

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def set_hue(self, hue: int) -> None:
        """Set the current hue without emitting a signal."""
        self._hue = hue % 360
        self.update()

    def set_onoff(self, val: int) -> None:
        """Set on/off state without emitting a signal.

        Args:
            val: 1=ON, 0=OFF.
        """
        self._onoff = val
        self._update_onoff_image()

    # ----------------------------------------------------------------
    # Painting
    # ----------------------------------------------------------------

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.setRenderHint(QPainter.RenderHint.Antialiasing)

        cx = self.width() / 2.0
        cy = self.height() / 2.0

        if self._ring_pixmap and not self._ring_pixmap.isNull():
            # Draw C# D3旋钮 image scaled to widget
            painter.setRenderHint(QPainter.RenderHint.SmoothPixmapTransform)
            painter.drawPixmap(
                QRectF(0, 0, self.width(), self.height()),
                self._ring_pixmap,
                QRectF(self._ring_pixmap.rect()),
            )
        else:
            # Fallback: draw conical gradient ring
            outer = self.OUTER_RADIUS
            inner = self.INNER_RADIUS
            gradient = QConicalGradient(cx, cy, 0)
            for i in range(13):
                stop = i / 12.0
                gradient.setColorAt(
                    stop, QColor.fromHsv(int(stop * 360) % 360, 255, 255))
            ring = QPainterPath()
            ring.addEllipse(QPointF(cx, cy), outer, outer)
            hole = QPainterPath()
            hole.addEllipse(QPointF(cx, cy), inner, inner)
            ring = ring.subtracted(hole)
            painter.setPen(Qt.PenStyle.NoPen)
            painter.setBrush(QBrush(gradient))
            painter.drawPath(ring)

        # --- Selector indicator on the ring midpoint ---
        # Convert HSV hue back to math angle for position on the ring.
        # D3旋钮 goes CW from Red: Red→Magenta→Blue→Cyan→Green→Yellow.
        # Inverse of hue=(math_angle+270)%360 → math_angle=(hue-270)%360
        mid_r = (self.OUTER_RADIUS + self.INNER_RADIUS) / 2.0
        math_angle = (self._hue - 270) % 360
        angle_rad = math.radians(math_angle)
        sx = cx + mid_r * math.cos(angle_rad)
        sy = cy - mid_r * math.sin(angle_rad)

        painter.setPen(QPen(QColor(255, 255, 255), 2))
        painter.setBrush(QBrush(QColor.fromHsv(self._hue, 255, 255)))
        painter.drawEllipse(
            QPointF(sx, sy), self.SELECTOR_RADIUS, self.SELECTOR_RADIUS)

        painter.end()

    # ----------------------------------------------------------------
    # Mouse interaction
    # ----------------------------------------------------------------

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if self._is_on_ring(event.position()):
                self._dragging = True
                self._update_hue_from_pos(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_hue_from_pos(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _is_on_ring(self, pos) -> bool:
        """Check if position is within the annular ring (not center button)."""
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        dist = math.hypot(pos.x() - cx, pos.y() - cy)
        return self._MIN_RING_R <= dist <= self._MAX_RING_R

    def _update_hue_from_pos(self, pos):
        """Convert mouse position to HSV hue matching the D3旋钮 image.

        The D3旋钮 image has colors going CW from Red at top:
        Red → Magenta → Blue → Cyan → Green → Yellow → Red
        (reverse of standard HSV order).
        Standard math atan2 gives 0°=right, CCW positive.
        Conversion: hue = (math_angle + 270) % 360.
        """
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        dx = pos.x() - cx
        dy = -(pos.y() - cy)  # invert Y for math coords
        math_angle = math.degrees(math.atan2(dy, dx))
        if math_angle < 0:
            math_angle += 360
        hue = int(math_angle + 270) % 360
        if hue != self._hue:
            self._hue = hue
            self.update()
            self.hue_changed.emit(hue)

    # ----------------------------------------------------------------
    # Center on/off toggle
    # ----------------------------------------------------------------

    def _toggle_onoff(self):
        """Toggle LED on/off state (C# UCColorA.buttonDSHX_Click)."""
        self._onoff = 0 if self._onoff == 1 else 1
        self._update_onoff_image()
        self.onoff_changed.emit(self._onoff)

    def _update_onoff_image(self):
        """Switch center button image between ON/OFF states."""
        if self._on_img and self._off_img:
            img = self._on_img if self._onoff == 1 else self._off_img
            self._onoff_btn.setStyleSheet(
                f"QPushButton {{ border: none; "
                f"background-image: url({img}); "
                f"background-repeat: no-repeat; "
                f"background-position: center; }}"
                f"QPushButton:hover {{ background-color: rgba(255,255,255,20); }}"
            )
        elif not self._on_img:
            color = "#0ff" if self._onoff == 1 else "#666"
            self._onoff_btn.setStyleSheet(
                f"QPushButton {{ background: rgba(60,60,60,180); border: none; "
                f"color: {color}; font-size: 16px; border-radius: 25px; }}"
                f"QPushButton:hover {{ background: rgba(80,80,80,200); }}"
            )
