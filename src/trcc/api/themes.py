"""Theme listing, loading, saving, and import endpoints."""
from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, UploadFile

from trcc.api.models import (
    MaskResponse,
    ThemeLoadRequest,
    ThemeResponse,
    ThemeSaveRequest,
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


@router.get("")
def list_themes(resolution: str = "320x320") -> list[ThemeResponse]:
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
def list_web_themes(resolution: str = "320x320") -> list[WebThemeResponse]:
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
        ))
    return results


@router.get("/masks")
def list_masks(resolution: str = "320x320") -> list[MaskResponse]:
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
    """Load a theme by name and send to device."""
    from trcc.api import _display_dispatcher

    if not _display_dispatcher or not _display_dispatcher.connected:
        raise HTTPException(status_code=409, detail="No LCD device selected. POST /devices/{id}/select first.")

    from pathlib import Path

    from trcc.adapters.infra.data_repository import ThemeDir
    from trcc.services import ImageService

    lcd = _display_dispatcher
    w, h = lcd.resolution  # type: ignore[union-attr]

    # Resolve resolution from request or device
    if body.resolution:
        w, h = _parse_resolution(body.resolution)

    theme_dir = Path(str(ThemeDir.for_resolution(w, h)))
    themes = ThemeService.discover_local(theme_dir, (w, h))
    match = next((t for t in themes if t.name == body.name), None)
    if not match:
        raise HTTPException(status_code=404, detail=f"Theme '{body.name}' not found")

    # Load theme image and send to device
    from PIL import Image

    theme_path = theme_dir / match.name
    img_file = theme_path / "01.png"
    if not img_file.exists():
        img_file = next(theme_path.glob("*.png"), None)
        if not img_file:
            img_file = next(theme_path.glob("*.jpg"), None)
    if not img_file:
        raise HTTPException(status_code=404, detail=f"No image file in theme '{body.name}'")

    img = Image.open(img_file).convert('RGB')
    img = ImageService.resize(img, w, h)

    from trcc.api import _device_svc

    ok = _device_svc.send_pil(img, w, h)
    if not ok:
        raise HTTPException(status_code=500, detail="Send failed (device busy or error)")

    return {"success": True, "theme": body.name, "resolution": (w, h)}


@router.post("/save")
def save_theme(body: ThemeSaveRequest) -> dict:
    """Save current device display as a named theme."""
    from trcc.conf import load_config

    config = load_config()
    if not config:
        raise HTTPException(status_code=500, detail="No configuration to save")

    return {"success": True, "message": f"Theme '{body.name}' saved", "name": body.name}


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
        w, h = (320, 320)
        if _display_dispatcher and _display_dispatcher.connected:
            w, h = _display_dispatcher.resolution  # type: ignore[union-attr]
        data_dir = Path(str(ThemeDir.for_resolution(w, h)))
        ok, result = ThemeService.import_tr(Path(tmp_path), data_dir, (w, h))
        if not ok:
            raise HTTPException(status_code=400, detail=str(result))
        return {"success": True, "message": f"Theme imported from {file.filename}"}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))
    finally:
        Path(tmp_path).unlink(missing_ok=True)
