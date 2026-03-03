"""Theme discovery and loading commands.

All operations route through DisplayDispatcher — no direct
service/adapter imports. CLI functions are thin presentation wrappers.
"""
from __future__ import annotations

from trcc.cli import _cli_handler


@_cli_handler
def list_themes(cloud=False, category=None):
    """List available themes for the current device resolution."""
    from trcc.cli._display import DisplayDispatcher

    lcd = DisplayDispatcher()
    result = lcd.list_themes(category=category or '')

    res = result.get("resolution", [320, 320])
    w, h = res[0], res[1]

    if cloud:
        themes = result.get("cloud", [])
        if not themes:
            print(f"No cloud themes for {w}x{h}.")
            return 0
        print(f"Cloud themes ({w}x{h}): {len(themes)}")
        for t in themes:
            cat = f" [{t.category}]" if t.category else ""
            print(f"  {t.name}{cat}")
    else:
        themes = result.get("local", [])
        if not themes:
            print(f"No local themes for {w}x{h}.")
            return 0
        print(f"Local themes ({w}x{h}): {len(themes)}")
        for t in themes:
            kind = "video" if t.is_animated else "static"
            user = " [user]" if t.name.startswith(('Custom_', 'User')) else ""
            print(f"  {t.name} ({kind}){user}")

    return 0


@_cli_handler
def load_theme(name, *, device=None, preview=False):
    """Load a theme by name and send to LCD."""
    from trcc.cli._display import _connect_or_fail, _print_result

    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc

    result = lcd.load_theme_by_name(name)
    if result.get("is_animated"):
        print(result["message"])
        return 0

    return _print_result(result, preview=preview)


@_cli_handler
def save_theme(name, *, device=None, video=None):
    """Save current display state as a custom theme."""
    from trcc.cli._display import _connect_or_fail, _print_result

    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc

    result = lcd.save_custom_theme(name, video=video)
    return _print_result(result)


@_cli_handler
def export_theme(theme_name, output_path):
    """Export a theme as .tr file."""
    from trcc.cli._display import DisplayDispatcher, _print_result

    lcd = DisplayDispatcher()
    result = lcd.export_theme_by_name(theme_name, output_path)
    return _print_result(result)


@_cli_handler
def import_theme(file_path, *, device=None):
    """Import a theme from .tr file."""
    from trcc.cli._display import _connect_or_fail, _print_result

    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc

    result = lcd.import_theme_file(file_path)
    return _print_result(result)
