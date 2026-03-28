"""Asset loader for PySide6 GUI components.

Centralizes all asset resolution — auto-appends .png for base names,
handles localized variants, and provides pixmap loading.

All GUI assets live in gui/assets/ and are extracted from Windows TRCC
resources using tools/extract_resx_images.py.
"""
from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtGui import QPixmap

log = logging.getLogger(__name__)

# Bundled asset directory (inside package)
_PKG_ASSETS_DIR = Path(__file__).parent / 'assets'

# Resolved at runtime by the platform adapter via set_assets_dir().
# Falls back to package dir until the builder initializes it.
_ASSETS_DIR = _PKG_ASSETS_DIR


def set_assets_dir(path: Path) -> None:
    """Set the resolved asset directory (called by platform adapter)."""
    global _ASSETS_DIR  # noqa: PLW0603
    _ASSETS_DIR = path
    _resolve.cache_clear()
    log.debug("Assets dir set to %s", path)


@lru_cache(maxsize=256)
def _resolve(name: str) -> Path:
    """Resolve asset name to filesystem path, auto-appending .png if needed.

    Data layer stores base names without extension (e.g. "DAX120_DIGITAL").
    All GUI assets are .png — this bridges that gap in one place.
    """
    path = _ASSETS_DIR / name
    if path.exists():
        return path
    if '.' not in name:
        png = _ASSETS_DIR / f"{name}.png"
        if png.exists():
            return png
    return path  # return original (non-existent) for consistent error handling


class Assets:
    """Centralized asset resolution for all GUI components.

    Handles .png auto-appending, pixmap loading, existence checks,
    and localized asset variants. Single entry point — no free functions.
    """

    # Form1 background (full window with sidebar + gold bar + sensor grid)
    FORM1_BG = 'App_main.png'

    # Main form backgrounds
    FORM_CZTV_BG = 'App_form.png'

    # Theme panel backgrounds (732x652)
    THEME_LOCAL_BG = 'App_theme_base.png'
    THEME_WEB_BG = 'App_theme_gallery.png'
    THEME_MASK_BG = 'App_theme_gallery.png'
    THEME_SETTING_BG = 'P0主题设置.png'

    # Preview frame backgrounds (500x500)
    PREVIEW_320X320 = 'P预览320X320.png'
    PREVIEW_320X240 = 'P预览320X240.png'
    PREVIEW_240X320 = 'P预览240X320.png'
    PREVIEW_240X240 = 'P预览240X240.png'
    PREVIEW_360X360 = 'P预览360360圆.png'
    PREVIEW_480X480 = 'P预览480X480.png'

    # Tab buttons (normal/selected)
    TAB_LOCAL = 'P本地主题.png'
    TAB_LOCAL_ACTIVE = 'P本地主题a.png'
    TAB_CLOUD = 'P云端背景.png'
    TAB_CLOUD_ACTIVE = 'P云端背景a.png'
    TAB_MASK = 'P云端主题.png'
    TAB_MASK_ACTIVE = 'P云端主题a.png'
    TAB_SETTINGS = 'P主题设置.png'
    TAB_SETTINGS_ACTIVE = 'P主题设置a.png'

    # Bottom control buttons
    BTN_SAVE = 'P保存主题.png'
    BTN_EXPORT = 'P导出.png'
    BTN_IMPORT = 'P导入.png'

    # Title bar buttons
    BTN_HELP = 'P帮助.png'
    BTN_POWER = 'Alogout默认.png'
    BTN_POWER_HOVER = 'Alogout选中.png'

    # Video controls background
    VIDEO_CONTROLS_BG = 'ucBoFangQiKongZhi1.BackgroundImage.png'

    # Settings panel sub-backgrounds (from UCThemeSetting.resx)
    SETTINGS_CONTENT = 'Panel_overlay.png'
    SETTINGS_PARAMS = 'Panel_params.png'

    # UCThemeSetting sub-component backgrounds (from .resx)
    OVERLAY_GRID_BG = 'ucXiTongXianShi1.BackgroundImage.png'        # 472x430
    OVERLAY_ADD_BG = 'ucXiTongXianShiAdd1.BackgroundImage.png'      # 230x430
    OVERLAY_COLOR_BG = 'ucXiTongXianShiColor1.BackgroundImage.png'  # 230x374
    OVERLAY_TABLE_BG = 'ucXiTongXianShiTable1.BackgroundImage.png'  # 230x54

    # Video cut background (from FormCZTV.resx)
    VIDEO_CUT_BG = 'ucVideoCut1.BackgroundImage.png'                # 500x702

    # Play/Pause icons
    ICON_PLAY = 'P0播放.png'
    ICON_PAUSE = 'P0暂停.png'

    # Sidebar (UCDevice)
    SIDEBAR_BG = 'A0硬件列表.png'
    SENSOR_BTN = 'A1传感器.png'
    SENSOR_BTN_ACTIVE = 'A1传感器a.png'
    ABOUT_BTN = 'A1关于.png'
    ABOUT_BTN_ACTIVE = 'A1关于a.png'

    # About / Control Center panel (UCAbout)
    ABOUT_BG = 'App_about.png'
    ABOUT_LOGOUT = 'Alogout默认.png'
    ABOUT_LOGOUT_HOVER = 'Alogout选中.png'
    CHECKBOX_OFF = 'P点选框.png'
    CHECKBOX_ON = 'P点选框A.png'
    UPDATE_BTN = 'A2立即更新.png'
    SYSINFO_BG = 'A0数据列表.png'

    @classmethod
    def path(cls, name: str) -> Path:
        """Resolve asset name to full path (.png auto-appended if needed)."""
        return _resolve(name)

    @classmethod
    def get(cls, name: str) -> str | None:
        """Return asset path as string if it exists, else None.

        Uses forward slashes — Qt stylesheets interpret backslashes
        as CSS escapes (C:\\Users → C:Users).
        """
        p = _resolve(name)
        return p.as_posix() if p.exists() else None

    @classmethod
    def exists(cls, name: str) -> bool:
        """Check if an asset file exists (.png auto-appended if needed)."""
        return _resolve(name).exists()

    @classmethod
    @lru_cache(maxsize=128)
    def load_pixmap(cls, name: str,
                    width: int | None = None,
                    height: int | None = None) -> QPixmap:
        """Load a QPixmap from assets directory.

        Args:
            name: Asset filename or base name (.png auto-appended).
            width: Optional scale width.
            height: Optional scale height.

        Returns:
            QPixmap (empty if file not found).
        """
        p = _resolve(name)
        if not p.exists():
            log.warning("Asset not found: %s", name)
            return QPixmap()

        # Use forward slashes — Qt handles them on all platforms,
        # avoids Windows backslash issues with sandboxed Python paths.
        pixmap = QPixmap(p.as_posix())
        if width and height:
            pixmap = pixmap.scaled(
                width, height,
                Qt.AspectRatioMode.IgnoreAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            )
        return pixmap

    @classmethod
    def get_preview_for_resolution(cls, width: int, height: int) -> str:
        """Get preview frame asset name for a resolution."""
        name = f'P预览{width}X{height}.png'
        if cls.exists(name):
            return name
        name_alt = f'P预览{width}x{height}.png'
        if cls.exists(name_alt):
            return name_alt
        return cls.PREVIEW_320X320

    @classmethod
    def get_localized(cls, base_name: str, lang: str = 'en') -> str:
        """Get localized asset name with language suffix.

        Args:
            base_name: Base asset name (e.g., 'P0CZTV' or 'P0CZTV.png').
            lang: ISO 639-1 language code ('en', 'de', 'fr', 'zh', etc.).

        Returns:
            Localized asset name if exists, else base name.
        """
        if lang == 'zh':
            # Simplified Chinese is the base asset (no suffix)
            return base_name

        # Map ISO code to legacy C# suffix for asset filenames
        from trcc.core.models import ISO_TO_LEGACY
        suffix = ISO_TO_LEGACY.get(lang, lang)

        # Split extension if present, insert lang suffix before it
        if '.' in base_name:
            stem, ext = base_name.rsplit('.', 1)
            localized = f"{stem}{suffix}.{ext}"
        else:
            localized = f"{base_name}{suffix}"

        if cls.exists(localized):
            return localized
        return base_name
