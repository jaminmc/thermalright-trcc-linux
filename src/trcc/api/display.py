"""LCD display control endpoints — brightness, rotation, color, mask, overlay, preview."""
from __future__ import annotations

import asyncio
import hmac
import io
import json
import logging

from fastapi import APIRouter, HTTPException, UploadFile, WebSocket, WebSocketDisconnect
from fastapi.responses import Response

from trcc.api.models import (
    BrightnessRequest,
    HexColorRequest,
    RotationRequest,
    SplitRequest,
    VideoStatusResponse,
    dispatch_result,
    parse_hex_or_400,
    require_connected,
)

log = logging.getLogger(__name__)

router = APIRouter(prefix="/display", tags=["display"])


def _get_display():
    """Get the active DisplayDispatcher, raise 409 if not connected."""
    from trcc.api import _display_dispatcher

    return require_connected(_display_dispatcher, "LCD")


def _display_route(method: str, *args, **kwargs) -> dict:
    """Generic: get display dispatcher, call method, return result.

    Frame capture is automatic via DeviceService.on_frame_sent callback.
    """
    from trcc.api import stop_overlay_loop, stop_video_playback

    # Static display operations replace any running video/overlay
    stop_video_playback()
    stop_overlay_loop()
    result = getattr(_get_display(), method)(*args, **kwargs)
    return dispatch_result(result)


@router.post("/color")
def set_color(body: HexColorRequest) -> dict:
    """Send solid color to LCD."""
    r, g, b = parse_hex_or_400(body.hex)
    return _display_route("send_color", r, g, b)


@router.post("/brightness")
def set_brightness(body: BrightnessRequest) -> dict:
    """Set display brightness (1=25%, 2=50%, 3=100%). Persists to config."""
    return _display_route("set_brightness", body.level)


@router.post("/rotation")
def set_rotation(body: RotationRequest) -> dict:
    """Set display rotation (0, 90, 180, 270). Persists to config."""
    return _display_route("set_rotation", body.degrees)


@router.post("/split")
def set_split(body: SplitRequest) -> dict:
    """Set split mode (0=off, 1-3=Dynamic Island). Persists to config."""
    return _display_route("set_split_mode", body.mode)


@router.post("/reset")
def reset_display() -> dict:
    """Reset device by sending solid red frame."""
    return _display_route("reset")


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
        result = lcd.load_mask(tmp_path)
        return dispatch_result(result)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


@router.post("/overlay")
async def render_overlay(dc_path: str, send: bool = True) -> dict:
    """Render overlay from DC config path and optionally send to device."""
    lcd = _get_display()
    result = lcd.render_overlay(dc_path, send=send)
    return dispatch_result(result)


@router.get("/status")
def display_status() -> dict:
    """Get current display state — resolution, device, overlay, video."""
    from trcc.api import _display_dispatcher

    if not _display_dispatcher or not _display_dispatcher.connected:
        return {"connected": False, "resolution": [0, 0], "device_path": None}
    return _display_dispatcher.status()


# ── Video playback endpoints ──────────────────────────────────────────


@router.post("/video/play")
def video_play() -> dict:
    """Start/resume video playback."""
    return dispatch_result(_get_display().play_video())


@router.post("/video/stop")
def video_stop() -> dict:
    """Stop background video playback."""
    from trcc.api import stop_video_playback

    stop_video_playback()
    return dispatch_result(_get_display().stop_video())


@router.post("/video/pause")
def video_pause() -> dict:
    """Pause video playback."""
    return dispatch_result(_get_display().pause_video())


@router.get("/video/status")
def video_status() -> VideoStatusResponse:
    """Get current video playback state."""
    from trcc.api import _display_dispatcher

    if not _display_dispatcher or not _display_dispatcher.display_service:
        return VideoStatusResponse()

    media = _display_dispatcher.display_service.media
    from trcc.core.models import PlaybackState

    state = media.state
    return VideoStatusResponse(
        playing=state.state == PlaybackState.PLAYING,
        paused=state.state == PlaybackState.PAUSED,
        progress=state.progress,
        current_time=state.current_time_str,
        total_time=state.total_time_str,
        fps=state.fps,
        source=str(media.source_path or ""),
        loop=state.loop,
    )


# ── Preview helpers ───────────────────────────────────────────────────


def _fetch_ipc_frame():
    """Fetch current LCD frame from GUI daemon via IPC (blocking call)."""
    import base64

    from PIL import Image

    from trcc.ipc import IPCClient

    try:
        result = IPCClient.send("display.get_frame")
        if result.get("success") and result.get("frame"):
            return Image.open(io.BytesIO(base64.b64decode(result["frame"])))
    except Exception:
        pass
    return None


def _get_lcd_frame():
    """Get current LCD frame — from IPC daemon if active, otherwise local state."""
    from trcc.api import _current_image, _display_dispatcher
    from trcc.ipc import IPCDisplayProxy

    if isinstance(_display_dispatcher, IPCDisplayProxy):
        return _fetch_ipc_frame()
    return _current_image


# ── Preview endpoints ─────────────────────────────────────────────────


@router.get("/preview")
def display_preview() -> Response:
    """Return the current LCD frame as a PNG image."""
    import numpy as np

    frame = _get_lcd_frame()
    if frame is None:
        raise HTTPException(status_code=503, detail="No image available")

    if isinstance(frame, np.ndarray):
        from PIL import Image as PILImage
        arr = frame[:, :, :3] if frame.ndim == 3 and frame.shape[2] == 4 else frame
        frame = PILImage.fromarray(arr)

    buf = io.BytesIO()
    frame.save(buf, format="PNG")
    return Response(content=buf.getvalue(), media_type="image/png")


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
            import numpy as np

            if isinstance(frame, np.ndarray):
                from PIL import Image as PILImage
                arr = frame[:, :, :3] if frame.ndim == 3 and frame.shape[2] == 4 else frame
                frame = PILImage.fromarray(arr)

            buf = io.BytesIO()
            frame.save(buf, format="JPEG", quality=quality)
            await websocket.send_bytes(buf.getvalue())

    except WebSocketDisconnect:
        pass
    except Exception:
        log.debug("Preview stream closed", exc_info=True)
