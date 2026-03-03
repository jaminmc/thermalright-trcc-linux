"""Tests for trcc.cli._led — LEDDispatcher and CLI wrappers."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trcc.cli._led import (
    LEDDispatcher,
    _connect_or_fail,
    _get_led_service,
    _led_command,
    _print_result,
    led_off,
    set_clock_format,
    set_color,
    set_led_brightness,
    set_mode,
    set_sensor_source,
    set_temp_unit,
    set_zone_brightness,
    set_zone_color,
    set_zone_mode,
    set_zone_sync,
    toggle_segment,
    toggle_zone,
)

# ===========================================================================
# Shared fixtures
# ===========================================================================

@pytest.fixture()
def mock_svc():
    """Fully mocked LEDService — no hardware required."""
    svc = MagicMock()
    svc.state = MagicMock()
    svc.state.zones = [MagicMock(), MagicMock(), MagicMock()]
    svc.state.segment_on = [True, False, True, False]
    svc.tick.return_value = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    return svc


@pytest.fixture()
def disp(mock_svc):
    """LEDDispatcher wired to mock service."""
    return LEDDispatcher(svc=mock_svc)


@pytest.fixture()
def disp_no_zones(mock_svc):
    """LEDDispatcher with no zones (empty list)."""
    mock_svc.state.zones = []
    return LEDDispatcher(svc=mock_svc)


@pytest.fixture()
def disp_no_segments(mock_svc):
    """LEDDispatcher with no segments (empty list)."""
    mock_svc.state.segment_on = []
    return LEDDispatcher(svc=mock_svc)


# ===========================================================================
# TestLEDDispatcherInit
# ===========================================================================

class TestLEDDispatcherInit:
    """__init__, connected, status, service properties."""

    def test_default_init_no_svc(self):
        d = LEDDispatcher()
        assert d._svc is None

    def test_init_with_svc(self, mock_svc):
        d = LEDDispatcher(svc=mock_svc)
        assert d._svc is mock_svc

    def test_connected_false_when_no_svc(self):
        d = LEDDispatcher()
        assert d.connected is False

    def test_connected_true_when_svc_set(self, disp):
        assert disp.connected is True

    def test_status_initially_none(self, disp):
        assert disp.status is None

    def test_status_reflects_init_status(self, disp):
        disp._init_status = "AX120 (style 1)"
        assert disp.status == "AX120 (style 1)"

    def test_service_property_returns_svc(self, mock_svc, disp):
        assert disp.service is mock_svc

    def test_service_property_none_when_disconnected(self):
        d = LEDDispatcher()
        assert d.service is None


# ===========================================================================
# TestLEDDispatcherModes
# ===========================================================================

class TestLEDDispatcherModes:
    """_modes() lazy classvar initialisation."""

    def test_modes_returns_dict(self):
        # Reset class-level cache so the lazy init runs fresh
        LEDDispatcher._MODE_MAP = None
        modes = LEDDispatcher._modes()
        assert isinstance(modes, dict)

    def test_modes_contains_static(self):
        modes = LEDDispatcher._modes()
        assert 'static' in modes

    def test_modes_contains_breathing(self):
        modes = LEDDispatcher._modes()
        assert 'breathing' in modes

    def test_modes_contains_colorful(self):
        modes = LEDDispatcher._modes()
        assert 'colorful' in modes

    def test_modes_contains_rainbow(self):
        modes = LEDDispatcher._modes()
        assert 'rainbow' in modes

    def test_modes_cached_after_first_call(self):
        LEDDispatcher._MODE_MAP = None
        first = LEDDispatcher._modes()
        second = LEDDispatcher._modes()
        assert first is second

    def test_modes_values_are_led_mode_enums(self):
        from trcc.core.models import LEDMode
        modes = LEDDispatcher._modes()
        for v in modes.values():
            assert isinstance(v, LEDMode)


# ===========================================================================
# TestLEDDispatcherConnect
# ===========================================================================

class TestLEDDispatcherConnect:
    """connect() with mocked detect_devices + LEDService."""

    def test_connect_returns_success_when_already_connected(self, mock_svc):
        d = LEDDispatcher(svc=mock_svc)
        d._init_status = "connected"
        result = d.connect()
        assert result["success"] is True
        assert result["status"] == "connected"

    def test_connect_no_led_device_returns_error(self):
        d = LEDDispatcher()
        fake_dev = MagicMock()
        fake_dev.implementation = 'hid_lcd'  # not hid_led
        with patch('trcc.cli._led.detect_devices', return_value=[fake_dev],
                   create=True), \
             patch('trcc.adapters.device.detector.detect_devices',
                   return_value=[fake_dev]):
            with patch('trcc.cli._led.LEDDispatcher.connect',
                       wraps=d.connect):
                # Patch at the import location inside connect()
                with patch('trcc.adapters.device.detector.detect_devices',
                           return_value=[fake_dev]):
                    pass  # covered by next test

    def test_connect_no_led_device_directly(self):
        """connect() returns failure when no hid_led device found."""
        d = LEDDispatcher()
        fake_dev = MagicMock()
        fake_dev.implementation = 'hid_lcd'

        with patch('trcc.adapters.device.detector.detect_devices',
                   return_value=[fake_dev]), \
             patch('trcc.services.LEDService'):
            result = d.connect()
        assert result["success"] is False
        assert "No LED device" in result["error"]

    def test_connect_empty_device_list(self):
        """connect() returns failure when device list is empty."""
        d = LEDDispatcher()
        with patch('trcc.adapters.device.detector.detect_devices',
                   return_value=[]):
            result = d.connect()
        assert result["success"] is False
        assert "No LED device" in result["error"]

    def test_connect_success_sets_svc(self):
        """connect() sets _svc and _init_status on success."""
        d = LEDDispatcher()
        led_dev = MagicMock()
        led_dev.implementation = 'hid_led'
        led_dev.vid = 0x0416
        led_dev.pid = 0x8001
        led_dev.usb_path = "1-2"

        fake_svc = MagicMock()
        fake_svc.initialize.return_value = "AX120"
        fake_info = MagicMock()
        fake_info.style.style_id = 1

        with patch('trcc.adapters.device.detector.detect_devices',
                   return_value=[led_dev]), \
             patch('trcc.services.LEDService', return_value=fake_svc), \
             patch('trcc.adapters.device.led.probe_led_model',
                   return_value=fake_info):
            result = d.connect()

        assert result["success"] is True
        assert d._svc is fake_svc
        assert d._init_status == "AX120"


# ===========================================================================
# TestLEDDispatcherValidation
# ===========================================================================

class TestLEDDispatcherValidation:
    """_validate_zone and _validate_segment bounds checking."""

    def test_validate_zone_valid(self, disp):
        assert disp._validate_zone(0) is None
        assert disp._validate_zone(1) is None
        assert disp._validate_zone(2) is None

    def test_validate_zone_negative(self, disp):
        err = disp._validate_zone(-1)
        assert err is not None
        assert err["success"] is False
        assert "out of range" in err["error"]

    def test_validate_zone_too_high(self, disp):
        err = disp._validate_zone(3)  # only 0-2 valid (3 zones)
        assert err is not None
        assert err["success"] is False

    def test_validate_zone_empty_list(self, disp_no_zones):
        err = disp_no_zones._validate_zone(0)
        assert err is not None
        assert "no zones" in err["error"]

    def test_validate_segment_valid(self, disp):
        assert disp._validate_segment(0) is None
        assert disp._validate_segment(3) is None

    def test_validate_segment_negative(self, disp):
        err = disp._validate_segment(-1)
        assert err is not None
        assert err["success"] is False
        assert "out of range" in err["error"]

    def test_validate_segment_too_high(self, disp):
        err = disp._validate_segment(4)  # only 0-3 valid (4 segments)
        assert err is not None
        assert err["success"] is False

    def test_validate_segment_empty_list(self, disp_no_segments):
        err = disp_no_segments._validate_segment(0)
        assert err is not None
        assert "no segments" in err["error"]

    def test_validate_zone_range_message_includes_max(self, disp):
        err = disp._validate_zone(99)
        assert "2" in err["error"]  # max index is 2 (3 zones)


# ===========================================================================
# TestLEDDispatcherInternalHelpers
# ===========================================================================

class TestLEDDispatcherInternalHelpers:
    """_apply_and_send and _send_and_save."""

    def test_apply_and_send_calls_toggle_global_true(self, disp, mock_svc):
        disp._apply_and_send()
        mock_svc.toggle_global.assert_called_with(True)

    def test_apply_and_send_calls_tick(self, disp, mock_svc):
        disp._apply_and_send()
        mock_svc.tick.assert_called_once()

    def test_apply_and_send_calls_send_colors(self, disp, mock_svc):
        colors = mock_svc.tick.return_value
        disp._apply_and_send()
        mock_svc.send_colors.assert_called_once_with(colors)

    def test_apply_and_send_calls_save_config(self, disp, mock_svc):
        disp._apply_and_send()
        mock_svc.save_config.assert_called_once()

    def test_apply_and_send_returns_colors(self, disp, mock_svc):
        result = disp._apply_and_send()
        assert result == mock_svc.tick.return_value

    def test_send_and_save_calls_send_tick(self, disp, mock_svc):
        disp._send_and_save()
        mock_svc.send_tick.assert_called_once()

    def test_send_and_save_calls_save_config(self, disp, mock_svc):
        disp._send_and_save()
        mock_svc.save_config.assert_called_once()


# ===========================================================================
# TestLEDDispatcherGlobalOps
# ===========================================================================

class TestLEDDispatcherGlobalOps:
    """set_color, set_mode, set_brightness, off, set_sensor_source."""

    def test_set_color_success(self, disp, mock_svc):
        result = disp.set_color(255, 0, 0)
        assert result["success"] is True
        assert "ff0000" in result["message"]

    def test_set_color_calls_set_mode_static(self, disp, mock_svc):
        from trcc.core.models import LEDMode
        disp.set_color(0, 255, 0)
        mock_svc.set_mode.assert_called_once_with(LEDMode.STATIC)

    def test_set_color_calls_set_color_on_svc(self, disp, mock_svc):
        disp.set_color(10, 20, 30)
        mock_svc.set_color.assert_called_once_with(10, 20, 30)

    def test_set_color_returns_colors(self, disp, mock_svc):
        result = disp.set_color(255, 0, 0)
        assert result["colors"] == mock_svc.tick.return_value

    def test_set_mode_static_not_animated(self, disp):
        result = disp.set_mode('static')
        assert result["success"] is True
        assert result["animated"] is False

    def test_set_mode_breathing_is_animated(self, disp):
        result = disp.set_mode('breathing')
        assert result["success"] is True
        assert result["animated"] is True

    def test_set_mode_colorful_is_animated(self, disp):
        result = disp.set_mode('colorful')
        assert result["success"] is True
        assert result["animated"] is True

    def test_set_mode_rainbow_is_animated(self, disp):
        result = disp.set_mode('rainbow')
        assert result["success"] is True
        assert result["animated"] is True

    def test_set_mode_unknown_fails(self, disp):
        result = disp.set_mode('fireworks')
        assert result["success"] is False
        assert "fireworks" in result["error"]
        assert "available" in result

    def test_set_mode_unknown_lists_available(self, disp):
        result = disp.set_mode('bad_mode')
        assert set(result["available"]) >= {'static', 'breathing', 'colorful', 'rainbow'}

    def test_set_mode_case_insensitive(self, disp):
        result = disp.set_mode('STATIC')
        assert result["success"] is True

    def test_set_mode_calls_svc_set_mode(self, disp, mock_svc):
        from trcc.core.models import LEDMode
        disp.set_mode('static')
        mock_svc.set_mode.assert_called_once_with(LEDMode.STATIC)

    def test_set_brightness_success(self, disp):
        result = disp.set_brightness(75)
        assert result["success"] is True
        assert "75%" in result["message"]

    def test_set_brightness_zero(self, disp):
        result = disp.set_brightness(0)
        assert result["success"] is True

    def test_set_brightness_hundred(self, disp):
        result = disp.set_brightness(100)
        assert result["success"] is True

    def test_set_brightness_negative_fails(self, disp):
        result = disp.set_brightness(-1)
        assert result["success"] is False
        assert "0-100" in result["error"]

    def test_set_brightness_over_100_fails(self, disp):
        result = disp.set_brightness(101)
        assert result["success"] is False

    def test_set_brightness_calls_svc(self, disp, mock_svc):
        disp.set_brightness(50)
        mock_svc.set_brightness.assert_called_once_with(50)

    def test_off_success(self, disp, mock_svc):
        result = disp.off()
        assert result["success"] is True
        assert "off" in result["message"].lower()

    def test_off_calls_toggle_global_false(self, disp, mock_svc):
        disp.off()
        mock_svc.toggle_global.assert_called_with(False)

    def test_off_calls_send_tick(self, disp, mock_svc):
        disp.off()
        mock_svc.send_tick.assert_called_once()

    def test_set_sensor_source_cpu(self, disp, mock_svc):
        result = disp.set_sensor_source('cpu')
        assert result["success"] is True
        assert "CPU" in result["message"]

    def test_set_sensor_source_gpu(self, disp, mock_svc):
        result = disp.set_sensor_source('gpu')
        assert result["success"] is True
        assert "GPU" in result["message"]

    def test_set_sensor_source_case_insensitive(self, disp, mock_svc):
        result = disp.set_sensor_source('CPU')
        assert result["success"] is True

    def test_set_sensor_source_invalid(self, disp):
        result = disp.set_sensor_source('tpu')
        assert result["success"] is False
        assert "cpu" in result["error"].lower() or "gpu" in result["error"].lower()

    def test_set_sensor_source_calls_svc(self, disp, mock_svc):
        disp.set_sensor_source('gpu')
        mock_svc.set_sensor_source.assert_called_once_with('gpu')

    def test_set_sensor_source_saves_config(self, disp, mock_svc):
        disp.set_sensor_source('cpu')
        mock_svc.save_config.assert_called_once()


# ===========================================================================
# TestLEDDispatcherZoneOps
# ===========================================================================

class TestLEDDispatcherZoneOps:
    """set_zone_color, set_zone_mode, set_zone_brightness, toggle_zone, set_zone_sync."""

    def test_set_zone_color_valid(self, disp, mock_svc):
        result = disp.set_zone_color(0, 255, 128, 0)
        assert result["success"] is True
        assert "Zone 0" in result["message"]
        assert "ff8000" in result["message"]

    def test_set_zone_color_invalid_zone(self, disp):
        result = disp.set_zone_color(99, 255, 0, 0)
        assert result["success"] is False

    def test_set_zone_color_negative_zone(self, disp):
        result = disp.set_zone_color(-1, 255, 0, 0)
        assert result["success"] is False

    def test_set_zone_color_calls_svc(self, disp, mock_svc):
        disp.set_zone_color(1, 10, 20, 30)
        mock_svc.set_zone_color.assert_called_once_with(1, 10, 20, 30)

    def test_set_zone_mode_valid(self, disp, mock_svc):
        result = disp.set_zone_mode(0, 'static')
        assert result["success"] is True
        assert "Zone 0" in result["message"]

    def test_set_zone_mode_invalid_zone(self, disp):
        result = disp.set_zone_mode(10, 'static')
        assert result["success"] is False

    def test_set_zone_mode_unknown_mode(self, disp):
        result = disp.set_zone_mode(0, 'laser')
        assert result["success"] is False
        assert "laser" in result["error"]

    def test_set_zone_mode_calls_svc(self, disp, mock_svc):
        from trcc.core.models import LEDMode
        disp.set_zone_mode(2, 'breathing')
        mock_svc.set_zone_mode.assert_called_once_with(2, LEDMode.BREATHING)

    def test_set_zone_brightness_valid(self, disp, mock_svc):
        result = disp.set_zone_brightness(0, 80)
        assert result["success"] is True
        assert "Zone 0" in result["message"]
        assert "80%" in result["message"]

    def test_set_zone_brightness_invalid_zone(self, disp):
        result = disp.set_zone_brightness(99, 50)
        assert result["success"] is False

    def test_set_zone_brightness_too_high(self, disp):
        result = disp.set_zone_brightness(0, 101)
        assert result["success"] is False
        assert "0-100" in result["error"]

    def test_set_zone_brightness_negative(self, disp):
        result = disp.set_zone_brightness(0, -5)
        assert result["success"] is False

    def test_set_zone_brightness_calls_svc(self, disp, mock_svc):
        disp.set_zone_brightness(1, 50)
        mock_svc.set_zone_brightness.assert_called_once_with(1, 50)

    def test_toggle_zone_on(self, disp, mock_svc):
        result = disp.toggle_zone(0, True)
        assert result["success"] is True
        assert "ON" in result["message"]

    def test_toggle_zone_off(self, disp, mock_svc):
        result = disp.toggle_zone(1, False)
        assert result["success"] is True
        assert "OFF" in result["message"]

    def test_toggle_zone_invalid_zone(self, disp):
        result = disp.toggle_zone(99, True)
        assert result["success"] is False

    def test_toggle_zone_calls_svc(self, disp, mock_svc):
        disp.toggle_zone(2, True)
        mock_svc.toggle_zone.assert_called_once_with(2, True)

    def test_set_zone_sync_enabled(self, disp, mock_svc):
        result = disp.set_zone_sync(True)
        assert result["success"] is True
        assert "enabled" in result["message"]

    def test_set_zone_sync_disabled(self, disp, mock_svc):
        result = disp.set_zone_sync(False)
        assert result["success"] is True
        assert "disabled" in result["message"]

    def test_set_zone_sync_with_interval(self, disp, mock_svc):
        result = disp.set_zone_sync(True, interval=5)
        assert result["success"] is True
        mock_svc.set_zone_sync_interval.assert_called_once_with(5)

    def test_set_zone_sync_no_interval_skips_set_interval(self, disp, mock_svc):
        disp.set_zone_sync(True, interval=None)
        mock_svc.set_zone_sync_interval.assert_not_called()

    def test_set_zone_sync_calls_svc(self, disp, mock_svc):
        disp.set_zone_sync(True)
        mock_svc.set_zone_sync.assert_called_once_with(True)


# ===========================================================================
# TestLEDDispatcherSegmentOps
# ===========================================================================

class TestLEDDispatcherSegmentOps:
    """toggle_segment, set_clock_format, set_temp_unit."""

    def test_toggle_segment_on(self, disp, mock_svc):
        result = disp.toggle_segment(0, True)
        assert result["success"] is True
        assert "ON" in result["message"]

    def test_toggle_segment_off(self, disp, mock_svc):
        result = disp.toggle_segment(1, False)
        assert result["success"] is True
        assert "OFF" in result["message"]

    def test_toggle_segment_invalid_index(self, disp):
        result = disp.toggle_segment(99, True)
        assert result["success"] is False

    def test_toggle_segment_negative_index(self, disp):
        result = disp.toggle_segment(-1, True)
        assert result["success"] is False

    def test_toggle_segment_calls_svc(self, disp, mock_svc):
        disp.toggle_segment(2, False)
        mock_svc.toggle_segment.assert_called_once_with(2, False)

    def test_toggle_segment_empty_list(self, disp_no_segments):
        result = disp_no_segments.toggle_segment(0, True)
        assert result["success"] is False
        assert "no segments" in result["error"]

    def test_set_clock_format_24h(self, disp, mock_svc):
        result = disp.set_clock_format(True)
        assert result["success"] is True
        assert "24h" in result["message"]

    def test_set_clock_format_12h(self, disp, mock_svc):
        result = disp.set_clock_format(False)
        assert result["success"] is True
        assert "12h" in result["message"]

    def test_set_clock_format_calls_svc(self, disp, mock_svc):
        disp.set_clock_format(True)
        mock_svc.set_clock_format.assert_called_once_with(True)

    def test_set_temp_unit_celsius(self, disp, mock_svc):
        result = disp.set_temp_unit('C')
        assert result["success"] is True
        assert "Celsius" in result["message"]

    def test_set_temp_unit_fahrenheit(self, disp, mock_svc):
        result = disp.set_temp_unit('F')
        assert result["success"] is True
        assert "Fahrenheit" in result["message"]

    def test_set_temp_unit_lowercase(self, disp, mock_svc):
        result = disp.set_temp_unit('f')
        assert result["success"] is True

    def test_set_temp_unit_invalid(self, disp):
        result = disp.set_temp_unit('K')
        assert result["success"] is False
        assert "C" in result["error"] and "F" in result["error"]

    def test_set_temp_unit_calls_svc(self, disp, mock_svc):
        disp.set_temp_unit('C')
        mock_svc.set_seg_temp_unit.assert_called_once_with('C')


# ===========================================================================
# TestLEDDispatcherTick
# ===========================================================================

class TestLEDDispatcherTick:
    """tick() — advance one animation frame."""

    def test_tick_returns_colors(self, disp, mock_svc):
        result = disp.tick()
        assert "colors" in result
        assert result["colors"] == mock_svc.tick.return_value

    def test_tick_calls_svc_tick(self, disp, mock_svc):
        disp.tick()
        mock_svc.tick.assert_called_once()

    def test_tick_calls_send_colors(self, disp, mock_svc):
        colors = mock_svc.tick.return_value
        disp.tick()
        mock_svc.send_colors.assert_called_once_with(colors)

    def test_tick_no_success_key(self, disp):
        # tick() returns {colors: ...}, not a success/error dict
        result = disp.tick()
        assert "success" not in result


# ===========================================================================
# TestCLIHelpers
# ===========================================================================

class TestCLIHelpers:
    """_connect_or_fail, _print_result, _led_command, _get_led_service."""

    def test_connect_or_fail_success(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(mock_svc, "AX120")):
            led, rc = _connect_or_fail()
        assert rc == 0
        assert led.connected is True
        captured = capsys.readouterr()
        assert "AX120" in captured.out

    def test_connect_or_fail_no_device(self, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(None, None)):
            led, rc = _connect_or_fail()
        assert rc == 1
        assert led.connected is False
        captured = capsys.readouterr()
        assert "No LED device" in captured.out

    def test_connect_or_fail_no_status_printed(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(mock_svc, None)):
            _, rc = _connect_or_fail()
        assert rc == 0
        captured = capsys.readouterr()
        # None status should not be printed
        assert captured.out.strip() == ""

    def test_print_result_success(self, capsys):
        result = {"success": True, "message": "Done!"}
        rc = _print_result(result)
        assert rc == 0
        assert "Done!" in capsys.readouterr().out

    def test_print_result_failure(self, capsys):
        result = {"success": False, "error": "Something failed"}
        rc = _print_result(result)
        assert rc == 1
        assert "Something failed" in capsys.readouterr().out

    def test_print_result_failure_no_error_key(self, capsys):
        result = {"success": False}
        rc = _print_result(result)
        assert rc == 1
        assert "Unknown error" in capsys.readouterr().out

    def test_print_result_preview_calls_zones_to_ansi(self, mock_svc, capsys):
        colors = [(255, 0, 0)]
        result = {"success": True, "message": "ok", "colors": colors}
        with patch('trcc.services.LEDService.zones_to_ansi',
                   return_value="[ANSI]") as mock_ansi:
            rc = _print_result(result, preview=True)
        assert rc == 0
        mock_ansi.assert_called_once_with(colors)

    def test_print_result_no_preview_no_ansi(self, capsys):
        result = {"success": True, "message": "ok", "colors": [(255, 0, 0)]}
        with patch('trcc.services.LEDService.zones_to_ansi') as mock_ansi:
            _print_result(result, preview=False)
        mock_ansi.assert_not_called()

    def test_print_result_preview_skipped_when_no_colors(self, capsys):
        result = {"success": True, "message": "ok"}
        with patch('trcc.services.LEDService.zones_to_ansi') as mock_ansi:
            _print_result(result, preview=True)
        mock_ansi.assert_not_called()

    def test_led_command_no_device(self, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(None, None)):
            rc = _led_command("off")
        assert rc == 1

    def test_led_command_success(self, mock_svc, capsys):
        mock_svc.send_tick = MagicMock()
        mock_svc.save_config = MagicMock()
        mock_svc.toggle_global = MagicMock()
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = _led_command("off")
        assert rc == 0

    def test_get_led_service_no_device(self):
        d = LEDDispatcher()
        with patch.object(LEDDispatcher, 'connect',
                          return_value={"success": False, "error": "no device"}):
            with patch('trcc.cli._led.LEDDispatcher', return_value=d):
                svc, status = _get_led_service()
        assert svc is None
        assert status is None

    def test_get_led_service_success(self, mock_svc):
        d = LEDDispatcher(svc=mock_svc)
        d._init_status = "PA120"
        connect_result = {"success": True, "status": "PA120"}
        with patch('trcc.cli._led.LEDDispatcher', return_value=d), \
             patch.object(d, 'connect', return_value=connect_result):
            svc, status = _get_led_service()
        assert svc is mock_svc
        assert status == "PA120"


# ===========================================================================
# TestCLISetColor
# ===========================================================================

class TestCLISetColor:
    """set_color CLI command — valid/invalid hex, preview."""

    def test_set_color_valid_hex(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_color("ff0000")
        assert rc == 0
        assert "ff0000" in capsys.readouterr().out

    def test_set_color_with_hash_prefix(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_color("#00ff00")
        assert rc == 0

    def test_set_color_invalid_hex(self, capsys):
        rc = set_color("zzzzzz")
        assert rc == 1
        assert "Invalid hex" in capsys.readouterr().out

    def test_set_color_too_short_hex(self, capsys):
        rc = set_color("ff00")
        assert rc == 1

    def test_set_color_no_device(self, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(None, None)):
            rc = set_color("ff0000")
        assert rc == 1

    def test_set_color_with_preview(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)), \
             patch('trcc.services.LEDService.zones_to_ansi',
                   return_value="[ANSI]"):
            rc = set_color("0000ff", preview=True)
        assert rc == 0
        assert "[ANSI]" in capsys.readouterr().out


# ===========================================================================
# TestCLISetMode
# ===========================================================================

class TestCLISetMode:
    """set_mode CLI — static/animated/unknown, preview, KeyboardInterrupt."""

    def test_set_mode_static(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_mode("static")
        assert rc == 0
        assert "static" in capsys.readouterr().out.lower()

    def test_set_mode_unknown(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_mode("fireworks")
        assert rc == 1
        captured = capsys.readouterr()
        assert "fireworks" in captured.out

    def test_set_mode_unknown_prints_available(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_mode("bad")
        assert rc == 1
        assert "Available" in capsys.readouterr().out

    def test_set_mode_no_device(self, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(None, None)):
            rc = set_mode("static")
        assert rc == 1

    def test_set_mode_animated_runs_loop(self, mock_svc, capsys):
        """Animated mode enters loop; KeyboardInterrupt exits cleanly."""
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)), \
             patch('time.sleep', side_effect=KeyboardInterrupt), \
             patch('trcc.services.LEDService.zones_to_ansi', return_value=""):
            rc = set_mode("breathing", preview=False)
        assert rc == 0
        captured = capsys.readouterr()
        assert "Stopped" in captured.out

    def test_set_mode_animated_with_preview(self, mock_svc, capsys):
        """Animated preview calls zones_to_ansi on each tick."""
        mock_svc.tick.return_value = [(255, 0, 0)]
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)), \
             patch('time.sleep', side_effect=KeyboardInterrupt), \
             patch('trcc.services.LEDService.zones_to_ansi',
                   return_value="[ANSI]") as mock_ansi:
            rc = set_mode("rainbow", preview=True)
        assert rc == 0
        mock_ansi.assert_called()

    def test_set_mode_static_with_preview(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)), \
             patch('trcc.services.LEDService.zones_to_ansi',
                   return_value="[ANSI]"):
            rc = set_mode("static", preview=True)
        assert rc == 0
        assert "[ANSI]" in capsys.readouterr().out


# ===========================================================================
# TestCLICommands
# ===========================================================================

class TestCLICommands:
    """set_led_brightness, led_off, set_sensor_source, zone/segment commands."""

    def test_set_led_brightness_success(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_led_brightness(60)
        assert rc == 0

    def test_set_led_brightness_invalid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_led_brightness(200)
        assert rc == 1
        assert "0-100" in capsys.readouterr().out

    def test_led_off_success(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = led_off()
        assert rc == 0

    def test_led_off_no_device(self, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(None, None)):
            rc = led_off()
        assert rc == 1

    def test_set_sensor_source_cpu(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_sensor_source("cpu")
        assert rc == 0

    def test_set_sensor_source_invalid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_sensor_source("fan")
        assert rc == 1

    def test_set_zone_color_valid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_color(0, "ff0000")
        assert rc == 0

    def test_set_zone_color_invalid_hex(self, capsys):
        rc = set_zone_color(0, "xyz")
        assert rc == 1
        assert "Invalid hex" in capsys.readouterr().out

    def test_set_zone_color_no_device(self, capsys):
        with patch('trcc.cli._led._get_led_service', return_value=(None, None)):
            rc = set_zone_color(0, "ff0000")
        assert rc == 1

    def test_set_zone_mode_valid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_mode(0, "static")
        assert rc == 0

    def test_set_zone_mode_invalid_zone(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_mode(99, "static")
        assert rc == 1

    def test_set_zone_brightness_valid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_brightness(0, 75)
        assert rc == 0

    def test_set_zone_brightness_invalid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_brightness(0, 999)
        assert rc == 1

    def test_toggle_zone_on(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = toggle_zone(1, True)
        assert rc == 0

    def test_toggle_zone_off(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = toggle_zone(2, False)
        assert rc == 0

    def test_toggle_zone_invalid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = toggle_zone(99, True)
        assert rc == 1

    def test_set_zone_sync_enabled(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_sync(True)
        assert rc == 0

    def test_set_zone_sync_disabled(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_sync(False)
        assert rc == 0

    def test_set_zone_sync_with_interval(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_zone_sync(True, interval=3)
        assert rc == 0
        mock_svc.set_zone_sync_interval.assert_called_once_with(3)

    def test_toggle_segment_on(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = toggle_segment(0, True)
        assert rc == 0

    def test_toggle_segment_invalid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = toggle_segment(99, True)
        assert rc == 1

    def test_set_clock_format_24h(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_clock_format(True)
        assert rc == 0

    def test_set_clock_format_12h(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_clock_format(False)
        assert rc == 0

    def test_set_temp_unit_celsius(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_temp_unit("C")
        assert rc == 0

    def test_set_temp_unit_fahrenheit(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_temp_unit("F")
        assert rc == 0

    def test_set_temp_unit_invalid(self, mock_svc, capsys):
        with patch('trcc.cli._led._get_led_service',
                   return_value=(mock_svc, None)):
            rc = set_temp_unit("X")
        assert rc == 1


# =========================================================================
# TestCLILedStatus
# =========================================================================

class TestCLILedStatus:
    """Tests for the led-status CLI command."""

    def test_led_status_connected(self, capsys):
        from trcc.cli._led import led_status
        mock_led = MagicMock()
        mock_led.get_state.return_value = {
            "success": True,
            "mode": "STATIC",
            "color": [255, 0, 0],
            "brightness": 80,
            "global_on": True,
            "zones": [
                {"color": [255, 0, 0], "mode": "STATIC", "brightness": 100, "on": True},
            ],
            "segment_on": [True, True, False],
        }
        with patch("trcc.cli._led._connect_or_fail", return_value=(mock_led, 0)):
            rc = led_status()
        assert rc == 0
        out = capsys.readouterr().out
        assert "STATIC" in out
        assert "#ff0000" in out
        assert "80%" in out
        assert "ON" in out
        assert "2/3 on" in out

    def test_led_status_connect_fail(self, capsys):
        from trcc.cli._led import led_status
        mock_led = MagicMock()
        with patch("trcc.cli._led._connect_or_fail", return_value=(mock_led, 1)):
            rc = led_status()
        assert rc == 1
