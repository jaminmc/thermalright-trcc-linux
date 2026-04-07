"""BaseHandler — shared interface for device handlers.

Holds a Device, exposes what TrccApp needs to manage handlers
in the device index. LCD and LED handlers inherit from this.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.models import DeviceInfo

log = logging.getLogger(__name__)


class BaseHandler:
    """Shared handler interface. Holds a Device, exposes what TrccApp needs."""

    def __init__(self, device: Any, view: str) -> None:
        self._device = device
        self._view = view

    @property
    def view_name(self) -> str:
        return self._view

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._device.device_info if self._device else None

    def deactivate(self) -> None:
        """Pause this handler — called when switching away from device."""

    def cleanup(self) -> None:
        if self._device:
            self._device.cleanup()

    @property
    def device(self) -> Any:
        return self._device

    def handle_frame(self, image: Any) -> None:
        """Receive a rendered frame from the background tick loop.

        Override in subclass — LCD shows preview, LED updates color display.
        """

    def update_metrics(self, metrics: Any) -> None:
        """Override in subclass."""
