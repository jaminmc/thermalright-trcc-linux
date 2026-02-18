#!/usr/bin/env python3
"""
Interactive HSV color wheel widget for LED control panels.

Renders a conical-gradient rainbow ring using QPainter. Click/drag on
the ring selects a hue (0-360) and emits ``hue_changed``.  A white
circle indicator tracks the current position on the ring.

Original implementation by Lcstyle (GitHub PR #9).
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
from PySide6.QtWidgets import QWidget

from .assets import Assets


class UCColorWheel(QWidget):
    """Circular hue ring with click/drag selection.

    Uses C# D3旋钮 image as the ring visual (falls back to QPainter
    conical gradient if asset is missing).

    Attributes:
        hue_changed: Emitted when the user selects a hue (0-360).
    """

    hue_changed = Signal(int)

    # Ring geometry (relative to widget center) — matches D3旋钮 (216x216)
    OUTER_RADIUS = 105
    INNER_RADIUS = 78
    SELECTOR_RADIUS = 8

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self._hue = 0
        self._dragging = False
        # Load C# color wheel asset
        path = Assets.get('D3旋钮')
        self._ring_pixmap: Optional[QPixmap] = QPixmap(path) if path else None

    # ----------------------------------------------------------------
    # Public API
    # ----------------------------------------------------------------

    def set_hue(self, hue: int) -> None:
        """Set the current hue without emitting a signal."""
        self._hue = hue % 360
        self.update()

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
        outer = self.OUTER_RADIUS
        inner = self.INNER_RADIUS
        mid_r = (outer + inner) / 2.0
        angle_rad = math.radians(self._hue)
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
            self._dragging = True
            self._update_hue_from_pos(event.position())

    def mouseMoveEvent(self, event):
        if self._dragging:
            self._update_hue_from_pos(event.position())

    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self._dragging = False

    def _update_hue_from_pos(self, pos):
        cx = self.width() / 2.0
        cy = self.height() / 2.0
        dx = pos.x() - cx
        dy = -(pos.y() - cy)  # invert Y for math coords
        angle = math.degrees(math.atan2(dy, dx))
        if angle < 0:
            angle += 360
        hue = int(angle) % 360
        if hue != self._hue:
            self._hue = hue
            self.update()
            self.hue_changed.emit(hue)
