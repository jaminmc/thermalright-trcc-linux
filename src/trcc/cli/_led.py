"""LED CLI commands — thin wrappers over Device.

Presentation-only: builder injected by _cmd_* boundary functions, call method, print result.
"""
from __future__ import annotations

from trcc.cli import _cli_handler
from trcc.core.models import parse_hex_color as _parse_hex

# =========================================================================
# CLI presentation helpers
# =========================================================================

def _connect_or_fail() -> int:
    """Connect LED via os_bus. Returns exit code (0 = success).

    DI chain: TrccApp.init() → set_ipc_handlers()
              → os_bus.dispatch(DiscoverDevicesCommand) → scan()
              → _wire_bus() → led_bus ready.
    """
    from trcc.core.app import TrccApp
    from trcc.core.commands.initialize import DiscoverDevicesCommand
    from trcc.core.instance import find_active
    from trcc.ipc import create_led_proxy

    app = TrccApp.get()
    app.set_ipc_handlers(find_active, create_led_proxy)
    result = app.os_bus.dispatch(DiscoverDevicesCommand())
    if not result.success or not app.has_led:
        print("No LED device found.")
        return 1
    return 0


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


def _led_dispatch(cmd_cls, preview: bool = False, **fields) -> int:
    """Connect LED, dispatch a command through the bus, print result."""
    rc = _connect_or_fail()
    if rc:
        return rc
    from trcc.core.app import TrccApp
    result = TrccApp.get().led_bus.dispatch(cmd_cls(**fields))
    return _print_result(result.payload, preview=preview)


# =========================================================================
# CLI functions (thin wrappers — print + exit code)
# =========================================================================

@_cli_handler
def set_color(builder, hex_color, *, preview=False):
    """Set LED static color."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.led import SetLEDColorCommand
    rgb = _parse_hex(hex_color)
    if not rgb:
        print("Error: Invalid hex color. Use format: ff0000")
        return 1
    rc = _connect_or_fail()
    if rc:
        return rc
    r, g, b = rgb
    result = TrccApp.get().led_bus.dispatch(SetLEDColorCommand(r=r, g=g, b=b))
    return _print_result(result.payload, preview=preview)


@_cli_handler
def set_mode(builder, mode_name, *, preview=False):
    """Set LED effect mode."""
    import time

    rc = _connect_or_fail()
    if rc:
        return rc
    from trcc.core.app import TrccApp
    from trcc.core.commands.led import SetLEDModeCommand
    result = TrccApp.get().led_bus.dispatch(SetLEDModeCommand(mode=mode_name)).payload
    if not result["success"]:
        print(f"Error: {result['error']}")
        if result.get("available"):
            print(f"Available: {', '.join(result['available'])}")
        return 1

    if result["animated"]:
        from trcc.cli import _ensure_system
        from trcc.core.commands.led import UpdateMetricsLEDCommand
        from trcc.services import LEDService
        from trcc.services.system import get_all_metrics

        _ensure_system(builder)
        led_bus = TrccApp.get().led_bus
        led_device = TrccApp.get().led_device
        assert led_device is not None
        print(f"LED mode: {mode_name} (running, Ctrl+C to stop)")
        _metric_ticks = 0
        try:
            while True:
                # Refresh sensor metrics every 20 ticks (~1 s)
                if _metric_ticks % 20 == 0:
                    led_bus.dispatch(UpdateMetricsLEDCommand(metrics=get_all_metrics()))
                _metric_ticks += 1
                tick = led_device.tick_with_result()
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
def set_led_brightness(builder, level, *, preview=False):
    """Set LED brightness (0-100)."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.led import SetLEDBrightnessCommand
    rc = _connect_or_fail()
    if rc:
        return rc
    result = TrccApp.get().led_bus.dispatch(SetLEDBrightnessCommand(level=level))
    return _print_result(result.payload, preview=preview)


@_cli_handler
def led_off(builder):
    """Turn LEDs off."""
    from trcc.core.commands.led import ToggleLEDCommand
    return _led_dispatch(ToggleLEDCommand, on=False)


@_cli_handler
def set_sensor_source(builder, source):
    """Set CPU/GPU sensor source for temp/load linked LED modes."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.led import SetLEDSensorSourceCommand
    rc = _connect_or_fail()
    if rc:
        return rc
    result = TrccApp.get().led_bus.dispatch(SetLEDSensorSourceCommand(source=source))
    return _print_result(result.payload)


@_cli_handler
def set_zone_color(builder, zone: int, hex_color: str, *, preview: bool = False):
    """Set color for a specific LED zone."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.led import SetZoneColorCommand
    rgb = _parse_hex(hex_color)
    if not rgb:
        print("Error: Invalid hex color. Use format: ff0000")
        return 1
    rc = _connect_or_fail()
    if rc:
        return rc
    r, g, b = rgb
    result = TrccApp.get().led_bus.dispatch(SetZoneColorCommand(zone=zone, r=r, g=g, b=b))
    return _print_result(result.payload, preview=preview)


@_cli_handler
def set_zone_mode(builder, zone: int, mode_name: str, *, preview: bool = False):
    """Set effect mode for a specific LED zone."""
    from trcc.core.commands.led import SetZoneModeCommand
    return _led_dispatch(SetZoneModeCommand, preview=preview, zone=zone, mode=mode_name)


@_cli_handler
def set_zone_brightness(builder, zone: int, level: int, *, preview: bool = False):
    """Set brightness for a specific LED zone (0-100)."""
    from trcc.core.commands.led import SetZoneBrightnessCommand
    return _led_dispatch(SetZoneBrightnessCommand, preview=preview, zone=zone, level=level)


@_cli_handler
def toggle_zone(builder, zone: int, on: bool):
    """Toggle a specific LED zone on/off."""
    from trcc.core.commands.led import ToggleZoneCommand
    return _led_dispatch(ToggleZoneCommand, zone=zone, on=on)


@_cli_handler
def set_zone_sync(builder, enabled: bool, *, interval: int | None = None):
    """Enable/disable zone sync (circulate or select-all depending on style)."""
    from trcc.core.commands.led import SetZoneSyncCommand
    return _led_dispatch(SetZoneSyncCommand, enabled=enabled, interval=interval)


@_cli_handler
def toggle_segment(builder, index: int, on: bool):
    """Toggle a specific LED segment on/off."""
    from trcc.core.commands.led import ToggleSegmentCommand
    return _led_dispatch(ToggleSegmentCommand, index=index, on=on)


@_cli_handler
def set_clock_format(builder, is_24h: bool):
    """Set LED segment display clock format (12h/24h)."""
    from trcc.core.commands.led import SetClockFormatCommand
    return _led_dispatch(SetClockFormatCommand, is_24h=is_24h)


@_cli_handler
def set_temp_unit(builder, unit: str):
    """Set LED segment display temperature unit (C/F)."""
    from trcc.core.commands.led import SetTempUnitLEDCommand
    return _led_dispatch(SetTempUnitLEDCommand, unit=unit)


# =========================================================================
# Developer test commands (no device needed)
# =========================================================================

def test_led(builder, *, mode: str | None = None, segments: int = 64,
             duration: int = 0):
    """Test LED ANSI preview with real system metrics. No device needed."""
    import time

    from trcc.cli import _ensure_system
    from trcc.core.models import LEDMode, LEDState
    from trcc.services.led import LEDService
    from trcc.services.system import get_instance

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

    _ensure_system(builder)
    sys_svc = get_instance()
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


def test_lcd(builder, *, cols: int = 60):
    """Test LCD ANSI preview with real system metrics. No device needed."""
    from trcc.cli import _ensure_system
    from trcc.services.image import ImageService
    from trcc.services.system import get_instance

    _ensure_system(builder)
    sys_svc = get_instance()
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
