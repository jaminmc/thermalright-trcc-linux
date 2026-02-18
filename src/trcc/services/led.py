"""LED effect engine, device communication, and config persistence.

Pure Python, no Qt dependencies.
Absorbs business logic from LEDModel (effects), LEDController (HR10, protocol send),
and LEDDeviceController (config, protocol factory).
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from ..core.models import HardwareMetrics, LEDMode, LEDState, LEDZoneState

log = logging.getLogger(__name__)


class LEDService:
    """LED state management, effect computation, config persistence, device send.

    Orchestrates:
    - State mutation (set_mode, set_color, set_brightness, toggles)
    - Effect computation (tick -> per-segment colors)
    - HR10 7-segment rendering
    - Protocol send (build packet, send via LedProtocol)
    - Config save/load (serialize LEDState to conf.py)
    - Style resolution (model_name -> style_id)
    """

    def __init__(self, state: LEDState | None = None) -> None:
        self.state = state or LEDState()
        self._metrics: HardwareMetrics = HardwareMetrics()
        self._protocol: Any = None

        # HR10 state (style 13 — 7-segment digit rendering)
        self._hr10_mode = False
        self._hr10_display_text = "---"
        self._hr10_indicators: set = {'deg'}
        self._hr10_mask: Optional[List[bool]] = None

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

    def set_zone_carousel(self, enabled: bool) -> None:
        """Enable/disable zone carousel (C# isLunBo)."""
        self.state.zone_carousel = enabled
        if enabled:
            self.state.zone_carousel_ticks = 0
            self.state.zone_carousel_current = self._next_carousel_zone(-1)

    def set_zone_carousel_zone(self, zone: int, selected: bool) -> None:
        """Toggle a zone's participation in carousel (C# LunBo1-4)."""
        if 0 <= zone < len(self.state.zone_carousel_zones):
            # Ensure at least one zone remains selected
            if not selected:
                active = sum(self.state.zone_carousel_zones)
                if active <= 1:
                    return
            self.state.zone_carousel_zones[zone] = selected

    def set_zone_carousel_interval(self, seconds: int) -> None:
        """Set carousel interval in seconds (C# textBoxTimer)."""
        self.state.zone_carousel_interval = max(1, seconds) * 6

    def _next_carousel_zone(self, current: int) -> int:
        """Find next enabled zone in carousel, wrapping around."""
        zones = self.state.zone_carousel_zones
        n = len(zones)
        for offset in range(1, n + 1):
            candidate = (current + offset) % n
            if zones[candidate]:
                return candidate
        return 0

    def set_zone_mode(self, zone: int, mode: LEDMode) -> None:
        """Set mode for a specific zone."""
        if 0 <= zone < len(self.state.zones):
            self.state.zones[zone].mode = LEDMode(mode) if not isinstance(mode, LEDMode) else mode

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> None:
        """Set color for a specific zone."""
        if 0 <= zone < len(self.state.zones):
            self.state.zones[zone].color = (r, g, b)

    def set_zone_brightness(self, zone: int, brightness: int) -> None:
        """Set brightness for a specific zone."""
        if 0 <= zone < len(self.state.zones):
            self.state.zones[zone].brightness = max(0, min(100, brightness))

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

    def configure_for_style(self, style_id: int) -> None:
        """Configure state for a specific LED device style.

        Sets up LED segment counts/zones from the style registry,
        activates HR10 mode for style 13, and activates segment
        display rotation for digit-display styles (1-11).
        """
        from ..adapters.device.led import LED_STYLES
        from ..adapters.device.led_segment import get_display

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

        self._hr10_mode = (style_id == 13)
        self._seg_display = get_display(style_id)
        self._segment_mode = self._seg_display is not None

        if self._hr10_mode:
            self._update_hr10_mask()
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

        # Advance segment display rotation (all digit-display styles)
        if self._segment_mode and self._seg_display:
            self._seg_tick_count += 1
            if self._seg_tick_count >= self._seg_phase_ticks:
                self._seg_tick_count = 0
                self._seg_phase = self._next_phase()
            self._update_segment_mask()

        if self.state.zone_count > 1 and self.state.zones:
            return self._tick_multi_zone()
        return self._tick_single_mode(self.state.mode, self.state.color,
                                      self.state.segment_count)

    def _tick_single_mode(self, mode: LEDMode, color: Tuple[int, int, int],
                          seg_count: int) -> List[Tuple[int, int, int]]:
        """Compute colors for a single mode across seg_count segments."""
        if mode == LEDMode.STATIC:
            return [color] * seg_count
        elif mode == LEDMode.BREATHING:
            return self._tick_breathing_for(color, seg_count)
        elif mode == LEDMode.COLORFUL:
            return self._tick_colorful_for(seg_count)
        elif mode == LEDMode.RAINBOW:
            return self._tick_rainbow_for(seg_count)
        elif mode == LEDMode.TEMP_LINKED:
            return self._tick_temp_linked_for(seg_count)
        elif mode == LEDMode.LOAD_LINKED:
            return self._tick_load_linked_for(seg_count)
        return [(0, 0, 0)] * seg_count

    _TEST_COLORS = [(1, 1, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1)]

    def _tick_test_mode(self) -> List[Tuple[int, int, int]]:
        """C# checkBox1 test mode: cycle 4 colors every 10 ticks at min brightness."""
        self.state.test_timer += 1
        if self.state.test_timer >= 10:
            self.state.test_timer = 0
            self.state.test_color = (self.state.test_color + 1) % 4
        color = self._TEST_COLORS[self.state.test_color]
        return [color] * self.state.led_count

    def _tick_multi_zone(self) -> List[Tuple[int, int, int]]:
        """Compute per-zone colors for multi-zone devices.

        When carousel (LunBo) is enabled, only the currently active zone
        lights up and the device cycles through selected zones on a timer.
        """
        total = self.state.segment_count
        zone_count = len(self.state.zones)
        colors: List[Tuple[int, int, int]] = []

        # Advance carousel timer
        if self.state.zone_carousel:
            self.state.zone_carousel_ticks += 1
            if self.state.zone_carousel_ticks >= self.state.zone_carousel_interval:
                self.state.zone_carousel_ticks = 0
                self.state.zone_carousel_current = self._next_carousel_zone(
                    self.state.zone_carousel_current)

        active_zone = self.state.zone_carousel_current if self.state.zone_carousel else None

        for zi, zone in enumerate(self.state.zones):
            base = total // zone_count
            n_segs = base + (1 if zi < total % zone_count else 0)

            # Zone off, or carousel active and not this zone's turn
            if not zone.on or (active_zone is not None and zi != active_zone):
                colors.extend([(0, 0, 0)] * n_segs)
            else:
                zone_colors = self._tick_single_mode(zone.mode, zone.color, n_segs)
                if zone.brightness < 100:
                    scale = zone.brightness / 100.0
                    zone_colors = [
                        (int(r * scale), int(g * scale), int(b * scale))
                        for r, g, b in zone_colors
                    ]
                colors.extend(zone_colors)

        return colors

    # ── Effect algorithms (ported from FormLED.cs) ──────────────────

    def _tick_breathing_for(self, color: Tuple[int, int, int],
                            seg_count: int) -> List[Tuple[int, int, int]]:
        """DSHX_Timer: pulse brightness, period=66 ticks."""
        timer = self.state.rgb_timer
        period = 66
        half = period // 2

        if timer < half:
            factor = timer / half
        else:
            factor = (period - 1 - timer) / half

        r, g, b = color
        anim_r = int(r * factor * 0.8 + r * 0.2)
        anim_g = int(g * factor * 0.8 + g * 0.2)
        anim_b = int(b * factor * 0.8 + b * 0.2)

        self.state.rgb_timer = (timer + 1) % period

        return [(anim_r, anim_g, anim_b)] * seg_count

    def _tick_colorful_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """QCJB_Timer: 6-phase color gradient cycle, period=168 ticks."""
        timer = self.state.rgb_timer
        period = 168
        phase_len = 28

        phase = timer // phase_len
        offset = timer % phase_len
        t = int(255 * offset / (phase_len - 1)) if phase_len > 1 else 0

        if phase == 0:
            r, g, b = 255, t, 0
        elif phase == 1:
            r, g, b = 255 - t, 255, 0
        elif phase == 2:
            r, g, b = 0, 255, t
        elif phase == 3:
            r, g, b = 0, 255 - t, 255
        elif phase == 4:
            r, g, b = t, 0, 255
        else:
            r, g, b = 255, 0, 255 - t

        self.state.rgb_timer = (timer + 1) % period

        return [(r, g, b)] * seg_count

    def _tick_rainbow_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """CHMS_Timer: 768-entry RGB table with per-segment offset."""
        from ..adapters.device.led import ColorEngine
        table = ColorEngine.get_table()
        timer = self.state.rgb_timer
        table_len = len(table)

        colors = []
        for i in range(seg_count):
            idx = (timer + i * table_len // max(seg_count, 1)) % table_len
            colors.append(table[idx])

        self.state.rgb_timer = (timer + 4) % table_len

        return colors

    def _tick_temp_linked_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """WDLD_Timer: color from temperature thresholds."""
        from ..adapters.device.led import ColorEngine

        source = self.state.temp_source
        temp = getattr(self._metrics, f"{source}_temp", 0)
        color = ColorEngine.color_for_value(temp, ColorEngine.TEMP_GRADIENT)
        return [color] * seg_count

    def _tick_load_linked_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """FZLD_Timer: color from CPU/GPU load thresholds."""
        from ..adapters.device.led import ColorEngine

        source = self.state.load_source
        load = self._metrics.cpu_percent if source == "cpu" else self._metrics.gpu_usage
        color = ColorEngine.color_for_value(load, ColorEngine.LOAD_GRADIENT)
        return [color] * seg_count

    # ── HR10 7-segment ──────────────────────────────────────────────

    def set_display_value(self, text: str, indicators: Optional[set] = None) -> None:
        """Set HR10 display text for 7-segment rendering."""
        self._hr10_display_text = text
        self._hr10_indicators = indicators or set()
        self._update_hr10_mask()

    def _update_hr10_mask(self) -> None:
        if not self._hr10_mode:
            return
        from ..adapters.device.led_hr10 import Hr10Display
        self._hr10_mask = Hr10Display.get_digit_mask(
            self._hr10_display_text, self._hr10_indicators
        )

    # ── Segment display (all styles 1-11) ────────────────────────

    def _next_phase(self) -> int:
        """Advance to the next segment display phase (round-robin)."""
        total = self._seg_display.phase_count
        return (self._seg_phase + 1) % total

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

        if self._segment_mode and self._segment_mask:
            base_color = colors[0] if colors else (0, 0, 0)
            send_colors: list[Any] = [
                base_color if self._segment_mask[i] else (0, 0, 0)
                for i in range(len(self._segment_mask))
            ]
            is_on = None
        elif self._hr10_mode and self._hr10_mask:
            from ..adapters.device.led_hr10 import LED_COUNT
            base_color = colors[0] if colors else (0, 0, 0)
            send_colors = [
                base_color if self._hr10_mask[i] else (0, 0, 0)
                for i in range(LED_COUNT)
            ]
            is_on = None
        else:
            send_colors = colors
            is_on = self.state.segment_on

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

    def save_config(self) -> None:
        """Serialize LEDState to config file."""
        if not self._device_key:
            return
        try:
            from ..conf import Settings

            config: Dict[str, Any] = {
                'mode': self.state.mode.value,
                'color': list(self.state.color),
                'brightness': self.state.brightness,
                'global_on': self.state.global_on,
                'segments_on': self.state.segment_on,
                'temp_source': self.state.temp_source,
                'load_source': self.state.load_source,
                'is_timer_24h': self.state.is_timer_24h,
                'is_week_sunday': self.state.is_week_sunday,
                'disk_index': self.state.disk_index,
                'memory_ratio': self.state.memory_ratio,
            }
            if self.state.zones:
                config['zones'] = [
                    {
                        'mode': z.mode.value,
                        'color': list(z.color),
                        'brightness': z.brightness,
                        'on': z.on,
                    }
                    for z in self.state.zones
                ]
            if self.state.zone_carousel_zones:
                config['zone_carousel'] = self.state.zone_carousel
                config['zone_carousel_zones'] = self.state.zone_carousel_zones
                config['zone_carousel_interval'] = self.state.zone_carousel_interval
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

            if 'mode' in led_config:
                self.state.mode = LEDMode(led_config['mode'])
            if 'color' in led_config:
                self.state.color = tuple(led_config['color'])
            if 'brightness' in led_config:
                self.state.brightness = led_config['brightness']
            if 'global_on' in led_config:
                self.state.global_on = led_config['global_on']
            if 'segments_on' in led_config:
                self.state.segment_on = led_config['segments_on']
            if 'temp_source' in led_config:
                self.state.temp_source = led_config['temp_source']
            if 'load_source' in led_config:
                self.state.load_source = led_config['load_source']
            if 'zones' in led_config and self.state.zones:
                for i, z_config in enumerate(led_config['zones']):
                    if i < len(self.state.zones):
                        self.state.zones[i].mode = LEDMode(z_config.get('mode', 0))
                        self.state.zones[i].color = tuple(z_config.get('color', (255, 0, 0)))
                        self.state.zones[i].brightness = z_config.get('brightness', 100)
                        self.state.zones[i].on = z_config.get('on', True)
            if 'zone_carousel' in led_config:
                self.state.zone_carousel = led_config['zone_carousel']
            if 'zone_carousel_zones' in led_config:
                saved = led_config['zone_carousel_zones']
                for i in range(min(len(saved), len(self.state.zone_carousel_zones))):
                    self.state.zone_carousel_zones[i] = saved[i]
            if 'zone_carousel_interval' in led_config:
                self.state.zone_carousel_interval = led_config['zone_carousel_interval']
            if 'is_timer_24h' in led_config:
                self.state.is_timer_24h = led_config['is_timer_24h']
            if 'is_week_sunday' in led_config:
                self.state.is_week_sunday = led_config['is_week_sunday']
            if 'disk_index' in led_config:
                self.state.disk_index = led_config['disk_index']
            if 'memory_ratio' in led_config:
                self.state.memory_ratio = led_config['memory_ratio']
        except Exception as e:
            log.error("Failed to load LED config: %s", e)

    def cleanup(self) -> None:
        """Save config and release protocol."""
        self.save_config()
        self.set_protocol(None)
