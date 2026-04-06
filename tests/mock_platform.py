"""Mock platform — noop protocols at the USB boundary, everything else real.

Shared by dev/mock_gui.py and test fixtures. Follows the real app flow:
discovery → builder.build_device() → device.connect() → handler.

Usage in tests:
    from tests.mock_platform import MockPlatform, DEFAULT_DEVICES
    platform = MockPlatform(DEFAULT_DEVICES)
    builder = ControllerBuilder(platform)
    ...
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Callable

# ═════════════════════════════════════════════════════════════════════════════
# Noop protocols — the only fake at the USB boundary
# ═════════════════════════════════════════════════════════════════════════════


class NoopLCDProtocol:
    """Noop LCD protocol — returns canned HandshakeResult, discards frames."""

    def __init__(self, resolution: tuple[int, int], fbl: int,
                 pm: int, sub: int):
        self._resolution = resolution
        self._fbl = fbl
        self._pm = pm
        self._sub = sub

    def handshake(self):
        from trcc.core.models import HandshakeResult
        return HandshakeResult(
            resolution=self._resolution,
            model_id=self._fbl,
            pm_byte=self._pm,
            sub_byte=self._sub,
        )

    def send_image(self, data: bytes, width: int, height: int) -> bool:
        return True

    def close(self) -> None:
        pass


class NoopLEDProtocol:
    """Noop LED protocol — returns canned LedHandshakeInfo, discards data."""

    def __init__(self, pm: int, sub: int = 0):
        self._pm = pm
        self._sub = sub

    def send_led_data(self, colors, segment_on, global_on, brightness) -> bool:
        return True

    def handshake(self):
        from trcc.core.models import LedHandshakeInfo, PmRegistry
        style = PmRegistry.get_style(self._pm, self._sub)
        model = PmRegistry.get_model_name(self._pm, self._sub)
        entry = PmRegistry.resolve(self._pm, self._sub)
        return LedHandshakeInfo(
            model_id=self._pm,
            pm=self._pm,
            sub_type=self._sub,
            style=style,
            model_name=model,
            style_sub=entry.style_sub if entry else 0,
        )

    def close(self) -> None:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# MockSetup — PlatformSetup pointing all paths to a temp directory
# ═════════════════════════════════════════════════════════════════════════════


class MockSetup:
    """PlatformSetup pointing all paths to a configurable root.

    Delegates to real LinuxSetup for everything not overridden.
    """

    def __init__(self, root: Path | None = None):
        from trcc.adapters.system.linux.setup import LinuxSetup
        self._real = LinuxSetup()
        self._root = root or Path(os.environ.get('TRCC_CONFIG_DIR', '/tmp/.trcc-test'))
        self._data = self._root / 'data'
        self._user = self._root.parent / '.trcc-user'

    def __getattr__(self, name: str) -> Any:
        return getattr(self._real, name)

    def config_dir(self) -> str:
        return str(self._root)

    def data_dir(self) -> str:
        return str(self._data)

    def user_content_dir(self) -> str:
        return str(self._user)

    def web_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import web_dir_name
        return str(self._data / 'web' / web_dir_name(width, height))

    def web_masks_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import masks_dir_name
        return str(self._data / 'web' / masks_dir_name(width, height))

    def user_masks_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import masks_dir_name
        return str(self._user / 'data' / 'web' / masks_dir_name(width, height))

    def theme_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import theme_dir_name
        return str(self._data / theme_dir_name(width, height))

    def resolve_assets_dir(self, pkg_assets_dir: Any) -> Any:
        return pkg_assets_dir

    def acquire_instance_lock(self) -> str:
        return "mock-lock"

    def raise_existing_instance(self) -> None:
        pass

    def configure_dpi(self) -> None:
        pass

    def wire_ipc_raise(self, app: Any, window: Any) -> None:
        pass

    def minimize_on_close(self) -> bool:
        return False

    def configure_stdout(self) -> None:
        pass


# ═════════════════════════════════════════════════════════════════════════════
# MockPlatform — PlatformAdapter returning fake devices + noop protocols
# ═════════════════════════════════════════════════════════════════════════════


class MockPlatform:
    """Platform adapter that injects fake devices and noop protocols.

    The only difference from LinuxPlatform: detect_fn returns mock devices,
    protocols are noop. Sensors, hardware info, autostart — all real.
    """

    def __init__(self, device_specs: list[dict], root: Path | None = None):
        self._specs = device_specs
        self._root = root
        from trcc.adapters.system.linux.platform import LinuxPlatform
        self._real = LinuxPlatform()

    def create_detect_fn(self) -> Callable[[], list]:
        from trcc.core.models import ALL_DEVICES, DetectedDevice

        devices: list[DetectedDevice] = []
        for i, spec in enumerate(self._specs):
            dtype = spec.get('type', 'lcd')
            vid = int(spec.get('vid', '0402'), 16)
            pid = int(spec.get('pid', '3922'), 16)
            name = spec.get('name', f'Mock {dtype.upper()} {i}')
            entry = ALL_DEVICES.get((vid, pid))

            if dtype == 'lcd':
                path = f"mock:lcd:{i}:{vid:04x}:{pid:04x}"
                devices.append(DetectedDevice(
                    vid=vid, pid=pid,
                    vendor_name=entry.vendor if entry else "Mock",
                    product_name=name,
                    usb_path=path, scsi_device=path,
                    protocol=entry.protocol if entry else "scsi",
                    device_type=entry.device_type if entry else 1,
                    implementation=entry.implementation if entry else "ali_corp_lcd_v1",
                    model=spec.get('model', entry.model if entry else 'FROZEN_WARFRAME'),
                    button_image=spec.get('button_image',
                                          entry.button_image if entry else "A1CZTV"),
                ))
            elif dtype == 'led':
                path = f"mock:led:{i}:{vid:04x}:{pid:04x}"
                devices.append(DetectedDevice(
                    vid=vid, pid=pid,
                    vendor_name=entry.vendor if entry else "Mock",
                    product_name=name,
                    usb_path=path, scsi_device=path,
                    protocol="led",
                    device_type=entry.device_type if entry else 1,
                    implementation=entry.implementation if entry else "hid_led",
                    model=spec.get('model', entry.model if entry else 'AX120'),
                    button_image=entry.button_image if entry else "",
                ))

        return lambda: devices

    def create_sensor_enumerator(self):
        return self._real.create_sensor_enumerator()

    def create_autostart_manager(self):
        from unittest.mock import MagicMock
        mgr = MagicMock()
        mgr.is_enabled.return_value = False
        return mgr

    def create_setup(self):
        return MockSetup(self._root)

    def get_memory_info_fn(self):
        return self._real.get_memory_info_fn()

    def get_disk_info_fn(self):
        return self._real.get_disk_info_fn()

    def configure_scsi_protocol(self, factory: Any) -> None:
        specs = self._specs

        def _make_lcd_protocol(device_info):
            vid = getattr(device_info, 'vid', 0)
            pid = getattr(device_info, 'pid', 0)
            for spec in specs:
                sv = int(spec.get('vid', '0'), 16)
                sp = int(spec.get('pid', '0'), 16)
                if sv == vid and sp == pid:
                    res_str = spec.get('resolution', '320x320')
                    parts = res_str.split('x')
                    w, h = int(parts[0]), int(parts[1])
                    from trcc.core.models import RESOLUTION_TO_PM
                    fbl = RESOLUTION_TO_PM.get((w, h), 100)
                    pm = spec.get('pm', fbl)
                    sub = spec.get('sub', 0)
                    return NoopLCDProtocol((w, h), fbl, pm, sub)
            return NoopLCDProtocol((320, 320), 100, 100, 0)

        def _make_led_protocol(device_info):
            vid = getattr(device_info, 'vid', 0)
            pid = getattr(device_info, 'pid', 0)
            for spec in specs:
                if spec.get('type') != 'led':
                    continue
                sv = int(spec.get('vid', '0'), 16)
                sp = int(spec.get('pid', '0'), 16)
                if sv == vid and sp == pid:
                    pm = spec.get('pm')
                    sub = spec.get('sub', 0)
                    if pm is None:
                        from trcc.core.models import PmRegistry
                        model = spec.get('model', '')
                        pm = next(
                            (p for p, e in PmRegistry if e.model_name == model),
                            3)
                    return NoopLEDProtocol(pm, sub)
            return NoopLEDProtocol(3)

        factory._PROTOCOL_REGISTRY[('scsi', '')] = _make_lcd_protocol
        factory._PROTOCOL_REGISTRY[('hid', '')] = _make_lcd_protocol
        factory._PROTOCOL_REGISTRY[('bulk', '')] = _make_lcd_protocol
        factory._PROTOCOL_REGISTRY[('ly', '')] = _make_lcd_protocol
        factory._PROTOCOL_REGISTRY[('led', '')] = _make_led_protocol


# ═════════════════════════════════════════════════════════════════════════════
# Default device specs
# ═════════════════════════════════════════════════════════════════════════════

DEFAULT_DEVICES = [
    {"type": "lcd", "resolution": "320x320", "name": "Frozen Warframe Pro",
     "vid": "0402", "pid": "3922", "pm": 32, "sub": 1},
    {"type": "lcd", "resolution": "1280x480", "name": "Trofeo Vision",
     "vid": "0418", "pid": "5303", "pm": 6, "sub": 1},
    {"type": "led", "model": "AX120_DIGITAL", "name": "AX120 R3",
     "vid": "0416", "pid": "8001"},
    {"type": "led", "model": "PA120_DIGITAL", "name": "PA120 DIGITAL",
     "vid": "0416", "pid": "8002"},
    {"type": "led", "model": "LF10", "name": "LF10",
     "vid": "0416", "pid": "8003"},
    {"type": "led", "model": "CZ1", "name": "CZ1",
     "vid": "0416", "pid": "8004"},
]
