"""LED CLI commands — thin print wrappers over LEDDevice.

LEDDevice lives in core/led_device.py (DIP). These CLI functions are
presentation-only adapters: connect, call device method, print result.
"""
from __future__ import annotations

from trcc.cli import _cli_handler
from trcc.core.led_device import LEDDevice
from trcc.core.models import parse_hex_color as _parse_hex

# =========================================================================
# CLI presentation helpers
# =========================================================================

def _connect_or_fail() -> tuple[LEDDevice, int]:
    """Create device, connect. Returns (device, exit_code).

    When the GUI daemon is running, returns an IPC proxy that routes
    all commands through the daemon.
    """
    from trcc.ipc import IPCClient, IPCLEDProxy
    if IPCClient.available():
        return IPCLEDProxy(), 0  # type: ignore[return-value]
    led = LEDDevice()
    result = led.connect()
    if not result["success"]:
        print("No LED device found.")
        return led, 1
    if result.get("status"):
        print(result["status"])
    return led, 0


def _print_result(result: dict, *, preview: bool = False) -> int:
    """Print result message + optional ANSI preview. Returns exit code."""
    if not result["success"]:
        print(f"Error: {result.get('error', 'Unknown error')}")
        return 1
    print(result["message"])
    if preview and result.get("colors"):
        from trcc.services import LEDService
        print(LEDService.zones_to_ansi(result["colors"]))
    return 0


def _led_command(method: str, *args, preview: bool = False, **kwargs) -> int:
    """Generic: connect LED, call device method, print result."""
    led, rc = _connect_or_fail()
    if rc:
        return rc
    return _print_result(getattr(led, method)(*args, **kwargs), preview=preview)


# =========================================================================
# CLI functions (thin wrappers — print + exit code)
# =========================================================================

# Keep _get_led_service for backward compat (tests import it)
def _get_led_service():
    """Detect LED device and create initialized LEDService."""
    led = LEDDevice()
    result = led.connect()
    if not result["success"]:
        return None, None
    return led.service, result["status"]


@_cli_handler
def set_color(hex_color, *, preview=False):
    """Set LED static color."""
    rgb = _parse_hex(hex_color)
    if not rgb:
        print("Error: Invalid hex color. Use format: ff0000")
        return 1

    led, rc = _connect_or_fail()
    if rc:
        return rc
    return _print_result(led.set_color(*rgb), preview=preview)


@_cli_handler
def set_mode(mode_name, *, preview=False):
    """Set LED effect mode."""
    import time

    led, rc = _connect_or_fail()
    if rc:
        return rc

    result = led.set_mode(mode_name)
    if not result["success"]:
        print(f"Error: {result['error']}")
        if result.get("available"):
            print(f"Available: {', '.join(result['available'])}")
        return 1

    if result["animated"]:
        from trcc.services import LEDService

        print(f"LED mode: {mode_name} (running animation, Ctrl+C to stop)")
        try:
            while True:
                tick = led.tick()
                if preview and tick.get("colors"):
                    print(LEDService.zones_to_ansi(tick["colors"]),
                          end='\r', flush=True)
                time.sleep(0.05)
        except KeyboardInterrupt:
            pass
        print("\nStopped.")
    else:
        print(result["message"])
        if preview and result.get("colors"):
            from trcc.services import LEDService
            print(LEDService.zones_to_ansi(result["colors"]))

    return 0


@_cli_handler
def set_led_brightness(level, *, preview=False):
    """Set LED brightness (0-100)."""
    return _led_command("set_brightness", level, preview=preview)


@_cli_handler
def led_off():
    """Turn LEDs off."""
    return _led_command("off")


@_cli_handler
def set_sensor_source(source):
    """Set CPU/GPU sensor source for temp/load linked LED modes."""
    return _led_command("set_sensor_source", source)


@_cli_handler
def set_zone_color(zone: int, hex_color: str, *, preview: bool = False):
    """Set color for a specific LED zone."""
    rgb = _parse_hex(hex_color)
    if not rgb:
        print("Error: Invalid hex color. Use format: ff0000")
        return 1

    led, rc = _connect_or_fail()
    if rc:
        return rc
    return _print_result(led.set_zone_color(zone, *rgb), preview=preview)


@_cli_handler
def set_zone_mode(zone: int, mode_name: str, *, preview: bool = False):
    """Set effect mode for a specific LED zone."""
    return _led_command("set_zone_mode", zone, mode_name, preview=preview)


@_cli_handler
def set_zone_brightness(zone: int, level: int, *, preview: bool = False):
    """Set brightness for a specific LED zone (0-100)."""
    return _led_command("set_zone_brightness", zone, level, preview=preview)


@_cli_handler
def toggle_zone(zone: int, on: bool):
    """Toggle a specific LED zone on/off."""
    return _led_command("toggle_zone", zone, on)


@_cli_handler
def set_zone_sync(enabled: bool, *, interval: int | None = None):
    """Enable/disable zone sync (circulate or select-all depending on style)."""
    return _led_command("set_zone_sync", enabled, interval=interval)


@_cli_handler
def toggle_segment(index: int, on: bool):
    """Toggle a specific LED segment on/off."""
    return _led_command("toggle_segment", index, on)


@_cli_handler
def set_clock_format(is_24h: bool):
    """Set LED segment display clock format (12h/24h)."""
    return _led_command("set_clock_format", is_24h)


@_cli_handler
def set_temp_unit(unit: str):
    """Set LED segment display temperature unit (C/F)."""
    return _led_command("set_temp_unit", unit)


# =========================================================================
# Developer test commands (no device needed)
# =========================================================================

def test_led(*, mode: str | None = None, segments: int = 64,
             duration: int = 0):
    """Test LED ANSI preview with real system metrics. No device needed."""
    import time

    from trcc.adapters.system.sensors import SensorEnumerator
    from trcc.core.models import LEDMode, LEDState
    from trcc.services.led import LEDService
    from trcc.services.system import SystemService

    modes = {
        'static': LEDMode.STATIC,
        'breathing': LEDMode.BREATHING,
        'colorful': LEDMode.COLORFUL,
        'rainbow': LEDMode.RAINBOW,
    }

    if mode:
        key = mode.lower()
        if key not in modes:
            print(f"Unknown mode '{mode}'. Choose: {', '.join(modes)}")
            return 1
        run_modes = {key: modes[key]}
    else:
        run_modes = modes

    sys_svc = SystemService(enumerator=SensorEnumerator())
    sys_svc.discover()
    metrics = sys_svc.all_metrics

    print(f"LED ANSI Preview ({segments} segments)")
    print(f"CPU: {metrics.cpu_temp:.0f}°C {metrics.cpu_percent:.0f}%  "
          f"GPU: {metrics.gpu_temp:.0f}°C {metrics.gpu_usage:.0f}%  "
          f"MEM: {metrics.mem_percent:.0f}%")
    print("─" * 60)

    try:
        start = time.monotonic()
        for mode_name, led_mode in run_modes.items():
            state = LEDState()
            state.mode = led_mode
            state.color = (255, 0, 0) if led_mode == LEDMode.STATIC else (0, 255, 255)
            state.segment_count = segments
            state.global_on = True
            state.brightness = 100
            svc = LEDService(state=state)
            svc.update_metrics(metrics)

            animated = led_mode in (LEDMode.BREATHING, LEDMode.COLORFUL,
                                    LEDMode.RAINBOW)
            if animated:
                print(f"\n  {mode_name} (animating, Ctrl+C to skip)")
                ticks = 60 if duration == 0 else duration * 20
                for _ in range(ticks):
                    colors = svc.tick()
                    line = LEDService.zones_to_ansi(colors[:20])
                    print(f'  {line}', end='\r', flush=True)
                    if duration and (time.monotonic() - start) >= duration:
                        break
                    time.sleep(0.05)
                print()
            else:
                colors = svc.tick()
                line = LEDService.zones_to_ansi(colors[:20])
                print(f"  {mode_name:12s} {line}")

        sys_svc.stop_polling()
        print("\nDone.")
        return 0
    except KeyboardInterrupt:
        sys_svc.stop_polling()
        print("\nStopped.")
        return 0
    except Exception as e:
        print(f"Error: {e}")
        return 1


def test_lcd(*, cols: int = 60):
    """Test LCD ANSI preview with real system metrics. No device needed."""
    from trcc.adapters.system.sensors import SensorEnumerator
    from trcc.services.image import ImageService
    from trcc.services.system import SystemService

    sys_svc = SystemService(enumerator=SensorEnumerator())
    sys_svc.discover()
    metrics = sys_svc.all_metrics

    print(f"LCD ANSI Preview ({cols} cols)")
    print("─" * 60)

    print("\n  All metrics:")
    print(ImageService.metrics_to_ansi(metrics, cols=cols))

    for group in ('cpu', 'gpu', 'mem', 'disk', 'net', 'fan', 'time'):
        print(f"\n  {group.upper()}:")
        print(ImageService.metrics_to_ansi(metrics, cols=cols, group=group))

    sys_svc.stop_polling()
    print("\nDone.")
    return 0
