"""FastAPI REST API — Driving adapter for headless/remote control.

Package structure mirrors cli/ — one module per domain:
    __init__.py — app, auth middleware, health, shared state
    models.py   — Pydantic request/response models
    devices.py  — device detection, selection, image send
    display.py  — LCD display settings (brightness, rotation, color, etc.)
    led.py      — LED RGB control (color, mode, zones, segments)
    themes.py   — theme listing, load, save, import
    system.py   — system metrics, diagnostic report

API is a thin HTTP adapter over CLI dispatchers. All business logic
lives in DisplayService/LEDService, accessed through DisplayDispatcher
and LEDDispatcher. Background threads for video/overlay pumping are
the only API-specific concern (adapter scheduling).

Security:
    - Localhost-only by default (bind 127.0.0.1)
    - Optional token auth via --token flag (X-API-Token header)
    - Optional TLS via --tls flag (auto-generates self-signed cert)
    - 10 MB upload limit with PIL format validation
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
from trcc.services import DeviceService

log = logging.getLogger(__name__)

# ── App ────────────────────────────────────────────────────────────────

app = FastAPI(title="TRCC Linux", version=__version__)

# ── Shared state ───────────────────────────────────────────────────────

_device_svc = DeviceService()

# Lazy-initialized dispatchers (set when device is selected)
_display_dispatcher = None  # DisplayDispatcher | None
_led_dispatcher = None      # LEDDispatcher | None
_system_svc = None          # SystemService | None

# Last frame sent to LCD — updated by on_frame_sent callback for preview
_current_image = None  # PIL Image | None


def set_current_image(img) -> None:
    """Update the tracked LCD frame (called by on_frame_sent callback)."""
    global _current_image  # noqa: PLW0603
    _current_image = img


# ── Video playback (background thread — adapter scheduling) ──────────

_video_thread: threading.Thread | None = None
_video_stop_event: threading.Event | None = None


def start_video_playback(
    video_path: str, width: int, height: int, *, loop: bool = True,
) -> bool:
    """Start background video playback using dispatcher's DisplayService.

    Thread pumps dispatcher.video_tick() → send frames to LCD.
    Service creation/ownership lives in DisplayService, not here.
    """
    global _video_thread, _video_stop_event  # noqa: PLW0603

    stop_video_playback()

    if not _display_dispatcher or not _display_dispatcher.display_service:
        return False

    dispatcher = _display_dispatcher  # local ref for closure
    media = dispatcher.display_service.media
    media.set_target_size(width, height)
    if not media.load(Path(video_path)):
        return False

    media._state.loop = loop
    dispatcher.play_video()

    _video_stop_event = threading.Event()
    stop_event = _video_stop_event

    def _pump() -> None:
        interval = media.frame_interval_ms / 1000.0
        while not stop_event.is_set() and media.is_playing:
            result = dispatcher.video_tick()
            if not result.get("success"):
                break
            frame = result.get("frame")
            if frame is not None and result.get("send"):
                _device_svc.send_pil(frame, width, height)
            stop_event.wait(interval)

    _video_thread = threading.Thread(target=_pump, daemon=True, name="api-video")
    _video_thread.start()
    log.info("Video playback started: %s (%dx%d)", video_path, width, height)
    return True


def stop_video_playback() -> None:
    """Stop background video playback."""
    global _video_thread, _video_stop_event  # noqa: PLW0603

    if _video_stop_event:
        _video_stop_event.set()
    if _video_thread and _video_thread.is_alive():
        _video_thread.join(timeout=2)
    if _display_dispatcher:
        _display_dispatcher.stop_video()
    _video_thread = None
    _video_stop_event = None


def pause_video_playback() -> None:
    """Toggle pause on background video playback."""
    if _display_dispatcher:
        _display_dispatcher.pause_video()


# ── Overlay metrics loop (background thread — adapter scheduling) ─────

_overlay_thread: threading.Thread | None = None
_overlay_stop_event: threading.Event | None = None


def start_overlay_loop(
    background, dc_path: str, width: int, height: int,
) -> bool:
    """Start background overlay rendering using dispatcher's DisplayService.

    Thread polls metrics → dispatcher.update_metrics() → render → send.
    """
    global _overlay_thread, _overlay_stop_event  # noqa: PLW0603

    stop_overlay_loop()

    if not _display_dispatcher or not _display_dispatcher.display_service:
        return False

    dispatcher = _display_dispatcher  # local ref for closure
    overlay = dispatcher.display_service.overlay
    overlay.set_background(background)
    overlay.load_from_dc(Path(dc_path))
    dispatcher.enable_overlay(True)

    _overlay_stop_event = threading.Event()
    stop_event = _overlay_stop_event

    def _loop() -> None:
        from trcc.services.system import get_all_metrics

        while not stop_event.is_set():
            metrics = get_all_metrics()
            if overlay.would_change(metrics):
                dispatcher.update_metrics(metrics)
                result = dispatcher.render_current_overlay()
                frame = result.get("image") if result.get("success") else None
                if frame is not None:
                    _device_svc.send_pil(frame, width, height)
            stop_event.wait(2.0)

    _overlay_thread = threading.Thread(target=_loop, daemon=True, name="api-overlay")
    _overlay_thread.start()
    log.info("Overlay loop started: %s (%dx%d)", dc_path, width, height)
    return True


def stop_overlay_loop() -> None:
    """Stop background overlay rendering."""
    global _overlay_thread, _overlay_stop_event  # noqa: PLW0603

    if _overlay_stop_event:
        _overlay_stop_event.set()
    if _overlay_thread and _overlay_thread.is_alive():
        _overlay_thread.join(timeout=2)
    if _display_dispatcher:
        _display_dispatcher.enable_overlay(False)
    _overlay_thread = None
    _overlay_stop_event = None


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


# ── Token auth middleware (optional, enabled via --token) ─────────────

_api_token: str | None = None


def configure_auth(token: str | None) -> None:
    """Set the API token. Called by CLI serve command."""
    global _api_token  # noqa: PLW0603
    _api_token = token


@app.middleware("http")
async def check_token(request: Request, call_next):
    """Reject requests without valid token (if token is configured)."""
    if _api_token and request.url.path != "/health":
        header_token = request.headers.get("X-API-Token", "")
        if not hmac.compare_digest(header_token, _api_token):
            return JSONResponse(status_code=401, content={"detail": "Invalid token"})
    return await call_next(request)


# ── Health endpoint (always accessible) ────────────────────────────────

@app.get("/health")
def health() -> dict:
    """Health check (always accessible, no auth required)."""
    return {"status": "ok", "version": __version__}


# ── Register routers ──────────────────────────────────────────────────

from trcc.api.devices import router as devices_router  # noqa: E402
from trcc.api.display import router as display_router  # noqa: E402
from trcc.api.led import router as led_router  # noqa: E402
from trcc.api.system import router as system_router  # noqa: E402
from trcc.api.themes import router as themes_router  # noqa: E402

app.include_router(devices_router)
app.include_router(display_router)
app.include_router(led_router)
app.include_router(themes_router)
app.include_router(system_router)
