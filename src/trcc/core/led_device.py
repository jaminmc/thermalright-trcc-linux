"""LEDDevice — concrete Device for LED segment displays.

Extends Device ABC. Uses existing models (LEDMode, LEDState, LEDZoneState)
and delegates to LEDService. Models define the device — LEDDevice just
wires operations to the service.

CLI, GUI, and API all consume this directly (DIP — core/, not adapter/).
"""
from __future__ import annotations

from typing import Any

from .models import LEDMode
from .ports import Device


class LEDDevice(Device):
    """LED device — extends Device ABC, delegates to LEDService.

    Models ARE the device: LEDMode, LEDState, LEDZoneState define all state.
    LEDService owns the logic. This class is the entry point.

    Construction:
        led = LEDDevice()
        led.connect()                        # CLI: auto-detect + probe
        led.set_color(255, 0, 0)             # set static red

        led = LEDDevice()
        led.initialize(device_info, style)   # GUI: device already detected
    """

    def __init__(self, svc: Any = None) -> None:
        self._svc = svc
        self._init_status: str | None = None
        self._device: Any = None  # DetectedDevice from detection

    # ── Device ABC ─────────────────────────────────────────────────

    def connect(self, detected: Any = None) -> dict:
        """Detect LED device, probe model, initialize LEDService.

        Returns: {"success": bool, "status": str}
        """
        if self._svc:
            return {"success": True, "status": self._init_status or ""}

        from ..services import DeviceService, LEDService

        svc = DeviceService()
        svc.detect()
        led_dev = next(
            (d for d in svc.devices if d.implementation == 'hid_led'), None)
        if not led_dev:
            return {"success": False, "error": "No LED device found"}

        self._device = led_dev
        self._svc = LEDService()
        style_id = led_dev.led_style_id or 1
        self._init_status = self._svc.initialize(led_dev, style_id)
        return {"success": True, "status": self._init_status or ""}

    @property
    def connected(self) -> bool:
        return self._svc is not None

    @property
    def device_info(self) -> Any:
        return self._device

    def cleanup(self) -> None:
        if self._svc:
            self._svc.cleanup()

    # ── LED-specific properties ────────────────────────────────────

    @property
    def status(self) -> str | None:
        return self._init_status

    @property
    def service(self) -> Any:
        """Direct LEDService access."""
        return self._svc

    @property
    def state(self) -> Any:
        """Current LEDState (models.LEDState — the device IS the model)."""
        return self._svc.state if self._svc else None

    # ── Lifecycle (GUI path — device already detected) ─────────────

    def initialize(self, device: Any, led_style: int) -> dict:
        """Initialize for a known device (GUI — device already detected).

        Unlike connect() which auto-detects, this takes a DeviceInfo
        and style_id directly from the sidebar.
        """
        if not self._svc:
            from ..services import LEDService
            self._svc = LEDService()
        self._device = device
        self._init_status = self._svc.initialize(device, led_style)
        return {"success": True, "status": self._init_status or "",
                "style": led_style}

    # ── Internal helpers ───────────────────────────────────────────

    def _resolve_mode(self, mode: LEDMode | str | int) -> LEDMode | None:
        """Resolve mode from LEDMode enum, string name, or int value."""
        if isinstance(mode, LEDMode):
            return mode
        if isinstance(mode, int):
            try:
                return LEDMode(mode)
            except ValueError:
                return None
        if isinstance(mode, str):
            try:
                return LEDMode[mode.upper()]
            except KeyError:
                return None
        return None

    def _apply_and_send(self) -> list:
        """Toggle global on, tick, send colors, save config."""
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
        n = len(self._svc.state.zones)
        if n == 0:
            return {"success": False, "error": "This LED device has no zones"}
        if zone < 0 or zone >= n:
            return {"success": False,
                    "error": f"Zone {zone} out of range (valid: 0–{n - 1})"}
        return None

    def _validate_segment(self, index: int) -> dict | None:
        n = len(self._svc.state.segment_on)
        if n == 0:
            return {"success": False,
                    "error": "This LED device has no segments"}
        if index < 0 or index >= n:
            return {"success": False,
                    "error": f"Segment {index} out of range (valid: 0–{n - 1})"}
        return None

    # ── Global operations ──────────────────────────────────────────

    def set_color(self, r: int, g: int, b: int) -> dict:
        self._svc.set_mode(LEDMode.STATIC)
        self._svc.set_color(r, g, b)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"LED color set to #{r:02x}{g:02x}{b:02x}"}

    def set_mode(self, mode: LEDMode | str | int) -> dict:
        resolved = self._resolve_mode(mode)
        if not resolved:
            return {"success": False, "error": f"Unknown mode '{mode}'",
                    "available": [m.name.lower() for m in LEDMode]}
        self._svc.set_mode(resolved)
        colors = self._apply_and_send()
        animated = resolved in (LEDMode.BREATHING, LEDMode.COLORFUL,
                                LEDMode.RAINBOW)
        return {"success": True, "colors": colors, "animated": animated,
                "message": f"LED mode: {resolved.name.lower()}"}

    def set_brightness(self, level: int) -> dict:
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}
        self._svc.set_brightness(level)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"LED brightness set to {level}%"}

    def toggle_global(self, on: bool) -> dict:
        self._svc.toggle_global(on)
        self._send_and_save()
        return {"success": True, "message": f"LEDs {'on' if on else 'off'}"}

    def off(self) -> dict:
        self._svc.toggle_global(False)
        self._send_and_save()
        return {"success": True, "message": "LEDs turned off"}

    def set_sensor_source(self, source: str) -> dict:
        source = source.lower()
        if source not in ('cpu', 'gpu'):
            return {"success": False,
                    "error": "Source must be 'cpu' or 'gpu'"}
        self._svc.set_sensor_source(source)
        self._svc.save_config()
        return {"success": True,
                "message": f"LED sensor source set to {source.upper()}"}

    # ── Zone operations ────────────────────────────────────────────

    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> dict:
        if err := self._validate_zone(zone):
            return err
        self._svc.set_zone_color(zone, r, g, b)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} color set to #{r:02x}{g:02x}{b:02x}"}

    def set_zone_mode(self, zone: int, mode: LEDMode | str | int) -> dict:
        if err := self._validate_zone(zone):
            return err
        resolved = self._resolve_mode(mode)
        if not resolved:
            return {"success": False, "error": f"Unknown mode '{mode}'"}
        self._svc.set_zone_mode(zone, resolved)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} mode set to {resolved.name.lower()}"}

    def set_zone_brightness(self, zone: int, level: int) -> dict:
        if err := self._validate_zone(zone):
            return err
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}
        self._svc.set_zone_brightness(zone, level)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} brightness set to {level}%"}

    def toggle_zone(self, zone: int, on: bool) -> dict:
        if err := self._validate_zone(zone):
            return err
        self._svc.toggle_zone(zone, on)
        self._send_and_save()
        return {"success": True,
                "message": f"Zone {zone} {'ON' if on else 'OFF'}"}

    def set_zone_sync(self, enabled: bool,
                      interval: int | None = None) -> dict:
        if interval is not None:
            self._svc.set_zone_sync_interval(interval)
        self._svc.set_zone_sync(enabled)
        self._send_and_save()
        return {"success": True,
                "message": f"Zone sync {'enabled' if enabled else 'disabled'}"}

    def set_zone_sync_zone(self, zone: int, selected: bool) -> dict:
        self._svc.set_zone_sync_zone(zone, selected)
        return {"success": True}

    def set_zone_sync_interval(self, seconds: int) -> dict:
        self._svc.set_zone_sync_interval(seconds)
        return {"success": True}

    def set_selected_zone(self, zone: int) -> dict:
        self._svc.set_selected_zone(zone)
        return {"success": True}

    # ── Segment operations ─────────────────────────────────────────

    def toggle_segment(self, index: int, on: bool) -> dict:
        if err := self._validate_segment(index):
            return err
        self._svc.toggle_segment(index, on)
        self._send_and_save()
        return {"success": True,
                "message": f"Segment {index} {'ON' if on else 'OFF'}"}

    def set_clock_format(self, is_24h: bool) -> dict:
        self._svc.set_clock_format(is_24h)
        self._send_and_save()
        return {"success": True,
                "message": f"Clock format set to {'24h' if is_24h else '12h'}"}

    def set_week_start(self, is_sunday: bool) -> dict:
        self._svc.set_week_start(is_sunday)
        self._send_and_save()
        return {"success": True}

    def set_temp_unit(self, unit: str) -> dict:
        unit = unit.upper()
        if unit not in ('C', 'F'):
            return {"success": False, "error": "Unit must be 'C' or 'F'"}
        self._svc.set_seg_temp_unit(unit)
        self._send_and_save()
        return {"success": True,
                "message": f"Temperature unit set to {unit}"}

    # Alias — GUI calls this name directly
    def set_seg_temp_unit(self, unit: str) -> dict:
        return self.set_temp_unit(unit)

    def set_disk_index(self, index: int) -> dict:
        self._svc.set_disk_index(index)
        return {"success": True}

    def set_memory_ratio(self, ratio: int) -> dict:
        self._svc.set_memory_ratio(ratio)
        return {"success": True}

    def set_test_mode(self, enabled: bool) -> dict:
        self._svc.set_test_mode(enabled)
        return {"success": True}

    # ── Metrics + Config ───────────────────────────────────────────

    def update_metrics(self, metrics: Any) -> dict:
        self._svc.update_metrics(metrics)
        return {"success": True}

    def save_config(self) -> None:
        if self._svc:
            self._svc.save_config()

    def load_config(self) -> None:
        if self._svc:
            self._svc.load_config()

    # ── Animation tick ─────────────────────────────────────────────

    def tick(self) -> dict:
        """Advance one animation frame. Returns colors + display_colors."""
        colors = self._svc.tick()
        display_colors = self._svc.apply_mask(colors)
        if self._svc.has_protocol:
            self._svc.send_colors(colors)
        return {"colors": colors, "display_colors": display_colors}
