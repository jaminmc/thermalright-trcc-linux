"""Unified instance detection — which trcc process owns the device?

Pure core module: no adapter imports, no framework deps.
Any adapter (GUI, CLI, API) calls find_active() before touching USB.

Priority: GUI > API > direct.
"""
from __future__ import annotations

import enum
import logging
import os
import socket
from pathlib import Path

log = logging.getLogger(__name__)

# Default API port — single source of truth (used by CLI serve and detection)
DEFAULT_API_PORT = 9876

# IPC socket name — matches ipc.py
_SOCK_NAME = "trcc-linux.sock"


class InstanceKind(enum.Enum):
    """Which type of trcc instance is running."""
    GUI = "gui"
    API = "api"


def _socket_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / _SOCK_NAME


def _gui_running() -> bool:
    """Check if GUI daemon is listening on IPC socket."""
    if not hasattr(socket, 'AF_UNIX'):
        return False
    path = _socket_path()
    if not path.exists():
        return False
    try:
        s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(str(path))
        s.close()
        return True
    except OSError:
        return False


def _api_running(port: int = DEFAULT_API_PORT) -> bool:
    """Check if API server responds on localhost."""
    try:
        s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
        s.settimeout(1.0)
        s.connect(("127.0.0.1", port))
        # Send minimal HTTP GET /health
        s.sendall(b"GET /health HTTP/1.0\r\nHost: 127.0.0.1\r\n\r\n")
        data = s.recv(512)
        s.close()
        return b"200" in data and b"trcc" in data.lower()
    except OSError:
        return False


def find_active(port: int = DEFAULT_API_PORT) -> InstanceKind | None:
    """Detect which trcc instance (if any) currently owns the device.

    Check order: GUI (IPC socket) > API (HTTP health) > None.
    Returns None when no other instance is running — caller should
    take device ownership directly.
    """
    if _gui_running():
        log.info("Detected running GUI daemon (IPC socket)")
        return InstanceKind.GUI
    if _api_running(port):
        log.info("Detected running API server (port %d)", port)
        return InstanceKind.API
    return None
