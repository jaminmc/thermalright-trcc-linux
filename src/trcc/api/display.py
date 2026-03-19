"""LCD display control endpoints — brightness, rotation, color, mask, overlay, preview."""
from __future__ import annotations

import asyncio
import hmac
import io
import json
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException, Query, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from trcc.api.models import (
    BrightnessRequest,
    HexColorRequest,
    RotationRequest,
    SplitRequest,
    VideoStatusResponse,
    dispatch_result,
    parse_hex_or_400,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/display", tags=["display"])


def _get_display():
    """Get the active LCDDevice, raise 409 if not connected."""
    from trcc.api import _display_dispatcher

    if not _display_dispatcher or not _display_dispatcher.connected:
        raise HTTPException(status_code=409, detail="No LCD device selected. POST /devices/{id}/select first.")
    return _display_dispatcher


def _display_frame_route(method: str, *args, **kwargs) -> dict:
    """Route to lcd.frame capability, stop video/overlay first."""
    from trcc.api import stop_overlay_loop, stop_video_playback

    stop_video_playback()
    stop_overlay_loop()
    result = getattr(_get_display().frame, method)(*args, **kwargs)
    return dispatch_result(result)


def _display_settings_route(method: str, *args, **kwargs) -> dict:
    """Route to lcd.settings capability."""
    result = getattr(_get_display().settings, method)(*args, **kwargs)
    return dispatch_result(result)


@router.post("/color")
def set_color(body: HexColorRequest) -> dict:
    """Send solid color to LCD."""
    r, g, b = parse_hex_or_400(body.hex)
    return _display_frame_route("send_color", r, g, b)


@router.post("/brightness")
def set_brightness(body: BrightnessRequest) -> dict:
    """Set display brightness (1=25%, 2=50%, 3=100%). Persists to config."""
    return _display_settings_route("set_brightness", body.level)


@router.post("/rotation")
def set_rotation(body: RotationRequest) -> dict:
    """Set display rotation (0, 90, 180, 270). Persists to config."""
    return _display_settings_route("set_rotation", body.degrees)


@router.post("/split")
def set_split(body: SplitRequest) -> dict:
    """Set split mode (0=off, 1-3=Dynamic Island). Persists to config."""
    return _display_settings_route("set_split_mode", body.mode)


@router.post("/reset")
def reset_display() -> dict:
    """Reset device by sending solid red frame."""
    return _display_frame_route("reset")


@router.post("/mask")
async def load_mask(image: UploadFile) -> dict:
    """Upload and apply mask overlay (PNG)."""
    import tempfile
    from pathlib import Path

    lcd = _get_display()

    data = await image.read()
    if len(data) > 10 * 1024 * 1024:
        raise HTTPException(status_code=413, detail="Mask image exceeds 10 MB limit")

    # Write to temp file for dispatcher (expects path)
    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        result = lcd.load_mask_standalone(tmp_path)
        return dispatch_result(result)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/overlay")
async def render_overlay(dc_path: str, send: bool = True) -> dict:
    """Render overlay from DC config path and optionally send to device."""
    import os

    from trcc.conf import settings

    # Validate path is within the data directory — prevent traversal

    if '\0' in dc_path:
        raise HTTPException(status_code=400, detail="Invalid overlay path")
    allowed_dir = os.path.realpath(str(settings.user_data_dir))
    # Resolve to canonical path — handles both absolute and relative input
    safe_path = os.path.realpath(os.path.join(allowed_dir, dc_path))
    if not safe_path.startswith(allowed_dir + os.sep) and safe_path != allowed_dir:
        raise HTTPException(status_code=400, detail="Invalid overlay path")

    import trcc.api as api

    lcd = _get_display()
    result = lcd.render_overlay_from_dc(
        safe_path, send=send, metrics=api._system_svc.all_metrics)
    return dispatch_result(result)


@router.get("/status")
def display_status() -> dict:
    """Get current display state — resolution, device path, connection."""
    from trcc.api import _display_dispatcher

    if not _display_dispatcher or not _display_dispatcher.connected:
        return {"connected": False, "resolution": [0, 0], "device_path": None}

    lcd = _display_dispatcher
    return {
        "connected": True,
        "resolution": lcd.resolution,
        "device_path": lcd.device_path,
    }


# ── Video playback endpoints ──────────────────────────────────────────


@router.post("/video/stop")
def video_stop() -> dict:
    """Stop background video playback."""
    from trcc.api import stop_video_playback

    stop_video_playback()
    return {"success": True, "message": "Video playback stopped"}


@router.post("/video/pause")
def video_pause() -> dict:
    """Toggle pause on background video playback."""
    from trcc.api import _media_service, pause_video_playback

    if not _media_service:
        raise HTTPException(status_code=409, detail="No video playing")
    pause_video_playback()
    return {"success": True, "paused": not _media_service.is_playing}


@router.get("/video/status")
def video_status() -> VideoStatusResponse:
    """Get current video playback state."""
    from trcc.api import _media_service
    from trcc.core.models import PlaybackState

    if not _media_service:
        return VideoStatusResponse()

    state = _media_service.state
    return VideoStatusResponse(
        playing=state.state == PlaybackState.PLAYING,
        paused=state.state == PlaybackState.PAUSED,
        progress=state.progress,
        current_time=state.current_time_str,
        total_time=state.total_time_str,
        fps=state.fps,
        source=str(_media_service.source_path or ""),
        loop=state.loop,
    )


# ── Test endpoint ─────────────────────────────────────────────────────


@router.post("/test")
def test_display() -> dict:
    """Send a color cycle test to the LCD device.

    Cycles through 7 colors (red, green, blue, yellow, magenta, cyan, white),
    sending each as a solid frame with a 1-second pause between them.
    """
    import time

    import trcc.api as api

    lcd = _get_display()
    api.stop_video_playback()
    api.stop_overlay_loop()

    w, h = lcd.resolution  # type: ignore[union-attr]

    colors = [
        (255, 0, 0, "Red"),
        (0, 255, 0, "Green"),
        (0, 0, 255, "Blue"),
        (255, 255, 0, "Yellow"),
        (255, 0, 255, "Magenta"),
        (0, 255, 255, "Cyan"),
        (255, 255, 255, "White"),
    ]

    from trcc.services import ImageService

    for r, g, b, _name in colors:
        img = ImageService.solid_color(r, g, b, w, h)
        lcd.frame.send_color(r, g, b)
        time.sleep(1)

    # Update preview with last frame
    api.set_current_image(img)  # type: ignore[possibly-undefined]

    return {"success": True, "message": f"Test complete — cycled {len(colors)} colors on {w}x{h}"}


# ── Create-theme endpoint ─────────────────────────────────────────────

_VIDEO_SUFFIXES = frozenset({'.mp4', '.zt', '.webm', '.avi', '.mkv'})


def _is_animated(path: Path) -> bool:
    """Return True if path is a video or an animated GIF (n_frames > 1)."""
    suffix = path.suffix.lower()
    if suffix in _VIDEO_SUFFIXES:
        return True
    if suffix == '.gif':
        try:
            from PIL import Image
            with Image.open(path) as img:
                return getattr(img, 'n_frames', 1) > 1
        except Exception:
            return False
    return False


@router.post("/create-theme")
def create_theme(
    background: str,
    mask: str | None = None,
    metric: list[str] = Query(default=[]),
    loop: bool = True,
    font_size: int = 14,
    color: str = "ffffff",
    font: str = "Microsoft YaHei",
    font_style: str = "regular",
    temp_unit: int = 0,
    time_format: int = 0,
    date_format: int = 0,
) -> dict:
    """Send a custom theme to the LCD device.

    Auto-detects animated backgrounds (video, animated GIF) and loops them
    by default. Add ``&loop=false`` to play once.

    ``metric`` is repeatable: ``&metric=cpu_temp:10,20&metric=time:150,10:ffffff:24``

    Metric spec format: ``key:x,y[:color[:size[:font[:style]]]]``
    """
    import trcc.api as api
    from trcc.core.models import build_overlay_config
    from trcc.services import ImageService

    lcd = _get_display()
    api.stop_video_playback()
    api.stop_overlay_loop()

    bg_path = Path(background)
    if '\0' in background or not bg_path.exists():
        raise HTTPException(status_code=400, detail=f"Background file not found: {background}")

    if mask is not None and ('\0' in mask or not Path(mask).exists()):
        raise HTTPException(status_code=400, detail=f"Mask file not found: {mask}")

    w, h = lcd.resolution  # type: ignore[union-attr]
    animated = _is_animated(bg_path)

    overlay_config = None
    if metric:
        try:
            overlay_config = build_overlay_config(
                metric,
                default_color=color,
                default_font_size=font_size,
                default_font=font,
                default_style=font_style,
                temp_unit=temp_unit,
                time_format=time_format,
                date_format=date_format,
            )
        except ValueError as e:
            raise HTTPException(status_code=400, detail=str(e))

    if animated:
        ok = api.start_video_playback(str(bg_path), w, h, loop=loop)
        if not ok:
            raise HTTPException(status_code=500, detail="Failed to start video playback")
        return {"success": True, "animated": True, "loop": loop, "resolution": f"{w}x{h}"}

    # Static image
    from trcc.cli import _ensure_renderer
    _ensure_renderer()
    img = ImageService.open_and_resize(bg_path, w, h)
    if img is None:
        raise HTTPException(status_code=400, detail="Failed to open background image")

    if mask:
        result = lcd.load_mask_standalone(mask)
        if not result.get("success"):
            raise HTTPException(status_code=400, detail=result.get("error", "Mask load failed"))
        img = result.get("image", img)

    if overlay_config:
        from trcc.adapters.infra.dc_config import DcConfig
        from trcc.adapters.infra.dc_parser import load_config_json
        from trcc.cli import _ensure_system
        from trcc.services.overlay import OverlayService
        _ensure_system()
        overlay = OverlayService(
            w, h, renderer=api._renderer,
            load_config_json_fn=load_config_json,
            dc_config_cls=DcConfig,
        )
        overlay.set_background(img)
        overlay.set_config(overlay_config)
        overlay.enabled = True
        api._overlay_svc = overlay
        # render one frame immediately and send
        from trcc.services.system import get_all_metrics
        frame = overlay.render(get_all_metrics())
        lcd.frame.send_pil(frame)
        api.set_current_image(frame)
    else:
        lcd.frame.send_pil(img)
        api.set_current_image(img)

    return {"success": True, "animated": False, "resolution": f"{w}x{h}"}


# ── Preview helpers ───────────────────────────────────────────────────


def _fetch_ipc_frame():
    """Fetch current LCD frame from GUI daemon via IPC (blocking call).

    Returns JPEG bytes (already encoded by IPC server).
    """
    import base64

    from trcc.ipc import IPCClient

    try:
        result = IPCClient.send("display.get_frame")
        if result.get("success") and result.get("frame"):
            return base64.b64decode(result["frame"])
    except Exception:
        pass
    return None


def _encode_frame(frame: object, fmt: str = 'JPEG', quality: int = 85) -> bytes | None:
    """Encode a frame (QImage or PIL) to image bytes."""
    from PySide6.QtGui import QImage

    if isinstance(frame, bytes):
        return frame  # Already encoded (IPC path)
    if isinstance(frame, QImage):
        from PySide6.QtCore import QBuffer, QByteArray, QIODevice
        buf = QByteArray()
        qbuf = QBuffer(buf)
        qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
        frame.save(qbuf, fmt.encode(), quality)
        qbuf.close()
        return bytes(buf.data())
    # PIL Image fallback
    bio = io.BytesIO()
    frame.save(bio, format=fmt, quality=quality)  # type: ignore[union-attr]
    return bio.getvalue()


def _get_lcd_frame():
    """Get current LCD frame — from IPC daemon if active, otherwise local state.

    Returns the raw frame object (QImage, PIL Image, or pre-encoded bytes).
    """
    from trcc.api import _current_image, _display_dispatcher
    from trcc.ipc import IPCDisplayProxy

    if isinstance(_display_dispatcher, IPCDisplayProxy):
        return _fetch_ipc_frame()
    return _current_image


# ── Preview endpoints ─────────────────────────────────────────────────


@router.get("/preview")
def display_preview() -> Response:
    """Return the current LCD frame as a PNG image."""
    frame = _get_lcd_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="No image available")

    try:
        data = _encode_frame(frame, fmt='PNG')
    except Exception:
        log.debug("Preview encode failed", exc_info=True)
        raise HTTPException(status_code=503, detail="Frame encode failed")
    if data is None:
        raise HTTPException(status_code=503, detail="Frame encode failed")
    return Response(content=data, media_type="image/png")


@router.websocket("/preview/stream")
async def preview_stream(websocket: WebSocket):
    """Live JPEG stream of the current LCD frame — like a screen capture.

    Reads the LCD frame at a steady framerate and sends it as binary JPEG.
    When the GUI daemon is running, frames are fetched via IPC.
    When standalone, frames come from the on_frame_sent capture.

    Auth: ``?token=`` query param (checked against configured API token).
    Client control: send JSON ``{"fps": N}``, ``{"quality": N}``, ``{"pause": bool}``.
    """
    from trcc.api import _api_token, _display_dispatcher
    from trcc.ipc import IPCDisplayProxy

    # ── Auth ──────────────────────────────────────────────────────────
    if _api_token:
        query_token = websocket.query_params.get("token", "")
        if not hmac.compare_digest(query_token, _api_token):
            await websocket.close(code=4001, reason="Unauthorized")
            return

    await websocket.accept()

    use_ipc = isinstance(_display_dispatcher, IPCDisplayProxy)
    fps = 10
    quality = 85
    paused = False

    try:
        while True:
            # ── Check for client control messages (non-blocking) ──────
            try:
                raw = await asyncio.wait_for(
                    websocket.receive_text(), timeout=1.0 / fps,
                )
                try:
                    msg = json.loads(raw)
                    if "fps" in msg:
                        fps = max(1, min(30, int(msg["fps"])))
                    if "quality" in msg:
                        quality = max(10, min(100, int(msg["quality"])))
                    if "pause" in msg:
                        paused = bool(msg["pause"])
                except (json.JSONDecodeError, ValueError, TypeError):
                    pass
                continue  # restart loop after processing message
            except asyncio.TimeoutError:
                pass  # no message — proceed to frame read

            if paused:
                continue

            # ── Read current frame directly from source ───────────────
            if use_ipc:
                frame = await asyncio.get_running_loop().run_in_executor(
                    None, _fetch_ipc_frame,
                )
            else:
                from trcc.api import _current_image  # noqa: F811

                frame = _current_image

            if frame is None:
                continue

            # ── Encode and send ───────────────────────────────────────
            data = _encode_frame(frame, fmt='JPEG', quality=quality)
            if data:
                await websocket.send_bytes(data)

    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("Preview stream closed", exc_info=True)
