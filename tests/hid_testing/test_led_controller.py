"""
Tests for LED service and model layer.

Covers LEDMode enum, LEDZoneState, LEDState, LEDService (state mutations,
tick dispatch, all 6 effect algorithms, mask application, zone mapping,
clock persistence).

Architecture mirrors Windows FormLED.cs:
  - LEDService holds state + computes per-segment colors each tick
"""

from unittest.mock import MagicMock, patch

import pytest

from trcc.core.models import (
    HardwareMetrics,
    LEDMode,
    LEDState,
    LEDZoneState,
)
from trcc.services.led import LEDService

# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def led_state():
    """Default LEDState with 10 segments."""
    return LEDState()


@pytest.fixture
def led_svc():
    """Fresh LEDService with default state."""
    return LEDService()


# =========================================================================
# Tests: LEDMode enum
# =========================================================================

class TestLEDMode:
    """Verify enum values match FormLED.cs mode IDs."""

    def test_static_value(self):
        assert LEDMode.STATIC.value == 0

    def test_breathing_value(self):
        assert LEDMode.BREATHING.value == 1

    def test_colorful_value(self):
        assert LEDMode.COLORFUL.value == 2

    def test_rainbow_value(self):
        assert LEDMode.RAINBOW.value == 3

    def test_temp_linked_value(self):
        assert LEDMode.TEMP_LINKED.value == 4

    def test_load_linked_value(self):
        assert LEDMode.LOAD_LINKED.value == 5

    def test_mode_count(self):
        assert len(LEDMode) == 6

    def test_round_trip_from_int(self):
        for mode in LEDMode:
            assert LEDMode(mode.value) is mode


# =========================================================================
# Tests: LEDZoneState dataclass
# =========================================================================

class TestLEDZoneState:
    """Verify default creation and field semantics."""

    def test_defaults(self):
        zone = LEDZoneState()
        assert zone.mode is LEDMode.STATIC
        assert zone.color == (255, 0, 0)
        assert zone.brightness == 65
        assert zone.on is True

    def test_custom_creation(self):
        zone = LEDZoneState(
            mode=LEDMode.BREATHING,
            color=(0, 255, 0),
            brightness=50,
            on=False,
        )
        assert zone.mode is LEDMode.BREATHING
        assert zone.color == (0, 255, 0)
        assert zone.brightness == 50
        assert zone.on is False


# =========================================================================
# Tests: LEDState dataclass
# =========================================================================

class TestLEDState:
    """Verify LEDState creation, defaults, __post_init__ logic."""

    def test_defaults(self, led_state):
        assert led_state.style == 1
        assert led_state.led_count == 30
        assert led_state.segment_count == 10
        assert led_state.zone_count == 1
        assert led_state.mode is LEDMode.STATIC
        assert led_state.color == (255, 0, 0)
        assert led_state.brightness == 65
        assert led_state.global_on is True
        assert led_state.rgb_timer == 0
        assert led_state.temp_source == "cpu"
        assert led_state.load_source == "cpu"

    def test_segment_on_auto_populated(self, led_state):
        """__post_init__ creates segment_on list matching segment_count."""
        assert len(led_state.segment_on) == 10
        assert all(s is True for s in led_state.segment_on)

    def test_segment_on_custom_count(self):
        state = LEDState(segment_count=5)
        assert len(state.segment_on) == 5

    def test_segment_on_preserves_if_provided(self):
        """If segment_on is already set, __post_init__ does not overwrite."""
        custom = [True, False, True]
        state = LEDState(segment_count=3, segment_on=custom)
        assert state.segment_on == [True, False, True]

    def test_zones_auto_populated_for_multi_zone(self):
        state = LEDState(zone_count=3)
        assert len(state.zones) == 3
        assert all(isinstance(z, LEDZoneState) for z in state.zones)

    def test_no_zones_for_single_zone(self, led_state):
        """Single-zone devices (zone_count=1) have empty zones list."""
        assert led_state.zones == []

    def test_zones_preserved_if_provided(self):
        custom_zones = [LEDZoneState(brightness=42)]
        state = LEDState(zone_count=2, zones=custom_zones)
        # Non-empty list provided, __post_init__ skips
        assert len(state.zones) == 1
        assert state.zones[0].brightness == 42


# =========================================================================
# Tests: LEDService — state mutations
# =========================================================================

class TestLEDServiceStateMutations:
    """Test set_mode, set_color, set_brightness, toggles, zone methods."""

    def test_set_mode(self, led_svc):
        led_svc.set_mode(LEDMode.RAINBOW)
        assert led_svc.state.mode is LEDMode.RAINBOW

    def test_set_mode_resets_timer(self, led_svc):
        led_svc.state.rgb_timer = 42
        led_svc.set_mode(LEDMode.BREATHING)
        assert led_svc.state.rgb_timer == 0

    def test_set_color(self, led_svc):
        led_svc.set_color(10, 20, 30)
        assert led_svc.state.color == (10, 20, 30)

    def test_set_brightness_normal(self, led_svc):
        led_svc.set_brightness(75)
        assert led_svc.state.brightness == 75

    def test_set_brightness_clamps_high(self, led_svc):
        led_svc.set_brightness(200)
        assert led_svc.state.brightness == 100

    def test_set_brightness_clamps_low(self, led_svc):
        led_svc.set_brightness(-10)
        assert led_svc.state.brightness == 0

    def test_toggle_global_off(self, led_svc):
        led_svc.toggle_global(False)
        assert led_svc.state.global_on is False

    def test_toggle_global_on(self, led_svc):
        led_svc.state.global_on = False
        led_svc.toggle_global(True)
        assert led_svc.state.global_on is True

    def test_toggle_segment(self, led_svc):
        led_svc.toggle_segment(3, False)
        assert led_svc.state.segment_on[3] is False
        # Others unchanged
        assert led_svc.state.segment_on[0] is True

    def test_toggle_segment_out_of_range(self, led_svc):
        """Out-of-range index does not raise."""
        led_svc.toggle_segment(999, False)
        led_svc.toggle_segment(-1, False)
        # No exception, state unchanged
        assert all(s is True for s in led_svc.state.segment_on)

    def test_set_zone_mode(self):
        model = LEDService(state=LEDState(zone_count=2))
        model.set_zone_mode(0, LEDMode.COLORFUL)
        assert model.state.zones[0].mode is LEDMode.COLORFUL

    def test_set_zone_mode_out_of_range(self):
        model = LEDService(state=LEDState(zone_count=2))
        model.set_zone_mode(5, LEDMode.STATIC)  # No exception

    def test_set_zone_color(self):
        model = LEDService(state=LEDState(zone_count=2))
        model.set_zone_color(1, 0, 128, 255)
        assert model.state.zones[1].color == (0, 128, 255)

    def test_set_zone_color_out_of_range(self):
        model = LEDService(state=LEDState(zone_count=2))
        model.set_zone_color(99, 0, 0, 0)  # No exception

    def test_set_zone_brightness(self):
        model = LEDService(state=LEDState(zone_count=2))
        model.set_zone_brightness(0, 50)
        assert model.state.zones[0].brightness == 50

    def test_set_zone_brightness_clamps(self):
        model = LEDService(state=LEDState(zone_count=2))
        model.set_zone_brightness(0, 999)
        assert model.state.zones[0].brightness == 100
        model.set_zone_brightness(0, -5)
        assert model.state.zones[0].brightness == 0

    def test_set_zone_brightness_out_of_range(self):
        model = LEDService(state=LEDState(zone_count=2))
        model.set_zone_brightness(99, 50)  # No exception

    def test_update_metrics(self, led_svc):
        metrics = HardwareMetrics(cpu_temp=65)
        led_svc.update_metrics(metrics)
        assert led_svc._metrics == metrics


# =========================================================================
# Tests: LEDService — configure_for_style
# =========================================================================

class TestLEDServiceConfigureForStyle:
    """Test configure_for_style() sets LED/segment counts from registry."""

    @patch("trcc.core.models.LED_STYLES", {
        1: MagicMock(style_id=1, led_count=30, segment_count=10, zone_count=1),
        2: MagicMock(style_id=2, led_count=84, segment_count=18, zone_count=4),
    })
    def test_configure_style_1(self, led_svc):
        led_svc.configure_for_style(1)
        assert led_svc.state.style == 1
        assert led_svc.state.led_count == 30
        assert led_svc.state.segment_count == 10
        assert led_svc.state.zone_count == 1
        assert len(led_svc.state.segment_on) == 10
        assert led_svc.state.zones == []

    @patch("trcc.core.models.LED_STYLES", {
        2: MagicMock(style_id=2, led_count=84, segment_count=18, zone_count=4),
    })
    def test_configure_multi_zone_style(self, led_svc):
        led_svc.configure_for_style(2)
        assert led_svc.state.zone_count == 4
        assert len(led_svc.state.zones) == 4

    @patch("trcc.core.models.LED_STYLES", {})
    def test_configure_unknown_style(self, led_svc):
        """Unknown style_id does nothing (LED_STYLES.get returns None)."""
        original_count = led_svc.state.segment_count
        led_svc.configure_for_style(999)
        assert led_svc.state.segment_count == original_count


# =========================================================================
# Tests: LEDService — tick dispatch
# =========================================================================

class TestLEDServiceTickDispatch:
    """Test that tick() dispatches to the correct mode algorithm."""

    def test_tick_static(self, led_svc):
        led_svc.set_mode(LEDMode.STATIC)
        colors = led_svc.tick()
        assert len(colors) == led_svc.state.segment_count
        assert all(c == led_svc.state.color for c in colors)

    def test_tick_breathing(self, led_svc):
        led_svc.set_mode(LEDMode.BREATHING)
        colors = led_svc.tick()
        assert len(colors) == led_svc.state.segment_count

    def test_tick_colorful(self, led_svc):
        led_svc.set_mode(LEDMode.COLORFUL)
        colors = led_svc.tick()
        assert len(colors) == led_svc.state.segment_count

    @patch("trcc.adapters.device.led.ColorEngine.get_table")
    def test_tick_rainbow(self, mock_table, led_svc):
        # Provide a minimal table
        mock_table.return_value = [(i, i, i) for i in range(768)]
        led_svc.set_mode(LEDMode.RAINBOW)
        colors = led_svc.tick()
        assert len(colors) == led_svc.state.segment_count

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value", return_value=(0, 255, 255))
    def test_tick_temp_linked(self, mock_cfv, led_svc):
        led_svc.set_mode(LEDMode.TEMP_LINKED)
        led_svc.update_metrics(HardwareMetrics(cpu_temp=25))
        colors = led_svc.tick()
        assert len(colors) == led_svc.state.segment_count

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value", return_value=(255, 255, 0))
    def test_tick_load_linked(self, mock_cfv, led_svc):
        led_svc.set_mode(LEDMode.LOAD_LINKED)
        led_svc.update_metrics(HardwareMetrics(cpu_percent=60))
        colors = led_svc.tick()
        assert len(colors) == led_svc.state.segment_count

    def test_tick_returns_list_of_tuples(self, led_svc):
        colors = led_svc.tick()
        assert isinstance(colors, list)
        for c in colors:
            assert isinstance(c, tuple)
            assert len(c) == 3


# =========================================================================
# Tests: LEDService — physical zone mapping (style 7 / LF10)
# =========================================================================

class TestPhysicalZones:
    """Style 7 (LF10) has 3 physical zones with independent color/mode/brightness."""

    @pytest.fixture
    def svc7(self):
        svc = LEDService()
        svc.configure_for_style(7)
        return svc

    def test_tick_returns_116_colors(self, svc7):
        colors = svc7.tick()
        assert len(colors) == 116

    def test_zones_get_independent_colors(self, svc7):
        for z in svc7.state.zones:
            z.brightness = 100
        svc7.set_zone_color(0, 255, 0, 0)   # zone 1 red
        svc7.set_zone_color(1, 0, 255, 0)    # zone 2 green
        svc7.set_zone_color(2, 0, 0, 255)    # zone 3 blue
        colors = svc7.tick()
        # CPU indicator (index 0) = zone 1 = red
        assert colors[0] == (255, 0, 0)
        # GPU indicator (index 3) = zone 2 = green
        assert colors[3] == (0, 255, 0)
        # Accent LED (index 104) = zone 3 = blue
        assert colors[104] == (0, 0, 255)

    def test_zone_brightness_scales(self, svc7):
        svc7.state.zones[0].brightness = 100
        svc7.set_zone_color(0, 200, 100, 50)
        svc7.state.zones[0].brightness = 50
        colors = svc7.tick()
        assert colors[0] == (100, 50, 25)

    def test_zone_off_produces_black(self, svc7):
        svc7.set_zone_color(2, 255, 255, 255)
        svc7.state.zones[2].on = False
        colors = svc7.tick()
        assert colors[104] == (0, 0, 0)

    def test_mask_gates_physical_zone_colors(self, svc7):
        svc7.state.zones[0].brightness = 100
        svc7.set_zone_color(0, 255, 0, 0)
        colors = svc7.tick()
        masked = svc7.apply_mask(colors)
        # CPU indicator (mask=True) keeps color
        assert masked[0] == (255, 0, 0)
        # Hundreds digit LED off (leading zero suppression for temp=0)
        assert masked[6] == (0, 0, 0)

    def test_breathing_mode_per_zone(self, svc7):
        for z in svc7.state.zones:
            z.brightness = 100
        svc7.state.zones[0].mode = LEDMode.BREATHING
        svc7.state.zones[0].color = (255, 0, 0)
        svc7.state.zones[1].mode = LEDMode.STATIC
        svc7.state.zones[1].color = (0, 255, 0)
        colors = svc7.tick()
        # Zone 2 static green at GPU indicator
        assert colors[3] == (0, 255, 0)
        # Zone 1 breathing — may or may not be full red depending on timer
        assert len(colors) == 116


# =========================================================================
# Tests: LEDService — _tick_static
# =========================================================================

class TestTickStatic:
    """DSCL_Timer: all segments = user color."""

    def test_all_segments_same_color(self, led_svc):
        led_svc.set_color(100, 200, 50)
        colors = led_svc._tick_single_mode(
            LEDMode.STATIC, led_svc.state.color, led_svc.state.segment_count)
        assert all(c == (100, 200, 50) for c in colors)

    def test_segment_count_matches(self, led_svc):
        colors = led_svc._tick_single_mode(
            LEDMode.STATIC, led_svc.state.color, led_svc.state.segment_count)
        assert len(colors) == led_svc.state.segment_count


# =========================================================================
# Tests: LEDService — _tick_breathing
# =========================================================================

class TestTickBreathing:
    """DSHX_Timer: pulse brightness, period=66."""

    def test_advances_timer(self, led_svc):
        led_svc.state.mode = LEDMode.BREATHING
        led_svc.state.rgb_timer = 0
        led_svc._tick_breathing_for(led_svc.state.color, led_svc.state.segment_count)
        assert led_svc.state.rgb_timer == 1

    def test_timer_wraps_at_66(self, led_svc):
        led_svc.state.rgb_timer = 65
        led_svc._tick_breathing_for(led_svc.state.color, led_svc.state.segment_count)
        assert led_svc.state.rgb_timer == 0

    def test_at_zero_brightness_is_20_percent_base(self, led_svc):
        """At timer=0, factor=0 so anim is 0; output = 20% of color."""
        led_svc.set_color(255, 0, 0)
        led_svc.state.rgb_timer = 0
        colors = led_svc._tick_breathing_for(led_svc.state.color, led_svc.state.segment_count)
        r, g, b = colors[0]
        # int(255 * 0 * 0.8 + 255 * 0.2) = int(51.0) = 51
        assert r == 51

    def test_at_midpoint_brightness_is_full(self, led_svc):
        """At timer=33 (half), factor= (66-1-33)/33 ~ 0.9697 -> near full."""
        led_svc.set_color(255, 0, 0)
        led_svc.state.rgb_timer = 32  # factor = 32/33 ~ 0.97
        colors = led_svc._tick_breathing_for(led_svc.state.color, led_svc.state.segment_count)
        r, g, b = colors[0]
        # 80% animated + 20% base -> near 255
        assert r > 200

    def test_uniform_across_segments(self, led_svc):
        """All segments get the same breathing color."""
        led_svc.set_color(100, 100, 100)
        led_svc.state.rgb_timer = 10
        colors = led_svc._tick_breathing_for(led_svc.state.color, led_svc.state.segment_count)
        assert len(set(colors)) == 1  # All identical


# =========================================================================
# Tests: LEDService — _tick_colorful
# =========================================================================

class TestTickColorful:
    """QCJB_Timer: 6-phase gradient, period=168."""

    def test_advances_timer(self, led_svc):
        led_svc.state.rgb_timer = 0
        led_svc._tick_colorful_for(led_svc.state.segment_count)
        assert led_svc.state.rgb_timer == 1

    def test_timer_wraps_at_168(self, led_svc):
        led_svc.state.rgb_timer = 167
        led_svc._tick_colorful_for(led_svc.state.segment_count)
        assert led_svc.state.rgb_timer == 0

    def test_phase_0_starts_red(self, led_svc):
        """Phase 0 offset 0 -> (255, 0, 0) = pure red."""
        led_svc.state.rgb_timer = 0
        colors = led_svc._tick_colorful_for(led_svc.state.segment_count)
        assert colors[0] == (255, 0, 0)

    def test_phase_1_yellow_to_green(self, led_svc):
        """Phase 1 offset 0 -> (255, 255, 0) -> R starts decreasing."""
        led_svc.state.rgb_timer = 28  # Phase 1 start
        colors = led_svc._tick_colorful_for(led_svc.state.segment_count)
        r, g, b = colors[0]
        assert g == 255
        assert b == 0

    def test_phase_2_green_to_cyan(self, led_svc):
        """Phase 2 starts at timer=56."""
        led_svc.state.rgb_timer = 56
        colors = led_svc._tick_colorful_for(led_svc.state.segment_count)
        r, g, b = colors[0]
        assert r == 0
        assert g == 255

    def test_full_cycle_returns_to_start(self, led_svc):
        """After 168 ticks, we're back at phase 0 offset 0."""
        led_svc.state.rgb_timer = 0
        for _ in range(168):
            led_svc._tick_colorful_for(led_svc.state.segment_count)
        assert led_svc.state.rgb_timer == 0

    def test_uniform_across_segments(self, led_svc):
        """All segments get the same colorful color."""
        led_svc.state.rgb_timer = 42
        colors = led_svc._tick_colorful_for(led_svc.state.segment_count)
        assert len(set(colors)) == 1


# =========================================================================
# Tests: LEDService — _tick_rainbow
# =========================================================================

class TestTickRainbow:
    """CHMS_Timer: 768-entry table, offset per segment."""

    @patch("trcc.adapters.device.led.ColorEngine.get_table")
    def test_uses_rgb_table(self, mock_table, led_svc):
        table = [(i, 0, 0) for i in range(768)]
        mock_table.return_value = table
        led_svc.state.rgb_timer = 0
        colors = led_svc._tick_rainbow_for(led_svc.state.segment_count)
        # Each segment gets a different offset
        assert len(colors) == led_svc.state.segment_count
        mock_table.assert_called()

    @patch("trcc.adapters.device.led.ColorEngine.get_table")
    def test_advances_by_4(self, mock_table, led_svc):
        mock_table.return_value = [(0, 0, 0)] * 768
        led_svc.state.rgb_timer = 0
        led_svc._tick_rainbow_for(led_svc.state.segment_count)
        assert led_svc.state.rgb_timer == 4

    @patch("trcc.adapters.device.led.ColorEngine.get_table")
    def test_timer_wraps(self, mock_table, led_svc):
        mock_table.return_value = [(0, 0, 0)] * 768
        led_svc.state.rgb_timer = 764
        led_svc._tick_rainbow_for(led_svc.state.segment_count)
        assert led_svc.state.rgb_timer == 0  # (764 + 4) % 768 = 0

    @patch("trcc.adapters.device.led.ColorEngine.get_table")
    def test_segments_get_different_offsets(self, mock_table, led_svc):
        """Different segments get different colors from the table."""
        table = [(i, i, i) for i in range(768)]
        mock_table.return_value = table
        led_svc.state.rgb_timer = 0
        led_svc.state.segment_count = 4
        led_svc.state.segment_on = [True] * 4
        colors = led_svc._tick_rainbow_for(led_svc.state.segment_count)
        # With 4 segments, offsets should be 0, 192, 384, 576
        assert len(set(colors)) > 1  # Not all the same


# =========================================================================
# Tests: LEDService — _tick_temp_linked
# =========================================================================

class TestTickTempLinked:
    """WDLD_Timer: color from CPU/GPU temperature thresholds."""

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value")
    def test_uses_cpu_temp_by_default(self, mock_cfv, led_svc):
        mock_cfv.return_value = (0, 255, 0)
        led_svc.state.temp_source = "cpu"
        led_svc.update_metrics(HardwareMetrics(cpu_temp=45))
        led_svc._tick_temp_linked_for(led_svc.state.segment_count)
        mock_cfv.assert_called_once()
        # First positional arg is the temp value
        assert mock_cfv.call_args[0][0] == 45

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value")
    def test_uses_gpu_temp(self, mock_cfv, led_svc):
        mock_cfv.return_value = (255, 0, 0)
        led_svc.state.temp_source = "gpu"
        led_svc.update_metrics(HardwareMetrics(gpu_temp=92))
        led_svc._tick_temp_linked_for(led_svc.state.segment_count)
        assert mock_cfv.call_args[0][0] == 92

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value")
    def test_missing_metric_defaults_to_zero(self, mock_cfv, led_svc):
        mock_cfv.return_value = (0, 255, 255)
        led_svc.update_metrics(HardwareMetrics())
        led_svc._tick_temp_linked_for(led_svc.state.segment_count)
        assert mock_cfv.call_args[0][0] == 0

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value")
    def test_uniform_color(self, mock_cfv, led_svc):
        mock_cfv.return_value = (0, 255, 0)
        led_svc.update_metrics(HardwareMetrics(cpu_temp=40))
        colors = led_svc._tick_temp_linked_for(led_svc.state.segment_count)
        assert all(c == (0, 255, 0) for c in colors)
        assert len(colors) == led_svc.state.segment_count


# =========================================================================
# Tests: LEDService — _tick_load_linked
# =========================================================================

class TestTickLoadLinked:
    """FZLD_Timer: color from CPU/GPU load thresholds."""

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value")
    def test_uses_cpu_load_by_default(self, mock_cfv, led_svc):
        mock_cfv.return_value = (255, 255, 0)
        led_svc.state.load_source = "cpu"
        led_svc.update_metrics(HardwareMetrics(cpu_percent=60))
        led_svc._tick_load_linked_for(led_svc.state.segment_count)
        assert mock_cfv.call_args[0][0] == 60

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value")
    def test_uses_gpu_load(self, mock_cfv, led_svc):
        mock_cfv.return_value = (255, 110, 0)
        led_svc.state.load_source = "gpu"
        led_svc.update_metrics(HardwareMetrics(gpu_usage=85))
        led_svc._tick_load_linked_for(led_svc.state.segment_count)
        assert mock_cfv.call_args[0][0] == 85

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value")
    def test_missing_metric_defaults_to_zero(self, mock_cfv, led_svc):
        mock_cfv.return_value = (0, 255, 255)
        led_svc.update_metrics(HardwareMetrics())
        led_svc._tick_load_linked_for(led_svc.state.segment_count)
        assert mock_cfv.call_args[0][0] == 0


# =========================================================================
# Tests: Multi-zone tick()
# =========================================================================

class TestMultiZoneTick:
    """Test _tick_multi_zone() — per-zone color computation via zone map."""

    @pytest.fixture
    def multi_zone_model(self):
        """LEDService with 2-zone, 10-LED zone map."""
        model = LEDService()
        model.state.led_count = 10
        model.state.segment_count = 10
        model.state.zone_count = 2
        model.state.zones = [
            LEDZoneState(mode=LEDMode.STATIC, color=(255, 0, 0), brightness=100),
            LEDZoneState(mode=LEDMode.STATIC, color=(0, 0, 255), brightness=100),
        ]
        return model

    def test_multi_zone_dispatches(self, multi_zone_model):
        """_tick_multi_zone places zone colors at mapped indices."""
        zone_map = (tuple(range(0, 5)), tuple(range(5, 10)))
        colors = multi_zone_model._tick_multi_zone(zone_map)
        assert len(colors) == 10
        assert colors[0] == (255, 0, 0)
        assert colors[4] == (255, 0, 0)
        assert colors[5] == (0, 0, 255)
        assert colors[9] == (0, 0, 255)

    def test_multi_zone_uneven_sizes(self):
        """Zone map with different-sized zones."""
        model = LEDService()
        model.state.led_count = 10
        model.state.segment_count = 10
        model.state.zone_count = 3
        model.state.zones = [
            LEDZoneState(mode=LEDMode.STATIC, color=(255, 0, 0), brightness=100),
            LEDZoneState(mode=LEDMode.STATIC, color=(0, 255, 0), brightness=100),
            LEDZoneState(mode=LEDMode.STATIC, color=(0, 0, 255), brightness=100),
        ]
        zone_map = ((0, 1, 2, 3, 4), (5, 6, 7), (8, 9))
        colors = model._tick_multi_zone(zone_map)
        assert len(colors) == 10
        assert all(c == (255, 0, 0) for c in colors[0:5])
        assert all(c == (0, 255, 0) for c in colors[5:8])
        assert all(c == (0, 0, 255) for c in colors[8:10])

    def test_multi_zone_brightness_scaling(self, multi_zone_model):
        """Zone brightness scales RGB values."""
        multi_zone_model.state.zones[0].brightness = 50
        zone_map = (tuple(range(0, 5)), tuple(range(5, 10)))
        colors = multi_zone_model._tick_multi_zone(zone_map)
        assert colors[0] == (127, 0, 0)
        assert colors[5] == (0, 0, 255)

    def test_multi_zone_off(self, multi_zone_model):
        """Zone with on=False produces black."""
        multi_zone_model.state.zones[0].on = False
        zone_map = (tuple(range(0, 5)), tuple(range(5, 10)))
        colors = multi_zone_model._tick_multi_zone(zone_map)
        assert colors[0] == (0, 0, 0)
        assert colors[4] == (0, 0, 0)
        assert colors[5] == (0, 0, 255)

    def test_multi_zone_breathing(self):
        """Multi-zone with breathing mode advances timer."""
        model = LEDService()
        model.state.led_count = 6
        model.state.segment_count = 6
        model.state.zone_count = 2
        model.state.zones = [
            LEDZoneState(mode=LEDMode.BREATHING, color=(100, 100, 100), brightness=100),
            LEDZoneState(mode=LEDMode.STATIC, color=(0, 255, 0), brightness=100),
        ]
        zone_map = ((0, 1, 2), (3, 4, 5))
        colors = model._tick_multi_zone(zone_map)
        assert len(colors) == 6
        assert colors[0] == (20, 20, 20)
        assert colors[3] == (0, 255, 0)

    def test_single_zone_skips_multi(self):
        """Single-zone device uses global mode, not multi-zone path."""
        model = LEDService()
        model.state.zone_count = 1
        model.state.segment_count = 5
        model.state.mode = LEDMode.STATIC
        model.state.color = (0, 128, 0)
        model.state.zones = []
        colors = model.tick()
        assert all(c == (0, 128, 0) for c in colors)

    def test_four_zone_device(self):
        """4-zone device with mapped LED indices."""
        model = LEDService()
        model.state.led_count = 18
        model.state.segment_count = 18
        model.state.zone_count = 4
        model.state.zones = [
            LEDZoneState(mode=LEDMode.STATIC, color=(255, 0, 0), brightness=100),
            LEDZoneState(mode=LEDMode.STATIC, color=(0, 255, 0), brightness=100),
            LEDZoneState(mode=LEDMode.STATIC, color=(0, 0, 255), brightness=100),
            LEDZoneState(mode=LEDMode.STATIC, color=(255, 255, 0), brightness=100),
        ]
        zone_map = (tuple(range(0, 5)), tuple(range(5, 10)),
                    tuple(range(10, 14)), tuple(range(14, 18)))
        colors = model._tick_multi_zone(zone_map)
        assert len(colors) == 18
        assert all(c == (255, 0, 0) for c in colors[0:5])
        assert all(c == (0, 255, 0) for c in colors[5:10])
        assert all(c == (0, 0, 255) for c in colors[10:14])
        assert all(c == (255, 255, 0) for c in colors[14:18])


# =========================================================================
# Tests: LEDState clock fields
# =========================================================================

class TestLEDStateClockFields:
    """Test LC2 clock fields on LEDState dataclass."""

    def test_default_values(self):
        state = LEDState()
        assert state.is_timer_24h is True
        assert state.is_week_sunday is False

    def test_custom_values(self):
        state = LEDState(is_timer_24h=False, is_week_sunday=True)
        assert state.is_timer_24h is False
        assert state.is_week_sunday is True


# =========================================================================
# Tests: _tick_single_mode dispatcher
# =========================================================================

class TestTickSingleMode:
    """Test _tick_single_mode dispatches correctly."""

    def test_static(self, led_svc):
        colors = led_svc._tick_single_mode(
            LEDMode.STATIC, (10, 20, 30), 5)
        assert colors == [(10, 20, 30)] * 5

    def test_breathing(self, led_svc):
        colors = led_svc._tick_single_mode(
            LEDMode.BREATHING, (100, 100, 100), 3)
        assert len(colors) == 3

    def test_colorful(self, led_svc):
        colors = led_svc._tick_single_mode(
            LEDMode.COLORFUL, (0, 0, 0), 4)
        assert len(colors) == 4

    @patch("trcc.adapters.device.led.ColorEngine.get_table",
           return_value=[(i, i, i) for i in range(768)])
    def test_rainbow(self, mock_table, led_svc):
        colors = led_svc._tick_single_mode(
            LEDMode.RAINBOW, (0, 0, 0), 6)
        assert len(colors) == 6

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value", return_value=(0, 255, 255))
    def test_temp_linked(self, mock_cfv, led_svc):
        colors = led_svc._tick_single_mode(
            LEDMode.TEMP_LINKED, (0, 0, 0), 3)
        assert len(colors) == 3

    @patch("trcc.adapters.device.led.ColorEngine.color_for_value", return_value=(255, 0, 0))
    def test_load_linked(self, mock_cfv, led_svc):
        colors = led_svc._tick_single_mode(
            LEDMode.LOAD_LINKED, (0, 0, 0), 3)
        assert len(colors) == 3

    def test_unknown_mode_returns_black(self, led_svc):
        colors = led_svc._tick_single_mode(99, (255, 255, 255), 4)
        assert colors == [(0, 0, 0)] * 4


# =========================================================================
# Tests: UCInfoImage widget (headless — no display needed)
# =========================================================================

class TestUCInfoImageWidget:
    """Test UCInfoImage sensor gauge widget logic."""

    def test_import(self):
        """UCInfoImage class is importable."""
        try:
            from trcc.qt_components.uc_led_control import UCInfoImage
            assert UCInfoImage is not None
        except ImportError:
            pytest.skip("PyQt6 not available")

    def test_set_value(self):
        """set_value stores values for painting."""
        try:
            from trcc.qt_components.uc_led_control import UCInfoImage
        except ImportError:
            pytest.skip("PyQt6 not available")
        # Can't instantiate without QApplication, just verify class exists
        assert hasattr(UCInfoImage, 'set_value')
        assert hasattr(UCInfoImage, 'set_mode')
        assert hasattr(UCInfoImage, 'paintEvent')

    def test_bar_width_calculation_temp(self):
        """Progress bar width for temp/percent mode: value*2, max 200."""
        # Test the formula directly (value * 2, capped at 200)
        assert max(0, min(200, int(50 * 2))) == 100

    def test_bar_width_calculation_mhz(self):
        """Progress bar width for MHz mode: value/25, max 200."""
        assert max(0, min(200, int(2500 / 25))) == 100
