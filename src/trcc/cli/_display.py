"""LCD display frame sending commands.

DisplayDispatcher is the single authority for LCD frame operations.
GUI and API import DisplayDispatcher directly; CLI functions are thin
presentation wrappers (print + exit code).

Two construction modes:
  - **Full** (GUI/API): ``DisplayDispatcher(display_svc=...)`` — wraps a
    DisplayService that already owns DeviceService, OverlayService, MediaService.
  - **Lite** (CLI direct): ``DisplayDispatcher()`` then ``connect()`` — creates a
    bare DeviceService for image/color/reset commands only.

Blocking loops (video, screencast, test) remain as standalone CLI functions
because they're inherently terminal-oriented.
"""
from __future__ import annotations

import logging
import os
from typing import Any

from trcc.cli import _cli_handler, _device
from trcc.core.models import parse_hex_color as _parse_hex

log = logging.getLogger(__name__)

# =========================================================================
# DisplayDispatcher — programmatic API (returns data, never prints)
# =========================================================================

class DisplayDispatcher:
    """LCD command dispatcher — single authority for all LCD operations.

    Thin wrapper around DisplayService (Approach B / SOLID).
    DisplayService owns all business logic; this class formats result dicts.

    Returns result dicts with 'success', 'message', 'error', and optional
    data ('image', 'resolution', 'device_path').  CLI wraps with print/exit.
    GUI and API import and use directly.
    """

    def __init__(self, device_svc: Any = None, *,
                 display_svc: Any = None):
        self._display_svc: Any = display_svc
        self._device_svc: Any = device_svc or (
            display_svc.devices if display_svc else None)

    # ── Properties ────────────────────────────────────────────────────

    @property
    def connected(self) -> bool:
        if self._device_svc and self._device_svc.selected:
            return True
        return False

    @property
    def device(self) -> Any:
        return self._device_svc.selected if self._device_svc else None

    @property
    def _dev(self) -> Any:
        """Return selected device, assert not None (call after connect())."""
        dev = self.device
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
        return self._device_svc

    @property
    def display_service(self) -> Any:
        return self._display_svc

    # ── Connection (CLI lite mode) ────────────────────────────────────

    def connect(self, device: str | None = None) -> dict:
        """Detect device, handshake, resolve resolution.

        Used by CLI direct-connect mode. GUI/API pass DisplayService
        to __init__ instead.

        Returns: {"success": bool, "resolution": (w, h), "device_path": str}
        """
        self._device_svc = _device._get_service(device)
        if not self._device_svc.selected:
            return {"success": False, "error": "No device found"}
        dev = self._dev
        return {
            "success": True,
            "resolution": dev.resolution,
            "device_path": dev.path,
        }

    # ── Image operations (work in both lite and full modes) ──────────

    def send_image(self, image_path: str) -> dict:
        """Send image file to LCD."""
        if not os.path.exists(image_path):
            return {"success": False, "error": f"File not found: {image_path}"}

        from PIL import Image

        from trcc.services import ImageService

        dev = self._dev
        w, h = dev.resolution
        img = Image.open(image_path).convert('RGB')
        img = ImageService.resize(img, w, h)
        self._device_svc.send_pil(img, w, h)
        return {
            "success": True,
            "image": img,
            "message": f"Sent {image_path} to {dev.path}",
        }

    def send_color(self, r: int, g: int, b: int) -> dict:
        """Send solid color to LCD."""
        from trcc.services import ImageService

        dev = self._dev
        w, h = dev.resolution
        img = ImageService.solid_color(r, g, b, w, h)
        self._device_svc.send_pil(img, w, h)
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
        self._device_svc.send_pil(img, w, h)
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
        """Set display brightness (1=25%, 2=50%, 3=100%). Persists to config.

        When DisplayService is available, also re-renders the current frame
        with the new brightness applied.
        """
        level_map = {1: 25, 2: 50, 3: 100}
        if level not in level_map:
            return {"success": False, "error": "Brightness level must be 1, 2, or 3"}

        self._persist_setting('brightness_level', level)

        image = None
        if self._display_svc:
            image = self._display_svc.set_brightness(level_map[level])

        result: dict[str, Any] = {
            "success": True,
            "message": f"Brightness set to L{level} ({level_map[level]}%) on {self._dev.path}",
        }
        if image is not None:
            result["image"] = image
        return result

    def set_rotation(self, degrees: int) -> dict:
        """Set display rotation (0, 90, 180, 270). Persists to config."""
        if degrees not in (0, 90, 180, 270):
            return {"success": False, "error": "Rotation must be 0, 90, 180, or 270"}

        self._persist_setting('rotation', degrees)

        image = None
        if self._display_svc:
            image = self._display_svc.set_rotation(degrees)

        result: dict[str, Any] = {
            "success": True,
            "message": f"Rotation set to {degrees}° on {self._dev.path}",
        }
        if image is not None:
            result["image"] = image
        return result

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

        image = None
        if self._display_svc:
            image = self._display_svc.set_split_mode(mode)

        state = "off" if mode == 0 else f"style {mode}"
        result: dict[str, Any] = {
            "success": True,
            "message": f"Split mode set to {state} on {self._dev.path}",
        }
        if warning:
            result["warning"] = warning
        if image is not None:
            result["image"] = image
        return result

    # ── Overlay operations (CLI lite — standalone overlay) ────────────

    def load_mask(self, mask_path: str) -> dict:
        """Load mask overlay and send composited image."""
        from pathlib import Path

        from PIL import Image

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
        mask_img = Image.open(mask_file).convert('RGBA')
        overlay.set_mask(mask_img)

        bg = ImageService.solid_color(0, 0, 0, w, h)
        overlay.set_background(bg)
        overlay.enabled = True
        result_img = overlay.render()

        self._device_svc.send_pil(result_img, w, h)
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

        dev = self._dev if self._device_svc else None
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
            import numpy as np
            from PIL import Image as PILImage
            save_img = PILImage.fromarray(result_img) if isinstance(result_img, np.ndarray) else result_img
            save_img.save(output)
            messages.append(f"Saved overlay render to {output}")
        if send and dev:
            self._device_svc.send_pil(result_img, w, h)
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

    # ── Video control (delegates to DisplayService) ───────────────────

    def load_theme(self, theme: Any) -> dict:
        """Load a theme (local or cloud). Requires DisplayService."""
        if not self._display_svc:
            return {"success": False, "error": "No display service (CLI lite mode)"}

        from trcc.core.models import ThemeType
        if hasattr(theme, 'theme_type') and theme.theme_type == ThemeType.CLOUD:
            result = self._display_svc.load_cloud_theme(theme)
        else:
            result = self._display_svc.load_local_theme(theme)

        return {
            "success": True,
            "image": result.get('image'),
            "is_animated": result.get('is_animated', False),
            "message": result.get('status', 'Theme loaded'),
        }

    def play_video(self) -> dict:
        """Start/resume video playback."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.media.play()
        return {"success": True, "message": "Video playing"}

    def pause_video(self) -> dict:
        """Pause video playback."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.media.pause()
        return {"success": True, "message": "Video paused"}

    def stop_video(self) -> dict:
        """Stop video playback."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.media.stop()
        return {"success": True, "message": "Video stopped"}

    def video_tick(self) -> dict:
        """Advance one video frame. Returns frame data."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}

        result = self._display_svc.video_tick()
        if result is None:
            return {"success": True, "frame": None}

        return {
            "success": True,
            "frame": result.get('frame'),
            "send": result.get('send'),
            "progress": result.get('progress'),
        }

    def is_video_playing(self) -> bool:
        """Check if video is currently playing."""
        if not self._display_svc:
            return False
        return self._display_svc.is_video_playing()

    def get_video_interval(self) -> int:
        """Get video frame interval in ms for timer setup."""
        if not self._display_svc:
            return 62  # ~16fps default
        return self._display_svc.get_video_interval()

    # ── Overlay control (delegates to DisplayService.overlay) ─────────

    def enable_overlay(self, enabled: bool) -> dict:
        """Enable or disable overlay rendering."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.overlay.enabled = enabled
        state = "enabled" if enabled else "disabled"
        return {"success": True, "message": f"Overlay {state}"}

    def set_overlay_config(self, config: dict) -> dict:
        """Set overlay element configuration."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.overlay.set_config(config)
        elements = len(config) if config else 0
        return {"success": True, "message": f"Overlay config set ({elements} elements)"}

    def update_metrics(self, metrics: Any) -> dict:
        """Push hardware metrics into overlay for rendering."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.overlay.update_metrics(metrics)
        return {"success": True}

    def render_current_overlay(self) -> dict:
        """Force-render overlay on current image. Returns rendered image."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        image = self._display_svc.render_overlay()
        return {"success": True, "image": image}

    # ── State queries ─────────────────────────────────────────────────

    def status(self) -> dict:
        """Full device/display state dict."""
        result: dict[str, Any] = {"success": True, "connected": self.connected}

        dev = self.device
        if dev:
            result["device_path"] = dev.path
            result["resolution"] = list(dev.resolution)
            result["protocol"] = dev.protocol

        if self._display_svc:
            result["rotation"] = self._display_svc.rotation
            result["brightness"] = self._display_svc.brightness
            result["split_mode"] = self._display_svc.split_mode
            result["overlay_enabled"] = self._display_svc.overlay.enabled
            result["video_playing"] = self._display_svc.is_video_playing()
            if self._display_svc.current_theme_path:
                result["theme"] = str(self._display_svc.current_theme_path)

        return result

    def get_current_frame(self) -> dict:
        """Return the current LCD frame (numpy array)."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        image = self._display_svc.current_image
        if image is None:
            return {"success": False, "error": "No frame available"}
        return {"success": True, "image": image}

    # ── Device operations ─────────────────────────────────────────────

    def detect(self) -> dict:
        """Detect LCD devices. Returns raw DetectedDevice objects.

        Returns raw adapter-level objects so CLI formatting (probe, udev
        checks, scsi_device paths) works without additional imports.
        """
        from trcc.adapters.device.detector import DeviceDetector

        raw = DeviceDetector.detect()
        if not raw:
            return {"success": False, "error": "No compatible device found"}
        return {
            "success": True,
            "devices": raw,
            "message": f"Found {len(raw)} device(s)",
        }

    def select_device(self, device_info: Any) -> dict:
        """Select a specific device for operations."""
        if not self._device_svc:
            return {"success": False, "error": "No device service"}
        self._device_svc.select(device_info)
        return {
            "success": True,
            "device_path": device_info.path if hasattr(device_info, 'path') else str(device_info),
            "message": f"Selected device: {device_info}",
        }

    def set_resolution(self, width: int, height: int) -> dict:
        """Change LCD resolution."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.set_resolution(width, height)
        return {
            "success": True,
            "resolution": [width, height],
            "message": f"Resolution set to {width}x{height}",
        }

    # ── Theme operations ──────────────────────────────────────────────

    def select_theme(self, theme: Any) -> dict:
        """Select and load a theme (delegates to load_theme)."""
        return self.load_theme(theme)

    def list_themes(self, resolution: tuple[int, int] | None = None,
                    category: str = '') -> dict:
        """List available themes for a resolution.

        Works in both full mode (with DisplayService) and lite mode (CLI).
        Resolves directories from settings when no display service.
        """
        from trcc.adapters.infra.data_repository import DataManager
        from trcc.conf import settings
        from trcc.services import ThemeService

        # Determine resolution
        if resolution:
            w, h = resolution
        elif self._display_svc:
            w, h = self._display_svc.lcd_size
        else:
            w, h = settings.width or 320, settings.height or 320

        # Ensure archives extracted
        DataManager.ensure_all(w, h)
        settings._resolve_paths()

        local: list[Any] = []
        cloud: list[Any] = []

        if self._display_svc:
            if self._display_svc.local_dir:
                local = ThemeService.discover_local(
                    self._display_svc.local_dir, (w, h))
            if self._display_svc.web_dir:
                cloud = ThemeService.discover_cloud(
                    self._display_svc.web_dir, category)
        else:
            td = settings.theme_dir
            if td and td.exists():
                local = ThemeService.discover_local(td.path, (w, h))
            web_dir = settings.web_dir
            if web_dir and web_dir.exists():
                cloud = ThemeService.discover_cloud(web_dir, category)

        return {
            "success": True,
            "local": local,
            "cloud": cloud,
            "resolution": [w, h],
            "message": f"{len(local)} local, {len(cloud)} cloud themes",
        }

    def save_theme(self, name: str, data_dir: Any) -> dict:
        """Save current config as a custom theme."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        from pathlib import Path
        ok, msg = self._display_svc.save_theme(name, Path(data_dir))
        return {"success": ok, "message": msg}

    def export_config(self, path: str) -> dict:
        """Export current theme as .tr or JSON file."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        from pathlib import Path
        ok, msg = self._display_svc.export_config(Path(path))
        return {"success": ok, "message": msg}

    def import_config(self, path: str, data_dir: Any) -> dict:
        """Import theme from .tr or JSON file."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        from pathlib import Path
        ok, msg = self._display_svc.import_config(Path(path), Path(data_dir))
        return {"success": ok, "message": msg}

    # ── CLI-oriented theme operations (lite mode capable) ─────────────

    def load_theme_by_name(self, name: str) -> dict:
        """Find a theme by name, load its background, and send to LCD.

        Discovers themes, finds by exact or partial name match, loads
        static background, applies device config adjustments, sends.
        For animated themes, returns info to use video playback instead.
        """
        themes_result = self.list_themes()
        local = themes_result.get("local", [])

        match = next((t for t in local if t.name == name), None)
        if not match:
            match = next((t for t in local if name.lower() in t.name.lower()), None)
        if not match:
            return {"success": False, "error": f"Theme not found: {name}"}

        if match.is_animated and match.animation_path:
            return {
                "success": True,
                "is_animated": True,
                "animation_path": str(match.animation_path),
                "message": f"Theme '{match.name}' is animated — use 'trcc video {match.animation_path}'",
            }

        if not match.background_path or not match.background_path.exists():
            return {"success": False, "error": f"Theme '{match.name}' has no background image"}

        from PIL import Image

        from trcc.conf import Settings
        from trcc.services import ImageService

        dev = self._dev
        w, h = dev.resolution
        img = Image.open(match.background_path).convert('RGB')
        img = ImageService.resize(img, w, h)

        key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
        cfg = Settings.get_device_config(key)
        brightness = {1: 25, 2: 50, 3: 100}.get(cfg.get('brightness_level', 3), 100)
        rotation = cfg.get('rotation', 0)
        img = ImageService.apply_brightness(img, brightness)
        img = ImageService.apply_rotation(img, rotation)

        self._device_svc.send_pil(img, w, h)
        Settings.save_device_setting(key, 'theme_path', str(match.path))
        return {
            "success": True,
            "image": img,
            "theme_name": match.name,
            "message": f"Loaded '{match.name}' → {dev.path}",
        }

    def save_custom_theme(self, name: str, video: str | None = None) -> dict:
        """Save current display state as a custom theme (CLI).

        Reads the last-used theme background from device config, saves
        it as a new custom theme with the given name.
        """
        from pathlib import Path

        from trcc.adapters.infra.data_repository import USER_DATA_DIR
        from trcc.conf import Settings
        from trcc.services import ThemeService

        dev = self._dev
        w, h = dev.resolution

        key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
        cfg = Settings.get_device_config(key)
        theme_path = cfg.get('theme_path')

        bg = None
        if theme_path:
            from trcc.adapters.infra.data_repository import ThemeDir as TDir
            td = TDir(theme_path)
            if td.bg.exists():
                from PIL import Image
                bg = Image.open(td.bg).convert('RGB')
                bg = bg.resize((w, h), Image.Resampling.LANCZOS)

        if not bg:
            return {"success": False, "error": "No current theme to save. Load a theme first."}

        video_path = Path(video) if video else None
        data_dir = Path(USER_DATA_DIR)
        ok, msg = ThemeService.save(
            name, data_dir, (w, h),
            background=bg, overlay_config={},
            video_path=video_path,
            current_theme_path=Path(theme_path) if theme_path else None,
        )
        return {"success": ok, "message": msg}

    def export_theme_by_name(self, name: str, output_path: str) -> dict:
        """Find a theme by name and export as .tr file."""
        from pathlib import Path

        from trcc.services import ThemeService

        themes_result = self.list_themes()
        local = themes_result.get("local", [])

        match = next((t for t in local if t.name == name), None)
        if not match:
            match = next((t for t in local if name.lower() in t.name.lower()), None)
        if not match or not match.path:
            return {"success": False, "error": f"Theme not found: {name}"}

        ok, msg = ThemeService.export_tr(match.path, Path(output_path))
        return {"success": ok, "message": msg}

    def import_theme_file(self, file_path: str) -> dict:
        """Import a theme from .tr file."""
        from pathlib import Path

        from trcc.adapters.infra.data_repository import USER_DATA_DIR
        from trcc.services import ThemeService

        dev = self._dev
        w, h = dev.resolution
        data_dir = Path(USER_DATA_DIR)

        ok, result = ThemeService.import_tr(Path(file_path), data_dir, (w, h))
        if ok and not isinstance(result, str):
            return {"success": True, "theme_name": result.name,
                    "message": f"Imported: {result.name}"}
        return {"success": ok,
                "message": result if isinstance(result, str) else "Import failed"}

    # ── Video extended ────────────────────────────────────────────────

    def play_pause(self) -> dict:
        """Toggle video play/pause."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        media = self._display_svc.media
        if media.is_playing:
            media.pause()
            return {"success": True, "message": "Video paused"}
        media.play()
        return {"success": True, "message": "Video playing"}

    def seek_video(self, percent: float) -> dict:
        """Seek video to a percentage position."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.media.seek(percent)
        return {"success": True, "message": f"Seeked to {percent:.0f}%"}

    def set_video_fit_mode(self, mode: str) -> dict:
        """Set video fit mode (fill, width, height)."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        image = self._display_svc.set_video_fit_mode(mode)
        result: dict[str, Any] = {
            "success": True,
            "message": f"Video fit mode set to '{mode}'",
        }
        if image is not None:
            result["image"] = image
        return result

    def load_video(self, path: str) -> dict:
        """Load a video file for playback."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        from pathlib import Path
        success = self._display_svc.media.load(Path(path))
        if not success:
            return {"success": False, "error": f"Failed to load video: {path}"}
        return {
            "success": True,
            "fps": self._display_svc.media.state.fps,
            "total_frames": self._display_svc.media.state.total_frames,
            "message": f"Loaded video: {Path(path).name}",
        }

    def play_video_standalone(self, path: str, *, loop: bool = True) -> dict:
        """Load video for standalone CLI playback.

        Creates a MediaService internally for CLI blocking loops.
        Returns media reference and playback params for the tick loop.
        """
        if not os.path.exists(path):
            return {"success": False, "error": f"File not found: {path}"}

        from pathlib import Path as P

        from trcc.services import MediaService

        dev = self._dev
        w, h = dev.resolution

        media = MediaService()
        media.set_target_size(w, h)
        if not media.load(P(path)):
            return {"success": False, "error": f"Failed to load video: {path}"}

        media._state.loop = loop
        media.play()

        return {
            "success": True,
            "media": media,
            "fps": media._state.fps,
            "total_frames": media._state.total_frames,
            "interval": media.frame_interval_ms / 1000.0,
            "message": (f"Playing {path} ({media._state.total_frames} frames, "
                        f"{media._state.fps:.0f}fps) on {dev.path} [{w}x{h}]"),
        }

    # ── Overlay extended ──────────────────────────────────────────────

    def set_overlay_temp_unit(self, unit: int) -> dict:
        """Set overlay temperature unit (0=Celsius, 1=Fahrenheit)."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.overlay.set_temp_unit(unit)
        label = "Fahrenheit" if unit else "Celsius"
        return {"success": True, "message": f"Temp unit set to {label}"}

    def set_overlay_background(self, image: Any) -> dict:
        """Set overlay background image."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.overlay.set_background(image)
        return {"success": True, "message": "Overlay background set"}

    def set_overlay_mask_visible(self, visible: bool) -> dict:
        """Toggle overlay mask visibility."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.overlay.set_mask_visible(visible)
        state = "visible" if visible else "hidden"
        return {"success": True, "message": f"Overlay mask {state}"}

    def set_overlay_theme_mask(self, image: Any = None,
                                position: tuple[int, int] | None = None) -> dict:
        """Set overlay theme mask image and optional position."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        self._display_svc.overlay.set_theme_mask(image, position)
        return {"success": True, "message": "Theme mask updated"}

    def render_overlay_and_preview(self) -> dict:
        """Force-render overlay and return the preview image."""
        if not self._display_svc:
            return {"success": False, "error": "No display service"}
        image = self._display_svc.render_overlay()
        return {"success": True, "image": image}

    # ── Frame send ────────────────────────────────────────────────────

    def send_frame(self, image: Any) -> dict:
        """Send an arbitrary frame (numpy/PIL) to the LCD device."""
        if not self._device_svc or not self._device_svc.selected:
            return {"success": False, "error": "No device connected"}
        dev = self._device_svc.selected
        w, h = dev.resolution
        self._device_svc.send_pil(image, w, h)
        return {"success": True, "message": f"Frame sent to {dev.path}"}

    def cleanup(self) -> dict:
        """Cleanup resources on shutdown."""
        if self._display_svc:
            self._display_svc.cleanup()
        return {"success": True, "message": "Cleanup complete"}

    def resume_all(self) -> dict:
        """Resume last-used themes on all detected devices (boot/headless).

        Iterates all detected SCSI devices, handshakes for resolution,
        loads saved theme background with adjustments, sends to device.
        Waits up to 20s for USB devices to appear (boot timing).
        """
        import time

        from trcc.conf import Settings
        from trcc.services import DeviceService, ImageService

        if not self._device_svc:
            self._device_svc = DeviceService()

        devices: list = []
        messages: list[str] = []
        for attempt in range(10):
            devices = self._device_svc.detect()
            if devices:
                break
            messages.append(f"Waiting for device... ({attempt + 1}/10)")
            time.sleep(2)

        if not devices:
            return {"success": False,
                    "error": "No compatible TRCC device detected.",
                    "messages": []}

        sent = 0
        for dev in devices:
            if dev.protocol != "scsi":
                continue

            _device.discover_resolution(dev)
            if dev.resolution == (0, 0):
                continue

            key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
            cfg = Settings.get_device_config(key)
            theme_path = cfg.get("theme_path")

            if not theme_path:
                messages.append(f"[{dev.product}] No saved theme, skipping")
                continue

            image_path = None
            if os.path.isdir(theme_path):
                candidate = os.path.join(theme_path, "00.png")
                if os.path.exists(candidate):
                    image_path = candidate
            elif os.path.isfile(theme_path):
                image_path = theme_path

            if not image_path:
                messages.append(f"[{dev.product}] Theme not found: {theme_path}")
                continue

            try:
                from PIL import Image

                img = Image.open(image_path).convert("RGB")
                w, h = dev.resolution
                img = ImageService.resize(img, w, h)

                brightness_level = cfg.get("brightness_level", 3)
                brightness_pct = {1: 25, 2: 50, 3: 100}.get(brightness_level, 100)
                img = ImageService.apply_brightness(img, brightness_pct)

                rotation = cfg.get("rotation", 0)
                img = ImageService.apply_rotation(img, rotation)

                self._device_svc.select(dev)
                self._device_svc.send_pil(img, w, h)
                messages.append(
                    f"[{dev.product}] Sent: {os.path.basename(theme_path)}")
                sent += 1
            except Exception as e:
                messages.append(f"[{dev.product}] Error: {e}")

        return {
            "success": sent > 0,
            "sent": sent,
            "messages": messages,
            "message": f"Resumed {sent} device(s)." if sent
                       else "No themes were sent.",
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
    if preview and result.get("image") is not None:
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

        lcd, rc = _connect_or_fail(device)
        if rc:
            return 1

        colors = [
            ((255, 0, 0), "Red"),
            ((0, 255, 0), "Green"),
            ((0, 0, 255), "Blue"),
            ((255, 255, 0), "Yellow"),
            ((255, 0, 255), "Magenta"),
            ((0, 255, 255), "Cyan"),
            ((255, 255, 255), "White"),
        ]

        print(f"Testing display on {lcd.device_path}...")

        while True:
            for (r, g, b), name in colors:
                print(f"  Displaying: {name}")
                result = lcd.send_color(r, g, b)
                if preview and result.get("image") is not None:
                    from trcc.services import ImageService
                    print(ImageService.to_ansi(result["image"]))
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

        lcd, rc = _connect_or_fail(device)
        if rc:
            return 1

        result = lcd.play_video_standalone(str(video_path), loop=loop)
        if not result["success"]:
            print(f"Error: {result['error']}")
            return 1

        media = result["media"]
        interval = result["interval"]

        print(result["message"])
        if loop:
            print("Press Ctrl+C to stop.")

        start = time.monotonic()
        if preview:
            print('\033[2J', end='', flush=True)  # clear screen

        while media.is_playing:
            frame, should_send, progress = media.tick()
            if frame is None:
                break
            if should_send:
                lcd.send_frame(frame)
            if preview and frame is not None:
                from trcc.services import ImageService
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

        lcd, rc = _connect_or_fail(device)
        if rc:
            return 1

        dev = lcd.device
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
            lcd.send_frame(img)
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
    if preview and result.get("image") is not None:
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
def display_status(*, device=None):
    """Show display status (device, resolution, overlay, video, brightness)."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    result = lcd.status()
    if not result.get("connected"):
        print("No device connected.")
        return 0
    print(f"  Device:   {result.get('device_path', '?')}")
    print(f"  Protocol: {result.get('protocol', '?')}")
    res = result.get('resolution', [0, 0])
    print(f"  Resolution: {res[0]}x{res[1]}")
    if 'rotation' in result:
        print(f"  Rotation: {result['rotation']}°")
    if 'brightness' in result:
        print(f"  Brightness: {result['brightness']}%")
    if 'split_mode' in result:
        sm = result['split_mode']
        print(f"  Split mode: {'off' if sm == 0 else f'style {sm}'}")
    if 'overlay_enabled' in result:
        print(f"  Overlay: {'enabled' if result['overlay_enabled'] else 'disabled'}")
    if 'video_playing' in result:
        print(f"  Video: {'playing' if result['video_playing'] else 'stopped'}")
    if 'theme' in result:
        print(f"  Theme: {result['theme']}")
    return 0


@_cli_handler
def video_play(*, device=None):
    """Tell running daemon to start/resume video playback."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    return _print_result(lcd.play_video())


@_cli_handler
def video_pause(*, device=None):
    """Tell running daemon to pause video playback."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    return _print_result(lcd.pause_video())


@_cli_handler
def video_stop(*, device=None):
    """Tell running daemon to stop video playback."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    return _print_result(lcd.stop_video())


@_cli_handler
def overlay_toggle(enabled: bool, *, device=None):
    """Enable or disable overlay rendering on daemon."""
    lcd, rc = _connect_or_fail(device)
    if rc:
        return rc
    return _print_result(lcd.enable_overlay(enabled))


@_cli_handler
def resume():
    """Send last-used theme to each detected device (headless, no GUI)."""
    lcd = DisplayDispatcher()
    result = lcd.resume_all()

    for msg in result.get("messages", []):
        print(f"  {msg}")

    if not result["success"]:
        error = result.get("error") or result.get("message", "No themes were sent.")
        print(error)
        if result.get("sent", 0) == 0 and not result.get("error"):
            print("Use the GUI to set a theme first.")
        return 1

    print(result["message"])
    return 0
