"""FastAPI REST API — Driving adapter for headless/remote control.

Package structure mirrors cli/ — one module per domain:
    __init__.py — app, auth middleware, health, shared state
    models.py   — Pydantic request/response models
    devices.py  — device detection, selection, image send
    display.py  — LCD display settings (brightness, rotation, color, etc.)
    led.py      — LED RGB control (color, mode, zones, segments)
    themes.py   — theme listing, load, save, import
    system.py   — system metrics, diagnostic report

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
