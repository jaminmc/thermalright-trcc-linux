"""LCDHandler — one per LCD device (C# FormCZTV equivalent).

Self-contained handler for a single LCD device. Owns an LCDDevice,
manages theme/video/overlay/slideshow state, renders + sends frames.
TRCCApp creates one LCDHandler per connected LCD device.

All device mutations call LCDDevice methods directly.
Read-only property accesses (connected, playing, auto_send, etc.) are
direct — they carry no side-effects.
"""
# pyright: reportOptionalMemberAccess=false
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtGui import QIcon, QPixmap

import trcc.conf as _conf
from trcc.conf import Settings

from ..core.lcd_device import LCDDevice
from ..core.models import (
    DEFAULT_BRIGHTNESS_LEVEL,
    SPLIT_MODE_RESOLUTIONS,
    DeviceInfo,
    ThemeInfo,
)
from .base import BaseHandler

log = logging.getLogger(__name__)


class _DataReadyNotifier(QObject):
    """Thread-safe notifier: emits ready() from background thread to main thread."""
    ready = Signal()


class LCDHandler(BaseHandler):
    """Handler for a single LCD device — like C# FormCZTV.

    Each LCD device gets its own handler with its own LCDDevice.
    All LCD operations route through here: themes, video, overlay,
    brightness, rotation, slideshow, screencast.

    Args:
        lcd: LCDDevice instance (built by ControllerBuilder).
        widgets: Dict of shared GUI widgets this handler drives.
        make_timer: Callable to create QTimers parented to app.
        data_dir: Application data directory.
    """

    def __init__(
        self,
        lcd: LCDDevice,
        widgets: dict[str, Any],
        make_timer: Any,
        data_dir: Path,
        is_visible_fn: Any = None,
    ) -> None:
        self._lcd = lcd
        self._w = widgets  # preview, theme_setting, theme_local, etc.
        self._data_dir = data_dir
        self._is_visible = is_visible_fn or (lambda: True)

        # Per-device state
        self._device_key = ''
        self._brightness_level = DEFAULT_BRIGHTNESS_LEVEL
        self._split_mode = 0
        self._ldd_is_split = False
        self._background_active = False
        self._slideshow_index = 0

        # QPixmap cache keyed by frame index: {index: (id(qimage), QPixmap)}
        # Avoids QImage→QPixmap conversion on every tick when L3 cache is warm.
        self._pixmap_cache: dict[int, tuple[int, QPixmap]] = {}

        # Thread-safe notifier for background data download → UI refresh
        self._data_notifier = _DataReadyNotifier()
        self._data_notifier.ready.connect(self._update_theme_directories)

        # Timers (created by parent, owned by this handler)
        self._animation_timer: QTimer = make_timer(self._on_video_tick)
        self._slideshow_timer: QTimer = make_timer(self._on_slideshow_tick)
        self._flash_timer: QTimer = make_timer(self._on_flash_timeout, single_shot=True)

    # ── BaseHandler interface ────────────────────────────────────────

    @property
    def view_name(self) -> str:
        return 'form'

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._lcd.device_info

    # ── Public API ───────────────────────────────────────────────────

    @property
    def display(self) -> LCDDevice:
        return self._lcd

    @property
    def device_key(self) -> str:
        return self._device_key

    # ── Device Config (C# ReadSystemConfiguration) ─────────────────

    def apply_device_config(self, device: DeviceInfo, w: int, h: int) -> None:
        """Apply device resolution, restore brightness/rotation/theme/overlay."""
        log.debug("apply_device_config called (device_key=%r)", self._device_key,
                  stack_info=True)
        self._device_key = Settings.device_config_key(
            device.device_index, device.vid, device.pid)

        # Persist resolution per device — each device remembers its own w/h
        Settings.save_device_setting(self._device_key, 'w', w)
        Settings.save_device_setting(self._device_key, 'h', h)

        self._switch_resolution(w, h)

        # Always refresh — first run downloads themes after widget init
        auto_loaded = self._update_theme_directories()

        # Wire background extraction callback via public method (no internal access)
        self._lcd.set_data_ready_callback(self._data_notifier.ready.emit)

        # Restore per-device hardware settings
        cfg = Settings.get_device_config(self._device_key)
        self._restore_brightness(cfg)
        self._restore_rotation(cfg)
        self._restore_split_mode(cfg, w, h)
        self._restore_carousel(cfg)

        # Restore theme+mask+overlay — skip if _update_theme_directories()
        # already auto-loaded the first theme (avoids double-load blink).
        if auto_loaded:
            return
        result = self._lcd.restore_last_theme()
        if result.get("success"):
            image = result.get("image")
            is_animated = result.get("is_animated", False)
            if image:
                self._w['preview'].set_image(image, fast=is_animated)
            overlay_config = result.get("overlay_config")
            overlay_enabled = result.get("overlay_enabled", False)
            if overlay_config:
                self._w['theme_setting'].load_from_overlay_config(overlay_config)
            self._w['theme_setting'].set_overlay_enabled(overlay_enabled)
            if is_animated and self._lcd.playing:
                log.info("_restore_overlay: video theme restored — starting animation timer")
                self._animation_timer.start(self._lcd.interval)
                self._w['preview'].set_playing(True)
                self._w['preview'].show_video_controls(True)
            elif overlay_enabled:
                self._render_and_send()

    def _switch_resolution(self, w: int, h: int) -> None:
        """Switch active resolution and update all resolution-aware widgets."""
        _conf.settings.set_resolution(w, h)
        self._w['preview'].set_resolution(w, h)
        self._w['image_cut'].set_resolution(w, h)
        self._w['video_cut'].set_resolution(w, h)
        self._w['theme_setting'].set_resolution(w, h)

    def reactivate(self, w: int, h: int) -> None:
        """Refresh shared widgets when switching back to this device."""
        self._switch_resolution(w, h)
        self._update_theme_directories()

        # Preview image — device's current image is ground truth
        image = self._lcd.current_image
        if image:
            self._w['preview'].set_image(image)

        # Overlay — reload from per-device config (defensive: missing = disabled)
        if self._device_key:
            cfg = Settings.get_device_config(self._device_key)
            overlay_cfg = cfg.get('overlay', {})
            overlay_config = overlay_cfg.get('config')
            overlay_enabled = overlay_cfg.get('enabled', False)
            if overlay_config:
                self._w['theme_setting'].load_from_overlay_config(overlay_config)
            self._w['theme_setting'].set_overlay_enabled(overlay_enabled)
            if overlay_enabled and image:
                self._render_and_send()
        else:
            self._w['theme_setting'].set_overlay_enabled(False)

    def _restore_brightness(self, cfg: dict) -> None:
        self._brightness_level = cfg.get('brightness_level', DEFAULT_BRIGHTNESS_LEVEL)
        log.info("Restoring brightness: %d%%", self._brightness_level)
        self._lcd.set_brightness(self._brightness_level)

    def _restore_rotation(self, cfg: dict) -> None:
        rotation_index = cfg.get('rotation', 0) // 90
        rotation = rotation_index * 90
        log.debug("_restore_rotation: rotation=%d", rotation)
        self._lcd.set_rotation(rotation)
        self._w['rotation_combo'].blockSignals(True)
        self._w['rotation_combo'].setCurrentIndex(rotation_index)
        self._w['rotation_combo'].blockSignals(False)
        # Non-square devices: swap preview dimensions on 90/270
        w, h = _conf.settings.width, _conf.settings.height
        if w != h and rotation in (90, 270):
            self._w['preview'].set_resolution(h, w)
        self._resolve_cloud_dirs(rotation)

    def _restore_split_mode(self, cfg: dict, w: int, h: int) -> None:
        self._split_mode = cfg.get('split_mode', 2)
        self._ldd_is_split = (w, h) in SPLIT_MODE_RESOLUTIONS
        log.debug("_restore_split_mode: split_mode=%d ldd_is_split=%s", self._split_mode, self._ldd_is_split)
        if self._ldd_is_split:
            if not self._split_mode:
                self._split_mode = 2
            self._lcd.set_split_mode(self._split_mode)
        else:
            self._lcd.set_split_mode(0)

    def _restore_carousel(self, cfg: dict) -> None:
        carousel = cfg.get('carousel')
        local = self._w['theme_local']
        if carousel and isinstance(carousel, dict):
            local._lunbo_array = carousel.get('themes', [])
            local._slideshow = carousel.get('enabled', False)
            local._slideshow_interval = carousel.get('interval', 3)
            local.timer_input.setText(str(carousel.get('interval', 3)))
            px = local._lunbo_on if carousel.get('enabled') else local._lunbo_off
            if not px.isNull():
                local.slideshow_btn.setIcon(QIcon(px))
                local.slideshow_btn.setIconSize(local.slideshow_btn.size())
            local._apply_decorations()
            self._update_slideshow_state()
        else:
            self._slideshow_timer.stop()
            local._lunbo_array = []
            local._slideshow = False
            local._apply_decorations()

    # ── Theme (C# Theme_Click_Event) ───────────────────────────────

    def _select_theme(self, theme: ThemeInfo, *, send_frame: bool = True) -> None:
        """Select theme and handle result."""
        log.info("Theme selected: %s (animated=%s)", theme.name, theme.is_animated)
        self._pixmap_cache.clear()
        payload = self._lcd.select(theme)
        image = payload.get('image')
        is_animated = payload.get('is_animated', False)

        if image:
            self._w['preview'].set_image(image, fast=is_animated)
            if send_frame and self._lcd.auto_send and not is_animated:
                self._lcd.send(image)

        if is_animated and self._lcd.playing:
            self._animation_timer.start(payload.get('interval', 33))
            self._w['preview'].set_playing(True)
            self._w['preview'].show_video_controls(True)

    def select_theme_from_path(self, path: Path, persist: bool = True) -> None:
        """Public entry for theme selection by path (local theme clicks)."""
        self._select_theme_from_path(path, persist=persist)

    def _select_theme_from_path(self, path: Path, persist: bool = True,
                                overlay_config: bool = True) -> None:
        """Load a local/mask theme by directory path."""
        if not path.exists():
            return
        self._slideshow_timer.stop()
        self._lcd.enable_overlay(False)

        # Reset mode toggles (C# ReadSystemConfiguration override)
        self._background_active = False
        self._animation_timer.stop()
        self._lcd.stop()
        self._w['theme_setting'].background_panel.set_enabled(False)
        self._w['theme_setting'].screencast_panel.set_enabled(False)
        self._w['theme_setting'].video_panel.set_enabled(False)

        theme = ThemeInfo.from_directory(path)
        # Suppress send when overlay config will follow — the overlay load
        # owns the single send, avoiding a double-send blink.
        self._select_theme(theme, send_frame=not overlay_config)
        if overlay_config:
            self._load_theme_overlay_config(path, persist=persist)

        if persist and self._device_key:
            log.info("Saving theme_path: %s (key=%s)", path, self._device_key)
            Settings.save_device_setting(self._device_key, 'theme_path', str(path))
            Settings.save_device_setting(self._device_key, 'mask_path', '')

    def select_cloud_theme(self, theme_info: Any) -> None:
        """Handle cloud theme selection (video backgrounds)."""
        self._slideshow_timer.stop()
        self._background_active = False
        self._w['theme_setting'].background_panel.set_enabled(False)
        self._w['theme_setting'].screencast_panel.set_enabled(False)

        if theme_info.video:
            video_path = Path(theme_info.video)
            preview_path = video_path.parent / f"{video_path.stem}.png"
            theme = ThemeInfo.from_video(
                video_path, preview_path if preview_path.exists() else None)
            self._select_theme(theme)
            if self._device_key:
                Settings.save_device_setting(
                    self._device_key, 'theme_path', str(video_path))
                Settings.save_device_setting(self._device_key, 'mask_path', '')

    def apply_mask(self, mask_info: Any) -> None:
        """Apply mask overlay on top of current content."""
        if mask_info.path:
            mask_dir = Path(mask_info.path)
            result = self._lcd.load_mask_standalone(str(mask_dir))
            image = result.get('image')
            if image:
                self._w['preview'].set_image(image)
            self._load_theme_overlay_config(mask_dir, persist=False)
            if self._device_key:
                Settings.save_device_setting(
                    self._device_key, 'mask_path', str(mask_dir))
        else:
            self._w['preview'].set_status(f"Mask: {mask_info.name}")

    def update_mask_position(self, x: int, y: int) -> None:
        """Update mask overlay position and re-render."""
        self._lcd.set_mask_position(x, y)
        self._render_and_send()

    def save_theme(self, name: str) -> None:
        result = self._lcd.save(name, str(self._data_dir))
        self._w['preview'].set_status(result.get('message', ''))
        if result.get("success"):
            td = _conf.settings.theme_dir
            if td:
                self._w['theme_local'].set_theme_directory(td.path)
            self._w['theme_local'].load_themes()
            if self._device_key and self._lcd.current_theme_path:
                Settings.save_device_setting(
                    self._device_key, 'theme_path',
                    str(self._lcd.current_theme_path))

    def export_config(self, path: Path) -> None:
        result = self._lcd.export_config(str(path))
        self._w['preview'].set_status(result.get('message', ''))

    def import_config(self, path: Path) -> None:
        result = self._lcd.import_config(str(path), str(self._data_dir))
        self._w['preview'].set_status(result.get('message', ''))
        if result.get("success"):
            td = _conf.settings.theme_dir
            if td:
                self._w['theme_local'].set_theme_directory(td.path)
            self._w['theme_local'].load_themes()

    # ── DC File Loading ────────────────────────────────────────────

    def _load_theme_overlay_config(self, theme_dir: Path,
                                    *, persist: bool = True) -> None:
        """Load overlay config from theme's config.json or config1.dc."""
        overlay_config = self._lcd.load_overlay_config_from_dir(str(theme_dir))

        if not overlay_config:
            self._w['theme_setting'].set_overlay_enabled(False)
            if persist and self._device_key:
                Settings.save_device_setting(self._device_key, 'overlay', {
                    'enabled': False, 'config': {},
                })
            self._render_and_send()
            return

        Settings.apply_format_prefs(overlay_config)
        self._w['theme_setting'].set_overlay_enabled(True)
        self._w['theme_setting'].load_from_overlay_config(overlay_config)
        self._lcd.set_config(overlay_config)
        self._lcd.enable_overlay(True)
        self._render_and_send()

        if persist and self._device_key:
            Settings.save_device_setting(self._device_key, 'overlay', {
                'enabled': True,
                'config': overlay_config,
            })

    # ── Video (C# ucBoFangQiKongZhi1) ─────────────────────────────

    def play_pause(self) -> None:
        log.debug("play_pause")
        result = self._lcd.pause()
        playing = result.get('state') == 'playing'
        self._w['preview'].set_playing(playing)
        if playing:
            self._animation_timer.start(self._lcd.interval)
        else:
            self._animation_timer.stop()

    def stop_video(self) -> None:
        log.debug("stop_video")
        self._lcd.stop()
        self._animation_timer.stop()
        self._w['preview'].set_playing(False)
        self._w['preview'].show_video_controls(False)

    def seek(self, percent: float) -> None:
        self._lcd.seek(percent)

    def set_video_fit_mode(self, mode: str) -> None:
        result = self._lcd.set_fit_mode(mode)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)

    def _on_video_tick(self) -> None:
        """Timer callback: advance one video frame."""
        result = self._lcd.video_tick()
        if not result:
            return
        frame_index = result.get('frame_index')
        if frame_index is not None and frame_index % 30 == 0:
            log.debug("_on_video_tick: frame=%d encoded=%s", frame_index, result.get('encoded') is not None)

        # Skip preview update when window is minimized
        if self._is_visible():
            preview = result.get('preview')
            if preview is not None:
                index = result.get('frame_index')
                if index is not None:
                    cached = self._pixmap_cache.get(index)
                    preview_id = id(preview)
                    if cached is None or cached[0] != preview_id:
                        pixmap = QPixmap.fromImage(preview)
                        self._pixmap_cache[index] = (preview_id, pixmap)
                    else:
                        pixmap = cached[1]
                    self._w['preview'].set_image(pixmap, fast=True)
                else:
                    self._w['preview'].set_image(preview, fast=True)

        if not self._lcd.connected:
            return

        # Pre-encoded path
        encoded = result.get('encoded')
        if encoded is not None:
            w, h = self._lcd.lcd_size
            log.debug("_on_video_tick: sending encoded frame %s (%dx%d, %d bytes)",
                      result.get('frame_index'), w, h, len(encoded))
            self._lcd.device_service.send_rgb565_async(encoded, w, h)
            return

        # Fallback encode
        send_img = result.get('send_image')
        if send_img:
            w, h = self._lcd.lcd_size
            log.debug("_on_video_tick: sending raw frame %s (%dx%d)", result.get('frame_index'), w, h)
            self._lcd.frame.send_async(send_img, w, h)

    # ── Overlay (C# ucXiTongXianShi1) ─────────────────────────────

    def on_overlay_changed(self, element_data: dict) -> None:
        """Forward overlay config change from settings panel."""
        log.debug("on_overlay_changed: %d elements", len(element_data) if element_data else 0)
        if not element_data:
            return
        if not self._lcd.enabled:
            self._lcd.enable_overlay(True)
        self._lcd.set_config(element_data)
        if self._lcd.playing and self._lcd.last_metrics is not None:
            log.debug("on_overlay_changed: video playing — updating cache text overlay")
            self._lcd.update_video_cache_text(self._lcd.last_metrics)
        else:
            self._render_and_send()

        if self._device_key:
            Settings.save_device_setting(self._device_key, 'overlay', {
                'enabled': self._w['theme_setting'].overlay_grid.overlay_enabled,
                'config': element_data,
            })

    def update_preview(self, image: Any) -> None:
        """Display a frame that was already rendered and sent to the device."""
        self._w['preview'].set_image(image)

    def on_overlay_tick(self, metrics: Any) -> None:
        """Metrics tick: video cache text update only."""
        if not self._lcd.connected or not self._lcd.playing:
            return
        log.debug("overlay_tick: video playing — updating cache text overlay")
        self._lcd.update_video_cache_text(metrics)

    def flash_element(self, index: int) -> None:
        """Flash/blink selected overlay element on preview."""
        self._lcd.set_flash_index(index)
        self._flash_timer.start(980)
        self._render_and_send()

    def _on_flash_timeout(self) -> None:
        self._lcd.set_flash_index(-1)
        self._render_and_send()

    # ── Display Settings ───────────────────────────────────────────

    def set_brightness(self, percent: int) -> None:
        log.debug("set_brightness: %d%%", percent)
        self._brightness_level = percent
        result = self._lcd.set_brightness(percent)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
            if self._lcd.auto_send:
                self._lcd.send(image)

    def set_rotation(self, degrees: int) -> None:
        log.debug("set_rotation: degrees=%d", degrees)
        result = self._lcd.set_rotation(degrees)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
            if self._lcd.auto_send:
                self._lcd.send(image)
        if self._device_key:
            Settings.save_device_setting(self._device_key, 'rotation', degrees)
        # Non-square devices: swap preview dimensions on 90/270
        w, h = _conf.settings.width, _conf.settings.height
        if w != h and degrees in (90, 270):
            self._w['preview'].set_resolution(h, w)
        else:
            self._w['preview'].set_resolution(w, h)
        self._resolve_cloud_dirs(degrees)

    def set_split_mode(self, mode: int) -> None:
        log.debug("set_split_mode: mode=%d", mode)
        self._split_mode = mode
        result = self._lcd.set_split_mode(mode)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
            if self._lcd.auto_send:
                self._lcd.send(image)
        if self._device_key:
            Settings.save_device_setting(self._device_key, 'split_mode', mode)

    # ── Background / Screencast Toggles ────────────────────────────

    def on_background_toggle(self, enabled: bool) -> None:
        """Handle background display toggle."""
        log.debug("on_background_toggle: enabled=%s", enabled)
        self._background_active = enabled
        if enabled:
            self._animation_timer.stop()
            self._lcd.stop()
            self._w['preview'].set_playing(False)
            self._w['preview'].show_video_controls(False)
        self._render_and_send()
        kind = "video" if self._lcd.has_frames else "image"
        self._w['preview'].set_status(
            f"Background: {'On' if enabled else 'Off'} ({kind})")

    def on_screencast_frame(self, image: Any) -> None:
        """Handle captured screencast frame — preview + send to LCD."""
        self._w['preview'].set_image(image)
        self._lcd.send(image)

    # ── Slideshow / Carousel ───────────────────────────────────────

    def _update_slideshow_state(self) -> None:
        log.debug("_update_slideshow_state")
        local = self._w['theme_local']
        if local.is_slideshow() and local.get_slideshow_themes():
            interval_s = local.get_slideshow_interval()
            self._slideshow_index = 0
            self._slideshow_timer.start(interval_s * 1000)
        else:
            self._slideshow_timer.stop()

        if self._device_key:
            themes = local.get_slideshow_themes()
            Settings.save_device_setting(self._device_key, 'carousel', {
                'enabled': local.is_slideshow(),
                'interval': local.get_slideshow_interval(),
                'themes': [t.name for t in themes],
            })

    def on_slideshow_delegate(self) -> None:
        """Handle slideshow toggle from local theme panel."""
        self._update_slideshow_state()

    def _on_slideshow_tick(self) -> None:
        """Auto-rotate to next theme in slideshow."""
        if self._lcd.playing:
            self._lcd.stop()
            self._animation_timer.stop()
        themes = self._w['theme_local'].get_slideshow_themes()
        if not themes:
            self._slideshow_timer.stop()
            return
        self._slideshow_index = (self._slideshow_index + 1) % len(themes)
        theme_info = themes[self._slideshow_index]
        path = Path(theme_info.path)
        if path.exists():
            theme = ThemeInfo.from_directory(path)
            self._select_theme(theme, send_frame=False)
            self._load_theme_overlay_config(path)

    # ── Rendering ──────────────────────────────────────────────────

    def _render_and_send(self, skip_if_video: bool = False) -> None:
        """Render overlay + send to LCD, update preview."""
        result = self._lcd.render_and_send(skip_if_video)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)

    def render_and_preview(self) -> Any:
        """Render overlay and update preview (no send)."""
        result = self._lcd.render()
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
        return image

    # ── Helpers ─────────────────────────────────────────────────────

    def _update_theme_directories(self) -> bool:
        """Reload theme browser directories for current resolution.

        Returns True if a first-install auto-load happened (caller should
        skip restore_last_theme to avoid a redundant double-load).
        """
        w, h = _conf.settings.width, _conf.settings.height
        td = _conf.settings.theme_dir
        if td and td.exists():
            self._w['theme_local'].set_theme_directory(td.path)
        if _conf.settings.web_dir:
            self._w['theme_web'].set_web_directory(_conf.settings.web_dir)
        self._w['theme_web'].set_resolution(f'{w}x{h}')
        if _conf.settings.masks_dir:
            self._w['theme_mask'].set_mask_directory(_conf.settings.masks_dir)
        self._w['theme_mask'].set_resolution(f'{w}x{h}')

        # First install: themes just extracted — load first one onto LCD + preview
        if self._lcd.current_image is None and td and td.exists():
            saved_cfg = Settings.get_device_config(self._device_key) if self._device_key else {}
            if not saved_cfg.get('theme_path'):
                for item in sorted(td.path.iterdir()):
                    if item.is_dir() and (item / '00.png').exists():
                        log.info("Data ready: auto-loading first theme: %s", item)
                        self._select_theme_from_path(item, persist=True, overlay_config=True)
                        return True
        return False

    def _resolve_cloud_dirs(self, rotation: int) -> None:
        """Re-resolve cloud dirs for portrait rotation."""
        _conf.settings.resolve_cloud_dirs(rotation)
        w, h = _conf.settings.width, _conf.settings.height
        if w != h and rotation in (90, 270):
            w, h = h, w
        if _conf.settings.web_dir:
            self._w['theme_web'].set_web_directory(_conf.settings.web_dir)
        self._w['theme_web'].set_resolution(f'{w}x{h}')
        if _conf.settings.masks_dir:
            self._w['theme_mask'].set_mask_directory(_conf.settings.masks_dir)
        self._w['theme_mask'].set_resolution(f'{w}x{h}')

    @property
    def is_background_active(self) -> bool:
        return self._background_active

    @is_background_active.setter
    def is_background_active(self, value: bool) -> None:
        self._background_active = value

    @property
    def brightness_level(self) -> int:
        return self._brightness_level

    @property
    def split_mode(self) -> int:
        return self._split_mode

    @property
    def ldd_is_split(self) -> bool:
        return self._ldd_is_split

    # ── Lifecycle ──────────────────────────────────────────────────

    def stop_timers(self) -> None:
        """Stop all timers (called when switching away from this device)."""
        self._animation_timer.stop()
        self._slideshow_timer.stop()

    def cleanup(self) -> None:
        """Full cleanup on shutdown."""
        self._animation_timer.stop()
        self._slideshow_timer.stop()
        self._flash_timer.stop()
        self._lcd.stop()
        # Stop async send worker and send black frame before disconnecting.
        try:
            self._lcd.device_service.stop_send_worker()
            self._lcd.send_color(0, 0, 0)
        except Exception:
            pass
        self._lcd.cleanup()
