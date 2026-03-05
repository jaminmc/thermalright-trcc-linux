"""Shared test fixtures for the TRCC Linux test suite.

Tier 0: Environment — disable live IPC daemon (tests must never route through GUI)
Tier 1: Data factories — DeviceInfo, mock devices, native renderer surfaces
Tier 2: Filesystem — isolated config dirs, theme dirs, temp PNGs
Tier 3: Service — pre-wired LED/Display dispatchers
Tier 4: Qt — session-scoped QApplication (offscreen)
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from trcc.core.models import DeviceInfo
from trcc.services.image import ImageService

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
    """Prevent tests from routing through a live GUI IPC daemon.

    When the GUI is running, IPCClient.available() returns True and CLI
    functions short-circuit to IPC proxies, bypassing mocked services.
    """
    with patch("trcc.ipc.IPCClient.available", return_value=False):
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

@pytest.fixture
def tmp_config(tmp_path, monkeypatch):
    """Isolated config dir — patches CONFIG_DIR/CONFIG_PATH to tmp_path."""
    config_dir = str(tmp_path / "trcc")
    config_path = str(tmp_path / "trcc" / "config.json")
    handshake_path = str(tmp_path / "trcc" / "last_handshake.json")
    os.makedirs(config_dir, exist_ok=True)
    monkeypatch.setattr("trcc.conf.CONFIG_DIR", config_dir)
    monkeypatch.setattr("trcc.conf.CONFIG_PATH", config_path)
    monkeypatch.setattr("trcc.conf._HANDSHAKE_CACHE_PATH", handshake_path)
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
# Tier 3: Service fixtures
# =========================================================================

@pytest.fixture
def led_dispatcher():
    """LEDDispatcher with fully mocked service — no hardware."""
    from trcc.cli._led import LEDDispatcher

    svc = MagicMock()
    svc.state = MagicMock()
    svc.state.global_on = True
    svc.state.brightness = 100
    svc.state.color = (255, 0, 0)
    svc.state.zones = [MagicMock() for _ in range(4)]
    svc.state.segment_on = [True] * 8
    svc.tick.return_value = [(255, 0, 0)] * 64

    disp = LEDDispatcher.__new__(LEDDispatcher)
    disp._service = svc
    disp._device = MagicMock()
    disp._segment = MagicMock()
    return disp


@pytest.fixture
def display_dispatcher():
    """DisplayDispatcher with fully mocked service — no hardware."""
    from trcc.cli._display import DisplayDispatcher

    svc = MagicMock()
    svc.selected = MagicMock()
    svc.selected.resolution = (320, 320)
    svc.send_pil.return_value = True

    disp = DisplayDispatcher.__new__(DisplayDispatcher)
    disp._service = svc
    disp._dev = svc.selected
    return disp


# =========================================================================
# Tier 4: Qt fixture
# =========================================================================

@pytest.fixture(scope="session")
def qapp():
    """Session-scoped QApplication for all GUI tests (offscreen)."""
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    try:
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance() or QApplication([])
        return app
    except ImportError:
        pytest.skip("PySide6 not available")


# =========================================================================
# Legacy factory functions (backward compat — 3 callers)
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
    """Legacy: prefer device_info fixture. Used by test_cli, test_controllers."""
    return DeviceInfo(
        name=name, path=path, vid=vid, pid=pid,
        protocol=protocol, resolution=resolution, **kw,
    )


def make_mock_device(
    path: str = "/dev/sg0",
    name: str = "LCD",
    vid: int = 0x87CD,
    pid: int = 0x70DB,
    protocol: str = "scsi",
) -> MagicMock:
    """Legacy: prefer mock_device fixture."""
    dev = MagicMock()
    dev.scsi_device = path
    dev.product_name = name
    dev.vid = vid
    dev.pid = pid
    dev.protocol = protocol
    dev.usb_path = "1-2"
    dev.vendor_name = "Thermalright"
    return dev


def make_mock_service(device: DeviceInfo | None = None) -> MagicMock:
    """Legacy: prefer mock_service fixture. Used by test_cli."""
    svc = MagicMock()
    dev = device or make_device_info()
    svc.selected = dev
    svc.devices = [dev]
    svc.detect.return_value = svc.devices
    svc.send_pil.return_value = True
    return svc


def make_test_image(
    w: int = 320, h: int = 320, color: tuple[int, ...] = (128, 0, 0),
) -> Any:
    """Legacy: prefer test_image fixture. Used by test_controllers."""
    return make_test_surface(w, h, color)


def save_test_png(path: str, w: int = 320, h: int = 320) -> None:
    """Legacy: prefer png_factory fixture. Used by test_integration."""
    make_test_image(w, h).save(path, "PNG")
