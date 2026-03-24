"""LCDHandler — one per LCD device (C# FormCZTV equivalent).

Self-contained handler for a single LCD device. Owns an LCDDevice,
manages theme/video/overlay/slideshow state, renders + sends frames.
TRCCApp creates one LCDHandler per connected LCD device.

SOLID: LCDDevice has composed capabilities (ISP) — this handler
calls lcd.theme.select(), lcd.settings.set_brightness(), etc.
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

log = logging.getLogger(__name__)


class _DataReadyNotifier(QObject):
    """Thread-safe notifier: emits ready() from background thread to main thread."""
    ready = Signal()


class LCDHandler:
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
        self._rebuild_debounce_timer: QTimer = make_timer(
            self._on_rebuild_debounce, single_shot=True)
        self._pending_metrics: Any = None

    @property
    def display(self) -> LCDDevice:
        return self._lcd

    @property
    def device_key(self) -> str:
        return self._device_key

    # ── Device Config (C# ReadSystemConfiguration) ─────────────────

    def apply_device_config(self, device: DeviceInfo, w: int, h: int) -> None:
        """Apply device resolution, restore brightness/rotation/theme/overlay."""
        self._device_key = Settings.device_config_key(
            device.device_index, device.vid, device.pid)

        # Resolution change — update Settings + DisplayService (triggers data download)
        cur_w, cur_h = self._lcd.lcd_size
        if (w, h) != (cur_w, cur_h):
            self._lcd.set_resolution(w, h)
            self._w['preview'].set_resolution(w, h)
            self._w['image_cut'].set_resolution(w, h)
            self._w['video_cut'].set_resolution(w, h)
            self._w['theme_setting'].set_resolution(w, h)

        # Always refresh — first run downloads themes after widget init
        self._update_theme_directories()

        # Wire background extraction callback — refresh theme browsers when done
        if self._lcd._display_svc:
            self._lcd._display_svc.on_data_ready = self._data_notifier.ready.emit

        # Restore per-device settings
        cfg = Settings.get_device_config(self._device_key)
        self._restore_brightness(cfg)
        self._restore_rotation(cfg)
        self._restore_split_mode(cfg, w, h)
        self._restore_theme(cfg)
        self._restore_carousel(cfg)
        self._restore_overlay(cfg)

    def _restore_brightness(self, cfg: dict) -> None:
        self._brightness_level = cfg.get('brightness_level', DEFAULT_BRIGHTNESS_LEVEL)
        log.info("Restoring brightness: level=%d", self._brightness_level)
        self._lcd.settings.set_brightness(self._brightness_level)

    def _restore_rotation(self, cfg: dict) -> None:
        rotation_index = cfg.get('rotation', 0) // 90
        rotation = rotation_index * 90
        self._lcd.settings.set_rotation(rotation)
        self._w['rotation_combo'].blockSignals(True)
        self._w['rotation_combo'].setCurrentIndex(rotation_index)
        self._w['rotation_combo'].blockSignals(False)
        self._resolve_cloud_dirs(rotation)

    def _restore_split_mode(self, cfg: dict, w: int, h: int) -> None:
        self._split_mode = cfg.get('split_mode', 2)
        self._ldd_is_split = (w, h) in SPLIT_MODE_RESOLUTIONS
        if self._ldd_is_split:
            if not self._split_mode:
                self._split_mode = 2
            self._lcd.settings.set_split_mode(self._split_mode)
        else:
            self._lcd.settings.set_split_mode(0)

    def _restore_theme(self, cfg: dict) -> None:
        saved = cfg.get('theme_path')
        if saved:
            path = Path(saved)
            if path.exists():
                log.info("Restoring saved theme: %s", path)
                if path.suffix in ('.mp4', '.avi', '.mkv', '.webm'):
                    preview = path.parent / f"{path.stem}.png"
                    theme = ThemeInfo.from_video(
                        path, preview if preview.exists() else None)
                    self._select_theme(theme)
                else:
                    self._select_theme_from_path(path)
                self._restore_mask(cfg)
                return
            log.warning("Saved theme path not found: %s", saved)

        # Auto-load first local theme as fallback.
        # Persist only when no theme was previously saved — avoids
        # overwriting a saved path that just went missing (v6.1.3).
        theme_base = _conf.settings.theme_dir
        if theme_base and theme_base.exists():
            persist = not saved  # no prior save → persist fallback
            for item in sorted(theme_base.path.iterdir()):
                if item.is_dir() and (item / '00.png').exists():
                    log.info("Fallback theme: %s (persist=%s)", item, persist)
                    self._select_theme_from_path(item, persist=persist)
                    break

    def _restore_mask(self, cfg: dict) -> None:
        """Restore mask overlay from saved config (applied on top of theme).

        Skips if the theme already loaded this mask via its config.json
        reference — avoids invalidating the pre-built video cache.
        """
        mask_path = cfg.get('mask_path')
        if not mask_path:
            return
        mask_dir = Path(mask_path)
        if not mask_dir.exists():
            log.warning("Saved mask path not found: %s", mask_path)
            return
        # Reference-based themes embed mask path in config.json — the theme
        # loader already loaded it and built the video cache with it.
        # Re-loading here would invalidate that cache (display_svc._cache=None)
        # causing mask-less frames until the fallback renderer catches up.
        svc = self._lcd._display_svc
        if svc and svc._mask_source_dir == mask_dir:
            log.debug("Mask %s already loaded by theme reference, skipping", mask_dir)
            return
        log.info("Restoring saved mask: %s", mask_dir)
        result = self._lcd.load_mask_standalone(str(mask_dir))
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
        self._load_theme_overlay_config(mask_dir)

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

    def _restore_overlay(self, cfg: dict) -> None:
        overlay = cfg.get('overlay')
        if overlay and isinstance(overlay, dict):
            enabled = overlay.get('enabled', False)
            config = overlay.get('config', {})
            if config:
                w, h = self._lcd.lcd_size
                self._lcd.overlay.service.set_config_resolution(w, h)
                self._w['theme_setting'].load_from_overlay_config(config)
                self._lcd.overlay.set_config(config)
            self._w['theme_setting'].set_overlay_enabled(enabled)
            self._lcd.overlay.enable(enabled)
        else:
            log.debug("No saved overlay config — keeping theme defaults")

    # ── Theme (C# Theme_Click_Event) ───────────────────────────────

    def _select_theme(self, theme: ThemeInfo) -> None:
        """Select theme via LCDDevice and handle result."""
        log.info("Theme selected: %s (animated=%s)", theme.name, theme.is_animated)
        self._pixmap_cache.clear()
        result = self._lcd.theme.select(theme)
        image = result.get('image')
        is_animated = result.get('is_animated', False)

        if image:
            fast = is_animated
            self._w['preview'].set_image(image, fast=fast)
            if self._lcd.auto_send and not is_animated:
                self._lcd.frame.send(image)

        if is_animated and self._lcd.video.playing:
            interval = result.get('interval', 33)
            self._animation_timer.start(interval)
            self._w['preview'].set_playing(True)
            self._w['preview'].show_video_controls(True)

    def select_theme_from_path(self, path: Path, persist: bool = True) -> None:
        """Public entry for theme selection by path (local theme clicks)."""
        self._select_theme_from_path(path, persist=persist)

    def _select_theme_from_path(self, path: Path, persist: bool = True) -> None:
        """Load a local/mask theme by directory path."""
        if not path.exists():
            return
        self._slideshow_timer.stop()
        self._lcd.overlay.enable(False)

        # Reset mode toggles (C# ReadSystemConfiguration override)
        self._background_active = False
        self._animation_timer.stop()
        self._lcd.video.stop()
        self._w['theme_setting'].background_panel.set_enabled(False)
        self._w['theme_setting'].screencast_panel.set_enabled(False)
        self._w['theme_setting'].video_panel.set_enabled(False)

        theme = ThemeInfo.from_directory(path)
        self._select_theme(theme)
        self._load_theme_overlay_config(path)

        if persist and self._device_key:
            log.info("Saving theme_path: %s (key=%s)", path, self._device_key)
            Settings.save_device_setting(self._device_key, 'theme_path', str(path))
            # Clear mask — selecting a new theme replaces any mask
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
        """Apply mask overlay on top of current content.

        C# ThemeMask case 16: loads 01.png as mask, reads config1.dc
        via ReadSystemConfiguration, then calls buttonMS_Mode + render.
        Overlay config from mask is NOT persisted — only theme loads persist.
        """
        if mask_info.path:
            mask_dir = Path(mask_info.path)
            result = self._lcd.load_mask_standalone(str(mask_dir))
            image = result.get('image')
            if image:
                self._w['preview'].set_image(image)
            # C# reads config1.dc from mask dir (ReadSystemConfiguration)
            self._load_theme_overlay_config(mask_dir, persist=False)
            # Persist mask path so it survives restart
            if self._device_key:
                Settings.save_device_setting(
                    self._device_key, 'mask_path', str(mask_dir))
        else:
            self._w['preview'].set_status(f"Mask: {mask_info.name}")

    def update_mask_position(self, x: int, y: int) -> None:
        """Update mask overlay position and re-render."""
        svc = self._lcd._display_svc
        if svc and svc.overlay:
            svc.overlay.theme_mask_position = (x, y)
            svc.overlay._invalidate_cache()
            self._render_and_send()

    def save_theme(self, name: str) -> None:
        result = self._lcd.theme.save(name, self._data_dir)
        self._w['preview'].set_status(result.get('message', ''))
        if result['success']:
            td = _conf.settings.theme_dir
            if td:
                self._w['theme_local'].set_theme_directory(td.path)
            self._w['theme_local'].load_themes()
            if self._device_key and self._lcd.current_theme_path:
                Settings.save_device_setting(
                    self._device_key, 'theme_path',
                    str(self._lcd.current_theme_path))

    def export_config(self, path: Path) -> None:
        result = self._lcd.theme.export_config(path)
        self._w['preview'].set_status(result.get('message', ''))

    def import_config(self, path: Path) -> None:
        result = self._lcd.theme.import_config(path, self._data_dir)
        self._w['preview'].set_status(result.get('message', ''))
        if result['success']:
            td = _conf.settings.theme_dir
            if td:
                self._w['theme_local'].set_theme_directory(td.path)
            self._w['theme_local'].load_themes()

    # ── DC File Loading ────────────────────────────────────────────

    def _load_theme_overlay_config(self, theme_dir: Path,
                                    *, persist: bool = True) -> None:
        """Load overlay config from theme's config.json or config1.dc.

        Args:
            theme_dir: Directory containing config.json or config1.dc.
            persist: If True, save overlay state to config.json (theme loads).
                     If False, apply but don't persist (mask loads — temporary).
        """
        overlay_config = None

        json_path = theme_dir / 'config.json'
        if json_path.exists():
            try:
                from ..adapters.infra.dc_parser import load_config_json
                result = load_config_json(str(json_path))
                if result is not None:
                    overlay_config = result[0]
            except Exception:
                pass

        if overlay_config is None:
            dc_path = theme_dir / 'config1.dc'
            if not dc_path.exists():
                return
            try:
                from ..adapters.infra.dc_config import DcConfig
                dc = DcConfig(dc_path)
                overlay_config = dc.to_overlay_config()
            except Exception:
                return

        if not overlay_config:
            # Custom themes without overlay — clear any stale saved overlay
            # so it doesn't reappear on restart (fixes #58).
            self._w['theme_setting'].set_overlay_enabled(False)
            if persist and self._device_key:
                Settings.save_device_setting(self._device_key, 'overlay', {
                    'enabled': False, 'config': {},
                })
            return

        Settings.apply_format_prefs(overlay_config)
        self._w['theme_setting'].set_overlay_enabled(True)
        self._w['theme_setting'].load_from_overlay_config(overlay_config)
        w, h = self._lcd.lcd_size
        self._lcd.overlay.service.set_config_resolution(w, h)
        self._lcd.overlay.set_config(overlay_config)
        self._lcd.overlay.enable(True)
        self._render_and_send()

        if persist and self._device_key:
            Settings.save_device_setting(self._device_key, 'overlay', {
                'enabled': True,
                'config': overlay_config,
            })

    # ── Video (C# ucBoFangQiKongZhi1) ─────────────────────────────

    def play_pause(self) -> None:
        result = self._lcd.video.pause()
        playing = result.get('state') == 'playing'
        self._w['preview'].set_playing(playing)
        if playing:
            self._animation_timer.start(self._lcd.video.interval)
        else:
            self._animation_timer.stop()

    def stop_video(self) -> None:
        self._lcd.video.stop()
        self._animation_timer.stop()
        self._w['preview'].set_playing(False)
        self._w['preview'].show_video_controls(False)

    def seek(self, percent: float) -> None:
        self._lcd.video.seek(percent)

    def set_video_fit_mode(self, mode: str) -> None:
        result = self._lcd.video.set_fit_mode(mode)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)

    def _on_video_tick(self) -> None:
        """Timer callback: advance one video frame."""
        result = self._lcd.video_tick()
        if not result:
            return

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
            self._lcd.device_service.send_rgb565_async(encoded, w, h)
            return

        # Fallback encode
        send_img = result.get('send_image')
        if send_img:
            w, h = self._lcd.lcd_size
            self._lcd.frame.send_async(send_img, w, h)

    # ── Overlay (C# ucXiTongXianShi1) ─────────────────────────────

    def on_overlay_changed(self, element_data: dict) -> None:
        """Forward overlay config change from settings panel."""
        log.debug("on_overlay_changed: %d elements", len(element_data) if element_data else 0)
        if not element_data:
            return
        if not self._lcd.overlay.enabled:
            self._lcd.overlay.enable(True)
        self._lcd.overlay.set_config(element_data)
        if self._lcd.video.playing and self._lcd.overlay.last_metrics is not None:
            log.debug("on_overlay_changed: video playing — forcing cache rebuild")
            self._rebuild_debounce_timer.stop()
            self._lcd.overlay.rebuild_video_cache(self._lcd.overlay.last_metrics)
        else:
            self._render_and_send()

        if self._device_key:
            Settings.save_device_setting(self._device_key, 'overlay', {
                'enabled': self._w['theme_setting'].overlay_grid.overlay_enabled,
                'config': element_data,
            })

    def on_overlay_tick(self, metrics: Any) -> None:
        """Metrics subscriber: render overlay when values change."""
        if not self._lcd.overlay.enabled:
            return

        self._lcd.overlay.update_metrics(metrics)

        if self._lcd.video.playing:
            if self._lcd.overlay.has_changed(metrics):
                log.debug("overlay_tick: video playing, metrics changed — debouncing cache rebuild")
                self._pending_metrics = metrics
                self._rebuild_debounce_timer.start(300)
            else:
                log.debug("overlay_tick: video playing, no change — skip")
            return

        if not self._lcd.overlay.has_changed(metrics):
            log.debug("overlay_tick: static theme, no change — skip send")
            return

        log.debug("overlay_tick: static theme, metrics changed — render+send")
        self._render_and_send()

    def _on_rebuild_debounce(self) -> None:
        """Fire after metrics settle — rebuild video cache once."""
        if self._pending_metrics is not None:
            log.debug("overlay_tick: debounce fired — rebuilding cache")
            self._lcd.overlay.rebuild_video_cache(self._pending_metrics)
            self._pending_metrics = None

    def keepalive(self) -> None:
        """Periodic keepalive: resend current frame to prevent USB standby.

        Fires every ~20 s via the metrics mediator. Skipped when video is
        playing (the animation timer already sends frames continuously).
        """
        if self._lcd.video.playing:
            return
        log.debug("keepalive: resending frame")
        self._render_and_send()

    def flash_element(self, index: int) -> None:
        """Flash/blink selected overlay element on preview."""
        self._lcd.overlay.service.flash_skip_index = index
        self._flash_timer.start(980)
        self._render_and_send()

    def _on_flash_timeout(self) -> None:
        self._lcd.overlay.service.flash_skip_index = -1
        self._render_and_send()

    # ── Display Settings ───────────────────────────────────────────

    def set_brightness(self, level: int) -> None:
        self._brightness_level = level
        result = self._lcd.settings.set_brightness(level)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
            if self._lcd.auto_send:
                self._lcd.frame.send(image)

    def set_rotation(self, degrees: int) -> None:
        result = self._lcd.settings.set_rotation(degrees)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
            if self._lcd.auto_send:
                self._lcd.frame.send(image)
        if self._device_key:
            Settings.save_device_setting(self._device_key, 'rotation', degrees)
        self._resolve_cloud_dirs(degrees)

    def set_split_mode(self, mode: int) -> None:
        self._split_mode = mode
        result = self._lcd.settings.set_split_mode(mode)
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
            if self._lcd.auto_send:
                self._lcd.frame.send(image)
        if self._device_key:
            Settings.save_device_setting(self._device_key, 'split_mode', mode)

    # ── Background / Screencast Toggles ────────────────────────────

    def on_background_toggle(self, enabled: bool) -> None:
        """Handle background display toggle (C# myBjxs / myMode=0).

        C# ThemeSetting case 1: sets myUIMode=1, myMode=0,
        calls ClosePlayer() and buttonMS_Mode(). Toggle off just
        stops drawing the background — doesn't resume video.
        """
        self._background_active = enabled
        if enabled:
            self._animation_timer.stop()
            self._lcd.video.stop()
            self._w['preview'].set_playing(False)
            self._w['preview'].show_video_controls(False)
        self._render_and_send()
        kind = "video" if self._lcd.video.has_frames else "image"
        self._w['preview'].set_status(
            f"Background: {'On' if enabled else 'Off'} ({kind})")

    def on_screencast_frame(self, image: Any) -> None:
        """Handle captured screencast frame — preview + send to LCD."""
        self._w['preview'].set_image(image)
        self._lcd.frame.send(image)

    # ── Slideshow / Carousel ───────────────────────────────────────

    def _update_slideshow_state(self) -> None:
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
        if self._lcd.video.playing:
            self._lcd.video.stop()
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
            self._select_theme(theme)
            self._load_theme_overlay_config(path)

    # ── Rendering ──────────────────────────────────────────────────

    def _render_and_send(self, skip_if_video: bool = False) -> None:
        """Render overlay + send to LCD if auto-send is on."""
        result = self._lcd.overlay.render()
        image = result.get('image')
        if not image or not self._lcd.auto_send:
            log.debug("_render_and_send: skipped (no image or auto_send off)")
            return
        if self._is_visible():
            self._w['preview'].set_image(image)
        if not self._lcd.connected:
            log.debug("_render_and_send: skipped (not connected)")
            return
        if skip_if_video and self._lcd.video.playing:
            log.debug("_render_and_send: skipped (video playing)")
            return
        log.debug("_render_and_send: sending frame")
        self._lcd.frame.send(image)

    def render_and_preview(self) -> Any:
        """Render overlay and update preview (no send)."""
        result = self._lcd.overlay.render()
        image = result.get('image')
        if image:
            self._w['preview'].set_image(image)
        return image

    # ── Helpers ─────────────────────────────────────────────────────

    def _update_theme_directories(self) -> None:
        """Reload theme browser directories for current resolution."""
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

    def _resolve_cloud_dirs(self, rotation: int) -> None:
        """Re-resolve cloud dirs for portrait rotation (C# GetWebBackgroundImageDirectory)."""
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
        self._lcd.video.stop()
        # Stop async send worker and wait for any in-progress send to finish,
        # then send a black frame to clear the display before disconnecting.
        try:
            self._lcd.device_service.stop_send_worker()
            self._lcd.frame.send_color(0, 0, 0)
        except Exception:
            pass
        self._lcd.cleanup()
