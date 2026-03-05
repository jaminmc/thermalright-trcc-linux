"""LCD display frame sending commands.

DisplayDispatcher is the single authority for LCD frame operations.
GUI and API import DisplayDispatcher directly; CLI functions are thin
presentation wrappers (print + exit code).

Blocking loops (video, screencast, test) remain as standalone CLI functions
because they're inherently terminal-oriented.
"""
from __future__ import annotations

import os
from typing import Any

from trcc.cli import _cli_handler, _device
from trcc.core.models import parse_hex_color as _parse_hex

# =========================================================================
# DisplayDispatcher — programmatic API (returns data, never prints)
# =========================================================================

class DisplayDispatcher:
    """LCD command dispatcher — single authority for all LCD operations.

    Returns result dicts with 'success', 'message', 'error', and optional
    data ('image', 'resolution', 'device_path').  CLI wraps with print/exit.
    GUI and API import and use directly.
    """

    def __init__(self, device_svc: Any = None):
        self._svc = device_svc

    # ── Properties ────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        return self._svc is not None and self._svc.selected is not None

    @property
    def device(self) -> Any:
        return self._svc.selected if self._svc else None

    @property
    def _dev(self) -> Any:
        """Return selected device, assert not None (call after connect())."""
        dev = self._svc.selected if self._svc else None
        assert dev is not None, "connect() must succeed before calling methods"
        return dev

    @property
    def resolution(self) -> tuple[int, int]:
        dev = self.device
        return dev.resolution if dev else (0, 0)

    @property
    def device_path(self) -> str | None:
        dev = self.device
        return dev.path if dev else None

    @property
    def service(self) -> Any:
        return self._svc

    # ── Connection ────────────────────────────────────────────────────

    def connect(self, device: str | None = None) -> dict:
        """Detect device, handshake, resolve resolution.

        Returns: {"success": bool, "resolution": (w, h), "device_path": str}
        """
        self._svc = _device._get_service(device)
        if not self._svc.selected:
            return {"success": False, "error": "No device found"}
        dev = self._dev
        return {
            "success": True,
            "resolution": dev.resolution,
            "device_path": dev.path,
        }

    # ── Image operations ──────────────────────────────────────────────

    def send_image(self, image_path: str) -> dict:
        """Send image file to LCD. Returns rendered PIL image."""
        if not os.path.exists(image_path):
            return {"success": False, "error": f"File not found: {image_path}"}

        from trcc.services import ImageService

        dev = self._dev
        w, h = dev.resolution
        img = ImageService.open_and_resize(image_path, w, h)
        self._svc.send_pil(img, w, h)
        return {
            "success": True,
            "image": img,
            "message": f"Sent {image_path} to {dev.path}",
        }

    def send_color(self, r: int, g: int, b: int) -> dict:
        """Send solid color to LCD. Returns rendered PIL image."""
        from trcc.services import ImageService

        dev = self._dev
        w, h = dev.resolution
        img = ImageService.solid_color(r, g, b, w, h)
        self._svc.send_pil(img, w, h)
        return {
            "success": True,
            "image": img,
            "message": f"Sent color #{r:02x}{g:02x}{b:02x} to {dev.path}",
        }

    def reset(self) -> dict:
        """Reset device by sending solid red frame."""
        from trcc.services import ImageService

        dev = self._dev
        w, h = dev.resolution
        img = ImageService.solid_color(255, 0, 0, w, h)
        self._svc.send_pil(img, w, h)
        return {
            "success": True,
            "image": img,
            "message": f"Device reset — displaying RED on {dev.path}",
        }

    # ── Display settings ──────────────────────────────────────────────

    def _persist_setting(self, field: str, value: object) -> None:
        """Save a single device setting to config."""
        from trcc.conf import Settings

        dev = self._dev
        key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
        Settings.save_device_setting(key, field, value)

    def set_brightness(self, level: int) -> dict:
        """Set display brightness (1=25%, 2=50%, 3=100%). Persists to config."""
        level_map = {1: 25, 2: 50, 3: 100}
        if level not in level_map:
            return {"success": False, "error": "Brightness level must be 1, 2, or 3"}

        self._persist_setting('brightness_level', level)
        return {
            "success": True,
            "message": f"Brightness set to L{level} ({level_map[level]}%) on {self._dev.path}",
        }

    def set_rotation(self, degrees: int) -> dict:
        """Set display rotation (0, 90, 180, 270). Persists to config."""
        if degrees not in (0, 90, 180, 270):
            return {"success": False, "error": "Rotation must be 0, 90, 180, or 270"}

        self._persist_setting('rotation', degrees)
        return {
            "success": True,
            "message": f"Rotation set to {degrees}° on {self._dev.path}",
        }

    def set_split_mode(self, mode: int) -> dict:
        """Set split mode (0=off, 1-3=Dynamic Island). Persists to config."""
        if mode not in (0, 1, 2, 3):
            return {"success": False, "error": "Split mode must be 0, 1, 2, or 3"}

        from trcc.core.models import SPLIT_MODE_RESOLUTIONS

        w, h = self._dev.resolution
        warning = None
        if (w, h) not in SPLIT_MODE_RESOLUTIONS:
            warning = f"Split mode only supports widescreen ({w}x{h} is not 1600x720)"

        self._persist_setting('split_mode', mode)
        state = "off" if mode == 0 else f"style {mode}"
        result: dict[str, Any] = {
            "success": True,
            "message": f"Split mode set to {state} on {self._dev.path}",
        }
        if warning:
            result["warning"] = warning
        return result

    # ── Overlay operations ────────────────────────────────────────────

    def load_mask(self, mask_path: str) -> dict:
        """Load mask overlay and send composited image."""
        from pathlib import Path

        from trcc.services import ImageService, OverlayService

        if not os.path.exists(mask_path):
            return {"success": False, "error": f"Path not found: {mask_path}"}

        dev = self._dev
        w, h = dev.resolution

        p = Path(mask_path)
        if p.is_dir():
            mask_file = p / "01.png"
            if not mask_file.exists():
                mask_file = next(p.glob("*.png"), None)
            if not mask_file:
                return {"success": False, "error": f"No PNG files in {mask_path}"}
        else:
            mask_file = p

        overlay = OverlayService(w, h)
        r = ImageService._r()
        mask_img = r.convert_to_rgba(r.open_image(mask_file))
        overlay.set_mask(mask_img)

        bg = ImageService.solid_color(0, 0, 0, w, h)
        overlay.set_background(bg)
        overlay.enabled = True
        result_img = overlay.render()

        self._svc.send_pil(result_img, w, h)
        return {
            "success": True,
            "image": result_img,
            "message": f"Sent mask {mask_file.name} to {dev.path}",
        }

    def render_overlay(self, dc_path: str, *, send: bool = False,
                       output: str | None = None) -> dict:
        """Render overlay from DC config. Optionally send to device or save."""
        from pathlib import Path

        from trcc.services import ImageService, OverlayService
        from trcc.services.system import get_all_metrics

        if not os.path.exists(dc_path):
            return {"success": False, "error": f"Path not found: {dc_path}"}

        dev = self._dev if self._svc else None
        w, h = dev.resolution if dev else (320, 320)

        overlay = OverlayService(w, h)

        p = Path(dc_path)
        dc_file = p / "config1.dc" if p.is_dir() else p
        display_opts = overlay.load_from_dc(dc_file)

        metrics = get_all_metrics()
        overlay.update_metrics(metrics)
        overlay.enabled = True

        bg = ImageService.solid_color(0, 0, 0, w, h)
        overlay.set_background(bg)
        result_img = overlay.render()

        messages = []
        if output:
            result_img.save(output)
            messages.append(f"Saved overlay render to {output}")
        if send and dev:
            self._svc.send_pil(result_img, w, h)
            messages.append(f"Sent overlay to {dev.path}")

        elements = len(overlay.config) if overlay.config else 0
        return {
            "success": True,
            "image": result_img,
            "elements": elements,
            "display_opts": display_opts or {},
            "message": "; ".join(messages) if messages else
                       f"Overlay config loaded: {elements} elements ({w}x{h})",
        }


# =========================================================================
# CLI presentation helpers
# =========================================================================

def _connect_or_fail(device: str | None = None) -> tuple[DisplayDispatcher, int]:
    """Create dispatcher, connect. Returns (dispatcher, exit_code).

    When the GUI daemon is running and no explicit device path is given,
    returns an IPC proxy that routes all commands through the daemon.
    """
    if device is None:
        from trcc.ipc import IPCClient, IPCDisplayProxy
        if IPCClient.available():
            return IPCDisplayProxy(), 0  # type: ignore[return-value]
    lcd = DisplayDispatcher()
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
        from pathlib import Path

        if not os.path.exists(video_path):
            print(f"Error: File not found: {video_path}")
            return 1

        from trcc.services import ImageService, MediaService

        svc = _device._get_service(device)
        if not svc.selected:
            print("No device found.")
            return 1

        dev = svc.selected
        w, h = dev.resolution

        media = MediaService()
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
            print('\033[2J', end='', flush=True)  # clear screen

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

        # Determine capture region
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
# CLI functions — thin wrappers around DisplayDispatcher
# =========================================================================

def _display_command(method: str, *args, device: str | None = None,
                     preview: bool = False, **kwargs) -> int:
    """Generic: connect LCD, call dispatcher method, print result."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    return _print_result(getattr(lcd, method)(*args, **kwargs), preview=preview)


@_cli_handler
def send_image(image_path, device=None, preview=False):
    """Send image to LCD."""
    return _display_command("send_image", image_path, device=device, preview=preview)


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
    result = lcd.set_brightness(level)
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
    return _display_command("set_rotation", degrees, device=device)


@_cli_handler
def set_split_mode(mode, *, device=None, preview=False):
    """Set split mode (Dynamic Island) for widescreen displays."""
    return _display_command("set_split_mode", mode, device=device, preview=preview)


@_cli_handler
def load_mask(mask_path, *, device=None, preview=False):
    """Load mask overlay from file/directory and send composited image."""
    return _display_command("load_mask", mask_path, device=device, preview=preview)


@_cli_handler
def render_overlay(dc_path, *, device=None, send=False, output=None,
                   preview=False):
    """Render overlay from DC config file."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    result = lcd.render_overlay(dc_path, send=send, output=output)
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
    return _print_result(lcd.reset(), preview=preview)


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

    from trcc.conf import Settings
    from trcc.services import DeviceService, ImageService

    svc = DeviceService()

    # Wait for USB devices to appear (they may not be ready at boot)
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

        # Discover resolution via handshake
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

        # Find the image to send (00.png in theme dir, or direct file)
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

            # Apply brightness
            brightness_level = cfg.get("brightness_level", 3)
            brightness_pct = {1: 25, 2: 50, 3: 100}.get(brightness_level, 100)
            img = ImageService.apply_brightness(img, brightness_pct)

            # Apply rotation
            rotation = cfg.get("rotation", 0)
            img = ImageService.apply_rotation(img, rotation)

            # Send via service (auto byte-order)
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
