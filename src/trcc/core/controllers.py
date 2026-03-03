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

    def __init__(self):
        # Create shared services
        device_svc = DeviceService()
        overlay_svc = OverlayService()
        media_svc = MediaService()

        # The head chef
        self._display = DisplayService(device_svc, overlay_svc, media_svc)

        # Theme service (standalone — DisplayService uses static methods)
        self._theme_svc = ThemeService()

        # View callbacks — LCD
        self.on_preview_update: Optional[Callable[[Any], None]] = None
        self.on_status_update: Optional[Callable[[str], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_resolution_changed: Optional[Callable[[int, int], None]] = None

        # View callbacks — Theme
        self.on_themes_loaded: Optional[Callable[[List[ThemeInfo]], None]] = None
        self.on_filter_changed: Optional[Callable[[str], None]] = None

        # View callbacks — Device
        self.on_devices_changed: Optional[Callable[[List[DeviceInfo]], None]] = None
        self.on_device_selected: Optional[Callable[[DeviceInfo], None]] = None
        self.on_send_started: Optional[Callable[[], None]] = None
        self.on_send_complete: Optional[Callable[[bool], None]] = None

        # View callbacks — Video
        self.on_video_loaded: Optional[Callable[[VideoState], None]] = None
        self.on_video_progress_update: Optional[Callable[[float, str, str], None]] = None
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
        themes = self._theme_svc.load_local_themes(resolution)
        if self.on_themes_loaded:
            self.on_themes_loaded(themes)

    def load_cloud_themes(self):
        themes = self._theme_svc.load_cloud_themes()
        if self.on_themes_loaded:
            self.on_themes_loaded(themes)

    def set_theme_filter(self, mode: str):
        self._theme_svc.set_filter(mode)
        if self.on_filter_changed:
            self.on_filter_changed(mode)

    def set_theme_category(self, category: str):
        self._theme_svc.set_category(category)

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
        if self.on_devices_changed:
            self.on_devices_changed(self._display.devices.devices)
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
        if self.on_send_started:
            self.on_send_started()
        self._display.devices.send_rgb565_async(rgb565_data, width, height)

    def send_pil_async(self, image: Any, width: int, height: int,
                       byte_order: str = '>'):
        if self._display.devices.is_busy:
            return
        if self.on_send_started:
            self.on_send_started()
        self._display.devices.send_pil_async(image, width, height)

    def get_protocol_info(self):
        return self._display.devices.get_protocol_info()

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

    def get_video_frame(self, index: Optional[int] = None) -> Optional[Any]:
        return self._display.media.get_frame(index)

    @property
    def video_source_path(self) -> Optional[Path]:
        return self._display.media.source_path

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

        if self.on_resolution_changed:
            self.on_resolution_changed(width, height)

    def set_rotation(self, degrees: int):
        image = self._display.set_rotation(degrees)
        if image is not None:
            self._fire_preview(image)
            if self.auto_send:
                self._send_frame_to_lcd(image)

    def set_brightness(self, percent: int):
        image = self._display.set_brightness(percent)
        if image is not None:
            self._fire_preview(image)
            if self.auto_send:
                self._send_frame_to_lcd(image)

    def set_split_mode(self, mode: int):
        """Set split mode (C# myLddVal: 0=off, 1-3=Dynamic Island style)."""
        image = self._display.set_split_mode(mode)
        if image is not None:
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
        if image is not None:
            self._fire_preview(image)
            if self.auto_send and not (skip_send_if_animated and is_animated):
                self._send_frame_to_lcd(image)
        if is_animated and self._display.is_video_playing():
            if self.on_video_state_changed:
                self.on_video_state_changed(PlaybackState.PLAYING)
        self._fire_status(result.get('status', ''))

    def apply_mask(self, mask_dir: Path):
        image = self._display.apply_mask(mask_dir)
        if image is not None:
            self._fire_preview(image)
            if self.auto_send and not self._display.is_video_playing():
                self._send_frame_to_lcd(image)
        self._fire_status(f"Mask: {mask_dir.name}")

    def load_image_file(self, path: Path):
        image = self._display.load_image_file(path)
        if image is not None:
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
        if image is not None:
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

        frame = result['frame']
        self._fire_preview(frame)

        if result['send']:
            self.send_pil_async(frame, self.lcd_width, self.lcd_height)

    def get_video_interval(self) -> int:
        return self._display.get_video_interval()

    def is_video_playing(self) -> bool:
        return self._display.is_video_playing()

    # ── Device Operations ─────────────────────────────────────────────

    def send_current_image(self):
        rgb565 = self._display.send_current_image()
        if rgb565:
            self.send_image_async(rgb565, self.lcd_width, self.lcd_height)
            self._fire_status("Sent to LCD")

    def render_overlay_and_preview(self):
        image = self.render_overlay()
        if image is not None:
            self._fire_preview(image)
        return image

    # ── Private helpers ───────────────────────────────────────────────

    def _fire_preview(self, image: Any):
        if self.on_preview_update:
            self.on_preview_update(image)

    def _fire_status(self, text: str):
        if self.on_status_update:
            self.on_status_update(text)

    def _fire_error(self, message: str):
        log.error("%s", message)
        if self.on_error:
            self.on_error(message)

    def _send_frame_to_lcd(self, image: Any):
        """Send a processed image to the LCD via DeviceService."""
        device = self.get_selected_device()
        if not device:
            log.debug("Send skipped — no device selected")
            return
        self.send_pil_async(image, self.lcd_width, self.lcd_height)

    def _setup_theme_dirs(self, width: int, height: int):
        self._display._setup_dirs(width, height)
        self.set_theme_directories(
            local_dir=self._display.local_dir,
            web_dir=self._display.web_dir,
            masks_dir=self._display.masks_dir,
        )


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

        # USB change detection — skip send when colors unchanged
        self._last_colors: list | None = None

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
        if self._svc.has_protocol and colors != self._last_colors:
            self._last_colors = list(colors)
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

def create_controller(data_dir: Optional[Path] = None) -> LCDDeviceController:
    """Create and initialize the main controller."""
    controller = LCDDeviceController()
    if data_dir:
        controller.initialize(data_dir)
    return controller
