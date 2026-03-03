"""Device detection, selection, and frame sending service.

Pure Python, no Qt dependencies.
Absorbed from DeviceController + DeviceModel in controllers.py/models.py.
"""
from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Optional

from ..core.models import DeviceInfo, LCDDeviceConfig

log = logging.getLogger(__name__)


class DeviceService:
    """Device lifecycle: detect, select, handshake, send."""

    def __init__(self) -> None:
        self._devices: list[DeviceInfo] = []
        self._selected: DeviceInfo | None = None
        self._send_lock = threading.Lock()
        self._send_busy = False
        self.on_frame_sent: Any = None  # callback(PIL Image) — called after every send_pil
        self._send_queue: queue.Queue = queue.Queue(maxsize=1)
        self._send_worker: threading.Thread | None = None

    # ── Detection ────────────────────────────────────────────────────

    def detect(self) -> list[DeviceInfo]:
        """Scan for all connected LCD/LED/Bulk devices via device_detector."""
        log.debug("DeviceService: scanning for devices...")
        try:
            from ..adapters.device.detector import DetectedDevice, DeviceDetector

            raw: list[DetectedDevice] = DeviceDetector.detect()
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

        # Auto-select first device
        if self._devices and not self._selected:
            self._selected = self._devices[0]

        return self._devices

    @staticmethod
    def _enrich_led_device(device: DeviceInfo, usb_path: str) -> None:
        """Probe LED device to resolve PM → style and model name.

        Without this, all 0416:8001 devices start as generic "LED_DIGITAL"
        which falls back to style 1 (AX120_DIGITAL, 30 LEDs) — wrong for
        multi-segment devices like PA120 (84), LF8 (93), etc.
        """
        try:
            from ..adapters.device.led import probe_led_model
            info = probe_led_model(device.vid, device.pid, usb_path=usb_path)
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

    # ── Handshake ────────────────────────────────────────────────────

    def handshake(self, device: DeviceInfo) -> Any:
        """Run protocol handshake for HID/Bulk devices.

        Returns:
            HandshakeResult or None on error/import failure.
        """
        try:
            from ..adapters.device.factory import DeviceProtocolFactory

            protocol = DeviceProtocolFactory.get_protocol(device)
            if hasattr(protocol, 'handshake'):
                return protocol.handshake()
        except Exception as e:
            log.error("Handshake error: %s", e)
        return None

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
            from ..adapters.device.factory import DeviceProtocolFactory

            log.debug("send_rgb565: device=%s protocol=%s %dx%d (%d bytes)",
                      self._selected.path if self._selected else 'None',
                      self._selected.protocol if self._selected else 'None',
                      width, height, len(data))
            protocol = DeviceProtocolFactory.get_protocol(self._selected)
            success = protocol.send_image(data, width, height)
            log.debug("send_rgb565: send_image returned %s", success)
            return success
        except Exception as e:
            log.error("Device send error: %s", e)
            return False
        finally:
            with self._send_lock:
                self._send_busy = False

    def send_image(self, image: Any, width: int, height: int,
                   byte_order: str = '>') -> bool:
        """Convert PIL Image to RGB565 and send to device."""
        from .image import ImageService

        rgb565 = ImageService.to_rgb565(image, byte_order)
        return self.send_rgb565(rgb565, width, height)

    def send_pil(self, image: Any, width: int, height: int) -> bool:
        """Encode PIL Image for device and send.

        Delegates encoding strategy to ImageService.encode_for_device() —
        JPEG for bulk/LY/HID-JPEG devices, RGB565 with pre-rotation for others.
        """
        from .image import ImageService

        device = self._selected
        protocol = device.protocol if device else 'scsi'
        resolution = device.resolution if device else (320, 320)
        fbl = device.fbl_code if device else None
        use_jpeg = device.use_jpeg if device else True

        data = ImageService.encode_for_device(image, protocol, resolution, fbl, use_jpeg)
        ok = self.send_rgb565(data, width, height)
        if ok and self.on_frame_sent:
            self.on_frame_sent(image)
        return ok

    def send_rgb565_async(self, data: bytes, width: int, height: int) -> None:
        """Send RGB565 bytes via persistent worker thread. Drops frame if busy."""
        log.debug("send_rgb565_async: queueing (%d bytes)", len(data))
        self._submit(lambda: self.send_rgb565(data, width, height))

    def send_pil_async(self, image: Any, width: int, height: int) -> None:
        """Encode + send PIL Image via persistent worker thread. Drops frame if busy."""
        self._submit(lambda: self.send_pil(image, width, height))

    def _submit(self, job: Any) -> None:
        """Submit a send job to the persistent worker. Drops if queue full."""
        self._ensure_worker()
        try:
            self._send_queue.put_nowait(job)
        except queue.Full:
            pass  # drop frame — worker still processing previous

    def _ensure_worker(self) -> None:
        """Start the persistent send worker thread if not alive."""
        if self._send_worker and self._send_worker.is_alive():
            return
        self._send_worker = threading.Thread(
            target=self._send_loop, daemon=True, name="device-send")
        self._send_worker.start()

    def _send_loop(self) -> None:
        """Persistent worker: process send jobs from the queue."""
        while True:
            try:
                job = self._send_queue.get(timeout=30)
                job()
            except queue.Empty:
                return  # idle for 30s → exit thread (re-created on next submit)
            except Exception:
                log.exception("Send worker error")

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
            from ..adapters.device.factory import DeviceProtocolFactory

            return DeviceProtocolFactory.get_protocol_info(self._selected)
        except ImportError:
            return None
