"""LED config persistence — save/load LEDState to conf.py.

Extracted from LEDService (SRP). Memento pattern — _PERSIST_FIELDS and
_ALIASES define the serialization schema. All functions operate on provided
state; no mutable service state.
"""
from __future__ import annotations

import logging
from typing import Any, Dict

from ..core.models import LEDMode, LEDState

log = logging.getLogger(__name__)

# Config persistence field map: config_key → LEDState attribute.
# One map drives both save and load — add a field here once.
_PERSIST_FIELDS: Dict[str, str] = {
    'mode': 'mode',
    'color': 'color',
    'brightness': 'brightness',
    'global_on': 'global_on',
    'segments_on': 'segment_on',
    'temp_source': 'temp_source',
    'load_source': 'load_source',
    'is_timer_24h': 'is_timer_24h',
    'is_week_sunday': 'is_week_sunday',
    'disk_index': 'disk_index',
    'memory_ratio': 'memory_ratio',
    'zone_sync': 'zone_sync',
    'zone_sync_interval': 'zone_sync_interval',
}

# Backward-compat aliases (v5.0.x config keys → current keys)
_ALIASES: Dict[str, str] = {
    'zone_carousel': 'zone_sync',
    'zone_carousel_zones': 'zone_sync_zones',
    'zone_carousel_interval': 'zone_sync_interval',
}


def _serialize(val: Any) -> Any:
    """Convert a state value for JSON-safe config storage."""
    if isinstance(val, LEDMode):
        return val.value
    if isinstance(val, tuple):
        return list(val)
    return val


def save_led_config(state: LEDState, device_key: str) -> None:
    """Serialize LEDState to config file."""
    try:
        from ..conf import Settings

        config: Dict[str, Any] = {
            ck: _serialize(getattr(state, sa))
            for ck, sa in _PERSIST_FIELDS.items()
        }
        config['zone_sync_zones'] = state.zone_sync_zones
        config['zones'] = [
            {'mode': z.mode.value, 'color': list(z.color),
             'brightness': z.brightness, 'on': z.on}
            for z in state.zones
        ]
        Settings.save_device_setting(device_key, 'led_config', config)
    except Exception as e:
        log.error("Failed to save LED config: %s", e)


def load_led_config(state: LEDState, device_key: str) -> None:
    """Deserialize LEDState from config file."""
    try:
        from ..conf import Settings

        dev_config = Settings.get_device_config(device_key)
        led_config = dev_config.get('led_config', {})
        if not led_config:
            return

        # Backward-compat aliases (v5.0.x: zone_carousel → zone_sync)
        for old, new in _ALIASES.items():
            if old in led_config and new not in led_config:
                led_config[new] = led_config[old]

        # Scalar and simple-list fields
        for ck, sa in _PERSIST_FIELDS.items():
            if ck in led_config:
                val = led_config[ck]
                cur = getattr(state, sa)
                if isinstance(cur, LEDMode):
                    val = LEDMode(val)
                elif isinstance(cur, tuple):
                    val = tuple(val)
                setattr(state, sa, val)

        # Zone sync zones: partial update (saved length may differ from current)
        if 'zone_sync_zones' in led_config:
            saved = led_config['zone_sync_zones']
            for i in range(min(len(saved), len(state.zone_sync_zones))):
                state.zone_sync_zones[i] = saved[i]

        # Per-zone states
        if 'zones' in led_config and state.zones:
            for i, zc in enumerate(led_config['zones']):
                if i < len(state.zones):
                    z = state.zones[i]
                    z.mode = LEDMode(zc.get('mode', 0))
                    z.color = tuple(zc.get('color', (255, 0, 0)))
                    z.brightness = zc.get('brightness', 100)
                    z.on = zc.get('on', True)
    except Exception as e:
        log.error("Failed to load LED config: %s", e)
