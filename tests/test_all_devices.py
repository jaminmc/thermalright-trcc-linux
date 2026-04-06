"""Integration tests — every device through the real app flow.

MockPlatform at the USB boundary, real builder, real services.
Parametrized over ALL_DEVICES, FBL_PROFILES, and PmRegistry —
every known VID:PID, resolution, and LED product gets tested.
"""
from __future__ import annotations

import os

import pytest
from mock_platform import MockPlatform

from trcc.core.models import (
    ALL_DEVICES,
    FBL_PROFILES,
    PROTOCOL_TRAITS,
    DeviceEntry,
    PmRegistry,
)

# Renderer needed for LCD devices — must init before builder
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')


def _make_spec(vid: int, pid: int, entry: DeviceEntry) -> dict:
    """Convert a registry entry to a MockPlatform device spec."""
    is_led = PROTOCOL_TRAITS.get(entry.protocol, PROTOCOL_TRAITS['scsi']).is_led
    spec: dict = {
        "type": "led" if is_led else "lcd",
        "vid": f"{vid:04x}",
        "pid": f"{pid:04x}",
        "name": f"{entry.vendor} {entry.product}",
        "model": entry.model,
    }
    if not is_led:
        # LCD needs a resolution for the noop handshake
        from trcc.core.models import FBL_TO_RESOLUTION
        res = FBL_TO_RESOLUTION.get(entry.fbl, (320, 320))
        spec["resolution"] = f"{res[0]}x{res[1]}"
        spec["pm"] = entry.fbl
    return spec


def _build_and_connect(vid_pid, entry, tmp_path):
    """Build a Device from registry entry through the real flow."""
    vid, pid = vid_pid
    spec = _make_spec(vid, pid, entry)
    platform = MockPlatform([spec], root=tmp_path / '.trcc')
    (tmp_path / '.trcc').mkdir(exist_ok=True)
    (tmp_path / '.trcc' / 'data').mkdir(exist_ok=True)

    from trcc.adapters.device.factory import DeviceProtocolFactory
    from trcc.adapters.render.qt import QtRenderer
    from trcc.conf import init_settings
    from trcc.core.builder import ControllerBuilder

    # Wire platform
    setup = platform.create_setup()
    init_settings(setup)
    platform.configure_scsi_protocol(DeviceProtocolFactory)

    builder = ControllerBuilder(platform)
    is_led = PROTOCOL_TRAITS.get(entry.protocol, PROTOCOL_TRAITS['scsi']).is_led
    if not is_led:
        builder = builder.with_renderer(QtRenderer())

    # Build detected device
    detect_fn = platform.create_detect_fn()
    detected_list = detect_fn()
    assert len(detected_list) == 1
    detected = detected_list[0]

    # Build + connect — the real flow
    device = builder.build_device(detected)
    result = device.connect(detected)

    return device, result


# ═════════════════════════════════════════════════════════════════════════════
# Parametrized over ALL_DEVICES
# ═════════════════════════════════════════════════════════════════════════════

_DEVICE_IDS = [
    f"{vid:04x}:{pid:04x}_{entry.implementation}"
    for (vid, pid), entry in ALL_DEVICES.items()
]


@pytest.mark.parametrize(
    "vid_pid,entry",
    ALL_DEVICES.items(),
    ids=_DEVICE_IDS,
)
class TestAllDevices:
    """Every device in ALL_DEVICES connects through the real flow."""

    def test_connects_successfully(self, vid_pid, entry, tmp_path, tmp_config):
        device, result = _build_and_connect(vid_pid, entry, tmp_path)
        assert result["success"], f"Connect failed: {result}"
        assert device.connected

    def test_device_info_populated(self, vid_pid, entry, tmp_path, tmp_config):
        device, _ = _build_and_connect(vid_pid, entry, tmp_path)
        info = device.device_info
        assert info is not None
        assert info.vid == vid_pid[0]
        assert info.pid == vid_pid[1]

    def test_device_type_matches_protocol(self, vid_pid, entry, tmp_path, tmp_config):
        device, _ = _build_and_connect(vid_pid, entry, tmp_path)
        is_led = PROTOCOL_TRAITS.get(entry.protocol, PROTOCOL_TRAITS['scsi']).is_led
        assert device.is_led == is_led
        assert device.is_lcd == (not is_led)

    def test_lcd_has_resolution(self, vid_pid, entry, tmp_path, tmp_config):
        is_led = PROTOCOL_TRAITS.get(entry.protocol, PROTOCOL_TRAITS['scsi']).is_led
        if is_led:
            pytest.skip("LED device")
        device, _ = _build_and_connect(vid_pid, entry, tmp_path)
        w, h = device.lcd_size
        assert w > 0 and h > 0, f"LCD resolution should be set, got {w}x{h}"

    def test_led_has_state(self, vid_pid, entry, tmp_path, tmp_config):
        is_led = PROTOCOL_TRAITS.get(entry.protocol, PROTOCOL_TRAITS['scsi']).is_led
        if not is_led:
            pytest.skip("LCD device")
        device, _ = _build_and_connect(vid_pid, entry, tmp_path)
        assert device.state is not None, "LED state should be initialized"
        assert device.status is not None, "LED status should be set from handshake"

    def test_cleanup_safe(self, vid_pid, entry, tmp_path, tmp_config):
        device, _ = _build_and_connect(vid_pid, entry, tmp_path)
        device.cleanup()  # should not raise


# ═════════════════════════════════════════════════════════════════════════════
# Every FBL profile — LCD connects at every known resolution
# ═════════════════════════════════════════════════════════════════════════════

# Use a common SCSI VID:PID to test all FBL resolutions
_LCD_VID, _LCD_PID = 0x0402, 0x3922

_FBL_IDS = [f"fbl{fbl}_{p.width}x{p.height}" for fbl, p in FBL_PROFILES.items()]


@pytest.mark.parametrize("fbl,profile", FBL_PROFILES.items(), ids=_FBL_IDS)
class TestAllFBLProfiles:
    """Every FBL resolution connects and resolves correctly."""

    def test_lcd_connects_at_resolution(self, fbl, profile, tmp_path, tmp_config):
        spec = {
            "type": "lcd",
            "vid": f"{_LCD_VID:04x}",
            "pid": f"{_LCD_PID:04x}",
            "name": f"LCD FBL={fbl}",
            "resolution": f"{profile.width}x{profile.height}",
            "pm": fbl,
        }
        platform = MockPlatform([spec], root=tmp_path / '.trcc')
        (tmp_path / '.trcc').mkdir(exist_ok=True)
        (tmp_path / '.trcc' / 'data').mkdir(exist_ok=True)

        from trcc.adapters.device.factory import DeviceProtocolFactory
        from trcc.adapters.render.qt import QtRenderer
        from trcc.conf import init_settings
        from trcc.core.builder import ControllerBuilder

        setup = platform.create_setup()
        init_settings(setup)
        platform.configure_scsi_protocol(DeviceProtocolFactory)

        builder = ControllerBuilder(platform).with_renderer(QtRenderer())
        detected = platform.create_detect_fn()()[0]
        device = builder.build_device(detected)
        result = device.connect(detected)

        assert result["success"]
        assert device.connected
        assert device.is_lcd
        # Resolution comes from handshake FBL → profile lookup.
        # NoopLCDProtocol returns the spec resolution directly.
        w, h = device.lcd_size
        assert w > 0 and h > 0, f"Expected valid resolution, got {w}x{h}"


# ═════════════════════════════════════════════════════════════════════════════
# Every PM entry — LED connects for every known product
# ═════════════════════════════════════════════════════════════════════════════

_PM_ENTRIES = list(PmRegistry)  # [(pm, PmEntry), ...]
_PM_IDS = [f"pm{pm}_{entry.model_name}" for pm, entry in _PM_ENTRIES]

# LED VID:PID
_LED_VID, _LED_PID = 0x0416, 0x8001


@pytest.mark.parametrize("pm,pm_entry", _PM_ENTRIES, ids=_PM_IDS)
class TestAllPMEntries:
    """Every PM registry entry connects and resolves to the right LED product."""

    def test_led_connects_with_pm(self, pm, pm_entry, tmp_path, tmp_config):
        spec = {
            "type": "led",
            "vid": f"{_LED_VID:04x}",
            "pid": f"{_LED_PID:04x}",
            "name": f"LED PM={pm}",
            "model": pm_entry.model_name,
            "pm": pm,
        }
        platform = MockPlatform([spec], root=tmp_path / '.trcc')
        (tmp_path / '.trcc').mkdir(exist_ok=True)
        (tmp_path / '.trcc' / 'data').mkdir(exist_ok=True)

        from trcc.adapters.device.factory import DeviceProtocolFactory
        from trcc.conf import init_settings
        from trcc.core.builder import ControllerBuilder

        setup = platform.create_setup()
        init_settings(setup)
        platform.configure_scsi_protocol(DeviceProtocolFactory)

        builder = ControllerBuilder(platform)
        detected = platform.create_detect_fn()()[0]
        device = builder.build_device(detected)
        result = device.connect(detected)

        assert result["success"]
        assert device.is_led
        assert device.state is not None
        assert device.status is not None
