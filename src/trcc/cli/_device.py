"""Device detection, selection, and probing."""
from __future__ import annotations

import logging

from trcc.cli import _cli_handler

log = logging.getLogger(__name__)


def _probe(dev):
    """Try to resolve device details via HID handshake/cache.

    Returns a dict with resolved fields, or empty dict if no probe available.
    """
    result = {}
    log.debug("probing device %04x:%04x impl=%s", dev.vid, dev.pid, dev.implementation)

    # LED devices: probe via led_device cache/handshake
    if dev.implementation == 'hid_led':
        try:
            from trcc.adapters.device.led import probe_led_model
            info = probe_led_model(dev.vid, dev.pid, usb_path=dev.usb_path)
            if info and info.model_name:
                result['model'] = info.model_name
                result['pm'] = info.pm
                result['style'] = info.style
                log.debug("LED probe result: model=%s pm=%s", info.model_name, info.pm)
        except Exception:
            log.debug("LED probe failed for %04x:%04x", dev.vid, dev.pid)

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
                log.debug("HID probe result: pm=%s resolution=%s",
                          raw_info.mode_byte_1, raw_info.resolution)
        except Exception:
            log.debug("HID probe failed for %04x:%04x", dev.vid, dev.pid)

    # Bulk USB devices: probe via factory
    elif dev.implementation == 'bulk_usblcdnew':
        try:
            from trcc.adapters.device.factory import DeviceProtocolFactory
            bp = DeviceProtocolFactory.create_protocol(dev)
            hs = bp.handshake()
            if hs and hs.resolution:
                result['resolution'] = hs.resolution
                result['pm'] = hs.model_id
                log.debug("bulk probe result: resolution=%s pm=%s", hs.resolution, hs.model_id)
            bp.close()
        except Exception:
            log.debug("bulk probe failed for %04x:%04x", dev.vid, dev.pid)

    return result


def _format(dev, probe=False):
    """Format a detected device for display."""
    vid_pid = f"[{dev.vid:04x}:{dev.pid:04x}]"
    proto = dev.protocol.upper()
    if dev.scsi_device:
        path = dev.scsi_device
    elif dev.protocol in ("hid", "bulk", "ly", "led"):
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
def detect(show_all=False, detect_fn=None, platform_setup=None):
    """Detect LCD device."""
    from trcc.conf import Settings
    from trcc.core.builder import ControllerBuilder

    log.debug("detect called show_all=%s", show_all)
    if detect_fn is None:
        detect_fn = ControllerBuilder.for_current_os().build_detect_fn()
    if platform_setup is None:
        platform_setup = ControllerBuilder.for_current_os().build_setup()
    devices = detect_fn()
    log.debug("detected %d device(s)", len(devices))

    if not devices:
        print("No compatible TRCC LCD device detected.")
        hint = platform_setup.no_devices_hint()
        if hint:
            print(hint)
        return 1

    selected = Settings.get_selected_device()
    if show_all or len(devices) > 1:
        for i, dev in enumerate(devices, 1):
            marker = "*" if dev.path == selected else " "
            print(f"{marker} [{i}] {_format(dev, probe=True)}")
        if len(devices) > 1:
            print("\nUse 'trcc select N' to switch devices")
    else:
        print(f"Active: {_format(devices[0], probe=True)}")

    for warning in platform_setup.check_device_permissions(devices):
        print(f"\n{warning}")

    return 0


@_cli_handler
def select(number, detect_fn=None):
    """Select a device by number."""
    from trcc.conf import Settings
    from trcc.core.builder import ControllerBuilder

    log.debug("select device number=%d", number)
    if detect_fn is None:
        detect_fn = ControllerBuilder.for_current_os().build_detect_fn()
    devices = detect_fn()
    if not devices:
        print("No devices found.")
        return 1

    if number < 1 or number > len(devices):
        print("Invalid device number. Available devices:")
        for i, dev in enumerate(devices, 1):
            print(f"  [{i}] {_format(dev)}")
        return 1

    device = devices[number - 1]
    Settings.save_selected_device(device.path)
    print(f"Selected: {_format(device)}")
    return 0
