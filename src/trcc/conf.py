"""Application settings and config persistence for TRCC.

Single source of truth for resolution, paths, preferences, language, and device settings.
Config is stored at ~/.trcc/config.json.

Usage:
    from trcc.conf import settings, Settings

    settings.width          # LCD width
    settings.height         # LCD height
    settings.resolution     # (width, height) tuple
    settings.theme_dir      # ThemeDir for current resolution
    settings.web_dir        # Cloud theme preview dir
    settings.masks_dir      # Cloud mask overlay dir
    settings.temp_unit      # 0=Celsius, 1=Fahrenheit
    settings.lang           # ISO 639-1 language code ('en', 'de', 'ru', 'fr', 'zh', etc.)

    # Static settings operations
    Settings.device_config_key(0, 0x87cd, 0x70db)  # returns "0"
    Settings.get_device_config(key)  # {"vid_pid": "87cd_70db", ...}
    Settings.save_device_setting(key, 'theme', 'dark')

    # Low-level config access (module-level)
    from trcc.conf import load_config, save_config
"""
from __future__ import annotations

import json
import locale
import logging
import os
from pathlib import Path
from typing import Any, Optional

from .__version__ import __version__
from .core.models import LEGACY_TO_ISO, LOCALE_TO_LANG, ThemeDir
from .core.paths import USER_CONFIG_DIR

log = logging.getLogger(__name__)

# =========================================================================
# Config file location — everything under ~/.trcc/
# =========================================================================

CONFIG_DIR = USER_CONFIG_DIR
CONFIG_PATH = os.path.join(CONFIG_DIR, 'config.json')

# USBLCD (SCSI/RGB565) supported resolutions
SUPPORTED_RESOLUTIONS = [
    (240, 240),
    (320, 320),
    (480, 480),
    (640, 480),
]


# =========================================================================
# Low-level config persistence
# =========================================================================

def _migrate_old_config() -> None:
    """One-time migration: move files from ~/.config/trcc/ to ~/.trcc/."""
    old_dir = os.path.expanduser('~/.config/trcc')
    if not os.path.isdir(old_dir) or old_dir == CONFIG_DIR:
        return
    import shutil
    os.makedirs(CONFIG_DIR, exist_ok=True)
    for name in os.listdir(old_dir):
        src = os.path.join(old_dir, name)
        dst = os.path.join(CONFIG_DIR, name)
        if not os.path.exists(dst):
            shutil.move(src, dst)
    # Remove old dir if empty
    try:
        os.rmdir(old_dir)
    except OSError:
        pass
    log.info("Migrated config from %s to %s", old_dir, CONFIG_DIR)


def _migrate_device_keys(config: dict) -> bool:
    """Migrate device keys from '0:vid_pid' to '0' with vid_pid inside dict.

    Old format: {"devices": {"0:0402_3922": {"brightness_level": 3}}}
    New format: {"devices": {"0": {"vid_pid": "0402_3922", "brightness_level": 3}}}

    Returns True if migration was performed.
    """
    devices = config.get('devices')
    if not devices or not isinstance(devices, dict):
        return False
    migrated = {}
    changed = False
    for key, value in devices.items():
        if ':' in key:
            index, vid_pid = key.split(':', 1)
            if isinstance(value, dict):
                value['vid_pid'] = vid_pid
            migrated[index] = value
            changed = True
        else:
            migrated[key] = value
    if changed:
        config['devices'] = migrated
    return changed


def load_config() -> dict:
    """Load user config from disk. Returns empty dict if file is missing."""
    _migrate_old_config()
    try:
        with open(CONFIG_PATH, 'r') as f:
            config = json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("Config file is corrupt (%s) — resetting to defaults: %s", CONFIG_PATH, e)
        return {}
    except OSError as e:
        log.error("Failed to read config file (%s): %s", CONFIG_PATH, e)
        return {}
    if _migrate_device_keys(config):
        save_config(config)
    return config


def save_config(config: dict):
    """Save user config to disk (fsync'd for durability across shutdowns)."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(CONFIG_PATH, 'w') as f:
        json.dump(config, f, indent=2)
        f.flush()
        os.fsync(f.fileno())


# =========================================================================
# Last handshake cache — written by GUI, read by `trcc report`
# =========================================================================

_HANDSHAKE_CACHE_PATH = os.path.join(CONFIG_DIR, 'last_handshake.json')


def save_last_handshake(data: dict) -> None:
    """Cache the last successful handshake result for `trcc report`."""
    os.makedirs(CONFIG_DIR, exist_ok=True)
    with open(_HANDSHAKE_CACHE_PATH, 'w') as f:
        json.dump(data, f, indent=2)


def load_last_handshake() -> dict:
    """Load cached handshake result. Returns empty dict if missing."""
    try:
        with open(_HANDSHAKE_CACHE_PATH, 'r') as f:
            return json.load(f)
    except FileNotFoundError:
        return {}
    except json.JSONDecodeError as e:
        log.warning("Handshake cache is corrupt — ignoring: %s", e)
        return {}
    except OSError as e:
        log.error("Failed to read handshake cache: %s", e)
        return {}


def _migrate_config() -> None:
    """Clear stale device-derived state when app version changes.

    Preserves user prefs (temp_unit, lang, format_prefs, hdd_enabled).
    Clears device-derived keys (devices, resolution, selected_device,
    installed_resolutions) and LED probe cache so new detection logic
    takes effect after upgrade.
    """
    config = load_config()
    saved_version = config.get('config_version')

    if saved_version == __version__:
        return

    if saved_version is not None:
        # Version mismatch — clear device-derived state
        log.info("Config version %s → %s: clearing device state",
                 saved_version, __version__)
        for key in ('devices', 'resolution', 'selected_device',
                    'installed_resolutions'):  # 'resolution' is legacy global — now per-device
            config.pop(key, None)

        # Delete LED probe cache (stale PM → style mappings)
        probe_cache = os.path.join(CONFIG_DIR, 'led_probe_cache.json')
        if os.path.exists(probe_cache):
            try:
                os.remove(probe_cache)
                log.info("Deleted stale LED probe cache")
            except OSError as e:
                log.warning("Failed to delete LED probe cache: %s", e)

    config['config_version'] = __version__
    save_config(config)


# =========================================================================
# Language detection (system locale → ISO 639-1 code)
# =========================================================================


def _detect_language() -> str:
    """Detect system language and return ISO 639-1 code."""
    try:
        lang = (locale.getlocale()[0]
                or os.environ.get('LANG', '').split('.')[0]
                or 'en')
    except Exception:
        lang = 'en'

    if lang in LOCALE_TO_LANG:
        return LOCALE_TO_LANG[lang]

    prefix = lang.split('_')[0]
    if prefix in LOCALE_TO_LANG:
        return LOCALE_TO_LANG[prefix]

    return 'en'


def _migrate_legacy_lang(code: str) -> str:
    """Convert legacy C# language suffix to ISO 639-1 code."""
    return LEGACY_TO_ISO.get(code, code)


# =========================================================================
# Settings class — all config operations + singleton
# =========================================================================

class Settings:
    """Application-wide settings singleton.

    Static methods provide config operations (device, format, resolution).
    Instance holds resolved paths and current state.
    """

    # --- Private persistence helpers (init-only / called by instance methods) ---

    @staticmethod
    def _get_saved_resolution() -> tuple[int, int] | None:
        """Get saved LCD resolution from per-device config.

        Scans all device entries for a saved w/h. Falls back to the legacy
        global 'resolution' key for migration from older config files.
        Returns None if no resolution has been configured.
        """
        config = load_config()
        # Per-device resolution (preferred — each device stores its own w/h)
        for dev_cfg in config.get('devices', {}).values():
            w = dev_cfg.get('w')
            h = dev_cfg.get('h')
            if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
                return (w, h)
        # Legacy global 'resolution' key — migrate on first write
        res = config.get('resolution')
        if isinstance(res, list) and len(res) == 2:
            return (int(res[0]), int(res[1]))
        return None

    @staticmethod
    def get_device_resolution(key: str) -> tuple[int, int] | None:
        """Get the saved resolution for a specific device. Returns None if not set."""
        dev_cfg = Settings.get_device_config(key)
        w = dev_cfg.get('w')
        h = dev_cfg.get('h')
        if isinstance(w, int) and isinstance(h, int) and w > 0 and h > 0:
            return (w, h)
        return None

    @staticmethod
    def _get_saved_temp_unit() -> int:
        """Get saved temperature unit. 0=Celsius, 1=Fahrenheit. Defaults to 0."""
        return load_config().get('temp_unit', 0)

    @staticmethod
    def _save_temp_unit(unit: int):
        """Persist temperature unit to config. 0=Celsius, 1=Fahrenheit."""
        config = load_config()
        config['temp_unit'] = unit
        save_config(config)

    @staticmethod
    def _get_saved_hdd_enabled() -> bool:
        """Get saved HDD info toggle. Defaults to True."""
        return load_config().get('hdd_enabled', True)

    @staticmethod
    def _save_hdd_enabled(enabled: bool):
        """Persist HDD info toggle to config."""
        config = load_config()
        config['hdd_enabled'] = enabled
        save_config(config)

    @staticmethod
    def _get_saved_refresh_interval() -> int:
        """Get saved metrics refresh interval in seconds. Defaults to 1."""
        return int(load_config().get('refresh_interval', 1))

    @staticmethod
    def _save_refresh_interval(interval: int) -> None:
        """Persist metrics refresh interval to config."""
        config = load_config()
        config['refresh_interval'] = interval
        save_config(config)

    # --- Public static methods (device config, format prefs, etc.) ---

    @staticmethod
    def get_install_info() -> dict:
        """Get install method and distro. Returns {} if not yet recorded."""
        return load_config().get('install_info', {})

    @staticmethod
    def save_install_info(method: str, distro: str):
        """Persist how trcc-linux was installed and on which distro."""
        config = load_config()
        config['install_info'] = {'method': method, 'distro': distro}
        save_config(config)

    @staticmethod
    def get_selected_device() -> Optional[str]:
        """Get CLI-selected device path (e.g. '/dev/sg0'). Returns None if unset."""
        return load_config().get('selected_device')

    @staticmethod
    def save_selected_device(device_path: str):
        """Persist CLI-selected device path."""
        config = load_config()
        config['selected_device'] = device_path
        save_config(config)

    # Cache vid_pid per index so save_device_setting can store it automatically
    _vid_pid_cache: dict[str, str] = {}

    @staticmethod
    def device_config_key(index: int, vid: int, pid: int) -> str:
        """Build per-device config key (index only).

        Config format: {"devices": {"0": {"vid_pid": "0402_3922", ...}}}
        The vid_pid is stored inside the device dict, not in the key.
        """
        key = str(index)
        Settings._vid_pid_cache[key] = f"{vid:04x}_{pid:04x}"
        return key

    @staticmethod
    def get_device_config(key: str) -> dict:
        """Get per-device config dict. Returns empty dict if not found."""
        return load_config().get('devices', {}).get(key, {})

    @staticmethod
    def save_device_setting(key: str, setting: str, value):
        """Save a single setting for a device."""
        config = load_config()
        devices = config.setdefault('devices', {})
        dev_cfg = devices.setdefault(key, {})
        # Store vid_pid on first write (from device_config_key cache)
        if 'vid_pid' not in dev_cfg and key in Settings._vid_pid_cache:
            dev_cfg['vid_pid'] = Settings._vid_pid_cache[key]
        dev_cfg[setting] = value
        save_config(config)

    @staticmethod
    def show_info_module() -> bool:
        """Whether to show the sensor metrics bar above the preview (default: off)."""
        return load_config().get('show_info_module', False)

    @staticmethod
    def get_format_prefs() -> dict:
        """Get saved format preferences. Keys: time_format, date_format, temp_unit."""
        return load_config().get('format_prefs', {})

    @staticmethod
    def save_format_pref(key: str, value: int):
        """Save a single format preference (e.g. time_format=1 for 12h)."""
        config = load_config()
        prefs = config.setdefault('format_prefs', {})
        prefs[key] = value
        save_config(config)

    @staticmethod
    def apply_format_prefs(overlay_config: dict) -> dict:
        """Apply saved format prefs to an overlay config dict.

        Theme DC defines element layout; user prefs override format fields.
        Each element cherry-picks the relevant pref for its metric type.
        """
        prefs = Settings.get_format_prefs()
        if not prefs:
            return overlay_config
        for entry in overlay_config.values():
            if not isinstance(entry, dict):
                continue
            metric = entry.get('metric', '')
            if metric == 'time' and 'time_format' in prefs:
                entry['time_format'] = prefs['time_format']
            elif metric == 'date' and 'date_format' in prefs:
                entry['date_format'] = prefs['date_format']
            if 'temp_unit' in prefs and 'metric' in entry:
                entry['temp_unit'] = prefs['temp_unit']
        return overlay_config

    @staticmethod
    def clear_installed_resolutions():
        """Remove all resolution-installed markers (used by uninstall)."""
        config = load_config()
        config.pop("installed_resolutions", None)
        save_config(config)

    @staticmethod
    def get_api_token() -> str:
        """Get persistent API token, generating one on first call.

        Stored in config.json so it survives restarts — phone pairs once,
        stays trusted forever.
        """
        import secrets
        import string

        config = load_config()
        token = config.get('api_token')
        if not token:
            alphabet = string.ascii_letters + string.digits
            token = ''.join(secrets.choice(alphabet) for _ in range(16))
            config['api_token'] = token
            save_config(config)
        return token

    @staticmethod
    def save_api_token(token: str) -> None:
        """Save an explicit API token (from --token flag)."""
        config = load_config()
        config['api_token'] = token
        save_config(config)

    # --- Instance methods and properties ---

    def __init__(self, path_resolver: Any) -> None:
        if path_resolver is None:
            raise RuntimeError(
                "Settings requires a path_resolver. "
                "Use init_settings() from a composition root.")
        _migrate_config()
        self._path_resolver = path_resolver
        res = Settings._get_saved_resolution()
        self._width, self._height = res if res else (0, 0)

        # Derived paths (resolved for current resolution)
        self.theme_dir: Optional[ThemeDir] = None
        self.web_dir: Optional[Path] = None
        self.masks_dir: Optional[Path] = None

        # User preferences
        self.temp_unit: int = Settings._get_saved_temp_unit()
        self.hdd_enabled: bool = Settings._get_saved_hdd_enabled()
        self.refresh_interval: int = Settings._get_saved_refresh_interval()
        self._lang: str = self._get_saved_lang()

        # Static paths
        self.user_data_dir = Path(path_resolver.data_dir())
        self.user_content_dir = Path(path_resolver.user_content_dir())

        # Resolve paths if a saved resolution exists
        if self._width and self._height:
            self._resolve_paths()

    @property
    def width(self) -> int:
        return self._width

    @property
    def height(self) -> int:
        return self._height

    @property
    def resolution(self) -> tuple[int, int]:
        return (self._width, self._height)

    def set_resolution(self, width: int, height: int, persist: bool = True) -> None:
        """Update active resolution in-memory and re-resolve derived paths.

        Resolution is persisted per device via save_device_setting('w'/'h'),
        called by lcd_handler after handshake. The 'persist' parameter is
        kept for backward compatibility but no longer writes the global key.
        """
        if (width, height) == (self._width, self._height):
            return
        log.info("Settings: resolution %dx%d → %dx%d",
                 self._width, self._height, width, height)
        self._width = width
        self._height = height
        self._resolve_paths()

    def set_temp_unit(self, unit: int) -> None:
        """Set temperature unit (0=Celsius, 1=Fahrenheit) and persist."""
        self.temp_unit = unit
        Settings._save_temp_unit(unit)

    def set_hdd_enabled(self, enabled: bool) -> None:
        """Set HDD info toggle and persist."""
        self.hdd_enabled = enabled
        Settings._save_hdd_enabled(enabled)

    def set_refresh_interval(self, interval: int) -> None:
        """Set metrics refresh interval in seconds and persist."""
        self.refresh_interval = interval
        Settings._save_refresh_interval(interval)

    @property
    def lang(self) -> str:
        """Current ISO 639-1 language code ('en', 'de', 'ru', 'fr', 'zh', etc.)."""
        return self._lang

    @lang.setter
    def lang(self, value: str) -> None:
        """Set ISO 639-1 language code and persist."""
        self._lang = value
        config = load_config()
        config['lang'] = value
        save_config(config)

    def _get_saved_lang(self) -> str:
        """Get saved language, falling back to system locale detection.

        Migrates legacy C# suffixes (e.g. 'd' → 'de') on first read.
        """
        saved = load_config().get('lang')
        if saved is not None:
            migrated = _migrate_legacy_lang(saved)
            if migrated != saved:
                self.lang = migrated  # Persist the migration
            return migrated
        return _detect_language()

    def _resolve_paths(self) -> None:
        """Resolve theme/web/mask directories for current resolution."""
        w, h = self._width, self._height
        self.theme_dir = ThemeDir.for_resolution(w, h)
        self.web_dir = Path(self._path_resolver.web_dir(w, h))
        self.masks_dir = Path(self._path_resolver.web_masks_dir(w, h))

    def resolve_cloud_dirs(self, rotation: int = 0) -> None:
        """Re-resolve cloud background/mask dirs for rotation.

        C# GetWebBackgroundImageDirectory / GetFileListMBDir:
        non-square displays swap width/height when directionB is 90 or 270.
        Local themes (theme_dir) stay landscape — only cloud dirs switch.
        """
        w, h = self._width, self._height
        if w != h and rotation in (90, 270):
            w, h = h, w
        self.web_dir = Path(self._path_resolver.web_dir(w, h))
        self.masks_dir = Path(self._path_resolver.web_masks_dir(w, h))


# Module-level singleton — initialized by composition roots via init_settings()
_settings: Settings | None = None


def _get_settings() -> Settings:
    """Return the Settings singleton. Raises if not initialized."""
    if _settings is None:
        raise RuntimeError(
            "Settings not initialized. "
            "Call init_settings() from a composition root.")
    return _settings


# Public accessor — always returns Settings (not Optional)
# Composition roots must call init_settings() before any code uses this.
settings: Settings = None  # type: ignore[assignment]


def init_settings(path_resolver: Any) -> Settings:
    """Initialize the Settings singleton with a platform path resolver.

    Called by composition roots (CLI, GUI, API) after building the
    platform adapter via ControllerBuilder.build_setup().
    """
    global _settings, settings  # noqa: PLW0603
    _settings = Settings(path_resolver)
    settings = _settings
    return settings
