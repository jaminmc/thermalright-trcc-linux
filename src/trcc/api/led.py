"""LED RGB control endpoints — color, mode, zones, segments."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException

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
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/led", tags=["led"])


def _get_led():
    """Get the active LEDDevice, raise 409 if not connected."""
    from trcc.api import _led_dispatcher

    if not _led_dispatcher or not _led_dispatcher.connected:
        raise HTTPException(status_code=409, detail="No LED device selected. POST /devices/{id}/select first.")
    return _led_dispatcher


def _led():
    """Get LED Device from TrccApp. Raises 409 if not connected."""
    from trcc.core.app import TrccApp
    _get_led()
    return TrccApp.get().led


# ── Global operations ──────────────────────────────────────────────────

@router.post("/color")
def set_color(body: HexColorRequest) -> dict:
    """Set LED static color."""
    r, g, b = parse_hex_or_400(body.hex)
    return dispatch_result(_led().set_color(r, g, b))


@router.post("/mode")
def set_mode(body: ModeRequest) -> dict:
    """Set LED effect mode (static, breathing, colorful, rainbow, temp_linked, load_linked)."""
    from trcc.api import ensure_metrics_loop
    from trcc.core.models import LEDMode

    try:
        mode = LEDMode[body.mode.upper()]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{body.mode}'. Choose: {', '.join(m.name.lower() for m in LEDMode)}",
        )
    result = dispatch_result(_led().set_mode(mode))
    if result.get("animated"):
        ensure_metrics_loop()
    return result


@router.post("/brightness")
def set_brightness(body: LEDBrightnessRequest) -> dict:
    """Set LED brightness (0-100)."""
    return dispatch_result(_led().set_brightness(body.level))


@router.post("/off")
def turn_off() -> dict:
    """Turn LEDs off."""
    return dispatch_result(_led().toggle_global(on=False))


@router.post("/sensor")
def set_sensor(body: LEDSensorRequest) -> dict:
    """Set CPU/GPU sensor source for temp/load linked modes."""
    return dispatch_result(_led().set_sensor_source(body.source))


# ── Zone operations ────────────────────────────────────────────────────

@router.post("/zones/{zone}/color")
def set_zone_color(zone: int, body: HexColorRequest) -> dict:
    """Set color for a specific LED zone."""
    r, g, b = parse_hex_or_400(body.hex)
    return dispatch_result(_led().set_zone_color(zone, r, g, b))


@router.post("/zones/{zone}/mode")
def set_zone_mode(zone: int, body: ModeRequest) -> dict:
    """Set effect mode for a specific LED zone."""
    from trcc.core.models import LEDMode

    try:
        mode = LEDMode[body.mode.upper()]
    except KeyError:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{body.mode}'. Choose: {', '.join(m.name.lower() for m in LEDMode)}",
        )
    return dispatch_result(_led().set_zone_mode(zone, mode))


@router.post("/zones/{zone}/brightness")
def set_zone_brightness(zone: int, body: LEDBrightnessRequest) -> dict:
    """Set brightness for a specific LED zone (0-100)."""
    return dispatch_result(_led().set_zone_brightness(zone, body.level))


@router.post("/zones/{zone}/toggle")
def toggle_zone(zone: int, body: ToggleRequest) -> dict:
    """Toggle a specific LED zone on/off."""
    return dispatch_result(_led().toggle_zone(zone, body.on))


@router.post("/sync")
def set_sync(body: ZoneSyncRequest) -> dict:
    """Enable/disable zone sync (circulate/select-all)."""
    return dispatch_result(_led().set_zone_sync(body.enabled, body.interval or 0))


# ── Segment operations ─────────────────────────────────────────────────

@router.post("/segments/{index}/toggle")
def toggle_segment(index: int, body: ToggleRequest) -> dict:
    """Toggle a specific LED segment on/off."""
    return dispatch_result(_led().toggle_segment(index, body.on))


@router.post("/clock")
def set_clock(body: ClockFormatRequest) -> dict:
    """Set LED segment display clock format (12h/24h)."""
    return dispatch_result(_led().set_clock_format(body.is_24h))


@router.post("/temp-unit")
def set_temp_unit(body: TempUnitRequest) -> dict:
    """Set LED segment display temperature unit (0=Celsius, 1=Fahrenheit)."""
    return dispatch_result(_led().set_temp_unit(body.unit))



# ── Test endpoint ─────────────────────────────────────────────────────


@router.post("/test")
def test_led(
    mode: str = "static",
    segments: int = 64,
) -> dict:
    """Run LED preview with real system metrics. No device needed."""
    from trcc.core.models import LEDMode, LEDState
    from trcc.services.led import LEDService

    modes = {
        'static': LEDMode.STATIC,
        'breathing': LEDMode.BREATHING,
        'colorful': LEDMode.COLORFUL,
        'rainbow': LEDMode.RAINBOW,
    }

    key = mode.lower()
    if key not in modes:
        raise HTTPException(
            status_code=400,
            detail=f"Unknown mode '{mode}'. Choose: {', '.join(modes)}",
        )

    import trcc.api as api

    state = LEDState()
    state.mode = modes[key]
    state.color = (255, 0, 0) if modes[key] == LEDMode.STATIC else (0, 255, 255)
    state.segment_count = segments
    state.global_on = True
    state.brightness = 100
    svc = LEDService(state=state)

    if api._system_svc:
        svc.update_metrics(api._system_svc.all_metrics)

    colors = svc.tick()

    return {
        "success": True,
        "mode": key,
        "segments": segments,
        "colors": [
            {"r": c[0], "g": c[1], "b": c[2]}
            for c in colors
        ],
    }


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
