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

        from trcc.core.models import PROTOCOL_TRAITS
        traits = PROTOCOL_TRAITS.get(dev.protocol or 'scsi')
        if (traits and traits.is_led) or getattr(dev, 'implementation', '') == 'hid_led':
            from trcc.core.app import TrccApp
            api._led_dispatcher = TrccApp.get().build_led()
            result = api._led_dispatcher.connect()
            if not result["success"]:
                api._led_dispatcher = None
        else:
            _device_svc._discover_resolution(dev)

            from trcc.core.app import TrccApp
            lcd = TrccApp.get().lcd_from_service(_device_svc)
            api._display_dispatcher = lcd

            w_res, h_res = dev.resolution or (320, 320)

            # Download/extract theme data for this resolution (no-op if cached)
            from trcc.adapters.infra.data_repository import DataManager
            DataManager.ensure_all(w_res, h_res)

            api.set_current_image(ImageService.solid_color(0, 0, 0, w_res, h_res))

            lcd.restore_device_settings()
            result = lcd.load_last_theme()
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
    """
    from trcc.api import _device_svc

    dev = _get_device_by_id(device_id)
    _device_svc.select(dev)

    # Read and validate upload
    data = await image.read()
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status_code=413, detail="Image exceeds 10 MB limit")

    from PySide6.QtGui import QImage
    img = QImage.fromData(bytes(data))
    if img.isNull():
        raise HTTPException(status_code=400, detail="Invalid image format")

    # Apply rotation and brightness
    if rotation:
        img = ImageService.apply_rotation(img, rotation)
    if brightness != 100:
        img = ImageService.apply_brightness(img, brightness)

    # Discover resolution via handshake if not yet known
    w, h = dev.resolution
    if (w, h) == (0, 0):
        from trcc.adapters.device.factory import DeviceProtocolFactory
        protocol = DeviceProtocolFactory.get_protocol(dev)
        result = protocol.handshake()
        if result:
            res = getattr(result, 'resolution', None)
            if isinstance(res, tuple) and len(res) == 2 and res != (0, 0):
                dev.resolution = res
                w, h = res
            # Propagate FBL code for JPEG mode detection
            fbl = getattr(result, 'fbl', None) or getattr(result, 'model_id', None)
            if fbl:
                dev.fbl_code = fbl
        if (w, h) == (0, 0):
            raise HTTPException(status_code=503, detail="Cannot discover device resolution")
    img = ImageService.resize(img, w, h)

    # Encode and send via service (handles JPEG vs RGB565, rotation, byte order)
    # Frame capture is automatic via on_frame_sent callback
    ok = _device_svc.send_pil(img, w, h)

    if not ok:
        raise HTTPException(status_code=500, detail="Send failed (device busy or error)")

    return {"sent": True, "resolution": (w, h)}
