"""macOS autostart — Launch Agent plist in ~/Library/LaunchAgents/."""
from __future__ import annotations

import logging
from pathlib import Path

from trcc.core.ports import AutostartManager

log = logging.getLogger(__name__)

_LAUNCH_AGENTS_DIR = Path.home() / 'Library' / 'LaunchAgents'
_LAUNCH_AGENT_FILE = _LAUNCH_AGENTS_DIR / 'com.thermalright.trcc.plist'


class MacOSAutostartManager(AutostartManager):
    """macOS autostart via ~/Library/LaunchAgents/com.thermalright.trcc.plist."""

    def is_enabled(self) -> bool:
        return _LAUNCH_AGENT_FILE.exists()

    def enable(self) -> None:
        _LAUNCH_AGENTS_DIR.mkdir(parents=True, exist_ok=True)
        _LAUNCH_AGENT_FILE.write_text(self._plist())
        log.info("Autostart enabled: %s", _LAUNCH_AGENT_FILE)

    def disable(self) -> None:
        if _LAUNCH_AGENT_FILE.exists():
            _LAUNCH_AGENT_FILE.unlink()
        log.info("Autostart disabled")

    def refresh(self) -> None:
        if not _LAUNCH_AGENT_FILE.exists():
            return
        expected = self._plist()
        if _LAUNCH_AGENT_FILE.read_text() != expected:
            _LAUNCH_AGENT_FILE.write_text(expected)
            log.info("Autostart refreshed: %s", _LAUNCH_AGENT_FILE)

    def _plist(self) -> str:
        exec_path = self.get_exec()
        return (
            '<?xml version="1.0" encoding="UTF-8"?>\n'
            '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN"\n'
            '  "http://www.apple.com/DTDs/PropertyList-1.0.dtd">\n'
            '<plist version="1.0">\n'
            '<dict>\n'
            '    <key>Label</key>\n'
            '    <string>com.thermalright.trcc</string>\n'
            '    <key>ProgramArguments</key>\n'
            '    <array>\n'
            f'        <string>{exec_path}</string>\n'
            '        <string>gui</string>\n'
            '        <string>--resume</string>\n'
            '    </array>\n'
            '    <key>RunAtLoad</key>\n'
            '    <true/>\n'
            '    <key>KeepAlive</key>\n'
            '    <false/>\n'
            '</dict>\n'
            '</plist>\n'
        )
