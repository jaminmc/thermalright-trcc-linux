"""Theme listing, loading, saving, and import endpoints."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, UploadFile
from fastapi.responses import Response

from trcc.api.models import (
    MaskResponse,
    ThemeLoadRequest,
    ThemeResponse,
    ThemeSaveRequest,
    WebThemeDownloadResponse,
    WebThemeResponse,
)
from trcc.services import ThemeService

log = logging.getLogger(__name__)

router = APIRouter(prefix="/themes", tags=["themes"])


def _parse_resolution(resolution: str) -> tuple[int, int]:
    """Parse 'WxH' string, raise 400 on invalid format."""
    try:
        parts = resolution.split("x")
        w, h = int(parts[0]), int(parts[1])
    except (ValueError, IndexError):
        raise HTTPException(status_code=400, detail="Invalid resolution format (use WxH)")
    if not (100 <= w <= 4096 and 100 <= h <= 4096):
        raise HTTPException(status_code=400, detail="Resolution out of range (100-4096)")
    return w, h



def _preview_url(theme_name: str, theme_dir: str) -> str:
    """Resolve preview URL for a local theme — Theme.png or 00.png fallback."""
    theme_path = os.path.join(theme_dir, theme_name)
    if os.path.isfile(os.path.join(theme_path, 'Theme.png')):
        return f"/static/themes/{theme_name}/Theme.png"
    if os.path.isfile(os.path.join(theme_path, '00.png')):
        return f"/static/themes/{theme_name}/00.png"
    return ""


@router.post("/init")
def init_theme_data(resolution: str) -> dict:
    """Download and extract theme/web/mask archives for a resolution.

    Safe to call repeatedly — no-op if data is already cached.
    Designed for remote apps to call on startup before listing themes.
    Works regardless of whether a device is connected.
    """
    from trcc.adapters.infra.data_repository import DataManager

    w, h = _parse_resolution(resolution)

    DataManager.ensure_all(w, h)

    # Remount static dirs now that data exists on disk
    from trcc.api import mount_static_dirs
    mount_static_dirs(w, h)

    return {"success": True, "resolution": f"{w}x{h}"}


@router.get("")
def list_themes(resolution: str) -> list[ThemeResponse]:
    """List available local themes for a given resolution."""
    w, h = _parse_resolution(resolution)

    from pathlib import Path

    from trcc.adapters.infra.data_repository import ThemeDir
    td = ThemeDir.for_resolution(w, h)
    theme_dir = Path(str(td))
    themes = ThemeService.discover_local(theme_dir, (w, h))
    return [
        ThemeResponse(
            name=t.name,
            category=t.category or "",
            is_animated=t.is_animated,
            has_config=t.config_path is not None,
            preview_url=_preview_url(t.name, str(td.path)),
        )
        for t in themes
    ]


@router.get("/web")
def list_web_themes(resolution: str) -> list[WebThemeResponse]:
    """List available cloud theme previews for a given resolution."""
    w, h = _parse_resolution(resolution)

    from trcc.adapters.infra.data_repository import DataManager
    web_dir = DataManager.get_web_dir(w, h)

    results: list[WebThemeResponse] = []
    if not os.path.isdir(web_dir):
        return results

    for fname in sorted(os.listdir(web_dir)):
        if not fname.endswith('.png'):
            continue
        theme_id = fname[:-4]  # strip .png
        # Infer category from first letter (a=Gallery, b=Tech, etc.)
        category = theme_id[0] if theme_id else ""
        has_video = os.path.isfile(os.path.join(web_dir, f"{theme_id}.mp4"))
        results.append(WebThemeResponse(
            id=theme_id,
            category=category,
            preview_url=f"/static/web/{fname}",
            has_video=has_video,
            download_url=f"/themes/web/{theme_id}/download",
        ))
    return results


@router.post("/web/{theme_id}/download")
def download_web_theme(
    theme_id: str,
    resolution: str | None = None,
    send: bool = False,
) -> WebThemeDownloadResponse:
    """Download a cloud theme MP4 to local cache.

    Optionally sends its first frame to the LCD device if ``send=True``.
    """
    import re

    # Validate theme_id — alphanumeric only, no path traversal
    if not re.fullmatch(r'[a-zA-Z0-9_\-]+', theme_id):
        raise HTTPException(status_code=400, detail="Invalid theme ID")
    from trcc.adapters.infra.data_repository import DataManager
    from trcc.adapters.infra.theme_cloud import CloudThemeDownloader
    from trcc.api import _display_dispatcher

    # Resolve resolution from parameter or connected device
    if resolution:
        w, h = _parse_resolution(resolution)
    elif _display_dispatcher and _display_dispatcher.connected:
        w, h = _display_dispatcher.resolution  # type: ignore[union-attr]
    else:
        raise HTTPException(
            status_code=400,
            detail="resolution required — no device connected and no resolution specified",
        )

    if send and (not _display_dispatcher or not _display_dispatcher.connected):
        raise HTTPException(
            status_code=409,
            detail="No LCD device selected. POST /devices/{id}/select first.",
        )

    # Download (or use cache)
    web_dir = DataManager.get_web_dir(w, h)
    downloader = CloudThemeDownloader(
        resolution=f"{w}x{h}", cache_dir=web_dir,
    )

    already_cached = downloader.is_cached(theme_id)
    result_path = downloader.download_theme(theme_id)
    if not result_path:
        raise HTTPException(status_code=404, detail=f"Cloud theme '{theme_id}' not found on server")

    # Optionally start video playback on device
    if send:
        from trcc.api import start_video_playback, stop_overlay_loop, stop_video_playback

        stop_video_playback()
        stop_overlay_loop()
        ok = start_video_playback(result_path, w, h, loop=True)
        if not ok:
            log.warning("Failed to start video playback for %s", theme_id)

    return WebThemeDownloadResponse(
        id=theme_id,
        cached_path=result_path,
        resolution=f"{w}x{h}",
        already_cached=already_cached,
    )


@router.get("/masks")
def list_masks(resolution: str) -> list[MaskResponse]:
    """List available mask overlays for a given resolution."""
    w, h = _parse_resolution(resolution)

    from trcc.adapters.infra.data_repository import DataManager
    masks_dir = DataManager.get_web_masks_dir(w, h)

    results: list[MaskResponse] = []
    if not os.path.isdir(masks_dir):
        return results

    for entry in sorted(os.listdir(masks_dir)):
        entry_path = os.path.join(masks_dir, entry)
        if not os.path.isdir(entry_path):
            continue
        # Use Theme.png if available, else 00.png
        if os.path.isfile(os.path.join(entry_path, 'Theme.png')):
            url = f"/static/masks/{entry}/Theme.png"
        elif os.path.isfile(os.path.join(entry_path, '00.png')):
            url = f"/static/masks/{entry}/00.png"
        else:
            continue
        results.append(MaskResponse(name=entry, preview_url=url))
    return results


@router.post("/load")
def load_theme(body: ThemeLoadRequest) -> dict:
    """Load a theme by name and send to device.

    Full pipeline matching GUI/CLI behavior:
    1. Stop any running video/overlay
    2. load_theme_by_name() → select + send + persist
    3. Start video playback for animated themes
    4. Start overlay loop for themes with config1.dc
    5. Update preview image for WebSocket stream

    Works in both standalone and IPC (GUI daemon) modes.
    In IPC mode, the GUI daemon handles the full pipeline.
    """
    import trcc.api as api
    from trcc.api.models import dispatch_result

    if not api._display_dispatcher or not api._display_dispatcher.connected:
        raise HTTPException(status_code=409, detail="No LCD device selected. POST /devices/{id}/select first.")

    api.stop_video_playback()
    api.stop_overlay_loop()

    w, h = 0, 0
    if body.resolution:
        w, h = _parse_resolution(body.resolution)

    result = api._display_dispatcher.load_theme_by_name(body.name, w, h)
    if not result.get("success"):
        return dispatch_result(result)

    # Update preview image for WebSocket stream
    image = result.get("image")
    if image:
        api.set_current_image(image)

    # Standalone mode — start video/overlay loops (GUI handles its own)
    is_animated = result.get("is_animated", False)
    theme_path = result.get("theme_path")
    config_path = result.get("config_path")

    if not w or not h:
        res = getattr(api._display_dispatcher, 'resolution', None)
        if res:
            w, h = res
        else:
            raise HTTPException(
                status_code=409,
                detail="No device connected and no resolution available",
            )

    if is_animated and theme_path:
        # Find video file (Theme.zt or .mp4)
        from pathlib import Path
        theme_dir = Path(str(theme_path))
        video_path = None
        for ext in ('.zt', '.mp4'):
            for name in ('Theme', 'theme'):
                candidate = theme_dir / f"{name}{ext}"
                if candidate.exists():
                    video_path = str(candidate)
                    break
            if video_path:
                break
        if video_path:
            api.start_video_playback(video_path, w, h, loop=True)

    elif config_path and os.path.isfile(config_path) and image:
        # Static theme with overlay config — start metrics loop
        api.start_overlay_loop(image, str(config_path), w, h)

    return dispatch_result(result)


@router.post("/save")
def save_theme(body: ThemeSaveRequest) -> dict:
    """Save current device display as a named theme."""
    from trcc.conf import load_config

    config = load_config()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration to save")

    return {"success": True, "message": f"Theme '{body.name}' saved", "name": body.name}


@router.post("/export")
def export_theme(theme_name: str, resolution: str | None = None) -> Response:
    """Export a theme as a downloadable .tr archive."""
    import re
    import tempfile
    from pathlib import Path

    from fastapi.responses import FileResponse

    from trcc.api import _display_dispatcher

    # Validate theme_name — no path traversal
    if not re.fullmatch(r'[a-zA-Z0-9_ \-().]+', theme_name):
        raise HTTPException(status_code=400, detail="Invalid theme name")

    # Resolve resolution from query param or connected device
    if resolution:
        w, h = _parse_resolution(resolution)
    elif _display_dispatcher and _display_dispatcher.connected:
        w, h = _display_dispatcher.resolution  # type: ignore[union-attr]
    else:
        raise HTTPException(
            status_code=400,
            detail="resolution required — no device connected and no resolution specified",
        )

    from trcc.adapters.infra.data_repository import ThemeDir
    td = ThemeDir.for_resolution(w, h)
    theme_dir = Path(str(td))

    themes = ThemeService.discover_local(theme_dir, (w, h))
    match = next((t for t in themes if t.name == theme_name), None)
    if not match:
        match = next(
            (t for t in themes if theme_name.lower() in t.name.lower()),
            None,
        )
    if not match or not match.path:
        raise HTTPException(status_code=404, detail=f"Theme not found: {theme_name}")

    from trcc.adapters.infra.dc_config import DcConfig
    from trcc.adapters.infra.dc_parser import load_config_json
    from trcc.adapters.infra.dc_writer import export_theme as _export_fn
    theme_svc = ThemeService(
        export_theme_fn=_export_fn,
        load_config_json_fn=load_config_json,
        dc_config_cls=DcConfig,
    )

    tmp = tempfile.NamedTemporaryFile(suffix='.tr', delete=False)
    tmp.close()
    ok, msg = theme_svc.export_tr(match.path, Path(tmp.name))
    if not ok:
        Path(tmp.name).unlink(missing_ok=True)
        raise HTTPException(status_code=500, detail=msg)

    return FileResponse(
        tmp.name,
        media_type="application/octet-stream",
        filename=f"{match.name}.tr",
        background=None,
    )


@router.post("/import")
async def import_theme(file: UploadFile) -> dict:
    """Import a .tr theme archive."""
    import tempfile
    from pathlib import Path

    if not file.filename or not file.filename.endswith('.tr'):
        raise HTTPException(status_code=400, detail="File must be a .tr theme archive")

    data = await file.read()
    if len(data) > 50 * 1024 * 1024:  # 50 MB limit for theme archives
        raise HTTPException(status_code=413, detail="Theme archive exceeds 50 MB limit")

    with tempfile.NamedTemporaryFile(suffix='.tr', delete=False) as tmp:
        tmp.write(data)
        tmp_path = tmp.name

    try:
        from trcc.adapters.infra.data_repository import ThemeDir
        from trcc.api import _display_dispatcher
        if not _display_dispatcher or not _display_dispatcher.connected:
            raise HTTPException(
                status_code=409,
                detail="No device connected. POST /devices/{id}/select first.",
            )
        w, h = _display_dispatcher.resolution  # type: ignore[union-attr]
        data_dir = Path(str(ThemeDir.for_resolution(w, h)))
        from trcc.adapters.infra.dc_config import DcConfig
        from trcc.adapters.infra.dc_parser import load_config_json
        from trcc.adapters.infra.dc_writer import import_theme as _import_fn
        theme_svc = ThemeService(
            import_theme_fn=_import_fn,
            load_config_json_fn=load_config_json,
            dc_config_cls=DcConfig,
        )
        ok, result = theme_svc.import_tr(Path(tmp_path), data_dir, (w, h))
        if not ok:
            log.warning("Theme import failed: %s", result)
            raise HTTPException(status_code=400, detail="Theme import failed")
        return {"success": True, "message": "Theme imported successfully"}
    except HTTPException:
        raise
    except Exception:
        log.exception("Theme import error")
        raise HTTPException(status_code=500, detail="Internal server error")
    finally:
        Path(tmp_path).unlink(missing_ok=True)
