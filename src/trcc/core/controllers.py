"""
TRCC Controllers — Driving adapters for PyQt6 GUI.

Two Facades: LCDDeviceController (LCD display pipeline) and
LEDDeviceController (LED RGB effects). All business logic lives
in the service layer; controllers route GUI calls and fire callbacks.
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Callable, List, Optional, Tuple

from ..services import (
    DeviceService,
    MediaService,
    OverlayService,
    ThemeService,
)
from ..services.display import DisplayService
from .models import (
    DeviceInfo,
    PlaybackState,
    ThemeInfo,
    ThemeType,
    VideoState,
)

log = logging.getLogger(__name__)


class LCDDeviceController:
    """LCD controller — Facade over DisplayService + ThemeService.

    Routes GUI calls to the right service, fires callbacks to update
    the view. No business logic — pure delegation + notification.
    """

    CATEGORIES = ThemeService.CATEGORIES

    def __init__(self, renderer=None):
        # Single renderer for entire pipeline (DI)
        if renderer is None:
            from ..adapters.render.qt import QtRenderer
            renderer = QtRenderer()

        # Set renderer on ImageService (global facade)
        from ..services.image import ImageService
        ImageService.set_renderer(renderer)

        # Create shared services
        device_svc = DeviceService()
        overlay_svc = OverlayService(renderer=renderer)
        media_svc = MediaService()

        # The head chef
        self._display = DisplayService(device_svc, overlay_svc, media_svc)

        # Theme service (standalone — DisplayService uses static methods)
        self._theme_svc = ThemeService()

        # View callbacks — LCD
        self.on_preview_update: Optional[Callable[[Any], None]] = None
        self.on_status_update: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None

        # View callbacks — Device
        self.on_device_selected: Optional[Callable[[DeviceInfo], None]] = None
        self.on_send_complete: Optional[Callable[[bool], None]] = None

        # View callbacks — Video
        self.on_video_loaded: Optional[Callable[[VideoState], None]] = None
        self.on_video_state_changed: Optional[Callable[[PlaybackState], None]] = None

        # View callbacks — Overlay
        self.on_overlay_config_changed: Optional[Callable[[], None]] = None

    # ── Service accessors ─────────────────────────────────────────────

    @property
    def lcd_svc(self) -> DisplayService:
        return self._display

    @property
    def theme_svc(self) -> ThemeService:
        return self._theme_svc

    @property
    def device_svc(self) -> DeviceService:
        return self._display.devices

    @property
    def overlay_svc(self) -> OverlayService:
        return self._display.overlay

    @property
    def media_svc(self) -> MediaService:
        return self._display.media

    # ── Display properties ────────────────────────────────────────────

    @property
    def working_dir(self) -> Path:
        return self._display.working_dir

    @property
    def lcd_width(self) -> int:
        return self._display.lcd_width

    @property
    def lcd_height(self) -> int:
        return self._display.lcd_height

    @property
    def current_image(self) -> Any:
        return self._display.current_image

    @current_image.setter
    def current_image(self, value: Any):
        self._display.current_image = value

    @property
    def current_theme_path(self) -> Optional[Path]:
        return self._display.current_theme_path

    @current_theme_path.setter
    def current_theme_path(self, value: Optional[Path]):
        self._display.current_theme_path = value

    @property
    def auto_send(self) -> bool:
        return self._display.auto_send

    @auto_send.setter
    def auto_send(self, value: bool):
        self._display.auto_send = value

    @property
    def rotation(self) -> int:
        return self._display.rotation

    @rotation.setter
    def rotation(self, value: int):
        self._display.rotation = value

    @property
    def brightness(self) -> int:
        return self._display.brightness

    @brightness.setter
    def brightness(self, value: int):
        self._display.brightness = value

    # ── Initialization ────────────────────────────────────────────────

    def initialize(self, data_dir: Path):
        log.debug("Initializing controller, data_dir=%s", data_dir)
        self._display.initialize(data_dir)

        self.set_theme_directories(
            local_dir=self._display.local_dir,
            web_dir=self._display.web_dir,
            masks_dir=self._display.masks_dir,
        )

        self._display.media.set_target_size(self.lcd_width, self.lcd_height)
        self._display.overlay.set_resolution(self.lcd_width, self.lcd_height)

        if self.lcd_width and self.lcd_height:
            self.load_local_themes((self.lcd_width, self.lcd_height))

        self.detect_devices()

    def cleanup(self):
        self._display.cleanup()

    # ── Theme operations ──────────────────────────────────────────────

    def set_theme_directories(self,
                              local_dir: Optional[Path] = None,
                              web_dir: Optional[Path] = None,
                              masks_dir: Optional[Path] = None):
        self._theme_svc.set_directories(local_dir, web_dir, masks_dir)

    def load_local_themes(self, resolution: Tuple[int, int] = (320, 320)):
        self._theme_svc.load_local_themes(resolution)

    def select_theme(self, theme: ThemeInfo):
        """Select a theme — routes to local or cloud loader."""
        self._theme_svc.select(theme)
        if theme:
            if theme.theme_type == ThemeType.CLOUD:
                self.load_cloud_theme(theme)
            else:
                self.load_local_theme(theme)

    def get_themes(self) -> List[ThemeInfo]:
        return self._theme_svc.themes

    def get_selected_theme(self) -> Optional[ThemeInfo]:
        return self._theme_svc.selected

    # ── Device operations ─────────────────────────────────────────────

    def detect_devices(self):
        self._display.devices.detect()
        if self._display.devices.selected and self.on_device_selected:
            self.on_device_selected(self._display.devices.selected)

    def select_device(self, device: DeviceInfo):
        self._display.devices.select(device)
        if self.on_device_selected:
            self.on_device_selected(device)

    def get_devices(self) -> List[DeviceInfo]:
        return self._display.devices.devices

    def get_selected_device(self) -> Optional[DeviceInfo]:
        return self._display.devices.selected

    def send_image_async(self, rgb565_data: bytes, width: int, height: int):
        if self._display.devices.is_busy:
            log.debug("send_image_async: busy, skipping")
            return
        log.debug("send_image_async: dispatching %d bytes (%dx%d)",
                  len(rgb565_data), width, height)
        self._display.devices.send_rgb565_async(rgb565_data, width, height)

    def send_pil_async(self, image: Any, width: int, height: int,
                       byte_order: str = '>'):
        if self._display.devices.is_busy:
            return
        self._display.devices.send_pil_async(image, width, height)

    # ── Video operations ──────────────────────────────────────────────

    def load_video(self, path: Path) -> bool:
        success = self._display.media.load(path)
        if success and self.on_video_loaded:
            self.on_video_loaded(self._display.media.state)
        return success

    def play_video(self):
        self._display.media.play()
        if self.on_video_state_changed:
            self.on_video_state_changed(self._display.media.state.state)

    def pause_video(self):
        self._display.media.pause()
        if self.on_video_state_changed:
            self.on_video_state_changed(self._display.media.state.state)

    def stop_video(self):
        self._display.media.stop()
        if self.on_video_state_changed:
            self.on_video_state_changed(self._display.media.state.state)

    def toggle_play_pause(self):
        self._display.media.toggle()
        if self.on_video_state_changed:
            self.on_video_state_changed(self._display.media.state.state)

    def video_has_frames(self) -> bool:
        return self._display.media.has_frames

    # ── Overlay operations ────────────────────────────────────────────

    def enable_overlay(self, enabled: bool = True):
        self._display.overlay.enabled = enabled

    def is_overlay_enabled(self) -> bool:
        return self._display.overlay.enabled

    def set_overlay_config(self, config: dict):
        self._display.overlay.set_config(config)
        if self.on_overlay_config_changed:
            self.on_overlay_config_changed()

    def set_overlay_background(self, image: Any):
        self._display.overlay.set_background(image)

    def set_overlay_theme_mask(self, image: Any = None,
                               position: tuple[int, int] | None = None):
        self._display.overlay.set_theme_mask(image, position)

    def get_overlay_theme_mask(self) -> tuple[Any, tuple[int, int] | None]:
        return self._display.overlay.get_mask()

    def set_overlay_mask_visible(self, visible: bool):
        self._display.overlay.set_mask_visible(visible)

    def set_overlay_temp_unit(self, unit: int):
        self._display.overlay.set_temp_unit(unit)

    def update_overlay_metrics(self, metrics: Any):
        self._display.overlay.update_metrics(metrics)

    def overlay_has_changed(self, metrics: Any) -> bool:
        """Check if overlay would produce a visually different frame."""
        return self._display.overlay.would_change(metrics)

    def render_overlay(self, background: Any = None, **kwargs) -> Any:
        """Render overlay onto background. No-arg = use current image."""
        if background is None and not kwargs:
            return self._display.render_overlay()
        return self._display.overlay.render(background, **kwargs)

    @property
    def overlay_flash_skip_index(self) -> int:
        return self._display.overlay.flash_skip_index

    @overlay_flash_skip_index.setter
    def overlay_flash_skip_index(self, value: int):
        self._display.overlay.flash_skip_index = value

    # ── Resolution ────────────────────────────────────────────────────

    def set_resolution(self, width: int, height: int, persist: bool = True):
        if width == self.lcd_width and height == self.lcd_height:
            return
        self._display.set_resolution(width, height, persist=persist)

        self.set_theme_directories(
            local_dir=self._display.local_dir,
            web_dir=self._display.web_dir,
            masks_dir=self._display.masks_dir,
        )

        self._display.media.set_target_size(width, height)
        self._display.overlay.set_resolution(width, height)

        if width and height:
            self.load_local_themes((width, height))

    def set_rotation(self, degrees: int):
        image = self._display.set_rotation(degrees)
        if image:
            self._fire_preview(image)
            if self.auto_send:
                self._send_frame_to_lcd(image)

    def set_brightness(self, percent: int):
        image = self._display.set_brightness(percent)
        if image:
            self._fire_preview(image)
            if self.auto_send:
                self._send_frame_to_lcd(image)

    def set_split_mode(self, mode: int):
        """Set split mode (C# myLddVal: 0=off, 1-3=Dynamic Island style)."""
        image = self._display.set_split_mode(mode)
        if image:
            self._fire_preview(image)
            if self.auto_send:
                self._send_frame_to_lcd(image)

    # ── Theme Operations ──────────────────────────────────────────────

    def load_local_theme(self, theme: ThemeInfo):
        result = self._display.load_local_theme(theme)
        self._handle_theme_result(result, skip_send_if_animated=True)

    def load_cloud_theme(self, theme: ThemeInfo):
        result = self._display.load_cloud_theme(theme)
        self._handle_theme_result(result, skip_send_if_animated=False)

    def _handle_theme_result(self, result: dict,
                             skip_send_if_animated: bool = False) -> None:
        image = result.get('image')
        is_animated = result.get('is_animated', False)
        log.debug("_handle_theme_result: image=%s animated=%s auto_send=%s skip_anim=%s",
                  type(image).__name__ if image else None, is_animated,
                  self.auto_send, skip_send_if_animated)
        if image:
            self._fire_preview(image)
            if self.auto_send and not (skip_send_if_animated and is_animated):
                self._send_frame_to_lcd(image)
        if is_animated and self._display.is_video_playing():
            if self.on_video_state_changed:
                self.on_video_state_changed(PlaybackState.PLAYING)
        self._fire_status(result.get('status', ''))

    def apply_mask(self, mask_dir: Path):
        image = self._display.apply_mask(mask_dir)
        if image:
            self._fire_preview(image)
            if self.auto_send and not self._display.is_video_playing():
                self._send_frame_to_lcd(image)
        self._fire_status(f"Mask: {mask_dir.name}")

    def load_image_file(self, path: Path):
        image = self._display.load_image_file(path)
        if image:
            self._fire_preview(image)
            if self.auto_send:
                self._send_frame_to_lcd(image)

    def save_theme(self, name: str, data_dir: Path) -> Tuple[bool, str]:
        return self._display.save_theme(name, data_dir)

    def export_config(self, export_path: Path) -> Tuple[bool, str]:
        return self._display.export_config(export_path)

    def import_config(self, import_path: Path, data_dir: Path) -> Tuple[bool, str]:
        return self._display.import_config(import_path, data_dir)

    # ── Video Operations (facade) ─────────────────────────────────────

    def set_video_fit_mode(self, mode: str):
        """Set video fit mode (C# buttonTPJCW/buttonTPJCH)."""
        image = self._display.set_video_fit_mode(mode)
        if image:
            self._fire_preview(image)
            if self.auto_send:
                self._send_frame_to_lcd(image)

    def play_pause(self):
        self.toggle_play_pause()

    def seek_video(self, percent: float):
        self._display.media.seek(percent)

    def video_tick(self):
        result = self._display.video_tick()
        if not result:
            return

        # Preview shows what the LCD shows (with overlay + adjustments)
        preview = result.get('preview')
        if preview is not None:
            log.debug("video_tick: preview type=%s", type(preview).__name__)
            self._fire_preview(preview)

        # Pre-encoded path — bytes already baked, skip encode
        encoded = result.get('encoded')
        if encoded is not None:
            log.debug("video_tick: encoded %d bytes", len(encoded))
            self._display.devices.send_rgb565_async(
                encoded, self.lcd_width, self.lcd_height)
            return

        # Fallback: encode path (cache not active)
        send_img = result.get('send_image')
        if send_img:
            log.debug("video_tick: fallback encode path, type=%s", type(send_img).__name__)
            self.send_pil_async(send_img, self.lcd_width, self.lcd_height)

    def get_video_interval(self) -> int:
        return self._display.get_video_interval()

    def is_video_playing(self) -> bool:
        return self._display.is_video_playing()

    def rebuild_video_cache_metrics(self, metrics: Any) -> None:
        """Rebuild video frame cache with new metrics text."""
        self._display.rebuild_video_cache_metrics(metrics)

    # ── Device Operations ─────────────────────────────────────────────

    def render_overlay_and_preview(self):
        image = self._display.render_overlay()
        log.debug("render_overlay_and_preview: result=%s",
                  type(image).__name__ if image else None)
        if image:
            self._fire_preview(image)
        return image

    # ── Private helpers ───────────────────────────────────────────────

    def _fire_preview(self, image: Any):
        log.debug("_fire_preview: type=%s id=%d callback=%s",
                  type(image).__name__, id(image),
                  self.on_preview_update is not None)
        if self.on_preview_update:
            self.on_preview_update(image)

    def _fire_status(self, text: str):
        if self.on_status_update:
            self.on_status_update(text)

    def _send_frame_to_lcd(self, image: Any):
        """Send image to LCD device (callers handle preview separately)."""
        device = self.get_selected_device()
        if not device:
            return
        self.send_pil_async(image, self.lcd_width, self.lcd_height)


# =============================================================================
# LED Controller (FormLED equivalent)
# =============================================================================

class LEDDeviceController:
    """LED controller — Facade for LEDService + device protocol.

    Combines lifecycle management (initialize, save, load, cleanup) with
    animation tick + notification pattern. Methods in _NOTIFY_METHODS
    auto-fire on_state_changed after delegation to LEDService.
    """

    _NOTIFY_METHODS = frozenset({
        'set_mode', 'set_color', 'set_brightness', 'toggle_global',
        'toggle_segment', 'set_zone_mode', 'set_zone_color',
        'set_zone_brightness', 'toggle_zone', 'configure_for_style',
    })

    def __init__(self, svc=None):
        from ..services.led import LEDService
        self._svc = svc or LEDService()

        # View callbacks
        self.on_state_changed: Optional[Callable] = None
        self.on_preview_update: Optional[Callable] = None
        self.on_send_complete: Optional[Callable[[bool], None]] = None
        self.on_status_update: Optional[Callable[[str], None]] = None

    @property
    def svc(self) -> Any:
        return self._svc

    @property
    def state(self) -> Any:
        return self._svc.state

    @property
    def _device_key(self) -> Any:
        return self._svc._device_key

    @_device_key.setter
    def _device_key(self, value: Any) -> None:
        self._svc._device_key = value

    def tick(self) -> None:
        colors = self._svc.tick()
        display_colors = self._svc.apply_mask(colors)
        if self.on_preview_update:
            self.on_preview_update(display_colors)
        if self._svc.has_protocol:
            success = self._svc.send_colors(colors)
            if self.on_send_complete:
                self.on_send_complete(success)

    def _fire_state_changed(self) -> None:
        if self.on_state_changed:
            self.on_state_changed(self._svc.state)

    def initialize(self, device_info: Any, led_style: int = 1) -> None:
        status = self._svc.initialize(device_info, led_style)
        if self.on_status_update:
            self.on_status_update(status)

    def save_config(self) -> None:
        self._svc.save_config()

    def load_config(self) -> None:
        self._svc.load_config()

    def cleanup(self) -> None:
        self._svc.cleanup()

    def __getattr__(self, name: str):
        try:
            svc = object.__getattribute__(self, '_svc')
        except AttributeError:
            raise AttributeError(name) from None
        attr = getattr(svc, name)
        if name in self._NOTIFY_METHODS and callable(attr):
            def _notifying(*args, **kwargs):
                result = attr(*args, **kwargs)
                self._fire_state_changed()
                return result
            return _notifying
        return attr


# =============================================================================
# Convenience function
# =============================================================================

def create_controller(data_dir: Optional[Path] = None,
                      renderer=None) -> LCDDeviceController:
    """Create and initialize the main controller."""
    controller = LCDDeviceController(renderer=renderer)
    if data_dir:
        controller.initialize(data_dir)
    return controller
