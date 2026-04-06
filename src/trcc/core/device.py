"""Device — unified device object for LCD displays and LED controllers.

Discovered via USB scan, handshaked to get identity, DI'd to handlers.
One class — the difference between LCD and LED is which services are
injected by the builder. ProtocolTraits.is_led drives the branching.

CLI, GUI, and API all consume this directly (DIP — core/, not adapter/).
"""
from __future__ import annotations

import functools
import logging
import os
from pathlib import Path
from typing import Any

from .models import DEFAULT_BRIGHTNESS_LEVEL, LEDMode, ThemeInfo, ThemeType
from .orientation import Orientation
from .paths import masks_dir_name, resolve_theme_dir, theme_dir_name, web_dir_name

log = logging.getLogger(__name__)


# ── Proxy decorator (LED set_* methods) ──────────────────────────────────

def _forward_to_proxy(method):
    """Forward method call to proxy if one is active."""
    @functools.wraps(method)
    def wrapper(self, *args, **kwargs):
        if self._proxy is not None:
            log.debug("proxy forward: %s → %s", method.__name__, type(self._proxy).__name__)
            return getattr(self._proxy, method.__name__)(*args, **kwargs)
        return method(self, *args, **kwargs)
    return wrapper


class Device:
    """A USB device. Discovered, handshaked, passed around.

    Builder injects services based on device type:
    - LCD: display_svc, theme_svc, renderer, media (via display_svc)
    - LED: led_svc (or led_svc_factory for deferred creation)

    Construction (via builder — the only correct way):
        device = ControllerBuilder.for_current_os().build_device(detected)
        device.connect(detected)
    """

    def __init__(
        self,
        *,
        device_svc: Any = None,
        device_type: bool = True,  # True=LCD, False=LED
        # LCD services
        display_svc: Any = None,
        theme_svc: Any = None,
        renderer: Any = None,
        dc_config_cls: Any = None,
        load_config_json_fn: Any = None,
        theme_info_from_dir_fn: Any = None,
        lcd_config: Any = None,
        build_services_fn: Any = None,
        # LED services
        led_svc: Any = None,
        get_protocol: Any = None,
        led_svc_factory: Any = None,
        led_config: Any = None,
        # IPC
        find_active_fn: Any = None,
        proxy_factory_fn: Any = None,
    ) -> None:
        self._device_svc = device_svc
        self._device_type = device_type  # True=LCD, False=LED
        # LCD
        self._display_svc = display_svc
        self._theme_svc = theme_svc
        self._renderer = renderer
        self._dc_config_cls = dc_config_cls
        self._load_config_json_fn = load_config_json_fn
        self._theme_info_from_dir_fn = theme_info_from_dir_fn
        self._lcd_config = lcd_config
        self._build_services_fn = build_services_fn
        # LED
        self._led_svc = led_svc
        self._get_protocol = get_protocol
        self._led_svc_factory = led_svc_factory
        self._led_config = led_config
        # IPC
        self._find_active_fn = find_active_fn
        self._proxy_factory_fn = proxy_factory_fn
        self._proxy: Any = None
        # State — uniform for both LCD and LED
        self._info: Any = None  # DeviceInfo, set during connect()
        self._init_status: str | None = None
        self.log: logging.Logger = log
        self.orientation = Orientation(0, 0)
        # Backward-compat aliases — all point to self
        self.theme: Device = self   # type: ignore[assignment]
        self.frame: Device = self   # type: ignore[assignment]
        self.video: Device = self   # type: ignore[assignment]
        self.overlay: Device = self  # type: ignore[assignment]
        self.settings: Device = self  # type: ignore[assignment]

    # ══════════════════════════════════════════════════════════════════════
    # Type queries — from data, not class hierarchy
    # ══════════════════════════════════════════════════════════════════════

    @property
    def is_lcd(self) -> bool:
        return self._device_type

    @property
    def is_led(self) -> bool:
        return not self._device_type

    # ══════════════════════════════════════════════════════════════════════
    # Shared lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def wire_ipc(self, find_active_fn: Any, proxy_factory_fn: Any) -> None:
        """Inject IPC routing functions for proxy delegation."""
        self._find_active_fn = find_active_fn
        self._proxy_factory_fn = proxy_factory_fn

    def _try_proxy_route(self, detected: Any) -> dict | None:
        """Check for active instance and route through proxy if found."""
        if detected is None and self._find_active_fn and self._proxy_factory_fn:
            active = self._find_active_fn()
            if active is not None:
                self._proxy = self._proxy_factory_fn(active)
                return {"success": True, "proxy": active}
        return None

    def connect(self, detected: Any = None) -> dict:
        """Connect to device — handshake via protocol, fill DeviceInfo.

        Returns: {"success": bool, ...}
        """
        if self.is_led:
            return self._connect_led(detected)
        return self._connect_lcd(detected)

    @property
    def connected(self) -> bool:
        if self._proxy is not None:
            return getattr(self._proxy, 'connected', True)
        if self._info is not None:
            return True
        # Pre-connect check: service presence means ready
        if self._led_svc is not None:
            return True
        if self._device_svc is not None and self._device_svc.selected is not None:
            return True
        return False

    @property
    def device_info(self) -> Any:
        if self._info is not None:
            return self._info
        # Fallback: LCD device_svc stores selected device before _info is set
        if self._device_svc is not None:
            return self._device_svc.selected
        return None

    def tick(self) -> Any:
        """Core metrics loop hook — called at fixed interval."""
        if self._display_svc:
            return self._tick_lcd()
        if self._led_svc:
            return self._tick_led()
        return None

    def cleanup(self) -> None:
        if self._display_svc:
            self._display_svc.cleanup()
        if self._led_svc:
            self._led_svc.cleanup()

    def update_metrics(self, metrics: Any) -> dict:
        if self._display_svc:
            self._display_svc.overlay.update_metrics(metrics)
        if self._led_svc:
            self._led_svc.update_metrics(metrics)
        return {"success": True}

    def set_temp_unit(self, unit: int) -> dict:
        """Set temperature unit (0=Celsius, 1=Fahrenheit)."""
        if self._led_svc:
            unit_str = 'F' if unit else 'C'
            self._led_svc.set_seg_temp_unit(unit_str)
            self._led_send_and_save()
            return {"success": True,
                    "message": f"Temperature unit set to {unit_str}"}
        if self._display_svc:
            self._display_svc.overlay.set_temp_unit(unit)
        return {"success": True, "message": f"Temp unit: {'F' if unit else 'C'}"}

    def initialize_pipeline(self, settings: Any) -> None:
        """Post-connect initialization — set resolution + data dir from settings."""
        if not self._display_svc:
            return
        info = self.device_info
        res = getattr(info, 'resolution', (0, 0))
        if res and res != (0, 0):
            w, h = res
            self.log.info("initialize_pipeline: %dx%d", w, h)
            settings.set_resolution(w, h)
            self.set_resolution(w, h)
            self.initialize(settings.user_data_dir)
        else:
            self.log.warning("initialize_pipeline: skipped — resolution is %s", res)

    def notify_data_ready(self) -> None:
        """Data extraction completed — refresh theme dirs."""
        if self._display_svc is not None and self._display_svc.on_data_ready is not None:
            self._display_svc.on_data_ready()

    # ══════════════════════════════════════════════════════════════════════
    # LCD connect
    # ══════════════════════════════════════════════════════════════════════

    def _connect_lcd(self, detected: Any) -> dict:
        proxy_result = self._try_proxy_route(detected)
        if proxy_result is not None:
            self.log.info("connect: routing through active proxy instance")
            self._set_proxy(self._proxy)
            proxy_result["resolution"] = getattr(self._proxy, 'resolution', (0, 0))
            proxy_result["device_path"] = getattr(self._proxy, 'device_path', '')
            return proxy_result

        if self._device_svc is None:
            raise RuntimeError(
                "Device requires a DeviceService. "
                "Use ControllerBuilder.build_device() to wire dependencies.")

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
        self._info = dev

        # Tag logger with full device identity from handshake
        vid = int(dev.vid) if isinstance(dev.vid, int) else 0
        pid = int(dev.pid) if isinstance(dev.pid, int) else 0
        label = f'lcd:{dev.device_index} [{vid:04X}:{pid:04X} FBL={dev.fbl_code} PM={dev.pm_byte} SUB={dev.sub_byte}]'
        self.log = logging.getLogger(f'{__name__}.{label}')
        if hasattr(self.log, 'dev'):
            self.log.dev = label  # type: ignore[attr-defined]
        if self._display_svc:
            self._display_svc.log = logging.getLogger(f'trcc.services.display.{label}')
            if hasattr(self._display_svc.log, 'dev'):
                self._display_svc.log.dev = label  # type: ignore[attr-defined]
            if self._display_svc.overlay:
                self._display_svc.overlay.log = logging.getLogger(f'trcc.services.overlay.{label}')
                if hasattr(self._display_svc.overlay.log, 'dev'):
                    self._display_svc.overlay.log.dev = label  # type: ignore[attr-defined]
        self.log.info("connected: %s [%04X:%04X] %dx%d FBL=%s PM=%d SUB=%d",
                      dev.path, dev.vid, dev.pid, *dev.resolution,
                      dev.fbl_code, dev.pm_byte, dev.sub_byte)

        w, h = dev.resolution
        if w and h and self._display_svc:
            self._display_svc.set_resolution(w, h)
            self.orientation = self._display_svc.orientation
            self.persist_dirs()
        return {
            "success": True,
            "resolution": dev.resolution,
            "device_path": dev.path,
        }

    def _build_services(self, device_svc: Any) -> None:
        """Wire up all services from a DeviceService via injected factory."""
        if self._build_services_fn is None:
            raise RuntimeError(
                "Device requires build_services_fn. "
                "Use ControllerBuilder.build_device() to wire dependencies.")
        result = self._build_services_fn(device_svc, self._renderer)
        self._device_svc = device_svc
        self._display_svc = result['display_svc']
        self._theme_svc = result['theme_svc']
        self._renderer = result['renderer']
        self._dc_config_cls = result['dc_config_cls']
        self._load_config_json_fn = result['load_config_json_fn']

    @classmethod
    def from_service(cls, device_svc: Any, renderer: Any = None,
                     build_services_fn: Any = None) -> Device:
        """Create a fully-wired LCD Device from an existing DeviceService."""
        device = cls(renderer=renderer, build_services_fn=build_services_fn)
        device._build_services(device_svc)
        return device

    def _set_proxy(self, proxy: Any) -> None:
        """Route all capability accessors through proxy."""
        self._proxy = proxy
        self.theme = proxy  # type: ignore[assignment]
        self.frame = proxy  # type: ignore[assignment]
        self.video = proxy  # type: ignore[assignment]
        self.overlay = proxy  # type: ignore[assignment]
        self.settings = proxy  # type: ignore[assignment]

    # ══════════════════════════════════════════════════════════════════════
    # LED connect
    # ══════════════════════════════════════════════════════════════════════

    def _connect_led(self, detected: Any) -> dict:
        if self._led_svc:
            log.debug("LED connect: already connected (status=%s)", self._init_status)
            return {"success": True, "status": self._init_status or ""}

        proxy_result = self._try_proxy_route(detected)
        if proxy_result is not None:
            log.info("LED connect: routing through proxy instance")
            proxy_result["status"] = f"Connected (via {proxy_result['proxy'].value})"
            return proxy_result

        if detected is not None and getattr(detected, 'implementation', '') == 'hid_led':
            from .models import DeviceInfo
            self._info = DeviceInfo.from_detected(detected)
            log.info("LED connect: using detected %s", self._info.path)
        else:
            if self._device_svc is None:
                raise RuntimeError(
                    "Device requires a DeviceService. "
                    "Use ControllerBuilder.build_device() to wire dependencies.")
            self._device_svc.detect()
            self._info = next(
                (d for d in self._device_svc.devices
                 if d.implementation == 'hid_led'), None)
            if not self._info:
                log.warning("LED connect: no LED device found")
                return {"success": False, "error": "No LED device found"}

        self._led_svc = self._led_svc_factory(
            get_protocol=self._get_protocol,
            led_config=self._led_config,
        )
        self._init_status = self._led_svc.initialize(self._info)
        pm = getattr(self._info, 'pm_byte', 0)
        sub = getattr(self._info, 'sub_byte', 0)
        vid = int(self._info.vid) if isinstance(self._info.vid, int) else 0
        pid = int(self._info.pid) if isinstance(self._info.pid, int) else 0
        label = f'led:{getattr(self._info, "device_index", 0)} [{vid:04X}:{pid:04X} PM={pm} SUB={sub}]'
        self.log = logging.getLogger(f'{__name__}.{label}')
        if hasattr(self.log, 'dev'):
            self.log.dev = label  # type: ignore[attr-defined]
        self.log.info("LED connected: %s style=%s", self._info.path, self._init_status)
        return {"success": True, "status": self._init_status or ""}

    # ══════════════════════════════════════════════════════════════════════
    # LCD tick
    # ══════════════════════════════════════════════════════════════════════

    def _tick_lcd(self) -> Any:
        """Render overlay + send frame to LCD device."""
        if not self._display_svc or self._display_svc.is_video_playing():
            return None
        new_frame = None
        if self._display_svc.overlay.enabled and self._display_svc.overlay.would_change(
            self._display_svc.overlay.metrics
        ):
            new_frame = self._display_svc.render_overlay()
            if new_frame:
                self.log.debug("tick: new overlay frame rendered")
                self._last_overlay_frame = new_frame
        image = new_frame or getattr(self, '_last_overlay_frame', None) or self._display_svc.current_image
        if image:
            self.send(image)
        return new_frame

    # ══════════════════════════════════════════════════════════════════════
    # LED tick
    # ══════════════════════════════════════════════════════════════════════

    def _tick_led(self) -> None:
        """Advance one LED animation frame and send to hardware."""
        if not self._led_svc:
            log.debug("tick: no service — skipping")
            return
        colors = self._led_svc.tick()
        if self._led_svc.has_protocol:
            ok = self._led_svc.send_colors(colors)
            if not ok:
                log.debug("tick: send_colors skipped (concurrent)")

    def tick_with_result(self) -> dict:
        """Advance one animation frame. Returns colors + display_colors (GUI use)."""
        if not self._led_svc:
            log.debug("tick_with_result: no service — skipping")
            return {"colors": [], "display_colors": []}
        colors = self._led_svc.tick()
        display_colors = self._led_svc.apply_mask(colors)
        if self._led_svc.has_protocol:
            ok = self._led_svc.send_colors(colors)
            if not ok:
                log.debug("tick_with_result: send_colors skipped (concurrent)")
        return {"colors": colors, "display_colors": display_colors}

    # ══════════════════════════════════════════════════════════════════════
    # LCD properties
    # ══════════════════════════════════════════════════════════════════════

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
        """Direct OverlayService access."""
        return self._display_svc.overlay if self._display_svc else None

    # ══════════════════════════════════════════════════════════════════════
    # LED properties
    # ══════════════════════════════════════════════════════════════════════

    @property
    def status(self) -> str | None:
        return self._init_status

    @property
    def service(self) -> Any:
        """Direct service access — LEDService for LED, OverlayService for LCD."""
        if self._led_svc:
            return self._led_svc
        return self._display_svc.overlay if self._display_svc else None

    @property
    def state(self) -> Any:
        """Current LEDState (LED only)."""
        return self._led_svc.state if self._led_svc else None

    # ══════════════════════════════════════════════════════════════════════
    # LCD — connection helpers
    # ══════════════════════════════════════════════════════════════════════

    def set_data_ready_callback(self, fn: Any) -> None:
        if self._display_svc is not None:
            self._display_svc.on_data_ready = fn

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

    # ══════════════════════════════════════════════════════════════════════
    # LCD — frame ops
    # ══════════════════════════════════════════════════════════════════════

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
        self.log.debug("send: image=%s", type(image).__name__ if image else None)
        if not self._device_svc.selected:
            return {"success": False, "error": "No device selected"}
        w, h = self.lcd_size
        self._device_svc.send_frame_async(image, w, h)
        return {"success": True}

    def send_frame(self, image: Any) -> bool:
        """Synchronously send image to LCD device."""
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

    # ══════════════════════════════════════════════════════════════════════
    # LCD — display settings
    # ══════════════════════════════════════════════════════════════════════

    def _persist(self, field: str, value: object) -> None:
        dev = self._device_svc.selected if self._device_svc else None
        if dev and self._lcd_config:
            self._lcd_config.persist(dev, field, value)

    def persist_dirs(self) -> None:
        """Write device's native-resolution dirs to config."""
        o = self.orientation
        if not isinstance(o, Orientation) or not o.data_root:
            return
        w, h = o.native
        if not w or not h:
            return
        td = o.data_root / theme_dir_name(w, h)
        self._persist('theme_dir', str(td) if td.exists() else None)
        web = o.data_root / 'web' / web_dir_name(w, h)
        self._persist('web_dir', str(web) if web.exists() else None)
        masks = o.data_root / 'web' / masks_dir_name(w, h)
        self._persist('masks_dir', str(masks) if masks.exists() else None)

    def refresh_dirs(self) -> None:
        """Re-probe filesystem dirs and update config."""
        if self._display_svc:
            self._display_svc.refresh_dirs()
            self.orientation = self._display_svc.orientation
        self.persist_dirs()

    def restore_device_settings(self) -> None:
        """Restore brightness + rotation from per-device config."""
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
        """Set brightness — routes to LCD display or LED strip."""
        if self._led_svc:
            return self._led_set_brightness(percent)
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
        old_theme_dir = svc.theme_dir
        saved_mask_dir = svc.mask_source_dir
        self.log.debug("set_rotation: %d° saved_mask_dir=%s old_theme_dir=%s",
                  degrees, saved_mask_dir,
                  old_theme_dir.path if old_theme_dir else None)
        image = svc.set_rotation(degrees)
        self._persist('rotation', degrees)

        new_theme_dir = svc.theme_dir
        theme_dir_changed = (old_theme_dir != new_theme_dir)
        if old_canvas != svc.canvas_size and theme_dir_changed:
            self.log.info("set_rotation: theme dir changed %s→%s, reloading",
                     old_theme_dir.path if old_theme_dir else None,
                     new_theme_dir.path if new_theme_dir else None)
            reloaded = self._reload_theme_for_rotation()
            if reloaded is not None:
                image = reloaded
        elif old_canvas != svc.canvas_size:
            self.log.info("set_rotation: canvas changed %s→%s but theme dir "
                     "unchanged — pixel-rotating only",
                     old_canvas, svc.canvas_size)

        w, h = self.orientation.native
        if w != h and saved_mask_dir:
            is_zt_mask = saved_mask_dir.parent.name.startswith('zt')
            if is_zt_mask:
                self.log.info("set_rotation: reloading zt mask from saved_mask_dir=%s",
                         saved_mask_dir)
                image = self._reload_mask_for_rotation(svc, saved_mask_dir) or image
            else:
                self.log.debug("set_rotation: skipping mask reload — "
                          "theme built-in mask %s", saved_mask_dir)

        return {"success": True, "image": image,
                "message": f"Rotation set to {degrees}°"}

    def _reload_theme_for_rotation(self) -> Any | None:
        current = self.current_theme_path
        if not current:
            self.log.debug("_reload_theme_for_rotation: no current_theme_path")
            return None
        theme_name = current.name
        svc = self._display_svc
        for base in (svc.local_dir, svc.web_dir):
            if not base:
                continue
            candidate = Path(base) / theme_name
            if candidate.exists():
                self.log.info("_reload_theme_for_rotation: %s → %s", theme_name, candidate)
                theme = self._theme_info_from_dir_fn(candidate)
                result = self.select(theme)

                overlay_cfg = self.load_overlay_config_from_dir(str(candidate))
                if overlay_cfg:
                    if self._lcd_config:
                        self._lcd_config.apply_format_prefs(overlay_cfg)
                    self.set_config(overlay_cfg)
                    self.enable_overlay(True)
                    rendered = svc.render_and_process()
                    return rendered
                else:
                    self.enable_overlay(False)
                return result.get('image')
        self.log.debug("_reload_theme_for_rotation: theme '%s' not in new dirs", theme_name)
        return None

    def _reload_mask_for_rotation(
        self, svc: Any, saved_mask_dir: Path | None = None,
    ) -> Any | None:
        old_mask_dir = saved_mask_dir or svc.mask_source_dir
        if not old_mask_dir or not svc.masks_dir:
            self.log.debug("_reload_mask_for_rotation: no mask dir to reload "
                      "(old=%s, masks_dir=%s)", old_mask_dir, svc.masks_dir)
            return None
        mask_name = old_mask_dir.name
        new_mask_dir = Path(svc.masks_dir) / mask_name
        if new_mask_dir.exists():
            self.log.info("_reload_mask_for_rotation: %s → %s", old_mask_dir, new_mask_dir)
            if self.orientation._is_rotated():
                ow, oh = svc.output_resolution
                svc.overlay.set_resolution(ow, oh)
                self.log.info("_reload_mask_for_rotation: portrait → overlay %dx%d", ow, oh)
            else:
                cw, ch = svc.canvas_size
                svc.overlay.set_resolution(cw, ch)
                self.log.info("_reload_mask_for_rotation: landscape → overlay %dx%d", cw, ch)
            overlay_cfg = self.load_overlay_config_from_dir(str(new_mask_dir))
            if overlay_cfg:
                if self._lcd_config:
                    self._lcd_config.apply_format_prefs(overlay_cfg)
                self.set_config(overlay_cfg)
                self.enable_overlay(True)
            self.load_mask_standalone(str(new_mask_dir))
            return svc.render_and_process()
        self.log.debug("_reload_mask_for_rotation: mask '%s' not in new masks dir %s",
                  mask_name, svc.masks_dir)
        svc.overlay.set_theme_mask(None)
        svc.mask_source_dir = None
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

    # ══════════════════════════════════════════════════════════════════════
    # LCD — theme ops
    # ══════════════════════════════════════════════════════════════════════

    def restore_last_theme(self) -> dict:
        """Restore theme, mask, and overlay from per-device config."""
        dev = self._device_svc.selected if self._device_svc else None
        if not dev or not self._lcd_config:
            return {"success": False, "error": "No device selected"}
        cfg = self._lcd_config.get_config(dev)

        theme_name = cfg.get("theme_name")
        theme_type = cfg.get("theme_type", "local")

        if not theme_name:
            old_path = cfg.get("theme_path")
            if not old_path:
                return {"success": False, "error": "No saved theme"}
            self.log.info("restore_last_theme: migrating old config theme_path=%s", old_path)
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
            self.log.info("restore_last_theme: migrated → name=%s type=%s", theme_name, theme_type)

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
            old_path = cfg.get("theme_path", "")
            if not old_path or not Path(old_path).exists():
                return {"success": False, "error": "Image not found"}
            result = self.load_image(old_path)
            return {**result, "overlay_config": None,
                    "overlay_enabled": False, "is_animated": False}
        else:
            td = self.orientation.theme_dir
            if not td:
                return {"success": False, "error": "No theme directory"}
            path = td.path / theme_name
            if not path.exists():
                utd = self.orientation.user_theme_dir
                if utd:
                    user_path = utd / theme_name
                    if user_path.exists():
                        self.log.info("restore_last_theme: found in user content dir: %s", user_path)
                        path = user_path
                if not path.exists():
                    return {"success": False, "error": f"Theme not found: {theme_name}"}
            theme = self._theme_info_from_dir_fn(path, (w, h))

        result = self.select(theme)
        if not result.get("success"):
            return {**result, "overlay_config": None,
                    "overlay_enabled": False, "is_animated": False}

        # Mask
        mask_id = cfg.get("mask_id") or ""
        if not mask_id:
            old_path = cfg.get("mask_path")
            if old_path:
                mask_id = Path(old_path).name
        if mask_id:
            is_custom = cfg.get("mask_custom", False)
            o = self.orientation
            base = o.user_masks_dir if is_custom else o.masks_dir
            mask_dir = Path(base) / mask_id if base else None
            if mask_dir and mask_dir.exists():
                svc = self._display_svc
                already_loaded = (svc and svc.mask_source_dir == mask_dir)
                if not already_loaded:
                    self.load_mask_standalone(str(mask_dir))

        # Overlay
        overlay_cfg = cfg.get("overlay", {})
        overlay_enabled = False
        overlay_config = None
        if overlay_cfg:
            overlay_enabled = overlay_cfg.get("enabled", False)
            overlay_config = overlay_cfg.get("config") or None
            if overlay_config:
                self.set_config(overlay_config)
            self.enable(overlay_enabled)

        # Send
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
        return self.restore_last_theme()

    def collect_other_device_resolutions(self) -> list[tuple[int, int]]:
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

    def select(self, theme: Any) -> dict:
        """Select and load a theme (local or cloud)."""
        self.log.debug("select: theme=%s type=%s",
                  getattr(theme, 'name', theme),
                  type(theme).__name__)
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
        w, h = (width, height) if width and height else self.lcd_size
        td = self.orientation.theme_dir
        theme_dir = td.path if td else Path(resolve_theme_dir(w, h))
        utd = self.orientation.user_theme_dir
        themes = self._theme_svc.discover_local_merged(
            theme_dir, utd, (w, h))
        match = next((t for t in themes if t.name == name), None)
        if not match:
            return {"success": False, "error": f"Theme '{name}' not found"}

        result = self.select(match)
        if not result.get("success"):
            return result

        image = result.get("image")
        is_animated = result.get("is_animated", False)

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

        result["theme_path"] = match.path
        result["config_path"] = match.config_path

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
        self._display_svc.mask_source_dir = p.parent
        return {"success": True, "message": f"Mask: {p.name}"}

    def export_config(self, path: Any) -> dict:
        ok, msg = self._display_svc.export_config(Path(path))
        return {"success": ok, "message": msg}

    def import_config(self, path: Any, data_dir: Any) -> dict:
        ok, msg = self._display_svc.import_config(Path(path), Path(data_dir))
        return {"success": ok, "message": msg}

    # ══════════════════════════════════════════════════════════════════════
    # LCD — standalone overlay/mask (CLI)
    # ══════════════════════════════════════════════════════════════════════

    def render_overlay_from_dc(self, dc_path: str, *, send: bool = False,
                               output: str | None = None,
                               metrics: Any = None) -> dict:
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
        from ..services import ImageService, OverlayService

        if not os.path.exists(mask_path):
            return {"success": False, "error": f"Path not found: {mask_path}"}
        if not self._display_svc:
            return {"success": False, "error": "Display service not initialized"}

        p = Path(mask_path)
        mask_dir = p if p.is_dir() else p.parent
        is_zt = mask_dir.parent.name.startswith('zt')
        if is_zt and self.orientation._is_rotated():
            w, h = self._display_svc.output_resolution
            self._display_svc.overlay.set_resolution(w, h)
            self.log.info("load_mask_standalone: portrait zt mask → overlay %dx%d", w, h)
        else:
            w, h = self._display_svc.canvas_size
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

        mask_w, mask_h = r.surface_size(mask_img)
        dc_path = (p if p.is_dir() else p.parent) / 'config1.dc'
        position = self._parse_mask_position(dc_path, mask_w, mask_h, w, h)

        if self._display_svc:
            ovl = self._display_svc.overlay
            ovl.set_theme_mask(None)
            ovl.set_mask(mask_img, position)
            ovl.enabled = True
            self._display_svc.mask_source_dir = p if p.is_dir() else p.parent
            self.log.debug("load_mask_standalone: mask_source_dir=%s", self._display_svc.mask_source_dir)
            bg = self._display_svc.clean_background or \
                self._display_svc.current_image or \
                ImageService.solid_color(0, 0, 0, w, h)
            self._display_svc.current_image = bg
            self._display_svc.invalidate_video_cache()
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
        if mask_w >= lcd_w and mask_h >= lcd_h:
            return (0, 0)
        if not dc_path or not dc_path.exists():
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
            self.log.warning("DC config parse failed for %s — using centered mask position: %s",
                        dc_path, e)
        return ((lcd_w - mask_w) // 2, (lcd_h - mask_h) // 2)

    # ══════════════════════════════════════════════════════════════════════
    # LCD — overlay ops
    # ══════════════════════════════════════════════════════════════════════

    def set_flash_index(self, index: int) -> dict:
        if self._display_svc and self._display_svc.overlay:
            self._display_svc.overlay.flash_skip_index = index
        return {"success": True, "index": index}

    def set_mask_position(self, x: int, y: int) -> dict:
        if self._display_svc and self._display_svc.overlay:
            self._display_svc.overlay.theme_mask_position = (x, y)
            self._display_svc.overlay._invalidate_cache()
        return {"success": True, "message": f"Mask position: ({x}, {y})"}

    def render_and_send(self) -> dict:
        if not self._display_svc:
            return {"success": False, "image": None}
        image = self._display_svc.render_overlay()
        if image and self.auto_send and self.connected:
            self.send(image)
        return {"success": True, "image": image}

    def enable(self, on: bool) -> dict:
        self._display_svc.overlay.enabled = on
        return {"success": True, "enabled": on,
                "message": f"Overlay: {'on' if on else 'off'}"}

    def enable_overlay(self, on: bool) -> dict:
        return self.enable(on)

    def set_config(self, config: dict) -> dict:
        ovl = self._display_svc.overlay
        w, h = ovl.width, ovl.height
        ovl.set_config_resolution(w, h)
        self._display_svc.overlay.set_config(config)
        return {"success": True, "message": f"Overlay config: {len(config)} elements"}

    def set_background(self, image: Any) -> dict:
        self._display_svc.overlay.set_background(image)
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
    def is_overlay_enabled(self) -> bool:
        return self.enabled

    @property
    def last_metrics(self) -> Any:
        return self._display_svc.overlay.metrics if self._display_svc else None

    def load_overlay_config_from_dir(self, theme_dir: str) -> dict | None:
        p = Path(theme_dir)
        overlay_config: dict | None = None

        json_path = p / 'config.json'
        if json_path.exists() and self._load_config_json_fn is not None:
            try:
                result = self._load_config_json_fn(str(json_path))
                if result is not None:
                    overlay_config = result[0]
                    self.log.debug("load_overlay_config_from_dir: loaded from config.json")
            except Exception as e:
                self.log.warning("load_overlay_config_from_dir: config.json parse failed: %s", e)

        if overlay_config is None and self._dc_config_cls is not None:
            dc_path = p / 'config1.dc'
            if dc_path.exists():
                try:
                    overlay_config = self._dc_config_cls(dc_path).to_overlay_config()
                    self.log.debug("load_overlay_config_from_dir: loaded from config1.dc")
                except Exception as e:
                    self.log.warning("load_overlay_config_from_dir: config1.dc parse failed: %s", e)

        return overlay_config or None

    # ══════════════════════════════════════════════════════════════════════
    # LCD — video playback
    # ══════════════════════════════════════════════════════════════════════

    def load(self, path: Any) -> dict:
        self._display_svc.invalidate_video_cache()
        success = self._display_svc.media.load(Path(path))
        if success:
            self._display_svc.convert_media_frames()
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

    def video_tick(self) -> dict | None:
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

    def load_video(self, path: Any) -> dict:
        return self.load(path)

    def play_video(self) -> dict:
        return self.play()

    def stop_video(self) -> dict:
        return self.stop()

    def video_has_frames(self) -> bool:
        return self.has_frames

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
        if not self._display_svc:
            return {"success": False, "error": "DisplayService not initialized"}
        self.log.info("play_video_loop: %s overlay=%s mask=%s",
                 video_path, bool(overlay_config), bool(mask_path))
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

    def keep_alive_loop(
        self,
        *,
        interval: float = 0.150,
        duration: float = 0,
        metrics_fn: Any | None = None,
        on_frame: Any | None = None,
    ) -> dict:
        if not self._display_svc:
            return {"success": False, "error": "DisplayService not initialized"}
        return self._display_svc.run_static_loop(
            interval=interval, duration=duration,
            metrics_fn=metrics_fn, on_frame=on_frame,
        )

    # Overlay convenience aliases
    def set_overlay_temp_unit(self, unit: int) -> dict:
        return self.set_temp_unit(unit)

    def set_overlay_background(self, image: Any) -> dict:
        return self.set_background(image)

    def set_overlay_mask(self, mask: Any,
                         position: tuple[int, int] | None = None) -> dict:
        return self.set_mask(mask, position)

    def set_overlay_mask_visible(self, visible: bool) -> dict:
        return self.set_mask_visible(visible)

    # ══════════════════════════════════════════════════════════════════════
    # LCD — lifecycle
    # ══════════════════════════════════════════════════════════════════════

    def initialize(self, data_dir: Any) -> dict:
        if not self._display_svc:
            return {"success": False, "error": "Not connected"}
        data_dir = Path(data_dir)
        self.log.debug("Device: initializing, data_dir=%s", data_dir)
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

    # ══════════════════════════════════════════════════════════════════════
    # LED — lifecycle (GUI path)
    # ══════════════════════════════════════════════════════════════════════

    def initialize_led(self, device: Any, led_style: int) -> dict:
        """Initialize for a known LED device (GUI — device already detected)."""
        if not self._led_svc:
            self._led_svc = self._led_svc_factory(
                get_protocol=self._get_protocol,
                led_config=self._led_config,
            )
        self._info = device
        self._init_status = self._led_svc.initialize(device, led_style)
        return {"success": True, "status": self._init_status or "",
                "style": led_style}

    # ══════════════════════════════════════════════════════════════════════
    # LED — state-only mutators (GUI — timer handles send)
    # ══════════════════════════════════════════════════════════════════════

    def update_color(self, r: int, g: int, b: int) -> None:
        self._led_svc.set_color(r, g, b)

    def update_mode(self, mode: LEDMode | int) -> None:
        resolved = LEDMode(mode) if isinstance(mode, int) else mode
        self._led_svc.set_mode(resolved)

    def update_brightness(self, level: int) -> None:
        self._led_svc.set_brightness(max(0, min(100, level)))

    def update_global_on(self, on: bool) -> None:
        self._led_svc.toggle_global(on)

    def update_segment(self, index: int, on: bool) -> None:
        self._led_svc.toggle_segment(index, on)

    def update_zone_color(self, zone: int, r: int, g: int, b: int) -> None:
        self._led_svc.set_zone_color(zone, r, g, b)

    def update_zone_mode(self, zone: int, mode: LEDMode | int) -> None:
        resolved = LEDMode(mode) if isinstance(mode, int) else mode
        self._led_svc.set_zone_mode(zone, resolved)

    def update_zone_brightness(self, zone: int, level: int) -> None:
        self._led_svc.set_zone_brightness(zone, max(0, min(100, level)))

    def update_zone_on(self, zone: int, on: bool) -> None:
        self._led_svc.toggle_zone(zone, on)

    def update_zone_sync(self, enabled: bool) -> None:
        self._led_svc.set_zone_sync(enabled)

    def update_zone_sync_zone(self, zone: int, selected: bool) -> None:
        self._led_svc.set_zone_sync_zone(zone, selected)

    def update_zone_sync_interval(self, seconds: int) -> None:
        self._led_svc.set_zone_sync_interval(seconds)

    def update_clock_format(self, is_24h: bool) -> None:
        self._led_svc.set_clock_format(is_24h)

    def update_week_start(self, is_sunday: bool) -> None:
        self._led_svc.set_week_start(is_sunday)

    def update_disk_index(self, index: int) -> None:
        self._led_svc.set_disk_index(index)

    def update_memory_ratio(self, ratio: int) -> None:
        self._led_svc.set_memory_ratio(ratio)

    def update_test_mode(self, enabled: bool) -> None:
        self._led_svc.set_test_mode(enabled)

    def update_selected_zone(self, zone: int) -> None:
        self._led_svc.set_selected_zone(zone)

    # ══════════════════════════════════════════════════════════════════════
    # LED — command methods (CLI/API — immediate tick/send/save)
    # ══════════════════════════════════════════════════════════════════════

    def _led_apply_and_send(self) -> list:
        self._led_svc.toggle_global(True)
        colors = self._led_svc.tick()
        self._led_svc.send_colors(colors)
        self._led_svc.save_config()
        return colors

    def _led_send_and_save(self) -> None:
        self._led_svc.send_tick()
        self._led_svc.save_config()

    def _resolve_mode(self, mode: LEDMode | str | int) -> LEDMode | None:
        match mode:
            case LEDMode():
                return mode
            case int() if mode in LEDMode._value2member_map_:
                return LEDMode(mode)
            case str() if mode.upper() in LEDMode._member_map_:
                return LEDMode[mode.upper()]
            case _:
                return None

    def _validate_zone(self, zone: int) -> dict | None:
        n = len(self._led_svc.state.zones)
        if n == 0:
            return {"success": False, "error": "This LED device has no zones"}
        if zone < 0 or zone >= n:
            return {"success": False,
                    "error": f"Zone {zone} out of range (valid: 0–{n - 1})"}
        return None

    def _validate_segment(self, index: int) -> dict | None:
        n = len(self._led_svc.state.segment_on)
        if n == 0:
            return {"success": False,
                    "error": "This LED device has no segments"}
        if index < 0 or index >= n:
            return {"success": False,
                    "error": f"Segment {index} out of range (valid: 0–{n - 1})"}
        return None

    @_forward_to_proxy
    def set_color(self, r: int, g: int, b: int) -> dict:
        self._led_svc.set_mode(LEDMode.STATIC)
        self._led_svc.set_color(r, g, b)
        colors = self._led_apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"LED color set to #{r:02x}{g:02x}{b:02x}"}

    @_forward_to_proxy
    def set_mode(self, mode: LEDMode | str | int) -> dict:
        resolved = self._resolve_mode(mode)
        if not resolved:
            return {"success": False, "error": f"Unknown mode '{mode}'",
                    "available": [m.name.lower() for m in LEDMode]}
        self._led_svc.set_mode(resolved)
        colors = self._led_apply_and_send()
        animated = resolved in (LEDMode.BREATHING, LEDMode.COLORFUL,
                                LEDMode.RAINBOW, LEDMode.TEMP_LINKED,
                                LEDMode.LOAD_LINKED)
        return {"success": True, "colors": colors, "animated": animated,
                "message": f"LED mode: {resolved.name.lower()}"}

    def _led_set_brightness(self, level: int) -> dict:
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}
        self._led_svc.set_brightness(level)
        colors = self._led_apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"LED brightness set to {level}%"}

    @_forward_to_proxy
    def toggle_global(self, on: bool) -> dict:
        self._led_svc.toggle_global(on)
        self._led_send_and_save()
        return {"success": True, "message": f"LEDs {'on' if on else 'off'}"}

    @_forward_to_proxy
    def off(self) -> dict:
        self._led_svc.toggle_global(False)
        self._led_send_and_save()
        return {"success": True, "message": "LEDs turned off"}

    @_forward_to_proxy
    def set_sensor_source(self, source: str) -> dict:
        source = source.lower()
        if source not in ('cpu', 'gpu'):
            return {"success": False,
                    "error": "Source must be 'cpu' or 'gpu'"}
        self._led_svc.set_sensor_source(source)
        self._led_svc.save_config()
        return {"success": True,
                "message": f"LED sensor source set to {source.upper()}"}

    @_forward_to_proxy
    def set_zone_color(self, zone: int, r: int, g: int, b: int) -> dict:
        if err := self._validate_zone(zone):
            return err
        self._led_svc.set_zone_color(zone, r, g, b)
        colors = self._led_apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} color set to #{r:02x}{g:02x}{b:02x}"}

    @_forward_to_proxy
    def set_zone_mode(self, zone: int, mode: LEDMode | str | int) -> dict:
        if err := self._validate_zone(zone):
            return err
        resolved = self._resolve_mode(mode)
        if not resolved:
            return {"success": False, "error": f"Unknown mode '{mode}'"}
        self._led_svc.set_zone_mode(zone, resolved)
        colors = self._led_apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} mode set to {resolved.name.lower()}"}

    @_forward_to_proxy
    def set_zone_brightness(self, zone: int, level: int) -> dict:
        if err := self._validate_zone(zone):
            return err
        if level < 0 or level > 100:
            return {"success": False, "error": "Brightness must be 0-100"}
        self._led_svc.set_zone_brightness(zone, level)
        colors = self._led_apply_and_send()
        return {"success": True, "colors": colors,
                "message": f"Zone {zone} brightness set to {level}%"}

    @_forward_to_proxy
    def toggle_zone(self, zone: int, on: bool) -> dict:
        if err := self._validate_zone(zone):
            return err
        self._led_svc.toggle_zone(zone, on)
        self._led_send_and_save()
        return {"success": True,
                "message": f"Zone {zone} {'ON' if on else 'OFF'}"}

    @_forward_to_proxy
    def set_zone_sync(self, enabled: bool,
                      interval: int | None = None) -> dict:
        if interval is not None:
            self._led_svc.set_zone_sync_interval(interval)
        self._led_svc.set_zone_sync(enabled)
        self._led_send_and_save()
        return {"success": True,
                "message": f"Zone sync {'enabled' if enabled else 'disabled'}"}

    def set_zone_sync_zone(self, zone: int, selected: bool) -> dict:
        self._led_svc.set_zone_sync_zone(zone, selected)
        return {"success": True}

    def set_zone_sync_interval(self, seconds: int) -> dict:
        self._led_svc.set_zone_sync_interval(seconds)
        return {"success": True}

    def set_selected_zone(self, zone: int) -> dict:
        self._led_svc.set_selected_zone(zone)
        return {"success": True}

    @_forward_to_proxy
    def toggle_segment(self, index: int, on: bool) -> dict:
        if err := self._validate_segment(index):
            return err
        self._led_svc.toggle_segment(index, on)
        self._led_send_and_save()
        return {"success": True,
                "message": f"Segment {index} {'ON' if on else 'OFF'}"}

    @_forward_to_proxy
    def set_clock_format(self, is_24h: bool) -> dict:
        self._led_svc.set_clock_format(is_24h)
        self._led_send_and_save()
        return {"success": True,
                "message": f"Clock format set to {'24h' if is_24h else '12h'}"}

    @_forward_to_proxy
    def set_week_start(self, is_sunday: bool) -> dict:
        self._led_svc.set_week_start(is_sunday)
        self._led_send_and_save()
        return {"success": True}

    def set_seg_temp_unit(self, unit: int) -> dict:
        return self.set_temp_unit(unit)

    def set_disk_index(self, index: int) -> dict:
        self._led_svc.set_disk_index(index)
        return {"success": True}

    def set_memory_ratio(self, ratio: int) -> dict:
        self._led_svc.set_memory_ratio(ratio)
        return {"success": True}

    def set_test_mode(self, enabled: bool) -> dict:
        self._led_svc.set_test_mode(enabled)
        return {"success": True}

    def save_config(self) -> None:
        if self._led_svc:
            self._led_svc.save_config()

    def load_config(self) -> None:
        if self._led_svc:
            self._led_svc.load_config()
