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

from .models import DEFAULT_BRIGHTNESS_LEVEL, ThemeDir, ThemeInfo, ThemeType
from .paths import resolve_theme_dir
from .ports import Device

log = logging.getLogger(__name__)



class LCDDevice(Device):
    """LCD device — all display operations in one class.

    Delegates to services (DeviceService, DisplayService, ThemeService,
    OverlayService, MediaService). Backward-compatible accessors
    (lcd.frame, lcd.video, lcd.overlay, lcd.theme, lcd.settings)
    all point to self.

    Construction (via builder — the only correct way):
        lcd = ControllerBuilder().with_renderer(renderer).build_lcd()
        lcd.connect()
        lcd.send_image("pic.png")
    """

    def __init__(
        self,
        device_svc: Any = None,
        display_svc: Any = None,
        theme_svc: Any = None,
        renderer: Any = None,
        dc_config_cls: Any = None,
        load_config_json_fn: Any = None,
        theme_info_from_dir_fn: Any = None,
        lcd_config: Any = None,
        find_active_fn: Any = None,
        proxy_factory_fn: Any = None,
        build_services_fn: Any = None,
    ) -> None:
        self._device_svc = device_svc
        self._display_svc = display_svc
        self._theme_svc = theme_svc
        self._renderer = renderer
        self._dc_config_cls = dc_config_cls
        self._load_config_json_fn = load_config_json_fn
        self._theme_info_from_dir_fn = theme_info_from_dir_fn
        self._lcd_config = lcd_config
        self._find_active_fn = find_active_fn
        self._proxy_factory_fn = proxy_factory_fn
        self._build_services_fn = build_services_fn
        self._proxy: Any = None  # Set when routing through another instance

        # All capability accessors point to self — methods are on LCDDevice
        self.theme: LCDDevice = self  # type: ignore[assignment]
        self.frame: LCDDevice = self  # type: ignore[assignment]
        self.video: LCDDevice = self  # type: ignore[assignment]
        self.overlay: LCDDevice = self  # type: ignore[assignment]
        self.settings: LCDDevice = self  # type: ignore[assignment]

    def notify_data_ready(self) -> None:
        """Notify the display service that data extraction completed.

        Called by TrccApp after the background data-extraction thread finishes.
        Tell-Don't-Ask: caller signals the event; LCDDevice decides what to do.
        """
        if self._display_svc is not None and self._display_svc.on_data_ready is not None:
            self._display_svc.on_data_ready()

    def initialize_pipeline(self, settings: Any) -> None:
        """Post-connect initialization — set resolution + data dir from settings."""
        info = self.device_info
        res = getattr(info, 'resolution', (0, 0))
        if res and res != (0, 0):
            w, h = res
            settings.set_resolution(w, h)
            self.set_resolution(w, h)
            self.initialize(settings.user_data_dir)

    def set_data_ready_callback(self, fn: Any) -> None:
        """Register a callback invoked when background data extraction completes."""
        if self._display_svc is not None:
            self._display_svc.on_data_ready = fn

    def set_flash_index(self, index: int) -> dict:
        """Set the overlay element flash-skip index (-1 clears flash state)."""
        if self._display_svc and self._display_svc.overlay:
            self._display_svc.overlay.flash_skip_index = index
        return {"success": True, "index": index}

    def set_mask_position(self, x: int, y: int) -> dict:
        """Move the mask overlay and invalidate the overlay render cache."""
        if self._display_svc and self._display_svc.overlay:
            self._display_svc.overlay.theme_mask_position = (x, y)
            self._display_svc.overlay._invalidate_cache()
        return {"success": True, "message": f"Mask position: ({x}, {y})"}

    def render_and_send(self) -> dict:
        """Render the overlay and send to device if auto_send is on.

        Returns {'image': rendered_image} so callers can update their preview.
        """
        if not self._display_svc:
            return {"success": False, "image": None}
        image = self._display_svc.render_overlay()
        if image and self.auto_send and self.connected:
            self.send(image)
        return {"success": True, "image": image}

    def _build_services(self, device_svc: Any) -> None:
        """Wire up all services from a DeviceService via injected factory."""
        if self._build_services_fn is None:
            raise RuntimeError(
                "LCDDevice requires build_services_fn. "
                "Use ControllerBuilder.build_lcd() to wire dependencies.")
        result = self._build_services_fn(device_svc, self._renderer)
        self._device_svc = device_svc
        self._display_svc = result['display_svc']
        self._theme_svc = result['theme_svc']
        self._renderer = result['renderer']
        self._dc_config_cls = result['dc_config_cls']
        self._load_config_json_fn = result['load_config_json_fn']

    @classmethod
    def from_service(cls, device_svc: Any, renderer: Any = None,
                     build_services_fn: Any = None) -> LCDDevice:
        """Create a fully-wired LCDDevice from an existing DeviceService.

        Use when the caller already has a connected DeviceService (e.g. CLI
        resume, API device select) and needs the full DisplayService pipeline.
        """
        lcd = cls(renderer=renderer, build_services_fn=build_services_fn)
        lcd._build_services(device_svc)
        return lcd

    # ── Device ABC ─────────────────────────────────────────────────

    @property
    def is_lcd(self) -> bool:
        return True

    @property
    def is_led(self) -> bool:
        return False

    def connect(self, detected: Any = None) -> dict:
        """Connect to LCD device — or route through active instance.

        If find_active_fn and proxy_factory_fn are injected and another
        trcc instance owns the device, delegates all future method calls
        to the proxy. Otherwise connects to USB directly.

        Args:
            detected: DetectedDevice, device_path str, or None for auto-detect.

        Returns:
            {"success": bool, "resolution": (w, h), "device_path": str,
             "proxy": InstanceKind | None}
        """
        proxy_result = self._try_proxy_route(detected)
        if proxy_result is not None:
            self._set_proxy(self._proxy)
            proxy_result["resolution"] = getattr(self._proxy, 'resolution', (0, 0))
            proxy_result["device_path"] = getattr(self._proxy, 'device_path', '')
            return proxy_result

        if self._device_svc is None:
            raise RuntimeError(
                "LCDDevice requires a DeviceService. "
                "Use ControllerBuilder.build_lcd() to wire dependencies.")

        device_path = None
        if isinstance(detected, str):
            device_path = detected
        elif detected is not None:
            device_path = getattr(detected, 'scsi_device', None) or \
                          getattr(detected, 'path', None)

        svc = self._device_svc
        svc.scan_and_select(device_path)
        if not svc.selected:
            return {"success": False, "error": "No LCD device found"}

        self._build_services(svc)
        dev = svc.selected
        w, h = dev.resolution
        if w and h and self._display_svc:
            self._display_svc.set_resolution(w, h)
        return {
            "success": True,
            "resolution": dev.resolution,
            "device_path": dev.path,
        }

    @property
    def connected(self) -> bool:
        if self._proxy is not None:
            return getattr(self._proxy, 'connected', True)
        return (self._device_svc is not None
                and self._device_svc.selected is not None)

    @property
    def device_info(self) -> Any:
        return self._device_svc.selected if self._device_svc else None

    def _set_proxy(self, proxy: Any) -> None:
        """Route all capability accessors through proxy."""
        self._proxy = proxy
        self.theme = proxy  # type: ignore[assignment]
        self.frame = proxy  # type: ignore[assignment]
        self.video = proxy  # type: ignore[assignment]
        self.overlay = proxy  # type: ignore[assignment]
        self.settings = proxy  # type: ignore[assignment]

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
                               output: str | None = None,
                               metrics: Any = None) -> dict:
        """Render overlay from DC config file (CLI standalone).

        Args:
            metrics: Pre-polled HardwareMetrics. Caller must provide
                     (injected from composition root).
        """
        from ..services import ImageService, OverlayService

        if not os.path.exists(dc_path):
            return {"success": False, "error": f"Path not found: {dc_path}"}

        if not self.connected:
            return {"success": False, "error": "Device not connected"}
        if not self._display_svc:
            return {"success": False, "error": "Display service not initialized"}
        w, h = self._display_svc.canvas_size
        overlay = OverlayService(
            w, h, renderer=self._renderer,
            load_config_json_fn=self._load_config_json_fn,
            dc_config_cls=self._dc_config_cls,
        )
        p = Path(dc_path)
        dc_file = p / "config1.dc" if p.is_dir() else p
        display_opts = overlay.load_from_dc(dc_file)

        if metrics is not None:
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
        if not self._display_svc:
            return {"success": False, "error": "Display service not initialized"}

        w, h = self._display_svc.canvas_size
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
        position = self._parse_mask_position(dc_path, mask_w, mask_h, w, h)

        # Use existing overlay service (GUI) or create fresh one (CLI)
        if self._display_svc:
            ovl = self._display_svc.overlay
            ovl.set_theme_mask(None)
            ovl.set_mask(mask_img, position)
            ovl.enabled = True
            # Track mask source for theme save
            self._display_svc._mask_source_dir = p if p.is_dir() else p.parent
            log.debug("load_mask_standalone: _mask_source_dir=%s", self._display_svc._mask_source_dir)
            # Use current theme bg, fall back to black
            bg = self._display_svc._clean_background or \
                self._display_svc.current_image or \
                ImageService.solid_color(0, 0, 0, w, h)
            self._display_svc.current_image = bg
            # Invalidate video cache (old mask baked in)
            self._display_svc._cache = None
            result_img = self._display_svc.render_overlay()
        else:
            ovl = OverlayService(
                w, h, renderer=self._renderer,
                load_config_json_fn=self._load_config_json_fn,
                dc_config_cls=self._dc_config_cls,
            )
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

    def _parse_mask_position(
        self, dc_path: Path | None, mask_w: int, mask_h: int,
        lcd_w: int, lcd_h: int,
    ) -> tuple[int, int] | None:
        """Parse mask position from DC file (center→top-left).

        DC files store mask_position as center coordinates (XvalMB, YvalMB).
        C# draws at (XvalMB - W/2, YvalMB - H/2).
        Full-size masks go at (0, 0).
        """
        if mask_w >= lcd_w and mask_h >= lcd_h:
            return (0, 0)
        if not dc_path or not dc_path.exists():
            # No DC file — center the mask (C# ThemeMask panel default)
            return ((lcd_w - mask_w) // 2, (lcd_h - mask_h) // 2)
        if self._dc_config_cls is None:
            return ((lcd_w - mask_w) // 2, (lcd_h - mask_h) // 2)
        try:
            dc = self._dc_config_cls(dc_path)
            if dc.mask_enabled:
                center_pos = dc.mask_settings.get('mask_position')
                if center_pos:
                    return (
                        center_pos[0] - mask_w // 2,
                        center_pos[1] - mask_h // 2,
                    )
        except Exception as e:
            log.warning("DC config parse failed for %s — using centered mask position: %s",
                        dc_path, e)
        # Fallback: center the mask
        return ((lcd_w - mask_w) // 2, (lcd_h - mask_h) // 2)

    # ── Frame ops (encode/send to hardware) ─────────────────────

    def send_image(self, image_path: str) -> dict:
        if not os.path.exists(image_path):
            return {"success": False, "error": f"File not found: {image_path}"}
        from ..services import ImageService
        w, h = self.lcd_size
        img = ImageService.open_and_resize(image_path, w, h)
        self._device_svc.send_frame(img, w, h)
        return {"success": True, "image": img, "message": f"Sent {image_path}"}

    def send_color(self, r: int, g: int, b: int) -> dict:
        from ..services import ImageService
        w, h = self.lcd_size
        img = ImageService.solid_color(r, g, b, w, h)
        self._device_svc.send_frame(img, w, h)
        return {"success": True, "image": img,
                "message": f"Sent color #{r:02x}{g:02x}{b:02x}"}

    def send(self, image: Any) -> dict:
        """Encode and async-send image to LCD device."""
        if not self._device_svc.selected:
            return {"success": False, "error": "No device selected"}
        w, h = self.lcd_size
        self._device_svc.send_frame_async(image, w, h)
        return {"success": True}

    def send_frame(self, image: Any) -> bool:
        """Encode and synchronously send image to LCD device.

        Unlike send() which queues asynchronously, this blocks until
        the USB write completes. Used by frame pump loops that need
        backpressure (video, overlay, keepalive, screencast).
        """
        w, h = self.lcd_size
        return self._device_svc.send_frame(image, w, h)

    def send_async(self, image: Any, width: int, height: int) -> None:
        if self._device_svc.is_busy:
            return
        self._device_svc.send_frame_async(image, width, height)

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
        self._device_svc.send_frame(img, w, h)
        return {"success": True, "image": img, "message": "Device reset — RED"}

    # ── Display settings (brightness/rotation/split) ─────────────

    def _persist(self, field: str, value: object) -> None:
        dev = self._device_svc.selected if self._device_svc else None
        if dev and self._lcd_config:
            self._lcd_config.persist(dev, field, value)

    def restore_device_settings(self) -> None:
        """Restore brightness + rotation from per-device config.

        Called by adapters (CLI, API, GUI) after device selection so they
        don't need to read config or convert brightness levels themselves.
        """
        dev = self._device_svc.selected if self._device_svc else None
        if not dev or not self._lcd_config:
            return
        cfg = self._lcd_config.get_config(dev)
        raw = cfg.get('brightness_level', DEFAULT_BRIGHTNESS_LEVEL)
        percent = raw if 0 <= raw <= 100 else 100
        self.set_brightness(percent)
        rotation = cfg.get('rotation', 0)
        if rotation in (0, 90, 180, 270):
            self.set_rotation(rotation)

    def set_brightness(self, percent: int) -> dict:
        """Set brightness. percent is 0–100."""
        if not 0 <= percent <= 100:
            return {"success": False,
                    "error": f"Brightness must be 0–100, got {percent}"}
        image = self._display_svc.set_brightness(percent)
        self._persist('brightness_level', percent)
        return {"success": True, "image": image,
                "message": f"Brightness set to {percent}%"}

    def set_rotation(self, degrees: int) -> dict:
        if degrees not in (0, 90, 180, 270):
            return {"success": False,
                    "error": "Rotation must be 0, 90, 180, or 270"}
        svc = self._display_svc
        old_canvas = svc.canvas_size
        image = svc.set_rotation(degrees)
        self._persist('rotation', degrees)

        # Non-square canvas change: reload theme from new directory
        # C# UpDateUCComboBox1: ReadFileTheme() + Theme_Click_Event()
        if old_canvas != svc.canvas_size:
            reloaded = self._reload_theme_for_rotation()
            if reloaded is not None:
                image = reloaded

        return {"success": True, "image": image,
                "message": f"Rotation set to {degrees}°"}

    def _reload_theme_for_rotation(self) -> Any | None:
        """Find current theme in the new rotation directory and reload it.

        After DisplayService.set_rotation() switches dirs, find the same
        theme name in the new directory and reload with overlay config.
        All UIs (CLI, API, GUI) get this via LCDDevice.set_rotation().
        """
        current = self.current_theme_path
        if not current:
            return None
        theme_name = current.name
        svc = self._display_svc
        for base in (svc.local_dir, svc.web_dir):
            if not base:
                continue
            candidate = Path(base) / theme_name
            if candidate.exists():
                log.info("Rotation reload: %s → %s", theme_name, candidate)
                theme = self._theme_info_from_dir_fn(candidate)
                result = self.select(theme)
                # Reload overlay config from new dir
                overlay_cfg = self.load_overlay_config_from_dir(str(candidate))
                if overlay_cfg:
                    if self._lcd_config:
                        self._lcd_config.apply_format_prefs(overlay_cfg)
                    self.set_config(overlay_cfg)
                    self.enable_overlay(True)
                    rendered = svc._render_and_process()
                    return rendered
                else:
                    self.enable_overlay(False)
                return result.get('image')
        log.debug("Rotation: theme '%s' not in new dirs", theme_name)
        return None

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
        if width and height:
            self._theme_svc.load_local_themes((width, height))
        return {"success": True, "resolution": (width, height),
                "message": f"Resolution: {width}x{height}"}

    def restore_last_theme(self) -> dict:
        """Restore theme, mask, and overlay from per-device config.

        Complete session restore — reads config, loads theme, applies mask
        and overlay. Returns result dict with image, overlay_config,
        overlay_enabled, and is_animated so each adapter can update its
        own presentation layer.
        """
        dev = self._device_svc.selected if self._device_svc else None
        if not dev or not self._lcd_config:
            return {"success": False, "error": "No device selected"}
        cfg = self._lcd_config.get_config(dev)

        # ── Theme ──────────────────────────────────────────────────────────
        theme_name = cfg.get("theme_name")
        theme_type = cfg.get("theme_type", "local")

        # Migration: old config stored full path as theme_path
        if not theme_name:
            old_path = cfg.get("theme_path")
            if not old_path:
                return {"success": False, "error": "No saved theme"}
            video_exts = {'.mp4', '.avi', '.mkv', '.webm'}
            image_exts = {'.png', '.jpg', '.jpeg', '.bmp', '.gif'}
            suffix = Path(old_path).suffix.lower()
            if suffix in video_exts:
                theme_name = Path(old_path).stem
                theme_type = "cloud"
            elif suffix in image_exts:
                theme_name = Path(old_path).name
                theme_type = "image"
            else:
                theme_name = Path(old_path).name
                theme_type = "local"

        # Resolve path from name + device resolution
        w, h = self.lcd_size
        svc = self._display_svc
        if theme_type == "cloud":
            if not svc or not svc.web_dir:
                return {"success": False, "error": "No cloud theme directory"}
            path = svc.web_dir / f"{theme_name}.mp4"
            if not path.exists():
                return {"success": False, "error": f"Cloud theme not found: {theme_name}"}
            preview = path.parent / f"{theme_name}.png"
            theme = ThemeInfo.from_video(path, preview if preview.exists() else None)
        elif theme_type == "image":
            # Single image file — keep full path from old config
            old_path = cfg.get("theme_path", "")
            if not old_path or not Path(old_path).exists():
                return {"success": False, "error": "Image not found"}
            result = self.load_image(old_path)
            return {**result, "overlay_config": None,
                    "overlay_enabled": False, "is_animated": False}
        else:
            # Local theme — resolve against device's resolution directory
            td = ThemeDir(resolve_theme_dir(w, h))
            path = td.path / theme_name
            if not path.exists():
                return {"success": False, "error": f"Theme not found: {theme_name}"}
            theme = self._theme_info_from_dir_fn(path, (w, h))

        result = self.select(theme)
        if not result.get("success"):
            return {**result, "overlay_config": None,
                    "overlay_enabled": False, "is_animated": False}

        # ── Mask ───────────────────────────────────────────────────────────
        mask_id = cfg.get("mask_id") or ""
        if not mask_id:
            # Migration: old config stored full path as mask_path
            old_path = cfg.get("mask_path")
            if old_path:
                mask_id = Path(old_path).name
        if mask_id:
            is_custom = cfg.get("mask_custom", False)
            svc = self._display_svc
            base = svc.user_masks_dir() if is_custom and svc else (svc.masks_dir if svc else None)
            mask_dir = Path(base) / mask_id if base else None
            if mask_dir and mask_dir.exists():
                svc = self._display_svc
                already_loaded = (svc and svc._mask_source_dir == mask_dir)
                if not already_loaded:
                    self.load_mask_standalone(str(mask_dir))

        # ── Overlay ────────────────────────────────────────────────────────
        overlay_cfg = cfg.get("overlay", {})
        overlay_enabled = False
        overlay_config = None
        if overlay_cfg:
            overlay_enabled = overlay_cfg.get("enabled", False)
            overlay_config = overlay_cfg.get("config") or None
            if overlay_config:
                self.set_config(overlay_config)
            self.enable(overlay_enabled)

        # ── Send to device ─────────────────────────────────────────────
        image = result.get("image")
        is_animated = result.get("is_animated", False)
        if not is_animated and self.connected:
            rendered = self.render_and_send()
            image = rendered.get("image") or image

        return {
            "success": True,
            "image": image,
            "is_animated": is_animated,
            "overlay_config": overlay_config,
            "overlay_enabled": overlay_enabled,
            "message": f"Restored theme: {path.name}",
        }

    def load_last_theme(self) -> dict:
        """Thin backward-compat wrapper — delegates to restore_last_theme()."""
        return self.restore_last_theme()

    def collect_other_device_resolutions(self) -> list[tuple[int, int]]:
        """Collect resolutions for all connected LCD devices except current.

        For non-square devices, includes both orientations (WxH and HxW).
        Returns deduplicated list of (width, height) tuples.
        """
        if not self._device_svc:
            return []
        current = self.lcd_size
        seen: set[tuple[int, int]] = set()
        for dev in self._device_svc.devices:
            res = dev.resolution
            if not res or res == (0, 0) or res == current:
                continue
            w, h = res
            seen.add((w, h))
            if w != h:
                seen.add((h, w))
        return list(seen)

    # ── Theme ops (loading, saving, import/export) ─────────────

    def select(self, theme: Any) -> dict:
        """Select and load a theme (local or cloud)."""
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

    def load_theme_by_name(self, name: str, width: int = 0, height: int = 0) -> dict:
        """Load a theme by name, send to device, persist as last-used.

        Full pipeline matching GUI/CLI behavior:
        1. Discover themes for resolution → find by name
        2. select() → DisplayService processes (brightness, rotation)
        3. Send static image to device (video themes return for caller to loop)
        4. Persist theme_path to per-device config

        Returns dict with: success, image, is_animated, interval,
        theme_path (Path), config_path (Path|None for overlay dc).
        """
        w, h = (width, height) if width and height else self.lcd_size
        theme_dir = Path(resolve_theme_dir(w, h))
        svc = self._display_svc
        pr = svc._path_resolver if svc else None
        user_content_dir = Path(pr.user_content_dir()) if pr else None
        themes = self._theme_svc.discover_local_merged(
            theme_dir, user_content_dir, (w, h))
        match = next((t for t in themes if t.name == name), None)
        if not match:
            return {"success": False, "error": f"Theme '{name}' not found"}

        result = self.select(match)
        if not result.get("success"):
            return result

        image = result.get("image")
        is_animated = result.get("is_animated", False)

        # Load overlay config (config.json / config1.dc) — matches GUI behavior
        overlay_config = None
        if match.path:
            overlay_config = self.load_overlay_config_from_dir(str(match.path))
            if overlay_config:
                if self._lcd_config:
                    self._lcd_config.apply_format_prefs(overlay_config)
                self.set_config(overlay_config)
                self.enable_overlay(True)
                if not is_animated:
                    rendered = self.render_and_send()
                    image = rendered.get("image") or image
                    result["image"] = image
            else:
                self.enable_overlay(False)
                if image and not is_animated:
                    self.send(image)
        elif image and not is_animated:
            self.send(image)
        result["overlay_config"] = overlay_config

        # Include theme paths for caller to handle overlay/persist
        result["theme_path"] = match.path
        result["config_path"] = match.config_path

        # Persist as last-used theme
        dev = self._device_svc.selected if self._device_svc else None
        if dev and match.path and self._lcd_config:
            self._lcd_config.persist(dev, 'theme_name', match.name)
            self._lcd_config.persist(dev, 'theme_type', 'local')
            self._lcd_config.persist(dev, 'mask_id', '')

        return result

    def load_local(self, resolution: tuple[int, int]) -> dict:
        themes = self._theme_svc.load_local_themes(resolution)
        return {"success": True, "themes": themes, "count": len(themes)}

    def save(self, name: str) -> dict:
        ok, msg = self._display_svc.save_theme(name)
        return {"success": ok, "message": msg}

    def set_mask_from_path(self, path: Any) -> dict:
        """Load and apply a mask from a file or directory path.

        File → loads PNG as mask via OverlayService.
        Directory → delegates to DisplayService.apply_mask().
        """
        p = Path(path)
        if p.is_dir():
            image = self._display_svc.apply_mask(p)
            return {"success": True, "image": image,
                    "message": f"Mask: {p.name}"}
        from ..services.image import ImageService
        from ..services.overlay import OverlayService
        r = ImageService._r()
        w, h = self.lcd_size
        mask_img = OverlayService.load_mask_from_path(p, r, w, h)
        if mask_img is None:
            return {"success": False, "error": f"Failed to load mask: {path}"}
        self._display_svc.overlay.set_theme_mask(mask_img)
        self._display_svc._mask_source_dir = p.parent
        return {"success": True, "message": f"Mask: {p.name}"}

    def export_config(self, path: Any) -> dict:
        ok, msg = self._display_svc.export_config(Path(path))
        return {"success": ok, "message": msg}

    def import_config(self, path: Any, data_dir: Any) -> dict:
        ok, msg = self._display_svc.import_config(Path(path), Path(data_dir))
        return {"success": ok, "message": msg}

    # ── Video playback ──────────────────────────────────────────

    def load(self, path: Any) -> dict:
        """Load video/GIF for playback."""
        self._display_svc._cache = None
        success = self._display_svc.media.load(Path(path))
        if success:
            self._display_svc._convert_media_frames()
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

    def tick(self) -> Any:
        """Core metrics loop hook: render overlay + send frame to device.

        Called by TrccApp metrics loop from a background thread.
        Video playback is driven exclusively by the GUI animation timer
        (video_tick()) — this method does NOT advance video frames.

        SCSI devices need continuous frame refreshes to maintain their
        display.  Re-render only when metrics change, but always resend
        the current frame.  The encoding cache in DeviceService skips
        re-encoding when the image hasn't changed.

        Returns:
            Rendered image if a NEW frame was produced, None if we resent
            the cached frame.  Callers (TrccApp) emit FRAME_RENDERED only
            for new frames so GUI adapters skip redundant preview updates.
        """
        if not self._display_svc or self._display_svc.is_video_playing():
            return None
        new_frame = None
        if self._display_svc.overlay.enabled and self._display_svc.overlay.would_change(
            self._display_svc.overlay.metrics
        ):
            new_frame = self._display_svc.render_overlay()
            if new_frame:
                self._last_overlay_frame = new_frame
        image = new_frame or getattr(self, '_last_overlay_frame', None) or self._display_svc.current_image
        if image:
            self.send(image)
        return new_frame

    def video_tick(self) -> dict | None:
        """Animation timer hook: advance one video frame, return frame data.

        Called by the GUI animation timer (LCDHandler._on_video_tick) at
        ~33ms intervals.  Returns None if video is not playing.
        """
        if not self._display_svc:
            return None
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

    # ── Blocking video loop (CLI / API) ──────────────────────────

    def play_video_loop(
        self,
        video_path: Any,
        *,
        overlay_config: dict | None = None,
        mask_path: Any | None = None,
        metrics_fn: Any | None = None,
        on_frame: Any | None = None,
        on_progress: Any | None = None,
        loop: bool = True,
        duration: float = 0,
    ) -> dict:
        """Play video with optional overlay, blocking until done.

        This is the single entry point for all adapters (CLI, GUI, API)
        to play video with live metric overlays.

        Args:
            video_path: Video/GIF/ZT file to play.
            overlay_config: Overlay element config dict (from
                ``build_overlay_config()``). Enables overlay if provided.
            mask_path: Mask PNG file or directory. Auto-resized to LCD dims.
            metrics_fn: Callable returning ``HardwareMetrics`` — polled
                once per second for live overlay updates.
            on_frame: Callback ``(processed_image)`` — adapter sends to device.
            on_progress: Callback ``(percent, current_time, total_time)``.
            loop: Whether to loop the video.
            duration: Stop after N seconds (0 = no limit).

        Returns:
            Result dict with success/error/message.
        """
        if not self._display_svc:
            return {"success": False, "error": "DisplayService not initialized"}
        log.info("play_video_loop: %s overlay=%s mask=%s",
                 video_path, bool(overlay_config), bool(mask_path))
        from pathlib import Path
        return self._display_svc.run_video_loop(
            Path(video_path),
            overlay_config=overlay_config,
            mask_path=Path(mask_path) if mask_path else None,
            metrics_fn=metrics_fn,
            on_frame=on_frame,
            on_progress=on_progress,
            loop=loop,
            duration=duration,
        )

    # ── Blocking static keepalive loop (CLI / API) ──────────────

    def keep_alive_loop(
        self,
        *,
        interval: float = 0.150,
        duration: float = 0,
        metrics_fn: Any | None = None,
        on_frame: Any | None = None,
    ) -> dict:
        """Re-send current frame at *interval* until interrupted.

        Bulk/LY devices don't retain frames — firmware reverts to the
        built-in logo unless frames keep arriving.  Mirrors
        ``play_video_loop`` for static themes.
        """
        if not self._display_svc:
            return {"success": False, "error": "DisplayService not initialized"}
        return self._display_svc.run_static_loop(
            interval=interval, duration=duration,
            metrics_fn=metrics_fn, on_frame=on_frame,
        )

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
        w, h = self.lcd_size
        self._display_svc.overlay.set_config_resolution(w, h)
        self._display_svc.overlay.set_config(config)
        return {"success": True, "message": f"Overlay config: {len(config)} elements"}

    def set_background(self, image: Any) -> dict:
        self._display_svc.overlay.set_background(image)
        # Also update clean_background so render_overlay() uses this image
        # as the base (C# sets both bitmapBGK and imagePicture).
        # Use overlay.background (already converted to native QImage)
        # to avoid re-conversion on every render tick.
        if image is not None:
            self._display_svc.set_clean_background(
                self._display_svc.overlay.background)
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
        if self._display_svc is None:
            return {"success": False}
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

    def update_video_cache_text(self, metrics: Any) -> dict:
        self._display_svc.update_video_cache_text(metrics)
        return {"success": True}

    @property
    def enabled(self) -> bool:
        return self._display_svc.overlay.enabled if self._display_svc else False

    @property
    def last_metrics(self) -> Any:
        """Most recently received metrics, or None before first tick."""
        return self._display_svc.overlay.metrics if self._display_svc else None

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

    def load_overlay_config_from_dir(self, theme_dir: str) -> dict | None:
        """Parse overlay config from a theme directory.

        Tries config.json first, then config1.dc.
        Returns the overlay config dict, or None if neither file exists or both fail.
        Uses the injected dc_config_cls and load_config_json_fn — no adapter imports
        in the caller (GUI handler stays adapter-free).
        """
        p = Path(theme_dir)
        overlay_config: dict | None = None

        json_path = p / 'config.json'
        if json_path.exists() and self._load_config_json_fn is not None:
            try:
                result = self._load_config_json_fn(str(json_path))
                if result is not None:
                    overlay_config = result[0]
            except Exception:
                pass

        if overlay_config is None and self._dc_config_cls is not None:
            dc_path = p / 'config1.dc'
            if dc_path.exists():
                try:
                    overlay_config = self._dc_config_cls(dc_path).to_overlay_config()
                except Exception:
                    pass

        return overlay_config or None

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
