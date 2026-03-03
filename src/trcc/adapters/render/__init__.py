"""Render adapters — concrete Renderer implementations."""

from .numpy_renderer import NumpyRenderer
from .pil import PilRenderer

__all__ = ['NumpyRenderer', 'PilRenderer']
