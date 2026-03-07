"""LCD display CLI commands — thin print wrappers over LCDDevice.

LCDDevice lives in core/lcd_device.py (DIP). These CLI functions are
presentation-only adapters: connect, call device method, print result.

Blocking loops (video, screencast, test) remain here — terminal-only.
"""
from __future__ import annotations

import os
from pathlib import Path

from trcc.cli import _cli_handler, _device
from trcc.core.lcd_device import LCDDevice
from trcc.core.models import parse_hex_color as _parse_hex

# =========================================================================
# CLI presentation helpers
# =========================================================================

def _connect_or_fail(device: str | None = None) -> tuple[LCDDevice, int]:
    """Create device, connect. Returns (device, exit_code).

    When the GUI daemon is running and no explicit device path is given,
    returns an IPC proxy that routes all commands through the daemon.
    """
    if device is None:
        from trcc.ipc import IPCClient, IPCDisplayProxy
        if IPCClient.available():
            return IPCDisplayProxy(), 0  # type: ignore[return-value]
    lcd = LCDDevice()
    result = lcd.connect(device)
    if not result["success"]:
        print(result["error"])
        return lcd, 1
    return lcd, 0


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
                svc.send_pil(img, w, h)
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


def play_video(video_path, *, device=None, loop=True, duration=0,
               preview=False):
    """Play video/GIF/ZT on LCD device."""
    try:
        import time

        if not os.path.exists(video_path):
            print(f"Error: File not found: {video_path}")
            return 1

        from trcc.adapters.infra.media_player import ThemeZtDecoder, VideoDecoder
        from trcc.services import ImageService, MediaService

        svc = _device._get_service(device)
        if not svc.selected:
            print("No device found.")
            return 1

        dev = svc.selected
        w, h = dev.resolution

        media = MediaService(
            video_decoder_cls=VideoDecoder,
            zt_decoder_cls=ThemeZtDecoder,
        )
        media.set_target_size(w, h)
        if not media.load(Path(video_path)):
            print(f"Error: Failed to load video: {video_path}")
            return 1

        total = media._state.total_frames
        fps = media._state.fps
        print(f"Playing {video_path} ({total} frames, {fps:.0f}fps) "
              f"on {dev.path} [{w}x{h}]")
        if loop:
            print("Press Ctrl+C to stop.")

        media._state.loop = loop
        media.play()

        interval = media.frame_interval_ms / 1000.0
        start = time.monotonic()
        if preview:
            print('\033[2J', end='', flush=True)

        while media.is_playing:
            frame, should_send, progress = media.tick()
            if frame is None:
                break
            if should_send:
                svc.send_pil(frame, w, h)
            if preview and frame:
                print(ImageService.to_ansi_cursor_home(frame), flush=True)
            elif progress:
                pct, cur, total_t = progress
                print(f"\r  {cur} / {total_t} ({pct:.0f}%)",
                      end="", flush=True)
            if duration and (time.monotonic() - start) >= duration:
                break
            time.sleep(interval)

        print("\nDone.")
        return 0
    except KeyboardInterrupt:
        print("\nStopped.")
        return 0
    except Exception as e:
        print(f"Error playing video: {e}")
        return 1


def screencast(*, device=None, x=0, y=0, w=0, h=0, fps=10, preview=False):
    """Stream screen region to LCD. Ctrl+C to stop."""
    try:
        import time

        from PIL import ImageGrab

        from trcc.services import ImageService

        svc = _device._get_service(device)
        if not svc.selected:
            print("No device found.")
            return 1

        dev = svc.selected
        lcd_w, lcd_h = dev.resolution

        bbox = None
        if w > 0 and h > 0:
            bbox = (x, y, x + w, y + h)
            print(f"Capturing region ({x},{y}) {w}x{h} → {dev.path} [{lcd_w}x{lcd_h}]")
        else:
            print(f"Capturing full screen → {dev.path} [{lcd_w}x{lcd_h}]")

        print(f"Target: {fps} fps. Press Ctrl+C to stop.")

        interval = 1.0 / fps
        frames = 0
        if preview:
            print('\033[2J', end='', flush=True)

        while True:
            start = time.monotonic()
            img = ImageGrab.grab(bbox=bbox)
            img = ImageService.resize(img, lcd_w, lcd_h)
            svc.send_pil(img, lcd_w, lcd_h)
            frames += 1
            if preview:
                print(ImageService.to_ansi_cursor_home(img), flush=True)
            else:
                print(f"\r  Frames: {frames}", end="", flush=True)
            elapsed = time.monotonic() - start
            if elapsed < interval:
                time.sleep(interval - elapsed)

    except KeyboardInterrupt:
        print(f"\nStopped after {frames} frames.")
        return 0
    except ImportError:
        print("Error: Screen capture requires Pillow with ImageGrab support.")
        print("On Linux, install: pip install Pillow")
        return 1
    except Exception as e:
        print(f"\nError: {e}")
        return 1


# =========================================================================
# CLI functions — thin wrappers over LCDDevice capabilities
# =========================================================================

def _display_command(method: str, *args, device: str | None = None,
                     preview: bool = False, **kwargs) -> int:
    """Generic: connect LCD, call method on frame ops, print result."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    return _print_result(getattr(lcd.frame, method)(*args, **kwargs),
                         preview=preview)


@_cli_handler
def send_image(image_path, device=None, preview=False):
    """Send image to LCD."""
    return _display_command("send_image", image_path, device=device,
                            preview=preview)


@_cli_handler
def send_color(hex_color, device=None, preview=False):
    """Send solid color to LCD."""
    rgb = _parse_hex(hex_color)
    if not rgb:
        print("Error: Invalid hex color. Use format: ff0000")
        return 1
    return _display_command("send_color", *rgb, device=device, preview=preview)


@_cli_handler
def set_brightness(level, *, device=None):
    """Set display brightness level (1=25%, 2=50%, 3=100%)."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    assert lcd.settings is not None
    result = lcd.settings.set_brightness(level)
    if not result["success"]:
        print(f"Error: {result['error']}")
        print("  1 = 25%  (dim)")
        print("  2 = 50%  (medium)")
        print("  3 = 100% (full)")
        return 1
    print(result["message"])
    return 0


@_cli_handler
def set_rotation(degrees, *, device=None):
    """Set display rotation (0, 90, 180, 270)."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    assert lcd.settings is not None
    return _print_result(lcd.settings.set_rotation(degrees))


@_cli_handler
def set_split_mode(mode, *, device=None, preview=False):
    """Set split mode (Dynamic Island) for widescreen displays."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    assert lcd.settings is not None
    return _print_result(lcd.settings.set_split_mode(mode), preview=preview)


@_cli_handler
def load_mask(mask_path, *, device=None, preview=False):
    """Load mask overlay from file/directory and send composited image."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    return _print_result(lcd.load_mask_standalone(mask_path), preview=preview)


@_cli_handler
def render_overlay(dc_path, *, device=None, send=False, output=None,
                   preview=False):
    """Render overlay from DC config file."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    result = lcd.render_overlay_from_dc(dc_path, send=send, output=output)
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
def reset(device=None, *, preview=False):
    """Reset/reinitialize the LCD device."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    print(f"  Device: {lcd.device_path}")
    return _print_result(lcd.frame.reset(), preview=preview)


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
def resume():
    """Send last-used theme to each detected device (headless, no GUI)."""
    import time

    from trcc.adapters.device.detector import DeviceDetector
    from trcc.adapters.device.factory import DeviceProtocolFactory
    from trcc.adapters.device.led import probe_led_model
    from trcc.conf import Settings
    from trcc.services import DeviceService, ImageService

    svc = DeviceService(
        detect_fn=DeviceDetector.detect,
        probe_led_fn=probe_led_model,
        get_protocol=DeviceProtocolFactory.get_protocol,
        get_protocol_info=DeviceProtocolFactory.get_protocol_info,
    )

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

        key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
        cfg = Settings.get_device_config(key)
        theme_path = cfg.get("theme_path")

        if not theme_path:
            print(f"  [{dev.product}] No saved theme, skipping")
            continue

        image_path = None
        if os.path.isdir(theme_path):
            candidate = os.path.join(theme_path, "00.png")
            if os.path.exists(candidate):
                image_path = candidate
        elif os.path.isfile(theme_path):
            image_path = theme_path

        if not image_path:
            print(f"  [{dev.product}] Theme not found: {theme_path}")
            continue

        try:
            w, h = dev.resolution
            img = ImageService.open_and_resize(image_path, w, h)

            brightness_level = cfg.get("brightness_level", 3)
            brightness_pct = {1: 25, 2: 50, 3: 100}.get(brightness_level, 100)
            img = ImageService.apply_brightness(img, brightness_pct)

            rotation = cfg.get("rotation", 0)
            img = ImageService.apply_rotation(img, rotation)

            svc.select(dev)
            svc.send_pil(img, w, h)
            print(f"  [{dev.product}] Sent: {os.path.basename(theme_path)}")
            sent += 1
        except Exception as e:
            print(f"  [{dev.product}] Error: {e}")

    if sent == 0:
        print("No themes were sent. Use the GUI to set a theme first.")
        return 1

    print(f"Resumed {sent} device(s).")
    return 0
