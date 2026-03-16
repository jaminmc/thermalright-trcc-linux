"""Shared test fixtures for the TRCC Linux test suite.

Tier 0: Environment — disable live IPC daemon (tests must never route through GUI)
Tier 1: Data factories — DeviceInfo, mock devices, native renderer surfaces
Tier 2: Filesystem — isolated config dirs, theme dirs, temp PNGs
Tier 3: Qt — session-scoped QApplication (offscreen)
Tier 4: Performance report — Valgrind-style summary for CPU + memory tests
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image
from PySide6.QtWidgets import QApplication

from trcc.adapters.render.qt import QtRenderer
from trcc.core.models import DeviceInfo

# ═══════════════════════════════════════════════════════════════════════
# Performance report — Valgrind-style summary for test_cpu.py / test_memory.py
# Uses PerfReport from core/perf.py (domain object, hexagonal)
# ═══════════════════════════════════════════════════════════════════════
from trcc.core.perf import PerfReport
from trcc.services.image import ImageService


def pytest_configure(config: pytest.Config) -> None:
    """Register the perf report collector."""
    config._perf_report = PerfReport()  # type: ignore[attr-defined]


def pytest_terminal_summary(
    terminalreporter: Any, exitstatus: int, config: pytest.Config,
) -> None:
    """Print Valgrind-style performance summary after test run."""
    report: PerfReport = getattr(config, '_perf_report', None)  # type: ignore[assignment]
    if report and report.has_data:
        tw = terminalreporter._tw
        for line in report.format_report():
            tw.line(line)

# ── Qt + Renderer initialization (once per test session) ────────────────
# QApplication must exist before QtRenderer — QFontDatabase.addApplicationFont
# segfaults without one. Create it once at module level for all tests.
os.environ.setdefault('QT_QPA_PLATFORM', 'offscreen')
_app = QApplication.instance() or QApplication([])
ImageService.set_renderer(QtRenderer())

# =========================================================================
# Surface helpers — create/inspect native renderer surfaces in tests
# =========================================================================

def make_test_surface(
    w: int = 320, h: int = 320,
    color: tuple[int, ...] = (128, 0, 0),
) -> Any:
    """Create a native renderer surface (QImage) for testing.

    For RGB: pass 3-tuple. For RGBA: pass 4-tuple.
    """
    r = ImageService._r()
    return r.create_surface(w, h, color)


def surface_size(surface: Any) -> tuple[int, int]:
    """Get (width, height) from any renderer surface."""
    return ImageService._r().surface_size(surface)


def get_pixel(surface: Any, x: int, y: int) -> tuple[int, ...]:
    """Get pixel color from any renderer surface.

    Returns (r, g, b) for RGB surfaces, (r, g, b, a) for RGBA.
    Converts to PIL internally for uniform pixel access.
    """
    pil = ImageService._r().to_pil(surface)
    return pil.getpixel((x, y))

# =========================================================================
# Tier 0: Environment — disable live IPC daemon
# =========================================================================

@pytest.fixture(autouse=True)
def _no_ipc():
    """Prevent tests from routing through a live GUI/API instance.

    When the GUI or API is running, find_active() returns an InstanceKind
    and core routes through proxies, bypassing mocked services.
    Patch both the core detection and legacy IPCClient.available().
    """
    with patch("trcc.core.instance.find_active", return_value=None), \
         patch("trcc.ipc.IPCClient.available", return_value=False):
        yield

# =========================================================================
# Tier 1: Data factories
# =========================================================================

@pytest.fixture
def device_info():
    """Factory fixture: create DeviceInfo with sensible defaults."""
    def _make(
        path: str = "/dev/sg0",
        name: str = "LCD",
        vid: int = 0x87CD,
        pid: int = 0x70DB,
        protocol: str = "scsi",
        resolution: tuple[int, int] = (320, 320),
        **kw,
    ) -> DeviceInfo:
        return DeviceInfo(
            name=name, path=path, vid=vid, pid=pid,
            protocol=protocol, resolution=resolution, **kw,
        )
    return _make


@pytest.fixture
def mock_device():
    """Factory fixture: MagicMock DetectedDevice."""
    def _make(
        path: str = "/dev/sg0",
        name: str = "LCD",
        vid: int = 0x87CD,
        pid: int = 0x70DB,
        protocol: str = "scsi",
    ) -> MagicMock:
        dev = MagicMock()
        dev.scsi_device = path
        dev.product_name = name
        dev.vid = vid
        dev.pid = pid
        dev.protocol = protocol
        dev.usb_path = "1-2"
        dev.vendor_name = "Thermalright"
        return dev
    return _make


@pytest.fixture
def mock_service(device_info):
    """Factory fixture: mock DeviceService with pre-selected device."""
    def _make(device=None) -> MagicMock:
        svc = MagicMock()
        dev = device or device_info()
        svc.selected = dev
        svc.devices = [dev]
        svc.detect.return_value = svc.devices
        svc.send_pil.return_value = True
        return svc
    return _make


@pytest.fixture
def test_image():
    """Factory fixture: native renderer surface for testing."""
    def _make(w: int = 320, h: int = 320,
              color: tuple[int, ...] = (128, 0, 0)) -> Any:
        return make_test_surface(w, h, color)
    return _make


# =========================================================================
# Tier 2: Filesystem fixtures
# =========================================================================

@pytest.fixture(autouse=True)
def tmp_config(tmp_path, monkeypatch):
    """Isolated config dir — patches CONFIG_DIR/CONFIG_PATH to tmp_path.

    Autouse: no test should ever read from or write to the real ~/.trcc/config.json.
    Initializes Settings with a platform path resolver pointing to tmp_path.
    """
    config_dir = str(tmp_path / "trcc")
    config_path = str(tmp_path / "trcc" / "config.json")
    handshake_path = str(tmp_path / "trcc" / "last_handshake.json")
    os.makedirs(config_dir, exist_ok=True)
    monkeypatch.setattr("trcc.conf.CONFIG_DIR", config_dir)
    monkeypatch.setattr("trcc.conf.CONFIG_PATH", config_path)
    monkeypatch.setattr("trcc.conf._HANDSHAKE_CACHE_PATH", handshake_path)

    # Initialize Settings with a test path resolver (DI)
    # Uses tmp_path so tests never touch real ~/.trcc/
    from unittest.mock import MagicMock

    from trcc.conf import init_settings

    resolver = MagicMock()
    resolver.config_dir.return_value = config_dir
    resolver.data_dir.return_value = str(tmp_path / "trcc" / "data")
    resolver.user_content_dir.return_value = str(tmp_path / "trcc-user")
    resolver.theme_dir.side_effect = lambda w, h: str(tmp_path / "trcc" / "data" / f"theme{w}{h}")
    resolver.web_dir.side_effect = lambda w, h: str(tmp_path / "trcc" / "data" / "web" / f"{w}{h}")
    resolver.web_masks_dir.side_effect = lambda w, h: str(tmp_path / "trcc" / "data" / "web" / f"zt{w}{h}")
    resolver.user_masks_dir.side_effect = lambda w, h: str(tmp_path / "trcc-user" / "data" / "web" / f"zt{w}{h}")
    os.makedirs(str(tmp_path / "trcc" / "data"), exist_ok=True)
    init_settings(resolver)

    return tmp_path


@pytest.fixture
def theme_dir(tmp_path):
    """Factory fixture: create a valid theme directory structure."""
    def _make(name: str = "TestTheme", *, has_bg: bool = True,
              has_dc: bool = False, has_mask: bool = False) -> Path:
        td = tmp_path / name
        td.mkdir(exist_ok=True)
        if has_bg:
            Image.new("RGB", (320, 320), (0, 0, 0)).save(str(td / "00.png"))
        if has_dc:
            # Minimal 0xDD format stub
            (td / "config1.dc").write_bytes(b"\xDD" + b"\x00" * 100)
        if has_mask:
            Image.new("RGBA", (320, 320), (255, 255, 255, 128)).save(
                str(td / "mask.png"))
        return td
    return _make


@pytest.fixture
def png_factory(tmp_path):
    """Factory fixture: write a minimal PNG and return its path."""
    def _make(filename: str = "test.png", w: int = 320, h: int = 320) -> str:
        path = str(tmp_path / filename)
        Image.new("RGB", (w, h), (128, 0, 0)).save(path, "PNG")
        return path
    return _make


# =========================================================================
# Tier 3: Qt fixture
# =========================================================================

@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for all GUI tests (offscreen).

    Reuses the module-level _app created at conftest import time.
    """
    return _app


# =========================================================================
# Legacy factory functions — used by test_cli.py and test_integration.py
# =========================================================================

def make_device_info(
    path: str = "/dev/sg0",
    name: str = "LCD",
    vid: int = 0x87CD,
    pid: int = 0x70DB,
    protocol: str = "scsi",
    resolution: tuple[int, int] = (320, 320),
    **kw,
) -> DeviceInfo:
    """Create DeviceInfo with sensible defaults. Used by test_cli."""
    return DeviceInfo(
        name=name, path=path, vid=vid, pid=pid,
        protocol=protocol, resolution=resolution, **kw,
    )


def make_mock_service(device: DeviceInfo | None = None) -> MagicMock:
    """Create mock DeviceService with pre-selected device. Used by test_cli."""
    svc = MagicMock()
    dev = device or make_device_info()
    svc.selected = dev
    svc.devices = [dev]
    svc.detect.return_value = svc.devices
    svc.send_pil.return_value = True
    return svc


def save_test_png(path: str, w: int = 320, h: int = 320) -> None:
    """Write a minimal PNG at path. Used by test_integration."""
    make_test_surface(w, h).save(path, "PNG")


def make_device_service(**overrides):
    """Create a DeviceService with mock adapter deps (no RuntimeError).

    Use this in tests that construct DeviceService directly. All adapter
    callables default to MagicMock so construction never raises.
    """
    from trcc.services import DeviceService

    defaults = {
        'detect_fn': MagicMock(return_value=[]),
        'probe_led_fn': MagicMock(return_value=None),
        'get_protocol': MagicMock(return_value=MagicMock()),
        'get_protocol_info': MagicMock(return_value=None),
    }
    defaults.update(overrides)
    return DeviceService(**defaults)
