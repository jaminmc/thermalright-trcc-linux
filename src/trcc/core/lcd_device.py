"""LCDDevice — concrete Device for LCD displays.

Extends Device ABC. All display operations (frame, video, overlay, theme,
settings) are methods directly on LCDDevice. Delegates to services internally.

CLI, GUI, and API all consume this directly (DIP — core/, not adapter/).
"""
from __future__ import annotations

import logging
import os
from pathlib import Path
from typing import Any

from .ports import Device

log = logging.getLogger(__name__)



class LCDDevice(Device):
    """LCD device — all display operations in one class.

    Delegates to services (DeviceService, DisplayService, ThemeService,
    OverlayService, MediaService). Backward-compatible accessors
    (lcd.frame, lcd.video, lcd.overlay, lcd.theme, lcd.settings)
    all point to self.

    Construction:
        lcd = LCDDevice()
        lcd.connect()
        lcd.send_image("pic.png")

    Or with pre-built services (GUI):
        lcd = LCDDevice(device_svc=svc, display_svc=disp, theme_svc=theme)
    """

    def __init__(
        self,
        device_svc: Any = None,
        display_svc: Any = None,
        theme_svc: Any = None,
        renderer: Any = None,
    ) -> None:
        self._device_svc = device_svc
        self._display_svc = display_svc
        self._theme_svc = theme_svc
        self._renderer = renderer

        # All capability accessors point to self — methods are on LCDDevice
        self.theme: LCDDevice = self  # type: ignore[assignment]
        self.frame: LCDDevice = self  # type: ignore[assignment]
        self.video: LCDDevice = self  # type: ignore[assignment]
        self.overlay: LCDDevice = self  # type: ignore[assignment]
        self.settings: LCDDevice = self  # type: ignore[assignment]

    def _build_services(self, device_svc: Any) -> None:
        """Wire up all services from a DeviceService."""
        from ..services import (
            DisplayService,
            MediaService,
            OverlayService,
            ThemeService,
        )
        from ..services.image import ImageService

        self._device_svc = device_svc
        self._renderer = self._renderer or ImageService._r()
        overlay_svc = OverlayService(renderer=self._renderer)
        media_svc = MediaService()
        self._display_svc = DisplayService(device_svc, overlay_svc, media_svc)
        self._theme_svc = ThemeService()

    # ── Device ABC ─────────────────────────────────────────────────

    def connect(self, detected: Any = None) -> dict:
        """Connect to LCD device. Handshakes, fills DeviceInfo from models.

        Args:
            detected: DetectedDevice, device_path str, or None for auto-detect.

        Returns:
            {"success": bool, "resolution": (w, h), "device_path": str}
        """
        from ..services import DeviceService

        device_path = None
        if isinstance(detected, str):
            device_path = detected
        elif detected is not None:
            device_path = getattr(detected, 'scsi_device', None) or \
                          getattr(detected, 'path', None)

        svc = DeviceService()
        svc.scan_and_select(device_path)
        if not svc.selected:
            return {"success": False, "error": "No LCD device found"}

        self._build_services(svc)
        dev = svc.selected
        return {
            "success": True,
            "resolution": dev.resolution,
            "device_path": dev.path,
        }

    @property
    def connected(self) -> bool:
        return (self._device_svc is not None
                and self._device_svc.selected is not None)

    @property
    def device_info(self) -> Any:
        return self._device_svc.selected if self._device_svc else None

    def cleanup(self) -> None:
        if self._display_svc:
            self._display_svc.cleanup()

    # ── LCD-specific properties ────────────────────────────────────

    @property
    def lcd_size(self) -> tuple[int, int]:
        if self._display_svc:
            return (self._display_svc.lcd_width, self._display_svc.lcd_height)
        return (0, 0)

    @property
    def resolution(self) -> tuple[int, int]:
        return self.lcd_size

    @property
    def device_path(self) -> str | None:
        dev = self.device_info
        return dev.path if dev else None

    @property
    def current_image(self) -> Any:
        return self._display_svc.current_image if self._display_svc else None

    @current_image.setter
    def current_image(self, value: Any) -> None:
        if self._display_svc:
            self._display_svc.current_image = value

    @property
    def current_theme_path(self) -> Any:
        return self._display_svc.current_theme_path if self._display_svc else None

    @property
    def auto_send(self) -> bool:
        return self._display_svc.auto_send if self._display_svc else False

    @auto_send.setter
    def auto_send(self, value: bool) -> None:
        if self._display_svc:
            self._display_svc.auto_send = value

    @property
    def device_service(self) -> Any:
        """Direct DeviceService access (for IPC frame capture wiring)."""
        return self._device_svc

    @property
    def overlay_service(self) -> Any:
        """Direct OverlayService access (for flash_skip_index etc.)."""
        return self._display_svc.overlay if self._display_svc else None

    # ── Connection helpers ─────────────────────────────────────────

    def detect_devices(self) -> dict:
        if not self._device_svc:
            return {"success": False, "error": "Not connected"}
        devices = self._device_svc.detect()
        return {
            "success": True, "devices": devices, "count": len(devices),
            "message": f"Found {len(devices)} device(s)",
        }

    def select_device(self, device: Any) -> dict:
        if not self._device_svc:
            return {"success": False, "error": "Not connected"}
        self._device_svc.select(device)
        return {"success": True, "device": device,
                "message": f"Selected: {device.path}"}

    # ── Standalone operations (CLI overlay/mask without GUI) ──────

    def render_overlay_from_dc(self, dc_path: str, *, send: bool = False,
                               output: str | None = None) -> dict:
        """Render overlay from DC config file (CLI standalone)."""
        from ..services import ImageService, OverlayService
        from ..services.system import get_all_metrics

        if not os.path.exists(dc_path):
            return {"success": False, "error": f"Path not found: {dc_path}"}

        w, h = self.resolution if self.connected else (320, 320)
        overlay = OverlayService(w, h, renderer=self._renderer)
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
        if send and self.connected:
            self.send(result_img)
            messages.append(f"Sent overlay to {self.device_path}")

        elements = len(overlay.config) if overlay.config else 0
        return {
            "success": True,
            "image": result_img,
            "elements": elements,
            "display_opts": display_opts or {},
            "message": "; ".join(messages) if messages else
                       f"Overlay config loaded: {elements} elements ({w}x{h})",
        }

    def load_mask_standalone(self, mask_path: str) -> dict:
        """Load mask overlay and send composited image.

        Used by both CLI and GUI. When display service exists (GUI),
        uses current theme background and existing overlay. When
        standalone (CLI), creates fresh overlay with black background.
        """
        from ..services import ImageService, OverlayService

        if not os.path.exists(mask_path):
            return {"success": False, "error": f"Path not found: {mask_path}"}

        w, h = self.resolution
        p = Path(mask_path)
        if p.is_dir():
            mask_file = p / "01.png"
            if not mask_file.exists():
                mask_file = next(p.glob("*.png"), None)
            if not mask_file:
                return {"success": False,
                        "error": f"No PNG files in {mask_path}"}
        else:
            mask_file = p

        r = ImageService._r()
        mask_img = r.convert_to_rgba(r.open_image(mask_file))

        # Parse mask position from DC file (C# stores center coords)
        mask_w, mask_h = r.surface_size(mask_img)
        dc_path = (p if p.is_dir() else p.parent) / 'config1.dc'
        from ..services.theme import ThemeService
        position = ThemeService._parse_mask_position(
            dc_path, mask_w, mask_h, w, h)

        # Use existing overlay service (GUI) or create fresh one (CLI)
        if self._display_svc:
            ovl = self._display_svc.overlay
            ovl.set_theme_mask(None)
            ovl.set_mask(mask_img, position)
            ovl.enabled = True
            # Use current theme bg, fall back to black
            bg = self._display_svc._clean_background or \
                self._display_svc.current_image or \
                ImageService.solid_color(0, 0, 0, w, h)
            self._display_svc.current_image = bg
            # Invalidate video cache (old mask baked in)
            self._display_svc._cache = None
            result_img = self._display_svc.render_overlay()
        else:
            ovl = OverlayService(w, h, renderer=self._renderer)
            ovl.set_mask(mask_img, position)
            bg = ImageService.solid_color(0, 0, 0, w, h)
            ovl.set_background(bg)
            ovl.enabled = True
            result_img = ovl.render()

        if self.connected:
            self.send(result_img)
        return {
            "success": True,
            "image": result_img,
            "message": f"Sent mask {mask_file.name} to {self.device_path}",
        }

    # ── Frame ops (encode/send to hardware) ─────────────────────

    def send_image(self, image_path: str) -> dict:
        if not os.path.exists(image_path):
            return {"success": False, "error": f"File not found: {image_path}"}
        from ..services import ImageService
        w, h = self.lcd_size
        img = ImageService.open_and_resize(image_path, w, h)
        self._device_svc.send_pil(img, w, h)
        return {"success": True, "image": img, "message": f"Sent {image_path}"}

    def send_color(self, r: int, g: int, b: int) -> dict:
        from ..services import ImageService
        w, h = self.lcd_size
        img = ImageService.solid_color(r, g, b, w, h)
        self._device_svc.send_pil(img, w, h)
        return {"success": True, "image": img,
                "message": f"Sent color #{r:02x}{g:02x}{b:02x}"}

    def send(self, image: Any) -> dict:
        """Encode and async-send image to LCD device."""
        if not self._device_svc.selected:
            return {"success": False, "error": "No device selected"}
        w, h = self.lcd_size
        self._device_svc.send_pil_async(image, w, h)
        return {"success": True}

    def send_async(self, image: Any, width: int, height: int) -> None:
        if self._device_svc.is_busy:
            return
        self._device_svc.send_pil_async(image, width, height)

    def load_image(self, path: Any) -> dict:
        image = self._display_svc.load_image_file(Path(path))
        if image:
            return {"success": True, "image": image,
                    "message": f"Loaded: {Path(path).name}"}
        return {"success": False, "error": f"Failed to load: {path}"}

    def reset(self) -> dict:
        from ..services import ImageService
        w, h = self.lcd_size
        img = ImageService.solid_color(255, 0, 0, w, h)
        self._device_svc.send_pil(img, w, h)
        return {"success": True, "image": img, "message": "Device reset — RED"}

    # ── Display settings (brightness/rotation/split) ─────────────

    def _persist(self, field: str, value: object) -> None:
        from ..conf import Settings
        dev = self._device_svc.selected if self._device_svc else None
        if dev:
            key = Settings.device_config_key(dev.device_index, dev.vid, dev.pid)
            Settings.save_device_setting(key, field, value)

    def set_brightness(self, level: int) -> dict:
        if level in (1, 2, 3):
            percent = {1: 25, 2: 50, 3: 100}[level]
        elif 0 <= level <= 100:
            percent = level
        else:
            return {"success": False,
                    "error": "Brightness: 1-3 (level) or 0-100 (percent)"}
        image = self._display_svc.set_brightness(percent)
        self._persist('brightness_level', level)
        return {"success": True, "image": image,
                "message": f"Brightness set to {percent}%"}

    def set_rotation(self, degrees: int) -> dict:
        if degrees not in (0, 90, 180, 270):
            return {"success": False,
                    "error": "Rotation must be 0, 90, 180, or 270"}
        image = self._display_svc.set_rotation(degrees)
        self._persist('rotation', degrees)
        return {"success": True, "image": image,
                "message": f"Rotation set to {degrees}°"}

    def set_split_mode(self, mode: int) -> dict:
        if mode not in (0, 1, 2, 3):
            return {"success": False,
                    "error": "Split mode must be 0, 1, 2, or 3"}
        image = self._display_svc.set_split_mode(mode)
        self._persist('split_mode', mode)
        return {"success": True, "image": image,
                "message": f"Split mode: {'off' if mode == 0 else f'style {mode}'}"}

    def set_resolution(self, width: int, height: int) -> dict:
        self._display_svc.set_resolution(width, height)
        self._theme_svc.set_directories(
            local_dir=self._display_svc.local_dir,
            web_dir=self._display_svc.web_dir,
            masks_dir=self._display_svc.masks_dir,
        )
        self._display_svc.media.set_target_size(width, height)
        self._display_svc.overlay.set_resolution(width, height)
        if width and height:
            self._theme_svc.load_local_themes((width, height))
        return {"success": True, "resolution": (width, height),
                "message": f"Resolution: {width}x{height}"}

    # ── Theme ops (loading, saving, import/export) ─────────────

    def select(self, theme: Any) -> dict:
        """Select and load a theme (local or cloud)."""
        from .models import ThemeType

        self._theme_svc.select(theme)
        if not theme:
            return {"success": False, "error": "No theme provided"}

        if theme.theme_type == ThemeType.CLOUD:
            result = self._display_svc.load_cloud_theme(theme)
        else:
            result = self._display_svc.load_local_theme(theme)

        image = result.get('image')
        is_animated = result.get('is_animated', False)

        return {
            "success": True,
            "image": image,
            "is_animated": is_animated,
            "interval": self._display_svc.get_video_interval() if is_animated else 0,
            "status": result.get('status', ''),
            "message": f"Theme: {theme.name}" if hasattr(theme, 'name') else "Theme loaded",
        }

    def load_local(self, resolution: tuple[int, int]) -> dict:
        themes = self._theme_svc.load_local_themes(resolution)
        return {"success": True, "themes": themes, "count": len(themes)}

    def save(self, name: str, data_dir: Any) -> dict:
        ok, msg = self._display_svc.save_theme(name, Path(data_dir))
        return {"success": ok, "message": msg}

    def export_config(self, path: Any) -> dict:
        ok, msg = self._display_svc.export_config(Path(path))
        return {"success": ok, "message": msg}

    def import_config(self, path: Any, data_dir: Any) -> dict:
        ok, msg = self._display_svc.import_config(Path(path), Path(data_dir))
        return {"success": ok, "message": msg}

    # ── Video playback ──────────────────────────────────────────

    def load(self, path: Any) -> dict:
        """Load video/GIF for playback."""
        success = self._display_svc.media.load(Path(path))
        if success:
            return {
                "success": True,
                "state": self._display_svc.media.state,
                "message": f"Loaded: {Path(path).name}",
            }
        return {"success": False, "error": f"Failed to load: {path}"}

    def play(self) -> dict:
        self._display_svc.media.play()
        return {"success": True, "state": "playing", "message": "Playing"}

    def stop(self) -> dict:
        self._display_svc.media.stop()
        return {"success": True, "state": "stopped", "message": "Stopped"}

    def pause(self) -> dict:
        self._display_svc.media.toggle()
        playing = self._display_svc.media.is_playing
        return {
            "success": True,
            "state": "playing" if playing else "paused",
            "message": "Playing" if playing else "Paused",
        }

    def seek(self, percent: float) -> dict:
        self._display_svc.media.seek(percent)
        return {"success": True, "message": f"Seek: {percent:.0%}"}

    def tick(self) -> dict | None:
        return self._display_svc.video_tick()

    def set_fit_mode(self, mode: str) -> dict:
        image = self._display_svc.set_video_fit_mode(mode)
        return {"success": True, "image": image, "message": f"Fit mode: {mode}"}

    @property
    def interval(self) -> int:
        return self._display_svc.get_video_interval()

    @property
    def has_frames(self) -> bool:
        return self._display_svc.media.has_frames if self._display_svc else False

    @property
    def playing(self) -> bool:
        return self._display_svc.is_video_playing() if self._display_svc else False

    # ── Flat convenience aliases ──────────────────────────────────

    def load_video(self, path: Any) -> dict:
        return self.load(path)

    def play_video(self) -> dict:
        return self.play()

    def stop_video(self) -> dict:
        return self.stop()

    def video_has_frames(self) -> bool:
        return self.has_frames

    # ── Overlay ops (compositing, metrics, masks) ──────────────

    def enable(self, on: bool) -> dict:
        self._display_svc.overlay.enabled = on
        return {"success": True, "enabled": on,
                "message": f"Overlay: {'on' if on else 'off'}"}

    def set_config(self, config: dict) -> dict:
        self._display_svc.overlay.set_config(config)
        return {"success": True, "message": f"Overlay config: {len(config)} elements"}

    def set_background(self, image: Any) -> dict:
        self._display_svc.overlay.set_background(image)
        return {"success": True, "message": "Overlay background set"}

    def set_mask(self, image: Any,
                 position: tuple[int, int] | None = None) -> dict:
        self._display_svc.overlay.set_theme_mask(image, position)
        return {"success": True, "message": "Mask set"}

    def set_mask_visible(self, visible: bool) -> dict:
        self._display_svc.overlay.set_mask_visible(visible)
        return {"success": True,
                "message": f"Mask: {'visible' if visible else 'hidden'}"}

    def set_temp_unit(self, unit: int) -> dict:
        self._display_svc.overlay.set_temp_unit(unit)
        return {"success": True, "message": f"Temp unit: {'F' if unit else 'C'}"}

    def update_metrics(self, metrics: Any) -> dict:
        self._display_svc.overlay.update_metrics(metrics)
        return {"success": True}

    def has_changed(self, metrics: Any) -> bool:
        return self._display_svc.overlay.would_change(metrics)

    def render(self) -> dict:
        image = self._display_svc.render_overlay()
        return {"success": True, "image": image}

    def apply_mask_dir(self, mask_dir: Any) -> dict:
        image = self._display_svc.apply_mask(Path(mask_dir))
        return {"success": True, "image": image,
                "message": f"Mask: {Path(mask_dir).name}"}

    def rebuild_video_cache(self, metrics: Any) -> dict:
        self._display_svc.rebuild_video_cache_metrics(metrics)
        return {"success": True}

    @property
    def enabled(self) -> bool:
        return self._display_svc.overlay.enabled if self._display_svc else False

    @property
    def service(self) -> Any:
        """Direct OverlayService access (for flash_skip_index etc.)."""
        return self._display_svc.overlay if self._display_svc else None

    # ── Overlay convenience aliases ───────────────────────────────

    def set_overlay_temp_unit(self, unit: int) -> dict:
        return self.set_temp_unit(unit)

    @property
    def is_overlay_enabled(self) -> bool:
        return self.enabled

    def enable_overlay(self, on: bool) -> dict:
        return self.enable(on)

    def set_overlay_background(self, image: Any) -> dict:
        return self.set_background(image)

    def set_overlay_mask(self, mask: Any,
                         position: tuple[int, int] | None = None) -> dict:
        return self.set_mask(mask, position)

    def set_overlay_mask_visible(self, visible: bool) -> dict:
        return self.set_mask_visible(visible)

    # ── Lifecycle ──────────────────────────────────────────────────

    def initialize(self, data_dir: Any) -> dict:
        if not self._display_svc:
            return {"success": False, "error": "Not connected"}
        data_dir = Path(data_dir)
        log.debug("LCDDevice: initializing, data_dir=%s", data_dir)
        self._display_svc.initialize(data_dir)
        self._theme_svc.set_directories(
            local_dir=self._display_svc.local_dir,
            web_dir=self._display_svc.web_dir,
            masks_dir=self._display_svc.masks_dir,
        )
        w, h = self.lcd_size
        if w and h:
            self._theme_svc.load_local_themes((w, h))
        devices = self._device_svc.detect()
        return {
            "success": True,
            "resolution": (w, h),
            "devices": len(devices),
            "message": f"Initialized: {w}x{h}, {len(devices)} device(s)",
        }
