"""Tests for core/led_device.py — LEDDevice application facade."""

import unittest
from unittest.mock import MagicMock

from trcc.core.led_device import LEDDevice
from trcc.core.models import LEDMode


def _make_led(**overrides) -> LEDDevice:
    """Create LEDDevice with mock service pre-wired."""
    svc = MagicMock()
    svc.state = MagicMock()
    svc.state.zones = [MagicMock(), MagicMock()]
    svc.state.segment_on = [True, False, True]
    svc.tick.return_value = [(255, 0, 0)]
    svc.apply_mask.return_value = [(255, 0, 0)]
    svc.has_protocol = True

    defaults = {'svc': svc, 'get_protocol': MagicMock()}
    defaults.update(overrides)
    led = LEDDevice(**defaults)
    return led


# =============================================================================
# Construction
# =============================================================================


class TestLEDDeviceConstruction(unittest.TestCase):
    """LEDDevice construction."""

    def test_default_no_service(self):
        led = LEDDevice()
        self.assertIsNone(led._svc)

    def test_with_service(self):
        svc = MagicMock()
        led = LEDDevice(svc=svc)
        self.assertIs(led._svc, svc)

    def test_with_get_protocol(self):
        gp = MagicMock()
        led = LEDDevice(get_protocol=gp)
        self.assertIs(led._get_protocol, gp)


# =============================================================================
# Device ABC
# =============================================================================


class TestLEDDeviceABC(unittest.TestCase):
    """Device ABC methods on LEDDevice."""

    def test_connected_true_with_service(self):
        led = _make_led()
        self.assertTrue(led.connected)

    def test_connected_false_without_service(self):
        led = LEDDevice()
        self.assertFalse(led.connected)

    def test_device_info_returns_device(self):
        led = _make_led()
        dev = MagicMock()
        led._device = dev
        self.assertIs(led.device_info, dev)

    def test_cleanup_calls_service(self):
        led = _make_led()
        led.cleanup()
        led._svc.cleanup.assert_called_once()

    def test_cleanup_safe_without_service(self):
        led = LEDDevice()
        led.cleanup()  # should not raise

    def test_connect_returns_success_when_already_initialized(self):
        """connect() with existing service returns success immediately."""
        led = _make_led()
        led._init_status = "Ready"
        result = led.connect()
        self.assertTrue(result['success'])
        self.assertEqual(result['status'], 'Ready')


# =============================================================================
# Properties
# =============================================================================


class TestLEDDeviceProperties(unittest.TestCase):
    """LED-specific properties."""

    def test_status(self):
        led = _make_led()
        led._init_status = 'AX120'
        self.assertEqual(led.status, 'AX120')

    def test_service_accessor(self):
        led = _make_led()
        self.assertIs(led.service, led._svc)

    def test_state_from_service(self):
        led = _make_led()
        self.assertIs(led.state, led._svc.state)

    def test_state_none_without_service(self):
        led = LEDDevice()
        self.assertIsNone(led.state)


# =============================================================================
# _resolve_mode
# =============================================================================


class TestResolveMode(unittest.TestCase):
    """LEDDevice._resolve_mode() — flexible mode resolution."""

    def setUp(self):
        self.led = _make_led()

    def test_resolve_from_enum(self):
        self.assertEqual(self.led._resolve_mode(LEDMode.STATIC), LEDMode.STATIC)

    def test_resolve_from_int(self):
        self.assertEqual(self.led._resolve_mode(LEDMode.STATIC.value), LEDMode.STATIC)

    def test_resolve_from_string(self):
        self.assertEqual(self.led._resolve_mode('static'), LEDMode.STATIC)

    def test_resolve_from_string_uppercase(self):
        self.assertEqual(self.led._resolve_mode('BREATHING'), LEDMode.BREATHING)

    def test_resolve_invalid_int_returns_none(self):
        self.assertIsNone(self.led._resolve_mode(9999))

    def test_resolve_invalid_string_returns_none(self):
        self.assertIsNone(self.led._resolve_mode('nonexistent'))

    def test_resolve_none_returns_none(self):
        self.assertIsNone(self.led._resolve_mode(None))


# =============================================================================
# Validation helpers
# =============================================================================


class TestValidation(unittest.TestCase):
    """Zone and segment validation."""

    def setUp(self):
        self.led = _make_led()

    def test_valid_zone(self):
        self.assertIsNone(self.led._validate_zone(0))
        self.assertIsNone(self.led._validate_zone(1))

    def test_zone_out_of_range(self):
        result = self.led._validate_zone(5)
        self.assertFalse(result['success'])
        self.assertIn('out of range', result['error'])

    def test_zone_negative(self):
        result = self.led._validate_zone(-1)
        self.assertFalse(result['success'])

    def test_zone_no_zones(self):
        self.led._svc.state.zones = []
        result = self.led._validate_zone(0)
        self.assertFalse(result['success'])
        self.assertIn('no zones', result['error'])

    def test_valid_segment(self):
        self.assertIsNone(self.led._validate_segment(0))
        self.assertIsNone(self.led._validate_segment(2))

    def test_segment_out_of_range(self):
        result = self.led._validate_segment(10)
        self.assertFalse(result['success'])

    def test_segment_no_segments(self):
        self.led._svc.state.segment_on = []
        result = self.led._validate_segment(0)
        self.assertFalse(result['success'])
        self.assertIn('no segments', result['error'])


# =============================================================================
# Global operations — CLI/API path (immediate tick/send/save)
# =============================================================================


class TestGlobalOperations(unittest.TestCase):
    """CLI/API operations that immediately tick, send, and save."""

    def setUp(self):
        self.led = _make_led()

    def test_set_color(self):
        result = self.led.set_color(255, 0, 0)
        self.assertTrue(result['success'])
        self.led._svc.set_mode.assert_called_with(LEDMode.STATIC)
        self.led._svc.set_color.assert_called_with(255, 0, 0)
        self.assertIn('#ff0000', result['message'])

    def test_set_mode_by_name(self):
        result = self.led.set_mode('static')
        self.assertTrue(result['success'])
        self.assertIn('static', result['message'])

    def test_set_mode_by_enum(self):
        result = self.led.set_mode(LEDMode.BREATHING)
        self.assertTrue(result['success'])
        self.assertTrue(result['animated'])

    def test_set_mode_invalid(self):
        result = self.led.set_mode('bogus')
        self.assertFalse(result['success'])
        self.assertIn('available', result)

    def test_set_brightness_valid(self):
        result = self.led.set_brightness(50)
        self.assertTrue(result['success'])
        self.led._svc.set_brightness.assert_called_with(50)

    def test_set_brightness_too_high(self):
        result = self.led.set_brightness(150)
        self.assertFalse(result['success'])

    def test_set_brightness_negative(self):
        result = self.led.set_brightness(-1)
        self.assertFalse(result['success'])

    def test_toggle_global_on(self):
        result = self.led.toggle_global(True)
        self.assertTrue(result['success'])
        self.assertIn('on', result['message'])

    def test_toggle_global_off(self):
        result = self.led.toggle_global(False)
        self.assertTrue(result['success'])
        self.assertIn('off', result['message'])

    def test_off(self):
        result = self.led.off()
        self.assertTrue(result['success'])
        self.led._svc.toggle_global.assert_called_with(False)

    def test_set_sensor_source_cpu(self):
        result = self.led.set_sensor_source('cpu')
        self.assertTrue(result['success'])
        self.led._svc.set_sensor_source.assert_called_with('cpu')

    def test_set_sensor_source_gpu(self):
        result = self.led.set_sensor_source('GPU')
        self.assertTrue(result['success'])
        self.led._svc.set_sensor_source.assert_called_with('gpu')

    def test_set_sensor_source_invalid(self):
        result = self.led.set_sensor_source('memory')
        self.assertFalse(result['success'])


# =============================================================================
# Zone operations
# =============================================================================


class TestZoneOperations(unittest.TestCase):
    """Zone-level operations with validation."""

    def setUp(self):
        self.led = _make_led()

    def test_set_zone_color(self):
        result = self.led.set_zone_color(0, 0, 255, 0)
        self.assertTrue(result['success'])
        self.led._svc.set_zone_color.assert_called_with(0, 0, 255, 0)

    def test_set_zone_color_invalid_zone(self):
        result = self.led.set_zone_color(99, 0, 0, 0)
        self.assertFalse(result['success'])

    def test_set_zone_mode(self):
        result = self.led.set_zone_mode(0, LEDMode.STATIC)
        self.assertTrue(result['success'])

    def test_set_zone_mode_invalid_mode(self):
        result = self.led.set_zone_mode(0, 'bogus')
        self.assertFalse(result['success'])

    def test_set_zone_brightness(self):
        result = self.led.set_zone_brightness(1, 80)
        self.assertTrue(result['success'])

    def test_set_zone_brightness_out_of_range(self):
        result = self.led.set_zone_brightness(0, 200)
        self.assertFalse(result['success'])

    def test_toggle_zone(self):
        result = self.led.toggle_zone(0, True)
        self.assertTrue(result['success'])
        self.led._svc.toggle_zone.assert_called_with(0, True)

    def test_set_zone_sync(self):
        result = self.led.set_zone_sync(True, interval=5)
        self.assertTrue(result['success'])
        self.led._svc.set_zone_sync_interval.assert_called_with(5)
        self.led._svc.set_zone_sync.assert_called_with(True)

    def test_set_zone_sync_no_interval(self):
        result = self.led.set_zone_sync(False)
        self.assertTrue(result['success'])
        self.led._svc.set_zone_sync_interval.assert_not_called()


# =============================================================================
# Segment operations
# =============================================================================


class TestSegmentOperations(unittest.TestCase):
    """Segment toggle and display operations."""

    def setUp(self):
        self.led = _make_led()

    def test_toggle_segment(self):
        result = self.led.toggle_segment(0, False)
        self.assertTrue(result['success'])
        self.led._svc.toggle_segment.assert_called_with(0, False)

    def test_toggle_segment_invalid(self):
        result = self.led.toggle_segment(100, True)
        self.assertFalse(result['success'])

    def test_set_clock_format_24h(self):
        result = self.led.set_clock_format(True)
        self.assertTrue(result['success'])
        self.assertIn('24h', result['message'])

    def test_set_clock_format_12h(self):
        result = self.led.set_clock_format(False)
        self.assertTrue(result['success'])
        self.assertIn('12h', result['message'])

    def test_set_temp_unit_celsius(self):
        result = self.led.set_temp_unit('C')
        self.assertTrue(result['success'])

    def test_set_temp_unit_fahrenheit(self):
        result = self.led.set_temp_unit('f')
        self.assertTrue(result['success'])
        self.led._svc.set_seg_temp_unit.assert_called_with('F')

    def test_set_temp_unit_invalid(self):
        result = self.led.set_temp_unit('K')
        self.assertFalse(result['success'])

    def test_set_seg_temp_unit_alias(self):
        """set_seg_temp_unit is an alias for set_temp_unit."""
        result = self.led.set_seg_temp_unit('C')
        self.assertTrue(result['success'])


# =============================================================================
# State-only mutators (GUI path — no tick/send)
# =============================================================================


class TestUpdateMutators(unittest.TestCase):
    """GUI-path state mutators that don't tick/send."""

    def setUp(self):
        self.led = _make_led()

    def test_update_color(self):
        self.led.update_color(100, 200, 50)
        self.led._svc.set_color.assert_called_with(100, 200, 50)

    def test_update_mode(self):
        self.led.update_mode(LEDMode.RAINBOW)
        self.led._svc.set_mode.assert_called_with(LEDMode.RAINBOW)

    def test_update_mode_from_int(self):
        self.led.update_mode(LEDMode.STATIC.value)
        self.led._svc.set_mode.assert_called_with(LEDMode.STATIC)

    def test_update_brightness_clamps_high(self):
        self.led.update_brightness(200)
        self.led._svc.set_brightness.assert_called_with(100)

    def test_update_brightness_clamps_low(self):
        self.led.update_brightness(-10)
        self.led._svc.set_brightness.assert_called_with(0)

    def test_update_global_on(self):
        self.led.update_global_on(True)
        self.led._svc.toggle_global.assert_called_with(True)

    def test_update_segment(self):
        self.led.update_segment(1, True)
        self.led._svc.toggle_segment.assert_called_with(1, True)

    def test_update_zone_color(self):
        self.led.update_zone_color(0, 10, 20, 30)
        self.led._svc.set_zone_color.assert_called_with(0, 10, 20, 30)

    def test_update_zone_brightness_clamps(self):
        self.led.update_zone_brightness(0, 150)
        self.led._svc.set_zone_brightness.assert_called_with(0, 100)

    def test_update_clock_format(self):
        self.led.update_clock_format(True)
        self.led._svc.set_clock_format.assert_called_with(True)

    def test_update_week_start(self):
        self.led.update_week_start(False)
        self.led._svc.set_week_start.assert_called_with(False)

    def test_update_disk_index(self):
        self.led.update_disk_index(2)
        self.led._svc.set_disk_index.assert_called_with(2)

    def test_update_memory_ratio(self):
        self.led.update_memory_ratio(75)
        self.led._svc.set_memory_ratio.assert_called_with(75)

    def test_update_test_mode(self):
        self.led.update_test_mode(True)
        self.led._svc.set_test_mode.assert_called_with(True)

    def test_update_selected_zone(self):
        self.led.update_selected_zone(1)
        self.led._svc.set_selected_zone.assert_called_with(1)


# =============================================================================
# Tick + config
# =============================================================================


class TestTickAndConfig(unittest.TestCase):
    """Animation tick and config persistence."""

    def setUp(self):
        self.led = _make_led()

    def test_tick_returns_colors(self):
        result = self.led.tick()
        self.assertIn('colors', result)
        self.assertIn('display_colors', result)

    def test_tick_sends_when_protocol_connected(self):
        self.led._svc.has_protocol = True
        self.led.tick()
        self.led._svc.send_colors.assert_called_once()

    def test_tick_skips_send_without_protocol(self):
        self.led._svc.has_protocol = False
        self.led.tick()
        self.led._svc.send_colors.assert_not_called()

    def test_save_config(self):
        self.led.save_config()
        self.led._svc.save_config.assert_called_once()

    def test_save_config_safe_without_service(self):
        led = LEDDevice()
        led.save_config()  # no crash

    def test_load_config(self):
        self.led.load_config()
        self.led._svc.load_config.assert_called_once()

    def test_load_config_safe_without_service(self):
        led = LEDDevice()
        led.load_config()  # no crash

    def test_update_metrics(self):
        metrics = MagicMock()
        result = self.led.update_metrics(metrics)
        self.assertTrue(result['success'])
        self.led._svc.update_metrics.assert_called_with(metrics)


# =============================================================================
# Initialize (GUI path)
# =============================================================================


class TestInitialize(unittest.TestCase):
    """LEDDevice.initialize() — GUI path with pre-detected device."""

    def test_initialize_creates_service_if_needed(self):
        led = LEDDevice(get_protocol=MagicMock())
        device = MagicMock()
        led._svc = None  # force creation
        with unittest.mock.patch('trcc.core.led_device.LEDDevice.initialize') as mock_init:
            mock_init.return_value = {"success": True, "status": "", "style": 2}
            result = led.initialize(device, 2)
        self.assertTrue(result['success'])

    def test_initialize_with_existing_service(self):
        led = _make_led()
        device = MagicMock()
        result = led.initialize(device, 3)
        self.assertTrue(result['success'])
        self.assertEqual(result['style'], 3)
        self.assertIs(led._device, device)


if __name__ == '__main__':
    unittest.main()
