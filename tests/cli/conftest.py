"""CLI layer test fixtures.

Fixtures inherit from each other following the same DI chain as production code:

    mock_device_info → mock_device_svc ──┐
    renderer + mock_media ───────────────┼→ display_svc (REAL)
                                         ├→ lcd (REAL LCDDevice) → mock_connect_lcd
    mock_led_svc → led → led_no_zones / led_no_segments
                 └→ led_empty (no svc)

Real services (DisplayService, OverlayService, ImageService) exercise actual
code paths. Only DeviceService (USB boundary) and MediaService are mocked.

Patch-path constants are exported so individual test files never hardcode
canonical module paths.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest

from trcc.core.lcd_device import LCDDevice
from trcc.core.led_device import LEDDevice
from trcc.services.display import DisplayService
from trcc.services.image import ImageService
from trcc.services.overlay import OverlayService

# ── Canonical patch targets ──────────────────────────────────────────────────
PATCH_SETTINGS = "trcc.conf.settings"
PATCH_SETTINGS_CLS = "trcc.conf.Settings"
PATCH_DATA_MANAGER = "trcc.adapters.infra.data_repository.DataManager"
PATCH_THEME_SVC = "trcc.services.ThemeService"
PATCH_IMAGE_SVC = "trcc.services.ImageService"
PATCH_CONNECT_LCD = "trcc.cli._display._connect_or_fail"
PATCH_CONNECT_LED = "trcc.cli._led._connect_or_fail"


# ── Real renderer ────────────────────────────────────────────────────────────

@pytest.fixture
def renderer() -> Any:
    """Real QtRenderer (offscreen) — same as test_display_integration."""
    return ImageService._r()


# ── LCD device chain (real services) ─────────────────────────────────────────

@pytest.fixture
def mock_device_info():
    """Mock DeviceInfo for the selected device."""
    dev = MagicMock()
    dev.resolution = (320, 320)
    dev.path = "/dev/sg0"
    dev.vid = 0x0402
    dev.pid = 0x3922
    dev.device_index = 0
    dev.encoding_params = ('scsi', (320, 320), None, False)
    return dev


@pytest.fixture
def mock_device_svc(mock_device_info):
    """Mock DeviceService with pre-selected device.

    Only the USB boundary is mocked — DeviceService sends raw frames
    to hardware. Everything above (DisplayService, OverlayService) is real.
    """
    svc = MagicMock()
    svc.selected = mock_device_info
    svc.send_frame.return_value = True
    svc.send_frame_async.return_value = None
    svc.is_busy = False
    return svc


@pytest.fixture
def mock_media():
    """Mock MediaService — video decoding boundary."""
    media = MagicMock()
    media._frames = []
    media.has_frames = False
    media.is_playing = False
    media.source_path = None
    media.get_frame.return_value = None
    media.frame_interval_ms = 33
    return media


@pytest.fixture
def display_svc(renderer, mock_media, mock_device_svc) -> DisplayService:
    """Real DisplayService with real OverlayService, mocked device/media.

    Sets resolution to 320x320 via conf.settings so lcd_size returns (320, 320).
    """
    import trcc.conf as _conf
    _conf.settings.set_resolution(320, 320, persist=False)
    overlay = OverlayService(320, 320, renderer=renderer)
    svc = DisplayService(mock_device_svc, overlay, mock_media)
    return svc


@pytest.fixture
def lcd(mock_device_svc, display_svc, renderer) -> LCDDevice:
    """LCDDevice wired to real DisplayService + real OverlayService.

    Only DeviceService (USB I/O) and MediaService (video decode) are mocked.
    """
    return LCDDevice(
        device_svc=mock_device_svc,
        display_svc=display_svc,
        theme_svc=MagicMock(),
        renderer=renderer,
    )


@pytest.fixture
def lcd_empty():
    """LCDDevice with no services (not connected)."""
    return LCDDevice()


# ── Connect fixtures ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_connect_lcd(lcd):
    """Patch LCD _connect_or_fail → 0 and wire TrccApp with mock lcd.

    TrccApp.lcd returns a MagicMock wrapping the real LCDDevice so CLI
    tests can set return_value on device methods.
    """
    from trcc.core.app import TrccApp
    mock_lcd = MagicMock(wraps=lcd)
    mock_lcd.device_path = "/dev/sg0"
    mock_lcd.lcd_size = (320, 320)
    mock_lcd.resolution = (320, 320)
    mock_app = TrccApp._instance
    mock_app.lcd_device = mock_lcd
    mock_app.lcd = mock_lcd
    mock_app.has_lcd = True
    with patch(PATCH_CONNECT_LCD, return_value=0):
        yield mock_lcd


@pytest.fixture
def mock_connect_led(led):
    """Patch LED _connect_or_fail → 0 and wire TrccApp with mock led."""
    from trcc.core.app import TrccApp
    mock_led = MagicMock(wraps=led)
    mock_app = TrccApp._instance
    mock_app.led_device = mock_led
    mock_app.led = mock_led
    mock_app.has_led = True
    with patch(PATCH_CONNECT_LED, return_value=0):
        yield mock_led


@pytest.fixture
def mock_connect_fail():
    """Patch both LCD and LED _connect_or_fail → 1 (no device)."""
    with patch(PATCH_CONNECT_LCD, return_value=1), \
         patch(PATCH_CONNECT_LED, return_value=1):
        yield


# ── LED device chain ─────────────────────────────────────────────────────────

@pytest.fixture
def mock_led_svc():
    """Fully mocked LEDService — no hardware required."""
    svc = MagicMock()
    svc.state = MagicMock()
    svc.state.zones = [MagicMock(), MagicMock(), MagicMock()]
    svc.state.segment_on = [True, False, True, False]
    svc.tick.return_value = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    svc.apply_mask.return_value = [(255, 0, 0), (0, 255, 0), (0, 0, 255)]
    svc.has_protocol = True
    return svc


@pytest.fixture
def led(mock_led_svc):
    """LEDDevice wired to mock service."""
    return LEDDevice(svc=mock_led_svc)


@pytest.fixture
def led_empty():
    """LEDDevice with no service (not connected)."""
    return LEDDevice()


@pytest.fixture
def led_no_zones(mock_led_svc):
    """LEDDevice with empty zone list."""
    mock_led_svc.state.zones = []
    return LEDDevice(svc=mock_led_svc)


@pytest.fixture
def led_no_segments(mock_led_svc):
    """LEDDevice with empty segment list."""
    mock_led_svc.state.segment_on = []
    return LEDDevice(svc=mock_led_svc)


# ── Theme factories ───────────────────────────────────────────────────────────

@pytest.fixture
def make_local_theme():
    """Factory: build a mock ThemeInfo for a local theme."""
    def _factory(
        name: str = "MyTheme",
        is_animated: bool = False,
        animation_path=None,
        bg_exists: bool = True,
        is_user: bool = False,
        theme_path: str = "/themes/MyTheme",
    ) -> MagicMock:
        t = MagicMock()
        t.name = name if not is_user else f"Custom_{name}"
        t.is_animated = is_animated
        t.animation_path = animation_path
        t.background_path = MagicMock()
        t.background_path.exists.return_value = bg_exists
        t.path = Path(theme_path)
        t.category = None
        return t
    return _factory


@pytest.fixture
def make_cloud_theme():
    """Factory: build a mock ThemeInfo for a cloud theme."""
    def _factory(name: str = "CloudTheme", category: str = "a") -> MagicMock:
        t = MagicMock()
        t.name = name
        t.category = category
        return t
    return _factory


@pytest.fixture
def mock_theme_dir():
    """Mock settings.theme_dir that exists with a valid path."""
    td = MagicMock()
    td.exists.return_value = True
    td.path = Path("/themes/320x320")
    return td


@pytest.fixture
def mock_web_dir():
    """Mock settings.web_dir that exists."""
    wd = MagicMock()
    wd.exists.return_value = True
    return wd


# ── Detection factory ─────────────────────────────────────────────────────────

@pytest.fixture
def make_detected_device():
    """Factory: build a mock detected device (DetectedDevice-like MagicMock)."""
    def _factory(
        scsi_device: str | None = "/dev/sg0",
        product_name: str = "Frost Commander 360",
        vid: int = 0x87CD,
        pid: int = 0x70DB,
        protocol: str = "scsi",
        implementation: str = "generic",
        device_type: int = 1,
        path: str = "/dev/sg0",
        usb_path: str = "1-2",
        resolution: tuple[int, int] = (0, 0),
    ) -> MagicMock:
        dev = MagicMock()
        dev.scsi_device = scsi_device
        dev.product_name = product_name
        dev.vid = vid
        dev.pid = pid
        dev.protocol = protocol
        dev.implementation = implementation
        dev.device_type = device_type
        dev.path = path
        dev.usb_path = usb_path
        dev.resolution = resolution
        return dev
    return _factory


# ── System test helpers ───────────────────────────────────────────────────────

@pytest.fixture
def completed_process():
    """Factory: build a minimal subprocess.CompletedProcess mock."""
    def _factory(returncode: int = 0, stdout: str = "", stderr: str = "") -> MagicMock:
        m = MagicMock()
        m.returncode = returncode
        m.stdout = stdout
        m.stderr = stderr
        return m
    return _factory


@pytest.fixture
def hardware_metrics():
    """Factory: build a HardwareMetrics-like mock with sensible defaults."""
    def _factory(**overrides) -> MagicMock:
        m = MagicMock()
        defaults: dict = {
            "cpu_temp": 42.0, "cpu_percent": 15.0, "cpu_freq": 3600.0, "cpu_power": 45.0,
            "gpu_temp": 0.0, "gpu_usage": 0.0, "gpu_clock": 0.0, "gpu_power": 0.0,
            "mem_temp": 0.0, "mem_percent": 60.0, "mem_clock": 0.0, "mem_available": 8.0,
            "disk_temp": 0.0, "disk_activity": 0.0, "disk_read": 0.0, "disk_write": 0.0,
            "net_up": 0.0, "net_down": 0.0, "net_total_up": 0.0, "net_total_down": 0.0,
            "fan_cpu": 0.0, "fan_gpu": 0.0, "fan_ssd": 0.0, "fan_sys2": 0.0,
            "date": "2026-02-28", "time": "12:00", "weekday": "Saturday",
        }
        defaults.update(overrides)
        m.__class__.__name__ = "HardwareMetrics"
        for k, v in defaults.items():
            setattr(m, k, v)
        return m
    return _factory
