"""LCD display CLI commands — thin wrappers over Device.

Presentation-only: builder injected by _cmd_* boundary functions, call method, print result.
"""
from __future__ import annotations

import os

from trcc.cli import _cli_handler, _device
from trcc.core.models import parse_hex_color as _parse_hex

# =========================================================================
# CLI presentation helpers
# =========================================================================

def _connect_or_fail(device: str | None = None) -> int:
    """Connect LCD via os_bus. Returns exit code (0 = success).

    DI chain: os_bus.dispatch(InitPlatformCommand) → renderer wired
              → os_bus.dispatch(DiscoverDevicesCommand) → scan()
              → _wire_bus() → lcd_bus ready.
    """
    from trcc.core.app import TrccApp
    from trcc.core.commands.initialize import DiscoverDevicesCommand
    from trcc.core.instance import find_active
    from trcc.ipc import create_lcd_proxy
    app = TrccApp.get()
    app.set_ipc_handlers(find_active, create_lcd_proxy)
    result = app.os_bus.dispatch(DiscoverDevicesCommand(path=device))
    if not result.success or not app.has_lcd:
        error = result.payload.get("error", "No LCD device found.")
        print(error)
        print("Run 'trcc report' to diagnose.")
        return 1
    return 0


def _print_result(result: dict, *, preview: bool = False) -> int:
    """Print result message + optional ANSI preview. Returns exit code."""
    if not result["success"]:
        print(f"Error: {result.get('error', 'Unknown error')}")
        return 1
    if result.get("warning"):
        print(f"Warning: {result['warning']}")
    print(result["message"])
    if preview and result.get("image"):
        from trcc.services import ImageService
        print(ImageService.to_ansi(result["image"]))
    return 0


# =========================================================================
# CLI functions — blocking loops (terminal-only)
# =========================================================================

def test(device=None, loop=False, preview=False):
    """Test display with color cycle."""
    try:
        import time

        from trcc.services import ImageService

        svc = _device._get_service(device)
        if not svc.selected:
            print("No device found.")
            return 1

        dev = svc.selected
        if dev.protocol == "led":
            print(f"{dev.path} is an LED controller with a segment display — use 'trcc led' commands.")
            return 0
        w, h = dev.resolution

        colors = [
            ((255, 0, 0), "Red"),
            ((0, 255, 0), "Green"),
            ((0, 0, 255), "Blue"),
            ((255, 255, 0), "Yellow"),
            ((255, 0, 255), "Magenta"),
            ((0, 255, 255), "Cyan"),
            ((255, 255, 255), "White"),
        ]

        print(f"Testing display on {dev.path}...")

        while True:
            for (r, g, b), name in colors:
                print(f"  Displaying: {name}")
                img = ImageService.solid_color(r, g, b, w, h)
                svc.send_frame(img, w, h)
                if preview:
                    print(ImageService.to_ansi(img))
                time.sleep(1)

            if not loop:
                break

        print("Test complete!")
        return 0
    except KeyboardInterrupt:
        print("\nTest interrupted.")
        return 0
    except Exception as e:
        print(f"Error testing display: {e}")
        return 1


def play_video(builder, video_path, *, device=None, loop=True, duration=0,
               preview=False, metrics=None, mask=None,
               font_size=14, color='ffffff', font='Microsoft YaHei',
               font_style='regular', temp_unit=0, time_format=0,
               date_format=0):
    """Play video/GIF/ZT on LCD device with optional overlay."""
    try:
        if not os.path.exists(video_path):
            print(f"Error: File not found: {video_path}")
            return 1

        from trcc.core.app import TrccApp
        from trcc.core.models import build_overlay_config

        rc = _connect_or_fail(device)
        if rc:
            return rc
        lcd = TrccApp.get().lcd_device
        assert lcd is not None

        dev_path = lcd.device_path
        w, h = lcd.lcd_size

        # Build overlay config from --metric specs
        overlay_config = None
        if metrics:
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

        # Metrics supplier for live overlay updates
        metrics_fn = None
        if overlay_config:
            from trcc.cli import _ensure_system
            from trcc.services.system import get_all_metrics
            _ensure_system(builder)
            metrics_fn = get_all_metrics

        print(f"Playing {video_path} on {dev_path} [{w}x{h}]")
        if overlay_config:
            print(f"  Overlay: {len(overlay_config)} elements")
        if mask:
            print(f"  Mask: {mask}")
        if loop:
            print("Press Ctrl+C to stop.")

        if preview:
            print('\033[2J', end='', flush=True)

        def _on_frame(img):
            svc = lcd._device_svc
            if svc:
                svc.send_frame(img, w, h)
            if preview:
                from trcc.services import ImageService
                print(ImageService.to_ansi_cursor_home(img), flush=True)

        def _on_progress(pct, cur, total_t):
            if not preview:
                print(f"\r  {cur} / {total_t} ({pct:.0f}%)",
                      end="", flush=True)

        result = lcd.play_video_loop(
            video_path,
            overlay_config=overlay_config,
            mask_path=mask,
            metrics_fn=metrics_fn,
            on_frame=_on_frame,
            on_progress=_on_progress,
            loop=loop,
            duration=duration,
        )

        if result["success"]:
            print(f"\n{result['message']}.")
            return 0
        print(f"Error: {result.get('error', 'Unknown error')}")
        return 1

    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as e:
        print(f"Error playing video: {e}")
        return 1


def screencast(builder, *, device=None, x=0, y=0, w=0, h=0, fps=10, preview=False):
    """Stream screen region to LCD via ffmpeg. Ctrl+C to stop."""
    import subprocess

    from PySide6.QtGui import QImage

    from trcc.services import ImageService

    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    dev = svc.selected
    lcd_w, lcd_h = dev.resolution

    capture = builder.build_setup().get_screencast_capture(x, y, w, h)
    if capture is None:
        print("Error: Screencast not supported on this platform.")
        return 1
    fmt, inp, region_args = capture

    cmd = [
        'ffmpeg', '-hide_banner', '-loglevel', 'error',
        '-f', fmt, '-framerate', str(fps),
        *region_args,
        '-i', inp,
        '-vf', f'scale={lcd_w}:{lcd_h}',
        '-f', 'rawvideo', '-pix_fmt', 'rgb24',
        'pipe:1',
    ]
    frame_size = lcd_w * lcd_h * 3

    if w and h:
        print(f"Capturing region ({x},{y}) {w}x{h} → {dev.path} [{lcd_w}x{lcd_h}]")
    else:
        print(f"Capturing full screen → {dev.path} [{lcd_w}x{lcd_h}]")
    print(f"Target: {fps} fps. Press Ctrl+C to stop.")

    if preview:
        print('\033[2J', end='', flush=True)

    frames = 0
    proc = None
    try:
        proc = subprocess.Popen(cmd, stdout=subprocess.PIPE,
                                stderr=subprocess.DEVNULL)
        assert proc.stdout is not None
        while True:
            raw = proc.stdout.read(frame_size)
            if len(raw) < frame_size:
                break
            # Detach from raw buffer immediately — send_frame may hold a ref
            qimg = QImage(raw, lcd_w, lcd_h, lcd_w * 3,
                          QImage.Format.Format_RGB888).copy()
            svc.send_frame(qimg, lcd_w, lcd_h)
            frames += 1
            if preview:
                print(ImageService.to_ansi_cursor_home(qimg), flush=True)
            else:
                print(f"\r  Frames: {frames}", end="", flush=True)
    except KeyboardInterrupt:
        pass
    except FileNotFoundError:
        print("Error: ffmpeg not found. Install ffmpeg to use screencast.")
        return 1
    except Exception as e:
        print(f"\nError: {e}")
        return 1
    finally:
        if proc is not None:
            proc.terminate()
            try:
                proc.wait(timeout=2)
            except subprocess.TimeoutExpired:
                proc.kill()
    print(f"\nStopped after {frames} frames.")
    return 0


# =========================================================================
# CLI functions — thin wrappers over LCDDevice capabilities
# =========================================================================

def _display_command(builder, method: str, *args, device: str | None = None,
                     preview: bool = False, **kwargs) -> int:
    """Generic: connect LCD, call method on frame ops, print result."""
    rc = _connect_or_fail(device)
    if rc:
        return rc
    from trcc.core.app import TrccApp
    lcd = TrccApp.get().lcd_device
    assert lcd is not None
    return _print_result(getattr(lcd.frame, method)(*args, **kwargs),
                         preview=preview)


@_cli_handler
def send_image(builder, image_path, device=None, preview=False):
    """Send image to LCD."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.lcd import SendImageCommand
    rc = _connect_or_fail(device)
    if rc:
        return rc
    result = TrccApp.get().lcd_bus.dispatch(SendImageCommand(image_path=image_path))
    return _print_result(result.payload, preview=preview)


@_cli_handler
def send_color(builder, hex_color, device=None, preview=False):
    """Send solid color to LCD."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.lcd import SendColorCommand
    rgb = _parse_hex(hex_color)
    if not rgb:
        print("Error: Invalid hex color. Use format: ff0000")
        return 1
    rc = _connect_or_fail(device)
    if rc:
        return rc
    r, g, b = rgb
    result = TrccApp.get().lcd_bus.dispatch(SendColorCommand(r=r, g=g, b=b))
    return _print_result(result.payload, preview=preview)


@_cli_handler
def set_brightness(builder, level, *, device=None):
    """Set display brightness level (1=25%, 2=50%, 3=100%)."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.lcd import SetBrightnessCommand
    rc = _connect_or_fail(device)
    if rc:
        return rc
    try:
        result = TrccApp.get().lcd_bus.dispatch(SetBrightnessCommand(level=level))
    except ValueError:
        result = None
    if not result or not result.success:
        print(f"Error: {getattr(result, 'payload', {}).get('error', 'invalid brightness level')}")
        print("  1 = 25%  (dim)")
        print("  2 = 50%  (medium)")
        print("  3 = 100% (full)")
        return 1
    print(result.payload["message"])
    return 0


@_cli_handler
def set_rotation(builder, degrees, *, device=None):
    """Set display rotation (0, 90, 180, 270)."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.lcd import SetRotationCommand
    rc = _connect_or_fail(device)
    if rc:
        return rc
    result = TrccApp.get().lcd_bus.dispatch(SetRotationCommand(degrees=degrees))
    return _print_result(result.payload)


@_cli_handler
def set_split_mode(builder, mode, *, device=None, preview=False):
    """Set split mode (Dynamic Island) for widescreen displays."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.lcd import SetSplitModeCommand
    rc = _connect_or_fail(device)
    if rc:
        return rc
    result = TrccApp.get().lcd_bus.dispatch(SetSplitModeCommand(mode=mode))
    return _print_result(result.payload, preview=preview)


@_cli_handler
def load_mask(builder, mask_path, *, device=None, preview=False):
    """Load mask overlay from file/directory and send composited image."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.lcd import LoadMaskCommand
    rc = _connect_or_fail(device)
    if rc:
        return rc
    result = TrccApp.get().lcd_bus.dispatch(LoadMaskCommand(mask_path=mask_path))
    return _print_result(result.payload, preview=preview)


@_cli_handler
def render_overlay(builder, dc_path, *, device=None, send=False, output=None,
                   preview=False):
    """Render overlay from DC config file."""
    from trcc.cli import _ensure_system
    from trcc.core.app import TrccApp
    from trcc.services.system import get_all_metrics

    rc = _connect_or_fail(device)
    if rc:
        return rc
    _ensure_system(builder)
    lcd = TrccApp.get().lcd_device
    assert lcd is not None
    result = lcd.render_overlay_from_dc(
        dc_path, send=send, output=output, metrics=get_all_metrics())
    if not result["success"]:
        print(f"Error: {result['error']}")
        return 1
    if result["message"]:
        print(result["message"])
    if preview and result.get("image"):
        from trcc.services import ImageService
        print(ImageService.to_ansi(result["image"]))
    if not output and not send and not preview:
        opts = result.get("display_opts", {})
        for k, v in opts.items():
            print(f"  {k}: {v}")
    return 0


@_cli_handler
def reset(builder, device=None, *, preview=False):
    """Reset/reinitialize the LCD device."""
    from trcc.core.app import TrccApp
    from trcc.core.commands.lcd import ResetDisplayCommand
    rc = _connect_or_fail(device)
    if rc:
        return rc
    lcd = TrccApp.get().lcd_device
    assert lcd is not None
    print(f"  Device: {lcd.device_path}")
    result = TrccApp.get().lcd_bus.dispatch(ResetDisplayCommand())
    return _print_result(result.payload, preview=preview)


@_cli_handler
def video_status(*, device=None):
    """Show current video playback status."""
    svc = _device._get_service(device)
    if not svc.selected:
        print("No device found.")
        return 1

    print("Video playback is controlled by the running 'trcc video' process.")
    print("Use Ctrl+C in the video process to stop playback.")
    print("For interactive control, use the GUI: trcc gui")
    return 0


@_cli_handler
def resume(builder):
    """Send last-used theme to each detected device (headless, no GUI)."""
    import time

    svc = builder.build_device_svc()

    devices: list = []
    for attempt in range(10):
        devices = svc.detect()
        if devices:
            break
        print(f"Waiting for device... ({attempt + 1}/10)")
        time.sleep(2)

    if not devices:
        print("No compatible TRCC device detected.")
        return 1

    sent = 0
    for dev in devices:
        if dev.protocol != "scsi":
            continue

        from trcc.cli._device import discover_resolution
        discover_resolution(dev)
        if dev.resolution == (0, 0):
            continue

        try:
            svc.select(dev)
            lcd = builder.lcd_from_service(svc)
            # Apply hardware resolution so the display pipeline encodes correctly.
            # dev.resolution is set by discover_resolution() (USB handshake result).
            w, h = dev.resolution
            if w and h:
                lcd.set_resolution(w, h)
            lcd.restore_device_settings()
            result = lcd.load_last_theme()
            if not result.get("success"):
                msg = result.get("error", "Unknown error")
                print(f"  [{dev.product}] {msg}")
                continue
            img = result["image"]
            lcd.send(img)
            print(f"  [{dev.product}] Sent")
            sent += 1
        except Exception as e:
            print(f"  [{dev.product}] Error: {e}")

    if sent == 0:
        print("No themes were sent. Use the GUI to set a theme first.")
        return 1

    print(f"Resumed {sent} device(s).")
    return 0
