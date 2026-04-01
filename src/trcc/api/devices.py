"""Device detection, selection, and image send endpoints."""
from __future__ import annotations

import logging

from fastapi import APIRouter, HTTPException, UploadFile

from trcc.api.models import DeviceResponse
from trcc.services import ImageService

log = logging.getLogger(__name__)

router = APIRouter()

MAX_UPLOAD_BYTES = 10 * 1024 * 1024  # 10 MB


# ── Helpers ────────────────────────────────────────────────────────────

def _device_to_response(idx: int, dev) -> DeviceResponse:
    return DeviceResponse(
        id=idx,
        name=dev.name,
        vid=dev.vid,
        pid=dev.pid,
        protocol=dev.protocol or "scsi",
        resolution=dev.resolution or (0, 0),
        path=dev.path or "",
    )


def _get_device_by_id(device_id: int):
    """Look up device by index, raise 404 if not found."""
    from trcc.api import _device_svc

    devices = _device_svc.devices
    if device_id < 0 or device_id >= len(devices):
        raise HTTPException(status_code=404, detail=f"Device {device_id} not found")
    return devices[device_id]


# ── Endpoints ──────────────────────────────────────────────────────────

@router.get("/devices")
def list_devices() -> list[DeviceResponse]:
    """List currently known devices."""
    from trcc.api import _device_svc

    return [_device_to_response(i, d) for i, d in enumerate(_device_svc.devices)]


@router.post("/devices/detect")
def detect_devices() -> list[DeviceResponse]:
    """Rescan USB for LCD devices."""
    from trcc.api import _device_svc

    _device_svc.detect()
    return [_device_to_response(i, d) for i, d in enumerate(_device_svc.devices)]


@router.post("/devices/{device_id}/select")
def select_device(device_id: int) -> dict:
    """Select a device by index. Initializes the appropriate dispatcher."""
    import trcc.api as api
    from trcc.api import _device_svc

    dev = _get_device_by_id(device_id)

    # Skip teardown if re-selecting the same device that's already active
    already_active = (
        _device_svc.selected is not None
        and _device_svc.selected is dev
        and (api._display_dispatcher or api._led_dispatcher)
    )
    if already_active:
        return {"selected": dev.name, "resolution": dev.resolution}

    _device_svc.select(dev)

    # Stop any running background threads from previous device
    api.stop_video_playback()
    api.stop_overlay_loop()

    # Check if another instance (GUI) already owns the device
    from trcc.core.instance import find_active
    from trcc.ipc import create_lcd_proxy, create_led_proxy

    active = find_active()

    if active is not None:
        api._display_dispatcher = create_lcd_proxy(active)
        api._led_dispatcher = create_led_proxy(active)

        # Active instance already discovered resolution — sync to DeviceInfo
        proxy_res = api._display_dispatcher.resolution
        if proxy_res != (0, 0):
            dev.resolution = proxy_res

        log.info("Using %s instance for device %s", active.value, dev.name)
    else:
        # Standalone mode — API manages device directly
        _device_svc.on_frame_sent = api.set_current_image

        from trcc.core.app import TrccApp
        app = TrccApp.get()
        app.discover(path=getattr(dev, 'path', None))

        if app.has_led:
            api._led_dispatcher = app.led_device
        else:
            _device_svc._discover_resolution(dev)
            # Fallback: wire LCD from existing device service if discover didn't find one
            if not app.has_lcd:
                api._display_dispatcher = app.lcd_from_service(_device_svc)
            else:
                api._display_dispatcher = app.lcd_device

            lcd = api._display_dispatcher
            if lcd is None:
                return {"selected": dev.name, "resolution": dev.resolution}
            w_res, h_res = dev.resolution or (0, 0)

            # Download/extract theme data for this resolution in background
            if w_res and h_res and app.has_lcd and app.lcd_device is not None:
                app._ensure_data_background(app.lcd_device, w_res, h_res)

            api.set_current_image(ImageService.solid_color(0, 0, 0, w_res, h_res))

            lcd.restore_device_settings()
            result = lcd.restore_last_theme()
            if result.get("image"):
                api.set_current_image(result["image"])
                log.info("Restored last theme for preview")

    # Mount static file directories for this device's resolution
    w, h = dev.resolution or (0, 0)
    if w and h:
        api.mount_static_dirs(w, h)

    return {"selected": dev.name, "resolution": dev.resolution}



@router.get("/devices/{device_id}")
def get_device(device_id: int) -> DeviceResponse:
    """Get details for a specific device."""
    dev = _get_device_by_id(device_id)
    return _device_to_response(device_id, dev)


@router.post("/devices/{device_id}/send")
async def send_image(device_id: int, image: UploadFile, rotation: int = 0,
                     brightness: int = 100) -> dict:
    """Send an image to the device LCD.

    Accepts image file upload. Validates size and format before processing.
    Routes through LCDDevice for consistent encoding and send behavior.
    """
    import tempfile
    from pathlib import Path

    from trcc.core.app import TrccApp

    _get_device_by_id(device_id)  # validate device exists

    app = TrccApp.get()
    if not app.has_lcd:
        raise HTTPException(status_code=409, detail="No LCD device connected")
    lcd = app.lcd

    # Read and validate upload
    data = await image.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 10 MB limit")

    # Save upload to temp file, load via LCDDevice
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        f.write(data)
        tmp_path = Path(f.name)

    try:
        result = lcd.load_image(tmp_path)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Invalid image"))

        if rotation:
            lcd.set_rotation(rotation)
        if brightness != 100:
            lcd.set_brightness(brightness)

        send_result = lcd.send(result["image"])
        if not send_result.get("success"):
            raise HTTPException(status_code=500, detail="Send failed (device busy or error)")
    finally:
        tmp_path.unlink(missing_ok=True)

    w, h = lcd.lcd_size
    return {"sent": True, "resolution": (w, h)}
