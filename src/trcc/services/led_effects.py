"""LED effect algorithms — RGB color computation per tick.

Pure computation: reads LEDState + HardwareMetrics, advances animation
timers, returns per-segment color lists. No I/O, no protocol, no config.
"""
from __future__ import annotations

from typing import List, Tuple

from ..core.models import HardwareMetrics, LEDMode, LEDState


class LEDEffectEngine:
    """Compute per-segment RGB colors for LED animation effects.

    Holds references to LEDState and HardwareMetrics. Mutates state timers
    (rgb_timer, test_timer, zone_sync_ticks) as side effects of computation.
    """

    _TEST_COLORS = [(1, 1, 1), (1, 0, 0), (0, 1, 0), (0, 0, 1)]

    def __init__(self, state: LEDState, metrics: HardwareMetrics) -> None:
        self._state = state
        self._metrics = metrics

    @property
    def metrics(self) -> HardwareMetrics:
        return self._metrics

    @metrics.setter
    def metrics(self, value: HardwareMetrics) -> None:
        self._metrics = value

    # ── Main dispatch ────────────────────────────────────────────────

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

    def _tick_test_mode(self) -> List[Tuple[int, int, int]]:
        """C# checkBox1 test mode: cycle 4 colors every 10 ticks at min brightness."""
        st = self._state
        st.test_timer += 1
        if st.test_timer >= 10:
            st.test_timer = 0
            st.test_color = (st.test_color + 1) % 4
        color = self._TEST_COLORS[st.test_color]
        return [color] * st.led_count

    def _tick_multi_zone(
        self, zone_map: tuple[tuple[int, ...], ...],
    ) -> List[Tuple[int, int, int]]:
        """Compute per-zone colors using physical LED index mapping.

        Each zone's LEDs are placed at their mapped indices.
        Zone map comes from SegmentDisplay.zone_led_map.
        """
        st = self._state
        zones = st.zones
        total = st.led_count
        colors: List[Tuple[int, int, int]] = [(0, 0, 0)] * total
        for zi, led_indices in enumerate(zone_map):
            if zi >= len(zones):
                break
            z = zones[zi]
            if not z.on:
                continue
            n = len(led_indices)
            zc = self._tick_single_mode(z.mode, z.color, n)
            if z.brightness < 100:
                scale = z.brightness / 100.0
                zc = [(int(r * scale), int(g * scale), int(b * scale))
                      for r, g, b in zc]
            for i, idx in enumerate(led_indices):
                if idx < total:
                    colors[idx] = zc[i]
        return colors

    def _next_sync_zone(self, current: int) -> int:
        """Find next enabled zone in sync rotation, wrapping around."""
        zones = self._state.zone_sync_zones
        n = len(zones)
        for offset in range(1, n + 1):
            candidate = (current + offset) % n
            if zones[candidate]:
                return candidate
        return 0

    # ── Effect algorithms (ported from FormLED.cs) ──────────────────

    def _tick_breathing_for(self, color: Tuple[int, int, int],
                            seg_count: int) -> List[Tuple[int, int, int]]:
        """DSHX_Timer: pulse brightness, period=66 ticks."""
        timer = self._state.rgb_timer
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

        self._state.rgb_timer = (timer + 1) % period

        return [(anim_r, anim_g, anim_b)] * seg_count

    def _tick_colorful_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """QCJB_Timer: 6-phase color gradient cycle, period=168 ticks."""
        timer = self._state.rgb_timer
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

        self._state.rgb_timer = (timer + 1) % period

        return [(r, g, b)] * seg_count

    def _tick_rainbow_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """CHMS_Timer: 768-entry RGB table with per-segment offset."""
        from ..core.color import ColorEngine
        table = ColorEngine.get_table()
        timer = self._state.rgb_timer
        table_len = len(table)

        colors = []
        for i in range(seg_count):
            idx = (timer + i * table_len // max(seg_count, 1)) % table_len
            colors.append(table[idx])

        self._state.rgb_timer = (timer + 4) % table_len

        return colors

    def _tick_temp_linked_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """WDLD_Timer: color from temperature thresholds."""
        from ..core.color import ColorEngine

        source = self._state.temp_source
        temp = getattr(self._metrics, f"{source}_temp", 0)
        color = ColorEngine.color_for_value(temp, ColorEngine.TEMP_GRADIENT)
        return [color] * seg_count

    def _tick_load_linked_for(self, seg_count: int) -> List[Tuple[int, int, int]]:
        """FZLD_Timer: color from CPU/GPU load thresholds."""
        from ..core.color import ColorEngine

        source = self._state.load_source
        load = self._metrics.cpu_percent if source == "cpu" else self._metrics.gpu_usage
        color = ColorEngine.color_for_value(load, ColorEngine.LOAD_GRADIENT)
        return [color] * seg_count
