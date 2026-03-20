"""Windows autostart — HKCU\\Software\\Microsoft\\Windows\\CurrentVersion\\Run."""
from __future__ import annotations

import logging
from typing import Any

from trcc.core.ports import AutostartManager

log = logging.getLogger(__name__)

_REG_KEY   = r'Software\Microsoft\Windows\CurrentVersion\Run'
_REG_VALUE = 'TRCC Linux'


def _winreg() -> Any:
    """Return winreg stdlib module as Any (Windows-only, avoids pyright platform errors)."""
    import winreg  # pyright: ignore[reportMissingImports]
    return winreg


class WindowsAutostartManager(AutostartManager):
    """Windows autostart via HKCU Run registry key."""

    def is_enabled(self) -> bool:
        try:
            wr = _winreg()
            key = wr.OpenKey(wr.HKEY_CURRENT_USER, _REG_KEY, 0, wr.KEY_READ)
            wr.QueryValueEx(key, _REG_VALUE)
            wr.CloseKey(key)
            return True
        except OSError:
            return False

    def enable(self) -> None:
        wr = _winreg()
        exec_path = self.get_exec()
        key = wr.OpenKey(wr.HKEY_CURRENT_USER, _REG_KEY, 0, wr.KEY_SET_VALUE)
        wr.SetValueEx(key, _REG_VALUE, 0, wr.REG_SZ, f'"{exec_path}" gui --resume')
        wr.CloseKey(key)
        log.info("Autostart enabled: HKCU\\%s", _REG_KEY)

    def disable(self) -> None:
        try:
            wr = _winreg()
            key = wr.OpenKey(wr.HKEY_CURRENT_USER, _REG_KEY, 0, wr.KEY_SET_VALUE)
            wr.DeleteValue(key, _REG_VALUE)
            wr.CloseKey(key)
        except OSError:
            pass
        log.info("Autostart disabled")

    def refresh(self) -> None:
        if not self.is_enabled():
            return
        wr = _winreg()
        exec_path = self.get_exec()
        expected = f'"{exec_path}" gui --resume'
        try:
            key = wr.OpenKey(
                wr.HKEY_CURRENT_USER, _REG_KEY, 0,
                wr.KEY_READ | wr.KEY_SET_VALUE,
            )
            current, _ = wr.QueryValueEx(key, _REG_VALUE)
            if current != expected:
                wr.SetValueEx(key, _REG_VALUE, 0, wr.REG_SZ, expected)
                log.info("Autostart refreshed: HKCU\\%s", _REG_KEY)
            wr.CloseKey(key)
        except OSError:
            pass
