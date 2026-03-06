"""Display pipeline orchestrator — coordinates theme, overlay, media -> LCD frame.

Pure Python, no Qt dependencies.
Controllers (PySide6, Typer CLI, FastAPI) are thin wrappers that call this
service and fire callbacks.
"""
from __future__ import annotations

import logging
import os
import shutil
import tempfile
from pathlib import Path
from typing import Any, Tuple

from ..adapters.infra.data_repository import RESOURCES_DIR, DataManager
from ..conf import settings
from ..core.models import SPLIT_MODE_RESOLUTIONS, SPLIT_OVERLAY_MAP
from .device import DeviceService
from .image import ImageService
from .media import MediaService
from .overlay import OverlayService
from .theme_loader import ThemeLoader
from .theme_persistence import ThemePersistence

log = logging.getLogger(__name__)


class DisplayService:
    """Display pipeline: theme -> overlay -> brightness/rotation -> LCD frame.

    Orchestrates sub-services (DeviceService, OverlayService, MediaService).
    Sub-services are injected, not owned. Theme loading and persistence
    delegated to ThemeLoader and ThemePersistence (SRP).
    """

    def __init__(self,
                 devices: DeviceService,
                 overlay: OverlayService,
                 media: MediaService) -> None:
        # Sub-services (injected)
        self.devices = devices
        self.overlay = overlay
        self.media = media

        # Theme loader (injected with same sub-services)
        self._loader = ThemeLoader(overlay, media)

        # Working directory (Windows GifDirectory pattern)
        self.working_dir = Path(tempfile.mkdtemp(prefix='trcc_work_'))

        # State
        self.current_image: Any | None = None  # Native surface (QImage or PIL)
        self._clean_background: Any | None = None  # Original bg before overlay
        self.current_theme_path: Path | None = None
        self.auto_send = True
        self.rotation = 0         # directionB: 0, 90, 180, 270
        self.brightness = 50      # percent (0-100)
        self.split_mode = 0       # myLddVal: 0=off, 1-3=Dynamic Island style
        self._split_overlay_cache: dict[tuple[int, int], Any] = {}  # (style,rot)->PIL

        # Pre-baked video frame cache (None when inactive)
        self._cache: Any | None = None  # VideoFrameCache

        # Theme directories
        self._local_dir: Path | None = None
        self._web_dir: Path | None = None
        self._masks_dir: Path | None = None
        self._mask_source_dir: Path | None = None

    # -- Properties --------------------------------------------------------

    @property
    def lcd_width(self) -> int:
        return settings.width

    @property
    def lcd_height(self) -> int:
        return settings.height

    @property
    def lcd_size(self) -> tuple[int, int]:
        return (settings.width, settings.height)

    # -- Initialization ----------------------------------------------------

    def initialize(self, data_dir: Path) -> None:
        """Initialize service with data directory."""
        log.debug("DisplayService: init data_dir=%s", data_dir)
        self._data_dir = data_dir

        self.media.set_target_size(self.lcd_width, self.lcd_height)
        self.overlay.set_resolution(self.lcd_width, self.lcd_height)

        if self.lcd_width and self.lcd_height:
            self._setup_dirs(self.lcd_width, self.lcd_height)

    def _setup_dirs(self, width: int, height: int) -> None:
        """Extract, locate, and set theme/web/mask directories."""
        DataManager.ensure_all(width, height)
        settings._resolve_paths()

        td = settings.theme_dir
        self._local_dir = td.path if td and td.exists() else None
        self._web_dir = settings.web_dir if settings.web_dir and settings.web_dir.exists() else None
        self._masks_dir = settings.masks_dir

    def cleanup(self) -> None:
        """Clean up working directory on exit."""
        if self.working_dir and self.working_dir.exists():
            shutil.rmtree(self.working_dir, ignore_errors=True)

    # -- Resolution --------------------------------------------------------

    def set_resolution(self, width: int, height: int, persist: bool = True) -> None:
        """Set LCD resolution and update sub-services."""
        if width == self.lcd_width and height == self.lcd_height:
            return
        log.info("Resolution changed: %dx%d -> %dx%d",
                 self.lcd_width, self.lcd_height, width, height)
        settings.set_resolution(width, height, persist=persist)
        self.media.set_target_size(width, height)
        self.overlay.set_resolution(width, height)

        if width and height:
            self._setup_dirs(width, height)

    # -- Display adjustments -----------------------------------------------

    def set_rotation(self, degrees: int) -> Any | None:
        """Set display rotation. Returns rendered image or None."""
        self.rotation = degrees % 360
        if self._cache and self._cache.active:
            self._cache.rebuild_from_rotation(self.rotation)
        return self._render_and_process()

    def set_brightness(self, percent: int) -> Any | None:
        """Set display brightness. Returns rendered image or None."""
        self.brightness = max(0, min(100, percent))
        if self._cache and self._cache.active:
            self._cache.rebuild_from_brightness(self.brightness)
        return self._render_and_process()

    def set_split_mode(self, mode: int) -> Any | None:
        """Set split mode (C# myLddVal: 0=off, 1-3=Dynamic Island style).

        Only affects 1600x720 widescreen devices. Returns rendered image.
        """
        self.split_mode = mode if mode in (0, 1, 2, 3) else 0
        return self._render_and_process()

    @property
    def is_widescreen_split(self) -> bool:
        """True if current resolution supports split mode."""
        return self.lcd_size in SPLIT_MODE_RESOLUTIONS

    # -- Frame conversion --------------------------------------------------

    def _convert_media_frames(self) -> None:
        """Convert MediaService's PIL frames to native renderer surfaces.

        VideoDecoder produces PIL Images, but the rendering pipeline
        (QtRenderer) needs QImage.  Convert in-place once at load time
        so all downstream code (video_tick, _build_video_cache, overlay)
        sees native surfaces.
        """
        frames = self.media._frames
        if not frames:
            return
        r = ImageService._r()
        try:
            r.surface_size(frames[0])
        except (AttributeError, TypeError):
            self.media._frames = [r.from_pil(f) for f in frames]

    # -- Theme loading (delegates to ThemeLoader) --------------------------

    def load_local_theme(self, theme) -> dict:
        """Load a local theme with DC config, mask, and overlay."""
        self._cache = None  # Invalidate previous video cache
        result = self._loader.load_local_theme(
            theme, self.lcd_size, self.working_dir)

        # Convert PIL frames → native renderer surfaces (if animated)
        if result.get('is_animated'):
            self._convert_media_frames()

        # Wire up state from loader result
        self._mask_source_dir = result.get('mask_source_dir')
        self.current_theme_path = result.get('theme_path')

        # Set current_image from result or from video first frame
        if result.get('image'):
            self.current_image = result['image']
            self._clean_background = result['image']
        elif result.get('is_animated'):
            first_frame = self.media.get_frame(0)
            if first_frame:
                self.current_image = first_frame
                self._clean_background = first_frame

        # Build pre-baked cache for animated themes
        if result.get('is_animated') and self.media.has_frames:
            self._build_video_cache()

        # Render with adjustments if we have a static image
        if result.get('image') and not result.get('is_animated'):
            result['image'] = self._render_and_process()

        return result

    def load_cloud_theme(self, theme) -> dict:
        """Load a cloud video theme as background."""
        self._cache = None  # Invalidate previous video cache
        result = self._loader.load_cloud_theme(theme, self.working_dir)
        log.debug("load_cloud_theme: loader result keys=%s", list(result.keys()))

        # Convert PIL frames → native renderer surfaces
        self._convert_media_frames()
        log.debug("load_cloud_theme: frames converted, count=%d",
                  len(self.media._frames) if self.media._frames else 0)

        first_frame = self.media.get_frame(0)
        log.debug("load_cloud_theme: first_frame=%s",
                  type(first_frame).__name__ if first_frame else None)
        if first_frame:
            self.current_image = first_frame
            self._clean_background = first_frame
        result['image'] = self.current_image

        # Build pre-baked cache for cloud video themes
        if self.media.has_frames:
            log.debug("load_cloud_theme: building video cache")
            self._build_video_cache()
            log.debug("load_cloud_theme: cache active=%s",
                      self._cache.active if self._cache else False)
        return result

    def apply_mask(self, mask_dir: Path) -> Any | None:
        """Apply a mask overlay on top of current content."""
        # Restore clean background so old mask isn't baked in
        if self._clean_background is not None:
            self.current_image = self._clean_background
        elif not self.current_image:
            self.current_image = ImageService.solid_color(0, 0, 0, *self.lcd_size)

        self._mask_source_dir = self._loader.apply_mask(
            mask_dir, self.working_dir, self.lcd_size)

        # Invalidate pre-baked video cache (old mask baked in)
        self._cache = None
        if self.media.has_frames:
            self._build_video_cache()

        return self.render_overlay()

    # -- Image loading (kept on DisplayService -- tied to state) -----------

    def load_image_file(self, path: Path) -> Any | None:
        """Load a static image file. Returns rendered image or None."""
        self._load_static_image(path)
        return self._render_and_process()

    def _load_static_image(self, path: Path) -> None:
        """Load and resize a static image to LCD dimensions."""
        try:
            self.current_image = ImageService.open_and_resize(path, *self.lcd_size)
            self._clean_background = self.current_image
        except Exception as e:
            log.error("Failed to load image: %s", e)

    def _create_black_background(self) -> None:
        """Create black background for mask-only themes."""
        self.current_image = ImageService.solid_color(0, 0, 0, *self.lcd_size)

    # -- Rendering ---------------------------------------------------------

    def _render_and_process(self) -> Any | None:
        """Render overlay on current image, apply brightness + rotation."""
        if not self.current_image:
            log.debug("_render_and_process: no current_image")
            return None
        image = self.current_image
        log.debug("_render_and_process: current_image type=%s overlay_enabled=%s",
                  type(image).__name__, self.overlay.enabled)
        if self.overlay.enabled:
            image = self.overlay.render(image)
            log.debug("_render_and_process: after overlay type=%s", type(image).__name__)
        return self._apply_adjustments(image)

    def render_overlay(self) -> Any | None:
        """Force-render overlay (for live editing). Returns image or None."""
        # Use clean background (no old overlay baked in)
        bg = self._clean_background or self.current_image
        if not bg:
            log.debug("render_overlay: no background, creating black bg")
            self._create_black_background()
            bg = self.current_image
        image = self.overlay.render(bg, force=True)
        return self._apply_adjustments(image)

    def _apply_adjustments(self, image: Any) -> Any:
        """Apply brightness, rotation, and split overlay to image."""
        if self.brightness >= 100 and self.rotation == 0 and not self.split_mode:
            return image
        image = ImageService.apply_brightness(image, self.brightness)
        image = ImageService.apply_rotation(image, self.rotation)
        return self._apply_split_overlay(image)

    def _apply_split_overlay(self, image: Any) -> Any:
        """Composite Dynamic Island overlay for widescreen split mode."""
        if not self.split_mode or not self.is_widescreen_split:
            return image

        key = (self.split_mode, self.rotation)
        asset_name = SPLIT_OVERLAY_MAP.get(key)
        if not asset_name:
            return image

        overlay = self._split_overlay_cache.get(key)
        if overlay is None:
            overlay = self._load_split_overlay(asset_name)
            self._split_overlay_cache[key] = overlay

        if overlay is None:
            return image

        try:
            r = ImageService._r()
            image = r.convert_to_rgba(image)
            img_w, img_h = r.surface_size(image)
            ovl_w, ovl_h = r.surface_size(overlay)
            if (ovl_w, ovl_h) != (img_w, img_h):
                overlay = r.resize(overlay, img_w, img_h)
            image = r.composite(image, overlay, (0, 0))
            return r.convert_to_rgb(image)
        except Exception as e:
            log.error("Split overlay composite failed: %s", e)
            return image

    @staticmethod
    def _load_split_overlay(asset_name: str) -> Any | None:
        """Load a split overlay PNG from assets/gui/ as native surface."""
        import os
        try:
            path = os.path.join(RESOURCES_DIR, asset_name)
            if os.path.exists(path):
                r = ImageService._r()
                img = r.open_image(path)
                return r.convert_to_rgba(img)
            log.warning("Split overlay not found: %s", path)
        except Exception as e:
            log.error("Failed to load split overlay %s: %s", asset_name, e)
        return None

    def set_video_fit_mode(self, mode: str) -> Any | None:
        """Set video fit mode. Re-decodes frames. Returns preview image."""
        if self.media.set_fit_mode(mode):
            self._convert_media_frames()
            frame = self.media.get_frame()
            if frame:
                self.current_image = frame
                return self._render_and_process()
        return self._render_and_process()

    # -- Video playback ----------------------------------------------------

    def video_tick(self) -> dict | None:
        """Advance one video frame. Returns dict or None if not playing."""
        frame, should_send, progress = self.media.tick()
        if not frame:
            return None

        self.current_image = frame

        # Fast path: pre-baked cache active — zero PIL work per tick
        if self._cache and self._cache.active:
            cf = self.media.state.current_frame
            total = self.media.state.total_frames
            index = (cf - 1) % total if total > 0 else 0
            return {
                'preview': self._cache.get_preview(index),
                'progress': progress,
                'send_image': None,
                'encoded': self._cache.get_encoded(index),
            }

        # Fallback: original pipeline (overlay disabled, or cache not built)
        if self.overlay.enabled:
            frame = self.overlay.render(frame)

        processed = self._apply_adjustments(frame)

        result = {'preview': processed, 'progress': progress,
                  'send_image': processed if (should_send and self.auto_send) else None}

        return result

    def get_video_interval(self) -> int:
        """Get video frame interval in ms for timer setup."""
        return self.media.frame_interval_ms

    def is_video_playing(self) -> bool:
        """Check if video is currently playing."""
        return self.media.is_playing

    # -- Video frame cache -------------------------------------------------

    def _build_video_cache(self) -> None:
        """Build pre-baked video frame cache from current state."""
        from .video_cache import VideoFrameCache

        device = self.devices.selected
        if device:
            protocol, resolution, fbl, use_jpeg = device.encoding_params
        else:
            protocol, resolution, fbl, use_jpeg = 'scsi', (320, 320), None, False
        cache = VideoFrameCache()
        cache.build(
            frames=self.media._frames,
            mask=(self.overlay.theme_mask
                  if self.overlay.enabled and self.overlay.theme_mask_visible
                  else None),
            mask_position=self.overlay.theme_mask_position,
            overlay_svc=self.overlay if self.overlay.enabled else None,
            metrics=self.overlay._metrics,
            brightness=self.brightness,
            rotation=self.rotation,
            protocol=protocol,
            resolution=resolution,
            fbl=fbl,
            use_jpeg=use_jpeg,
        )
        self._cache = cache

    def rebuild_video_cache_metrics(self, metrics: Any) -> None:
        """Rebuild video cache with new metrics text."""
        if self._cache and self._cache.active:
            self._cache.rebuild_from_metrics(
                self.overlay if self.overlay.enabled else None, metrics)

    # -- LCD send ----------------------------------------------------------

    def send_current_image(self) -> bytes | None:
        """Prepare current image for LCD send. Returns encoded bytes or None."""
        if not self.current_image:
            return None
        image = self.current_image
        if self.overlay.enabled:
            image = self.overlay.render(image)
        image = self._apply_adjustments(image)
        return self._encode_for_device(image)

    def _encode_for_device(self, img: Any) -> bytes:
        """Encode image for LCD device."""
        device = self.devices.selected
        if device:
            protocol, resolution, fbl, use_jpeg = device.encoding_params
        else:
            protocol, resolution, fbl, use_jpeg = 'scsi', (320, 320), None, True
        return ImageService.encode_for_device(img, protocol, resolution, fbl, use_jpeg)

    # -- Theme save (delegates to ThemePersistence) ------------------------

    def save_theme(self, name: str, data_dir: Path) -> Tuple[bool, str]:
        """Save current config as a custom theme."""
        # Fall back to user-writable dir on system-wide installs (#51)
        if not os.access(data_dir, os.W_OK):
            from ..adapters.infra.data_repository import USER_DATA_DIR
            data_dir = Path(USER_DATA_DIR)
        ok, msg = ThemePersistence.save(
            name, data_dir, self.lcd_size,
            current_image=self.current_image,
            overlay=self.overlay,
            mask_source_dir=self._mask_source_dir,
            media_source_path=self.media.source_path,
            media_is_playing=self.media.is_playing,
            current_theme_path=self.current_theme_path,
        )
        if ok:
            safe_name = f'Custom_{name}' if not name.startswith('Custom_') else name
            self.current_theme_path = data_dir / f'theme{self.lcd_width}{self.lcd_height}' / safe_name
        return ok, msg

    def export_config(self, export_path: Path) -> Tuple[bool, str]:
        """Export current theme as .tr or JSON file."""
        return ThemePersistence.export_config(
            export_path, self.current_theme_path,
            self.lcd_width, self.lcd_height,
        )

    def import_config(self, import_path: Path, data_dir: Path) -> Tuple[bool, str]:
        """Import theme from .tr or JSON file."""
        # Fall back to user-writable dir on system-wide installs (#51)
        if not os.access(data_dir, os.W_OK):
            from ..adapters.infra.data_repository import USER_DATA_DIR
            data_dir = Path(USER_DATA_DIR)
        ok, result = ThemePersistence.import_config(
            import_path, data_dir, self.lcd_size)
        if ok and not isinstance(result, str):
            self.load_local_theme(result)
            return True, f"Imported: {import_path.stem}"
        return ok, result if isinstance(result, str) else "Import failed"

    # -- Directory properties ----------------------------------------------

    @property
    def local_dir(self) -> Path | None:
        return self._local_dir

    @property
    def web_dir(self) -> Path | None:
        return self._web_dir

    @property
    def masks_dir(self) -> Path | None:
        return self._masks_dir
