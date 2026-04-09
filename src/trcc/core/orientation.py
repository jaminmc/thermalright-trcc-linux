"""Display orientation — owns rotation state + content directory refs.

Stores native resolution, rotation, and two root paths (data + user content).
All content directories are derived from resolution math + dir name helpers.
No stored dir lists — the dir name encodes the orientation.

C# equivalents:
    output_resolution  → directionB + is{W}x{H} flags (physical output shape)
    canvas_resolution  → rendering dims (swaps only when portrait themes exist)
    image_rotation     → RotateImg() dispatch in ImageToJpg
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any

from .paths import masks_dir_name, theme_dir_name, web_dir_name

log = logging.getLogger(__name__)


def output_resolution(w: int, h: int, rotation: int) -> tuple[int, int]:
    """Physical output shape — always swaps for non-square at 90/270.

    Standalone function for callers without a DisplayService (CLI, GUI init).
    """
    if w != h and rotation in (90, 270):
        return (h, w)
    return (w, h)


class Orientation:
    """Rotation state + content directory resolution for one LCD device.

    Stores two root paths and native resolution. All content directories
    are derived: root / dir_name(w, h). Rotation swaps w,h in the name.
    """

    def __init__(self, width: int, height: int) -> None:
        self.native = (width, height)
        self.rotation: int = 0

        # Root paths (set by _setup_dirs after connect)
        self.data_root: Path | None = None      # ~/.trcc/data
        self.user_root: Path | None = None       # ~/.trcc-user/data

        # Probed at init — only non-derivable fact
        self.has_portrait_themes: bool = False

    # ── Resolution helpers ─────────────────────────────────────────

    def _is_rotated(self) -> bool:
        """True when rotation is 90/270 on a non-square device."""
        w, h = self.native
        return w != h and self.rotation in (90, 270)

    def _rotated_res(self) -> tuple[int, int]:
        """Resolution with w,h swapped if rotated."""
        w, h = self.native
        return (h, w) if self._is_rotated() else (w, h)

    # ── Resolution properties ──────────────────────────────────────

    @property
    def output_resolution(self) -> tuple[int, int]:
        """Physical device output shape — always swaps for non-square at 90/270."""
        return self._rotated_res()

    @property
    def canvas_resolution(self) -> tuple[int, int]:
        """Internal rendering resolution — only swaps when portrait themes exist."""
        if self.has_portrait_themes and self._is_rotated():
            w, h = self.native
            return (h, w)
        return self.native

    @property
    def image_rotation(self) -> int:
        """Degrees to pixel-rotate the composited output.

        0 when portrait theme dirs handle orientation (content already portrait).
        Actual degrees when pixel rotation is needed.
        """
        if self.has_portrait_themes and self._is_rotated():
            return 0
        return self.rotation

    # ── Content directory properties ───────────────────────────────
    # All derived from roots + resolution. Rotation swaps w,h in the name.

    @property
    def theme_dir(self) -> Any | None:
        """Active theme dir. Swaps only when portrait themes exist."""
        if not self.data_root:
            return None
        from .models import ThemeDir
        w, h = self.canvas_resolution
        return ThemeDir(str(self.data_root / theme_dir_name(w, h)))

    @property
    def web_dir(self) -> Path | None:
        """Active cloud backgrounds dir. Swaps independently on rotation."""
        if not self.data_root:
            return None
        w, h = self._rotated_res()
        d = self.data_root / 'web' / web_dir_name(w, h)
        return d if d.exists() else None

    @property
    def masks_dir(self) -> Path | None:
        """Active masks dir. Swaps independently on rotation."""
        if not self.data_root:
            return None
        w, h = self._rotated_res()
        d = self.data_root / 'web' / masks_dir_name(w, h)
        return d if d.exists() else None

    @property
    def user_theme_dir(self) -> Path | None:
        """User custom themes dir (~/.trcc-user/data/theme{W}{H})."""
        if not self.user_root:
            return None
        w, h = self.canvas_resolution
        d = self.user_root / theme_dir_name(w, h)
        return d if d.exists() else None

    @property
    def user_masks_dir(self) -> Path | None:
        """User custom masks dir (~/.trcc-user/data/web/zt{W}{H})."""
        if not self.user_root:
            return None
        w, h = self._rotated_res()
        d = self.user_root / 'web' / masks_dir_name(w, h)
        return d if d.exists() else None

    # ── Serialization ──────────────────────────────────────────────

    def to_dict(self) -> dict[str, Any]:
        """Serialize for config persistence."""
        return {
            'data_root': str(self.data_root) if self.data_root else None,
            'user_root': str(self.user_root) if self.user_root else None,
            'has_portrait_themes': self.has_portrait_themes,
        }

    @classmethod
    def from_dict(cls, width: int, height: int, dirs: dict) -> 'Orientation | None':
        """Restore from stored config. Returns None if malformed."""
        if not isinstance(dirs, dict):
            return None
        if not (data_root := dirs.get('data_root')):
            # Legacy format — extract data_root from theme dir path
            if not (theme := dirs.get('theme')):
                return None
            data_root = str(Path(theme).parent)
        o = cls(width, height)
        o.data_root = Path(data_root)
        if dirs.get('user_root'):
            o.user_root = Path(dirs['user_root'])
        o.has_portrait_themes = dirs.get('has_portrait_themes', False)
        return o
