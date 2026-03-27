"""Theme discovery and loading commands."""
from __future__ import annotations

from trcc.cli import _cli_handler, _device


@_cli_handler
def list_themes(cloud=False, category=None):
    """List available themes for the current device resolution."""
    from trcc.conf import settings
    from trcc.services import ThemeService

    w, h = settings.width, settings.height
    if not w or not h:
        print("No device resolution saved. Connect your device first.")
        return 1

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
def load_theme(builder, name, *, device=None, preview=False):
    """Load a theme by name and send to LCD."""
    from trcc.conf import Settings, settings
    from trcc.core.commands.lcd import SelectThemeCommand
    from trcc.services import ImageService, ThemeService

    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    dev = svc.selected
    w, h = dev.resolution

    settings.set_resolution(w, h)

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

    # Build LCD with full service stack (DisplayService, OverlayService, etc.)
    from trcc.core.app import TrccApp
    lcd = builder.lcd_from_service(svc)
    lcd.restore_device_settings()

    # Dispatch SelectThemeCommand through the bus — same path as GUI/API
    lcd_bus = TrccApp.get().build_lcd_bus(lcd)
    cmd_result = lcd_bus.dispatch(SelectThemeCommand(theme=match))
    result = cmd_result.payload

    # Save as last-used theme
    key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
    Settings.save_device_setting(key, 'theme_path', str(match.path))

    if result.get('is_animated') and lcd._display_svc.media.has_frames:
        print(f"Playing '{match.name}' → {dev.path}")
        print("Press Ctrl+C to stop.")

        # Get metrics supplier if overlay is enabled
        metrics_fn = None
        if lcd._display_svc.overlay.enabled:
            from trcc.cli import _ensure_system
            from trcc.services.system import get_all_metrics
            _ensure_system(builder)
            metrics_fn = get_all_metrics

        lcd._display_svc.media._state.loop = True
        lcd._display_svc.media.play()

        loop_result = lcd._display_svc._run_tick_loop(
            metrics_fn=metrics_fn,
            on_frame=lambda img: svc.send_frame(img, w, h),
            on_progress=lambda p, c, t: print(
                f"\r  {c} / {t} ({p:.0f}%)", end="", flush=True),
        )
        print(f"\n{loop_result['message']}.")
    else:
        # Static theme
        img = result.get('image')
        if img:
            lcd.send(img)
            print(f"Loaded '{match.name}' → {dev.path}")
            if preview:
                print(ImageService.to_ansi(img))
        else:
            print(f"Theme '{match.name}' has no background image.")
            return 1

    return 0


@_cli_handler
def save_theme(name, *, device=None, video=None, background=None,
               metrics=None, mask=None, font_size=14, color='ffffff',
               font='Microsoft YaHei', font_style='regular',
               temp_unit=0, time_format=0, date_format=0):
    """Save current display state as a custom theme."""
    from pathlib import Path

    from trcc.conf import settings as _settings
    from trcc.services import ImageService, ThemeService

    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    dev = svc.selected
    w, h = dev.resolution

    # --background replaces --video (auto-detect animated vs static)
    bg_source = background or video
    video_path = None
    bg = None

    if bg_source:
        p = Path(bg_source)
        if not p.exists():
            print(f"Error: File not found: {bg_source}")
            return 1
        suffix = p.suffix.lower()
        if suffix in ('.mp4', '.gif', '.zt', '.webm', '.avi', '.mkv'):
            video_path = p
            # Load first frame as background thumbnail
            bg = ImageService.open_and_resize(p, w, h)
        else:
            bg = ImageService.open_and_resize(p, w, h)

    if not bg:
        # Fall back to current theme's background
        from trcc.conf import Settings
        key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
        cfg = Settings.get_device_config(key)
        theme_path = cfg.get('theme_path')
        if theme_path:
            from trcc.core.models import ThemeDir as TDir
            td = TDir(theme_path)
            if td.bg.exists():
                bg = ImageService.open_and_resize(td.bg, w, h)

    if not bg:
        print("No background to save. Provide --background or load a theme first.")
        return 1

    # Build overlay config from --metric specs
    overlay_config: dict = {}
    if metrics:
        from trcc.core.models import build_overlay_config
        try:
            overlay_config = build_overlay_config(
                metrics,
                default_color=color,
                default_font_size=font_size,
                default_font=font,
                default_style=font_style,
                temp_unit=temp_unit,
                time_format=time_format,
                date_format=date_format,
            )
        except ValueError as e:
            print(f"Error: {e}")
            return 1

    # Load mask image if provided
    mask_img = None
    mask_source = None
    if mask:
        from trcc.services.overlay import OverlayService
        r = ImageService._r()
        mask_img = OverlayService.load_mask_from_path(Path(mask), r, w, h)
        mask_source = Path(mask)

    data_dir = _settings.user_data_dir
    ok, msg = ThemeService.save(
        name, data_dir, (w, h),
        background=bg, overlay_config=overlay_config,
        video_path=video_path,
        mask=mask_img,
        mask_source=mask_source,
    )
    print(msg)
    if overlay_config:
        print(f"  Overlay: {len(overlay_config)} elements")
    if mask:
        print(f"  Mask: {mask}")
    return 0 if ok else 1


@_cli_handler
def export_theme(theme_name, output_path):
    """Export a theme as .tr file."""
    from pathlib import Path

    from trcc.conf import settings
    from trcc.services import ThemeService

    w, h = settings.width, settings.height
    if not w or not h:
        print("No device resolution saved. Connect your device first.")
        return 1

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

    from trcc.adapters.infra.dc_config import DcConfig
    from trcc.adapters.infra.dc_parser import load_config_json
    from trcc.adapters.infra.dc_writer import import_theme as _import_fn
    from trcc.conf import settings as _settings
    from trcc.services import ThemeService

    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    dev = svc.selected
    w, h = dev.resolution
    data_dir = _settings.user_data_dir

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
