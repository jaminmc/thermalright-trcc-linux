"""Display orientation — owns rotation state + content directory refs.

Holds landscape/portrait directory paths for each content type (themes,
web backgrounds, masks). On rotation, properties resolve to the correct
dir. When a portrait dir doesn't exist, the landscape dir is used and
the output gets pixel-rotated instead.

C# equivalents:
    output_resolution  → directionB + is{W}x{H} flags (physical output shape)
    canvas_resolution  → rendering dims (swaps only when portrait dirs exist)
    image_rotation     → RotateImg() dispatch in ImageToJpg
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)


def output_resolution(w: int, h: int, rotation: int) -> tuple[int, int]:
    """Physical output shape — always swaps for non-square at 90/270.

    Standalone function for callers without a DisplayService (CLI, GUI init).
    """
    if w != h and rotation in (90, 270):
        return (h, w)
    return (w, h)


class Orientation:
    """Rotation state + content directory resolution for one LCD device."""

    def __init__(self, width: int, height: int) -> None:
        self.native = (width, height)
        self.rotation: int = 0

        # Landscape dirs (always set when device has content)
        self.landscape_theme_dir: Any | None = None
        self.landscape_web_dir: Path | None = None
        self.landscape_masks_dir: Path | None = None

        # Portrait dirs (None when no rotated content exists)
        self.portrait_theme_dir: Any | None = None
        self.portrait_web_dir: Path | None = None
        self.portrait_masks_dir: Path | None = None

    # ── Computed state ──────────────────────────────────────────────

    @property
    def is_square(self) -> bool:
        return self.native[0] == self.native[1]

    @property
    def is_portrait(self) -> bool:
        """True when rotation is 90 or 270 on a non-square device."""
        return not self.is_square and self.rotation in (90, 270)

    @property
    def has_rotated_dirs(self) -> bool:
        """True when any portrait content directory exists on disk."""
        return (self.portrait_theme_dir is not None
                or self.portrait_web_dir is not None
                or self.portrait_masks_dir is not None)

    @property
    def swaps_dirs(self) -> bool:
        """True when portrait dirs exist and rotation is 90/270."""
        return self.is_portrait and self.has_rotated_dirs

    # ── Resolution properties ───────────────────────────────────────

    @property
    def output_resolution(self) -> tuple[int, int]:
        """Physical device output shape — always swaps for non-square at 90/270."""
        w, h = self.native
        if self.is_portrait:
            return (h, w)
        return (w, h)

    @property
    def canvas_resolution(self) -> tuple[int, int]:
        """Internal rendering resolution — only swaps when dirs swap."""
        w, h = self.native
        if self.swaps_dirs:
            return (h, w)
        return (w, h)

    @property
    def image_rotation(self) -> int:
        """Degrees to pixel-rotate the composited output.

        0 when portrait dirs handle orientation (content is already portrait).
        Actual degrees when pixel rotation is needed (no portrait dirs, or square).
        """
        if self.swaps_dirs:
            return 0
        return self.rotation

    # ── Active directory properties ─────────────────────────────────
    # Each content type swaps independently based on its own portrait dir.

    @property
    def theme_dir(self) -> Any | None:
        if self.is_portrait and self.portrait_theme_dir is not None:
            return self.portrait_theme_dir
        return self.landscape_theme_dir

    @property
    def web_dir(self) -> Path | None:
        if self.is_portrait and self.portrait_web_dir is not None:
            return self.portrait_web_dir
        return self.landscape_web_dir

    @property
    def masks_dir(self) -> Path | None:
        if self.is_portrait and self.portrait_masks_dir is not None:
            return self.portrait_masks_dir
        return self.landscape_masks_dir

    # ── Serialization ──────────────────────────────────────────────

    def to_dict(self) -> dict[str, str | None]:
        """Serialize resolved dirs for config persistence."""
        return {
            'theme': str(self.landscape_theme_dir.path) if self.landscape_theme_dir else None,
            'web': str(self.landscape_web_dir) if self.landscape_web_dir else None,
            'masks': str(self.landscape_masks_dir) if self.landscape_masks_dir else None,
            'theme_portrait': str(self.portrait_theme_dir.path) if self.portrait_theme_dir else None,
            'web_portrait': str(self.portrait_web_dir) if self.portrait_web_dir else None,
            'masks_portrait': str(self.portrait_masks_dir) if self.portrait_masks_dir else None,
        }

    @classmethod
    def from_dict(cls, width: int, height: int, dirs: dict) -> 'Orientation | None':
        """Restore from stored config dirs. Returns None if malformed/stale."""
        if not isinstance(dirs, dict):
            return None
        # Must have at least the landscape theme dir
        theme = dirs.get('theme')
        if not theme:
            return None

        from ..core.models import ThemeDir

        o = cls(width, height)
        o.landscape_theme_dir = ThemeDir(theme)
        o.landscape_web_dir = Path(dirs['web']) if dirs.get('web') else None
        o.landscape_masks_dir = Path(dirs['masks']) if dirs.get('masks') else None
        o.portrait_theme_dir = ThemeDir(dirs['theme_portrait']) if dirs.get('theme_portrait') else None
        o.portrait_web_dir = Path(dirs['web_portrait']) if dirs.get('web_portrait') else None
        o.portrait_masks_dir = Path(dirs['masks_portrait']) if dirs.get('masks_portrait') else None
        return o
