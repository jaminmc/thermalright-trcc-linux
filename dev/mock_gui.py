#!/usr/bin/env python3
"""Mock GUI — real TRCC GUI with fake USB devices.

Injects a MockPlatform adapter at the hexagonal boundary. Everything else —
TrccApp, ControllerBuilder, LCDDevice, LCDHandler, TRCCApp — is production
code. Bugs found here are real bugs.

Device config (dev/.trcc/devices.json):
    [
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
         "vid": "0416", "pid": "8004"}
    ]

Usage:
    PYTHONPATH=src python3 dev/mock_gui.py
    PYTHONPATH=src python3 dev/mock_gui.py --decorated
    PYTHONPATH=src python3 dev/mock_gui.py --report report.txt  # emulate user's setup
    PYTHONPATH=src python3 dev/mock_gui.py --init     # generate default devices.json
    PYTHONPATH=src python3 dev/mock_gui.py --list      # list resolutions
"""
from __future__ import annotations

import json
import logging
import os
import signal
import sys
from pathlib import Path
from typing import Any, cast

os.environ.pop('QT_QPA_PLATFORM', None)  # use real display

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'src'))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tests'))

# ── Isolated config directory ────────────────────────────────────────────────

_DEV_DIR = Path(__file__).resolve().parent
_DEV_TRCC = _DEV_DIR / '.trcc'
_DEV_DATA = _DEV_TRCC / 'data'
_DEV_USER = _DEV_DIR / '.trcc-user'
_DEV_TRCC.mkdir(exist_ok=True)
_DEV_DATA.mkdir(exist_ok=True)
_DEV_USER.mkdir(exist_ok=True)

_DEVICES_JSON = _DEV_DIR / 'devices.json'  # survives .trcc wipe

os.environ['TRCC_CONFIG_DIR'] = str(_DEV_TRCC)

log = logging.getLogger(__name__)


# Mock platform classes live in tests/mock_platform.py — shared with test suite
from mock_platform import DEFAULT_DEVICES as _DEFAULT_DEVICES_BASE  # noqa: E402
from mock_platform import MockPlatform  # noqa: E402

# ═════════════════════════════════════════════════════════════════════════════
# CLI helpers
# ═════════════════════════════════════════════════════════════════════════════


_DEFAULT_DEVICES = list(_DEFAULT_DEVICES_BASE)


def _specs_from_report(report_path: str) -> list[dict]:
    """Parse a trcc report file and convert to device specs."""
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent / 'tools'))
    from diagnose import parse_report

    from trcc.core.models import LED_DEVICES

    text = Path(report_path).read_text()
    report = parse_report(text)

    if report.os_name:
        print(f"User OS: {report.os_name}")
    if report.trcc_version:
        print(f"User trcc version: {report.trcc_version}")

    specs: list[dict] = []
    for dev in report.devices:
        is_led = (dev.vid, dev.pid) in LED_DEVICES
        spec: dict[str, Any] = {
            "type": "led" if is_led else "lcd",
            "vid": f"{dev.vid:04x}",
            "pid": f"{dev.pid:04x}",
            "name": f"User {dev.protocol.upper()} ({dev.vid:04x}:{dev.pid:04x})",
        }
        if dev.pm:
            spec["pm"] = dev.pm
        if dev.sub:
            spec["sub"] = dev.sub
        if dev.width and dev.height:
            spec["resolution"] = f"{dev.width}x{dev.height}"
        specs.append(spec)

    if not specs:
        print("Warning: no devices found in report — using defaults")
        return list(_DEFAULT_DEVICES)
    return specs


def _parse_args():
    decorated = False
    verbosity = 0
    report_path = None
    args = sys.argv[1:]
    i = 0
    while i < len(args):
        arg = args[i]
        if arg.startswith('-v'):
            verbosity = arg.count('v')
        elif arg == '--list':
            from trcc.core.models import FBL_TO_RESOLUTION
            resolutions = sorted(set(FBL_TO_RESOLUTION.values()),
                                 key=lambda r: (r[0] * r[1], r[0]))
            print("Available resolutions:")
            for w, h in resolutions:
                print(f"  {w}x{h}")
            sys.exit(0)
        elif arg == '--init':
            sample = list(_DEFAULT_DEVICES)
            _DEVICES_JSON.write_text(json.dumps(sample, indent=2))
            print(f"Created {_DEVICES_JSON}")
            sys.exit(0)
        elif arg == '--report':
            i += 1
            if i < len(args):
                report_path = args[i]
            else:
                print("Error: --report requires a file path")
                sys.exit(1)
        elif arg == '--decorated':
            decorated = True
        i += 1
    return decorated, verbosity, report_path


def _load_device_specs(report_path: str | None = None) -> list[dict]:
    if report_path:
        return _specs_from_report(report_path)
    if _DEVICES_JSON.exists():
        try:
            specs = json.loads(_DEVICES_JSON.read_text())
            if isinstance(specs, list) and specs:
                return specs
        except (json.JSONDecodeError, OSError) as e:
            print(f"Warning: bad devices.json: {e} — using defaults")
    return list(_DEFAULT_DEVICES)


# ═════════════════════════════════════════════════════════════════════════════
# main — mirrors gui/__init__.py::launch() with MockPlatform instead of Linux
# ═════════════════════════════════════════════════════════════════════════════


def main():
    decorated, verbosity, report_path = _parse_args()
    device_specs = _load_device_specs(report_path)

    print(f"Devices: {len(device_specs)}")
    for i, spec in enumerate(device_specs):
        dtype = spec.get('type', 'lcd')
        name = spec.get('name', f'Device {i}')
        detail = spec.get('resolution', '') or spec.get('model', '')
        print(f"  [{i}] {dtype.upper()} {name} {detail}")

    # ── Patch core paths to dev/.trcc/ before any import reads them ───────
    import trcc.core.paths as _paths
    _paths.USER_CONFIG_DIR = str(_DEV_TRCC)
    _paths.USER_DATA_DIR = str(_DEV_DATA)
    _paths.DATA_DIR = str(_DEV_DATA)
    _paths.USER_CONTENT_DIR = str(_DEV_USER)
    _paths.USER_CONTENT_DATA_DIR = str(_DEV_USER / 'data')
    _paths.USER_MASKS_WEB_DIR = str(_DEV_USER / 'data' / 'web')

    import trcc.conf as _conf_mod
    _conf_mod.CONFIG_DIR = str(_DEV_TRCC)
    _conf_mod.CONFIG_PATH = str(_DEV_TRCC / 'config.json')

    # Log to dev/.trcc/trcc.log (must be before bootstrap imports the configurator)
    from trcc.adapters.infra.diagnostics import StandardLoggingConfigurator
    StandardLoggingConfigurator.__init__.__defaults__ = (_DEV_TRCC / 'trcc.log',)

    # ── Build the app with MockPlatform — one adapter swap ────────────────
    from trcc.core.app import AppEvent, TrccApp
    from trcc.core.builder import ControllerBuilder

    platform: Any = MockPlatform(device_specs, root=_DEV_TRCC)
    builder = ControllerBuilder(platform)
    TrccApp.reset()
    app = TrccApp(builder)
    TrccApp._instance = app
    app._ensure_data_fn = builder.build_ensure_data_fn()
    dl_pack, dl_list = builder.build_download_fns()
    app._download_pack_fn = dl_pack
    app._list_available_fn = dl_list

    # ── Qt bootstrap ─────────────────────────────────────────────────────
    from trcc.gui.assets import _PKG_ASSETS_DIR, set_assets_dir
    setup = platform.create_setup()
    set_assets_dir(setup.resolve_assets_dir(_PKG_ASSETS_DIR))

    os.environ.setdefault("QT_LOGGING_RULES", "qt.qpa.services=false")
    os.environ["QT_ENABLE_HIGHDPI_SCALING"] = "0"

    from PySide6.QtGui import QFont
    from PySide6.QtWidgets import QApplication
    qapp = cast(QApplication, QApplication.instance() or QApplication(sys.argv))
    qapp.setQuitOnLastWindowClosed(True)
    qapp.setDesktopFileName("trcc-mock")

    font = QFont("Microsoft YaHei", 10)
    if not font.exactMatch():
        font = QFont("Sans Serif", 10)
    qapp.setFont(font)

    # ── Register noop protocols BEFORE scan ─────────────────────────────
    from trcc.adapters.device.factory import DeviceProtocolFactory
    platform.configure_scsi_protocol(DeviceProtocolFactory)

    # ── Bootstrap — THE REAL FLOW ────────────────────────────────────────
    from trcc.adapters.render.qt import QtRenderer
    app.init_platform(verbosity=verbosity, renderer_factory=lambda: QtRenderer())
    app.scan()
    app._ensure_data_blocking()

    # ── System service (real sensors from this machine) ──────────────────
    system_svc = app.build_system()
    app.set_system(system_svc)

    from trcc.services.system import set_instance
    set_instance(system_svc)

    # ── GUI — production TRCCApp, injected deps ──────────────────────────
    mem_fn, disk_fn = builder.build_hardware_fns()

    from trcc.gui.trcc_app import TRCCApp as _TRCCApp
    window = _TRCCApp(
        system_svc=system_svc,
        setup=cast(Any, setup),
        autostart=platform.create_autostart_manager(),
        mem_fn=mem_fn,
        disk_fn=disk_fn,
        decorated=decorated,
    )

    # ── Register + replay device scan → handlers created ─────────────────
    app.register(cast(Any, window))
    app._notify(AppEvent.DEVICES_CHANGED, list(app._devices.values()))
    app.start_metrics_loop(interval=2)

    # ── Run ──────────────────────────────────────────────────────────────
    signal.signal(signal.SIGINT, lambda *_: qapp.quit())
    window.show()

    print(f"\nConfig: {_DEV_TRCC / 'config.json'}")
    print(f"Data:   {_DEV_DATA}")
    print(f"Devices: {_DEVICES_JSON}")
    print("Close window or Ctrl+C to quit.")

    sys.exit(qapp.exec())


if __name__ == '__main__':
    main()
