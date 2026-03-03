"""Tests for trcc.cli._theme — thin presentation wrappers over DisplayDispatcher.

_theme.py functions call dispatcher methods and format the result dicts.
Tests mock at the dispatcher level only — no PIL, no services, no adapters.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from trcc.cli._theme import (
    export_theme,
    import_theme,
    list_themes,
    load_theme,
    save_theme,
)

_PATCH_DISPATCHER = "trcc.cli._display.DisplayDispatcher"
_PATCH_CONNECT = "trcc.cli._display._connect_or_fail"
_PATCH_PRINT_RESULT = "trcc.cli._display._print_result"


# ===========================================================================
# Helpers
# ===========================================================================

def _mock_theme(name="MyTheme", is_animated=False, category=None):
    """Build a stub theme object with the attrs _theme.py reads."""
    t = MagicMock()
    t.name = name
    t.is_animated = is_animated
    t.category = category
    return t


def _make_dispatcher(list_result=None, load_result=None, save_result=None,
                     export_result=None, import_result=None):
    """Build a MagicMock dispatcher with preset return values."""
    d = MagicMock()
    if list_result is not None:
        d.list_themes.return_value = list_result
    if load_result is not None:
        d.load_theme_by_name.return_value = load_result
    if save_result is not None:
        d.save_custom_theme.return_value = save_result
    if export_result is not None:
        d.export_theme_by_name.return_value = export_result
    if import_result is not None:
        d.import_theme_file.return_value = import_result
    return d


# ===========================================================================
# TestListThemes
# ===========================================================================

class TestListThemes:
    """list_themes() — formats dispatcher.list_themes() result dict."""

    def test_local_themes_prints_count(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [_mock_theme("A"), _mock_theme("B")],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            rc = list_themes()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Local themes" in out
        assert "2" in out

    def test_local_themes_lists_names(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [_mock_theme("Alpha"), _mock_theme("Beta")],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes()
        out = capsys.readouterr().out
        assert "Alpha" in out
        assert "Beta" in out

    def test_animated_shown_as_video(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [_mock_theme("V", is_animated=True)],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes()
        assert "video" in capsys.readouterr().out

    def test_static_shown_as_static(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [_mock_theme("S", is_animated=False)],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes()
        assert "static" in capsys.readouterr().out

    def test_user_theme_shown_with_tag(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [_mock_theme("Custom_Mine")],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes()
        assert "[user]" in capsys.readouterr().out

    def test_no_local_themes_prints_message(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            rc = list_themes()
        assert rc == 0
        assert "No local themes" in capsys.readouterr().out

    def test_resolution_shown_in_output(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [_mock_theme("T")],
            "cloud": [],
            "resolution": [640, 480],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes()
        assert "640x480" in capsys.readouterr().out

    def test_cloud_themes_prints_count(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [],
            "cloud": [_mock_theme("C1", category="a"), _mock_theme("C2", category="b")],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            rc = list_themes(cloud=True)
        assert rc == 0
        out = capsys.readouterr().out
        assert "Cloud themes" in out
        assert "2" in out

    def test_cloud_theme_shows_category(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [],
            "cloud": [_mock_theme("C", category="b")],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes(cloud=True)
        assert "[b]" in capsys.readouterr().out

    def test_cloud_no_category_no_bracket(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [],
            "cloud": [_mock_theme("C", category=None)],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes(cloud=True)
        assert "[" not in capsys.readouterr().out

    def test_no_cloud_themes_prints_message(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            rc = list_themes(cloud=True)
        assert rc == 0
        assert "No cloud themes" in capsys.readouterr().out

    def test_passes_category_to_dispatcher(self):
        d = _make_dispatcher(list_result={
            "local": [],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes(category="mycat")
        d.list_themes.assert_called_once_with(category="mycat")

    def test_none_category_passes_empty_string(self):
        d = _make_dispatcher(list_result={
            "local": [],
            "cloud": [],
            "resolution": [320, 320],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes(category=None)
        d.list_themes.assert_called_once_with(category="")

    def test_default_resolution_when_missing(self, capsys):
        d = _make_dispatcher(list_result={
            "local": [_mock_theme("T")],
            "cloud": [],
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            list_themes()
        out = capsys.readouterr().out
        assert "320x320" in out


# ===========================================================================
# TestLoadTheme
# ===========================================================================

class TestLoadTheme:
    """load_theme() — routes through _connect_or_fail + load_theme_by_name."""

    def test_success_returns_0(self, capsys):
        d = _make_dispatcher(load_result={
            "success": True, "message": "Loaded 'T' → /dev/sg0",
            "image": MagicMock(), "theme_name": "T",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = load_theme("T")
        assert rc == 0
        assert "Loaded" in capsys.readouterr().out

    def test_connect_failure_returns_1(self, capsys):
        d = MagicMock()
        with patch(_PATCH_CONNECT, return_value=(d, 1)):
            rc = load_theme("T")
        assert rc == 1

    def test_theme_not_found_returns_1(self, capsys):
        d = _make_dispatcher(load_result={
            "success": False, "error": "Theme not found: Nope",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = load_theme("Nope")
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_animated_theme_prints_message(self, capsys):
        d = _make_dispatcher(load_result={
            "success": True, "is_animated": True,
            "message": "Theme 'V' is animated — use 'trcc video /path'",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = load_theme("V")
        assert rc == 0
        assert "animated" in capsys.readouterr().out.lower()

    def test_no_background_returns_1(self, capsys):
        d = _make_dispatcher(load_result={
            "success": False, "error": "Theme 'X' has no background image",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = load_theme("X")
        assert rc == 1
        assert "no background" in capsys.readouterr().out.lower()

    def test_calls_dispatcher_with_name(self):
        d = _make_dispatcher(load_result={"success": True, "message": "ok", "image": None})
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            load_theme("ExactName")
        d.load_theme_by_name.assert_called_once_with("ExactName")

    def test_preview_prints_ansi(self, capsys):
        img = MagicMock()
        d = _make_dispatcher(load_result={
            "success": True, "message": "Loaded T", "image": img,
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)), \
             patch("trcc.services.ImageService.to_ansi", return_value="[ANSI]"):
            rc = load_theme("T", preview=True)
        assert rc == 0
        assert "[ANSI]" in capsys.readouterr().out

    def test_no_preview_skips_ansi(self, capsys):
        d = _make_dispatcher(load_result={
            "success": True, "message": "Loaded T", "image": MagicMock(),
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            load_theme("T", preview=False)
        assert "[ANSI]" not in capsys.readouterr().out


# ===========================================================================
# TestSaveTheme
# ===========================================================================

class TestSaveTheme:
    """save_theme() — routes through _connect_or_fail + save_custom_theme."""

    def test_success_returns_0(self, capsys):
        d = _make_dispatcher(save_result={
            "success": True, "message": "Saved: MyTheme",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = save_theme("MyTheme")
        assert rc == 0
        assert "Saved" in capsys.readouterr().out

    def test_connect_failure_returns_1(self):
        d = MagicMock()
        with patch(_PATCH_CONNECT, return_value=(d, 1)):
            rc = save_theme("MyTheme")
        assert rc == 1

    def test_no_current_theme_returns_1(self, capsys):
        d = _make_dispatcher(save_result={
            "success": False, "error": "No current theme to save. Load a theme first.",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = save_theme("MyTheme")
        assert rc == 1
        assert "No current theme" in capsys.readouterr().out

    def test_save_fails_returns_1(self, capsys):
        d = _make_dispatcher(save_result={
            "success": False, "error": "Save failed: disk full",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = save_theme("MyTheme")
        assert rc == 1

    def test_passes_name_and_video(self):
        d = _make_dispatcher(save_result={"success": True, "message": "Saved"})
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            save_theme("MyTheme", video="/path/to/vid.gif")
        d.save_custom_theme.assert_called_once_with("MyTheme", video="/path/to/vid.gif")

    def test_no_video_passes_none(self):
        d = _make_dispatcher(save_result={"success": True, "message": "Saved"})
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            save_theme("MyTheme")
        d.save_custom_theme.assert_called_once_with("MyTheme", video=None)


# ===========================================================================
# TestExportTheme
# ===========================================================================

class TestExportTheme:
    """export_theme() — routes through DisplayDispatcher + export_theme_by_name."""

    def test_success_returns_0(self, capsys):
        d = _make_dispatcher(export_result={
            "success": True, "message": "Exported to /out/T.tr",
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            rc = export_theme("T", "/out/T.tr")
        assert rc == 0
        assert "Exported" in capsys.readouterr().out

    def test_not_found_returns_1(self, capsys):
        d = _make_dispatcher(export_result={
            "success": False, "error": "Theme not found: Nope",
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            rc = export_theme("Nope", "/out/x.tr")
        assert rc == 1
        assert "not found" in capsys.readouterr().out.lower()

    def test_export_fails_returns_1(self, capsys):
        d = _make_dispatcher(export_result={
            "success": False, "error": "Export failed: permission denied",
        })
        with patch(_PATCH_DISPATCHER, return_value=d):
            rc = export_theme("T", "/out/T.tr")
        assert rc == 1
        assert "Export failed" in capsys.readouterr().out

    def test_passes_name_and_path(self):
        d = _make_dispatcher(export_result={"success": True, "message": "ok"})
        with patch(_PATCH_DISPATCHER, return_value=d):
            export_theme("MyTheme", "/tmp/out.tr")
        d.export_theme_by_name.assert_called_once_with("MyTheme", "/tmp/out.tr")


# ===========================================================================
# TestImportTheme
# ===========================================================================

class TestImportTheme:
    """import_theme() — routes through _connect_or_fail + import_theme_file."""

    def test_success_returns_0(self, capsys):
        d = _make_dispatcher(import_result={
            "success": True, "message": "Imported: CoolTheme",
            "theme_name": "CoolTheme",
        })
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = import_theme("/tmp/theme.tr")
        assert rc == 0
        assert "Imported" in capsys.readouterr().out

    def test_connect_failure_returns_1(self):
        d = MagicMock()
        with patch(_PATCH_CONNECT, return_value=(d, 1)):
            rc = import_theme("/tmp/theme.tr")
        assert rc == 1

    def test_failure_returns_1(self, capsys):
        d = _make_dispatcher(import_result={
            "success": False, "error": "Invalid .tr file",
        })
        # _print_result reads "error" key on failure
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            rc = import_theme("/tmp/theme.tr")
        assert rc == 1

    def test_passes_file_path(self):
        d = _make_dispatcher(import_result={"success": True, "message": "ok"})
        with patch(_PATCH_CONNECT, return_value=(d, 0)):
            import_theme("/tmp/my_theme.tr")
        d.import_theme_file.assert_called_once_with("/tmp/my_theme.tr")
