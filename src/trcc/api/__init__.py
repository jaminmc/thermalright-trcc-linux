"""FastAPI REST API — Driving adapter for headless/remote control.

Package structure mirrors cli/ — one module per domain:
    __init__.py — app, auth middleware, health, shared state
    models.py   — Pydantic request/response models
    devices.py  — device detection, selection, image send
    display.py  — LCD display settings (brightness, rotation, color, etc.)
    i18n.py     — language listing and selection
    led.py      — LED RGB control (color, mode, zones, segments)
    themes.py   — theme listing, load, save, import
    system.py   — system metrics, diagnostic report

Security:
    - Localhost-only by default (bind 127.0.0.1)
    - Optional token auth via --token flag (X-API-Token header)
    - Optional TLS via --tls flag (auto-generates self-signed cert)
    - 10 MB upload limit with image format validation
"""
from __future__ import annotations

import hmac
import logging
import os
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from trcc.__version__ import __version__
from trcc.adapters.device.detector import DeviceDetector
from trcc.adapters.device.factory import DeviceProtocolFactory
from trcc.adapters.device.led import probe_led_model
from trcc.adapters.infra.dc_config import DcConfig
from trcc.adapters.infra.dc_parser import load_config_json
from trcc.services import DeviceService, MediaService, OverlayService
from trcc.services.system import SystemService

log = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(title="TRCC Linux", version=__version__)

# ── Shared state ───────────────────────────────────────────────────────

_device_svc = DeviceService(
    detect_fn=DeviceDetector.detect,
    probe_led_fn=probe_led_model,
    get_protocol=DeviceProtocolFactory.get_protocol,
    get_protocol_info=DeviceProtocolFactory.get_protocol_info,
)

# System service — None until configure_app() is called by trcc serve
_system_svc: SystemService | None = None

# Lazy-initialized devices (set when device is selected)
_display_dispatcher = None  # LCDDevice | None
_led_dispatcher = None      # LEDDevice | None

# Last frame sent to LCD — updated by display/theme endpoints for preview
_current_image = None  # QImage | None


def set_current_image(img) -> None:
    """Update the tracked LCD frame (called by display/theme endpoints)."""
    global _current_image  # noqa: PLW0603
    _current_image = img


def configure_app() -> None:
    """Initialize platform, renderer, and system service.

    Called once by CLI serve command before uvicorn starts. Not called at
    import time so tests can import the module without triggering side effects.
    """
    global _system_svc  # noqa: PLW0603
    from trcc.adapters.render.qt import QtRenderer
    from trcc.core.app import AppEvent, AppObserver, TrccApp
    from trcc.services.system import set_instance

    trcc_app = TrccApp.init()

    class _ApiProgressObserver(AppObserver):
        def on_app_event(self, event: AppEvent, data: object) -> None:
            if event == AppEvent.BOOTSTRAP_PROGRESS:
                print(data, flush=True)

    trcc_app.register(_ApiProgressObserver())
    trcc_app.bootstrap(renderer_factory=QtRenderer)
    _system_svc = trcc_app.build_system()
    set_instance(_system_svc)


# ── Video playback (background thread) ───────────────────────────────

_media_service: MediaService | None = None
_video_thread: threading.Thread | None = None
_video_stop_event: threading.Event | None = None


def start_video_playback(
    video_path: str, width: int, height: int, *, loop: bool = True,
) -> bool:
    """Start background video playback — pumps frames to LCD and _current_image.

    Uses MediaService to decode frames, DeviceService to send to LCD,
    and set_current_image() to feed the WebSocket preview stream.
    """
    global _media_service, _video_thread, _video_stop_event  # noqa: PLW0603

    stop_video_playback()  # Stop any existing playback

    from trcc.adapters.infra.media_player import ThemeZtDecoder, VideoDecoder
    media = MediaService(
        video_decoder_cls=VideoDecoder,
        zt_decoder_cls=ThemeZtDecoder,
    )
    media.set_target_size(width, height)
    if not media.load(Path(video_path)):
        return False

    media._state.loop = loop
    media.play()

    _media_service = media
    _video_stop_event = threading.Event()
    stop_event = _video_stop_event  # Local ref for closure

    def _pump() -> None:
        interval = media.frame_interval_ms / 1000.0
        while not stop_event.is_set() and media.is_playing:
            frame, should_send, _ = media.tick()
            if frame is None:
                break
            if should_send:
                _device_svc.send_frame(frame, width, height)
            stop_event.wait(interval)

    _video_thread = threading.Thread(target=_pump, daemon=True, name="api-video")
    _video_thread.start()
    log.info("Video playback started: %s (%dx%d)", video_path, width, height)
    return True


def stop_video_playback() -> None:
    """Stop background video playback if running."""
    global _media_service, _video_thread, _video_stop_event  # noqa: PLW0603

    if _video_stop_event:
        _video_stop_event.set()
    if _video_thread and _video_thread.is_alive():
        _video_thread.join(timeout=2)
    if _media_service:
        _media_service.stop()
    _media_service = None
    _video_thread = None
    _video_stop_event = None


def pause_video_playback() -> None:
    """Toggle pause on background video playback."""
    if _media_service:
        _media_service.toggle()


# ── Overlay metrics loop (background thread for static themes) ────────

_overlay_svc: OverlayService | None = None
_overlay_thread: threading.Thread | None = None
_overlay_stop_event: threading.Event | None = None


def start_overlay_loop(
    background, dc_path: str, width: int, height: int,
) -> bool:
    """Start background overlay rendering — polls metrics, re-renders, sends to LCD.

    For static themes with config1.dc overlay configs. Updates _current_image
    so the WebSocket preview stream shows live metrics.
    """
    global _overlay_svc, _overlay_thread, _overlay_stop_event  # noqa: PLW0603

    stop_overlay_loop()

    from trcc.services.image import ImageService
    overlay = OverlayService(
        width, height, renderer=ImageService._r(),
        load_config_json_fn=load_config_json,
        dc_config_cls=DcConfig,
    )
    overlay.set_background(background)
    overlay.load_from_dc(Path(dc_path))
    overlay.enabled = True

    _overlay_svc = overlay
    _overlay_stop_event = threading.Event()
    stop_event = _overlay_stop_event

    def _loop() -> None:
        while not stop_event.is_set():
            if _system_svc is None:
                stop_event.wait(2.0)
                continue
            metrics = _system_svc.all_metrics
            if overlay.would_change(metrics):
                overlay.update_metrics(metrics)
                frame = overlay.render(metrics=metrics)
                if frame is not None:
                    _device_svc.send_frame(frame, width, height)
            stop_event.wait(2.0)

    _overlay_thread = threading.Thread(target=_loop, daemon=True, name="api-overlay")
    _overlay_thread.start()
    log.info("Overlay loop started: %s (%dx%d)", dc_path, width, height)
    return True


def stop_overlay_loop() -> None:
    """Stop background overlay rendering if running."""
    global _overlay_svc, _overlay_thread, _overlay_stop_event  # noqa: PLW0603

    if _overlay_stop_event:
        _overlay_stop_event.set()
    if _overlay_thread and _overlay_thread.is_alive():
        _overlay_thread.join(timeout=2)
    _overlay_svc = None
    _overlay_thread = None
    _overlay_stop_event = None


# ── Static frame keepalive loop (bulk/LY devices don't retain frames) ──

_keepalive_thread: threading.Thread | None = None
_keepalive_stop_event: threading.Event | None = None


def start_keepalive_loop(image, width: int, height: int) -> bool:
    """Re-send a static frame every 150 ms to keep bulk/LY displays alive."""
    global _keepalive_thread, _keepalive_stop_event  # noqa: PLW0603

    stop_keepalive_loop()

    _keepalive_stop_event = threading.Event()
    stop_event = _keepalive_stop_event

    def _loop() -> None:
        while not stop_event.is_set():
            _device_svc.send_frame(image, width, height)
            stop_event.wait(0.150)

    _keepalive_thread = threading.Thread(target=_loop, daemon=True, name="api-keepalive")
    _keepalive_thread.start()
    log.info("Keepalive loop started (%dx%d)", width, height)
    return True


def stop_keepalive_loop() -> None:
    """Stop background frame keepalive if running."""
    global _keepalive_thread, _keepalive_stop_event  # noqa: PLW0603

    if _keepalive_stop_event:
        _keepalive_stop_event.set()
    if _keepalive_thread and _keepalive_thread.is_alive():
        _keepalive_thread.join(timeout=2)
    _keepalive_thread = None
    _keepalive_stop_event = None


# ── LED keepalive loop (background thread for animated modes) ─────────

_led_thread: threading.Thread | None = None
_led_stop_event: threading.Event | None = None


def start_led_loop() -> None:
    """Start background LED tick loop for animated/live-data modes.

    Ticks the LED device at 50ms intervals. Refreshes sensor metrics
    every second for temp_linked/load_linked modes.
    """
    global _led_thread, _led_stop_event  # noqa: PLW0603

    stop_led_loop()
    if _led_dispatcher is None or not _led_dispatcher.connected:
        return

    _led_stop_event = threading.Event()
    stop_event = _led_stop_event
    led = _led_dispatcher

    def _loop() -> None:
        tick_count = 0
        while not stop_event.is_set():
            if tick_count % 20 == 0 and _system_svc is not None:
                try:
                    led.update_metrics(_system_svc.all_metrics)
                except Exception:
                    pass
            tick_count += 1
            try:
                led.tick()
            except Exception:
                break
            stop_event.wait(0.05)

    _led_thread = threading.Thread(target=_loop, daemon=True, name="api-led")
    _led_thread.start()
    log.info("LED keepalive loop started")


def stop_led_loop() -> None:
    """Stop background LED tick loop if running."""
    global _led_thread, _led_stop_event  # noqa: PLW0603

    if _led_stop_event:
        _led_stop_event.set()
    if _led_thread and _led_thread.is_alive():
        _led_thread.join(timeout=1)
    _led_thread = None
    _led_stop_event = None


# ── Static file mounts (resolution-aware, remounted on device select) ─

_mounted_routes: list[str] = []  # Track mounted paths for remount


def mount_static_dirs(width: int, height: int) -> None:
    """Mount theme/web/mask directories as static files for the given resolution.

    Called after device select when resolution is known. Remounts if resolution
    changes (e.g., user switches device).
    """
    from trcc.adapters.infra.data_repository import DataManager, ThemeDir

    # Remove previous mounts
    for path in _mounted_routes:
        app.routes[:] = [r for r in app.routes if getattr(r, 'path', '') != path]
    _mounted_routes.clear()

    # Theme directory (local themes)
    theme_dir = str(ThemeDir.for_resolution(width, height).path)
    if os.path.isdir(theme_dir):
        app.mount("/static/themes", StaticFiles(directory=theme_dir), name="themes")
        _mounted_routes.append("/static/themes")

    # Cloud theme previews
    web_dir = DataManager.get_web_dir(width, height)
    if os.path.isdir(web_dir):
        app.mount("/static/web", StaticFiles(directory=web_dir), name="web")
        _mounted_routes.append("/static/web")

    # Cloud masks
    masks_dir = DataManager.get_web_masks_dir(width, height)
    if os.path.isdir(masks_dir):
        app.mount("/static/masks", StaticFiles(directory=masks_dir), name="masks")
        _mounted_routes.append("/static/masks")

    log.info("Mounted static dirs for %dx%d: themes=%s web=%s masks=%s",
             width, height, theme_dir, web_dir, masks_dir)


# ── Token auth + pairing ──────────────────────────────────────────────

_api_token: str | None = None
_pairing_code: str | None = None  # Ephemeral 6-char code, shown in terminal


def configure_auth(token: str | None) -> None:
    """Set the API token. Called by CLI serve command."""
    global _api_token  # noqa: PLW0603
    _api_token = token


def set_pairing_code(code: str) -> None:
    """Set the ephemeral pairing code (displayed in terminal)."""
    global _pairing_code  # noqa: PLW0603
    _pairing_code = code


# Paths exempt from token auth — pairing needs to work before the phone has a token
_AUTH_EXEMPT = {"/health", "/pair"}


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log every HTTP request with method, path, status, and latency."""
    import time
    start = time.monotonic()
    response = await call_next(request)
    ms = (time.monotonic() - start) * 1000
    log.info("API %s %s → %d (%.0fms)",
             request.method, request.url.path, response.status_code, ms)
    return response


@app.middleware("http")
async def check_token(request: Request, call_next):
    """Reject requests without valid token (if token is configured)."""
    if _api_token and request.url.path not in _AUTH_EXEMPT:
        header_token = request.headers.get("X-API-Token", "")
        if not hmac.compare_digest(header_token, _api_token):
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    return await call_next(request)


# ── Health endpoint (always accessible) ────────────────────────────────

@app.get("/health")
def health() -> dict:
    """Health check (always accessible, no auth required)."""
    return {"status": "ok", "version": __version__}


# ── Pairing endpoint (no auth required) ───────────────────────────────

@app.post("/pair")
def pair_device(code: str):
    """Pair a remote device using the 6-char code shown in the terminal.

    Returns the persistent API token on success. The remote app stores
    this token and uses it for all future requests (X-API-Token header).
    No re-pairing needed after server restart.
    """
    if not _pairing_code:
        return JSONResponse(
            status_code=503,
            content={"detail": "Pairing not available (server started with --token)"},
        )

    if not hmac.compare_digest(code.upper(), _pairing_code.upper()):
        log.warning("Pairing attempt with wrong code")
        return JSONResponse(
            status_code=403, content={"detail": "Invalid pairing code"},
        )

    if not _api_token:
        return JSONResponse(
            status_code=500, content={"detail": "No API token configured"},
        )

    log.info("Remote device paired successfully")
    return {"success": True, "token": _api_token}


# ── Register routers ──────────────────────────────────────────────────

from trcc.api.devices import router as devices_router  # noqa: E402
from trcc.api.display import router as display_router  # noqa: E402
from trcc.api.i18n import router as i18n_router  # noqa: E402
from trcc.api.led import router as led_router  # noqa: E402
from trcc.api.system import router as system_router  # noqa: E402
from trcc.api.themes import router as themes_router  # noqa: E402

app.include_router(devices_router)
app.include_router(display_router)
app.include_router(i18n_router)
app.include_router(led_router)
app.include_router(themes_router)
app.include_router(system_router)
