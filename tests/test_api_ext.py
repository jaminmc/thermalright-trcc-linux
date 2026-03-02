"""Extended API tests — coverage for error paths, edge cases, and uncovered endpoints.

Complements tests/test_api.py.  All test classes use FastAPI TestClient.
"""
from __future__ import annotations

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from PIL import Image

import trcc.api as api_module
from trcc.api import _device_svc, app, configure_auth
from trcc.api.models import dispatch_result, parse_hex_or_400
from trcc.core.models import DeviceInfo

# ── Helpers ───────────────────────────────────────────────────────────────────

def _make_client() -> TestClient:
    configure_auth(None)
    return TestClient(app)


def _png_bytes(w: int = 50, h: int = 50) -> bytes:
    img = Image.new("RGB", (w, h), (128, 64, 32))
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _scsi_dev(**overrides) -> DeviceInfo:
    defaults = dict(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                    protocol="scsi", resolution=(320, 320))
    defaults.update(overrides)
    return DeviceInfo(**defaults)


# ── Auth middleware edge cases ────────────────────────────────────────────────

class TestAuthEdgeCases(unittest.TestCase):
    """Edge cases in token auth middleware not covered by existing tests."""

    def tearDown(self) -> None:
        configure_auth(None)

    def test_empty_string_token_treated_as_no_auth(self) -> None:
        """configure_auth('') means falsy — all requests pass."""
        configure_auth("")
        client = TestClient(app)
        resp = client.get("/devices")
        self.assertEqual(resp.status_code, 200)

    def test_wrong_token_body_contains_detail(self) -> None:
        configure_auth("mytoken")
        client = TestClient(app)
        resp = client.get("/devices", headers={"X-API-Token": "badtoken"})
        self.assertEqual(resp.status_code, 401)
        self.assertIn("detail", resp.json())

    def test_token_header_case_sensitive(self) -> None:
        """Header name must be exactly X-API-Token (FastAPI lowercases, but value is case-sensitive)."""
        configure_auth("Secret")
        client = TestClient(app)
        # Correct name, wrong case for the value
        resp = client.get("/devices", headers={"X-API-Token": "secret"})
        self.assertEqual(resp.status_code, 401)

    def test_health_endpoint_bypasses_auth_any_token(self) -> None:
        """Any /health request passes even with a completely wrong token."""
        configure_auth("valid_token")
        client = TestClient(app)
        resp = client.get("/health", headers={"X-API-Token": "completely_wrong"})
        self.assertEqual(resp.status_code, 200)

    def test_token_required_for_post_endpoints(self) -> None:
        """POST /devices/detect also requires auth when token is set."""
        configure_auth("tok123")
        client = TestClient(app)
        resp = client.post("/devices/detect")
        self.assertEqual(resp.status_code, 401)


# ── Health response shape ─────────────────────────────────────────────────────

class TestHealthShape(unittest.TestCase):
    """Health endpoint response field types."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)

    def test_health_version_is_string(self) -> None:
        resp = self.client.get("/health")
        self.assertIsInstance(resp.json()["version"], str)

    def test_health_status_is_ok(self) -> None:
        resp = self.client.get("/health")
        self.assertEqual(resp.json()["status"], "ok")


# ── Device endpoint edge cases ────────────────────────────────────────────────

class TestDeviceEdgeCases(unittest.TestCase):
    """Uncovered device endpoint paths."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)
        _device_svc._devices = []
        _device_svc._selected = None

    def test_list_devices_multiple(self) -> None:
        _device_svc._devices = [
            _scsi_dev(name="LCD1", resolution=(320, 320)),
            _scsi_dev(name="LCD2", path="/dev/sg1", pid=0x3923, resolution=(480, 480)),
        ]
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["id"], 0)
        self.assertEqual(data[1]["id"], 1)

    def test_get_device_response_fields(self) -> None:
        _device_svc._devices = [_scsi_dev()]
        resp = self.client.get("/devices/0")
        self.assertEqual(resp.status_code, 200)
        d = resp.json()
        for field in ("id", "name", "vid", "pid", "protocol", "resolution", "path"):
            self.assertIn(field, d, f"Missing field: {field}")

    def test_get_device_negative_index(self) -> None:
        """Negative index treated as out-of-range — 404."""
        _device_svc._devices = [_scsi_dev()]
        resp = self.client.get("/devices/-1")
        self.assertEqual(resp.status_code, 404)

    def test_detect_returns_list_shape(self) -> None:
        with patch.object(_device_svc, "detect") as mock_detect:
            mock_detect.return_value = []
            _device_svc._devices = [_scsi_dev(name="Found")]
            resp = self.client.post("/devices/detect")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, list)

    def test_select_lcd_device_sets_display_dispatcher(self) -> None:
        """Selecting an LCD device sets api._display_dispatcher."""
        dev = _scsi_dev(resolution=(320, 320))
        _device_svc._devices = [dev]
        with patch("trcc.cli._device.discover_resolution"), \
             patch("trcc.cli._display.DisplayDispatcher") as mock_disp_cls, \
             patch("trcc.api.mount_static_dirs"):
            mock_disp = MagicMock()
            mock_disp_cls.return_value = mock_disp
            resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("selected", resp.json())

    def test_select_led_device_failed_connect_clears_dispatcher(self) -> None:
        """If LEDDispatcher.connect() fails, _led_dispatcher stays None."""
        dev = DeviceInfo(name="HR10", path="hid:0416:8001", vid=0x0416, pid=0x8001,
                         protocol="led", implementation="hid_led")
        _device_svc._devices = [dev]
        with patch("trcc.cli._led.LEDDispatcher") as mock_cls:
            mock_inst = MagicMock()
            mock_inst.connect.return_value = {"success": False, "error": "USB error"}
            mock_cls.return_value = mock_inst
            resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        self.assertIsNone(api_module._led_dispatcher)

    def test_select_response_contains_resolution(self) -> None:
        dev = _scsi_dev(resolution=(480, 480))
        _device_svc._devices = [dev]
        with patch("trcc.cli._device.discover_resolution"), \
             patch("trcc.cli._display.DisplayDispatcher"), \
             patch("trcc.api.mount_static_dirs"):
            resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("resolution", resp.json())


# ── send_image edge cases ─────────────────────────────────────────────────────

class TestSendImageEdgeCases(unittest.TestCase):
    """Paths not covered in TestSendImage."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)
        dev = _scsi_dev(resolution=(320, 320))
        _device_svc._devices = [dev]
        _device_svc._selected = None

    def test_send_with_brightness_param(self) -> None:
        with patch.object(_device_svc, "send_pil", return_value=True):
            resp = self.client.post(
                "/devices/0/send?brightness=50",
                files={"image": ("t.png", io.BytesIO(_png_bytes()), "image/png")},
            )
        self.assertEqual(resp.status_code, 200)

    def test_send_resolution_zero_cannot_discover_raises_503(self) -> None:
        """If resolution stays (0,0) after handshake, endpoint returns 503."""
        dev = _scsi_dev(resolution=(0, 0))
        _device_svc._devices = [dev]
        with patch("trcc.adapters.device.factory.DeviceProtocolFactory.get_protocol") as mock_gp:
            mock_protocol = MagicMock()
            mock_protocol.handshake.return_value = None
            mock_gp.return_value = mock_protocol
            resp = self.client.post(
                "/devices/0/send",
                files={"image": ("t.png", io.BytesIO(_png_bytes()), "image/png")},
            )
        self.assertEqual(resp.status_code, 503)

    def test_send_corrupt_image_returns_400(self) -> None:
        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("broken.png", io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"\x00" * 8), "image/png")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_send_empty_file_returns_400(self) -> None:
        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("empty.png", io.BytesIO(b""), "image/png")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_send_response_has_resolution_field(self) -> None:
        with patch.object(_device_svc, "send_pil", return_value=True):
            resp = self.client.post(
                "/devices/0/send",
                files={"image": ("t.png", io.BytesIO(_png_bytes()), "image/png")},
            )
        self.assertEqual(resp.status_code, 200)
        self.assertIn("resolution", resp.json())


# ── Display endpoint error paths ──────────────────────────────────────────────

class TestDisplayErrorPaths(unittest.TestCase):
    """409 / 422 paths and disconnected-dispatcher state."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)
        self.mock_lcd = MagicMock()
        self.mock_lcd.connected = True
        self.mock_lcd.resolution = (320, 320)
        self.mock_lcd.device_path = "/dev/sg0"
        api_module._display_dispatcher = self.mock_lcd

    def tearDown(self) -> None:
        api_module._display_dispatcher = None

    def test_brightness_zero_rejected_by_pydantic(self) -> None:
        """level=0 violates Field(ge=1)."""
        resp = self.client.post("/display/brightness", json={"level": 0})
        self.assertEqual(resp.status_code, 422)

    def test_brightness_negative_rejected(self) -> None:
        resp = self.client.post("/display/brightness", json={"level": -1})
        self.assertEqual(resp.status_code, 422)

    def test_split_mode_out_of_range(self) -> None:
        """mode=4 violates Field(le=3)."""
        resp = self.client.post("/display/split", json={"mode": 4})
        self.assertEqual(resp.status_code, 422)

    def test_split_mode_negative_rejected(self) -> None:
        resp = self.client.post("/display/split", json={"mode": -1})
        self.assertEqual(resp.status_code, 422)

    def test_color_too_short_rejected(self) -> None:
        resp = self.client.post("/display/color", json={"hex": "ff00"})
        self.assertEqual(resp.status_code, 400)

    def test_color_eight_digit_hex_rejected(self) -> None:
        """8-digit hex (RGBA) is not a valid 6-digit hex color."""
        resp = self.client.post("/display/color", json={"hex": "ff0000ff"})
        self.assertEqual(resp.status_code, 400)

    def test_rotation_no_device_returns_409(self) -> None:
        api_module._display_dispatcher = None
        resp = self.client.post("/display/rotation", json={"degrees": 0})
        self.assertEqual(resp.status_code, 409)

    def test_brightness_no_device_returns_409(self) -> None:
        api_module._display_dispatcher = None
        resp = self.client.post("/display/brightness", json={"level": 1})
        self.assertEqual(resp.status_code, 409)

    def test_split_no_device_returns_409(self) -> None:
        api_module._display_dispatcher = None
        resp = self.client.post("/display/split", json={"mode": 0})
        self.assertEqual(resp.status_code, 409)

    def test_reset_no_device_returns_409(self) -> None:
        api_module._display_dispatcher = None
        resp = self.client.post("/display/reset")
        self.assertEqual(resp.status_code, 409)

    def test_overlay_no_device_returns_409(self) -> None:
        api_module._display_dispatcher = None
        resp = self.client.post("/display/overlay?dc_path=/tmp/nope.dc")
        self.assertEqual(resp.status_code, 409)

    def test_mask_too_large_returns_413(self) -> None:
        big = io.BytesIO(b"\x00" * (11 * 1024 * 1024))
        resp = self.client.post(
            "/display/mask",
            files={"image": ("big.png", big, "image/png")},
        )
        self.assertEqual(resp.status_code, 413)

    def test_display_status_disconnected_dispatcher(self) -> None:
        """Dispatcher present but connected=False → disconnected response."""
        self.mock_lcd.connected = False
        resp = self.client.get("/display/status")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["connected"])

    def test_display_status_has_device_path(self) -> None:
        resp = self.client.get("/display/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("device_path", resp.json())


# ── LED endpoint error paths ──────────────────────────────────────────────────

class TestLEDErrorPaths(unittest.TestCase):
    """LED 409 / 422 paths and dispatch-failure cases."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)
        self.mock_led = MagicMock()
        self.mock_led.connected = True
        self.mock_led.status = "PA120 (style 2)"
        api_module._led_dispatcher = self.mock_led

    def tearDown(self) -> None:
        api_module._led_dispatcher = None

    def test_brightness_over_100_rejected(self) -> None:
        resp = self.client.post("/led/brightness", json={"level": 101})
        self.assertEqual(resp.status_code, 422)

    def test_brightness_negative_rejected(self) -> None:
        resp = self.client.post("/led/brightness", json={"level": -1})
        self.assertEqual(resp.status_code, 422)

    def test_color_empty_string_rejected(self) -> None:
        resp = self.client.post("/led/color", json={"hex": ""})
        self.assertEqual(resp.status_code, 400)

    def test_mode_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/mode", json={"mode": "breathing"})
        self.assertEqual(resp.status_code, 409)

    def test_off_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/off")
        self.assertEqual(resp.status_code, 409)

    def test_sensor_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/sensor", json={"source": "cpu"})
        self.assertEqual(resp.status_code, 409)

    def test_zone_color_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/zones/0/color", json={"hex": "ff0000"})
        self.assertEqual(resp.status_code, 409)

    def test_clock_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/clock", json={"is_24h": False})
        self.assertEqual(resp.status_code, 409)

    def test_temp_unit_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/temp-unit", json={"unit": "C"})
        self.assertEqual(resp.status_code, 409)

    def test_segment_toggle_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/segments/0/toggle", json={"on": True})
        self.assertEqual(resp.status_code, 409)

    def test_sync_no_device_returns_409(self) -> None:
        api_module._led_dispatcher = None
        resp = self.client.post("/led/sync", json={"enabled": True})
        self.assertEqual(resp.status_code, 409)

    def test_led_status_disconnected_dispatcher(self) -> None:
        """Dispatcher present but connected=False → disconnected response."""
        self.mock_led.connected = False
        resp = self.client.get("/led/status")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["connected"])

    def test_set_color_hex_with_hash_prefix(self) -> None:
        self.mock_led.set_color.return_value = {"success": True, "message": "ok"}
        resp = self.client.post("/led/color", json={"hex": "#aabbcc"})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_color.assert_called_once_with(0xAA, 0xBB, 0xCC)

    def test_zone_sync_without_interval(self) -> None:
        """interval is optional — None is valid."""
        self.mock_led.set_zone_sync.return_value = {"success": True, "message": "ok"}
        resp = self.client.post("/led/sync", json={"enabled": False})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_zone_sync.assert_called_once_with(False, None)


# ── Theme endpoint edge cases ─────────────────────────────────────────────────

class TestThemeEdgeCases(unittest.TestCase):
    """Uncovered theme paths."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)
        api_module._display_dispatcher = None

    def tearDown(self) -> None:
        api_module._display_dispatcher = None

    def test_list_themes_resolution_boundary_min(self) -> None:
        """100x100 is the minimum valid resolution."""
        with patch("trcc.api.themes.ThemeService.discover_local", return_value=[]), \
             patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_td:
            mock_td.return_value = MagicMock(path="/tmp/none", __str__=lambda s: "/tmp/none")
            resp = self.client.get("/themes?resolution=100x100")
        self.assertEqual(resp.status_code, 200)

    def test_list_themes_resolution_out_of_range(self) -> None:
        """99x99 is below the 100-pixel minimum — 400."""
        resp = self.client.get("/themes?resolution=99x99")
        self.assertEqual(resp.status_code, 400)

    def test_list_themes_resolution_above_max(self) -> None:
        """4097x4097 exceeds the 4096-pixel maximum — 400."""
        resp = self.client.get("/themes?resolution=4097x4097")
        self.assertEqual(resp.status_code, 400)

    def test_list_themes_missing_x_separator(self) -> None:
        resp = self.client.get("/themes?resolution=320320")
        self.assertEqual(resp.status_code, 400)

    def test_list_web_themes_resolution_out_of_range(self) -> None:
        resp = self.client.get("/themes/web?resolution=50x50")
        self.assertEqual(resp.status_code, 400)

    def test_list_masks_resolution_out_of_range(self) -> None:
        resp = self.client.get("/themes/masks?resolution=9999x9999")
        self.assertEqual(resp.status_code, 400)

    def test_import_theme_correct_extension_accepted(self) -> None:
        """A .tr file passes extension check (content validation may still fail)."""
        data = b"not-a-real-tr-archive"
        with patch("trcc.api.themes.ThemeService.import_tr", return_value=(True, "ok")), \
             patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_td:
            mock_td.return_value = MagicMock(path="/tmp", __str__=lambda s: "/tmp")
            resp = self.client.post(
                "/themes/import",
                files={"file": ("my_theme.tr", io.BytesIO(data), "application/octet-stream")},
            )
        self.assertEqual(resp.status_code, 200)

    def test_import_theme_too_large_returns_413(self) -> None:
        big = io.BytesIO(b"\x00" * (51 * 1024 * 1024))
        resp = self.client.post(
            "/themes/import",
            files={"file": ("huge.tr", big, "application/octet-stream")},
        )
        self.assertEqual(resp.status_code, 413)

    def test_import_theme_service_error_returns_400(self) -> None:
        """ThemeService.import_tr returning (False, msg) → 400."""
        with patch("trcc.api.themes.ThemeService.import_tr", return_value=(False, "bad archive")), \
             patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_td:
            mock_td.return_value = MagicMock(path="/tmp", __str__=lambda s: "/tmp")
            resp = self.client.post(
                "/themes/import",
                files={"file": ("x.tr", io.BytesIO(b"junk"), "application/octet-stream")},
            )
        self.assertEqual(resp.status_code, 400)

    def test_save_theme_empty_config_returns_500(self) -> None:
        """load_config() returning empty dict → 500."""
        with patch("trcc.conf.load_config", return_value={}):
            resp = self.client.post("/themes/save", json={"name": "Empty"})
        self.assertEqual(resp.status_code, 500)

    def test_load_theme_sends_image_to_device(self) -> None:
        """Successful theme load calls device_svc.send_pil."""
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd

        mock_theme = MagicMock()
        mock_theme.name = "Theme001"
        mock_theme.config_path = None

        with tempfile.TemporaryDirectory() as td:
            theme_dir = Path(td) / "Theme001"
            theme_dir.mkdir()
            img_path = theme_dir / "01.png"
            Image.new("RGB", (320, 320), "blue").save(img_path)

            with patch("trcc.api.themes.ThemeService.discover_local", return_value=[mock_theme]), \
                 patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_tdr, \
                 patch.object(_device_svc, "send_pil", return_value=True):
                mock_tdr.return_value = MagicMock(
                    path=td,
                    __str__=lambda s: td,
                )
                resp = self.client.post("/themes/load", json={"name": "Theme001"})

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["theme"], "Theme001")

    def test_load_theme_send_failure_returns_500(self) -> None:
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd

        mock_theme = MagicMock()
        mock_theme.name = "BrokenTheme"
        mock_theme.config_path = None

        with tempfile.TemporaryDirectory() as td:
            theme_dir = Path(td) / "BrokenTheme"
            theme_dir.mkdir()
            Image.new("RGB", (100, 100)).save(theme_dir / "01.png")

            with patch("trcc.api.themes.ThemeService.discover_local", return_value=[mock_theme]), \
                 patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_tdr, \
                 patch.object(_device_svc, "send_pil", return_value=False):
                mock_tdr.return_value = MagicMock(path=td, __str__=lambda s: td)
                resp = self.client.post("/themes/load", json={"name": "BrokenTheme"})

        self.assertEqual(resp.status_code, 500)

    def test_load_theme_no_image_file_returns_404(self) -> None:
        """Theme directory exists but contains no image files → 404."""
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd

        mock_theme = MagicMock()
        mock_theme.name = "NoImages"
        mock_theme.config_path = None

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "NoImages").mkdir()  # empty theme directory

            with patch("trcc.api.themes.ThemeService.discover_local", return_value=[mock_theme]), \
                 patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_tdr:
                mock_tdr.return_value = MagicMock(path=td, __str__=lambda s: td)
                resp = self.client.post("/themes/load", json={"name": "NoImages"})

        self.assertEqual(resp.status_code, 404)

    def test_load_theme_with_jpg_fallback(self) -> None:
        """Theme without 01.png falls back to any .jpg file."""
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd

        mock_theme = MagicMock()
        mock_theme.name = "JpgTheme"
        mock_theme.config_path = None

        with tempfile.TemporaryDirectory() as td:
            theme_dir = Path(td) / "JpgTheme"
            theme_dir.mkdir()
            Image.new("RGB", (320, 320)).save(theme_dir / "preview.jpg")

            with patch("trcc.api.themes.ThemeService.discover_local", return_value=[mock_theme]), \
                 patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_tdr, \
                 patch.object(_device_svc, "send_pil", return_value=True):
                mock_tdr.return_value = MagicMock(path=td, __str__=lambda s: td)
                resp = self.client.post("/themes/load", json={"name": "JpgTheme"})

        self.assertEqual(resp.status_code, 200)

    def test_list_masks_with_dirs_having_theme_png(self) -> None:
        """Mask dirs containing Theme.png are returned with /static/masks/<name>/Theme.png."""
        with tempfile.TemporaryDirectory() as td:
            mask_dir = Path(td) / "MaskA"
            mask_dir.mkdir()
            (mask_dir / "Theme.png").write_bytes(b"fake")

            with patch("trcc.adapters.infra.data_repository.DataManager.get_web_masks_dir",
                       return_value=td):
                resp = self.client.get("/themes/masks?resolution=320x320")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "MaskA")
        self.assertIn("Theme.png", data[0]["preview_url"])

    def test_list_masks_dirs_without_known_image_are_skipped(self) -> None:
        """Mask dirs that have neither Theme.png nor 00.png are excluded."""
        with tempfile.TemporaryDirectory() as td:
            mask_dir = Path(td) / "MaskEmpty"
            mask_dir.mkdir()
            (mask_dir / "something.txt").write_text("ignored")

            with patch("trcc.adapters.infra.data_repository.DataManager.get_web_masks_dir",
                       return_value=td):
                resp = self.client.get("/themes/masks?resolution=320x320")

        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_list_web_themes_video_flag(self) -> None:
        """has_video=True when matching .mp4 file exists alongside the .png."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "a001.png").write_bytes(b"fake")
            (Path(td) / "a001.mp4").write_bytes(b"fake")

            with patch("trcc.adapters.infra.data_repository.DataManager.get_web_dir",
                       return_value=td):
                resp = self.client.get("/themes/web?resolution=320x320")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertTrue(data[0]["has_video"])

    def test_list_web_themes_no_video_flag(self) -> None:
        """has_video=False when no matching .mp4 exists."""
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "b002.png").write_bytes(b"fake")

            with patch("trcc.adapters.infra.data_repository.DataManager.get_web_dir",
                       return_value=td):
                resp = self.client.get("/themes/web?resolution=480x480")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]["has_video"])


# ── System endpoint edge cases ────────────────────────────────────────────────

class TestSystemEdgeCases(unittest.TestCase):
    """Additional system endpoint paths."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)

    def tearDown(self) -> None:
        api_module._system_svc = None

    def _mock_svc_with_metrics(self, **kw):
        from trcc.core.models import HardwareMetrics
        svc = MagicMock()
        m = HardwareMetrics()
        for attr, val in kw.items():
            setattr(m, attr, val)
        svc.all_metrics = m
        api_module._system_svc = svc
        return svc

    def test_get_metrics_memory_category(self) -> None:
        self._mock_svc_with_metrics(mem_percent=80.0, mem_available=4096.0)
        resp = self.client.get("/system/metrics/mem")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("mem_percent", data)
        self.assertNotIn("cpu_temp", data)

    def test_get_metrics_memory_alias(self) -> None:
        """'memory' is aliased to 'mem_' prefix."""
        self._mock_svc_with_metrics(mem_percent=55.0)
        resp = self.client.get("/system/metrics/memory")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("mem_percent", resp.json())

    def test_get_metrics_disk_category(self) -> None:
        self._mock_svc_with_metrics(disk_activity=42.0)
        resp = self.client.get("/system/metrics/disk")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("disk_activity", data)

    def test_get_metrics_network_category(self) -> None:
        self._mock_svc_with_metrics(net_up=100.0)
        resp = self.client.get("/system/metrics/net")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("net_up", resp.json())

    def test_get_metrics_network_alias(self) -> None:
        self._mock_svc_with_metrics(net_down=50.0)
        resp = self.client.get("/system/metrics/network")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("net_down", resp.json())

    def test_get_metrics_fan_category(self) -> None:
        self._mock_svc_with_metrics(fan_cpu=1200.0)
        resp = self.client.get("/system/metrics/fan")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("fan_cpu", resp.json())

    def test_get_metrics_gpu_category(self) -> None:
        self._mock_svc_with_metrics(gpu_temp=85.0)
        resp = self.client.get("/system/metrics/gpu")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("gpu_temp", data)
        self.assertNotIn("cpu_temp", data)

    def test_get_metrics_invalid_category_detail_lists_valid(self) -> None:
        """400 response detail should list valid categories."""
        self._mock_svc_with_metrics()
        resp = self.client.get("/system/metrics/poweruser")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cpu", resp.json()["detail"])

    def test_get_metrics_all_fields_present(self) -> None:
        """GET /system/metrics returns a non-empty dict with at least cpu_temp."""
        self._mock_svc_with_metrics(cpu_temp=72.5)
        resp = self.client.get("/system/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, dict)
        self.assertIn("cpu_temp", data)
        self.assertEqual(data["cpu_temp"], 72.5)

    def test_system_svc_lazily_created(self) -> None:
        """_system_svc is None at start; endpoint creates it on first call."""
        api_module._system_svc = None
        with patch("trcc.services.SystemService") as mock_cls:
            mock_inst = MagicMock()
            from trcc.core.models import HardwareMetrics
            mock_inst.all_metrics = HardwareMetrics()
            mock_cls.return_value = mock_inst
            resp = self.client.get("/system/metrics")
        self.assertEqual(resp.status_code, 200)
        mock_cls.assert_called_once()


# ── Static mount edge cases ───────────────────────────────────────────────────

class TestStaticMountEdgeCases(unittest.TestCase):
    """mount_static_dirs() with non-existent directories."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)

    def test_mount_static_dirs_nonexistent_web_dir_skipped(self) -> None:
        """If web_dir does not exist, no /static/web mount is added."""
        from trcc.api import _mounted_routes, mount_static_dirs

        with patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.adapters.infra.data_repository.DataManager.get_web_dir",
                   return_value="/nonexistent/web"), \
             patch("trcc.adapters.infra.data_repository.DataManager.get_web_masks_dir",
                   return_value="/nonexistent/masks"):
            mock_td_obj = MagicMock()
            mock_td_obj.path = "/nonexistent/themes"
            mock_td.return_value = mock_td_obj
            mount_static_dirs(320, 320)

        self.assertNotIn("/static/web", _mounted_routes)
        self.assertNotIn("/static/masks", _mounted_routes)

    def test_mount_static_dirs_clears_old_routes(self) -> None:
        """Calling mount_static_dirs twice does not accumulate duplicate entries."""
        from trcc.api import _mounted_routes, mount_static_dirs

        with patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_td, \
             patch("trcc.adapters.infra.data_repository.DataManager.get_web_dir",
                   return_value="/nonexistent"), \
             patch("trcc.adapters.infra.data_repository.DataManager.get_web_masks_dir",
                   return_value="/nonexistent"):
            mock_td_obj = MagicMock()
            mock_td_obj.path = "/nonexistent"
            mock_td.return_value = mock_td_obj

            mount_static_dirs(320, 320)
            count_after_first = len(_mounted_routes)
            mount_static_dirs(320, 320)
            count_after_second = len(_mounted_routes)

        self.assertEqual(count_after_first, count_after_second)


# ── dispatch_result / parse_hex_or_400 unit tests ────────────────────────────

class TestModelsHelpers:
    """Pure-unit tests for shared API helper functions."""

    def test_dispatch_result_strips_both_non_serializable_keys(self) -> None:
        from PIL import Image as PILImage
        img = PILImage.new("RGB", (10, 10))
        result = {"success": True, "message": "ok", "image": img, "colors": [1, 2, 3], "extra": 42}
        out = dispatch_result(result)
        assert "image" not in out
        assert "colors" not in out
        assert out["extra"] == 42

    def test_dispatch_result_preserves_all_safe_keys(self) -> None:
        result = {"success": True, "message": "done", "count": 5, "name": "Theme001"}
        out = dispatch_result(result)
        assert out == result

    def test_parse_hex_or_400_lowercase(self) -> None:
        r, g, b = parse_hex_or_400("aabbcc")
        assert r == 0xAA
        assert g == 0xBB
        assert b == 0xCC

    def test_parse_hex_or_400_uppercase(self) -> None:
        r, g, b = parse_hex_or_400("FFFFFF")
        assert (r, g, b) == (255, 255, 255)

    def test_parse_hex_or_400_with_hash(self) -> None:
        r, g, b = parse_hex_or_400("#000000")
        assert (r, g, b) == (0, 0, 0)

    def test_parse_hex_or_400_invalid_raises_http_400(self) -> None:
        from fastapi import HTTPException
        with pytest.raises(HTTPException) as exc_info:
            parse_hex_or_400("gg0000")
        assert exc_info.value.status_code == 400

    def test_parse_hex_or_400_too_short_raises_400(self) -> None:
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            parse_hex_or_400("ff00")

    def test_parse_hex_or_400_empty_raises_400(self) -> None:
        from fastapi import HTTPException
        with pytest.raises(HTTPException):
            parse_hex_or_400("")


if __name__ == "__main__":
    unittest.main()
