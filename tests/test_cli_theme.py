"""Tests for trcc.cli._theme — theme discovery, loading, save, export, import."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

from trcc.cli._theme import (
    export_theme,
    import_theme,
    list_themes,
    load_theme,
    save_theme,
)

# ===========================================================================
# Shared helpers
# ===========================================================================

def _make_local_theme(
    name: str = "MyTheme",
    is_animated: bool = False,
    animation_path=None,
    bg_exists: bool = True,
    is_user: bool = False,
    theme_path: str = "/themes/MyTheme",
) -> MagicMock:
    """Build a mock ThemeInfo for a local theme."""
    t = MagicMock()
    t.name = name if not is_user else f"Custom_{name}"
    t.is_animated = is_animated
    t.animation_path = animation_path
    t.background_path = MagicMock()
    t.background_path.exists.return_value = bg_exists
    t.path = Path(theme_path)
    t.category = None
    return t


def _make_cloud_theme(name: str = "CloudTheme", category: str = "a") -> MagicMock:
    """Build a mock ThemeInfo for a cloud theme."""
    t = MagicMock()
    t.name = name
    t.category = category
    return t


def _make_theme_dir() -> MagicMock:
    """Mock settings.theme_dir with a valid path."""
    td = MagicMock()
    td.exists.return_value = True
    td.path = Path("/themes/320x320")
    return td


def _make_web_dir() -> MagicMock:
    """Mock settings.web_dir with a valid path."""
    wd = MagicMock()
    wd.exists.return_value = True
    return wd


def _make_mock_service(resolution=(320, 320)) -> MagicMock:
    """Mock DeviceService with a selected device."""
    dev = MagicMock()
    dev.resolution = resolution
    dev.path = "/dev/sg0"
    dev.device_index = 0
    dev.vid = 0x87CD
    dev.pid = 0x70DB

    svc = MagicMock()
    svc.selected = dev
    return svc


# ===========================================================================
# Shared patch targets
# All imports in _theme.py are local (inside function bodies), so we patch
# the canonical module locations rather than trcc.cli._theme.*
# ===========================================================================

_PATCH_SETTINGS = "trcc.conf.settings"
_PATCH_SETTINGS_CLS = "trcc.conf.Settings"
_PATCH_DATA_MANAGER = "trcc.adapters.infra.data_repository.DataManager"
_PATCH_THEME_SVC = "trcc.services.ThemeService"
_PATCH_IMAGE_SVC = "trcc.services.ImageService"
_PATCH_PIL_IMAGE = "PIL.Image"
_PATCH_GET_SERVICE = "trcc.cli._device._get_service"


# ===========================================================================
# TestListThemes
# ===========================================================================

class TestListThemes:
    """list_themes() — local and cloud theme discovery."""

    def _base_patches(self, td=None, wd=None, w=320, h=320):
        """Common patch context for list_themes."""
        settings_mock = MagicMock()
        settings_mock.width = w
        settings_mock.height = h
        settings_mock.theme_dir = td or _make_theme_dir()
        settings_mock.web_dir = wd or _make_web_dir()

        data_mgr = MagicMock()
        theme_svc = MagicMock()
        return settings_mock, data_mgr, theme_svc

    def test_local_themes_prints_count(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        theme_svc.discover_local.return_value = [
            _make_local_theme("Alpha"),
            _make_local_theme("Beta"),
        ]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = list_themes()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Local themes" in out
        assert "2" in out

    def test_local_themes_lists_names(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        theme_svc.discover_local.return_value = [
            _make_local_theme("Alpha"),
            _make_local_theme("Beta"),
        ]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes()
        out = capsys.readouterr().out
        assert "Alpha" in out
        assert "Beta" in out

    def test_local_animated_theme_shown_as_video(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        animated = _make_local_theme("VideoTheme", is_animated=True)
        theme_svc.discover_local.return_value = [animated]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes()
        out = capsys.readouterr().out
        assert "video" in out

    def test_local_static_theme_shown_as_static(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        static = _make_local_theme("StaticTheme", is_animated=False)
        theme_svc.discover_local.return_value = [static]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes()
        out = capsys.readouterr().out
        assert "static" in out

    def test_local_user_theme_shown_with_user_tag(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        user = _make_local_theme("MyTheme", is_user=True)
        theme_svc.discover_local.return_value = [user]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes()
        out = capsys.readouterr().out
        assert "[user]" in out

    def test_local_no_theme_dir_returns_0(self, capsys):
        settings_mock = MagicMock()
        settings_mock.width = 320
        settings_mock.height = 320
        settings_mock.theme_dir = None
        data_mgr = MagicMock()
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr):
            rc = list_themes()
        assert rc == 0
        assert "No local themes" in capsys.readouterr().out

    def test_local_theme_dir_not_exists_returns_0(self, capsys):
        settings_mock = MagicMock()
        settings_mock.width = 320
        settings_mock.height = 320
        td = MagicMock()
        td.exists.return_value = False
        settings_mock.theme_dir = td
        data_mgr = MagicMock()
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr):
            rc = list_themes()
        assert rc == 0
        assert "No local themes" in capsys.readouterr().out

    def test_zero_resolution_defaults_to_320x320(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches(w=0, h=0)
        theme_svc.discover_local.return_value = []
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes()
        data_mgr.ensure_all.assert_called_once_with(320, 320)

    def test_cloud_themes_prints_count(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        theme_svc.discover_cloud.return_value = [
            _make_cloud_theme("CloudA"),
            _make_cloud_theme("CloudB"),
        ]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = list_themes(cloud=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Cloud themes" in out
        assert "2" in out

    def test_cloud_themes_shows_category(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        theme_svc.discover_cloud.return_value = [
            _make_cloud_theme("CloudA", category="b"),
        ]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes(cloud=True)
        out = capsys.readouterr().out
        assert "[b]" in out

    def test_cloud_theme_no_category_no_bracket(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        t = _make_cloud_theme("CloudA")
        t.category = None
        theme_svc.discover_cloud.return_value = [t]
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes(cloud=True)
        out = capsys.readouterr().out
        assert "[" not in out

    def test_cloud_no_web_dir_returns_0(self, capsys):
        settings_mock = MagicMock()
        settings_mock.width = 320
        settings_mock.height = 320
        settings_mock.web_dir = None
        data_mgr = MagicMock()
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr):
            rc = list_themes(cloud=True)
        assert rc == 0
        assert "No cloud themes" in capsys.readouterr().out

    def test_cloud_web_dir_not_exists_returns_0(self, capsys):
        settings_mock = MagicMock()
        settings_mock.width = 320
        settings_mock.height = 320
        wd = MagicMock()
        wd.exists.return_value = False
        settings_mock.web_dir = wd
        data_mgr = MagicMock()
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr):
            rc = list_themes(cloud=True)
        assert rc == 0
        assert "No cloud themes" in capsys.readouterr().out

    def test_cloud_passes_category_to_service(self, capsys):
        settings_mock, data_mgr, theme_svc = self._base_patches()
        theme_svc.discover_cloud.return_value = []
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            list_themes(cloud=True, category="c")
        theme_svc.discover_cloud.assert_called_once()
        args = theme_svc.discover_cloud.call_args
        assert args[0][1] == "c" or args[1].get("category") == "c" or "c" in args[0]


# ===========================================================================
# TestLoadTheme
# ===========================================================================

class TestLoadTheme:
    """load_theme() — exact match, partial match, animated, no bg, no device."""

    def _patches(
        self,
        svc=None,
        themes=None,
        td=None,
        img=None,
        img_svc=None,
        settings_mock=None,
        settings_cls=None,
    ):
        """Return all patch targets as a dict of context managers."""
        if svc is None:
            svc = _make_mock_service()
        if themes is None:
            themes = [_make_local_theme()]
        if td is None:
            td = _make_theme_dir()
        if img is None:
            img = MagicMock()
        if img_svc is None:
            img_svc = MagicMock()
            img_svc.open_and_resize.return_value = img
            img_svc.resize.return_value = img
            img_svc.apply_brightness.return_value = img
            img_svc.apply_rotation.return_value = img
            img_svc.to_ansi.return_value = "[ANSI]"
        if settings_mock is None:
            settings_mock = MagicMock()
            settings_mock.theme_dir = td
        if settings_cls is None:
            settings_cls = MagicMock()
            settings_cls.device_config_key.return_value = "key"
            settings_cls.get_device_config.return_value = {
                "brightness_level": 3,
                "rotation": 0,
            }

        return svc, themes, img, img_svc, settings_mock, settings_cls

    def test_exact_match_returns_0(self, capsys):
        svc, themes, img, img_svc, sm, sc = self._patches()
        themes[0].name = "ExactTheme"
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = themes
        pil_mock = MagicMock()
        pil_mock.open.return_value.__enter__ = lambda s: s
        pil_mock.open.return_value.convert.return_value = img
        pil_mock.open.return_value = MagicMock(convert=lambda m: img)
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            rc = load_theme("ExactTheme")
        assert rc == 0
        out = capsys.readouterr().out
        assert "ExactTheme" in out

    def test_partial_match_found(self, capsys):
        t = _make_local_theme("SuperTheme")
        svc, _, img, img_svc, sm, sc = self._patches(themes=[t])
        sm.theme_dir = _make_theme_dir()
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = [t]
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=lambda m: img)
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            rc = load_theme("super")  # partial, case-insensitive
        assert rc == 0

    def test_theme_not_found_returns_1(self, capsys):
        svc = _make_mock_service()
        sm = MagicMock()
        sm.theme_dir = _make_theme_dir()
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = [_make_local_theme("Alpha")]
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = load_theme("Nonexistent")
        assert rc == 1
        out = capsys.readouterr().out
        assert "not found" in out.lower()

    def test_animated_theme_redirects_to_video(self, capsys):
        svc = _make_mock_service()
        animated = _make_local_theme("AnimTheme", is_animated=True,
                                     animation_path="/path/to/vid.gif")
        sm = MagicMock()
        sm.theme_dir = _make_theme_dir()
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = [animated]
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = load_theme("AnimTheme")
        assert rc == 0
        out = capsys.readouterr().out
        assert "animated" in out.lower() or "video" in out.lower()

    def test_no_background_path_returns_1(self, capsys):
        svc = _make_mock_service()
        t = _make_local_theme("NoBg", bg_exists=False)
        t.background_path = None  # no bg at all
        sm = MagicMock()
        sm.theme_dir = _make_theme_dir()
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = [t]
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = load_theme("NoBg")
        assert rc == 1

    def test_background_does_not_exist_returns_1(self, capsys):
        svc = _make_mock_service()
        t = _make_local_theme("NoBg", bg_exists=False)
        sm = MagicMock()
        sm.theme_dir = _make_theme_dir()
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = [t]
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = load_theme("NoBg")
        assert rc == 1
        assert "no background" in capsys.readouterr().out.lower()

    def test_no_device_returns_1(self, capsys):
        svc = MagicMock()
        svc.selected = None
        with patch(_PATCH_GET_SERVICE, return_value=svc):
            rc = load_theme("AnyTheme")
        assert rc == 1
        assert "No device" in capsys.readouterr().out

    def test_no_theme_dir_returns_1(self, capsys):
        svc = _make_mock_service()
        sm = MagicMock()
        sm.theme_dir = None
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS), \
             patch(_PATCH_DATA_MANAGER):
            rc = load_theme("AnyTheme")
        assert rc == 1
        assert "No themes" in capsys.readouterr().out

    def test_preview_calls_to_ansi(self, capsys):
        svc, themes, img, img_svc, sm, sc = self._patches()
        themes[0].name = "PreviewTheme"
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = themes
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=lambda m: img)
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            rc = load_theme("PreviewTheme", preview=True)
        assert rc == 0
        img_svc.to_ansi.assert_called_once()
        assert "[ANSI]" in capsys.readouterr().out

    def test_no_preview_skips_to_ansi(self, capsys):
        svc, themes, img, img_svc, sm, sc = self._patches()
        themes[0].name = "Theme"
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = themes
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=lambda m: img)
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            load_theme("Theme", preview=False)
        img_svc.to_ansi.assert_not_called()

    def test_brightness_level_1_uses_25(self):
        svc, themes, img, img_svc, sm, sc = self._patches()
        sc.get_device_config.return_value = {"brightness_level": 1, "rotation": 0}
        themes[0].name = "T"
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = themes
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=lambda m: img)
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            load_theme("T")
        img_svc.apply_brightness.assert_called_once_with(img, 25)

    def test_saves_theme_path_to_settings(self):
        svc, themes, img, img_svc, sm, sc = self._patches()
        themes[0].name = "T"
        themes[0].path = Path("/themes/T")
        theme_svc = MagicMock()
        theme_svc.discover_local.return_value = themes
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=lambda m: img)
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_DATA_MANAGER), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            load_theme("T")
        sc.save_device_setting.assert_called_once()
        call_args = sc.save_device_setting.call_args[0]
        assert "theme_path" in call_args
        assert "/themes/T" in call_args


# ===========================================================================
# TestSaveTheme
# ===========================================================================

class TestSaveTheme:
    """save_theme() — success, no device, no current theme, video path."""

    def _base_setup(self, theme_path="/themes/LastTheme"):
        svc = _make_mock_service()
        sc = MagicMock()
        sc.device_config_key.return_value = "key"
        sc.get_device_config.return_value = {"theme_path": theme_path}

        td = MagicMock()
        td.bg = MagicMock()
        td.bg.exists.return_value = True

        img = MagicMock()
        img.convert.return_value = img
        img.resize.return_value = img

        return svc, sc, td, img

    def test_success_returns_0(self, capsys):
        svc, sc, td, img = self._base_setup()
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=MagicMock(return_value=img))
        img.resize.return_value = img

        theme_svc = MagicMock()
        theme_svc.save.return_value = (True, "Saved: MyTheme")

        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch("trcc.core.models.ThemeDir", return_value=td), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            rc = save_theme("MyTheme")
        assert rc == 0
        assert "Saved" in capsys.readouterr().out

    def test_no_device_returns_1(self, capsys):
        svc = MagicMock()
        svc.selected = None
        with patch(_PATCH_GET_SERVICE, return_value=svc):
            rc = save_theme("MyTheme")
        assert rc == 1
        assert "No device" in capsys.readouterr().out

    def test_no_current_theme_returns_1(self, capsys):
        svc = _make_mock_service()
        sc = MagicMock()
        sc.device_config_key.return_value = "key"
        sc.get_device_config.return_value = {}  # no theme_path

        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"):
            rc = save_theme("MyTheme")
        assert rc == 1
        assert "No current theme" in capsys.readouterr().out

    def test_bg_file_not_exists_returns_1(self, capsys):
        svc, sc, td, img = self._base_setup()
        td.bg.exists.return_value = False

        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch("trcc.core.models.ThemeDir", return_value=td), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"):
            rc = save_theme("MyTheme")
        assert rc == 1
        assert "No current theme" in capsys.readouterr().out

    def test_save_fails_returns_1(self, capsys):
        svc, sc, td, img = self._base_setup()
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=MagicMock(return_value=img))
        img.resize.return_value = img

        theme_svc = MagicMock()
        theme_svc.save.return_value = (False, "Save failed: disk full")

        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch("trcc.core.models.ThemeDir", return_value=td), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            rc = save_theme("MyTheme")
        assert rc == 1

    def test_video_path_passed_to_service(self, capsys):
        svc, sc, td, img = self._base_setup()
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=MagicMock(return_value=img))
        img.resize.return_value = img

        theme_svc = MagicMock()
        theme_svc.save.return_value = (True, "Saved")

        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch("trcc.core.models.ThemeDir", return_value=td), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            save_theme("MyTheme", video="/path/to/video.gif")

        call_kwargs = theme_svc.save.call_args[1]
        assert call_kwargs.get("video_path") == Path("/path/to/video.gif")

    def test_no_video_path_is_none(self, capsys):
        svc, sc, td, img = self._base_setup()
        pil_mock = MagicMock()
        pil_mock.open.return_value = MagicMock(convert=MagicMock(return_value=img))
        img.resize.return_value = img

        theme_svc = MagicMock()
        theme_svc.save.return_value = (True, "Saved")

        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch("trcc.core.models.ThemeDir", return_value=td), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"), \
             patch(_PATCH_PIL_IMAGE, pil_mock):
            save_theme("MyTheme")

        call_kwargs = theme_svc.save.call_args[1]
        assert call_kwargs.get("video_path") is None


# ===========================================================================
# TestExportTheme
# ===========================================================================

class TestExportTheme:
    """export_theme() — success, partial match, not found, no themes dir."""

    def _base_patches(self, themes=None, td=None, w=320, h=320):
        settings_mock = MagicMock()
        settings_mock.width = w
        settings_mock.height = h
        settings_mock.theme_dir = td or _make_theme_dir()
        data_mgr = MagicMock()
        theme_svc = MagicMock()
        if themes is not None:
            theme_svc.discover_local.return_value = themes
        return settings_mock, data_mgr, theme_svc

    def test_exact_match_success(self, capsys, tmp_path):
        t = _make_local_theme("MyTheme", theme_path="/themes/MyTheme")
        sm, dm, ts = self._base_patches(themes=[t])
        ts.export_tr.return_value = (True, "Exported to /out/MyTheme.tr")
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm), \
             patch(_PATCH_THEME_SVC, ts):
            rc = export_theme("MyTheme", str(tmp_path / "MyTheme.tr"))
        assert rc == 0
        assert "Exported" in capsys.readouterr().out

    def test_partial_match_success(self, capsys, tmp_path):
        t = _make_local_theme("CoolThemeXL", theme_path="/themes/CoolThemeXL")
        sm, dm, ts = self._base_patches(themes=[t])
        ts.export_tr.return_value = (True, "Exported")
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm), \
             patch(_PATCH_THEME_SVC, ts):
            rc = export_theme("cool", str(tmp_path / "out.tr"))
        assert rc == 0

    def test_not_found_returns_1(self, capsys, tmp_path):
        sm, dm, ts = self._base_patches(themes=[_make_local_theme("OtherTheme")])
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm), \
             patch(_PATCH_THEME_SVC, ts):
            rc = export_theme("Nonexistent", str(tmp_path / "out.tr"))
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_theme_with_no_path_returns_1(self, capsys, tmp_path):
        t = _make_local_theme("NullPath")
        t.path = None  # no path attribute
        sm, dm, ts = self._base_patches(themes=[t])
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm), \
             patch(_PATCH_THEME_SVC, ts):
            rc = export_theme("NullPath", str(tmp_path / "out.tr"))
        assert rc == 1

    def test_no_themes_dir_returns_1(self, capsys, tmp_path):
        sm = MagicMock()
        sm.width = 320
        sm.height = 320
        sm.theme_dir = None
        dm = MagicMock()
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm):
            rc = export_theme("AnyTheme", str(tmp_path / "out.tr"))
        assert rc == 1
        assert "No themes" in capsys.readouterr().out

    def test_themes_dir_not_exists_returns_1(self, capsys, tmp_path):
        sm = MagicMock()
        sm.width = 320
        sm.height = 320
        td = MagicMock()
        td.exists.return_value = False
        sm.theme_dir = td
        dm = MagicMock()
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm):
            rc = export_theme("AnyTheme", str(tmp_path / "out.tr"))
        assert rc == 1

    def test_export_fails_returns_1(self, capsys, tmp_path):
        t = _make_local_theme("MyTheme")
        sm, dm, ts = self._base_patches(themes=[t])
        ts.export_tr.return_value = (False, "Export failed: permission denied")
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm), \
             patch(_PATCH_THEME_SVC, ts):
            rc = export_theme("MyTheme", str(tmp_path / "out.tr"))
        assert rc == 1
        assert "Export failed" in capsys.readouterr().out

    def test_zero_resolution_defaults_to_320x320(self):
        sm = MagicMock()
        sm.width = 0
        sm.height = 0
        sm.theme_dir = _make_theme_dir()
        dm = MagicMock()
        ts = MagicMock()
        ts.discover_local.return_value = []
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm), \
             patch(_PATCH_THEME_SVC, ts):
            export_theme("AnyTheme", "/out.tr")
        dm.ensure_all.assert_called_once_with(320, 320)


# ===========================================================================
# TestImportTheme
# ===========================================================================

class TestImportTheme:
    """import_theme() — success (ThemeInfo result), success (str result), failure, no device."""

    def test_success_with_theme_info_result(self, capsys, tmp_path):
        svc = _make_mock_service()
        theme_info = MagicMock()
        theme_info.name = "ImportedTheme"
        theme_svc = MagicMock()
        theme_svc.import_tr.return_value = (True, theme_info)
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"):
            rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 0
        assert "ImportedTheme" in capsys.readouterr().out

    def test_success_with_string_result(self, capsys, tmp_path):
        svc = _make_mock_service()
        theme_svc = MagicMock()
        theme_svc.import_tr.return_value = (True, "Import successful")
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"):
            rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 0
        assert "Import successful" in capsys.readouterr().out

    def test_failure_returns_1(self, capsys, tmp_path):
        svc = _make_mock_service()
        theme_svc = MagicMock()
        theme_svc.import_tr.return_value = (False, "Invalid .tr file")
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"):
            rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 1
        assert "Invalid" in capsys.readouterr().out

    def test_no_device_returns_1(self, capsys, tmp_path):
        svc = MagicMock()
        svc.selected = None
        with patch(_PATCH_GET_SERVICE, return_value=svc):
            rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 1
        assert "No device" in capsys.readouterr().out

    def test_passes_resolution_to_import_tr(self, tmp_path):
        svc = _make_mock_service(resolution=(640, 480))
        theme_svc = MagicMock()
        theme_svc.import_tr.return_value = (True, "ok")
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"):
            import_theme(str(tmp_path / "theme.tr"))
        call_args = theme_svc.import_tr.call_args[0]
        assert (640, 480) in call_args

    def test_passes_correct_file_path(self, tmp_path):
        svc = _make_mock_service()
        theme_svc = MagicMock()
        theme_svc.import_tr.return_value = (True, "ok")
        file_path = str(tmp_path / "my_theme.tr")
        with patch(_PATCH_GET_SERVICE, return_value=svc), \
             patch(_PATCH_THEME_SVC, theme_svc), \
             patch("trcc.adapters.infra.data_repository.USER_DATA_DIR", "/data"):
            import_theme(file_path)
        call_args = theme_svc.import_tr.call_args[0]
        assert Path(file_path) in call_args
