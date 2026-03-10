"""Tests for services/led_config.py — LED state persistence (Memento pattern).

Covers:
- _serialize() — LEDMode enum, tuple, passthrough
- save_led_config() — serializes LEDState to config dict
- load_led_config() — deserializes config dict to LEDState
- Backward-compat aliases (zone_carousel → zone_sync)
- Partial zone restore (saved length ≠ current length)
- Per-zone state restore
- Missing/empty config graceful fallback
"""
from __future__ import annotations

from unittest.mock import patch

from trcc.core.models import LEDMode, LEDState, LEDZoneState
from trcc.services.led_config import (
    _ALIASES,
    _PERSIST_FIELDS,
    _serialize,
    load_led_config,
    save_led_config,
)

# Settings is lazy-imported inside functions via `from ..conf import Settings`
_SETTINGS_PATCH = 'trcc.conf.Settings'


# =========================================================================
# _serialize()
# =========================================================================


class TestSerialize:
    """_serialize — converts values for JSON-safe storage."""

    def test_led_mode_to_int(self):
        assert _serialize(LEDMode.STATIC) == 0
        assert _serialize(LEDMode.BREATHING) == 1
        assert _serialize(LEDMode.RAINBOW) == 3

    def test_tuple_to_list(self):
        assert _serialize((255, 0, 128)) == [255, 0, 128]

    def test_int_passthrough(self):
        assert _serialize(42) == 42

    def test_bool_passthrough(self):
        assert _serialize(True) is True

    def test_string_passthrough(self):
        assert _serialize("cpu") == "cpu"

    def test_list_passthrough(self):
        assert _serialize([1, 2, 3]) == [1, 2, 3]


# =========================================================================
# save_led_config()
# =========================================================================


class TestSaveLedConfig:
    """save_led_config — serializes LEDState to config file."""

    @patch(_SETTINGS_PATCH)
    def test_saves_all_persist_fields(self, mock_settings):
        state = LEDState(
            mode=LEDMode.BREATHING,
            color=(0, 255, 0),
            brightness=80,
            global_on=True,
            segment_on=[True, False, True],
            temp_source='gpu',
            load_source='cpu',
            is_timer_24h=False,
            is_week_sunday=True,
            disk_index=2,
            memory_ratio=4,
            zone_sync=True,
            zone_sync_interval=20,
        )
        save_led_config(state, 'dev_key')

        mock_settings.save_device_setting.assert_called_once()
        _, args, _ = mock_settings.save_device_setting.mock_calls[0]
        assert args[0] == 'dev_key'
        assert args[1] == 'led_config'
        config = args[2]

        assert config['mode'] == 1  # LEDMode.BREATHING.value
        assert config['color'] == [0, 255, 0]
        assert config['brightness'] == 80
        assert config['global_on'] is True
        assert config['segments_on'] == [True, False, True]
        assert config['temp_source'] == 'gpu'
        assert config['zone_sync'] is True
        assert config['zone_sync_interval'] == 20
        assert config['is_timer_24h'] is False
        assert config['is_week_sunday'] is True
        assert config['disk_index'] == 2
        assert config['memory_ratio'] == 4

    @patch(_SETTINGS_PATCH)
    def test_saves_zone_sync_zones(self, mock_settings):
        state = LEDState(zone_count=3)
        state.zone_sync_zones = [True, False, True]
        save_led_config(state, 'k')

        config = mock_settings.save_device_setting.call_args[0][2]
        assert config['zone_sync_zones'] == [True, False, True]

    @patch(_SETTINGS_PATCH)
    def test_saves_per_zone_states(self, mock_settings):
        state = LEDState(zone_count=2)
        state.zones = [
            LEDZoneState(mode=LEDMode.RAINBOW, color=(10, 20, 30),
                         brightness=50, on=False),
            LEDZoneState(mode=LEDMode.STATIC, color=(255, 255, 255),
                         brightness=100, on=True),
        ]
        save_led_config(state, 'k')

        config = mock_settings.save_device_setting.call_args[0][2]
        assert len(config['zones']) == 2
        assert config['zones'][0] == {
            'mode': 3, 'color': [10, 20, 30], 'brightness': 50, 'on': False}
        assert config['zones'][1] == {
            'mode': 0, 'color': [255, 255, 255], 'brightness': 100, 'on': True}

    @patch(_SETTINGS_PATCH)
    def test_exception_does_not_propagate(self, mock_settings):
        mock_settings.save_device_setting.side_effect = RuntimeError("boom")
        state = LEDState()
        # Should log error but not raise
        save_led_config(state, 'k')


# =========================================================================
# load_led_config()
# =========================================================================


class TestLoadLedConfig:
    """load_led_config — deserializes config dict to LEDState."""

    @patch(_SETTINGS_PATCH)
    def test_loads_scalar_fields(self, mock_settings):
        mock_settings.get_device_config.return_value = {
            'led_config': {
                'mode': 2,
                'color': [100, 200, 50],
                'brightness': 90,
                'global_on': False,
                'temp_source': 'gpu',
                'load_source': 'gpu',
                'is_timer_24h': False,
                'is_week_sunday': True,
                'disk_index': 1,
                'memory_ratio': 4,
                'zone_sync': True,
                'zone_sync_interval': 25,
            }
        }
        state = LEDState()
        load_led_config(state, 'k')

        assert state.mode == LEDMode.COLORFUL
        assert state.color == (100, 200, 50)
        assert state.brightness == 90
        assert state.global_on is False
        assert state.temp_source == 'gpu'
        assert state.load_source == 'gpu'
        assert state.is_timer_24h is False
        assert state.is_week_sunday is True
        assert state.disk_index == 1
        assert state.memory_ratio == 4
        assert state.zone_sync is True
        assert state.zone_sync_interval == 25

    @patch(_SETTINGS_PATCH)
    def test_loads_segment_on(self, mock_settings):
        mock_settings.get_device_config.return_value = {
            'led_config': {'segments_on': [True, False, True, True]}
        }
        state = LEDState(segment_count=4)
        load_led_config(state, 'k')
        assert state.segment_on == [True, False, True, True]

    @patch(_SETTINGS_PATCH)
    def test_empty_config_is_noop(self, mock_settings):
        mock_settings.get_device_config.return_value = {}
        state = LEDState()
        original_mode = state.mode
        load_led_config(state, 'k')
        assert state.mode == original_mode

    @patch(_SETTINGS_PATCH)
    def test_empty_led_config_is_noop(self, mock_settings):
        mock_settings.get_device_config.return_value = {'led_config': {}}
        state = LEDState()
        original_mode = state.mode
        load_led_config(state, 'k')
        assert state.mode == original_mode

    @patch(_SETTINGS_PATCH)
    def test_alias_zone_carousel_to_zone_sync(self, mock_settings):
        """v5.0.x backward compat: zone_carousel → zone_sync."""
        mock_settings.get_device_config.return_value = {
            'led_config': {
                'zone_carousel': True,
                'zone_carousel_interval': 30,
            }
        }
        state = LEDState()
        load_led_config(state, 'k')
        assert state.zone_sync is True
        assert state.zone_sync_interval == 30

    @patch(_SETTINGS_PATCH)
    def test_alias_does_not_overwrite_new_key(self, mock_settings):
        """If both old and new keys exist, new key wins."""
        mock_settings.get_device_config.return_value = {
            'led_config': {
                'zone_carousel': True,
                'zone_sync': False,  # New key takes precedence
            }
        }
        state = LEDState()
        load_led_config(state, 'k')
        assert state.zone_sync is False

    @patch(_SETTINGS_PATCH)
    def test_zone_sync_zones_partial_restore(self, mock_settings):
        """Saved zones shorter than current — only updates saved portion."""
        mock_settings.get_device_config.return_value = {
            'led_config': {
                'zone_sync_zones': [False, True],
            }
        }
        state = LEDState(zone_count=4)
        # __post_init__ creates [True, False, False, False]
        load_led_config(state, 'k')
        assert state.zone_sync_zones == [False, True, False, False]

    @patch(_SETTINGS_PATCH)
    def test_zone_sync_zones_longer_saved(self, mock_settings):
        """Saved zones longer than current — only restores up to current length."""
        mock_settings.get_device_config.return_value = {
            'led_config': {
                'zone_sync_zones': [True, True, True, True, True],
            }
        }
        state = LEDState(zone_count=3)
        load_led_config(state, 'k')
        assert len(state.zone_sync_zones) == 3
        assert state.zone_sync_zones == [True, True, True]

    @patch(_SETTINGS_PATCH)
    def test_per_zone_restore(self, mock_settings):
        mock_settings.get_device_config.return_value = {
            'led_config': {
                'zones': [
                    {'mode': 3, 'color': [10, 20, 30],
                     'brightness': 40, 'on': False},
                    {'mode': 1, 'color': [255, 0, 0],
                     'brightness': 100, 'on': True},
                ]
            }
        }
        state = LEDState(zone_count=2)
        load_led_config(state, 'k')

        assert state.zones[0].mode == LEDMode.RAINBOW
        assert state.zones[0].color == (10, 20, 30)
        assert state.zones[0].brightness == 40
        assert state.zones[0].on is False
        assert state.zones[1].mode == LEDMode.BREATHING
        assert state.zones[1].color == (255, 0, 0)

    @patch(_SETTINGS_PATCH)
    def test_per_zone_fewer_saved_than_current(self, mock_settings):
        """Saved 1 zone, current has 3 — only first zone updated."""
        mock_settings.get_device_config.return_value = {
            'led_config': {
                'zones': [
                    {'mode': 2, 'color': [0, 0, 255],
                     'brightness': 50, 'on': True},
                ]
            }
        }
        state = LEDState(zone_count=3)
        load_led_config(state, 'k')
        assert state.zones[0].mode == LEDMode.COLORFUL
        assert state.zones[1].mode == LEDMode.STATIC  # Untouched default

    @patch(_SETTINGS_PATCH)
    def test_exception_does_not_propagate(self, mock_settings):
        mock_settings.get_device_config.side_effect = RuntimeError("boom")
        state = LEDState()
        load_led_config(state, 'k')  # Should log error, not raise


# =========================================================================
# Schema consistency
# =========================================================================


class TestSchema:
    """Verify persist field map and aliases are consistent."""

    def test_all_persist_fields_exist_on_led_state(self):
        state = LEDState()
        for attr in _PERSIST_FIELDS.values():
            assert hasattr(state, attr), f"LEDState missing attribute: {attr}"

    def test_aliases_map_to_known_keys(self):
        for old, new in _ALIASES.items():
            assert new in _PERSIST_FIELDS or new == 'zone_sync_zones', \
                f"Alias {old}→{new} doesn't map to a persist field or zone_sync_zones"
