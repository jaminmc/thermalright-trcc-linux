"""Platform detection — routes to the correct adapter implementations.

Zero imports from adapters. Returns string identifiers that composition roots
use to select the right concrete classes.
"""
from __future__ import annotations

import os
import shutil
import sys

LINUX = sys.platform.startswith('linux')
WINDOWS = sys.platform == 'win32'
MACOS = sys.platform == 'darwin'
BSD = 'bsd' in sys.platform


def platform_name() -> str:
    """Human-readable platform name."""
    if WINDOWS:
        return 'Windows'
    if MACOS:
        return 'macOS'
    if BSD:
        return 'BSD'
    return 'Linux'


def is_root() -> bool:
    """Check if running as root/admin (cross-platform)."""
    if LINUX:
        return os.geteuid() == 0
    try:
        import ctypes
        return ctypes.windll.shell32.IsUserAnAdmin() != 0  # type: ignore[attr-defined]
    except Exception:
        return False


def detect_install_method() -> str:
    """Detect how trcc-linux was installed.

    Returns 'pipx', 'pip', 'pacman', 'dnf', or 'apt'.
    """
    if 'pipx' in sys.prefix:
        return 'pipx'
    try:
        from importlib.metadata import distribution
        dist = distribution('trcc-linux')
        installer = (dist.read_text('INSTALLER') or '').strip()
        if installer == 'pip':
            return 'pip'
    except Exception:
        pass
    for mgr in ('pacman', 'dnf', 'apt'):
        if shutil.which(mgr):
            return mgr
    return 'pip'
