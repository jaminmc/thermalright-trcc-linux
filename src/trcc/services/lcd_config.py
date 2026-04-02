"""LCD config persistence — per-device settings save/load.

Concrete DeviceConfigService for LCD. Adds apply_format_prefs
(LCD-specific overlay format preferences).
"""
from __future__ import annotations

from typing import Any, Callable

from ..core.ports import DeviceConfigService


class LCDConfigService(DeviceConfigService):
    """LCD per-device config persistence — injected into LCDDevice.

    Wraps Settings static methods behind a device-aware interface.
    LCDDevice calls persist/get_config with a device object — this
    service computes the config key internally.
    """

    def __init__(
        self,
        config_key_fn: Callable[..., str],
        save_setting_fn: Callable[..., None],
        get_config_fn: Callable[..., dict],
        apply_format_prefs_fn: Callable[..., None],
    ) -> None:
        self._config_key_fn = config_key_fn
        self._save_fn = save_setting_fn
        self._get_fn = get_config_fn
        self._apply_prefs_fn = apply_format_prefs_fn

    def device_key(self, dev: Any) -> str:
        return self._config_key_fn(dev.device_index, dev.vid, dev.pid)

    def persist(self, dev: Any, field: str, value: Any) -> None:
        if dev:
            self._save_fn(self.device_key(dev), field, value)

    def get_config(self, dev: Any) -> dict:
        if not dev:
            return {}
        return self._get_fn(self.device_key(dev))

    def apply_format_prefs(self, overlay_cfg: dict) -> None:
        """Apply user format preferences to an overlay config. LCD-specific."""
        self._apply_prefs_fn(overlay_cfg)
