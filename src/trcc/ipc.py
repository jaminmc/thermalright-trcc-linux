"""IPC server/client and proxies for single-device-owner pattern.

When another trcc instance owns the device, callers route through it
instead of touching USB directly. Two transport types:

  - IPCTransport — Unix domain socket to GUI
  - APITransport — HTTP to ``trcc serve``

Detection: ``core.instance.find_active()`` checks GUI socket, then API
health endpoint, returns InstanceKind or None.

Protocol (IPC):
  Request:  {"cmd": "display.send_color", "args": [255, 0, 0], "kwargs": {}}\n
  Response: {"success": true, "message": "..."}\n
"""
from __future__ import annotations

import json
import logging
import os
import socket
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from PySide6.QtCore import QBuffer, QByteArray, QIODevice

log = logging.getLogger(__name__)

# Socket path: same dir as the instance lock file
_SOCK_NAME = "trcc-linux.sock"


def _socket_path() -> Path:
    return Path(os.environ.get("XDG_RUNTIME_DIR", "/tmp")) / _SOCK_NAME


# Non-serializable keys to strip from dispatcher results (QImage, etc.)
_NON_SERIALIZABLE = frozenset({"image", "colors"})

# SOLID routing: display methods route through LCDDevice composed capabilities.
# Format: "method_name" -> ("capability", "method") or None for flat on device.
_DISPLAY_ROUTES: dict[str, tuple[str, str]] = {
    "send_image":           ("frame", "send_image"),
    "send_color":           ("frame", "send_color"),
    "reset":                ("frame", "reset"),
    "set_brightness":       ("settings", "set_brightness"),
    "set_rotation":         ("settings", "set_rotation"),
    "set_split_mode":       ("settings", "set_split_mode"),
    "load_theme_by_name":   ("theme", "load_theme_by_name"),
    "load_mask_standalone":  ("overlay", "load_mask_standalone"),
}

# LED methods are flat on LEDDevice -- whitelist only.
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
    """Unix socket IPC server -- listens for CLI requests, routes to dispatchers.

    Integrates with Qt event loop via QSocketNotifier on the listening fd.
    Each client is handled synchronously (accept -> read -> dispatch -> respond
    -> close) in a single callback, which is safe because requests are small
    and local.
    """

    def __init__(self, display_dispatcher: Any, led_dispatcher: Any):
        self._display = display_dispatcher
        self._led = led_dispatcher
        self._sock: socket.socket | None = None
        self._notifier: Any = None  # QSocketNotifier
        self._current_frame: Any = None  # Last frame sent to LCD (QImage)

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
        """Bind and listen on Unix domain socket (Unix only)."""
        if not hasattr(socket, 'AF_UNIX'):
            log.debug("IPC server skipped -- AF_UNIX not available (Windows)")
            return

        path = _socket_path()
        if path.exists():
            path.unlink()

        self._sock = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
        self._sock.setblocking(False)
        self._sock.bind(str(path))
        self._sock.listen(5)
        os.chmod(str(path), 0o600)

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

        match cmd.split(".", 1):
            case ["status"]:
                return self._status()
            case ["display", method]:
                return self._dispatch_display(method, cmd, args, kwargs)
            case ["led", method]:
                return self._dispatch_led(method, cmd, args, kwargs)
            case _:
                return {"success": False, "error": f"Invalid command: {cmd}"}

    def _dispatch_display(self, method: str, cmd: str,
                          args: list, kwargs: dict) -> dict:
        """Route display sub-commands."""
        match method:
            case "status":
                return self._display_status()
            case "get_frame":
                return self._get_frame()
            case "pause":
                return self._pause_display()
            case "resume":
                return self._resume_display()
            case _ if (route := _DISPLAY_ROUTES.get(method)):
                if not self._display or not self._display.connected:
                    return {"success": False, "error": "No LCD device connected"}
                cap_name, cap_method = route
                cap = getattr(self._display, cap_name)
                return _sanitize(getattr(cap, cap_method)(*args, **kwargs))
            case _:
                return {"success": False, "error": f"Unknown command: {cmd}"}

    def _dispatch_led(self, method: str, cmd: str,
                      args: list, kwargs: dict) -> dict:
        """Route LED sub-commands."""
        match method:
            case "status":
                return self._led_status()
            case _ if method not in _LED_METHODS:
                return {"success": False, "error": f"Unknown command: {cmd}"}
            case _:
                if not self._led or not self._led.connected:
                    return {"success": False, "error": "No LED device connected"}
                return _sanitize(getattr(self._led, method)(*args, **kwargs))

    def _display_status(self) -> dict:
        """Return flat LCD device status."""
        if not self._display or not self._display.connected:
            return {"success": True, "connected": False}
        dev = self._display.device_info
        return {
            "success": True,
            "connected": True,
            "path": dev.path,
            "resolution": list(dev.resolution),
            "protocol": dev.protocol,
        }

    def _led_status(self) -> dict:
        """Return flat LED device status."""
        if not self._led or not self._led.connected:
            return {"success": True, "connected": False}
        return {"success": True, "connected": True}

    def _pause_display(self) -> dict:
        """Pause LCD frame sending (for exclusive device access)."""
        if not self._display or not self._display.connected:
            return {"success": True, "message": "No LCD connected"}
        self._display.auto_send = False
        log.info("IPC: display paused (auto_send=False)")
        return {"success": True, "message": "Display paused"}

    def _resume_display(self) -> dict:
        """Resume LCD frame sending after pause."""
        if not self._display or not self._display.connected:
            return {"success": True, "message": "No LCD connected"}
        self._display.auto_send = True
        log.info("IPC: display resumed (auto_send=True)")
        return {"success": True, "message": "Display resumed"}

    def _get_frame(self) -> dict:
        """Return the current LCD frame as base64 JPEG."""
        import base64

        if self._current_frame is None:
            return {"success": False, "error": "No frame available"}

        frame = self._current_frame

        buf = QByteArray()
        qbuf = QBuffer(buf)
        qbuf.open(QIODevice.OpenModeFlag.WriteOnly)
        frame.save(qbuf, 'jpeg', 85)  # type: ignore[call-overload]
        qbuf.close()
        jpeg_data = bytes(buf.data())

        return {
            "success": True,
            "frame": base64.b64encode(jpeg_data).decode("ascii"),
        }

    def _status(self) -> dict:
        """Return combined device status (legacy — kept for backward compat)."""
        result: dict[str, Any] = {"success": True}
        if self._display and self._display.connected:
            dev = self._display.device_info
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
# Transport ABC + implementations
# =========================================================================

class Transport(ABC):
    """Abstract transport for routing device commands to an owning instance."""

    is_ipc: bool = False

    @abstractmethod
    def send(self, cmd: str, args: list | None = None,
             kwargs: dict | None = None) -> dict:
        """Send a command and return the result dict."""


class IPCTransport(Transport):
    """Unix domain socket transport -- routes commands to the GUI daemon."""

    is_ipc: bool = True

    @staticmethod
    def available() -> bool:
        """Check if the IPC daemon is running and accepting connections."""
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

    def send(self, cmd: str, args: list | None = None,
             kwargs: dict | None = None) -> dict:
        if not hasattr(socket, 'AF_UNIX'):
            return {"success": False, "error": "IPC not available on Windows"}
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
            return {"success": False, "error": "IPC timeout -- daemon may be busy"}
        except OSError as e:
            return {"success": False, "error": f"IPC connection failed: {e}"}
        except json.JSONDecodeError:
            return {"success": False, "error": "Invalid response from daemon"}


class _APIClient:
    """Minimal HTTP client for routing through a running API server."""

    def __init__(self, port: int | None = None) -> None:
        from .core.instance import DEFAULT_API_PORT
        self._port = port or DEFAULT_API_PORT

    def _request(self, method: str, path: str,
                 body: dict | None = None) -> dict:
        """Send HTTP request, return parsed JSON response."""
        import http.client

        try:
            conn = http.client.HTTPConnection("127.0.0.1", self._port,
                                              timeout=10)
            headers = {"Content-Type": "application/json"}
            payload = json.dumps(body).encode() if body else None
            conn.request(method, path, body=payload, headers=headers)
            resp = conn.getresponse()
            data = resp.read().decode()
            conn.close()
            if resp.status >= 400:
                result = json.loads(data) if data else {}
                detail = result.get("detail", data)
                return {"success": False, "error": detail}
            return {"success": True, **json.loads(data)} if data else {"success": True}
        except (OSError, json.JSONDecodeError) as e:
            return {"success": False, "error": f"API connection failed: {e}"}


# Method -> (HTTP method, URL path, body builder)
_LCD_ROUTES: dict[str, tuple[str, str, Any]] = {
    "send_color":           ("POST", "/display/color",
                             lambda r, g, b: {"hex": f"{r:02x}{g:02x}{b:02x}"}),
    "set_brightness":       ("POST", "/display/brightness",
                             lambda level: {"level": level}),
    "set_rotation":         ("POST", "/display/rotation",
                             lambda angle: {"angle": angle}),
    "set_split_mode":       ("POST", "/display/split",
                             lambda mode: {"mode": mode}),
    "reset":                ("POST", "/display/reset", lambda: None),
    "load_theme_by_name":   ("POST", "/themes/load",
                             lambda name, w=0, h=0: {
                                 "name": name,
                                 **({"resolution": f"{w}x{h}"} if w and h else {}),
                             }),
    "load_mask_standalone":  ("POST", "/display/mask",
                              lambda path: {"path": path}),
    "status":               ("GET", "/display/status", lambda: None),
}

_LED_ROUTES: dict[str, tuple[str, str, Any]] = {
    "set_color":        ("POST", "/led/color",
                         lambda r, g, b: {"hex": f"{r:02x}{g:02x}{b:02x}"}),
    "set_mode":         ("POST", "/led/mode", lambda mode: {"mode": mode}),
    "set_brightness":   ("POST", "/led/brightness",
                         lambda level: {"level": level}),
    "off":              ("POST", "/led/off", lambda: None),
    "set_sensor_source": ("POST", "/led/sensor",
                          lambda source: {"source": source}),
    "set_clock_format":  ("POST", "/led/clock",
                          lambda is_24h: {"is_24h": is_24h}),
    "set_temp_unit":     ("POST", "/led/temp-unit",
                          lambda unit: {"unit": unit}),
    "status":            ("GET", "/led/status", lambda: None),
}


class APITransport(Transport):
    """HTTP transport -- routes commands to the ``trcc serve`` API."""

    def __init__(self, routes: dict[str, tuple[str, str, Any]],
                 port: int | None = None) -> None:
        self._client = _APIClient(port)
        self._routes = routes

    def send(self, cmd: str, args: list | None = None,
             kwargs: dict | None = None) -> dict:
        # Strip domain prefix: "display.send_color" -> "send_color"
        _, _, method = cmd.rpartition(".")
        route = self._routes.get(method)
        if route:
            http_method, path, body_fn = route
            body = body_fn(*(args or []), **(kwargs or {})) if body_fn else None
            return self._client._request(http_method, path, body)
        return {"success": False,
                "error": f"No API route for '{cmd}'"}


# =========================================================================
# Unified proxies
# =========================================================================

class DeviceProxy:
    """Base proxy — routes method calls through a Transport to the owning instance."""

    connected = True

    def __init__(self, transport: Transport, prefix: str) -> None:
        self._transport = transport
        self._prefix = prefix

    @property
    def is_ipc(self) -> bool:
        return self._transport.is_ipc

    def __getattr__(self, name: str) -> Any:
        if name.startswith("_"):
            raise AttributeError(name)

        def _proxy(*args: Any, **kwargs: Any) -> dict:
            return self._transport.send(f"{self._prefix}.{name}", list(args), kwargs)
        return _proxy


class DisplayProxy(DeviceProxy):
    """LCD proxy — adds device_path and resolution properties."""

    def __init__(self, transport: Transport) -> None:
        super().__init__(transport, "display")

    @property
    def device_path(self) -> str | None:
        result = self._transport.send("display.status")
        return result.get("path")

    @property
    def resolution(self) -> tuple[int, int]:
        result = self._transport.send("display.status")
        r = result.get("resolution", [0, 0])
        return (r[0], r[1])


class LEDProxy(DeviceProxy):
    """LED proxy — adds status property."""

    def __init__(self, transport: Transport) -> None:
        super().__init__(transport, "led")

    @property
    def status(self) -> str | None:
        result = self._transport.send("led.status")
        if result.get("connected"):
            kind = "GUI daemon" if self._transport.is_ipc else "API server"
            return f"Connected (via {kind})"
        return None


# =========================================================================
# Proxy factories -- injected into core devices via DI
# =========================================================================

def _create_proxy(kind: Any, proxy_cls: type,
                  routes: dict) -> DeviceProxy:
    """Create a device proxy for the given InstanceKind + transport."""
    from trcc.core.instance import InstanceKind

    if kind == InstanceKind.GUI:
        return proxy_cls(IPCTransport())
    return proxy_cls(APITransport(routes))


def create_lcd_proxy(kind: Any) -> DisplayProxy:
    """Create an LCD proxy. Injected into Device as proxy_factory_fn."""
    return _create_proxy(kind, DisplayProxy, _LCD_ROUTES)  # type: ignore[return-value]


def create_led_proxy(kind: Any) -> LEDProxy:
    """Create an LED proxy. Injected into Device as proxy_factory_fn."""
    return _create_proxy(kind, LEDProxy, _LED_ROUTES)  # type: ignore[return-value]
