"""Linux autostart — XDG .desktop file in ~/.config/autostart/."""
from __future__ import annotations

import logging
from pathlib import Path

from trcc.core.ports import AutostartManager

log = logging.getLogger(__name__)

_AUTOSTART_DIR  = Path.home() / '.config' / 'autostart'
_AUTOSTART_FILE = _AUTOSTART_DIR / 'trcc-linux.desktop'
_LEGACY_FILE    = _AUTOSTART_DIR / 'trcc.desktop'


class LinuxAutostartManager(AutostartManager):
    """XDG autostart via ~/.config/autostart/trcc-linux.desktop."""

    def is_enabled(self) -> bool:
        return _AUTOSTART_FILE.exists()

    def enable(self) -> None:
        _AUTOSTART_DIR.mkdir(parents=True, exist_ok=True)
        _AUTOSTART_FILE.write_text(self._desktop_entry())
        log.info("Autostart enabled: %s", _AUTOSTART_FILE)

    def disable(self) -> None:
        if _AUTOSTART_FILE.exists():
            _AUTOSTART_FILE.unlink()
        log.info("Autostart disabled")

    def refresh(self) -> None:
        if not _AUTOSTART_FILE.exists():
            return
        expected = self._desktop_entry()
        if _AUTOSTART_FILE.read_text() != expected:
            _AUTOSTART_FILE.write_text(expected)
            log.info("Autostart refreshed: %s", _AUTOSTART_FILE)

    def ensure(self) -> bool:
        # Remove legacy file from pre-v2.0.2
        if _LEGACY_FILE.exists():
            _LEGACY_FILE.unlink()
            log.info("Removed legacy autostart file: %s", _LEGACY_FILE)
        return super().ensure()

    def _desktop_entry(self) -> str:
        exec_path = self.get_exec()
        return (
            "[Desktop Entry]\n"
            "Type=Application\n"
            "Name=TRCC Linux\n"
            "Comment=Thermalright LCD Control Center\n"
            f"Exec={exec_path} gui --resume\n"
            "Icon=trcc\n"
            "Terminal=false\n"
            "Categories=Utility;System;\n"
            "StartupWMClass=trcc-linux\n"
            "X-GNOME-Autostart-enabled=true\n"
        )
