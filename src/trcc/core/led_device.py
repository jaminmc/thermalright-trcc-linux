"""LEDDevice — concrete Device for LED segment displays.

Extends Device ABC. Uses existing models (LEDMode, LEDState, LEDZoneState)
and delegates to LEDService. Models define the device — LEDDevice just
wires operations to the service.

CLI, GUI, and API all consume this directly (DIP — core/, not adapter/).
"""
from __future__ import annotations

import functools
import logging
from typing import Any

from .models import LEDMode
from .ports import Device

log = logging.getLogger(__name__)


def _forward_to_proxy(method):
    """Forward method call to proxy if one is active."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if self._proxy is not None:
            log.debug("proxy forward: %s → %s", method.__name__, type(self._proxy).__name__)
            return getattr(self._proxy, method.__name__)(*args, **kwargs)
        return method(self, *args, **kwargs)
    return wrapper


class LEDDevice(Device):
    """LED device — extends Device ABC, delegates to LEDService.

    Models ARE the device: LEDMode, LEDState, LEDZoneState define all state.
    LEDService owns the logic. This class is the entry point.

    Construction (via builder — the only correct way):
        led = ControllerBuilder.for_current_os().build_led()
        led.connect()                        # CLI: auto-detect + probe
        led.set_color(255, 0, 0)             # set static red
    """

    def __init__(self, svc: Any = None,
                 get_protocol: Any = None,
                 device_svc: Any = None,
                 led_svc_factory: Any = None,
                 led_config: Any = None,
                 find_active_fn: Any = None,
                 proxy_factory_fn: Any = None) -> None:
        self._svc = svc
        self._get_protocol = get_protocol
        self._device_svc = device_svc
        self._led_svc_factory = led_svc_factory
        self._led_config = led_config
        self._find_active_fn = find_active_fn
        self._proxy_factory_fn = proxy_factory_fn
        self._proxy: Any = None
        self._init_status: str | None = None
        self._device: Any = None  # DetectedDevice from detection

    # ── Device ABC ─────────────────────────────────────────────────

    @property
    def is_lcd(self) -> bool:
        return False

    @property
    def is_led(self) -> bool:
        return True

    def connect(self, detected: Any = None) -> dict:
        """Connect to LED device — same flow as LCD.

        When *detected* is provided (scan() path), uses it directly.
        When None (CLI auto-detect), falls back to DeviceService.
        Handshake inside initialize() resolves PM → style identity.

        Returns: {"success": bool, "status": str}
        """
        if self._svc:
            log.debug("LED connect: already connected (status=%s)", self._init_status)
            return {"success": True, "status": self._init_status or ""}

        proxy_result = self._try_proxy_route(detected)
        if proxy_result is not None:
            log.info("LED connect: routing through proxy instance")
            proxy_result["status"] = f"Connected (via {proxy_result['proxy'].value})"
            return proxy_result

        # Use detected directly (same as LCD) — handshake sets identity
        if detected is not None and getattr(detected, 'implementation', '') == 'hid_led':
            from .models import DeviceInfo
            self._device = DeviceInfo.from_detected(detected)
            log.info("LED connect: using detected %s", self._device.path)
        else:
            # CLI auto-detect: no specific device given
            if self._device_svc is None:
                raise RuntimeError(
                    "LEDDevice requires a DeviceService. "
                    "Use ControllerBuilder.build_led() to wire dependencies.")
            self._device_svc.detect()
            self._device = next(
                (d for d in self._device_svc.devices
                 if d.implementation == 'hid_led'), None)
            if not self._device:
                log.warning("LED connect: no LED device found")
                return {"success": False, "error": "No LED device found"}

        self._svc = self._led_svc_factory(
            get_protocol=self._get_protocol,
            led_config=self._led_config,
        )
        self._init_status = self._svc.initialize(self._device)
        return {"success": True, "status": self._init_status or ""}

    @property
    def connected(self) -> bool:
        if self._proxy is not None:
            return getattr(self._proxy, 'connected', True)
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
            self._svc = self._led_svc_factory(
                get_protocol=self._get_protocol,
                led_config=self._led_config,
            )
        self._device = device
        self._init_status = self._svc.initialize(device, led_style)
        return {"success": True, "status": self._init_status or "",
                "style": led_style}

    # ── Internal helpers ───────────────────────────────────────────

    def _resolve_mode(self, mode: LEDMode | str | int) -> LEDMode | None:
        """Resolve mode from LEDMode enum, string name, or int value."""
        match mode:
            case LEDMode():
                return mode
            case int() if mode in LEDMode._value2member_map_:
                return LEDMode(mode)
            case str() if mode.upper() in LEDMode._member_map_:
                return LEDMode[mode.upper()]
            case _:
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

    # ── State-only mutators (GUI path — timer handles send) ───────
    # C# pattern: FormLED event handlers set rgbR1/myLedMode/etc.,
    # MyTimer_Event picks them up next tick → SendHidVal.

    def update_color(self, r: int, g: int, b: int) -> None:
        """Set color without tick/send (GUI — timer handles it)."""
        self._svc.set_color(r, g, b)

    def update_mode(self, mode: LEDMode | int) -> None:
        """Set mode without tick/send (GUI — timer handles it)."""
        resolved = LEDMode(mode) if isinstance(mode, int) else mode
        self._svc.set_mode(resolved)

    def update_brightness(self, level: int) -> None:
        """Set brightness without tick/send (GUI — timer handles it)."""
        self._svc.set_brightness(max(0, min(100, level)))

    def update_global_on(self, on: bool) -> None:
        """Set global on/off without tick/send (GUI — timer handles it)."""
        self._svc.toggle_global(on)

    def update_segment(self, index: int, on: bool) -> None:
        """Toggle segment without tick/send (GUI — timer handles it)."""
        self._svc.toggle_segment(index, on)

    def update_zone_color(self, zone: int, r: int, g: int, b: int) -> None:
        """Set zone color without tick/send (GUI — timer handles it)."""
        self._svc.set_zone_color(zone, r, g, b)

    def update_zone_mode(self, zone: int, mode: LEDMode | int) -> None:
        """Set zone mode without tick/send (GUI — timer handles it)."""
        resolved = LEDMode(mode) if isinstance(mode, int) else mode
        self._svc.set_zone_mode(zone, resolved)

    def update_zone_brightness(self, zone: int, level: int) -> None:
        """Set zone brightness without tick/send (GUI — timer handles it)."""
        self._svc.set_zone_brightness(zone, max(0, min(100, level)))

    def update_zone_on(self, zone: int, on: bool) -> None:
        """Toggle zone without tick/send (GUI — timer handles it)."""
        self._svc.toggle_zone(zone, on)

    def update_zone_sync(self, enabled: bool) -> None:
        """Set zone sync without tick/send (GUI — timer handles it)."""
        self._svc.set_zone_sync(enabled)

    def update_zone_sync_zone(self, zone: int, selected: bool) -> None:
        """Set zone sync zone without tick/send (GUI — timer handles it)."""
        self._svc.set_zone_sync_zone(zone, selected)

    def update_zone_sync_interval(self, seconds: int) -> None:
        """Set zone sync interval without tick/send (GUI — timer handles it)."""
        self._svc.set_zone_sync_interval(seconds)

    def update_clock_format(self, is_24h: bool) -> None:
        """Set clock format without tick/send (GUI — timer handles it)."""
        self._svc.set_clock_format(is_24h)

    def update_week_start(self, is_sunday: bool) -> None:
        """Set week start without tick/send (GUI — timer handles it)."""
        self._svc.set_week_start(is_sunday)

    def update_disk_index(self, index: int) -> None:
        """Set disk index without tick/send (GUI — timer handles it)."""
        self._svc.set_disk_index(index)

    def update_memory_ratio(self, ratio: int) -> None:
        """Set memory ratio without tick/send (GUI — timer handles it)."""
        self._svc.set_memory_ratio(ratio)

    def update_test_mode(self, enabled: bool) -> None:
        """Set test mode without tick/send (GUI — timer handles it)."""
        self._svc.set_test_mode(enabled)

    def update_selected_zone(self, zone: int) -> None:
        """Set selected zone without tick/send (GUI — timer handles it)."""
        self._svc.set_selected_zone(zone)

    # ── Global operations (CLI/API — immediate tick/send/save) ────
    # @_forward_to_proxy: when another trcc instance owns the device,
    # these calls route through the proxy transparently.

    @_forward_to_proxy
    def set_color(self, r: int, g: int, b: int) -> dict:
        self._svc.set_mode(LEDMode.STATIC)
        self._svc.set_color(r, g, b)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"LED color set to #{r:02x}{g:02x}{b:02x}"}

    @_forward_to_proxy
    def set_mode(self, mode: LEDMode | str | int) -> dict:
        resolved = self._resolve_mode(mode)
        if not resolved:
            return {"success": False, "error": f"Unknown mode '{mode}'",
                    "available": [m.name.lower() for m in LEDMode]}
        self._svc.set_mode(resolved)
        colors = self._apply_and_send()
        animated = resolved in (LEDMode.BREATHING, LEDMode.COLORFUL,
                                LEDMode.RAINBOW, LEDMode.TEMP_LINKED,
                                LEDMode.LOAD_LINKED)
        return {"success": True, "colors": colors, "animated": animated,
                "message": f"LED mode: {resolved.name.lower()}"}

    @_forward_to_proxy
    def set_brightness(self, level: int) -> dict:
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}
        self._svc.set_brightness(level)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"LED brightness set to {level}%"}

    @_forward_to_proxy
    def toggle_global(self, on: bool) -> dict:
        self._svc.toggle_global(on)
        self._send_and_save()
        return {"success": True, "message": f"LEDs {'on' if on else 'off'}"}

    @_forward_to_proxy
    def off(self) -> dict:
        self._svc.toggle_global(False)
        self._send_and_save()
        return {"success": True, "message": "LEDs turned off"}

    @_forward_to_proxy
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

    @_forward_to_proxy
    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> dict:
        if err := self._validate_zone(zone):
            return err
        self._svc.set_zone_color(zone, r, g, b)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} color set to #{r:02x}{g:02x}{b:02x}"}

    @_forward_to_proxy
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

    @_forward_to_proxy
    def set_zone_brightness(self, zone: int, level: int) -> dict:
        if err := self._validate_zone(zone):
            return err
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}
        self._svc.set_zone_brightness(zone, level)
        colors = self._apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} brightness set to {level}%"}

    @_forward_to_proxy
    def toggle_zone(self, zone: int, on: bool) -> dict:
        if err := self._validate_zone(zone):
            return err
        self._svc.toggle_zone(zone, on)
        self._send_and_save()
        return {"success": True,
                "message": f"Zone {zone} {'ON' if on else 'OFF'}"}

    @_forward_to_proxy
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

    @_forward_to_proxy
    def toggle_segment(self, index: int, on: bool) -> dict:
        if err := self._validate_segment(index):
            return err
        self._svc.toggle_segment(index, on)
        self._send_and_save()
        return {"success": True,
                "message": f"Segment {index} {'ON' if on else 'OFF'}"}

    @_forward_to_proxy
    def set_clock_format(self, is_24h: bool) -> dict:
        self._svc.set_clock_format(is_24h)
        self._send_and_save()
        return {"success": True,
                "message": f"Clock format set to {'24h' if is_24h else '12h'}"}

    @_forward_to_proxy
    def set_week_start(self, is_sunday: bool) -> dict:
        self._svc.set_week_start(is_sunday)
        self._send_and_save()
        return {"success": True}

    @_forward_to_proxy
    def set_temp_unit(self, unit: int) -> dict:
        """Set temperature unit (0=Celsius, 1=Fahrenheit)."""
        unit_str = 'F' if unit else 'C'
        self._svc.set_seg_temp_unit(unit_str)
        self._send_and_save()
        return {"success": True,
                "message": f"Temperature unit set to {unit_str}"}

    # Alias — GUI calls this name directly
    def set_seg_temp_unit(self, unit: int) -> dict:
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

    def tick(self) -> None:
        """Advance one LED animation frame and send to hardware."""
        if not self._svc:
            log.debug("tick: no service — skipping")
            return
        colors = self._svc.tick()
        if self._svc.has_protocol:
            ok = self._svc.send_colors(colors)
            if not ok:
                log.debug("tick: send_colors skipped (concurrent)")

    def tick_with_result(self) -> dict:
        """Advance one animation frame. Returns colors + display_colors (GUI use)."""
        if not self._svc:
            log.debug("tick_with_result: no service — skipping")
            return {"colors": [], "display_colors": []}
        colors = self._svc.tick()
        display_colors = self._svc.apply_mask(colors)
        if self._svc.has_protocol:
            ok = self._svc.send_colors(colors)
            if not ok:
                log.debug("tick_with_result: send_colors skipped (concurrent)")
        return {"colors": colors, "display_colors": display_colors}
