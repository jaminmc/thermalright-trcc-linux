"""IPC server (GUI daemon) and client (CLI) for single-device-owner pattern.

When the GUI is running, it owns all USB device access.  CLI commands
detect the running GUI and route through a Unix domain socket instead
of touching USB directly.  When no GUI is running, CLI falls back to
direct USB access (current behavior).

Protocol: newline-delimited JSON over Unix domain socket.
  Request:  {"cmd": "display.send_color", "args": [255, 0, 0], "kwargs": {}}\n
  Response: {"success": true, "message": "..."}\n
"""
from __future__ import annotations

import json
import logging
import os
import socket
from pathlib import Path
from typing import Any

log = logging.getLogger(__name__)

# Socket path: same dir as the instance lock file
_SOCK_NAME = "trcc-linux.sock"


def _socket_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / _SOCK_NAME


# Non-serializable keys to strip from dispatcher results (PIL Image, etc.)
_NON_SERIALIZABLE = frozenset({"image", "colors"})

# Allowed dispatcher methods (whitelist — reject anything else)
_DISPLAY_METHODS = frozenset({
    "send_image", "send_color", "reset",
    "set_brightness", "set_rotation", "set_split_mode",
    "load_mask", "render_overlay",
})
_LED_METHODS = frozenset({
    "set_color", "set_mode", "set_brightness", "off",
    "set_sensor_source",
    "set_zone_color", "set_zone_mode", "set_zone_brightness",
    "toggle_zone", "set_zone_sync",
    "toggle_segment", "set_clock_format", "set_temp_unit",
})


def _sanitize(result: dict) -> dict:
    """Remove non-JSON-serializable keys from dispatcher result."""
    return {k: v for k, v in result.items() if k not in _NON_SERIALIZABLE}


# =========================================================================
# Server (runs in the GUI process, Qt event loop)
# =========================================================================

class IPCServer:
    """Unix socket IPC server — listens for CLI requests, routes to dispatchers.

    Integrates with Qt event loop via QSocketNotifier on the listening fd.
    Each client is handled synchronously (accept → read → dispatch → respond
    → close) in a single callback, which is safe because requests are small
    and local.
    """

    def __init__(self, display_dispatcher: Any, led_dispatcher: Any):
        self._display = display_dispatcher
        self._led = led_dispatcher
        self._sock: socket.socket | None = None
        self._notifier: Any = None  # QSocketNotifier
        self._current_frame: Any = None  # PIL Image — last frame sent to LCD

    @property
    def display(self) -> Any:
        return self._display

    @display.setter
    def display(self, value: Any) -> None:
        self._display = value

    @property
    def led(self) -> Any:
        return self._led

    @led.setter
    def led(self, value: Any) -> None:
        self._led = value

    def capture_frame(self, image: Any) -> None:
        """Store the latest frame sent to LCD (called by on_frame_sent callback)."""
        self._current_frame = image

    def start(self) -> None:
        """Bind and listen on Unix domain socket."""
        path = _socket_path()
        if path.exists():
            path.unlink()

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.setblocking(False)
        self._sock.bind(str(path))
        self._sock.listen(5)
        os.chmod(str(path), 0o660)  # nosec B103 — socket in $XDG_RUNTIME_DIR (0o700)

        from PySide6.QtCore import QSocketNotifier
        self._notifier = QSocketNotifier(
            self._sock.fileno(), QSocketNotifier.Type.Read)
        self._notifier.activated.connect(self._on_connection)
        log.info("IPC server listening on %s", path)

    def shutdown(self) -> None:
        """Close socket and clean up."""
        if self._notifier:
            self._notifier.setEnabled(False)
            self._notifier = None
        if self._sock:
            self._sock.close()
            self._sock = None
        path = _socket_path()
        if path.exists():
            path.unlink()
        log.info("IPC server shut down")

    def _on_connection(self) -> None:
        """Accept client, read request, dispatch, respond, close."""
        if not self._sock:
            return
        try:
            client, _ = self._sock.accept()
        except OSError:
            return

        try:
            client.settimeout(5.0)
            data = client.recv(65536)
            if not data:
                return

            request = json.loads(data.decode().strip())
            result = self._dispatch(request)
            client.sendall(json.dumps(result).encode() + b"\n")
        except (json.JSONDecodeError, UnicodeDecodeError) as e:
            _send_error(client, f"Bad request: {e}")
        except Exception as e:
            log.warning("IPC dispatch error: %s", e)
            _send_error(client, str(e))
        finally:
            try:
                client.close()
            except OSError:
                pass

    def _dispatch(self, request: dict) -> dict:
        """Route request to the correct dispatcher method."""
        cmd = request.get("cmd", "")
        args = request.get("args", [])
        kwargs = request.get("kwargs", {})

        if cmd == "status":
            return self._status()

        parts = cmd.split(".", 1)
        if len(parts) != 2:
            return {"success": False, "error": f"Invalid command: {cmd}"}

        domain, method = parts

        if domain == "display":
            if method == "get_frame":
                return self._get_frame()
            if method not in _DISPLAY_METHODS:
                return {"success": False, "error": f"Unknown command: {cmd}"}
            if not self._display or not self._display.connected:
                return {"success": False, "error": "No LCD device connected"}
            return _sanitize(getattr(self._display, method)(*args, **kwargs))

        if domain == "led":
            if method not in _LED_METHODS:
                return {"success": False, "error": f"Unknown command: {cmd}"}
            if not self._led or not self._led.connected:
                return {"success": False, "error": "No LED device connected"}
            return _sanitize(getattr(self._led, method)(*args, **kwargs))

        return {"success": False, "error": f"Unknown domain: {domain}"}

    def _get_frame(self) -> dict:
        """Return the current LCD frame as base64 JPEG."""
        import base64
        import io

        if self._current_frame is None:
            return {"success": False, "error": "No frame available"}
        buf = io.BytesIO()
        self._current_frame.save(buf, format="JPEG", quality=85)
        return {
            "success": True,
            "frame": base64.b64encode(buf.getvalue()).decode("ascii"),
        }

    def _status(self) -> dict:
        """Return current device status."""
        result: dict[str, Any] = {"success": True}
        if self._display and self._display.connected:
            dev = self._display.device
            result["lcd"] = {
                "connected": True,
                "path": dev.path,
                "resolution": list(dev.resolution),
                "protocol": dev.protocol,
            }
        if self._led and self._led.connected:
            result["led"] = {"connected": True}
        return result


def _send_error(client: socket.socket, msg: str) -> None:
    try:
        client.sendall(json.dumps({"success": False, "error": msg}).encode() + b"\n")
    except OSError:
        pass


# =========================================================================
# Client (used by CLI to send commands to the GUI daemon)
# =========================================================================

class IPCClient:
    """Unix socket IPC client — detects daemon and routes commands."""

    @staticmethod
    def available() -> bool:
        """Check if the IPC daemon is running and accepting connections."""
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

    @staticmethod
    def send(cmd: str, args: list | None = None,
             kwargs: dict | None = None) -> dict:
        """Send command to daemon, return result dict."""
        request = {"cmd": cmd, "args": args or [], "kwargs": kwargs or {}}
        try:
            s = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
            s.settimeout(10.0)
            s.connect(str(_socket_path()))
            s.sendall(json.dumps(request).encode() + b"\n")

            chunks: list[bytes] = []
            while True:
                chunk = s.recv(65536)
                if not chunk:
                    break
                chunks.append(chunk)
                if b"\n" in chunk:
                    break

            s.close()
            data = b"".join(chunks).decode().strip()
            if not data:
                return {"success": False, "error": "Empty response from daemon"}
            return json.loads(data)
        except socket.timeout:
            return {"success": False, "error": "IPC timeout — daemon may be busy"}
        except OSError as e:
            return {"success": False, "error": f"IPC connection failed: {e}"}
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid response from daemon"}


# =========================================================================
# IPC Proxy — returned by CLI _connect_or_fail when daemon is alive
# =========================================================================

class IPCDisplayProxy:
    """Proxy that routes DisplayDispatcher method calls through IPC."""

    connected = True

    @property
    def device_path(self) -> str | None:
        result = IPCClient.send("status")
        return result.get("lcd", {}).get("path")

    @property
    def resolution(self) -> tuple[int, int]:
        result = IPCClient.send("status")
        r = result.get("lcd", {}).get("resolution", [0, 0])
        return (r[0], r[1])

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _proxy(*args: Any, **kwargs: Any) -> dict:
            return IPCClient.send(f"display.{name}", list(args), kwargs)
        return _proxy


class IPCLEDProxy:
    """Proxy that routes LEDDispatcher method calls through IPC."""

    connected = True

    @property
    def status(self) -> str | None:
        result = IPCClient.send("status")
        if result.get("led", {}).get("connected"):
            return "Connected (via GUI daemon)"
        return None

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _proxy(*args: Any, **kwargs: Any) -> dict:
            return IPCClient.send(f"led.{name}", list(args), kwargs)
        return _proxy
