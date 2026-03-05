"""HID/LED diagnostic commands."""
from __future__ import annotations


def _hex_dump(data: bytes, max_bytes: int = 64) -> None:
    """Print a hex dump of data (for hid-debug diagnostics)."""
    for row in range(0, min(len(data), max_bytes), 16):
        hex_str = ' '.join(f'{b:02x}' for b in data[row:row + 16])
        ascii_str = ''.join(
            chr(b) if 32 <= b < 127 else '.'
            for b in data[row:row + 16]
        )
        print(f"  {row:04x}: {hex_str:<48s} {ascii_str}")


def _hid_debug_lcd(dev, *, test_frame: bool = False) -> None:
    """HID handshake diagnostic for LCD devices (Type 2/3)."""
    from trcc.adapters.device.factory import HidProtocol
    from trcc.adapters.device.hid import (
        HidHandshakeInfo,
        get_button_image,
    )
    from trcc.core.models import FBL_TO_RESOLUTION, JPEG_MODE_FBLS, fbl_to_resolution, pm_to_fbl

    protocol = HidProtocol(
        vid=dev.vid, pid=dev.pid,
        device_type=dev.device_type,
    )
    info = protocol.handshake()

    if info is None:
        error = protocol.last_error
        if error:
            print(f"  Handshake FAILED: {error}")
        else:
            print("  Handshake returned None (no response from device)")
        protocol.close()
        return

    assert isinstance(info, HidHandshakeInfo)
    pm = info.mode_byte_1
    sub = info.mode_byte_2
    fbl = info.fbl if info.fbl is not None else pm_to_fbl(pm, sub)
    resolution = info.resolution or fbl_to_resolution(fbl, pm)

    print("  Handshake OK!")
    print(f"  PM byte  = {pm} (0x{pm:02x})")
    print(f"  SUB byte = {sub} (0x{sub:02x})")
    print(f"  FBL      = {fbl} (0x{fbl:02x})")
    print(f"  Serial   = {info.serial}")
    print(f"  Resolution = {resolution[0]}x{resolution[1]}")

    # Encoding mode
    is_jpeg = fbl in JPEG_MODE_FBLS
    print(f"  Encoding = {'JPEG' if is_jpeg else 'RGB565'}")

    # Button image from PM + SUB
    button = get_button_image(pm, sub)
    if button:
        print(f"  Button image = {button}")
    else:
        print(f"  Button image = unknown PM={pm} SUB={sub} (defaulting to CZTV)")

    # Known FBL?
    if fbl in FBL_TO_RESOLUTION:
        print(f"  FBL {fbl} = known resolution")
    else:
        print(f"  FBL {fbl} = UNKNOWN (not in mapping table)")

    # Raw response hex dump
    if info.raw_response:
        print("\n  Raw handshake response (first 64 bytes):")
        _hex_dump(info.raw_response)

    # Test frame send
    if test_frame:
        _send_test_frame(protocol, resolution, fbl)

    protocol.close()


def _send_test_frame(protocol, resolution: tuple, fbl: int) -> None:
    """Send a solid red test frame and report transfer details."""
    from trcc.core.models import JPEG_MODE_FBLS

    w, h = resolution
    print(f"\n  Sending RED test frame ({w}x{h})...")

    try:
        from trcc.services.image import ImageService

        img = ImageService.solid_color(255, 0, 0, w, h)

        is_jpeg = fbl in JPEG_MODE_FBLS
        if is_jpeg:
            data = ImageService.to_jpeg(img)
            print(f"    Encoding: JPEG ({len(data):,} bytes)")
        else:
            data = ImageService.to_rgb565(img, '<')
            print(f"    Encoding: RGB565 LE ({len(data):,} bytes)")

        # Show packet header
        packet = protocol._device.build_frame_packet(data, w, h)
        print(f"    Packet size: {len(packet):,} bytes")
        print(f"    Header: {packet[:20].hex()}")

        ok = protocol._device.send_frame(data)
        print(f"    Send result: {'OK' if ok else 'FAILED'}")
        print("    >>> Check your LCD — did it turn RED?")

    except Exception as e:
        print(f"    Test frame FAILED: {e}")


def _hid_debug_led(dev) -> None:
    """HID handshake diagnostic for LED devices (Type 1)."""
    from trcc.adapters.device.factory import LedProtocol
    from trcc.adapters.device.led import LedHandshakeInfo, PmRegistry

    protocol = LedProtocol(vid=dev.vid, pid=dev.pid)
    info = protocol.handshake()

    if info is None:
        error = protocol.last_error
        if error:
            print(f"  Handshake FAILED: {error}")
        else:
            print("  Handshake returned None (no response from device)")
        protocol.close()
        return

    assert isinstance(info, LedHandshakeInfo)
    print("  Handshake OK!")
    print(f"  PM byte    = {info.pm} (0x{info.pm:02x})")
    print(f"  Sub-type   = {info.sub_type} (0x{info.sub_type:02x})")
    print(f"  Model      = {info.model_name}")

    style = info.style
    if style:
        print(f"  Style ID   = {style.style_id}")
        print(f"  LED count  = {style.led_count}")
        print(f"  Segments   = {style.segment_count}")
        print(f"  Zones      = {style.zone_count}")

    if info.pm in PmRegistry.PM_TO_STYLE:
        print(f"\n  Status: KNOWN device (PM {info.pm} in tables)")
    else:
        print(f"\n  Status: UNKNOWN PM byte ({info.pm})")
        print("  This device falls back to AX120 defaults.")
        print(f"  Please report PM {info.pm} in your GitHub issue.")

    # Raw response hex dump
    if info.raw_response:
        print("\n  Raw handshake response (first 64 bytes):")
        _hex_dump(info.raw_response)

    protocol.close()


def hid_debug(*, test_frame: bool = False):
    """HID handshake diagnostic — prints hex dump and resolved device info.

    Users can share this output in bug reports to help debug HID device issues.
    Routes LED devices (Type 1) through LedProtocol, LCD devices through HidProtocol.

    Args:
        test_frame: If True, send a solid red test frame after handshake.
    """
    try:
        from trcc.adapters.device.detector import detect_devices

        print("HID Debug — Handshake Diagnostic")
        print("=" * 60)

        devices = detect_devices()
        hid_devices = [d for d in devices if d.protocol == 'hid']

        if not hid_devices:
            print("\nNo HID devices found.")
            print("Make sure the device is plugged in and try:")
            print("  trcc setup-udev   (then unplug/replug USB cable)")
            return 0

        for dev in hid_devices:
            is_led = dev.implementation == 'hid_led'
            dev_kind = "LED" if is_led else f"LCD (Type {dev.device_type})"

            print(f"\nDevice: {dev.vendor_name} {dev.product_name}")
            print(f"  VID:PID = {dev.vid:04x}:{dev.pid:04x}")
            print(f"  Kind = {dev_kind}")
            print(f"  Implementation = {dev.implementation}")

            print("\n  Attempting handshake...")
            try:
                if is_led:
                    _hid_debug_led(dev)
                else:
                    _hid_debug_lcd(dev, test_frame=test_frame)
            except ImportError as e:
                print(f"  Missing dependency: {e}")
                print("  Install: pip install pyusb  (or pip install hidapi)")
            except Exception as e:
                print(f"  Handshake FAILED: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'=' * 60}")
        print("Copy the output above and paste it in your GitHub issue.")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def led_debug(test=False):
    """Diagnose LED device — handshake, PM byte discovery, optional test colors."""
    try:
        import time

        from trcc.adapters.device.factory import LedProtocol
        from trcc.adapters.device.led import (
            LED_PID,
            LED_VID,
            LedHandshakeInfo,
            PmRegistry,
        )

        print("LED Device Diagnostic")
        print("=" * 50)
        print(f"  Target: VID=0x{LED_VID:04x} PID=0x{LED_PID:04x}")

        protocol = LedProtocol(vid=LED_VID, pid=LED_PID)
        info = protocol.handshake()

        if info is None:
            error = protocol.last_error
            print(f"\nHandshake failed: {error or 'no response'}")
            protocol.close()
            return 1

        assert isinstance(info, LedHandshakeInfo)
        print(f"\n  PM byte:    {info.pm}")
        print(f"  Sub-type:   {info.sub_type}")
        print(f"  Model:      {info.model_name}")
        style = info.style
        if style is None:
            print("  Style:      (unknown — handshake returned no style)")
            protocol.close()
            return 1
        print(f"  Style ID:   {style.style_id}")
        print(f"  LED count:  {style.led_count}")
        print(f"  Segments:   {style.segment_count}")
        print(f"  Zones:      {style.zone_count}")

        if info.pm in PmRegistry.PM_TO_STYLE:
            print(f"\n  Status: KNOWN device (PM {info.pm} in tables)")
        else:
            print(f"\n  Status: UNKNOWN PM byte ({info.pm})")
            print("  This device falls back to AX120 defaults.")
            print(f"  Add PM {info.pm} to led_device.py _PM_REGISTRY.")

        if test:
            print("\n  Sending test colors...")
            led_count = style.led_count
            for name, color in [("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)),
                                ("BLUE", (0, 0, 255)), ("WHITE", (255, 255, 255))]:
                protocol.send_led_data([color] * led_count, brightness=100)
                print(f"    {name}")
                time.sleep(1.5)
            protocol.send_led_data(
                [(0, 0, 0)] * led_count, global_on=False, brightness=0)
            print("    OFF")

        protocol.close()
        print("\nDone.")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1
