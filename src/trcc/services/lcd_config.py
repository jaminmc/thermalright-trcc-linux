"""LCD config persistence — per-device settings save/load.

Concrete DeviceConfigService for LCD. Adds apply_format_prefs
(LCD-specific overlay format preferences).
"""
from __future__ import annotations

from typing import Callable

from ..core.ports import DeviceConfigService


class LCDConfigService(DeviceConfigService):
    """LCD per-device config persistence — injected into LCDDevice.

    Inherits device_key, persist, get_config from DeviceConfigService.
    Adds apply_format_prefs for LCD overlay format preferences.
    """

    def __init__(
        self,
        config_key_fn: Callable[..., str],
        save_setting_fn: Callable[..., None],
        get_config_fn: Callable[..., dict],
        apply_format_prefs_fn: Callable[..., dict | None],
    ) -> None:
        super().__init__(config_key_fn, save_setting_fn, get_config_fn)
        self._apply_prefs_fn = apply_format_prefs_fn

    def apply_format_prefs(self, overlay_cfg: dict) -> None:
        """Apply user format preferences to an overlay config. LCD-specific."""
        self._apply_prefs_fn(overlay_cfg)
