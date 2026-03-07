"""Device detection, selection, and frame sending service.

Pure Python, no Qt dependencies.
Handles USB device lifecycle — detection, handshake, frame encoding + send.
"""
from __future__ import annotations

import logging
import threading
from collections import deque
from typing import Any, Optional

from ..core.models import DetectedDevice, DeviceInfo, LCDDeviceConfig
from ..core.ports import DetectDevicesFn, GetProtocolFn, ProbeLedModelFn

log = logging.getLogger(__name__)


def _default_detect() -> list[DetectedDevice]:
    """Default detection — imports adapter lazily."""
    from ..adapters.device.detector import DeviceDetector
    return DeviceDetector.detect()


def _default_probe_led(*args: Any, **kwargs: Any) -> Any:
    """Default LED probe — imports adapter lazily."""
    from ..adapters.device.led import probe_led_model
    return probe_led_model(*args, **kwargs)


def _default_get_protocol(dev: Any) -> Any:
    """Default protocol factory — imports adapter lazily."""
    from ..adapters.device.factory import DeviceProtocolFactory
    return DeviceProtocolFactory.get_protocol(dev)


class DeviceService:
    """Device lifecycle: detect, select, handshake, send."""

    def __init__(
        self,
        detect_fn: DetectDevicesFn | None = None,
        probe_led_fn: ProbeLedModelFn | None = None,
        get_protocol: GetProtocolFn | None = None,
    ) -> None:
        self._detect_fn = detect_fn or _default_detect
        self._probe_led_fn = probe_led_fn or _default_probe_led
        self._get_protocol = get_protocol or _default_get_protocol
        self._devices: list[DeviceInfo] = []
        self._selected: DeviceInfo | None = None
        self._send_lock = threading.Lock()
        self._send_busy = False
        self.on_frame_sent: Any = None  # callback(image) — called after every send
        # Encoded frame cache — skip re-encoding when same image is sent repeatedly
        # (C#-matching 150ms refresh sends the same frame ~6x before metrics change)
        self._last_encode_id: int | None = None
        self._last_encode_data: bytes | None = None

        # Persistent send worker — avoids 30 thread creations/sec during video
        self._send_queue: deque[tuple[bytes, int, int]] = deque(maxlen=1)
        self._send_event = threading.Event()
        self._send_worker: threading.Thread | None = None
        self._send_shutdown = False

    # ── Detection ────────────────────────────────────────────────────

    def detect(self) -> list[DeviceInfo]:
        """Scan for all connected LCD/LED/Bulk devices via device_detector."""
        log.debug("DeviceService: scanning for devices...")
        raw: list[DetectedDevice] = []
        try:
            raw = self._detect_fn()
            self._devices = [
                DeviceInfo(
                    name=f"{d.vendor_name} {d.product_name}",
                    path=d.scsi_device or f"hid:{d.vid:04x}:{d.pid:04x}",
                    vendor=d.vendor_name,
                    product=d.product_name,
                    model=d.model,
                    vid=d.vid,
                    pid=d.pid,
                    device_index=i,
                    protocol=d.protocol,
                    device_type=d.device_type,
                    implementation=d.implementation,
                )
                for i, d in enumerate(raw)
            ]
        except ImportError:
            self._devices = []

        # Enrich LED devices with probe data (PM → style, model name).
        for d, raw_d in zip(self._devices, raw):
            if d.implementation == 'hid_led':
                self._enrich_led_device(d, raw_d.usb_path)

        log.info("DeviceService: found %d device(s)", len(self._devices))
        for d in self._devices:
            log.debug("  %s [%04X:%04X] %s res=%s",
                      d.name, d.vid, d.pid, d.protocol, d.resolution)

        return self._devices

    def _enrich_led_device(self, device: DeviceInfo, usb_path: str) -> None:
        """Probe LED device to resolve PM → style and model name.

        Without this, all 0416:8001 devices start as generic "LED_DIGITAL"
        which falls back to style 1 (AX120_DIGITAL, 30 LEDs) — wrong for
        multi-segment devices like PA120 (84), LF8 (93), etc.
        """
        try:
            info = self._probe_led_fn(device.vid, device.pid, usb_path=usb_path)
            if info and info.style:
                device.led_style_id = info.style.style_id
                device.model = info.style.model_name
                log.debug("LED probe: PM=%d → style=%d model=%s",
                          info.pm, info.style.style_id, info.style.model_name)
        except Exception as e:
            log.debug("LED probe failed: %s", e)

    # ── Selection ────────────────────────────────────────────────────

    def select(self, device: DeviceInfo) -> None:
        """Select a device."""
        self._selected = device

    @property
    def selected(self) -> DeviceInfo | None:
        """Currently selected device."""
        return self._selected

    @property
    def devices(self) -> list[DeviceInfo]:
        """List of detected devices."""
        return self._devices

    def scan_and_select(self, device_path: str | None = None) -> DeviceInfo | None:
        """Detect, select best match, and handshake.

        Selection priority: explicit path > saved preference > first device.
        Returns selected DeviceInfo or None if no device found.
        """
        self.detect()

        if device_path:
            match = next((d for d in self._devices if d.path == device_path), None)
            if match:
                self.select(match)
            elif self._devices:
                self.select(self._devices[0])
        elif not self._selected:
            from ..conf import Settings
            saved = Settings.get_selected_device()
            matched = False
            if saved:
                match = next((d for d in self._devices if d.path == saved), None)
                if match:
                    self.select(match)
                    matched = True
            if not matched and self._devices:
                self.select(self._devices[0])

        if self._selected:
            self._discover_resolution(self._selected)

        return self._selected

    def _discover_resolution(self, dev: DeviceInfo) -> None:
        """Run protocol handshake to discover resolution + FBL.

        Mutates dev in-place. No-op if resolution already known.
        """
        if dev.resolution != (0, 0):
            return
        try:
            protocol = self._get_protocol(dev)
            result = protocol.handshake()
            if result:
                res = getattr(result, 'resolution', None)
                if isinstance(res, tuple) and len(res) == 2 and res != (0, 0):
                    dev.resolution = res
                fbl = getattr(result, 'fbl', None) or getattr(result, 'model_id', None)
                if fbl:
                    dev.fbl_code = fbl
        except Exception:
            pass

    # ── Send ─────────────────────────────────────────────────────────

    def send_rgb565(self, data: bytes, width: int, height: int) -> bool:
        """Send pre-converted RGB565 bytes to selected device.

        Thread-safe: only one send at a time.
        """
        with self._send_lock:
            if self._send_busy:
                log.debug("send_rgb565: already busy, skipping")
                return False
            self._send_busy = True

        try:
            protocol = self._get_protocol(self._selected)
            success = protocol.send_image(data, width, height)
            return success
        except Exception as e:
            log.error("Device send error: %s", e)
            return False
        finally:
            with self._send_lock:
                self._send_busy = False

    def send_pil(self, image: Any, width: int, height: int) -> bool:
        """Encode image for device and send.

        Delegates encoding strategy to ImageService.encode_for_device() —
        JPEG for bulk/LY/HID-JPEG devices, RGB565 with pre-rotation for others.

        Caches encoded bytes by image id() — the 150ms refresh timer
        re-sends the same overlay frame ~6x per second between metric
        changes.  Cache hit skips the entire encode pipeline.
        """
        img_id = id(image)
        if img_id == self._last_encode_id and self._last_encode_data is not None:
            data = self._last_encode_data
        else:
            from .image import ImageService

            if self._selected:
                protocol, resolution, fbl, use_jpeg = self._selected.encoding_params
            else:
                protocol, resolution, fbl, use_jpeg = 'scsi', (320, 320), None, True

            data = ImageService.encode_for_device(image, protocol, resolution, fbl, use_jpeg)
            self._last_encode_id = img_id
            self._last_encode_data = data
        ok = self.send_rgb565(data, width, height)
        if ok and self.on_frame_sent:
            self.on_frame_sent(image)
        return ok

    def send_rgb565_async(self, data: bytes, width: int, height: int) -> None:
        """Queue RGB565 bytes for the persistent send worker.

        Latest-frame-wins: if a frame is already queued, it's replaced.
        The worker drains the queue one frame at a time.
        """
        self._ensure_send_worker()
        self._send_queue.append((data, width, height))
        self._send_event.set()

    def send_pil_async(self, image: Any, width: int, height: int) -> None:
        """Encode image and queue for the persistent send worker.

        Encoding runs inline (~0.5ms), then routes through the same
        persistent worker as ``send_rgb565_async`` — no per-call Thread.
        The send queue (maxlen=1) handles latest-frame-wins semantics —
        no need to guard with is_busy here.
        """
        img_id = id(image)
        if img_id == self._last_encode_id and self._last_encode_data is not None:
            data = self._last_encode_data
        else:
            from .image import ImageService

            if self._selected:
                protocol, resolution, fbl, use_jpeg = self._selected.encoding_params
            else:
                protocol, resolution, fbl, use_jpeg = 'scsi', (320, 320), None, True

            data = ImageService.encode_for_device(
                image, protocol, resolution, fbl, use_jpeg)
            self._last_encode_id = img_id
            self._last_encode_data = data

        self.send_rgb565_async(data, width, height)
        if self.on_frame_sent:
            self.on_frame_sent(image)

    def _ensure_send_worker(self) -> None:
        """Start the persistent send worker if not already running."""
        if self._send_worker and self._send_worker.is_alive():
            return
        self._send_shutdown = False
        self._send_worker = threading.Thread(
            target=self._send_worker_loop, daemon=True)
        self._send_worker.start()

    def _send_worker_loop(self) -> None:
        """Persistent worker — drains send queue, sleeps when empty."""
        while not self._send_shutdown:
            self._send_event.wait(timeout=1.0)
            self._send_event.clear()
            while self._send_queue:
                data, w, h = self._send_queue.popleft()
                self.send_rgb565(data, w, h)

    @property
    def is_busy(self) -> bool:
        """Check if a send is in progress."""
        with self._send_lock:
            return self._send_busy

    # ── LCD resolution detection ────────────────────────────────────

    @staticmethod
    def detect_lcd_resolution(config: LCDDeviceConfig, device_path: str,
                              verbose: bool = False) -> bool:
        """Auto-detect SCSI LCD resolution via poll byte[0] → fbl_to_resolution().

        Mutates config.width/height/fbl/resolution_detected on success.
        Resolution is now detected in ScsiDevice.handshake() directly,
        so this is only needed for pre-handshake discovery.
        """
        from ..adapters.device.scsi import ScsiDevice
        from ..core.models import fbl_to_resolution

        try:
            poll_header = ScsiDevice._build_header(0xF5, 0xE100)
            response = ScsiDevice._scsi_read(device_path, poll_header[:16], 0xE100)
            if not response:
                if verbose:
                    log.warning("Empty poll response from %s", device_path)
                return False

            fbl = response[0]
            width, height = fbl_to_resolution(fbl)
            config.width = width
            config.height = height
            config.fbl = fbl
            config.resolution_detected = True
            if verbose:
                log.info("Auto-detected resolution: %dx%d (FBL=%d)",
                         width, height, fbl)
            return True
        except Exception as e:
            if verbose:
                log.warning("Failed to auto-detect resolution: %s", e)
            return False

    # ── Protocol info ────────────────────────────────────────────────

    def get_protocol_info(self) -> Optional[Any]:
        """Get protocol/backend info for the selected device."""
        try:
            from ..adapters.device.factory import DeviceProtocolFactory  # infrastructure query
            return DeviceProtocolFactory.get_protocol_info(self._selected)
        except ImportError:
            return None
