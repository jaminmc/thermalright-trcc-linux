"""
TRCC Linux — Command Line Interface.

Entry points for the trcc-linux package (Typer CLI).
Split into submodules by command group:
  _device.py   — detection, selection, probing
  _display.py  — LCD frame operations (test, send, color, video, resume,
                  brightness, rotation, screencast, mask, overlay)
  _theme.py    — theme listing, loading, save, export, import
  _led.py      — LED color, mode, brightness, off, sensor source
  _diag.py     — HID/LED diagnostics
  _system.py   — setup, install, admin, info, download
"""

import functools
import logging
from typing import Annotated, Optional

import typer

# =========================================================================
# CLI error handler decorator (imported by submodules via circular import)
# =========================================================================

def _cli_handler(func):
    """Decorator: catches Exception, prints error, returns 1."""
    @functools.wraps(func)
    def wrapper(*args, **kwargs):
        try:
            return func(*args, **kwargs)
        except KeyboardInterrupt:
            print("\nInterrupted.")
            return 0
        except Exception as e:
            print(f"Error: {e}")
            return 1
    return wrapper


# =========================================================================
# Import submodules (must be AFTER _cli_handler definition)
# =========================================================================

from trcc.cli import (  # noqa: E402
    _device,
    _diag,
    _display,
    _led,
    _system,
    _theme,
)

# =========================================================================
# Typer app
# =========================================================================

app = typer.Typer(
    help="Thermalright LCD Control Center for Linux",
    add_completion=False,
    pretty_exceptions_enable=False,
    context_settings={"help_option_names": ["--help", "-h"]},
)

_verbose = 0


def _version_callback(value: bool) -> None:
    if value:
        from trcc.__version__ import __version__
        typer.echo(f"trcc {__version__}")
        raise typer.Exit()


@app.callback(invoke_without_command=True)
def _main_callback(
    ctx: typer.Context,
    verbose: Annotated[int, typer.Option(
        "--verbose", "-v", count=True,
        help="Increase verbosity (-v, -vv, -vvv)",
    )] = 0,
    last_one: Annotated[bool, typer.Option(
        "--last-one",
        help="Start minimized to system tray with last-used theme (autostart)",
    )] = False,
    testing_hid: Annotated[bool, typer.Option(
        "--testing-hid", hidden=True,
        help="No-op (HID devices are now auto-detected)",
    )] = False,
    version: Annotated[Optional[bool], typer.Option(
        "--version", callback=_version_callback, is_eager=True,
        help="Show version and exit",
    )] = None,
) -> None:
    global _verbose
    _verbose = verbose
    if last_one:
        result = gui(verbose=verbose, start_hidden=True)
        raise typer.Exit(result or 0)
    if ctx.invoked_subcommand is None:
        typer.echo(ctx.get_help())


# =========================================================================
# GUI launcher
# =========================================================================

def gui(verbose=0, decorated=False, start_hidden=False):
    """Launch the GUI application.

    Args:
        verbose: Logging verbosity (0=warning, 1=info, 2=debug).
        decorated: Use decorated window with titlebar.
        start_hidden: Start minimized to system tray (used by --last-one autostart).
    """
    # Set up logging based on verbosity (filter out noisy PIL)
    if verbose >= 2:
        logging.basicConfig(level=logging.DEBUG, format='[%(levelname)s] %(name)s: %(message)s')
        logging.getLogger('PIL').setLevel(logging.WARNING)
    elif verbose == 1:
        logging.basicConfig(level=logging.INFO, format='[%(levelname)s] %(message)s')
    else:
        logging.basicConfig(level=logging.WARNING)

    try:
        from trcc.qt_components.qt_app_mvc import run_mvc_app
        print("[TRCC] Starting LCD Control Center...")
        return run_mvc_app(decorated=decorated, start_hidden=start_hidden)
    except ImportError as e:
        print(f"Error: PySide6 not available: {e}")
        print("Install with: pip install PySide6")
        return 1
    except Exception as e:
        print(f"Error launching GUI: {e}")
        import traceback
        traceback.print_exc()
        return 1


# =========================================================================
# Typer command functions (thin wrappers → submodule functions)
# =========================================================================

@app.command("gui")
def _cmd_gui(
    decorated: Annotated[bool, typer.Option(
        "--decorated", "-d",
        help="Use decorated window (normal window with titlebar, can minimize)",
    )] = False,
) -> int:
    """Launch graphical interface."""
    return gui(verbose=_verbose, decorated=decorated)


@app.command("detect")
def _cmd_detect(
    all_devices: Annotated[bool, typer.Option(
        "--all", "-a", help="Show all devices",
    )] = False,
) -> int:
    """Detect LCD device."""
    return _device.detect(show_all=all_devices)


@app.command("select")
def _cmd_select(
    number: Annotated[int, typer.Argument(help="Device number from 'trcc detect --all'")],
) -> int:
    """Select device to control."""
    return _device.select(number)


@app.command("test")
def _cmd_test(
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path (e.g., /dev/sg0)",
    )] = None,
    loop: Annotated[bool, typer.Option(
        "--loop", "-l", help="Loop colors continuously",
    )] = False,
) -> int:
    """Test display with color cycle."""
    return _display.test(device=device, loop=loop)


@app.command("send")
def _cmd_send(
    image: Annotated[str, typer.Argument(help="Image file to send")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Send image to LCD."""
    return _display.send_image(image, device=device)


@app.command("color")
def _cmd_color(
    hex_color: Annotated[str, typer.Argument(
        metavar="HEX", help="Hex color code (e.g., ff0000 for red)",
    )],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Display solid color."""
    return _display.send_color(hex_color, device=device)


@app.command("video")
def _cmd_video(
    path: Annotated[str, typer.Argument(help="Video/GIF/ZT file to play")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
    no_loop: Annotated[bool, typer.Option(
        "--no-loop", "-n", help="Play once without looping",
    )] = False,
    duration: Annotated[int, typer.Option(
        "--duration", "-t", help="Stop after N seconds (0=unlimited)",
    )] = 0,
) -> int:
    """Play video/GIF on LCD."""
    return _display.play_video(
        path, device=device, loop=not no_loop, duration=duration)


@app.command("brightness")
def _cmd_brightness(
    level: Annotated[int, typer.Argument(help="Brightness level: 1=25%, 2=50%, 3=100%")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Set display brightness."""
    return _display.set_brightness(level, device=device)


@app.command("rotation")
def _cmd_rotation(
    degrees: Annotated[int, typer.Argument(help="Rotation: 0, 90, 180, or 270")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Set display rotation."""
    return _display.set_rotation(degrees, device=device)


@app.command("screencast")
def _cmd_screencast(
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
    x: Annotated[int, typer.Option(help="Capture region X offset")] = 0,
    y: Annotated[int, typer.Option(help="Capture region Y offset")] = 0,
    w: Annotated[int, typer.Option(help="Capture region width (0=full)")] = 0,
    h: Annotated[int, typer.Option(help="Capture region height (0=full)")] = 0,
    fps: Annotated[int, typer.Option(help="Target frames per second")] = 10,
) -> int:
    """Stream screen region to LCD."""
    return _display.screencast(device=device, x=x, y=y, w=w, h=h, fps=fps)


@app.command("mask")
def _cmd_mask(
    path: Annotated[Optional[str], typer.Argument(
        help="Mask PNG file or theme directory",
    )] = None,
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
    clear: Annotated[bool, typer.Option(
        "--clear", "-c", help="Clear mask (send solid black)",
    )] = False,
) -> int:
    """Load mask overlay and send to LCD."""
    if clear:
        return _display.send_color("#000000", device=device)
    if not path:
        typer.echo("Error: Provide a mask path or use --clear")
        raise typer.Exit(1)
    return _display.load_mask(path, device=device)


@app.command("overlay")
def _cmd_overlay(
    dc_path: Annotated[str, typer.Argument(help="DC config or theme directory path")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
    send: Annotated[bool, typer.Option(
        "--send", "-s", help="Send rendered result to LCD",
    )] = False,
    output: Annotated[Optional[str], typer.Option(
        "--output", "-o", help="Save rendered image to file",
    )] = None,
) -> int:
    """Render overlay from DC config."""
    return _display.render_overlay(
        dc_path, device=device, send=send, output=output)


@app.command("theme-list")
def _cmd_theme_list(
    cloud: Annotated[bool, typer.Option(
        "--cloud", "-c", help="List cloud themes instead of local",
    )] = False,
    category: Annotated[Optional[str], typer.Option(
        "--category", help="Filter by category (a=Gallery, b=Tech, c=HUD, etc.)",
    )] = None,
) -> int:
    """List available themes."""
    return _theme.list_themes(cloud=cloud, category=category)


@app.command("theme-load")
def _cmd_theme_load(
    name: Annotated[str, typer.Argument(help="Theme name (from theme-list)")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Load a theme and send to LCD."""
    return _theme.load_theme(name, device=device)


@app.command("led-color")
def _cmd_led_color(
    hex_color: Annotated[str, typer.Argument(
        metavar="HEX", help="Hex color (e.g., ff0000 for red)",
    )],
) -> int:
    """Set LED static color."""
    return _led.set_color(hex_color)


@app.command("led-mode")
def _cmd_led_mode(
    mode: Annotated[str, typer.Argument(
        help="Effect: static, breathing, colorful, rainbow",
    )],
) -> int:
    """Set LED effect mode."""
    return _led.set_mode(mode)


@app.command("led-brightness")
def _cmd_led_brightness(
    level: Annotated[int, typer.Argument(help="Brightness 0-100")],
) -> int:
    """Set LED brightness."""
    return _led.set_led_brightness(level)


@app.command("led-off")
def _cmd_led_off() -> int:
    """Turn LEDs off."""
    return _led.led_off()


@app.command("led-sensor")
def _cmd_led_sensor(
    source: Annotated[str, typer.Argument(
        help="Sensor source: cpu or gpu",
    )],
) -> int:
    """Set LED sensor source for temp/load linked modes."""
    return _led.set_sensor_source(source)


@app.command("theme-save")
def _cmd_theme_save(
    name: Annotated[str, typer.Argument(help="Theme name")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
    video: Annotated[Optional[str], typer.Option(
        "--video", "-v", help="Video path for animated theme",
    )] = None,
) -> int:
    """Save current display as a custom theme."""
    return _theme.save_theme(name, device=device, video=video)


@app.command("theme-export")
def _cmd_theme_export(
    theme_name: Annotated[str, typer.Argument(help="Theme name to export")],
    output: Annotated[str, typer.Argument(help="Output .tr file path")],
) -> int:
    """Export a theme as .tr file."""
    return _theme.export_theme(theme_name, output)


@app.command("theme-import")
def _cmd_theme_import(
    file_path: Annotated[str, typer.Argument(help="Path to .tr file")],
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path",
    )] = None,
) -> int:
    """Import a theme from .tr file."""
    return _theme.import_theme(file_path, device=device)


@app.command("info")
def _cmd_info() -> int:
    """Show system metrics."""
    return _system.show_info()


@app.command("reset")
def _cmd_reset(
    device: Annotated[Optional[str], typer.Option(
        "--device", "-d", help="Device path (e.g., /dev/sg0)",
    )] = None,
) -> int:
    """Reset/reinitialize LCD device."""
    return _display.reset(device=device)


@app.command("setup-udev")
def _cmd_setup_udev(
    dry_run: Annotated[bool, typer.Option(
        "--dry-run", "-n", help="Print rules without installing",
    )] = False,
) -> int:
    """Install udev rules for LCD device access."""
    return _system.setup_udev(dry_run=dry_run)


@app.command("setup-selinux")
def _cmd_setup_selinux() -> int:
    """Install SELinux policy module for USB device access."""
    return _system.setup_selinux()


@app.command("setup-polkit")
def _cmd_setup_polkit() -> int:
    """Install polkit policy for passwordless dmidecode/smartctl."""
    return _system.setup_polkit()


@app.command("install-desktop")
def _cmd_install_desktop() -> int:
    """Install application menu entry and icon."""
    return _system.install_desktop()


@app.command("resume")
def _cmd_resume() -> int:
    """Send last-used theme to each detected device (headless)."""
    return _display.resume()


@app.command("uninstall")
def _cmd_uninstall(
    yes: Annotated[bool, typer.Option(
        "--yes", "-y", help="Skip confirmation prompts (for non-interactive use)",
    )] = False,
) -> int:
    """Remove all TRCC config, udev rules, and autostart files."""
    return _system.uninstall(yes=yes)


@app.command("hid-debug")
def _cmd_hid_debug(
    test_frame: Annotated[bool, typer.Option(
        "--test-frame", "-t", help="Send solid red test frame after handshake",
    )] = False,
) -> int:
    """HID handshake diagnostic (hex dump for bug reports)."""
    return _diag.hid_debug(test_frame=test_frame)


@app.command("led-debug")
def _cmd_led_debug(
    test_colors: Annotated[bool, typer.Option(
        "--test", "-t", help="Send test colors after handshake",
    )] = False,
) -> int:
    """Diagnose LED device (handshake, PM byte)."""
    return _diag.led_debug(test=test_colors)


@app.command("report")
def _cmd_report() -> int:
    """Generate full diagnostic report for bug reports."""
    return _system.report()


@app.command("doctor")
def _cmd_doctor() -> int:
    """Check dependencies, libraries, and permissions."""
    from trcc.adapters.infra.doctor import run_doctor
    return run_doctor()


@app.command("setup")
def _cmd_setup(
    yes: Annotated[bool, typer.Option(
        "--yes", "-y", help="Accept all defaults (non-interactive)",
    )] = False,
) -> int:
    """Interactive setup wizard — check deps, install packages, configure system."""
    return _system.run_setup(auto_yes=yes)


@app.command("setup-gui")
def _cmd_setup_gui() -> None:
    """Launch the setup wizard GUI."""
    from trcc.install.gui import main
    raise SystemExit(main())


@app.command("download")
def _cmd_download(
    pack: Annotated[Optional[str], typer.Argument(
        help="Theme pack name (e.g., themes-320x320 or themes-480)",
    )] = None,
    show_list: Annotated[bool, typer.Option(
        "--list", "-l", help="List available packs",
    )] = False,
    force: Annotated[bool, typer.Option(
        "--force", "-f", help="Force reinstall",
    )] = False,
    show_info: Annotated[bool, typer.Option(
        "--info", "-i", help="Show pack info",
    )] = False,
) -> int:
    """Download theme packs."""
    return _system.download_themes(
        pack=pack, show_list=show_list, force=force, show_info=show_info)


@app.command("serve")
def _cmd_serve(
    host: Annotated[str, typer.Option(
        "--host", "-H", help="Bind address (use 0.0.0.0 for LAN)",
    )] = "127.0.0.1",
    port: Annotated[int, typer.Option(
        "--port", "-p", help="Listen port",
    )] = 8080,
    token: Annotated[Optional[str], typer.Option(
        "--token", "-t", help="API token for auth",
    )] = None,
) -> int:
    """Start REST API server (requires trcc-linux[api])."""
    try:
        import uvicorn  # noqa: I001

        from trcc.api import app as api_app, configure_auth
        configure_auth(token)
        uvicorn.run(api_app, host=host, port=port)
        return 0
    except ImportError:
        print("REST API requires: pip install trcc-linux[api]")
        return 1


# =========================================================================
# Main entry point
# =========================================================================

def main():
    """Main CLI entry point (pyproject.toml console_scripts)."""
    try:
        result = app(standalone_mode=False)
        return result if isinstance(result, int) else 0
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0


# =========================================================================
# Backward-compat class stubs (for tests that import DeviceCommands, etc.)
# =========================================================================

class DeviceCommands:
    """Backward-compat stub — delegates to _device module functions."""
    detect = staticmethod(_device.detect)
    select = staticmethod(_device.select)
    _get_service = staticmethod(_device._get_service)
    _ensure_extracted = staticmethod(_device._ensure_extracted)
    _get_driver = staticmethod(_device._get_driver)
    _probe = staticmethod(_device._probe)
    _format = staticmethod(_device._format)


class DisplayCommands:
    """Backward-compat stub — delegates to _display module functions."""
    test = staticmethod(_display.test)
    send_image = staticmethod(_display.send_image)
    send_color = staticmethod(_display.send_color)
    play_video = staticmethod(_display.play_video)
    set_brightness = staticmethod(_display.set_brightness)
    set_rotation = staticmethod(_display.set_rotation)
    screencast = staticmethod(_display.screencast)
    load_mask = staticmethod(_display.load_mask)
    render_overlay = staticmethod(_display.render_overlay)
    reset = staticmethod(_display.reset)
    resume = staticmethod(_display.resume)


class ThemeCommands:
    """Backward-compat stub — delegates to _theme module functions."""
    list_themes = staticmethod(_theme.list_themes)
    load_theme = staticmethod(_theme.load_theme)
    save_theme = staticmethod(_theme.save_theme)
    export_theme = staticmethod(_theme.export_theme)
    import_theme = staticmethod(_theme.import_theme)


class LEDCommands:
    """Backward-compat stub — delegates to _led module functions."""
    _get_led_service = staticmethod(_led._get_led_service)
    set_color = staticmethod(_led.set_color)
    set_mode = staticmethod(_led.set_mode)
    set_led_brightness = staticmethod(_led.set_led_brightness)
    led_off = staticmethod(_led.led_off)
    set_sensor_source = staticmethod(_led.set_sensor_source)


class DiagCommands:
    """Backward-compat stub — delegates to _diag module functions."""
    _hex_dump = staticmethod(_diag._hex_dump)
    _hid_debug_lcd = staticmethod(_diag._hid_debug_lcd)
    _hid_debug_led = staticmethod(_diag._hid_debug_led)
    hid_debug = staticmethod(_diag.hid_debug)
    led_debug = staticmethod(_diag.led_debug)


class SystemCommands:
    """Backward-compat stub — delegates to _system module functions."""
    show_info = staticmethod(_system.show_info)
    setup_udev = staticmethod(_system.setup_udev)
    setup_selinux = staticmethod(_system.setup_selinux)
    setup_polkit = staticmethod(_system.setup_polkit)
    install_desktop = staticmethod(_system.install_desktop)
    uninstall = staticmethod(_system.uninstall)
    report = staticmethod(_system.report)
    download_themes = staticmethod(_system.download_themes)
    _confirm = staticmethod(_system._confirm)
    run_setup = staticmethod(_system.run_setup)


# =========================================================================
# Backward-compat function aliases (pyproject.toml entry points + tests)
# =========================================================================

# Entry points (pyproject.toml console_scripts)
detect = _device.detect
test_display = _display.test
select_device = _device.select

# Backward-compat for tests and external consumers
_probe_device = _device._probe
_format_device = _device._format
_ensure_extracted = _device._ensure_extracted
_get_driver = _device._get_driver
_get_service = _device._get_service
send_image = _display.send_image
send_color = _display.send_color
play_video = _display.play_video
reset_device = _display.reset
resume = _display.resume
show_info = _system.show_info
hid_debug = _diag.hid_debug
led_debug = _diag.led_debug
setup_udev = _system.setup_udev
install_desktop = _system.install_desktop
uninstall = _system.uninstall
report = _system.report
download_themes = _system.download_themes
run_setup = _system.run_setup
_hex_dump = _diag._hex_dump
_hid_debug_lcd = _diag._hid_debug_lcd
_hid_debug_led = _diag._hid_debug_led

# Display adjustments
set_brightness = _display.set_brightness
set_rotation = _display.set_rotation
screencast = _display.screencast
load_mask = _display.load_mask
render_overlay = _display.render_overlay

# Theme commands
list_themes = _theme.list_themes
load_theme = _theme.load_theme
save_theme = _theme.save_theme
export_theme = _theme.export_theme
import_theme = _theme.import_theme

# LED commands
led_color = _led.set_color
led_mode = _led.set_mode
led_brightness = _led.set_led_brightness
led_off = _led.led_off
led_sensor = _led.set_sensor_source
