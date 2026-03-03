"""LED color, mode, brightness control commands.

LEDDispatcher is the single authority for all LED operations.
GUI and API import LEDDispatcher directly; CLI functions are thin
presentation wrappers (print + exit code).
"""
from __future__ import annotations

from typing import Any

from trcc.cli import _cli_handler
from trcc.core.models import parse_hex_color as _parse_hex

# =========================================================================
# LEDDispatcher — programmatic API (returns data, never prints)
# =========================================================================

class LEDDispatcher:
    """LED command dispatcher — single authority for all LED operations.

    Returns result dicts with 'success', 'message', 'error', and optional
    data ('colors', 'animated').  CLI wraps with print/exit.  GUI and API
    import and use directly.
    """

    # Canonical mode name → LEDMode mapping (import deferred to avoid top-level dep)
    _MODE_MAP: dict[str, Any] | None = None

    @classmethod
    def _modes(cls) -> dict[str, Any]:
        if cls._MODE_MAP is None:
            from trcc.core.models import LEDMode
            cls._MODE_MAP = {
                'static': LEDMode.STATIC,
                'breathing': LEDMode.BREATHING,
                'colorful': LEDMode.COLORFUL,
                'rainbow': LEDMode.RAINBOW,
            }
        return cls._MODE_MAP

    def __init__(self, svc: Any = None):
        self._svc = svc
        self._init_status: str | None = None

    # ── Properties ────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._svc is not None

    @property
    def status(self) -> str | None:
        return self._init_status

    @property
    def service(self) -> Any:
        return self._svc

    # ── Connection ────────────────────────────────────────────────────

    def connect(self) -> dict:
        """Auto-detect LED device and initialize.

        Returns: {"success": bool, "status": str, "error": str}
        """
        if self._svc:
            return {"success": True, "status": self._init_status or ""}

        from trcc.adapters.device.detector import detect_devices
        from trcc.services import LEDService

        devices = detect_devices()
        led_dev = next(
            (d for d in devices if d.implementation == 'hid_led'), None)
        if not led_dev:
            return {"success": False, "error": "No LED device found"}

        self._svc = LEDService()
        from trcc.adapters.device.led import probe_led_model
        info = probe_led_model(led_dev.vid, led_dev.pid,
                               usb_path=led_dev.usb_path)
        style_id = info.style.style_id if (info and info.style) else 1
        self._init_status = self._svc.initialize(led_dev, style_id)
        return {"success": True, "status": self._init_status or ""}

    # ── Internal helpers ──────────────────────────────────────────────

    def _apply_and_send(self) -> list:
        """Toggle global on, tick, send colors, save config. Returns colors."""
        self._svc.toggle_global(True)
        colors = self._svc.tick()
        self._svc.send_colors(colors)
        self._svc.save_config()
        return colors

    def _send_and_save(self) -> None:
        """Send tick and save config."""
        self._svc.send_tick()
        self._svc.save_config()

    def _validate_zone(self, zone: int) -> dict | None:
        """Return error dict if zone index is out of bounds, else None."""
        n = len(self._svc.state.zones)
        if n == 0:
            return {"success": False, "error": "This LED device has no zones"}
        if zone < 0 or zone >= n:
            return {"success": False, "error": f"Zone {zone} out of range (valid: 0–{n - 1})"}
        return None

    def _validate_segment(self, index: int) -> dict | None:
        """Return error dict if segment index is out of bounds, else None."""
        n = len(self._svc.state.segment_on)
        if n == 0:
            return {"success": False, "error": "This LED device has no segments"}
        if index < 0 or index >= n:
            return {"success": False, "error": f"Segment {index} out of range (valid: 0–{n - 1})"}
        return None

    # ── Global operations ─────────────────────────────────────────────

    def set_color(self, r: int, g: int, b: int) -> dict:
        """Set LED static color."""
        from trcc.core.models import LEDMode

        self._svc.set_mode(LEDMode.STATIC)
        self._svc.set_color(r, g, b)
        colors = self._apply_and_send()
        return {
            "success": True,
            "colors": colors,
            "message": f"LED color set to #{r:02x}{g:02x}{b:02x}",
        }

    def set_mode(self, mode_name: str) -> dict:
        """Set LED effect mode. Returns animated=True for breathing/colorful/rainbow."""
        from trcc.core.models import LEDMode

        modes = self._modes()
        mode = modes.get(mode_name.lower())
        if not mode:
            return {
                "success": False,
                "error": f"Unknown mode '{mode_name}'",
                "available": list(modes.keys()),
            }

        self._svc.set_mode(mode)
        colors = self._apply_and_send()

        animated = mode in (LEDMode.BREATHING, LEDMode.COLORFUL, LEDMode.RAINBOW)
        return {
            "success": True,
            "colors": colors,
            "animated": animated,
            "message": f"LED mode: {mode_name}",
        }

    def set_brightness(self, level: int) -> dict:
        """Set LED brightness (0-100)."""
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}

        self._svc.set_brightness(level)
        colors = self._apply_and_send()
        return {
            "success": True,
            "colors": colors,
            "message": f"LED brightness set to {level}%",
        }

    def off(self) -> dict:
        """Turn LEDs off."""
        self._svc.toggle_global(False)
        self._send_and_save()
        return {"success": True, "message": "LEDs turned off"}

    def set_sensor_source(self, source: str) -> dict:
        """Set CPU/GPU sensor source for temp/load linked modes."""
        source = source.lower()
        if source not in ('cpu', 'gpu'):
            return {"success": False, "error": "Source must be 'cpu' or 'gpu'"}

        self._svc.set_sensor_source(source)
        self._svc.save_config()
        return {"success": True, "message": f"LED sensor source set to {source.upper()}"}

    # ── Zone operations ───────────────────────────────────────────────

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> dict:
        """Set color for a specific LED zone."""
        if err := self._validate_zone(zone):
            return err
        self._svc.set_zone_color(zone, r, g, b)
        colors = self._apply_and_send()
        return {
            "success": True,
            "colors": colors,
            "message": f"Zone {zone} color set to #{r:02x}{g:02x}{b:02x}",
        }

    def set_zone_mode(self, zone: int, mode_name: str) -> dict:
        """Set effect mode for a specific LED zone."""
        if err := self._validate_zone(zone):
            return err
        mode = self._modes().get(mode_name.lower())
        if not mode:
            return {"success": False, "error": f"Unknown mode '{mode_name}'"}

        self._svc.set_zone_mode(zone, mode)
        colors = self._apply_and_send()
        return {
            "success": True,
            "colors": colors,
            "message": f"Zone {zone} mode set to {mode_name}",
        }

    def set_zone_brightness(self, zone: int, level: int) -> dict:
        """Set brightness for a specific LED zone (0-100)."""
        if err := self._validate_zone(zone):
            return err
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}

        self._svc.set_zone_brightness(zone, level)
        colors = self._apply_and_send()
        return {
            "success": True,
            "colors": colors,
            "message": f"Zone {zone} brightness set to {level}%",
        }

    def toggle_zone(self, zone: int, on: bool) -> dict:
        """Toggle a specific LED zone on/off."""
        if err := self._validate_zone(zone):
            return err
        self._svc.toggle_zone(zone, on)
        self._send_and_save()
        state = "ON" if on else "OFF"
        return {"success": True, "message": f"Zone {zone} turned {state}"}

    def set_zone_sync(self, enabled: bool, interval: int | None = None) -> dict:
        """Enable/disable zone sync (circulate/select-all)."""
        if interval is not None:
            self._svc.set_zone_sync_interval(interval)
        self._svc.set_zone_sync(enabled)
        self._send_and_save()
        state = "enabled" if enabled else "disabled"
        return {"success": True, "message": f"Zone sync {state}"}

    # ── Segment operations ────────────────────────────────────────────

    def toggle_segment(self, index: int, on: bool) -> dict:
        """Toggle a specific LED segment on/off."""
        if err := self._validate_segment(index):
            return err
        self._svc.toggle_segment(index, on)
        self._send_and_save()
        state = "ON" if on else "OFF"
        return {"success": True, "message": f"Segment {index} turned {state}"}

    def set_clock_format(self, is_24h: bool) -> dict:
        """Set LED segment display clock format (12h/24h)."""
        self._svc.set_clock_format(is_24h)
        self._send_and_save()
        fmt = "24h" if is_24h else "12h"
        return {"success": True, "message": f"Clock format set to {fmt}"}

    def set_temp_unit(self, unit: str) -> dict:
        """Set LED segment display temperature unit (C/F)."""
        unit = unit.upper()
        if unit not in ('C', 'F'):
            return {"success": False, "error": "Unit must be 'C' or 'F'"}

        self._svc.set_seg_temp_unit(unit)
        self._send_and_save()
        name = "Celsius" if unit == 'C' else "Fahrenheit"
        return {"success": True, "message": f"Temperature unit set to {name}"}

    # ── Animation tick ────────────────────────────────────────────────

    def tick(self) -> dict:
        """Advance one animation frame. Returns colors for preview."""
        colors = self._svc.tick()
        self._svc.send_colors(colors)
        return {"colors": colors}

    # ── State queries ─────────────────────────────────────────────────

    def get_state(self) -> dict:
        """Full LED state dict (mode, colors, zones, segments, brightness)."""
        st = self._svc.state
        return {
            "success": True,
            "mode": st.mode.name if hasattr(st.mode, 'name') else str(st.mode),
            "color": list(st.color),
            "brightness": st.brightness,
            "global_on": st.global_on,
            "zones": [
                {"color": list(z.color), "mode": z.mode.name if hasattr(z.mode, 'name') else str(z.mode),
                 "brightness": z.brightness, "on": z.on}
                for z in st.zones
            ],
            "segment_on": list(st.segment_on),
        }

    def update_metrics(self, metrics: Any) -> dict:
        """Push hardware metrics into LED service for segment display."""
        self._svc.update_metrics(metrics)
        return {"success": True}


# =========================================================================
# CLI presentation helpers
# =========================================================================

def _connect_or_fail() -> tuple[LEDDispatcher, int]:
    """Create dispatcher from _get_led_service. Returns (dispatcher, exit_code).

    When the GUI daemon is running, returns an IPC proxy that routes
    all commands through the daemon.
    Uses _get_led_service() so test mocks that patch it still work.
    """
    from trcc.ipc import IPCClient, IPCLEDProxy
    if IPCClient.available():
        return IPCLEDProxy(), 0  # type: ignore[return-value]
    svc, status = _get_led_service()
    if not svc:
        print("No LED device found.")
        return LEDDispatcher(), 1
    if status:
        print(status)
    return LEDDispatcher(svc=svc), 0


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
    """Generic: connect LED, call dispatcher method, print result."""
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
    led = LEDDispatcher()
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


@_cli_handler
def led_status():
    """Show LED device status (mode, color, brightness, zones, segments)."""
    led, rc = _connect_or_fail()
    if rc:
        return rc
    result = led.get_state()
    if not result["success"]:
        print(f"Error: {result.get('error', 'Unknown error')}")
        return 1
    print(f"  Mode:       {result['mode']}")
    r, g, b = result['color']
    print(f"  Color:      #{r:02x}{g:02x}{b:02x}")
    print(f"  Brightness: {result['brightness']}%")
    print(f"  Global:     {'ON' if result['global_on'] else 'OFF'}")
    zones = result.get('zones', [])
    if zones:
        print(f"  Zones ({len(zones)}):")
        for i, z in enumerate(zones):
            zr, zg, zb = z['color']
            print(f"    [{i}] {z['mode']:10s} #{zr:02x}{zg:02x}{zb:02x} "
                  f"B={z['brightness']}% {'ON' if z['on'] else 'OFF'}")
    segs = result.get('segment_on', [])
    if segs:
        on_count = sum(segs)
        print(f"  Segments: {on_count}/{len(segs)} on")
    return 0


# =========================================================================
# Developer test commands (no device needed)
# =========================================================================

def test_led(*, mode: str | None = None, segments: int = 64,
             duration: int = 0):
    """Test LED ANSI preview with real system metrics. No device needed.

    Cycles through LED modes rendering zone colors as ANSI blocks in terminal.
    Developers can verify LED rendering without hardware.
    """
    import time

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

    # Real metrics from this machine
    sys_svc = SystemService()
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
    """Test LCD ANSI preview with real system metrics. No device needed.

    Renders a metrics dashboard as ANSI half-block art in terminal.
    Developers can verify LCD rendering without hardware.
    """
    from trcc.services.image import ImageService
    from trcc.services.system import SystemService

    sys_svc = SystemService()
    sys_svc.discover()
    metrics = sys_svc.all_metrics

    print(f"LCD ANSI Preview ({cols} cols)")
    print("─" * 60)

    # Full dashboard
    print("\n  All metrics:")
    print(ImageService.metrics_to_ansi(metrics, cols=cols))

    # Per-group
    for group in ('cpu', 'gpu', 'mem', 'disk', 'net', 'fan', 'time'):
        print(f"\n  {group.upper()}:")
        print(ImageService.metrics_to_ansi(metrics, cols=cols, group=group))

    sys_svc.stop_polling()
    print("\nDone.")
    return 0
