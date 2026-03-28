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
        theme_svc.return_value = theme_svc
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

    def test_zero_resolution_errors(self, capsys):
        """When no device resolution is saved (0x0), list_themes errors — no fallback."""
        settings_mock, data_mgr, theme_svc = self._base_patches(w=0, h=0)
        with patch(_PATCH_SETTINGS, settings_mock), \
             patch(_PATCH_DATA_MANAGER, data_mgr), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = list_themes()
        assert rc == 1
        assert "connect" in capsys.readouterr().out.lower()

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
    """load_theme() — dispatches LoadThemeByNameCommand through TrccApp.lcd_bus.

    The autouse _mock_builder fixture already wires TrccApp._instance with a
    working mock bus (has_lcd=True, os_bus succeeds), so _connect_or_fail()
    passes without any additional patching.
    """

    def test_no_device_returns_1(self, _mock_builder, capsys):
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        mock_app = TrccApp._instance
        mock_app.has_lcd = False
        mock_app.os_bus.dispatch.return_value = CommandResult.fail("No LCD device found.")
        rc = load_theme(MagicMock(), "AnyTheme")
        assert rc == 1

    def test_dispatch_failure_returns_1(self, _mock_builder, capsys):
        """Bus dispatch returns success=False → returns 1, prints error."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        TrccApp._instance.lcd_bus.dispatch.return_value = CommandResult.fail("Theme not found")
        rc = load_theme(MagicMock(), "Missing")
        assert rc == 1
        assert "Theme not found" in capsys.readouterr().out

    def test_static_theme_returns_0(self, _mock_builder, capsys):
        """Dispatch returns success+image (static) → returns 0, prints name + device path."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        img = MagicMock()
        mock_app = TrccApp._instance
        mock_app.lcd_bus.dispatch.return_value = CommandResult.ok(image=img, is_animated=False)
        mock_app.lcd_device.device_path = "/dev/sg0"
        rc = load_theme(MagicMock(), "MyTheme")
        assert rc == 0
        out = capsys.readouterr().out
        assert "MyTheme" in out
        assert "/dev/sg0" in out

    def test_no_image_returns_1(self, _mock_builder, capsys):
        """success=True but image=None (not animated) → returns 1, prints error."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        TrccApp._instance.lcd_bus.dispatch.return_value = CommandResult.ok(
            image=None, is_animated=False)
        rc = load_theme(MagicMock(), "NoImage")
        assert rc == 1
        assert "no background" in capsys.readouterr().out.lower()

    def test_preview_calls_to_ansi(self, _mock_builder, capsys):
        """preview=True → ImageService.to_ansi called and its output printed."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        img = MagicMock()
        TrccApp._instance.lcd_bus.dispatch.return_value = CommandResult.ok(
            image=img, is_animated=False)
        img_svc = MagicMock()
        img_svc.to_ansi.return_value = "[ANSI]"
        with patch(_PATCH_IMAGE_SVC, img_svc):
            rc = load_theme(MagicMock(), "PTheme", preview=True)
        assert rc == 0
        img_svc.to_ansi.assert_called_once_with(img)
        assert "[ANSI]" in capsys.readouterr().out

    def test_no_preview_skips_to_ansi(self, _mock_builder):
        """preview=False → ImageService.to_ansi not called."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        img = MagicMock()
        TrccApp._instance.lcd_bus.dispatch.return_value = CommandResult.ok(
            image=img, is_animated=False)
        img_svc = MagicMock()
        with patch(_PATCH_IMAGE_SVC, img_svc):
            load_theme(MagicMock(), "Theme", preview=False)
        img_svc.to_ansi.assert_not_called()

    def test_animated_dispatches_play_video_loop(self, _mock_builder, capsys):
        """Animated theme → dispatches PlayVideoLoopCommand on the same bus."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        from trcc.core.commands.lcd import PlayVideoLoopCommand
        theme_path = "/themes/AnimTheme/anim.gif"
        mock_app = TrccApp._instance
        mock_app.lcd_device.device_path = "/dev/sg0"
        mock_app.lcd_bus.dispatch.side_effect = [
            CommandResult.ok(image=None, is_animated=True, theme_path=theme_path),
            CommandResult.ok(message="Done"),
        ]
        rc = load_theme(MagicMock(), "AnimTheme")
        assert rc == 0
        assert mock_app.lcd_bus.dispatch.call_count == 2
        cmd = mock_app.lcd_bus.dispatch.call_args_list[1][0][0]
        assert isinstance(cmd, PlayVideoLoopCommand)
        assert cmd.video_path == theme_path
        assert "Done" in capsys.readouterr().out

    def test_keyboard_interrupt_during_video(self, _mock_builder, capsys):
        """KeyboardInterrupt during PlayVideoLoopCommand → returns 0, prints Stopped."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        theme_path = "/themes/AnimTheme/anim.gif"
        mock_app = TrccApp._instance
        mock_app.lcd_device.device_path = "/dev/sg0"
        mock_app.lcd_bus.dispatch.side_effect = [
            CommandResult.ok(image=None, is_animated=True, theme_path=theme_path),
            KeyboardInterrupt(),
        ]
        rc = load_theme(MagicMock(), "AnimTheme")
        assert rc == 0
        assert "Stopped" in capsys.readouterr().out

    def test_dispatches_load_theme_by_name_command(self, _mock_builder):
        """load_theme passes the theme name through LoadThemeByNameCommand."""
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        from trcc.core.commands.lcd import LoadThemeByNameCommand
        img = MagicMock()
        TrccApp._instance.lcd_bus.dispatch.return_value = CommandResult.ok(
            image=img, is_animated=False)
        load_theme(MagicMock(), "TargetTheme")
        cmd = TrccApp._instance.lcd_bus.dispatch.call_args_list[0][0][0]
        assert isinstance(cmd, LoadThemeByNameCommand)
        assert cmd.name == "TargetTheme"


# ===========================================================================
# TestSaveTheme
# ===========================================================================

class TestSaveTheme:
    """save_theme() — success, no device, no background, video path.

    The autouse _mock_builder fixture wires TrccApp._instance so
    _connect_or_fail() passes by default (has_lcd=True).
    """

    _THEME_DIR = "trcc.core.models.ThemeDir"

    def _wire_lcd_size(self, resolution=(320, 320)) -> None:
        from trcc.core.app import TrccApp
        TrccApp._instance.lcd_device.lcd_size = resolution

    def test_no_device_returns_1(self, _mock_builder, capsys):
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        mock_app = TrccApp._instance
        mock_app.has_lcd = False
        mock_app.os_bus.dispatch.return_value = CommandResult.fail("No LCD device found.")
        rc = save_theme("MyTheme")
        assert rc == 1

    def test_success_returns_0(self, _mock_builder, capsys):
        self._wire_lcd_size()
        td = MagicMock()
        td.bg.exists.return_value = True
        img = MagicMock()
        img_svc = MagicMock()
        img_svc.open_and_resize.return_value = img
        sc = MagicMock()
        sc.get_device_config.return_value = {"theme_path": "/themes/LastTheme"}
        sm = MagicMock()
        sm.user_data_dir = "/data"
        theme_svc = MagicMock()
        theme_svc.save.return_value = (True, "Saved: MyTheme")

        with patch(self._THEME_DIR, return_value=td), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = save_theme("MyTheme")
        assert rc == 0
        assert "Saved" in capsys.readouterr().out

    def test_no_current_theme_returns_1(self, _mock_builder, capsys):
        self._wire_lcd_size()
        sc = MagicMock()
        sc.get_device_config.return_value = {}  # no theme_path
        with patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_SETTINGS):
            rc = save_theme("MyTheme")
        assert rc == 1
        assert "No background to save" in capsys.readouterr().out

    def test_bg_file_not_exists_returns_1(self, _mock_builder, capsys):
        self._wire_lcd_size()
        sc = MagicMock()
        sc.get_device_config.return_value = {"theme_path": "/themes/LastTheme"}
        td = MagicMock()
        td.bg.exists.return_value = False
        with patch(self._THEME_DIR, return_value=td), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_SETTINGS):
            rc = save_theme("MyTheme")
        assert rc == 1
        assert "No background to save" in capsys.readouterr().out

    def test_save_fails_returns_1(self, _mock_builder, capsys):
        self._wire_lcd_size()
        td = MagicMock()
        td.bg.exists.return_value = True
        img = MagicMock()
        img_svc = MagicMock()
        img_svc.open_and_resize.return_value = img
        sc = MagicMock()
        sc.get_device_config.return_value = {"theme_path": "/themes/LastTheme"}
        sm = MagicMock()
        sm.user_data_dir = "/data"
        theme_svc = MagicMock()
        theme_svc.save.return_value = (False, "Save failed: disk full")
        with patch(self._THEME_DIR, return_value=td), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_THEME_SVC, theme_svc):
            rc = save_theme("MyTheme")
        assert rc == 1

    def test_video_path_passed_to_service(self, _mock_builder, tmp_path):
        self._wire_lcd_size()
        video_file = tmp_path / "video.gif"
        video_file.write_bytes(b"GIF89a")
        img = MagicMock()
        img_svc = MagicMock()
        img_svc.open_and_resize.return_value = img
        sm = MagicMock()
        sm.user_data_dir = "/data"
        theme_svc = MagicMock()
        theme_svc.save.return_value = (True, "Saved")
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_THEME_SVC, theme_svc):
            save_theme("MyTheme", video=str(video_file))
        call_kwargs = theme_svc.save.call_args[1]
        assert call_kwargs.get("video_path") == video_file

    def test_no_video_path_is_none(self, _mock_builder):
        self._wire_lcd_size()
        td = MagicMock()
        td.bg.exists.return_value = True
        img = MagicMock()
        img_svc = MagicMock()
        img_svc.open_and_resize.return_value = img
        sc = MagicMock()
        sc.get_device_config.return_value = {"theme_path": "/themes/LastTheme"}
        sm = MagicMock()
        sm.user_data_dir = "/data"
        theme_svc = MagicMock()
        theme_svc.save.return_value = (True, "Saved")
        with patch(self._THEME_DIR, return_value=td), \
             patch(_PATCH_SETTINGS_CLS, sc), \
             patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_IMAGE_SVC, img_svc), \
             patch(_PATCH_THEME_SVC, theme_svc):
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
        theme_svc.return_value = theme_svc
        # ThemeService(export_theme_fn=...) returns the same mock instance
        theme_svc.return_value = theme_svc
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

    def test_zero_resolution_errors(self, capsys):
        """When no device resolution is saved (0x0), export_theme errors — no fallback."""
        sm = MagicMock()
        sm.width = 0
        sm.height = 0
        dm = MagicMock()
        ts = MagicMock()
        with patch(_PATCH_SETTINGS, sm), \
             patch(_PATCH_DATA_MANAGER, dm), \
             patch(_PATCH_THEME_SVC, ts):
            rc = export_theme("AnyTheme", "/out.tr")
        assert rc == 1
        assert "connect" in capsys.readouterr().out.lower()


# ===========================================================================
# TestImportTheme
# ===========================================================================

class TestImportTheme:
    """import_theme() — success, failure, no device, resolution and path forwarding.

    The autouse _mock_builder fixture wires TrccApp._instance so
    _connect_or_fail() passes by default (has_lcd=True).
    """

    def _wire_lcd_size(self, resolution=(320, 320)) -> None:
        from trcc.core.app import TrccApp
        TrccApp._instance.lcd_device.lcd_size = resolution

    def _mock_theme_svc(self, result) -> MagicMock:
        ts = MagicMock()
        ts.return_value = ts
        ts.import_tr.return_value = result
        return ts

    def test_no_device_returns_1(self, _mock_builder, capsys, tmp_path):
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        mock_app = TrccApp._instance
        mock_app.has_lcd = False
        mock_app.os_bus.dispatch.return_value = CommandResult.fail("No LCD device found.")
        rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 1

    def test_success_with_theme_info_result(self, _mock_builder, capsys, tmp_path):
        self._wire_lcd_size()
        theme_info = MagicMock()
        theme_info.name = "ImportedTheme"
        ts = self._mock_theme_svc((True, theme_info))
        with patch(_PATCH_SETTINGS), \
             patch(_PATCH_THEME_SVC, ts):
            rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 0
        assert "ImportedTheme" in capsys.readouterr().out

    def test_success_with_string_result(self, _mock_builder, capsys, tmp_path):
        self._wire_lcd_size()
        ts = self._mock_theme_svc((True, "Import successful"))
        with patch(_PATCH_SETTINGS), \
             patch(_PATCH_THEME_SVC, ts):
            rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 0
        assert "Import successful" in capsys.readouterr().out

    def test_failure_returns_1(self, _mock_builder, capsys, tmp_path):
        self._wire_lcd_size()
        ts = self._mock_theme_svc((False, "Invalid .tr file"))
        with patch(_PATCH_SETTINGS), \
             patch(_PATCH_THEME_SVC, ts):
            rc = import_theme(str(tmp_path / "theme.tr"))
        assert rc == 1
        assert "Invalid" in capsys.readouterr().out

    def test_passes_resolution_to_import_tr(self, _mock_builder, tmp_path):
        self._wire_lcd_size(resolution=(640, 480))
        ts = self._mock_theme_svc((True, "ok"))
        with patch(_PATCH_SETTINGS), \
             patch(_PATCH_THEME_SVC, ts):
            import_theme(str(tmp_path / "theme.tr"))
        call_args = ts.import_tr.call_args[0]
        assert (640, 480) in call_args

    def test_passes_correct_file_path(self, _mock_builder, tmp_path):
        self._wire_lcd_size()
        ts = self._mock_theme_svc((True, "ok"))
        file_path = str(tmp_path / "my_theme.tr")
        with patch(_PATCH_SETTINGS), \
             patch(_PATCH_THEME_SVC, ts):
            import_theme(file_path)
        call_args = ts.import_tr.call_args[0]
        assert Path(file_path) in call_args
