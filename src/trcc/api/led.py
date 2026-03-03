"""LED RGB control endpoints — color, mode, zones, segments."""
from __future__ import annotations

import logging

from fastapi import APIRouter

from trcc.api.models import (
    ClockFormatRequest,
    HexColorRequest,
    LEDBrightnessRequest,
    LEDSensorRequest,
    ModeRequest,
    TempUnitRequest,
    ToggleRequest,
    ZoneSyncRequest,
    dispatch_result,
    parse_hex_or_400,
    require_connected,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/led", tags=["led"])


def _get_led():
    """Get the active LEDDispatcher, raise 409 if not connected."""
    from trcc.api import _led_dispatcher

    return require_connected(_led_dispatcher, "LED")


def _led_route(method: str, *args, **kwargs) -> dict:
    """Generic: get LED dispatcher, call method, return dispatch result."""
    return dispatch_result(getattr(_get_led(), method)(*args, **kwargs))


# ── Global operations ──────────────────────────────────────────────────

@router.post("/color")
def set_color(body: HexColorRequest) -> dict:
    """Set LED static color."""
    r, g, b = parse_hex_or_400(body.hex)
    return _led_route("set_color", r, g, b)


@router.post("/mode")
def set_mode(body: ModeRequest) -> dict:
    """Set LED effect mode (static, breathing, colorful, rainbow)."""
    return _led_route("set_mode", body.mode)


@router.post("/brightness")
def set_brightness(body: LEDBrightnessRequest) -> dict:
    """Set LED brightness (0-100)."""
    return _led_route("set_brightness", body.level)


@router.post("/off")
def turn_off() -> dict:
    """Turn LEDs off."""
    return _led_route("off")


@router.post("/sensor")
def set_sensor(body: LEDSensorRequest) -> dict:
    """Set CPU/GPU sensor source for temp/load linked modes."""
    return _led_route("set_sensor_source", body.source)


# ── Zone operations ────────────────────────────────────────────────────

@router.post("/zones/{zone}/color")
def set_zone_color(zone: int, body: HexColorRequest) -> dict:
    """Set color for a specific LED zone."""
    r, g, b = parse_hex_or_400(body.hex)
    return _led_route("set_zone_color", zone, r, g, b)


@router.post("/zones/{zone}/mode")
def set_zone_mode(zone: int, body: ModeRequest) -> dict:
    """Set effect mode for a specific LED zone."""
    return _led_route("set_zone_mode", zone, body.mode)


@router.post("/zones/{zone}/brightness")
def set_zone_brightness(zone: int, body: LEDBrightnessRequest) -> dict:
    """Set brightness for a specific LED zone (0-100)."""
    return _led_route("set_zone_brightness", zone, body.level)


@router.post("/zones/{zone}/toggle")
def toggle_zone(zone: int, body: ToggleRequest) -> dict:
    """Toggle a specific LED zone on/off."""
    return _led_route("toggle_zone", zone, body.on)


@router.post("/sync")
def set_sync(body: ZoneSyncRequest) -> dict:
    """Enable/disable zone sync (circulate/select-all)."""
    return _led_route("set_zone_sync", body.enabled, body.interval)


# ── Segment operations ─────────────────────────────────────────────────

@router.post("/segments/{index}/toggle")
def toggle_segment(index: int, body: ToggleRequest) -> dict:
    """Toggle a specific LED segment on/off."""
    return _led_route("toggle_segment", index, body.on)


@router.post("/clock")
def set_clock(body: ClockFormatRequest) -> dict:
    """Set LED segment display clock format (12h/24h)."""
    return _led_route("set_clock_format", body.is_24h)


@router.post("/temp-unit")
def set_temp_unit(body: TempUnitRequest) -> dict:
    """Set LED segment display temperature unit (C/F)."""
    return _led_route("set_temp_unit", body.unit)


# ── Status ─────────────────────────────────────────────────────────────

@router.get("/status")
def led_status() -> dict:
    """Get current LED state — connected, init status."""
    from trcc.api import _led_dispatcher

    if not _led_dispatcher or not _led_dispatcher.connected:
        return {"connected": False, "status": None}

    led = _led_dispatcher
    return {
        "connected": True,
        "status": led.status,
    }
