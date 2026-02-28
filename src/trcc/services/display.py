"""Display pipeline orchestrator — coordinates theme, overlay, media → LCD frame.

Pure Python, no Qt dependencies.
Controllers (PySide6, Typer CLI, FastAPI) are thin wrappers that call this
service and fire callbacks.
"""
from __future__ import annotations

import json
import logging
import shutil
import tempfile
from pathlib import Path
from typing import Any, Tuple

from ..adapters.infra.data_repository import RESOURCES_DIR, DataManager, ThemeDir
from ..conf import settings
from ..core.models import JPEG_MODE_FBLS, SPLIT_MODE_RESOLUTIONS, SPLIT_OVERLAY_MAP
from .device import DeviceService
from .image import ImageService
from .media import MediaService
from .overlay import OverlayService
from .theme import ThemeService, _copy_flat_files

log = logging.getLogger(__name__)


class DisplayService:
    """Display pipeline: theme → overlay → brightness/rotation → LCD frame.

    Orchestrates sub-services (DeviceService, OverlayService, MediaService).
    Sub-services are injected, not owned.
    """

    def __init__(self,
                 devices: DeviceService,
                 overlay: OverlayService,
                 media: MediaService) -> None:
        # Sub-services (injected)
        self.devices = devices
        self.overlay = overlay
        self.media = media

        # Working directory (Windows GifDirectory pattern)
        self.working_dir = Path(tempfile.mkdtemp(prefix='trcc_work_'))

        # State
        self.current_image: Any | None = None  # PIL Image
        self.current_theme_path: Path | None = None
        self.auto_send = True
        self.rotation = 0         # directionB: 0, 90, 180, 270
        self.brightness = 50      # percent (0-100)
        self.split_mode = 0       # myLddVal: 0=off, 1-3=Dynamic Island style
        self._split_overlay_cache: dict[tuple[int, int], Any] = {}  # (style,rot)→PIL

        # Theme directories
        self._local_dir: Path | None = None
        self._web_dir: Path | None = None
        self._masks_dir: Path | None = None
        self._mask_source_dir: Path | None = None

    # ── Properties ────────────────────────────────────────────────────

    @property
    def lcd_width(self) -> int:
        return settings.width

    @property
    def lcd_height(self) -> int:
        return settings.height

    @property
    def lcd_size(self) -> tuple[int, int]:
        return (settings.width, settings.height)

    # ── Initialization ────────────────────────────────────────────────

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

    # ── Resolution ────────────────────────────────────────────────────

    def set_resolution(self, width: int, height: int, persist: bool = True) -> None:
        """Set LCD resolution and update sub-services."""
        if width == self.lcd_width and height == self.lcd_height:
            return
        log.info("Resolution changed: %dx%d → %dx%d",
                 self.lcd_width, self.lcd_height, width, height)
        settings.set_resolution(width, height, persist=persist)
        self.media.set_target_size(width, height)
        self.overlay.set_resolution(width, height)

        if width and height:
            self._setup_dirs(width, height)

    # ── Display adjustments ───────────────────────────────────────────

    def set_rotation(self, degrees: int) -> Any | None:
        """Set display rotation. Returns rendered image or None."""
        self.rotation = degrees % 360
        return self._render_and_process()

    def set_brightness(self, percent: int) -> Any | None:
        """Set display brightness. Returns rendered image or None."""
        self.brightness = max(0, min(100, percent))
        return self._render_and_process()

    def set_split_mode(self, mode: int) -> Any | None:
        """Set split mode (C# myLddVal: 0=off, 1-3=Dynamic Island style).

        Only affects 1600x720 widescreen devices. Returns rendered image.
        """
        self.split_mode = mode if mode in (0, 1, 2, 3) else 0
        return self._render_and_process()

    @property
    def is_widescreen_split(self) -> bool:
        """True if current resolution supports split mode (灵动岛)."""
        return self.lcd_size in SPLIT_MODE_RESOLUTIONS

    # ── Theme loading ─────────────────────────────────────────────────

    def load_local_theme(self, theme) -> dict:
        """Load a local theme with DC config, mask, and overlay.

        Returns dict with keys:
            'image': PIL Image (rendered preview) or None
            'is_animated': bool
            'status': str
        """
        log.info("Loading local theme: %s", theme.path)
        self.media.stop()

        # Full reset
        self.overlay.enabled = False
        self.overlay.set_background(None)
        self.overlay.set_mask(None)
        self.overlay.set_config({})
        self._mask_source_dir = None
        self.current_image = None
        self.current_theme_path = theme.path
        assert theme.path is not None

        td = ThemeDir(theme.path)

        # Reference-based theme (config.json exists)
        if td.json.exists():
            return self._load_reference_theme(theme, td)

        # Copy-based theme (original behavior)
        return self._load_copy_theme(theme, td)

    def _load_reference_theme(self, theme, td: ThemeDir) -> dict:
        """Load theme by path references (config.json)."""
        display_opts = self.overlay.load_from_dc(td.dc)

        if display_opts.get('overlay_enabled'):
            self.overlay.enabled = True

        # Load mask by reference
        mask_ref = display_opts.get('mask_path')
        if mask_ref:
            mask_td = ThemeDir(mask_ref)
            if mask_td.mask.exists():
                self._mask_source_dir = mask_td.path
                self._load_mask(mask_td.mask, None)
                mask_pos = display_opts.get('mask_position')
                if mask_pos:
                    mask_img, _ = self.overlay.get_mask()
                    self.overlay.set_mask(mask_img, mask_pos)

        # Load background by reference
        result = {'image': None, 'is_animated': False, 'status': f"Theme: {theme.name}"}
        bg_ref = display_opts.get('background_path')
        if bg_ref:
            bg_path = Path(bg_ref)
            if bg_path.exists():
                if bg_path.suffix in ('.mp4', '.avi', '.mkv', '.webm', '.zt'):
                    self._load_and_play_video(bg_path)
                    result['is_animated'] = True
                    result['image'] = self.current_image
                else:
                    self._load_static_image(bg_path)
                    result['image'] = self._render_and_process()

        return result

    def _load_copy_theme(self, theme, td: ThemeDir) -> dict:
        """Load theme by copying to working dir (original behavior)."""
        self._copy_to_working_dir(theme.path)

        wd = ThemeDir(self.working_dir)
        display_opts = self.overlay.load_from_dc(wd.dc)

        result = {'image': None, 'is_animated': False, 'status': f"Theme: {theme.name}"}

        # Load background / animation
        anim_file = display_opts.get('animation_file')
        if anim_file:
            anim_path = self.working_dir / anim_file
            if anim_path.exists():
                self._load_and_play_video(anim_path)
                result['is_animated'] = True
            elif theme.is_animated and theme.animation_path:
                self._load_and_play_video(theme.animation_path)
                result['is_animated'] = True
        elif theme.is_animated and theme.animation_path:
            wd_copy = self.working_dir / Path(theme.animation_path).name
            load_path = wd_copy if wd_copy.exists() else theme.animation_path
            self._load_and_play_video(load_path)
            result['is_animated'] = True
        elif wd.zt.exists():
            self._load_and_play_video(wd.zt)
            result['is_animated'] = True
        elif wd.bg.exists():
            mp4_files = list(self.working_dir.glob('*.mp4'))
            if mp4_files:
                self._load_and_play_video(mp4_files[0])
                result['is_animated'] = True
            else:
                self._load_static_image(wd.bg)
        elif theme.is_mask_only:
            self._create_black_background()

        # Load mask from working dir
        if wd.mask.exists():
            self._mask_source_dir = theme.path
            self._load_mask(wd.mask, wd.dc if wd.dc.exists() else None)

        result['image'] = self._render_and_process()
        return result

    def load_cloud_theme(self, theme) -> dict:
        """Load a cloud video theme as background."""
        self.media.stop()

        if theme.animation_path:
            video_path = Path(theme.animation_path)
            if video_path.exists():
                dest = self.working_dir / video_path.name
                if not dest.exists():
                    shutil.copy2(str(video_path), str(dest))
            self._load_and_play_video(theme.animation_path)

        return {
            'image': self.current_image,
            'is_animated': True,
            'status': f"Cloud Theme: {theme.name}",
        }

    def apply_mask(self, mask_dir: Path) -> Any | None:
        """Apply a mask overlay on top of current content."""
        if not mask_dir or not mask_dir.exists():
            return None

        self._mask_source_dir = mask_dir
        _copy_flat_files(mask_dir, self.working_dir)

        wd = ThemeDir(self.working_dir)
        self.overlay.load_from_dc(wd.dc)

        if wd.mask.exists():
            self._load_mask(wd.mask, wd.dc if wd.dc.exists() else None)

        self.overlay.enabled = True

        if not self.current_image:
            self._create_black_background()

        return self.render_overlay()

    # ── Image loading ─────────────────────────────────────────────────

    def load_image_file(self, path: Path) -> Any | None:
        """Load a static image file. Returns rendered image or None."""
        self._load_static_image(path)
        return self._render_and_process()

    def _load_static_image(self, path: Path) -> None:
        """Load and resize a static image to LCD dimensions."""
        try:
            self.current_image = ImageService.open_and_resize(path, *self.lcd_size)
        except Exception as e:
            log.error("Failed to load image: %s", e)

    def _load_and_play_video(self, path: Path) -> None:
        """Load video, set first frame as current image, start playback."""
        self.media.load(path)
        first_frame = self.media.get_frame(0)
        if first_frame:
            self.current_image = first_frame
        self.media.play()

    def _create_black_background(self) -> None:
        """Create black background for mask-only themes."""
        self.current_image = ImageService.solid_color(0, 0, 0, *self.lcd_size)

    # ── Mask loading ──────────────────────────────────────────────────

    def _load_mask(self, mask_path: Path, dc_path: Path | None = None) -> None:
        """Load mask image with position from DC config."""
        try:
            from PIL import Image
            mask_img = Image.open(mask_path)
            position = self._parse_mask_position(dc_path, mask_img)
            self.overlay.set_mask(mask_img, position)
        except Exception as e:
            log.error("Failed to load mask: %s", e)

    def _parse_mask_position(self, dc_path: Path | None, mask_img: Any) -> tuple[int, int] | None:
        """Parse mask position from DC file, convert center to top-left coords."""
        if mask_img.width >= self.lcd_width and mask_img.height >= self.lcd_height:
            return (0, 0)

        if not dc_path or not Path(dc_path).exists():
            return None

        try:
            from ..adapters.infra.dc_config import DcConfig
            dc = DcConfig(dc_path)
            if dc.mask_enabled:
                center_pos = dc.mask_settings.get('mask_position')
                if center_pos:
                    return (
                        center_pos[0] - mask_img.width // 2,
                        center_pos[1] - mask_img.height // 2,
                    )
        except Exception:
            pass
        return None

    # ── Working directory ─────────────────────────────────────────────

    def _clear_working_dir(self) -> None:
        """Clear and recreate working directory."""
        if self.working_dir.exists():
            shutil.rmtree(self.working_dir)
        self.working_dir.mkdir(parents=True, exist_ok=True)

    def _copy_to_working_dir(self, source: Path) -> None:
        """Copy theme files to working dir."""
        self._clear_working_dir()
        _copy_flat_files(source, self.working_dir)

    # ── Rendering ─────────────────────────────────────────────────────

    def _render_and_process(self) -> Any | None:
        """Render overlay on current image, apply brightness + rotation."""
        if not self.current_image:
            return None
        image = self.current_image
        if self.overlay.enabled:
            image = self.overlay.render(image)
        return self._apply_adjustments(image)

    def render_overlay(self) -> Any | None:
        """Force-render overlay (for live editing). Returns image or None."""
        if not self.current_image:
            self._create_black_background()
        image = self.overlay.render(self.current_image, force=True)
        return self._apply_adjustments(image)

    def _apply_adjustments(self, image: Any) -> Any:
        """Apply brightness, rotation, and split overlay to image."""
        if self.brightness >= 100 and self.rotation == 0 and not self.split_mode:
            return image
        image = ImageService.apply_brightness(image, self.brightness)
        image = ImageService.apply_rotation(image, self.rotation)
        image = self._apply_split_overlay(image)
        return image

    def _apply_split_overlay(self, image: Any) -> Any:
        """Composite Dynamic Island (灵动岛) overlay for widescreen split mode.

        C# UCScreenImage.cs: overlay selected by (myLddVal, directionB),
        alpha-composited on top of the rotated frame.
        """
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
            from PIL import Image as PILImage
            if image.mode != 'RGBA':
                image = image.convert('RGBA')
            # Resize overlay if it doesn't match (shouldn't happen, but safe)
            if overlay.size != image.size:
                overlay = overlay.resize(image.size, PILImage.Resampling.LANCZOS)
            image = PILImage.alpha_composite(image, overlay)
            return image.convert('RGB')
        except Exception as e:
            log.error("Split overlay composite failed: %s", e)
            return image

    @staticmethod
    def _load_split_overlay(asset_name: str) -> Any | None:
        """Load a split overlay PNG from assets/gui/ as PIL RGBA Image."""
        import os
        try:
            from PIL import Image as PILImage
            path = os.path.join(RESOURCES_DIR, asset_name)
            if os.path.exists(path):
                img = PILImage.open(path).convert('RGBA')
                return img
            log.warning("Split overlay not found: %s", path)
        except Exception as e:
            log.error("Failed to load split overlay %s: %s", asset_name, e)
        return None

    def set_video_fit_mode(self, mode: str) -> Any | None:
        """Set video fit mode (C# UCBoFangQiKongZhi: buttonTPJCW/buttonTPJCH).

        mode: 'fill' (stretch), 'width' (letterbox width), 'height' (letterbox height).
        Re-decodes video frames with adjusted scaling. Returns preview image.
        """
        if self.media.set_fit_mode(mode):
            # Get current frame for preview
            frame = self.media.get_frame()
            if frame:
                self.current_image = frame
                return self._render_and_process()
        return self._render_and_process()

    # ── Video playback ────────────────────────────────────────────────

    def video_tick(self) -> dict | None:
        """Advance one video frame. Returns dict or None if not playing."""
        frame, should_send, progress = self.media.tick()
        if not frame:
            return None

        self.current_image = frame

        if self.overlay.enabled:
            frame = self.overlay.render(frame)

        processed = self._apply_adjustments(frame)

        result: dict[str, Any] = {'preview': processed, 'progress': progress}

        if should_send and self.auto_send:
            result['send_image'] = processed
        else:
            result['send_image'] = None

        return result

    def get_video_interval(self) -> int:
        """Get video frame interval in ms for timer setup."""
        return self.media.frame_interval_ms

    def is_video_playing(self) -> bool:
        """Check if video is currently playing."""
        return self.media.is_playing

    # ── LCD send ──────────────────────────────────────────────────────

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
        """Encode image for LCD device.

        C# protocol encoding depends on device type:
        - Bulk: JPEG (ImageToJpg) for most PMs; PM=32 uses RGB565 (cmd=3)
        - HID Type 2 with JPEG_MODE_FBLS: JPEG (ImageToJpg), no rotation
        - SCSI / HID (standard): RGB565 (ImageTo565), non-square pre-rotation

        C# ImageTo565 rotates non-square displays +90° CW before encoding.
        ImageToJpg does NOT rotate.
        """
        device = self.devices.selected
        protocol = device.protocol if device else 'scsi'
        resolution = device.resolution if device else (320, 320)
        fbl = device.fbl_code if device else None

        # Bulk (most use JPEG, PM=32 uses RGB565) and HID JPEG-mode devices
        use_jpeg = device.use_jpeg if device else True
        if (protocol in ('bulk', 'ly') and use_jpeg) or (protocol == 'hid' and fbl in JPEG_MODE_FBLS):
            data = ImageService.to_jpeg(img)
            log.debug("_encode_for_device: %dx%d → JPEG %d bytes (protocol=%s, fbl=%s)",
                      img.width, img.height, len(data), protocol, fbl)
            return data

        # C# ImageTo565: non-square displays rotate +90° CW before encoding.
        img = ImageService.apply_device_rotation(img, resolution)
        byte_order = ImageService.byte_order_for(protocol, resolution, fbl)
        data = ImageService.to_rgb565(img, byte_order)
        log.debug("_encode_for_device: %dx%d mode=%s order=%s → RGB565 %d bytes",
                  img.width, img.height, img.mode, byte_order, len(data))
        return data

    # ── Theme save (delegates to ThemeService) ────────────────────────

    def save_theme(self, name: str, data_dir: Path) -> Tuple[bool, str]:
        """Save current config as a custom theme."""
        if not self.current_image:
            return False, "No image to save"

        rendered = self.overlay.render(self.current_image)
        mask_img, mask_pos = self.overlay.get_mask()
        overlay_config = self._get_overlay_config()

        ok, msg = ThemeService.save(
            name, data_dir, self.lcd_size,
            background=rendered,
            overlay_config=overlay_config,
            mask=mask_img,
            mask_source=self._mask_source_dir,
            mask_position=mask_pos,
            video_path=self.media.source_path if self.media.is_playing else None,
            current_theme_path=self.current_theme_path,
        )
        if ok:
            safe_name = f'Custom_{name}' if not name.startswith('Custom_') else name
            self.current_theme_path = data_dir / f'theme{self.lcd_width}{self.lcd_height}' / safe_name
        return ok, msg

    def _get_overlay_config(self) -> dict:
        """Get current overlay config for saving."""
        return self.overlay.config

    # ── Theme export / import (delegates to ThemeService) ─────────────

    def export_config(self, export_path: Path) -> Tuple[bool, str]:
        """Export current theme as .tr or JSON file."""
        if not self.current_theme_path:
            return False, "No theme loaded"

        if str(export_path).endswith('.tr'):
            return ThemeService.export_tr(self.current_theme_path, export_path)

        # JSON export
        config = {
            'theme_path': str(self.current_theme_path),
            'resolution': f'{self.lcd_width}x{self.lcd_height}',
        }
        try:
            with open(str(export_path), 'w') as f:
                json.dump(config, f, indent=2)
            return True, f"Exported: {export_path.name}"
        except Exception as e:
            return False, f"Export failed: {e}"

    def import_config(self, import_path: Path, data_dir: Path) -> Tuple[bool, str]:
        """Import theme from .tr or JSON file."""
        if str(import_path).endswith('.tr'):
            ok, result = ThemeService.import_tr(import_path, data_dir, self.lcd_size)
            if ok and not isinstance(result, str):
                self.load_local_theme(result)
                return True, f"Imported: {import_path.stem}"
            return ok, result if isinstance(result, str) else "Import failed"

        # JSON import
        try:
            with open(str(import_path)) as f:
                config = json.load(f)
            tp = config.get('theme_path')
            if tp and Path(tp).exists():
                from ..core.models import ThemeInfo
                theme = ThemeInfo.from_directory(Path(tp))
                self.load_local_theme(theme)
                return True, f"Imported config from {import_path.name}"
            return False, "Theme path in config not found"
        except Exception as e:
            return False, f"Import failed: {e}"

    # ── Directory properties ──────────────────────────────────────────

    @property
    def local_dir(self) -> Path | None:
        return self._local_dir

    @property
    def web_dir(self) -> Path | None:
        return self._web_dir

    @property
    def masks_dir(self) -> Path | None:
        return self._masks_dir
