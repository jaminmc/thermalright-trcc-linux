"""LED effect engine, device communication, and config persistence.

Pure Python, no Qt dependencies.
Absorbs business logic from LEDModel (effects), LEDController (protocol send),
and LEDDeviceController (config, protocol factory).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..core.models import HardwareMetrics, LEDMode, LEDState, LEDZoneState
from .led_effects import LEDEffectEngine

log = logging.getLogger(__name__)

# Config persistence field map: config_key → LEDState attribute.
# One map drives both save_config() and load_config() — add a field here once.
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


class LEDService:
    """LED state management, effect computation, config persistence, device send.

    Orchestrates:
    - State mutation (set_mode, set_color, set_brightness, toggles)
    - Effect computation (tick -> per-segment colors)
    - Protocol send (build packet, send via LedProtocol)
    - Config save/load (serialize LEDState to conf.py)
    - Style resolution (model_name -> style_id)
    """

    # Styles where the checkbox means "Select all" (sync all zones)
    # instead of "Circulate" (timer rotation). C# FormLED.cs buttonLB_Click.
    SELECT_ALL_STYLES = frozenset({2, 7})

    # Methods delegated to LEDEffectEngine via __getattr__
    _ENGINE_METHODS = frozenset({
        '_tick_single_mode', '_tick_test_mode', '_tick_multi_zone',
        '_tick_breathing_for', '_tick_colorful_for', '_tick_rainbow_for',
        '_tick_temp_linked_for', '_tick_load_linked_for', '_next_sync_zone',
    })

    def __init__(self, state: LEDState | None = None) -> None:
        self.state = state or LEDState()
        self._metrics: HardwareMetrics = HardwareMetrics()
        self._engine = LEDEffectEngine(self.state, self._metrics)
        self._protocol: Any = None

        # Segment display state (styles 1-11 — all digit-display LED devices)
        self._segment_mode = False
        self._segment_mask: Optional[List[bool]] = None
        self._seg_phase = 0          # Current rotation phase
        self._seg_tick_count = 0     # Ticks since last phase change
        self._seg_phase_ticks = self.state.carousel_interval
        self._seg_temp_unit = "C"    # "C" or "F"
        self._seg_display: Any = None  # SegmentDisplay instance

        # Device identity (for config persistence)
        self._device_key: Optional[str] = None
        self._led_style: int = 1

    # ── Style resolution (static) ───────────────────────────────────

    @staticmethod
    def resolve_style_id(model_name: str) -> int:
        """Resolve LED style_id from device model name.

        Replaces the view-layer iteration over LED_STYLES.
        """
        from ..adapters.device.led import LED_STYLES
        for style_id, style in LED_STYLES.items():
            if style.model_name == model_name:
                return style_id
        return 1

    @staticmethod
    def get_style_info(style_id: int) -> Any:
        """Get LedDeviceStyle for a style_id."""
        from ..adapters.device.led import LED_STYLES
        return LED_STYLES.get(style_id)

    # ── State mutators ──────────────────────────────────────────────

    def set_mode(self, mode: LEDMode) -> None:
        """Set LED effect mode."""
        self.state.mode = LEDMode(mode) if not isinstance(mode, LEDMode) else mode
        self.state.rgb_timer = 0
        return None

    def set_color(self, r: int, g: int, b: int) -> None:
        """Set global LED color."""
        self.state.color = (r, g, b)

    def set_brightness(self, brightness: int) -> None:
        """Set global brightness (0-100)."""
        self.state.brightness = max(0, min(100, brightness))

    def toggle_global(self, on: bool) -> None:
        """Set global on/off."""
        self.state.global_on = on

    def toggle_segment(self, index: int, on: bool) -> None:
        """Toggle a single LED segment."""
        if 0 <= index < len(self.state.segment_on):
            self.state.segment_on[index] = on

    def toggle_zone(self, zone: int, on: bool) -> None:
        """Toggle a specific zone on/off (C# myOnOff1-4)."""
        if 0 <= zone < len(self.state.zones):
            self.state.zones[zone].on = on

    def set_test_mode(self, enabled: bool) -> None:
        """Toggle LED test mode (C# checkBox1).

        Cycles white/red/green/blue at brightness=1 every 10 ticks.
        """
        self.state.test_mode = enabled
        self.state.test_timer = 0
        self.state.test_color = 0

    def set_selected_zone(self, zone: int) -> None:
        """Set the currently selected zone (drives segment display phase)."""
        self.state.selected_zone = zone

    def set_zone_sync(self, enabled: bool) -> None:
        """Enable/disable zone sync (C# isLunBo).

        One checkbox, one flag. Style determines behavior:
        Styles 2/7: "Select all" — sync all zones to selected zone's settings.
        Other styles: "Circulate" — timer-based rotation through enabled zones.
        """
        self.state.zone_sync = enabled
        if enabled:
            if self._led_style in self.SELECT_ALL_STYLES:
                self._sync_all_zones_to_selected()
            else:
                self.state.zone_sync_ticks = 0
                self.state.zone_sync_current = self._next_sync_zone(-1)

    def set_zone_sync_zone(self, zone: int, selected: bool) -> None:
        """Toggle a zone's participation in sync rotation (C# LunBo1-4)."""
        if 0 <= zone < len(self.state.zone_sync_zones):
            if not selected:
                active = sum(self.state.zone_sync_zones)
                if active <= 1:
                    return
            self.state.zone_sync_zones[zone] = selected

    def set_zone_sync_interval(self, seconds: int) -> None:
        """Set sync interval in seconds (C# textBoxTimer)."""
        self.state.zone_sync_interval = max(1, seconds) * 6

    @property
    def _select_all_active(self) -> bool:
        """True when zone_sync is on AND style uses select-all behavior."""
        return self.state.zone_sync and self._led_style in self.SELECT_ALL_STYLES

    def set_zone_mode(self, zone: int, mode: LEDMode) -> None:
        """Set mode for a specific zone. Propagates to all if select-all active."""
        resolved = LEDMode(mode) if not isinstance(mode, LEDMode) else mode
        if self._select_all_active:
            for z in self.state.zones:
                z.mode = resolved
        elif 0 <= zone < len(self.state.zones):
            self.state.zones[zone].mode = resolved

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> None:
        """Set color for a specific zone. Propagates to all if select-all active."""
        if self._select_all_active:
            for z in self.state.zones:
                z.color = (r, g, b)
        elif 0 <= zone < len(self.state.zones):
            self.state.zones[zone].color = (r, g, b)

    def set_zone_brightness(self, zone: int, brightness: int) -> None:
        """Set brightness for a specific zone. Propagates to all if select-all active."""
        val = max(0, min(100, brightness))
        if self._select_all_active:
            for z in self.state.zones:
                z.brightness = val
        elif 0 <= zone < len(self.state.zones):
            self.state.zones[zone].brightness = val

    def set_disk_index(self, index: int) -> None:
        """Set which disk to monitor (C# hardDiskCount, 0-based)."""
        self.state.disk_index = max(0, index)

    def set_memory_ratio(self, ratio: int) -> None:
        """Set DDR memory multiplier (C# memoryRatio: 1, 2, or 4)."""
        self.state.memory_ratio = ratio if ratio in (1, 2, 4) else 2

    def set_sensor_source(self, source: str) -> None:
        """Set CPU/GPU source for temp/load linked modes and segment cycling."""
        self.state.temp_source = source
        self.state.load_source = source

    def set_seg_temp_unit(self, unit: str) -> None:
        """Set temperature unit for segment display ('C' or 'F')."""
        self._seg_temp_unit = unit
        if self._segment_mode:
            self._update_segment_mask()

    def set_clock_format(self, is_24h: bool) -> None:
        self.state.is_timer_24h = is_24h

    def set_week_start(self, is_sunday: bool) -> None:
        self.state.is_week_sunday = is_sunday

    def update_metrics(self, metrics: HardwareMetrics) -> None:
        """Update cached sensor metrics for temp/load-linked modes."""
        self._metrics = metrics
        self._engine.metrics = metrics

    def configure_for_style(self, style_id: int) -> None:
        """Configure state for a specific LED device style.

        Sets up LED segment counts/zones from the style registry and
        activates segment display rotation for digit-display styles (1-11).
        """
        from ..adapters.device.led import LED_STYLES
        from ..adapters.device.led_segment import get_display

        self._led_style = style_id
        style = LED_STYLES.get(style_id)
        if style:
            self.state.style = style.style_id
            self.state.led_count = style.led_count
            self.state.segment_count = style.segment_count
            self.state.zone_count = style.zone_count
            self.state.segment_on = [True] * style.segment_count
            if style.zone_count > 1:
                self.state.zones = [LEDZoneState() for _ in range(style.zone_count)]
            else:
                self.state.zones = []

        self._seg_display = get_display(style_id)
        self._segment_mode = self._seg_display is not None

        if self._segment_mode:
            self._seg_phase = 0
            self._seg_tick_count = 0
            self._update_segment_mask()

    # ── Effect engine ───────────────────────────────────────────────

    def tick(self) -> List[Tuple[int, int, int]]:
        """Advance animation one tick and return computed per-segment colors.

        Dispatches to mode-specific algorithm. For multi-zone devices,
        divides segments among zones and computes independently.
        For segment display styles, also advances the rotation phase.
        """
        # Test mode: cycle white/red/green/blue at brightness=1
        if self.state.test_mode:
            return self._tick_test_mode()

        # Segment display phase = active zone
        # Circulate ON: cycle through enabled zones on timer (C# GetVal + ValCount)
        # Circulate OFF: lock to selected zone (C# LunBo1-4 radio select)
        if self._segment_mode and self._seg_display:
            if self.state.zone_sync and self._led_style not in self.SELECT_ALL_STYLES:
                # Circulate: advance timer, rotate through enabled zones
                self.state.zone_sync_ticks += 1
                if self.state.zone_sync_ticks >= self.state.zone_sync_interval:
                    self.state.zone_sync_ticks = 0
                    self.state.zone_sync_current = self._next_sync_zone(
                        self.state.zone_sync_current)
                self._seg_phase = self.state.zone_sync_current
            else:
                self._seg_phase = self.state.selected_zone
            self._update_segment_mask()

        # Multi-zone segment displays
        if self._segment_mode and self.state.zones and self._seg_display:
            zone_map = self._seg_display.zone_led_map
            if zone_map:
                # Physical zones: each zone colors its own mapped LED indices
                return self._tick_multi_zone(zone_map)
            # Phase-rotating: active zone's color/mode for ALL LEDs
            active = self._seg_phase
            if 0 <= active < len(self.state.zones):
                z = self.state.zones[active]
                colors = self._tick_single_mode(z.mode, z.color,
                                                self.state.segment_count)
                if z.brightness < 100:
                    scale = z.brightness / 100.0
                    colors = [(int(r * scale), int(g * scale), int(b * scale))
                              for r, g, b in colors]
                return colors

        return self._tick_single_mode(self.state.mode, self.state.color,
                                      self.state.segment_count)

    # ── Segment display (all styles 1-11) ────────────────────────

    def _sync_all_zones_to_selected(self) -> None:
        """Copy selected zone's mode/color/brightness to all zones (Select all)."""
        zones = self.state.zones
        sel = self.state.selected_zone
        if not zones or sel < 0 or sel >= len(zones):
            return
        src = zones[sel]
        for z in zones:
            z.mode = src.mode
            z.color = src.color
            z.brightness = src.brightness

    def _next_sync_zone(self, current: int) -> int:
        """Find next enabled zone in carousel, wrapping around."""
        zones = self.state.zone_sync_zones
        n = len(zones)
        for offset in range(1, n + 1):
            candidate = (current + offset) % n
            if zones[candidate]:
                return candidate
        return current

    def _update_segment_mask(self) -> None:
        """Recompute segment mask from current metrics + rotation phase.

        Delegates to the unified SegmentDisplay class hierarchy in
        device_led_segment.py.  Each style handles its own phase/metric
        mapping internally.
        """
        if not self._seg_display:
            return
        self._segment_mask = self._seg_display.compute_mask(
            self._metrics,
            self._seg_phase,
            self._seg_temp_unit,
            is_24h=self.state.is_timer_24h,
            week_sunday=self.state.is_week_sunday,
            sub_style=self.state.sub_style,
            memory_ratio=self.state.memory_ratio,
        )

    # ── Display-ready colors ────────────────────────────────────────

    def apply_mask(self, colors: List[Tuple[int, int, int]]
                   ) -> List[Tuple[int, int, int]]:
        """Apply segment mask to produce per-LED color array.

        Returns the same masked array used for both hardware send and
        preview rendering — one entry per physical LED position.
        """
        if self._segment_mode and self._segment_mask:
            n = len(self._segment_mask)
            if len(colors) == n:
                # Per-LED colors (physical zone mapping)
                return [
                    colors[i] if self._segment_mask[i] else (0, 0, 0)
                    for i in range(n)
                ]
            base = colors[0] if colors else (0, 0, 0)
            return [
                base if self._segment_mask[i] else (0, 0, 0)
                for i in range(n)
            ]
        return colors

    # ── Protocol send ───────────────────────────────────────────────

    @property
    def has_protocol(self) -> bool:
        return self._protocol is not None

    def set_protocol(self, protocol: Any) -> None:
        self._protocol = protocol

    def send_colors(self, colors: List[Tuple[int, int, int]]) -> bool:
        """Send pre-computed colors to device. Returns success."""
        if not colors or not self._protocol:
            return False

        send_colors = self.apply_mask(colors)
        is_on = None if self._segment_mode else self.state.segment_on

        try:
            return self._protocol.send_led_data(
                send_colors, is_on, self.state.global_on, self.state.brightness
            )
        except Exception as e:
            log.debug("LED send error: %s", e)
            return False

    def send_tick(self) -> bool:
        """Tick animation and send colors to device. Returns success."""
        return self.send_colors(self.tick())

    @staticmethod
    def zones_to_ansi(colors: List[Tuple[int, int, int]]) -> str:
        """Render LED zone colors as ANSI true-color blocks for terminal preview."""
        if not colors:
            return ''
        parts = [
            f'\033[48;2;{r};{g};{b}m  \033[0m' for r, g, b in colors
        ]
        return ''.join(parts)

    # ── Device initialization ───────────────────────────────────────

    def initialize(self, device_info: Any, led_style: int = 1) -> str:
        """Initialize for a device. Returns status message."""
        from ..conf import Settings

        self._led_style = led_style
        self._device_key = Settings.device_config_key(
            getattr(device_info, 'device_index', 0),
            device_info.vid,
            device_info.pid,
        )

        self.configure_for_style(led_style)

        try:
            from ..adapters.device.factory import DeviceProtocolFactory
            protocol = DeviceProtocolFactory.get_protocol(device_info)
            protocol.handshake()  # Cache handshake result for wire remap
            self.set_protocol(protocol)
        except Exception as e:
            log.error("LED protocol error: %s", e)
            return f"LED protocol error: {e}"

        self.load_config()

        from ..adapters.device.led import LED_STYLES
        style = LED_STYLES.get(led_style)
        name = style.model_name if style else f"Style {led_style}"
        led_count = style.led_count if style else 0
        return f"LED: {name} ({led_count} LEDs)"

    # ── Config persistence ──────────────────────────────────────────

    @staticmethod
    def _serialize(val: Any) -> Any:
        """Convert a state value for JSON-safe config storage."""
        if isinstance(val, LEDMode):
            return val.value
        if isinstance(val, tuple):
            return list(val)
        return val

    def save_config(self) -> None:
        """Serialize LEDState to config file."""
        if not self._device_key:
            return
        try:
            from ..conf import Settings

            ser = self._serialize
            config: Dict[str, Any] = {
                ck: ser(getattr(self.state, sa))
                for ck, sa in _PERSIST_FIELDS.items()
            }
            config['zone_sync_zones'] = self.state.zone_sync_zones
            config['zones'] = [
                {'mode': z.mode.value, 'color': list(z.color),
                 'brightness': z.brightness, 'on': z.on}
                for z in self.state.zones
            ]
            Settings.save_device_setting(self._device_key, 'led_config', config)
        except Exception as e:
            log.error("Failed to save LED config: %s", e)

    def load_config(self) -> None:
        """Deserialize LEDState from config file."""
        if not self._device_key:
            return
        try:
            from ..conf import Settings

            dev_config = Settings.get_device_config(self._device_key)
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
                    cur = getattr(self.state, sa)
                    if isinstance(cur, LEDMode):
                        val = LEDMode(val)
                    elif isinstance(cur, tuple):
                        val = tuple(val)
                    setattr(self.state, sa, val)

            # Zone sync zones: partial update (saved length may differ from current)
            if 'zone_sync_zones' in led_config:
                saved = led_config['zone_sync_zones']
                for i in range(min(len(saved), len(self.state.zone_sync_zones))):
                    self.state.zone_sync_zones[i] = saved[i]

            # Per-zone states
            if 'zones' in led_config and self.state.zones:
                for i, zc in enumerate(led_config['zones']):
                    if i < len(self.state.zones):
                        z = self.state.zones[i]
                        z.mode = LEDMode(zc.get('mode', 0))
                        z.color = tuple(zc.get('color', (255, 0, 0)))
                        z.brightness = zc.get('brightness', 100)
                        z.on = zc.get('on', True)
        except Exception as e:
            log.error("Failed to load LED config: %s", e)

    def cleanup(self) -> None:
        """Save config and release protocol."""
        self.save_config()
        self.set_protocol(None)

    # ── Effect engine delegation ─────────────────────────────────

    def __getattr__(self, name: str):
        if name in self._ENGINE_METHODS:
            try:
                engine = object.__getattribute__(self, '_engine')
            except AttributeError:
                raise AttributeError(name) from None
            return getattr(engine, name)
        raise AttributeError(f'{type(self).__name__!r} has no attribute {name!r}')
