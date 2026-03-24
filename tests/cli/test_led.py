"""Tests for LEDDevice (core/led_device.py) + CLI LED wrappers (_led.py).

Fixtures build mock LEDService and inject into LEDDevice. Tests verify
device methods return correct result dicts, and CLI wrappers print/exit
correctly.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trcc.core.led_device import LEDDevice
from trcc.core.models import LEDMode

# =========================================================================
# Patch-path constants
# =========================================================================
_CONNECT = "trcc.cli._led._connect_or_fail"
_IPC = "trcc.core.instance.find_active"


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture()
def mock_svc():
    """Fully mocked LEDService — no hardware required."""
    svc = MagicMock()
    svc.state = MagicMock()
    svc.state.zones = [MagicMock(), MagicMock(), MagicMock()]
    svc.state.segment_on = [True, False, True, False]
    svc.tick.return_value = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    svc.apply_mask.return_value = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    svc.has_protocol = True
    return svc


@pytest.fixture()
def led(mock_svc):
    """LEDDevice wired to mock service."""
    return LEDDevice(svc=mock_svc)


@pytest.fixture()
def led_empty():
    """LEDDevice with no service (not connected)."""
    return LEDDevice()


@pytest.fixture()
def led_no_zones(mock_svc):
    """LEDDevice with no zones (empty list)."""
    mock_svc.state.zones = []
    return LEDDevice(svc=mock_svc)


@pytest.fixture()
def led_no_segments(mock_svc):
    """LEDDevice with no segments (empty list)."""
    mock_svc.state.segment_on = []
    return LEDDevice(svc=mock_svc)


@pytest.fixture()
def mock_connect(led):
    """Patch _connect_or_fail to return a connected LEDDevice."""
    with patch(_CONNECT, return_value=(led, 0)):
        yield led


@pytest.fixture()
def mock_connect_fail():
    """Patch _connect_or_fail to simulate no device."""
    dev = MagicMock()
    with patch(_CONNECT, return_value=(dev, 1)):
        yield


# =========================================================================
# TestLEDDeviceInit
# =========================================================================

class TestLEDDeviceInit:
    """Construction, connected, status, service properties."""

    def test_default_init_no_svc(self, led_empty):
        assert led_empty._svc is None

    def test_init_with_svc(self, mock_svc, led):
        assert led._svc is mock_svc

    def test_connected_false_when_no_svc(self, led_empty):
        assert led_empty.connected is False

    def test_connected_true_when_svc_set(self, led):
        assert led.connected is True

    def test_status_initially_none(self, led):
        assert led.status is None

    def test_status_reflects_init_status(self, led):
        led._init_status = "AX120 (style 1)"
        assert led.status == "AX120 (style 1)"

    def test_service_property_returns_svc(self, mock_svc, led):
        assert led.service is mock_svc

    def test_service_property_none_when_disconnected(self, led_empty):
        assert led_empty.service is None


# =========================================================================
# TestLEDDeviceModeResolution
# =========================================================================

class TestLEDDeviceModeResolution:
    """_resolve_mode() — string, enum, int resolution."""

    def test_resolve_string_static(self, led):
        assert led._resolve_mode('static') is LEDMode.STATIC

    def test_resolve_string_breathing(self, led):
        assert led._resolve_mode('breathing') is LEDMode.BREATHING

    def test_resolve_string_colorful(self, led):
        assert led._resolve_mode('colorful') is LEDMode.COLORFUL

    def test_resolve_string_rainbow(self, led):
        assert led._resolve_mode('rainbow') is LEDMode.RAINBOW

    def test_resolve_string_case_insensitive(self, led):
        assert led._resolve_mode('STATIC') is LEDMode.STATIC
        assert led._resolve_mode('Breathing') is LEDMode.BREATHING

    def test_resolve_enum_passthrough(self, led):
        assert led._resolve_mode(LEDMode.STATIC) is LEDMode.STATIC

    def test_resolve_int_value(self, led):
        mode = led._resolve_mode(LEDMode.STATIC.value)
        assert mode is LEDMode.STATIC

    def test_resolve_unknown_string_returns_none(self, led):
        assert led._resolve_mode('fireworks') is None

    def test_resolve_unknown_int_returns_none(self, led):
        assert led._resolve_mode(9999) is None


# =========================================================================
# TestLEDDeviceConnect
# =========================================================================

class TestLEDDeviceConnect:
    """connect() with mocked detect_devices + LEDService."""

    def test_connect_returns_success_when_already_connected(self, mock_svc):
        dev = LEDDevice(svc=mock_svc)
        dev._init_status = "connected"
        result = dev.connect()
        assert result["success"] is True
        assert result["status"] == "connected"

    def test_connect_no_led_device_directly(self):
        """connect() returns failure when no hid_led device found."""
        fake_dev = MagicMock()
        fake_dev.implementation = 'hid_lcd'
        mock_dev_svc = MagicMock()
        mock_dev_svc.devices = [fake_dev]

        dev = LEDDevice(device_svc=mock_dev_svc)
        with patch('trcc.services.LEDService'):
            result = dev.connect()
        assert result["success"] is False
        assert "No LED device" in result["error"]

    def test_connect_empty_device_list(self):
        """connect() returns failure when device list is empty."""
        mock_dev_svc = MagicMock()
        mock_dev_svc.devices = []

        dev = LEDDevice(device_svc=mock_dev_svc)
        result = dev.connect()
        assert result["success"] is False
        assert "No LED device" in result["error"]

    def test_connect_success_sets_svc(self):
        """connect() sets _svc and _init_status on success."""
        led_dev = MagicMock()
        led_dev.implementation = 'hid_led'
        led_dev.led_style_id = 1

        fake_svc = MagicMock()
        fake_svc.initialize.return_value = "AX120"

        mock_dev_svc = MagicMock()
        mock_dev_svc.devices = [led_dev]

        dev = LEDDevice(device_svc=mock_dev_svc)
        with patch('trcc.services.LEDService', return_value=fake_svc):
            result = dev.connect()

        assert result["success"] is True
        assert dev._svc is fake_svc
        assert dev._init_status == "AX120"


# =========================================================================
# TestLEDDeviceValidation
# =========================================================================

class TestLEDDeviceValidation:
    """_validate_zone and _validate_segment bounds checking."""

    def test_validate_zone_valid(self, led):
        assert led._validate_zone(0) is None
        assert led._validate_zone(1) is None
        assert led._validate_zone(2) is None

    def test_validate_zone_negative(self, led):
        err = led._validate_zone(-1)
        assert err is not None
        assert err["success"] is False
        assert "out of range" in err["error"]

    def test_validate_zone_too_high(self, led):
        err = led._validate_zone(3)  # only 0-2 valid (3 zones)
        assert err is not None
        assert err["success"] is False

    def test_validate_zone_empty_list(self, led_no_zones):
        err = led_no_zones._validate_zone(0)
        assert err is not None
        assert "no zones" in err["error"]

    def test_validate_segment_valid(self, led):
        assert led._validate_segment(0) is None
        assert led._validate_segment(3) is None

    def test_validate_segment_negative(self, led):
        err = led._validate_segment(-1)
        assert err is not None
        assert err["success"] is False
        assert "out of range" in err["error"]

    def test_validate_segment_too_high(self, led):
        err = led._validate_segment(4)  # only 0-3 valid (4 segments)
        assert err is not None
        assert err["success"] is False

    def test_validate_segment_empty_list(self, led_no_segments):
        err = led_no_segments._validate_segment(0)
        assert err is not None
        assert "no segments" in err["error"]

    def test_validate_zone_range_message_includes_max(self, led):
        err = led._validate_zone(99)
        assert "2" in err["error"]  # max index is 2 (3 zones)


# =========================================================================
# TestLEDDeviceInternalHelpers
# =========================================================================

class TestLEDDeviceInternalHelpers:
    """_apply_and_send and _send_and_save."""

    def test_apply_and_send_calls_toggle_global_true(self, led, mock_svc):
        led._apply_and_send()
        mock_svc.toggle_global.assert_called_with(True)

    def test_apply_and_send_calls_tick(self, led, mock_svc):
        led._apply_and_send()
        mock_svc.tick.assert_called_once()

    def test_apply_and_send_calls_send_colors(self, led, mock_svc):
        colors = mock_svc.tick.return_value
        led._apply_and_send()
        mock_svc.send_colors.assert_called_once_with(colors)

    def test_apply_and_send_calls_save_config(self, led, mock_svc):
        led._apply_and_send()
        mock_svc.save_config.assert_called_once()

    def test_apply_and_send_returns_colors(self, led, mock_svc):
        result = led._apply_and_send()
        assert result == mock_svc.tick.return_value

    def test_send_and_save_calls_send_tick(self, led, mock_svc):
        led._send_and_save()
        mock_svc.send_tick.assert_called_once()

    def test_send_and_save_calls_save_config(self, led, mock_svc):
        led._send_and_save()
        mock_svc.save_config.assert_called_once()


# =========================================================================
# TestLEDDeviceGlobalOps
# =========================================================================

class TestLEDDeviceGlobalOps:
    """set_color, set_mode, set_brightness, off, set_sensor_source."""

    def test_set_color_success(self, led):
        result = led.set_color(255, 0, 0)
        assert result["success"] is True
        assert "ff0000" in result["message"]

    def test_set_color_calls_set_mode_static(self, led, mock_svc):
        led.set_color(0, 255, 0)
        mock_svc.set_mode.assert_called_once_with(LEDMode.STATIC)

    def test_set_color_calls_set_color_on_svc(self, led, mock_svc):
        led.set_color(10, 20, 30)
        mock_svc.set_color.assert_called_once_with(10, 20, 30)

    def test_set_color_returns_colors(self, led, mock_svc):
        result = led.set_color(255, 0, 0)
        assert result["colors"] == mock_svc.tick.return_value

    def test_set_mode_static_not_animated(self, led):
        result = led.set_mode('static')
        assert result["success"] is True
        assert result["animated"] is False

    def test_set_mode_breathing_is_animated(self, led):
        result = led.set_mode('breathing')
        assert result["success"] is True
        assert result["animated"] is True

    def test_set_mode_colorful_is_animated(self, led):
        result = led.set_mode('colorful')
        assert result["success"] is True
        assert result["animated"] is True

    def test_set_mode_rainbow_is_animated(self, led):
        result = led.set_mode('rainbow')
        assert result["success"] is True
        assert result["animated"] is True

    def test_set_mode_unknown_fails(self, led):
        result = led.set_mode('fireworks')
        assert result["success"] is False
        assert "fireworks" in result["error"]
        assert "available" in result

    def test_set_mode_unknown_lists_available(self, led):
        result = led.set_mode('bad_mode')
        avail = result["available"]
        assert 'static' in avail
        assert 'breathing' in avail
        assert 'colorful' in avail
        assert 'rainbow' in avail

    def test_set_mode_case_insensitive(self, led):
        result = led.set_mode('STATIC')
        assert result["success"] is True

    def test_set_mode_calls_svc_set_mode(self, led, mock_svc):
        led.set_mode('static')
        mock_svc.set_mode.assert_called_once_with(LEDMode.STATIC)

    def test_set_brightness_success(self, led):
        result = led.set_brightness(75)
        assert result["success"] is True
        assert "75%" in result["message"]

    def test_set_brightness_zero(self, led):
        result = led.set_brightness(0)
        assert result["success"] is True

    def test_set_brightness_hundred(self, led):
        result = led.set_brightness(100)
        assert result["success"] is True

    def test_set_brightness_negative_fails(self, led):
        result = led.set_brightness(-1)
        assert result["success"] is False
        assert "0-100" in result["error"]

    def test_set_brightness_over_100_fails(self, led):
        result = led.set_brightness(101)
        assert result["success"] is False

    def test_set_brightness_calls_svc(self, led, mock_svc):
        led.set_brightness(50)
        mock_svc.set_brightness.assert_called_once_with(50)

    def test_off_success(self, led, mock_svc):
        result = led.off()
        assert result["success"] is True
        assert "off" in result["message"].lower()

    def test_off_calls_toggle_global_false(self, led, mock_svc):
        led.off()
        mock_svc.toggle_global.assert_called_with(False)

    def test_off_calls_send_tick(self, led, mock_svc):
        led.off()
        mock_svc.send_tick.assert_called_once()

    def test_set_sensor_source_cpu(self, led, mock_svc):
        result = led.set_sensor_source('cpu')
        assert result["success"] is True
        assert "CPU" in result["message"]

    def test_set_sensor_source_gpu(self, led, mock_svc):
        result = led.set_sensor_source('gpu')
        assert result["success"] is True
        assert "GPU" in result["message"]

    def test_set_sensor_source_case_insensitive(self, led, mock_svc):
        result = led.set_sensor_source('CPU')
        assert result["success"] is True

    def test_set_sensor_source_invalid(self, led):
        result = led.set_sensor_source('tpu')
        assert result["success"] is False
        assert "cpu" in result["error"].lower() or "gpu" in result["error"].lower()

    def test_set_sensor_source_calls_svc(self, led, mock_svc):
        led.set_sensor_source('gpu')
        mock_svc.set_sensor_source.assert_called_once_with('gpu')

    def test_set_sensor_source_saves_config(self, led, mock_svc):
        led.set_sensor_source('cpu')
        mock_svc.save_config.assert_called_once()


# =========================================================================
# TestLEDDeviceZoneOps
# =========================================================================

class TestLEDDeviceZoneOps:
    """set_zone_color, set_zone_mode, set_zone_brightness, toggle_zone, set_zone_sync."""

    def test_set_zone_color_valid(self, led, mock_svc):
        result = led.set_zone_color(0, 255, 128, 0)
        assert result["success"] is True
        assert "Zone 0" in result["message"]
        assert "ff8000" in result["message"]

    def test_set_zone_color_invalid_zone(self, led):
        result = led.set_zone_color(99, 255, 0, 0)
        assert result["success"] is False

    def test_set_zone_color_negative_zone(self, led):
        result = led.set_zone_color(-1, 255, 0, 0)
        assert result["success"] is False

    def test_set_zone_color_calls_svc(self, led, mock_svc):
        led.set_zone_color(1, 10, 20, 30)
        mock_svc.set_zone_color.assert_called_once_with(1, 10, 20, 30)

    def test_set_zone_mode_valid(self, led, mock_svc):
        result = led.set_zone_mode(0, 'static')
        assert result["success"] is True
        assert "Zone 0" in result["message"]

    def test_set_zone_mode_invalid_zone(self, led):
        result = led.set_zone_mode(10, 'static')
        assert result["success"] is False

    def test_set_zone_mode_unknown_mode(self, led):
        result = led.set_zone_mode(0, 'laser')
        assert result["success"] is False
        assert "laser" in result["error"]

    def test_set_zone_mode_calls_svc(self, led, mock_svc):
        led.set_zone_mode(2, 'breathing')
        mock_svc.set_zone_mode.assert_called_once_with(2, LEDMode.BREATHING)

    def test_set_zone_brightness_valid(self, led, mock_svc):
        result = led.set_zone_brightness(0, 80)
        assert result["success"] is True
        assert "Zone 0" in result["message"]
        assert "80%" in result["message"]

    def test_set_zone_brightness_invalid_zone(self, led):
        result = led.set_zone_brightness(99, 50)
        assert result["success"] is False

    def test_set_zone_brightness_too_high(self, led):
        result = led.set_zone_brightness(0, 101)
        assert result["success"] is False
        assert "0-100" in result["error"]

    def test_set_zone_brightness_negative(self, led):
        result = led.set_zone_brightness(0, -5)
        assert result["success"] is False

    def test_set_zone_brightness_calls_svc(self, led, mock_svc):
        led.set_zone_brightness(1, 50)
        mock_svc.set_zone_brightness.assert_called_once_with(1, 50)

    def test_toggle_zone_on(self, led, mock_svc):
        result = led.toggle_zone(0, True)
        assert result["success"] is True
        assert "ON" in result["message"]

    def test_toggle_zone_off(self, led, mock_svc):
        result = led.toggle_zone(1, False)
        assert result["success"] is True
        assert "OFF" in result["message"]

    def test_toggle_zone_invalid_zone(self, led):
        result = led.toggle_zone(99, True)
        assert result["success"] is False

    def test_toggle_zone_calls_svc(self, led, mock_svc):
        led.toggle_zone(2, True)
        mock_svc.toggle_zone.assert_called_once_with(2, True)

    def test_set_zone_sync_enabled(self, led, mock_svc):
        result = led.set_zone_sync(True)
        assert result["success"] is True
        assert "enabled" in result["message"]

    def test_set_zone_sync_disabled(self, led, mock_svc):
        result = led.set_zone_sync(False)
        assert result["success"] is True
        assert "disabled" in result["message"]

    def test_set_zone_sync_with_interval(self, led, mock_svc):
        result = led.set_zone_sync(True, interval=5)
        assert result["success"] is True
        mock_svc.set_zone_sync_interval.assert_called_once_with(5)

    def test_set_zone_sync_no_interval_skips_set_interval(self, led, mock_svc):
        led.set_zone_sync(True, interval=None)
        mock_svc.set_zone_sync_interval.assert_not_called()

    def test_set_zone_sync_calls_svc(self, led, mock_svc):
        led.set_zone_sync(True)
        mock_svc.set_zone_sync.assert_called_once_with(True)


# =========================================================================
# TestLEDDeviceSegmentOps
# =========================================================================

class TestLEDDeviceSegmentOps:
    """toggle_segment, set_clock_format, set_temp_unit."""

    def test_toggle_segment_on(self, led, mock_svc):
        result = led.toggle_segment(0, True)
        assert result["success"] is True
        assert "ON" in result["message"]

    def test_toggle_segment_off(self, led, mock_svc):
        result = led.toggle_segment(1, False)
        assert result["success"] is True
        assert "OFF" in result["message"]

    def test_toggle_segment_invalid_index(self, led):
        result = led.toggle_segment(99, True)
        assert result["success"] is False

    def test_toggle_segment_negative_index(self, led):
        result = led.toggle_segment(-1, True)
        assert result["success"] is False

    def test_toggle_segment_calls_svc(self, led, mock_svc):
        led.toggle_segment(2, False)
        mock_svc.toggle_segment.assert_called_once_with(2, False)

    def test_toggle_segment_empty_list(self, led_no_segments):
        result = led_no_segments.toggle_segment(0, True)
        assert result["success"] is False
        assert "no segments" in result["error"]

    def test_set_clock_format_24h(self, led, mock_svc):
        result = led.set_clock_format(True)
        assert result["success"] is True
        assert "24h" in result["message"]

    def test_set_clock_format_12h(self, led, mock_svc):
        result = led.set_clock_format(False)
        assert result["success"] is True
        assert "12h" in result["message"]

    def test_set_clock_format_calls_svc(self, led, mock_svc):
        led.set_clock_format(True)
        mock_svc.set_clock_format.assert_called_once_with(True)

    def test_set_temp_unit_celsius(self, led, mock_svc):
        result = led.set_temp_unit('C')
        assert result["success"] is True
        assert "C" in result["message"]

    def test_set_temp_unit_fahrenheit(self, led, mock_svc):
        result = led.set_temp_unit('F')
        assert result["success"] is True
        assert "F" in result["message"]

    def test_set_temp_unit_lowercase(self, led, mock_svc):
        result = led.set_temp_unit('f')
        assert result["success"] is True

    def test_set_temp_unit_invalid(self, led):
        result = led.set_temp_unit('K')
        assert result["success"] is False
        assert "C" in result["error"] and "F" in result["error"]

    def test_set_temp_unit_calls_svc(self, led, mock_svc):
        led.set_temp_unit('C')
        mock_svc.set_seg_temp_unit.assert_called_once_with('C')


# =========================================================================
# TestLEDDeviceTick
# =========================================================================

class TestLEDDeviceTick:
    """tick() — advance one animation frame."""

    def test_tick_returns_colors(self, led, mock_svc):
        result = led.tick_with_result()
        assert "colors" in result
        assert result["colors"] == mock_svc.tick.return_value

    def test_tick_calls_svc_tick(self, led, mock_svc):
        led.tick()
        mock_svc.tick.assert_called_once()

    def test_tick_calls_send_colors(self, led, mock_svc):
        colors = mock_svc.tick.return_value
        led.tick()
        mock_svc.send_colors.assert_called_once_with(colors)

    def test_tick_returns_display_colors(self, led, mock_svc):
        result = led.tick_with_result()
        assert "display_colors" in result


# =========================================================================
# TestCLIHelpers — _connect_or_fail, _print_result, _led_command
# =========================================================================

class TestCLIHelpers:
    """CLI presentation helpers in _led.py."""

    # _connect_or_fail takes builder directly — no ControllerBuilder patching needed.

    def test_connect_or_fail_success(self, capsys):
        from trcc.cli._led import _connect_or_fail

        fake_led = LEDDevice()
        fake_led._svc = MagicMock()
        fake_led._init_status = "AX120"
        mock_builder = MagicMock()
        mock_builder.build_led.return_value = fake_led

        with patch.object(fake_led, "connect",
                          return_value={"success": True, "status": "AX120"}), \
             patch(_IPC, return_value=None):
            led, rc = _connect_or_fail(mock_builder)

        assert rc == 0
        assert led.connected is True
        assert "AX120" in capsys.readouterr().out

    def test_connect_or_fail_no_device(self, capsys):
        from trcc.cli._led import _connect_or_fail

        fake_led = LEDDevice()
        mock_builder = MagicMock()
        mock_builder.build_led.return_value = fake_led

        with patch.object(fake_led, "connect",
                          return_value={"success": False,
                                        "error": "No LED device found"}), \
             patch(_IPC, return_value=None):
            led, rc = _connect_or_fail(mock_builder)

        assert rc == 1
        assert "No LED device" in capsys.readouterr().out

    def test_connect_or_fail_no_status_printed(self, capsys):
        from trcc.cli._led import _connect_or_fail

        fake_led = LEDDevice()
        fake_led._svc = MagicMock()
        mock_builder = MagicMock()
        mock_builder.build_led.return_value = fake_led

        with patch.object(fake_led, "connect",
                          return_value={"success": True}), \
             patch(_IPC, return_value=None):
            _, rc = _connect_or_fail(mock_builder)

        assert rc == 0
        assert capsys.readouterr().out.strip() == ""

    def test_print_result_success(self, capsys):
        from trcc.cli._led import _print_result

        result = {"success": True, "message": "Done!"}
        rc = _print_result(result)
        assert rc == 0
        assert "Done!" in capsys.readouterr().out

    def test_print_result_failure(self, capsys):
        from trcc.cli._led import _print_result

        result = {"success": False, "error": "Something failed"}
        rc = _print_result(result)
        assert rc == 1
        assert "Something failed" in capsys.readouterr().out

    def test_print_result_failure_no_error_key(self, capsys):
        from trcc.cli._led import _print_result

        result = {"success": False}
        rc = _print_result(result)
        assert rc == 1
        assert "Unknown error" in capsys.readouterr().out

    def test_print_result_preview_calls_zones_to_ansi(self, capsys):
        from trcc.cli._led import _print_result

        colors = [(255, 0, 0)]
        result = {"success": True, "message": "ok", "colors": colors}
        with patch('trcc.services.LEDService.zones_to_ansi',
                   return_value="[ANSI]") as mock_ansi:
            rc = _print_result(result, preview=True)
        assert rc == 0
        mock_ansi.assert_called_once_with(colors)

    def test_print_result_no_preview_no_ansi(self, capsys):
        from trcc.cli._led import _print_result

        result = {"success": True, "message": "ok", "colors": [(255, 0, 0)]}
        with patch('trcc.services.LEDService.zones_to_ansi') as mock_ansi:
            _print_result(result, preview=False)
        mock_ansi.assert_not_called()

    def test_print_result_preview_skipped_when_no_colors(self, capsys):
        from trcc.cli._led import _print_result

        result = {"success": True, "message": "ok"}
        with patch('trcc.services.LEDService.zones_to_ansi') as mock_ansi:
            _print_result(result, preview=True)
        mock_ansi.assert_not_called()

    def test_led_command_no_device(self, mock_connect_fail):
        from trcc.cli._led import _led_command

        rc = _led_command(MagicMock(), "off")
        assert rc == 1

    def test_led_command_success(self, mock_connect):
        from trcc.cli._led import _led_command

        rc = _led_command(MagicMock(), "off")
        assert rc == 0

    def test_get_led_service_no_device(self, _mock_builder):
        """Backward-compat _get_led_service returns (None, None)."""
        from trcc.cli._led import _get_led_service

        dev = LEDDevice()
        _mock_builder.build_led.return_value = dev
        with patch.object(dev, 'connect',
                          return_value={"success": False, "error": "no device"}):
            svc, status = _get_led_service()
        assert svc is None
        assert status is None

    def test_get_led_service_success(self, mock_svc, _mock_builder):
        """Backward-compat _get_led_service returns (svc, status)."""
        from trcc.cli._led import _get_led_service

        dev = LEDDevice(svc=mock_svc)
        dev._init_status = "PA120"
        _mock_builder.build_led.return_value = dev
        with patch.object(dev, 'connect',
                          return_value={"success": True, "status": "PA120"}):
            svc, status = _get_led_service()
        assert svc is mock_svc
        assert status == "PA120"


# =========================================================================
# TestCLISetColor — test through the Typer boundary (CliRunner)
# =========================================================================

class TestCLISetColor:
    """set_color CLI command — valid/invalid hex, preview.

    Uses CliRunner so TrccApp injection flows through the real Typer boundary.
    _connect_or_fail is patched to avoid hardware; output is in result.stdout.
    """

    def test_set_color_valid_hex(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-color', 'ff0000'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0
        assert "ff0000" in result.stdout

    def test_set_color_with_hash_prefix(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-color', '#00ff00'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_color_invalid_hex(self):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-color', 'zzzzzz'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1
        assert "Invalid hex" in result.stdout

    def test_set_color_too_short_hex(self):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-color', 'ff00'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_color_no_device(self, mock_connect_fail):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-color', 'ff0000'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_color_with_preview(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        with patch('trcc.services.LEDService.zones_to_ansi', return_value="[ANSI]"):
            result = CliRunner().invoke(app, ['led-color', '0000ff', '--preview'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0
        assert "[ANSI]" in result.stdout


# =========================================================================
# TestCLISetMode — test through the Typer boundary (CliRunner)
# =========================================================================

class TestCLISetMode:
    """set_mode CLI — static/animated/unknown, preview, KeyboardInterrupt."""

    def test_set_mode_static(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-mode', 'static'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0
        assert "static" in result.stdout.lower()

    def test_set_mode_unknown(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-mode', 'fireworks'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1
        assert "fireworks" in result.stdout

    def test_set_mode_unknown_prints_available(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-mode', 'bad'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1
        assert "Available" in result.stdout

    def test_set_mode_no_device(self, mock_connect_fail):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-mode', 'static'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_mode_animated_runs_loop(self, mock_connect):
        """Animated mode enters loop; KeyboardInterrupt exits cleanly."""
        from typer.testing import CliRunner

        from trcc.cli import app
        with patch('time.sleep', side_effect=KeyboardInterrupt), \
             patch('trcc.services.LEDService.zones_to_ansi', return_value=""):
            result = CliRunner().invoke(app, ['led-mode', 'breathing'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0
        assert "Stopped" in result.stdout

    def test_set_mode_animated_with_preview(self, mock_connect, mock_svc):
        """Animated preview calls zones_to_ansi on each tick."""
        from typer.testing import CliRunner

        from trcc.cli import app
        mock_svc.tick.return_value = [(255, 0, 0)]
        with patch('time.sleep', side_effect=KeyboardInterrupt), \
             patch('trcc.services.LEDService.zones_to_ansi',
                   return_value="[ANSI]") as mock_ansi:
            result = CliRunner().invoke(app, ['led-mode', 'rainbow', '--preview'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0
        mock_ansi.assert_called()

    def test_set_mode_static_with_preview(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        with patch('trcc.services.LEDService.zones_to_ansi', return_value="[ANSI]"):
            result = CliRunner().invoke(app, ['led-mode', 'static', '--preview'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0
        assert "[ANSI]" in result.stdout


# =========================================================================
# TestCLICommands — remaining thin CLI wrappers (CliRunner)
# =========================================================================

class TestCLICommands:
    """set_led_brightness, led_off, set_sensor_source, zone/segment commands."""

    def test_set_led_brightness_success(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-brightness', '60'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_led_brightness_invalid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-brightness', '200'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1
        assert "0-100" in result.stdout

    def test_led_off_success(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-off'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_led_off_no_device(self, mock_connect_fail):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-off'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_sensor_source_cpu(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-sensor', 'cpu'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_sensor_source_invalid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-sensor', 'fan'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_zone_color_valid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-color', '0', 'ff0000'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_zone_color_invalid_hex(self):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-color', '0', 'xyz'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1
        assert "Invalid hex" in result.stdout

    def test_set_zone_color_no_device(self, mock_connect_fail):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-color', '0', 'ff0000'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_zone_mode_valid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-mode', '0', 'static'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_zone_mode_invalid_zone(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-mode', '99', 'static'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_zone_brightness_valid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-brightness', '0', '75'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_zone_brightness_invalid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-brightness', '0', '999'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_toggle_zone_on(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-toggle', '1', 'true'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_toggle_zone_off(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-toggle', '2', 'false'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_toggle_zone_invalid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-toggle', '99', 'true'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_zone_sync_enabled(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-sync', 'true'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_zone_sync_disabled(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-sync', 'false'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_zone_sync_with_interval(self, mock_connect, mock_svc):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-zone-sync', 'true', '--interval', '3'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0
        mock_svc.set_zone_sync_interval.assert_called_once_with(3)

    def test_toggle_segment_on(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-segment', '0', 'true'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_toggle_segment_invalid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-segment', '99', 'true'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1

    def test_set_clock_format_24h(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-clock', 'true'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_clock_format_12h(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-clock', 'false'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_temp_unit_celsius(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-temp-unit', 'C'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_temp_unit_fahrenheit(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-temp-unit', 'F'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 0

    def test_set_temp_unit_invalid(self, mock_connect):
        from typer.testing import CliRunner

        from trcc.cli import app
        result = CliRunner().invoke(app, ['led-temp-unit', 'X'], standalone_mode=False, catch_exceptions=False)
        assert result.return_value == 1
