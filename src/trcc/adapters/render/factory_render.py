"""Renderer factory — creates QtRenderer."""
from __future__ import annotations

from trcc.core.ports import Renderer


def create_renderer() -> Renderer:
    """Create QtRenderer (primary renderer using C++ QPainter)."""
    from trcc.adapters.render.qt import QtRenderer
    return QtRenderer()
