"""Theme discovery and loading commands."""
from __future__ import annotations

from trcc.cli import _cli_handler, _device


@_cli_handler
def list_themes(cloud=False, category=None):
    """List available themes for the current device resolution."""
    from trcc.adapters.infra.data_repository import DataManager
    from trcc.conf import settings
    from trcc.services import ThemeService

    w, h = settings.width, settings.height
    if not w or not h:
        w, h = 320, 320

    DataManager.ensure_all(w, h)
    settings._resolve_paths()

    if cloud:
        web_dir = settings.web_dir
        if not web_dir or not web_dir.exists():
            print(f"No cloud themes for {w}x{h}.")
            return 0
        themes = ThemeService.discover_cloud(web_dir, category)
        print(f"Cloud themes ({w}x{h}): {len(themes)}")
        for t in themes:
            cat = f" [{t.category}]" if t.category else ""
            print(f"  {t.name}{cat}")
    else:
        td = settings.theme_dir
        if not td or not td.exists():
            print(f"No local themes for {w}x{h}.")
            return 0
        themes = ThemeService.discover_local(td.path, (w, h))
        print(f"Local themes ({w}x{h}): {len(themes)}")
        for t in themes:
            kind = "video" if t.is_animated else "static"
            user = " [user]" if t.name.startswith(('Custom_', 'User')) else ""
            print(f"  {t.name} ({kind}){user}")

    return 0


@_cli_handler
def load_theme(name, *, device=None, preview=False):
    """Load a theme by name and send to LCD."""
    from trcc.adapters.infra.data_repository import DataManager
    from trcc.conf import Settings, settings
    from trcc.services import ImageService, ThemeService

    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    dev = svc.selected
    w, h = dev.resolution

    DataManager.ensure_all(w, h)
    settings._resolve_paths()

    td = settings.theme_dir
    if not td or not td.exists():
        print(f"No themes for {w}x{h}.")
        return 1

    themes = ThemeService.discover_local(td.path, (w, h))
    match = next((t for t in themes if t.name == name), None)
    if not match:
        # Try partial match
        match = next((t for t in themes if name.lower() in t.name.lower()), None)
    if not match:
        print(f"Theme not found: {name}")
        print("Use 'trcc theme-list' to see available themes.")
        return 1

    # Load the theme image
    if match.is_animated and match.animation_path:
        print(f"Theme '{match.name}' is animated — use 'trcc video {match.animation_path}'")
        return 0

    if match.background_path and match.background_path.exists():
        img = ImageService.open_and_resize(match.background_path, w, h)

        # Apply saved adjustments
        key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
        cfg = Settings.get_device_config(key)
        brightness = {1: 25, 2: 50, 3: 100}.get(
            cfg.get('brightness_level', 3), 100)
        rotation = cfg.get('rotation', 0)
        img = ImageService.apply_brightness(img, brightness)
        img = ImageService.apply_rotation(img, rotation)

        svc.send_pil(img, w, h)

        # Save as last-used theme
        Settings.save_device_setting(key, 'theme_path', str(match.path))
        print(f"Loaded '{match.name}' → {dev.path}")
        if preview:
            print(ImageService.to_ansi(img))
    else:
        print(f"Theme '{match.name}' has no background image.")
        return 1

    return 0


@_cli_handler
def save_theme(name, *, device=None, video=None):
    """Save current display state as a custom theme."""
    from pathlib import Path

    from trcc.adapters.infra.data_repository import USER_DATA_DIR
    from trcc.services import ImageService, ThemeService

    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    dev = svc.selected
    w, h = dev.resolution

    # Load current background from last-used theme
    from trcc.conf import Settings
    key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
    cfg = Settings.get_device_config(key)
    theme_path = cfg.get('theme_path')

    bg = None
    if theme_path:
        from trcc.core.models import ThemeDir as TDir
        td = TDir(theme_path)
        if td.bg.exists():
            bg = ImageService.open_and_resize(td.bg, w, h)

    if not bg:
        print("No current theme to save. Load a theme first.")
        return 1

    video_path = Path(video) if video else None
    data_dir = Path(USER_DATA_DIR)
    ok, msg = ThemeService.save(
        name, data_dir, (w, h),
        background=bg, overlay_config={},
        video_path=video_path,
        current_theme_path=Path(theme_path) if theme_path else None,
    )
    print(msg)
    return 0 if ok else 1


@_cli_handler
def export_theme(theme_name, output_path):
    """Export a theme as .tr file."""
    from pathlib import Path

    from trcc.adapters.infra.data_repository import DataManager
    from trcc.conf import settings
    from trcc.services import ThemeService

    w, h = settings.width, settings.height
    if not w or not h:
        w, h = 320, 320

    DataManager.ensure_all(w, h)
    settings._resolve_paths()

    td = settings.theme_dir
    if not td or not td.exists():
        print(f"No themes for {w}x{h}.")
        return 1

    # Find theme by name
    themes = ThemeService.discover_local(td.path, (w, h))
    match = next((t for t in themes if t.name == theme_name), None)
    if not match:
        match = next(
            (t for t in themes if theme_name.lower() in t.name.lower()),
            None,
        )
    if not match or not match.path:
        print(f"Theme not found: {theme_name}")
        return 1

    from trcc.adapters.infra.dc_config import DcConfig
    from trcc.adapters.infra.dc_parser import load_config_json
    from trcc.adapters.infra.dc_writer import export_theme as _export_fn
    theme_svc = ThemeService(
        export_theme_fn=_export_fn,
        load_config_json_fn=load_config_json,
        dc_config_cls=DcConfig,
    )
    ok, msg = theme_svc.export_tr(match.path, Path(output_path))
    print(msg)
    return 0 if ok else 1


@_cli_handler
def import_theme(file_path, *, device=None):
    """Import a theme from .tr file."""
    from pathlib import Path

    from trcc.adapters.infra.data_repository import USER_DATA_DIR
    from trcc.adapters.infra.dc_config import DcConfig
    from trcc.adapters.infra.dc_parser import load_config_json
    from trcc.adapters.infra.dc_writer import import_theme as _import_fn
    from trcc.services import ThemeService

    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    dev = svc.selected
    w, h = dev.resolution
    data_dir = Path(USER_DATA_DIR)

    theme_svc = ThemeService(
        import_theme_fn=_import_fn,
        load_config_json_fn=load_config_json,
        dc_config_cls=DcConfig,
    )
    ok, result = theme_svc.import_tr(
        Path(file_path), data_dir, (w, h))
    if ok and not isinstance(result, str):
        print(f"Imported: {result.name}")
    else:
        print(result)
    return 0 if ok else 1
