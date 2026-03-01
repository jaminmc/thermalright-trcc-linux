"""Device detection, selection, and image send endpoints."""
from __future__ import annotations

import io
import logging

from fastapi import APIRouter, HTTPException, UploadFile
from PIL import Image

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
    _device_svc.select(dev)

    # Initialize dispatcher based on device type
    from trcc.core.models import PROTOCOL_TRAITS
    traits = PROTOCOL_TRAITS.get(dev.protocol or 'scsi')
    if (traits and traits.is_led) or getattr(dev, 'implementation', '') == 'hid_led':
        from trcc.cli._led import LEDDispatcher

        api._led_dispatcher = LEDDispatcher()
        result = api._led_dispatcher.connect()
        if not result["success"]:
            api._led_dispatcher = None
    else:
        # Discover resolution via handshake if not yet known (all LCD protocols)
        from trcc.cli._device import discover_resolution
        discover_resolution(dev)

        from trcc.cli._display import DisplayDispatcher

        api._display_dispatcher = DisplayDispatcher(device_svc=_device_svc)

        # Restore last theme as _current_image for preview endpoints
        _restore_last_theme(dev)

    # Mount static file directories for this device's resolution
    w, h = dev.resolution or (0, 0)
    if w and h:
        api.mount_static_dirs(w, h)

    return {"selected": dev.name, "resolution": dev.resolution}


def _restore_last_theme(dev) -> None:
    """Load saved theme image into _current_image (for preview/stream).

    Mirrors CLI --last-one: reads theme_path from device config, opens
    00.png, applies brightness + rotation. Does NOT re-send to device.
    """
    import os

    from trcc.api import set_current_image
    from trcc.conf import Settings

    key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
    cfg = Settings.get_device_config(key)
    theme_path = cfg.get("theme_path")
    if not theme_path:
        return

    image_path = None
    if os.path.isdir(theme_path):
        candidate = os.path.join(theme_path, "00.png")
        if os.path.exists(candidate):
            image_path = candidate
    elif os.path.isfile(theme_path):
        image_path = theme_path

    if not image_path:
        return

    try:
        w, h = dev.resolution
        img = Image.open(image_path).convert("RGB")
        img = ImageService.resize(img, w, h)

        brightness_pct = {1: 25, 2: 50, 3: 100}.get(cfg.get("brightness_level", 3), 100)
        img = ImageService.apply_brightness(img, brightness_pct)
        img = ImageService.apply_rotation(img, cfg.get("rotation", 0))

        set_current_image(img)
        log.info("Restored last theme for preview: %s", os.path.basename(theme_path))
    except Exception as e:
        log.debug("Could not restore last theme: %s", e)


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

    try:
        img = Image.open(io.BytesIO(data))
        img.load()  # Force decode to catch corrupt files
    except Exception:
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
    ok = _device_svc.send_pil(img, w, h)

    if not ok:
        raise HTTPException(status_code=500, detail="Send failed (device busy or error)")

    from trcc.api import set_current_image
    set_current_image(img)

    return {"sent": True, "resolution": (w, h)}
