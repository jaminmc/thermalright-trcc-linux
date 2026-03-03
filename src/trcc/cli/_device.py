"""Device detection, selection, and probing."""
from __future__ import annotations

from typing import Optional

from trcc.cli import _cli_handler


def _get_service(device_path: Optional[str] = None):
    """Create a DeviceService, detect devices, select, and handshake.

    Args:
        device_path: SCSI path (/dev/sgX) or None to use saved selection.

    Returns:
        DeviceService with a selected device (resolution discovered).
    """
    from trcc.services import DeviceService

    svc = DeviceService()
    svc.detect()

    if device_path:
        # Select by explicit path
        match = next((d for d in svc.devices if d.path == device_path), None)
        if match:
            svc.select(match)
        elif svc.devices:
            svc.select(svc.devices[0])
    elif not svc.selected:
        # Fall back to saved selection
        from trcc.conf import Settings
        saved = Settings.get_selected_device()
        if saved:
            match = next((d for d in svc.devices if d.path == saved), None)
            if match:
                svc.select(match)

    # Discover resolution + FBL via handshake if not yet known
    dev = svc.selected
    if dev:
        discover_resolution(dev)

    return svc


def discover_resolution(dev) -> None:
    """Run protocol handshake to discover resolution + FBL if still unknown.

    Mutates dev in-place: sets resolution, fbl_code, use_jpeg.
    Safe to call multiple times — no-op if resolution already known.
    """
    if dev.resolution != (0, 0):
        return
    try:
        from trcc.adapters.device.factory import DeviceProtocolFactory
        protocol = DeviceProtocolFactory.get_protocol(dev)
        result = protocol.handshake()
        if result:
            res = getattr(result, 'resolution', None)
            if isinstance(res, tuple) and len(res) == 2 and res != (0, 0):
                dev.resolution = res
            # Propagate FBL code for JPEG mode detection
            fbl = getattr(result, 'fbl', None) or getattr(result, 'model_id', None)
            if fbl:
                dev.fbl_code = fbl
            # Bulk PM=32 uses RGB565, not JPEG
            bulk_dev = getattr(protocol, '_device', None)
            if bulk_dev is not None:
                dev.use_jpeg = getattr(bulk_dev, 'use_jpeg', True)
    except Exception:
        pass  # Handshake may fail if device not ready


def _ensure_extracted(driver):
    """Extract theme/mask archives for the driver's detected resolution (one-time)."""
    try:
        if driver.implementation:
            w, h = driver.implementation.resolution
            from trcc.adapters.infra.data_repository import DataManager
            DataManager.ensure_all(w, h)
    except Exception:
        pass  # Non-fatal — themes are optional for CLI commands


def _get_driver(device=None):
    """Create an LCDDriver, resolving selected device and extracting archives."""
    from trcc.adapters.device.lcd import LCDDriver
    from trcc.conf import Settings
    if device is None:
        device = Settings.get_selected_device()
    driver = LCDDriver(device_path=device)
    _ensure_extracted(driver)
    return driver


def _probe(dev):
    """Try to resolve device details via HID handshake/cache.

    Returns a dict with resolved fields, or empty dict if no probe available.
    """
    result = {}

    # LED devices: probe via led_device cache/handshake
    if dev.implementation == 'hid_led':
        try:
            from trcc.adapters.device.led import probe_led_model
            info = probe_led_model(dev.vid, dev.pid, usb_path=dev.usb_path)
            if info and info.model_name:
                result['model'] = info.model_name
                result['pm'] = info.pm
                result['style'] = info.style
        except Exception:
            pass

    # HID LCD devices: probe via hid_device handshake
    elif dev.implementation in ('hid_type2', 'hid_type3'):
        try:
            from trcc.adapters.device.factory import DeviceProtocolFactory
            from trcc.adapters.device.hid import HidHandshakeInfo
            device_info = {
                'vid': dev.vid, 'pid': dev.pid,
                'protocol': dev.protocol, 'device_type': dev.device_type,
                'implementation': dev.implementation,
                'path': f"hid:{dev.vid:04x}:{dev.pid:04x}",
            }
            protocol = DeviceProtocolFactory.get_protocol(device_info)
            raw_info = protocol.handshake()
            if isinstance(raw_info, HidHandshakeInfo):
                result['pm'] = raw_info.mode_byte_1
                result['resolution'] = raw_info.resolution
                if raw_info.serial:
                    result['serial'] = raw_info.serial
        except Exception:
            pass

    # Bulk USB devices: probe via BulkProtocol
    elif dev.implementation == 'bulk_usblcdnew':
        try:
            from trcc.adapters.device.factory import BulkProtocol
            bp = BulkProtocol(dev.vid, dev.pid)
            hs = bp.handshake()
            if hs and hs.resolution:
                result['resolution'] = hs.resolution
                result['pm'] = hs.model_id
            bp.close()
        except Exception:
            pass

    return result


def _format(dev, probe=False):
    """Format a detected device for display."""
    vid_pid = f"[{dev.vid:04x}:{dev.pid:04x}]"
    proto = dev.protocol.upper()
    if dev.scsi_device:
        path = dev.scsi_device
    elif dev.protocol in ("hid", "bulk", "ly"):
        path = f"{dev.vid:04x}:{dev.pid:04x}"
    else:
        path = "No device path found"
    line = f"{path} — {dev.product_name} {vid_pid} ({proto})"

    if not probe:
        return line

    info = _probe(dev)
    if not info:
        return line

    details = []
    if 'model' in info:
        details.append(f"model: {info['model']}")
    if 'resolution' in info:
        w, h = info['resolution']
        details.append(f"resolution: {w}x{h}")
    if 'pm' in info:
        details.append(f"PM={info['pm']}")
    if 'serial' in info:
        details.append(f"serial: {info['serial'][:16]}")

    if details:
        line += f" ({', '.join(details)})"
    return line


@_cli_handler
def detect(show_all=False):
    """Detect LCD device."""
    from trcc.cli._display import DisplayDispatcher
    from trcc.conf import Settings

    lcd = DisplayDispatcher()
    result = lcd.detect()

    if not result["success"]:
        print("No compatible TRCC LCD device detected.")
        return 1

    devices = result["devices"]

    if show_all:
        selected = Settings.get_selected_device()
        for i, dev in enumerate(devices, 1):
            marker = "*" if dev.scsi_device == selected else " "
            print(f"{marker} [{i}] {_format(dev, probe=True)}")
        if len(devices) > 1:
            print("\nUse 'trcc select N' to switch devices")
    else:
        selected = Settings.get_selected_device()
        dev = None
        if selected:
            dev = next((d for d in devices if d.scsi_device == selected), None)
        if not dev:
            dev = devices[0]
        print(f"Active: {_format(dev, probe=True)}")

    # Check for stale/missing udev rules on any device
    from trcc.adapters.device.detector import check_udev_rules
    from trcc.core.models import PROTOCOL_TRAITS

    for dev in devices:
        if not check_udev_rules(dev):
            msg = f"\nDevice {dev.vid:04x}:{dev.pid:04x} needs updated udev rules.\n"
            msg += "Run:  sudo trcc setup-udev"
            traits = PROTOCOL_TRAITS.get(dev.protocol, PROTOCOL_TRAITS['scsi'])
            if traits.requires_reboot:
                msg += "\nThen reboot for the USB storage quirk to take effect."
            print(msg)
            break

    return 0


@_cli_handler
def select(number):
    """Select a device by number."""
    from trcc.cli._display import DisplayDispatcher
    from trcc.conf import Settings

    lcd = DisplayDispatcher()
    result = lcd.detect()

    if not result["success"]:
        print("No devices found.")
        return 1

    devices = result["devices"]
    if number < 1 or number > len(devices):
        print(f"Invalid device number. Use 1-{len(devices)}")
        return 1

    device = devices[number - 1]
    Settings.save_selected_device(device.scsi_device)
    print(f"Selected: {device.scsi_device} ({device.product_name})")
    return 0
