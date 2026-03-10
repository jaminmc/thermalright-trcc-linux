"""Tests for trcc.conf — Settings singleton, config persistence, language detection.

Covers every function and branch in conf.py for 100% coverage.
Uses the tmp_config fixture from conftest.py for filesystem isolation.
"""
from __future__ import annotations

import json
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from trcc.conf import (
    Settings,
    _detect_language,
    _migrate_config,
    load_config,
    load_last_handshake,
    save_config,
    save_last_handshake,
)

# =========================================================================
# load_config / save_config
# =========================================================================


class TestLoadConfig:
    """load_config: reads JSON from CONFIG_PATH, returns {} on errors."""

    def test_returns_empty_dict_when_file_missing(self, tmp_config):
        assert load_config() == {}

    def test_reads_valid_json(self, tmp_config):
        save_config({"hello": "world"})
        assert load_config() == {"hello": "world"}

    def test_returns_empty_dict_on_corrupt_json(self, tmp_config):
        config_path = os.path.join(str(tmp_config / "trcc"), "config.json")
        with open(config_path, "w") as f:
            f.write("{broken json!!")
        assert load_config() == {}

    def test_returns_empty_dict_on_os_error(self, tmp_config, monkeypatch):
        """Simulate an OSError (e.g. permission denied)."""
        import builtins

        real_open = builtins.open

        def _bad_open(path, *a, **kw):
            from trcc.conf import CONFIG_PATH
            if str(path) == CONFIG_PATH:
                raise OSError("permission denied")
            return real_open(path, *a, **kw)

        monkeypatch.setattr(builtins, "open", _bad_open)
        assert load_config() == {}


class TestSaveConfig:
    """save_config: writes JSON to CONFIG_PATH, creates dirs."""

    def test_creates_dir_and_writes_json(self, tmp_config):
        save_config({"key": "value"})
        assert load_config() == {"key": "value"}

    def test_overwrites_existing_config(self, tmp_config):
        save_config({"v": 1})
        save_config({"v": 2})
        assert load_config()["v"] == 2


# =========================================================================
# Handshake cache
# =========================================================================


class TestHandshakeCache:
    """save_last_handshake / load_last_handshake: handshake JSON cache."""

    def test_round_trip(self, tmp_config):
        data = {"pm": 50, "fbl": 72, "raw": [0xDA, 0xDB]}
        save_last_handshake(data)
        assert load_last_handshake() == data

    def test_load_returns_empty_when_missing(self, tmp_config):
        assert load_last_handshake() == {}

    def test_load_returns_empty_on_corrupt_json(self, tmp_config):
        from trcc.conf import _HANDSHAKE_CACHE_PATH
        with open(_HANDSHAKE_CACHE_PATH, "w") as f:
            f.write("not json{{{")
        assert load_last_handshake() == {}

    def test_load_returns_empty_on_os_error(self, tmp_config, monkeypatch):
        import builtins

        real_open = builtins.open

        def _bad_open(path, *a, **kw):
            from trcc.conf import _HANDSHAKE_CACHE_PATH
            if str(path) == _HANDSHAKE_CACHE_PATH:
                raise OSError("disk error")
            return real_open(path, *a, **kw)

        monkeypatch.setattr(builtins, "open", _bad_open)
        assert load_last_handshake() == {}


# =========================================================================
# _migrate_config
# =========================================================================


class TestMigrateConfig:
    """_migrate_config: clears device state on version change."""

    def test_no_op_when_version_matches(self, tmp_config):
        from trcc.__version__ import __version__
        save_config({"config_version": __version__, "devices": {"0:1234_5678": {}}})
        _migrate_config()
        cfg = load_config()
        assert cfg["devices"] == {"0:1234_5678": {}}

    def test_first_run_sets_version_no_clear(self, tmp_config):
        """No saved_version (fresh install) — just sets config_version."""
        from trcc.__version__ import __version__
        _migrate_config()
        cfg = load_config()
        assert cfg["config_version"] == __version__

    def test_clears_device_state_on_version_mismatch(self, tmp_config):
        from trcc.__version__ import __version__
        save_config({
            "config_version": "0.0.1",
            "devices": {"0:1234_5678": {"theme": "dark"}},
            "resolution": [480, 480],
            "selected_device": "/dev/sg0",
            "installed_resolutions": {"320320": True},
            "temp_unit": 1,
            "lang": "d",
        })
        _migrate_config()
        cfg = load_config()
        # Device-derived keys cleared
        assert "devices" not in cfg
        assert "resolution" not in cfg
        assert "selected_device" not in cfg
        assert "installed_resolutions" not in cfg
        # User prefs preserved
        assert cfg["temp_unit"] == 1
        assert cfg["lang"] == "d"
        assert cfg["config_version"] == __version__

    def test_deletes_led_probe_cache_on_version_mismatch(self, tmp_config):
        from trcc.conf import CONFIG_DIR
        probe_cache = os.path.join(CONFIG_DIR, "led_probe_cache.json")
        with open(probe_cache, "w") as f:
            json.dump({"stale": True}, f)
        save_config({"config_version": "0.0.1"})
        _migrate_config()
        assert not os.path.exists(probe_cache)

    def test_handles_led_probe_cache_delete_failure(self, tmp_config, monkeypatch):
        """OSError on probe cache delete is logged, not raised."""
        from trcc.conf import CONFIG_DIR
        probe_cache = os.path.join(CONFIG_DIR, "led_probe_cache.json")
        with open(probe_cache, "w") as f:
            json.dump({"stale": True}, f)
        save_config({"config_version": "0.0.1"})

        real_remove = os.remove
        def _fail_remove(path):
            if "led_probe_cache" in str(path):
                raise OSError("permission denied")
            return real_remove(path)

        monkeypatch.setattr(os, "remove", _fail_remove)
        # Should not raise
        _migrate_config()
        # Cache file still exists since remove failed
        assert os.path.exists(probe_cache)


# =========================================================================
# _detect_language
# =========================================================================


class TestDetectLanguage:
    """_detect_language: maps system locale to C# asset suffix."""

    def test_exact_locale_match(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("zh_CN", "UTF-8"))
        assert _detect_language() == ""

    def test_exact_locale_en(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("en", "UTF-8"))
        assert _detect_language() == "en"

    def test_prefix_match_de_DE(self, monkeypatch):
        """de_DE is not in LOCALE_TO_LANG, but prefix 'de' is."""
        monkeypatch.setattr("locale.getlocale", lambda: ("de_DE", "UTF-8"))
        assert _detect_language() == "d"

    def test_prefix_match_fr(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("fr_FR", "UTF-8"))
        assert _detect_language() == "f"

    def test_prefix_match_ru(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("ru_RU", "UTF-8"))
        assert _detect_language() == "e"

    def test_prefix_match_ja(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("ja_JP", "UTF-8"))
        assert _detect_language() == "r"

    def test_prefix_match_es(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("es_ES", "UTF-8"))
        assert _detect_language() == "x"

    def test_prefix_match_pt(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("pt_BR", "UTF-8"))
        assert _detect_language() == "p"

    def test_zh_TW_traditional_chinese(self, monkeypatch):
        monkeypatch.setattr("locale.getlocale", lambda: ("zh_TW", "UTF-8"))
        assert _detect_language() == "tc"

    def test_falls_back_to_env_LANG(self, monkeypatch):
        """locale.getlocale returns (None, None) — fall back to $LANG."""
        monkeypatch.setattr("locale.getlocale", lambda: (None, None))
        monkeypatch.setenv("LANG", "de.UTF-8")
        assert _detect_language() == "d"

    def test_falls_back_to_en_when_no_locale(self, monkeypatch):
        """No locale, no $LANG — defaults to 'en'."""
        monkeypatch.setattr("locale.getlocale", lambda: (None, None))
        monkeypatch.delenv("LANG", raising=False)
        assert _detect_language() == "en"

    def test_korean_locale_returns_h(self, monkeypatch):
        """Korean locale returns 'h' suffix."""
        monkeypatch.setattr("locale.getlocale", lambda: ("ko_KR", "UTF-8"))
        assert _detect_language() == "h"

    def test_unknown_locale_returns_en(self, monkeypatch):
        """Unrecognized locale with no prefix match returns 'en'."""
        monkeypatch.setattr("locale.getlocale", lambda: ("sw_KE", "UTF-8"))
        assert _detect_language() == "en"

    def test_exception_in_getlocale_returns_en(self, monkeypatch):
        """locale.getlocale() raises — catch and default to 'en'."""
        monkeypatch.setattr("locale.getlocale", lambda: (_ for _ in ()).throw(ValueError("bad")))
        assert _detect_language() == "en"


# =========================================================================
# Settings — persistence helpers (static methods)
# =========================================================================


class TestSettingsPersistence:
    """Static persistence methods on Settings class."""

    def test_get_saved_resolution_default(self, tmp_config):
        assert Settings._get_saved_resolution() == (320, 320)

    def test_save_and_get_resolution(self, tmp_config):
        Settings._save_resolution(480, 480)
        assert Settings._get_saved_resolution() == (480, 480)

    def test_get_saved_resolution_invalid_type(self, tmp_config):
        """Non-list resolution falls back to (320, 320)."""
        save_config({"resolution": "bad"})
        assert Settings._get_saved_resolution() == (320, 320)

    def test_get_saved_resolution_wrong_length(self, tmp_config):
        """List with != 2 elements falls back to (320, 320)."""
        save_config({"resolution": [320]})
        assert Settings._get_saved_resolution() == (320, 320)

    def test_get_saved_temp_unit_default(self, tmp_config):
        assert Settings._get_saved_temp_unit() == 0

    def test_save_and_get_temp_unit(self, tmp_config):
        Settings._save_temp_unit(1)
        assert Settings._get_saved_temp_unit() == 1

    def test_get_saved_hdd_enabled_default(self, tmp_config):
        assert Settings._get_saved_hdd_enabled() is True

    def test_save_and_get_hdd_enabled(self, tmp_config):
        Settings._save_hdd_enabled(False)
        assert Settings._get_saved_hdd_enabled() is False


# =========================================================================
# Settings — device config, format prefs, selected device
# =========================================================================


class TestSettingsDeviceConfig:
    """Device config, selected device, and format prefs."""

    def test_device_config_key(self):
        assert Settings.device_config_key(0, 0x87CD, 0x70DB) == "0:87cd_70db"
        assert Settings.device_config_key(1, 0x0416, 0x5302) == "1:0416_5302"

    def test_get_device_config_empty(self, tmp_config):
        assert Settings.get_device_config("0:87cd_70db") == {}

    def test_save_and_get_device_setting(self, tmp_config):
        key = "0:87cd_70db"
        Settings.save_device_setting(key, "theme", "dark")
        Settings.save_device_setting(key, "rotation", 90)
        cfg = Settings.get_device_config(key)
        assert cfg == {"theme": "dark", "rotation": 90}

    def test_get_selected_device_none(self, tmp_config):
        assert Settings.get_selected_device() is None

    def test_save_and_get_selected_device(self, tmp_config):
        Settings.save_selected_device("/dev/sg0")
        assert Settings.get_selected_device() == "/dev/sg0"

    def test_get_format_prefs_empty(self, tmp_config):
        assert Settings.get_format_prefs() == {}

    def test_save_and_get_format_pref(self, tmp_config):
        Settings.save_format_pref("time_format", 1)
        Settings.save_format_pref("date_format", 2)
        prefs = Settings.get_format_prefs()
        assert prefs == {"time_format": 1, "date_format": 2}

    def test_clear_installed_resolutions(self, tmp_config):
        save_config({"installed_resolutions": {"320320": True}})
        Settings.clear_installed_resolutions()
        assert "installed_resolutions" not in load_config()

    def test_clear_installed_resolutions_no_key(self, tmp_config):
        """No-op when key doesn't exist."""
        save_config({"other": 1})
        Settings.clear_installed_resolutions()
        assert load_config()["other"] == 1


# =========================================================================
# Settings.apply_format_prefs
# =========================================================================


class TestApplyFormatPrefs:
    """apply_format_prefs: applies saved format prefs to overlay config."""

    def test_no_prefs_returns_unchanged(self, tmp_config):
        overlay = {"e0": {"metric": "time", "time_format": 0}}
        result = Settings.apply_format_prefs(overlay)
        assert result["e0"]["time_format"] == 0

    def test_applies_time_format(self, tmp_config):
        Settings.save_format_pref("time_format", 1)
        overlay = {"e0": {"metric": "time", "time_format": 0}}
        result = Settings.apply_format_prefs(overlay)
        assert result["e0"]["time_format"] == 1

    def test_applies_date_format(self, tmp_config):
        Settings.save_format_pref("date_format", 2)
        overlay = {"e0": {"metric": "date", "date_format": 0}}
        result = Settings.apply_format_prefs(overlay)
        assert result["e0"]["date_format"] == 2

    def test_applies_temp_unit_to_all_entries_with_metric(self, tmp_config):
        Settings.save_format_pref("temp_unit", 1)
        overlay = {
            "e0": {"metric": "cpu_temp"},
            "e1": {"metric": "gpu_temp"},
        }
        result = Settings.apply_format_prefs(overlay)
        assert result["e0"]["temp_unit"] == 1
        assert result["e1"]["temp_unit"] == 1

    def test_skips_non_dict_entries(self, tmp_config):
        Settings.save_format_pref("time_format", 1)
        overlay = {"meta": "some_string", "e0": {"metric": "time", "time_format": 0}}
        result = Settings.apply_format_prefs(overlay)
        assert result["meta"] == "some_string"
        assert result["e0"]["time_format"] == 1

    def test_no_metric_key_no_temp_unit_applied(self, tmp_config):
        """Entries without 'metric' key don't get temp_unit."""
        Settings.save_format_pref("temp_unit", 1)
        overlay = {"e0": {"value": 42}}
        result = Settings.apply_format_prefs(overlay)
        assert "temp_unit" not in result["e0"]


# =========================================================================
# Settings.__init__ — instance construction
# =========================================================================


class TestSettingsInit:
    """Settings.__init__: loads config, resolves paths."""

    def test_init_loads_defaults(self, tmp_config):
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            s = Settings()
        assert s.resolution == (320, 320)
        assert s.temp_unit == 0
        assert s.hdd_enabled is True

    def test_init_loads_saved_state(self, tmp_config):
        save_config({
            "resolution": [480, 480],
            "temp_unit": 1,
            "hdd_enabled": False,
            "lang": "d",
        })
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            s = Settings()
        assert s.resolution == (480, 480)
        assert s.width == 480
        assert s.height == 480
        assert s.temp_unit == 1
        assert s.hdd_enabled is False
        assert s.lang == "d"

    def test_init_zero_resolution_skips_resolve(self, tmp_config):
        """If saved resolution is (0, 0), _resolve_paths is not called."""
        save_config({"resolution": [0, 0]})
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td:
            s = Settings()
        mock_td.assert_not_called()
        assert s.theme_dir is None
        assert s.web_dir is None
        assert s.masks_dir is None


# =========================================================================
# Settings — instance methods
# =========================================================================


class TestSettingsInstance:
    """Instance methods: set_resolution, set_temp_unit, set_hdd_enabled, lang."""

    @pytest.fixture
    def settings(self, tmp_config):
        """Create a Settings instance with mocked external dependencies."""
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            s = Settings()
        return s

    def test_set_resolution_updates_and_persists(self, settings, tmp_config):
        with patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web2"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks2"):
            mock_td.return_value = MagicMock()
            settings.set_resolution(480, 480)
        assert settings.resolution == (480, 480)
        assert Settings._get_saved_resolution() == (480, 480)

    def test_set_resolution_no_op_same_value(self, settings, tmp_config):
        """No change when setting the same resolution."""
        with patch("trcc.conf.ThemeDir.for_resolution") as mock_td:
            settings.set_resolution(320, 320)
        mock_td.assert_not_called()

    def test_set_resolution_no_persist(self, settings, tmp_config):
        """persist=False skips saving to config."""
        with patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            settings.set_resolution(640, 480, persist=False)
        assert settings.resolution == (640, 480)
        # Config still has default
        assert Settings._get_saved_resolution() == (320, 320)

    def test_set_temp_unit_updates_and_persists(self, settings, tmp_config):
        settings.set_temp_unit(1)
        assert settings.temp_unit == 1
        assert Settings._get_saved_temp_unit() == 1

    def test_set_hdd_enabled_updates_and_persists(self, settings, tmp_config):
        settings.set_hdd_enabled(False)
        assert settings.hdd_enabled is False
        assert Settings._get_saved_hdd_enabled() is False

    def test_lang_setter_persists(self, settings, tmp_config):
        settings.lang = "r"
        assert settings.lang == "r"
        assert load_config()["lang"] == "r"

    def test_get_saved_lang_falls_back_to_detect(self, tmp_config, monkeypatch):
        """No saved lang in config -> falls back to _detect_language."""
        monkeypatch.setattr("locale.getlocale", lambda: ("ja_JP", "UTF-8"))
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            s = Settings()
        assert s.lang == "r"

    def test_get_saved_lang_uses_saved(self, tmp_config):
        """Saved lang in config is used directly."""
        save_config({"lang": "x"})
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            s = Settings()
        assert s.lang == "x"


# =========================================================================
# Settings.resolve_cloud_dirs
# =========================================================================


class TestResolveCloudDirs:
    """resolve_cloud_dirs: swaps width/height for non-square at 90/270."""

    @pytest.fixture
    def settings(self, tmp_config):
        """Settings with a non-square resolution (1280x480)."""
        save_config({"resolution": [1280, 480]})
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            s = Settings()
        return s

    def test_rotation_0_keeps_landscape(self, settings):
        with patch("trcc.conf.get_web_dir", return_value="/tmp/web_l") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks_l"):
            settings.resolve_cloud_dirs(0)
            mock_web.assert_called_with(1280, 480)

    def test_rotation_90_swaps_to_portrait(self, settings):
        with patch("trcc.conf.get_web_dir", return_value="/tmp/web_p") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks_p"):
            settings.resolve_cloud_dirs(90)
            mock_web.assert_called_with(480, 1280)
        assert settings.web_dir == Path("/tmp/web_p")
        assert settings.masks_dir == Path("/tmp/masks_p")

    def test_rotation_270_swaps_to_portrait(self, settings):
        with patch("trcc.conf.get_web_dir", return_value="/tmp/web_p") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks_p"):
            settings.resolve_cloud_dirs(270)
            mock_web.assert_called_with(480, 1280)

    def test_rotation_180_keeps_landscape(self, settings):
        with patch("trcc.conf.get_web_dir", return_value="/tmp/web_l") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks_l"):
            settings.resolve_cloud_dirs(180)
            mock_web.assert_called_with(1280, 480)

    def test_square_display_no_swap(self, tmp_config):
        """Square resolution (320x320) never swaps, even at 90 degrees."""
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            mock_td.return_value = MagicMock()
            s = Settings()
        with patch("trcc.conf.get_web_dir", return_value="/tmp/web_sq") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks_sq"):
            s.resolve_cloud_dirs(90)
            mock_web.assert_called_with(320, 320)

    def test_default_rotation_0(self, settings):
        """Default rotation parameter is 0 (no swap)."""
        with patch("trcc.conf.get_web_dir", return_value="/tmp/web") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            settings.resolve_cloud_dirs()
            mock_web.assert_called_with(1280, 480)


# =========================================================================
# Settings._resolve_paths
# =========================================================================


class TestResolvePaths:
    """_resolve_paths: resolves theme_dir, web_dir, masks_dir."""

    def test_sets_all_three_paths(self, tmp_config):
        mock_td = MagicMock()
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution", return_value=mock_td), \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web") as mock_web, \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks") as mock_masks:
            s = Settings()
        assert s.theme_dir is mock_td
        assert s.web_dir == Path("/tmp/web")
        assert s.masks_dir == Path("/tmp/masks")
        mock_web.assert_called_with(320, 320)
        mock_masks.assert_called_with(320, 320)


# =========================================================================
# Settings properties (width, height, resolution, user_data_dir)
# =========================================================================


class TestSettingsProperties:
    """Read-only properties return correct values."""

    def test_user_data_dir(self, tmp_config):
        from trcc.adapters.infra.data_repository import USER_DATA_DIR
        with patch("trcc.conf._migrate_config"), \
             patch("trcc.conf.ThemeDir.for_resolution", return_value=MagicMock()), \
             patch("trcc.conf.get_web_dir", return_value="/tmp/web"), \
             patch("trcc.conf.get_web_masks_dir", return_value="/tmp/masks"):
            s = Settings()
        assert s.user_data_dir == Path(USER_DATA_DIR)
