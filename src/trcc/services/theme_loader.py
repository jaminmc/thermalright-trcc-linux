"""Theme loading orchestrator — loads local, cloud, and mask themes.

Extracted from DisplayService (SRP). Receives injected OverlayService +
MediaService. Returns result dicts; DisplayService wires up state.
"""
from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Any

from ..adapters.infra.data_repository import ThemeDir
from .image import ImageService
from .media import MediaService
from .overlay import OverlayService
from .theme import _copy_flat_files

log = logging.getLogger(__name__)


class ThemeLoader:
    """Loads themes from local dirs, cloud, and mask overlays.

    Stateless except for injected service references. All mutable display
    state stays in DisplayService.
    """

    def __init__(self, overlay: OverlayService, media: MediaService) -> None:
        self._overlay = overlay
        self._media = media

    def load_local_theme(
        self, theme, lcd_size: tuple[int, int],
        working_dir: Path,
    ) -> dict:
        """Load a local theme with DC config, mask, and overlay.

        Returns dict with keys:
            'image': PIL Image (rendered preview) or None
            'is_animated': bool
            'status': str
            'mask_source_dir': Path or None (for caller to store)
            'theme_path': Path
        """
        log.info("Loading local theme: %s", theme.path)
        self._media.stop()

        # Full reset
        self._overlay.enabled = False
        self._overlay.set_background(None)
        self._overlay.set_mask(None)
        self._overlay.set_config({})

        assert theme.path is not None
        td = ThemeDir(theme.path)

        # Reference-based theme (config.json exists)
        if td.json.exists():
            return self._load_reference_theme(theme, td, lcd_size, working_dir)

        # Copy-based theme (original behavior)
        return self._load_copy_theme(theme, td, lcd_size, working_dir)

    def _load_reference_theme(
        self, theme, td: ThemeDir,
        lcd_size: tuple[int, int], working_dir: Path,
    ) -> dict:
        """Load theme by path references (config.json)."""
        display_opts = self._overlay.load_from_dc(td.dc)

        if display_opts.get('overlay_enabled'):
            self._overlay.enabled = True

        mask_source_dir: Path | None = None

        # Load mask by reference
        mask_ref = display_opts.get('mask_path')
        if mask_ref:
            mask_td = ThemeDir(mask_ref)
            if mask_td.mask.exists():
                mask_source_dir = mask_td.path
                self._load_mask(mask_td.mask, None, lcd_size)
                mask_pos = display_opts.get('mask_position')
                if mask_pos:
                    mask_img, _ = self._overlay.get_mask()
                    self._overlay.set_mask(mask_img, mask_pos)

        # Load background by reference
        result: dict[str, Any] = {
            'image': None, 'is_animated': False,
            'status': f"Theme: {theme.name}",
            'mask_source_dir': mask_source_dir,
            'theme_path': theme.path,
        }
        bg_ref = display_opts.get('background_path')
        if bg_ref:
            bg_path = Path(bg_ref)
            if not bg_path.exists() and td.bg.exists():
                bg_path = td.bg
            if bg_path.exists():
                if bg_path.suffix in ('.mp4', '.avi', '.mkv', '.webm', '.zt'):
                    self._load_and_play_video(bg_path)
                    result['is_animated'] = True
                else:
                    result['image'] = self._load_static_image(bg_path, lcd_size)
        elif td.bg.exists():
            result['image'] = self._load_static_image(td.bg, lcd_size)

        return result

    def _load_copy_theme(
        self, theme, td: ThemeDir,
        lcd_size: tuple[int, int], working_dir: Path,
    ) -> dict:
        """Load theme by copying to working dir (original behavior)."""
        # Clear and copy
        if working_dir.exists():
            shutil.rmtree(working_dir)
        working_dir.mkdir(parents=True, exist_ok=True)
        _copy_flat_files(theme.path, working_dir)

        wd = ThemeDir(working_dir)
        display_opts = self._overlay.load_from_dc(wd.dc)

        mask_source_dir: Path | None = None
        result: dict[str, Any] = {
            'image': None, 'is_animated': False,
            'status': f"Theme: {theme.name}",
            'mask_source_dir': None,
            'theme_path': theme.path,
        }

        # Load background / animation
        anim_file = display_opts.get('animation_file')
        if anim_file:
            anim_path = working_dir / anim_file
            if anim_path.exists():
                self._load_and_play_video(anim_path)
                result['is_animated'] = True
            elif theme.is_animated and theme.animation_path:
                self._load_and_play_video(theme.animation_path)
                result['is_animated'] = True
        elif theme.is_animated and theme.animation_path:
            wd_copy = working_dir / Path(theme.animation_path).name
            load_path = wd_copy if wd_copy.exists() else theme.animation_path
            self._load_and_play_video(load_path)
            result['is_animated'] = True
        elif wd.zt.exists():
            self._load_and_play_video(wd.zt)
            result['is_animated'] = True
        elif wd.bg.exists():
            mp4_files = list(working_dir.glob('*.mp4'))
            if mp4_files:
                self._load_and_play_video(mp4_files[0])
                result['is_animated'] = True
            else:
                result['image'] = self._load_static_image(wd.bg, lcd_size)
        elif theme.is_mask_only:
            result['image'] = ImageService.solid_color(0, 0, 0, *lcd_size)

        # Load mask from working dir
        if wd.mask.exists():
            mask_source_dir = theme.path
            self._load_mask(wd.mask, wd.dc if wd.dc.exists() else None, lcd_size)

        result['mask_source_dir'] = mask_source_dir
        return result

    def load_cloud_theme(self, theme, working_dir: Path) -> dict:
        """Load a cloud video theme as background."""
        self._media.stop()

        if theme.animation_path:
            video_path = Path(theme.animation_path)
            if video_path.exists():
                dest = working_dir / video_path.name
                if not dest.exists():
                    shutil.copy2(str(video_path), str(dest))
            self._load_and_play_video(theme.animation_path)

        return {
            'image': None,
            'is_animated': True,
            'status': f"Cloud Theme: {theme.name}",
            'mask_source_dir': None,
            'theme_path': None,
        }

    def apply_mask(
        self, mask_dir: Path, working_dir: Path,
        lcd_size: tuple[int, int],
    ) -> Path | None:
        """Apply a mask overlay on top of current content.

        Returns the mask source dir (for caller to store), or None.
        """
        if not mask_dir or not mask_dir.exists():
            return None

        _copy_flat_files(mask_dir, working_dir)

        wd = ThemeDir(working_dir)
        self._overlay.load_from_dc(wd.dc)

        if wd.mask.exists():
            self._load_mask(wd.mask, wd.dc if wd.dc.exists() else None, lcd_size)

        self._overlay.enabled = True
        return mask_dir

    # ── Internal helpers ─────────────────────────────────────────────

    def _load_static_image(self, path: Path, lcd_size: tuple[int, int]) -> Any | None:
        """Load and resize a static image to LCD dimensions."""
        try:
            return ImageService.open_and_resize(path, *lcd_size)
        except Exception as e:
            log.error("Failed to load image: %s", e)
            return None

    def _load_and_play_video(self, path: Path) -> None:
        """Load video and start playback."""
        self._media.load(path)
        self._media.play()

    def _load_mask(self, mask_path: Path, dc_path: Path | None,
                   lcd_size: tuple[int, int]) -> None:
        """Load mask image with position from DC config."""
        try:
            from PIL import Image
            mask_img = Image.open(mask_path)
            position = self._parse_mask_position(dc_path, mask_img, lcd_size)
            self._overlay.set_mask(mask_img, position)
        except Exception as e:
            log.error("Failed to load mask: %s", e)

    @staticmethod
    def _parse_mask_position(dc_path: Path | None, mask_img: Any,
                             lcd_size: tuple[int, int]) -> tuple[int, int] | None:
        """Parse mask position from DC file, convert center to top-left coords."""
        lcd_w, lcd_h = lcd_size
        if mask_img.width >= lcd_w and mask_img.height >= lcd_h:
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
