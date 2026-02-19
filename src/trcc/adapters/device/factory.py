"""
Device Protocol Factory — unified API for SCSI, HID LCD, and HID LED devices.

Observer pattern: DeviceProtocol ABC defines the contract. ScsiProtocol,
HidProtocol, and LedProtocol are separate implementations with identical API.
Observers register callbacks for send_complete, error, and state changes.

The factory creates the right protocol class based on device PID/implementation.

Usage::

    from trcc.device_factory import DeviceProtocolFactory

    protocol = DeviceProtocolFactory.get_protocol(device_info)
    protocol.on_send_complete = lambda ok: print(f"sent: {ok}")
    protocol.on_error = lambda msg: print(f"err: {msg}")
    protocol.send_image(rgb565_data, width, height)      # LCD devices
    protocol.send_led_data(colors, is_on, True, 100)     # LED devices
"""

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from trcc.core.models import (
    DEVICE_TYPE_NAMES,
    LED_DEVICE_TYPE_NAME,
    PROTOCOL_NAMES,
    HandshakeResult,
)

log = logging.getLogger(__name__)

# Errno 16 = EBUSY — device interface claimed by another process (e.g. GUI).
_ERRNO_EBUSY = 16


def _is_ebusy(exc: Exception) -> bool:
    """Check if exception is a USB EBUSY (device in use by another process)."""
    # Walk the exception chain — EBUSY may be wrapped in RuntimeError
    cur: Optional[BaseException] = exc
    while cur is not None:
        if getattr(cur, "errno", None) == _ERRNO_EBUSY:
            return True
        cur = cur.__cause__
    return False


# =========================================================================
# DeviceProtocol ABC — the contract both SCSI and HID implement
# =========================================================================

class DeviceProtocol(ABC):
    """Abstract protocol interface for LCD device communication.

    Both ScsiProtocol and HidProtocol implement this identical API.
    The app codes against DeviceProtocol, never against a specific backend.

    Observer callbacks:
        on_send_complete(success: bool) — fired after each send attempt
        on_error(message: str) — fired on any protocol error
        on_state_changed(key: str, value) — fired on state transitions
    """

    def __init__(self):
        # Observer callbacks
        self.on_send_complete: Optional[Callable[[bool], None]] = None
        self.on_error: Optional[Callable[[str], None]] = None
        self.on_state_changed: Optional[Callable[[str, object], None]] = None
        # Handshake state — common to all protocols
        self._handshake_result: Optional[HandshakeResult] = None
        self._last_error: Optional[Exception] = None

    @abstractmethod
    def send_image(self, image_data: bytes, width: int, height: int) -> bool:
        """Send image data to the LCD device.

        Args:
            image_data: Pixel bytes (RGB565 for SCSI, JPEG for HID).
            width: Image width in pixels.
            height: Image height in pixels.

        Returns:
            True if the send succeeded.
        """

    @abstractmethod
    def close(self) -> None:
        """Release resources (USB transport, SCSI state, etc.)."""

    @abstractmethod
    def get_info(self) -> 'ProtocolInfo':
        """Get protocol/backend info for GUI display."""

    @property
    @abstractmethod
    def protocol_name(self) -> str:
        """Protocol identifier: 'scsi' or 'hid'."""

    @property
    @abstractmethod
    def is_available(self) -> bool:
        """Whether the required backend (sg_raw / pyusb / hidapi) is installed."""

    def send_led_data(
        self,
        led_colors: List[Tuple[int, int, int]],
        is_on: Optional[List[bool]] = None,
        global_on: bool = True,
        brightness: int = 100,
    ) -> bool:
        """Send LED color data to an RGB LED device.

        Default implementation returns False (not an LED device).
        Only LedProtocol overrides this.
        """
        return False

    def handshake(self) -> Optional[HandshakeResult]:
        """Template Method: perform handshake, cache result, handle errors.

        Subclasses implement _do_handshake() with protocol-specific logic.
        """
        try:
            result = self._do_handshake()
            self._handshake_result = result
            if result:
                self._cache_handshake(result)
            return result
        except Exception as e:
            if _is_ebusy(e):
                log.warning("%s in use by another process",
                            self._handshake_label)
            else:
                log.exception("%s handshake failed", self._handshake_label)
            self._last_error = e
            self._notify_error(f"{self._handshake_label} handshake failed: {e}")
            return None

    @abstractmethod
    def _do_handshake(self) -> Optional[HandshakeResult]:
        """Protocol-specific handshake logic. Called by handshake()."""

    @property
    def _handshake_label(self) -> str:
        """Human-readable label for error messages (e.g. 'HID 0416:5302')."""
        return self.protocol_name

    @property
    def handshake_info(self) -> Optional[HandshakeResult]:
        """Cached handshake result (None if not yet handshaked)."""
        return self._handshake_result

    @property
    def last_error(self) -> Optional[Exception]:
        """Last exception from handshake."""
        return self._last_error

    def _cache_handshake(self, result: HandshakeResult) -> None:
        """Save handshake result so `trcc report` can read it while GUI runs."""
        try:
            from trcc.conf import save_last_handshake
            save_last_handshake({
                "protocol": self.protocol_name,
                "model_id": result.model_id,
                "resolution": list(result.resolution) if result.resolution else None,
                "serial": result.serial,
                "raw": result.raw_response.hex() if result.raw_response else "",
            })
        except Exception:
            log.debug("Failed to cache handshake result", exc_info=True)

    @property
    def is_led(self) -> bool:
        """Whether this protocol is for LED control (not LCD)."""
        return False

    def _notify_send_complete(self, success: bool):
        """Notify observers of send result."""
        if self.on_send_complete:
            self.on_send_complete(success)

    def _notify_error(self, message: str):
        """Notify observers of an error."""
        if self.on_error:
            self.on_error(message)

    def _notify_state_changed(self, key: str, value: object):
        """Notify observers of a state change."""
        if self.on_state_changed:
            self.on_state_changed(key, value)

    def _guarded_send(self, label: str, fn: Callable[[], bool]) -> bool:
        """Execute a send operation with error handling and observer notification."""
        try:
            success = fn()
            self._notify_send_complete(success)
            return success
        except Exception as e:
            self._notify_error(f"{label} send failed: {e}")
            self._notify_send_complete(False)
            return False

    @staticmethod
    def _build_usb_protocol_info(
        protocol: str, device_type: int, protocol_display: str,
        device_type_display: str, transport_open: bool,
        *, pyusb_only: bool = False,
    ) -> 'ProtocolInfo':
        """Build ProtocolInfo for USB-transport protocols (HID, LED, Bulk)."""
        backends = DeviceProtocolFactory._get_hid_backends()
        if pyusb_only:
            active = "pyusb" if backends["pyusb"] else "none"
        elif backends["pyusb"]:
            active = "pyusb"
        elif backends["hidapi"]:
            active = "hidapi"
        else:
            active = "none"
        backends["sg_raw"] = False
        return ProtocolInfo(
            protocol=protocol, device_type=device_type,
            protocol_display=protocol_display,
            device_type_display=device_type_display,
            active_backend=active, backends=backends,
            transport_open=transport_open,
        )


# =========================================================================
# ScsiProtocol — SCSI/sg_raw implementation
# =========================================================================

class ScsiProtocol(DeviceProtocol):
    """LCD communication via SCSI protocol (sg_raw).

    Wraps scsi_device.py. Uses subprocess per send (stateless transport).
    """

    def __init__(self, device_path: str):
        super().__init__()
        self._path = device_path

    def _do_handshake(self) -> Optional[HandshakeResult]:
        """Poll SCSI device to discover FBL → resolution."""
        from .scsi import ScsiDevice
        dev = ScsiDevice(self._path)
        return dev.handshake()

    def send_image(self, image_data: bytes, width: int, height: int) -> bool:
        from .scsi import send_image_to_device
        log.debug("SCSI send: %d bytes to %s (%dx%d)", len(image_data), self._path, width, height)
        return self._guarded_send(
            f"SCSI ({self._path})",
            lambda: send_image_to_device(self._path, image_data, width, height),
        )

    def close(self) -> None:
        pass  # SCSI uses subprocess per call, nothing to release

    def get_info(self) -> 'ProtocolInfo':
        import shutil
        sg_raw = shutil.which("sg_raw") is not None
        return ProtocolInfo(
            protocol="scsi",
            device_type=1,
            protocol_display="SCSI (sg_raw)",
            device_type_display="SCSI RGB565",
            active_backend="sg_raw" if sg_raw else "none",
            backends={"sg_raw": sg_raw, "pyusb": False, "hidapi": False},
        )

    @property
    def protocol_name(self) -> str:
        return "scsi"

    @property
    def is_available(self) -> bool:
        import shutil
        return shutil.which("sg_raw") is not None

    def __repr__(self) -> str:
        return f"ScsiProtocol(path={self._path!r})"


# =========================================================================
# HidProtocol — HID/USB bulk implementation
# =========================================================================

class HidProtocol(DeviceProtocol):
    """LCD communication via HID USB bulk protocol (pyusb or hidapi).

    Wraps hid_device.py. Transport opens lazily on first send.
    Prefers pyusb, falls back to hidapi.
    """

    def __init__(self, vid: int, pid: int, device_type: int):
        super().__init__()
        self._vid = vid
        self._pid = pid
        self._device_type = device_type
        self._transport = None

    def _ensure_transport(self) -> None:
        """Lazily open USB transport on first use."""
        if self._transport is None:
            log.debug("Opening HID transport: %04X:%04X (type %d)", self._vid, self._pid, self._device_type)
            self._transport = self._create_transport()
            self._transport.open()
            self._notify_state_changed("transport_open", True)

    def _do_handshake(self) -> Optional[HandshakeResult]:
        """Open HID transport and perform type-specific handshake."""
        self._ensure_transport()
        assert self._transport is not None

        from .hid import HidDeviceType2, HidDeviceType3
        if self._device_type == 2:
            handler = HidDeviceType2(self._transport)
        elif self._device_type == 3:
            handler = HidDeviceType3(self._transport)
        else:
            log.warning("Unknown HID device type: %d", self._device_type)
            return None

        result = handler.handshake()
        if result:
            log.info("HID handshake OK: PM=%s, FBL=%s, resolution=%s",
                     result.mode_byte_1, result.fbl, result.resolution)
        else:
            log.warning("HID handshake returned None")
        self._notify_state_changed("handshake_complete", True)
        return result

    @property
    def _handshake_label(self) -> str:
        return f"HID {self._vid:04X}:{self._pid:04X} type {self._device_type}"

    def send_image(self, image_data: bytes, width: int, height: int) -> bool:
        def _do_send() -> bool:
            from .hid import HidDeviceManager
            self._ensure_transport()
            assert self._transport is not None
            return HidDeviceManager.send_image(
                self._transport, image_data, self._device_type
            )
        return self._guarded_send("HID", _do_send)

    def _close_transport(self) -> None:
        """Close USB transport and notify observers."""
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
            self._notify_state_changed("transport_open", False)

    def close(self) -> None:
        self._close_transport()

    def get_info(self) -> 'ProtocolInfo':
        return self._build_usb_protocol_info(
            "hid", self._device_type, "HID (USB bulk)",
            DEVICE_TYPE_NAMES.get(self._device_type, f"Type {self._device_type}"),
            self._transport is not None and getattr(self._transport, 'is_open', False),
        )

    def _create_transport(self):
        """Create the best available USB transport."""
        return DeviceProtocolFactory.create_usb_transport(self._vid, self._pid)

    @property
    def protocol_name(self) -> str:
        return "hid"

    @property
    def is_available(self) -> bool:
        backends = DeviceProtocolFactory._get_hid_backends()
        return backends["pyusb"] or backends["hidapi"]

    def __repr__(self) -> str:
        return (
            f"HidProtocol(vid=0x{self._vid:04x}, pid=0x{self._pid:04x}, "
            f"type={self._device_type})"
        )


# =========================================================================
# LedProtocol — HID LED RGB controller
# =========================================================================

class LedProtocol(DeviceProtocol):
    """LED device communication via HID 64-byte reports (FormLED equivalent).

    Unlike HidProtocol (LCD images), LedProtocol sends LED color arrays
    for RGB LED effects. Uses the same UsbTransport as HidProtocol.
    """

    def __init__(self, vid: int, pid: int):
        super().__init__()
        self._vid = vid
        self._pid = pid
        self._transport = None
        self._sender = None

    def send_image(self, image_data: bytes, width: int, height: int) -> bool:
        """No-op — LED devices don't display images."""
        return False

    def send_led_data(
        self,
        led_colors: List[Tuple[int, int, int]],
        is_on: Optional[List[bool]] = None,
        global_on: bool = True,
        brightness: int = 100,
    ) -> bool:
        """Send LED color data to the device.

        Args:
            led_colors: List of (R, G, B) tuples, one per LED.
            is_on: Per-LED on/off state. None means all on.
            global_on: Global on/off switch.
            brightness: Global brightness 0-100.

        Returns:
            True if the send succeeded.
        """
        def _do_send() -> bool:
            self._ensure_transport()
            assert self._transport is not None

            if self._sender is None:
                from .led import LedHidSender
                self._sender = LedHidSender(self._transport)

            from .led import LedPacketBuilder, remap_led_colors

            # Remap logical LED order → physical wire order (per-style).
            hr = self._handshake_result
            style = getattr(hr, 'style', None) if hr else None
            remapped = remap_led_colors(led_colors, style.style_id) if style else led_colors

            packet = LedPacketBuilder.build_led_packet(
                remapped, is_on, global_on, brightness
            )
            return self._sender.send_led_data(packet)
        return self._guarded_send("LED", _do_send)

    def _ensure_transport(self) -> None:
        """Lazily open USB transport on first use."""
        if self._transport is None:
            self._transport = self._create_transport()
            self._transport.open()
            self._notify_state_changed("transport_open", True)

    def _do_handshake(self) -> Optional[HandshakeResult]:
        """LED handshake — cached after first call (firmware ignores re-handshakes)."""
        if self._handshake_result is not None:
            return self._handshake_result

        self._ensure_transport()
        assert self._transport is not None

        if self._sender is None:
            from .led import LedHidSender
            self._sender = LedHidSender(self._transport)

        result = self._sender.handshake()
        self._notify_state_changed("handshake_complete", True)
        return result

    @property
    def _handshake_label(self) -> str:
        return f"LED {self._vid:04X}:{self._pid:04X}"

    def _close_transport(self) -> None:
        """Close USB transport and notify observers."""
        if self._transport is not None:
            try:
                self._transport.close()
            except Exception:
                pass
            self._transport = None
            self._notify_state_changed("transport_open", False)

    def close(self) -> None:
        self._close_transport()
        self._sender = None

    def get_info(self) -> 'ProtocolInfo':
        return self._build_usb_protocol_info(
            "led", 1, "LED (HID 64-byte)", "RGB LED Controller",
            self._transport is not None and getattr(self._transport, 'is_open', False),
        )

    def _create_transport(self):
        """Create the best available USB transport."""
        return DeviceProtocolFactory.create_usb_transport(self._vid, self._pid)

    @property
    def protocol_name(self) -> str:
        return "led"

    @property
    def is_available(self) -> bool:
        backends = DeviceProtocolFactory._get_hid_backends()
        return backends["pyusb"] or backends["hidapi"]

    @property
    def is_led(self) -> bool:
        return True

    def __repr__(self) -> str:
        return f"LedProtocol(vid=0x{self._vid:04x}, pid=0x{self._pid:04x})"


# =========================================================================
# BulkProtocol — raw USB bulk (USBLCDNew) implementation
# =========================================================================

class BulkProtocol(DeviceProtocol):
    """LCD communication via raw USB bulk (bInterfaceClass=255).

    Wraps bulk_device.BulkDevice.  Used for GrandVision / Mjolnir Vision
    devices (87AD:70DB) that use the USBLCDNew ThreadSendDeviceData protocol.
    """

    def __init__(self, vid: int, pid: int):
        super().__init__()
        self._vid = vid
        self._pid = pid
        self._device: Optional[Any] = None  # BulkDevice (lazy import)

    def _ensure_device(self):
        """Lazily create and handshake the bulk device."""
        if self._device is None:
            from .bulk import BulkDevice
            self._device = BulkDevice(self._vid, self._pid)
            result = self._device.handshake()
            self._handshake_result = result
            if result.resolution:
                self._notify_state_changed("handshake_complete", True)
                log.info("Bulk handshake OK: PM=%d, resolution=%s",
                         result.model_id, result.resolution)
            else:
                log.warning("Bulk handshake: no resolution detected")

    def _do_handshake(self) -> Optional[HandshakeResult]:
        """Create bulk device and perform handshake."""
        self._ensure_device()
        return self._handshake_result

    @property
    def _handshake_label(self) -> str:
        return f"Bulk {self._vid:04X}:{self._pid:04X}"

    def send_image(self, image_data: bytes, width: int, height: int) -> bool:
        def _do_send() -> bool:
            self._ensure_device()
            assert self._device is not None
            return self._device.send_frame(image_data)
        return self._guarded_send("Bulk", _do_send)

    def close(self) -> None:
        if self._device is not None:
            try:
                self._device.close()
            except Exception:
                pass
            self._device = None

    def get_info(self) -> 'ProtocolInfo':
        return self._build_usb_protocol_info(
            "bulk", 4, "USB Bulk (USBLCDNew)", "Raw USB Bulk LCD",
            self._device is not None, pyusb_only=True,
        )

    @property
    def protocol_name(self) -> str:
        return "bulk"

    @property
    def is_available(self) -> bool:
        backends = DeviceProtocolFactory._get_hid_backends()
        return backends["pyusb"]

    def __repr__(self) -> str:
        return f"BulkProtocol(vid=0x{self._vid:04x}, pid=0x{self._pid:04x})"


# =========================================================================
# Factory
# =========================================================================

class DeviceProtocolFactory:
    """Factory that creates and caches protocol instances.

    Protocols are cached by device identity so USB transports stay open
    across successive frame sends. SCSI is the default/primary protocol.

    Usage::

        protocol = DeviceProtocolFactory.get_protocol(device_info)
        protocol.on_send_complete = lambda ok: update_ui(ok)
        protocol.send_image(data, w, h)

        # When done:
        DeviceProtocolFactory.close_all()
    """

    _protocols: Dict[str, DeviceProtocol] = {}

    @classmethod
    def _device_key(cls, device_info) -> str:
        """Build a cache key from device info."""
        vid = getattr(device_info, 'vid', 0)
        pid = getattr(device_info, 'pid', 0)
        path = getattr(device_info, 'path', '')
        return f"{vid:04x}_{pid:04x}_{path}"

    @classmethod
    def create_protocol(cls, device_info) -> DeviceProtocol:
        """Create a new protocol for the given device (not cached).

        Routes to ScsiProtocol or HidProtocol based on device_info.protocol.
        SCSI is the default when protocol is unset.

        Args:
            device_info: Object with protocol, vid, pid, path, device_type.

        Returns:
            DeviceProtocol subclass instance.

        Raises:
            ValueError: If protocol is unknown.
        """
        protocol = getattr(device_info, 'protocol', 'scsi')
        implementation = getattr(device_info, 'implementation', '')

        if protocol == 'scsi':
            log.info("Creating ScsiProtocol for %s", device_info.path)
            return ScsiProtocol(device_info.path)
        elif protocol == 'bulk':
            log.info("Creating BulkProtocol for %04X:%04X",
                     device_info.vid, device_info.pid)
            return BulkProtocol(
                vid=device_info.vid,
                pid=device_info.pid,
            )
        elif protocol == 'hid':
            # LED devices use a different protocol than LCD HID devices
            if implementation == 'hid_led':
                log.info("Creating LedProtocol for %04X:%04X", device_info.vid, device_info.pid)
                return LedProtocol(
                    vid=device_info.vid,
                    pid=device_info.pid,
                )
            log.info("Creating HidProtocol for %04X:%04X (type %d)",
                     device_info.vid, device_info.pid, getattr(device_info, 'device_type', 2))
            return HidProtocol(
                vid=device_info.vid,
                pid=device_info.pid,
                device_type=getattr(device_info, 'device_type', 2),
            )
        else:
            raise ValueError(f"Unknown protocol: {protocol!r}")

    @classmethod
    def get_protocol(cls, device_info) -> DeviceProtocol:
        """Get or create a cached protocol for the device.

        Args:
            device_info: Object with protocol, vid, pid, path, device_type.

        Returns:
            Cached DeviceProtocol instance.
        """
        key = cls._device_key(device_info)
        if key not in cls._protocols:
            cls._protocols[key] = cls.create_protocol(device_info)
        return cls._protocols[key]

    @classmethod
    def remove_protocol(cls, device_info) -> None:
        """Remove and close a cached protocol."""
        key = cls._device_key(device_info)
        proto = cls._protocols.pop(key, None)
        if proto is not None:
            proto.close()

    @classmethod
    def close_all(cls) -> None:
        """Close all cached protocols and clear the cache."""
        for proto in cls._protocols.values():
            try:
                proto.close()
            except Exception:
                pass
        cls._protocols.clear()

    @classmethod
    def get_cached_count(cls) -> int:
        """Number of cached protocols (for testing)."""
        return len(cls._protocols)

    # =================================================================
    # USB transport + backend helpers
    # =================================================================

    @staticmethod
    def _check_sg_raw() -> bool:
        """Check if sg_raw is available on the system."""
        import shutil
        return shutil.which("sg_raw") is not None

    @staticmethod
    def create_usb_transport(vid: int, pid: int):
        """Create the best available USB transport (pyusb preferred, hidapi fallback)."""
        from .hid import HIDAPI_AVAILABLE, PYUSB_AVAILABLE
        if PYUSB_AVAILABLE:
            from .hid import PyUsbTransport
            return PyUsbTransport(vid, pid)
        elif HIDAPI_AVAILABLE:
            from .hid import HidApiTransport
            return HidApiTransport(vid, pid)
        else:
            raise ImportError(
                "No USB backend available. Install pyusb or hidapi:\n"
                "  pip install pyusb   (+ apt install libusb-1.0-0)\n"
                "  pip install hidapi  (+ apt install libhidapi-dev)"
            )

    @staticmethod
    def _get_hid_backends() -> Dict[str, bool]:
        """Check HID backend availability."""
        try:
            from .hid import HIDAPI_AVAILABLE, PYUSB_AVAILABLE
            return {"pyusb": PYUSB_AVAILABLE, "hidapi": HIDAPI_AVAILABLE}
        except ImportError:
            return {"pyusb": False, "hidapi": False}

    @classmethod
    def get_backend_availability(cls) -> Dict[str, bool]:
        """Check which USB/SCSI backends are installed.

        Returns dict with keys: sg_raw, pyusb, hidapi — each True/False.
        """
        hid = cls._get_hid_backends()
        return {
            "sg_raw": cls._check_sg_raw(),
            "pyusb": hid["pyusb"],
            "hidapi": hid["hidapi"],
        }

    @classmethod
    def get_protocol_info(cls, device_info=None) -> 'ProtocolInfo':
        """Get protocol/backend info for a device (or system defaults).

        If a cached protocol exists for this device, delegates to its get_info().
        Otherwise builds ProtocolInfo from backend availability.

        Args:
            device_info: DeviceInfo object (or None for system-level info).

        Returns:
            ProtocolInfo with all fields populated.
        """
        if device_info is None:
            backends = cls.get_backend_availability()
            return ProtocolInfo(
                protocol="none",
                device_type=0,
                protocol_display="No device",
                device_type_display="",
                active_backend="none",
                backends=backends,
            )

        # If there's a cached protocol, ask it directly
        key = cls._device_key(device_info)
        proto = cls._protocols.get(key)
        if proto is not None:
            return proto.get_info()

        # No cached protocol — build info from scratch
        backends = cls.get_backend_availability()
        protocol = getattr(device_info, 'protocol', 'scsi')
        device_type = getattr(device_info, 'device_type', 1)

        implementation = getattr(device_info, 'implementation', '')

        if protocol == "scsi":
            active = "sg_raw" if backends["sg_raw"] else "none"
        elif protocol == "bulk":
            active = "pyusb" if backends["pyusb"] else "none"
        elif protocol == "hid":
            if backends["pyusb"]:
                active = "pyusb"
            elif backends["hidapi"]:
                active = "hidapi"
            else:
                active = "none"
        else:
            active = "none"

        # LED devices report as "led" protocol
        if implementation == "hid_led":
            return ProtocolInfo(
                protocol="led",
                device_type=1,
                protocol_display=PROTOCOL_NAMES.get("led", "LED"),
                device_type_display=LED_DEVICE_TYPE_NAME,
                active_backend=active,
                backends=backends,
                transport_open=False,
            )

        return ProtocolInfo(
            protocol=protocol,
            device_type=device_type,
            protocol_display=PROTOCOL_NAMES.get(protocol, protocol),
            device_type_display=DEVICE_TYPE_NAMES.get(device_type, f"Type {device_type}"),
            active_backend=active,
            backends=backends,
            transport_open=False,
        )


# =========================================================================
# Protocol Info API — for GUI to query device/backend state
# =========================================================================

# Domain data re-exported from core.models (canonical location):
# PROTOCOL_NAMES, DEVICE_TYPE_NAMES, LED_DEVICE_TYPE_NAME


@dataclass
class ProtocolInfo:
    """Protocol and backend info for a device — returned to the GUI.

    Usage in GUI::

        info = DeviceProtocolFactory.get_protocol_info(device)
        label.setText(f"{info.protocol_display} via {info.active_backend}")
    """
    protocol: str = "scsi"
    device_type: int = 1
    protocol_display: str = ""
    device_type_display: str = ""
    active_backend: str = ""
    backends: Dict[str, bool] = field(default_factory=dict)
    transport_open: bool = False

    @property
    def is_scsi(self) -> bool:
        return self.protocol == "scsi"

    @property
    def is_hid(self) -> bool:
        return self.protocol == "hid"

    @property
    def is_led(self) -> bool:
        return self.protocol == "led"

    @property
    def has_backend(self) -> bool:
        """Whether at least one usable backend is available."""
        if self.protocol == "scsi":
            return self.backends.get("sg_raw", False)
        return self.backends.get("pyusb", False) or self.backends.get("hidapi", False)
