"""Tests for api/ — FastAPI REST endpoints."""

import io
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi import HTTPException
from fastapi.testclient import TestClient
from PIL import Image

import trcc.api as api_module
from trcc.api import _device_svc, app, configure_auth
from trcc.api.models import dispatch_result, parse_hex_or_400
from trcc.core.models import DeviceInfo


class TestHealthEndpoint(unittest.TestCase):
    """GET /health always returns 200."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def test_health(self):
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["status"], "ok")
        self.assertIn("version", data)


class TestAuthMiddleware(unittest.TestCase):
    """Token auth middleware."""

    def setUp(self):
        self.client = TestClient(app)

    def tearDown(self):
        configure_auth(None)

    def test_no_token_required(self):
        configure_auth(None)
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 200)

    def test_token_required_rejects_missing(self):
        configure_auth("secret123")
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 401)

    def test_token_required_rejects_wrong(self):
        configure_auth("secret123")
        resp = self.client.get("/devices", headers={"X-API-Token": "wrong"})
        self.assertEqual(resp.status_code, 401)

    def test_token_required_accepts_correct(self):
        configure_auth("secret123")
        resp = self.client.get("/devices", headers={"X-API-Token": "secret123"})
        self.assertEqual(resp.status_code, 200)

    def test_health_bypasses_auth(self):
        configure_auth("secret123")
        resp = self.client.get("/health")
        self.assertEqual(resp.status_code, 200)


class TestDeviceEndpoints(unittest.TestCase):
    """Device list/detect/select/get endpoints."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)
        # Clear device state
        _device_svc._devices = []
        _device_svc._selected = None

    def test_list_devices_empty(self):
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_list_devices_with_device(self):
        _device_svc._devices = [
            DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                       protocol="scsi", resolution=(320, 320)),
        ]
        resp = self.client.get("/devices")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "LCD1")
        self.assertEqual(data[0]["vid"], 0x0402)

    @patch.object(_device_svc, 'detect')
    def test_detect_devices(self, mock_detect):
        mock_detect.return_value = []
        resp = self.client.post("/devices/detect")
        self.assertEqual(resp.status_code, 200)
        mock_detect.assert_called_once()

    def test_select_device(self):
        dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                         protocol="scsi", resolution=(320, 320))
        _device_svc._devices = [dev]
        resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["selected"], "LCD1")
        self.assertEqual(_device_svc.selected, dev)

    def test_select_device_calls_discover_resolution(self):
        """Select triggers resolution discovery for LCD devices with (0,0) resolution."""
        dev = DeviceInfo(name="FW", path="/dev/sg1", vid=0x0402, pid=0x3922,
                         protocol="scsi", resolution=(0, 0))
        _device_svc._devices = [dev]
        with patch.object(_device_svc, '_discover_resolution') as mock_discover:
            resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        mock_discover.assert_called_once_with(dev)

    def test_select_led_device_skips_discover_resolution(self):
        """LED devices have no resolution — discover_resolution must not be called."""
        dev = DeviceInfo(name="HR10", path="hid:0416:8001", vid=0x0416, pid=0x8001,
                         protocol="led", implementation="hid_led")
        _device_svc._devices = [dev]
        with patch.object(_device_svc, '_discover_resolution') as mock_discover, \
             patch("trcc.core.led_device.LEDDevice") as mock_led:
            mock_led.return_value.connect.return_value = {"success": True}
            resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        mock_discover.assert_not_called()

    @patch('trcc.api.stop_overlay_loop')
    @patch('trcc.api.stop_video_playback')
    def test_reselect_same_device_preserves_overlay(self, mock_stop_video, mock_stop_overlay):
        """Re-selecting the already-active device does NOT tear down overlay/video."""
        dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                         protocol="scsi", resolution=(320, 320))
        _device_svc._devices = [dev]
        _device_svc._selected = dev
        api_module._display_dispatcher = MagicMock()

        resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        mock_stop_video.assert_not_called()
        mock_stop_overlay.assert_not_called()

    def test_select_device_not_found(self):
        resp = self.client.post("/devices/99/select")
        self.assertEqual(resp.status_code, 404)

    def test_get_device(self):
        _device_svc._devices = [
            DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                       protocol="scsi", resolution=(480, 480)),
        ]
        resp = self.client.get("/devices/0")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["name"], "LCD1")
        self.assertEqual(data["resolution"], [480, 480])

    def test_get_device_not_found(self):
        resp = self.client.get("/devices/0")
        self.assertEqual(resp.status_code, 404)


class TestSendImage(unittest.TestCase):
    """POST /devices/{id}/send — image upload and processing."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)
        self.dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                              protocol="scsi", resolution=(320, 320))
        _device_svc._devices = [self.dev]
        _device_svc._selected = None

    @patch.object(_device_svc, 'send_pil', return_value=True)
    def test_send_image_success(self, mock_send):
        img = Image.new('RGB', (100, 100), (255, 0, 0))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["sent"])
        mock_send.assert_called_once()

    @patch.object(_device_svc, 'send_pil', return_value=False)
    def test_send_image_failure(self, mock_send):
        img = Image.new('RGB', (100, 100), (0, 0, 255))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 500)

    def test_send_image_invalid_format(self):
        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("test.txt", io.BytesIO(b"not an image"), "text/plain")},
        )
        self.assertEqual(resp.status_code, 400)

    def test_send_image_too_large(self):
        # 11 MB of zeros
        big = io.BytesIO(b'\x00' * (11 * 1024 * 1024))
        resp = self.client.post(
            "/devices/0/send",
            files={"image": ("big.bin", big, "image/png")},
        )
        self.assertEqual(resp.status_code, 413)

    def test_send_image_device_not_found(self):
        _device_svc._devices = []
        img = Image.new('RGB', (10, 10))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/99/send",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 404)

    @patch.object(_device_svc, 'send_pil', return_value=True)
    def test_send_with_rotation(self, mock_send):
        img = Image.new('RGB', (100, 100), (0, 255, 0))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/devices/0/send?rotation=90",
            files={"image": ("test.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 200)


    @patch.object(_device_svc, 'send_pil', return_value=True)
    def test_send_propagates_fbl_from_handshake(self, mock_send):
        """Handshake fbl_code propagates to DeviceInfo for JPEG mode detection."""
        dev = DeviceInfo(name="HID", path="hid:0416:5302", vid=0x0416, pid=0x5302,
                         protocol="hid", resolution=(0, 0))
        _device_svc._devices = [dev]

        mock_result = MagicMock()
        mock_result.resolution = (1280, 480)
        mock_result.fbl = 128
        mock_result.model_id = 128

        with patch('trcc.adapters.device.factory.DeviceProtocolFactory') as mock_factory:
            mock_protocol = MagicMock()
            mock_protocol.handshake.return_value = mock_result
            mock_factory.get_protocol.return_value = mock_protocol

            img = Image.new('RGB', (100, 100), (255, 0, 0))
            buf = io.BytesIO()
            img.save(buf, format='PNG')
            buf.seek(0)

            resp = self.client.post(
                "/devices/0/send",
                files={"image": ("test.png", buf, "image/png")},
            )
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(dev.fbl_code, 128)
            self.assertEqual(dev.resolution, (1280, 480))
            mock_send.assert_called_once()


class TestThemesEndpoint(unittest.TestCase):
    """GET /themes — list local themes."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    @patch('trcc.api.themes.ThemeService.discover_local', return_value=[])
    @patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution', return_value=MagicMock(__str__=lambda s: '/tmp/themes'))
    def test_list_themes_empty(self, mock_dir, mock_discover):
        resp = self.client.get("/themes?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    @patch('trcc.api.themes.ThemeService.discover_local')
    @patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution')
    def test_list_themes_with_results(self, mock_dir, mock_discover):
        mock_td = MagicMock(__str__=lambda s: '/tmp/themes')
        mock_td.path = '/tmp/themes'
        mock_dir.return_value = mock_td
        mock_theme = MagicMock()
        mock_theme.name = "Theme001"
        mock_theme.category = "a"
        mock_theme.is_animated = False
        mock_theme.config_path = None
        mock_discover.return_value = [mock_theme]

        resp = self.client.get("/themes")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["name"], "Theme001")
        self.assertIn("preview_url", data[0])

    def test_invalid_resolution_format(self):
        resp = self.client.get("/themes?resolution=invalid")
        self.assertEqual(resp.status_code, 400)


# ── Display endpoints ──────────────────────────────────────────────────

class TestDisplayEndpoints(unittest.TestCase):
    """Display control endpoints (POST /display/*)."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)
        # Set up a mock LCDDevice
        self.mock_lcd = MagicMock()
        self.mock_lcd.connected = True
        self.mock_lcd.resolution = (320, 320)
        self.mock_lcd.device_path = "/dev/sg0"
        api_module._display_dispatcher = self.mock_lcd

    def tearDown(self):
        api_module._display_dispatcher = None

    def test_display_status_connected(self):
        resp = self.client.get("/display/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["connected"])
        self.assertEqual(data["resolution"], [320, 320])

    def test_display_status_not_connected(self):
        api_module._display_dispatcher = None
        resp = self.client.get("/display/status")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["connected"])

    def test_set_color_invalid_hex(self):
        resp = self.client.post("/display/color", json={"hex": "xyz"})
        self.assertEqual(resp.status_code, 400)

    def test_set_brightness_invalid(self):
        resp = self.client.post("/display/brightness", json={"level": 5})
        self.assertEqual(resp.status_code, 422)  # Pydantic rejects level > 3

    def test_set_rotation_invalid(self):
        self.mock_lcd.settings.set_rotation.return_value = {
            "success": False, "error": "Rotation must be 0, 90, 180, or 270"}
        resp = self.client.post("/display/rotation", json={"degrees": 45})
        self.assertEqual(resp.status_code, 400)

    def test_display_no_device_returns_409(self):
        api_module._display_dispatcher = None
        resp = self.client.post("/display/color", json={"hex": "ff0000"})
        self.assertEqual(resp.status_code, 409)

    def test_on_frame_sent_callback_updates_current_image(self):
        """DeviceService.on_frame_sent callback updates _current_image."""
        test_img = Image.new('RGB', (320, 320), (0, 255, 0))
        api_module._current_image = None

        # Simulate the callback that select_device() wires up
        _device_svc.on_frame_sent = api_module.set_current_image
        _device_svc.on_frame_sent(test_img)

        self.assertIs(api_module._current_image, test_img)
        _device_svc.on_frame_sent = None
        api_module._current_image = None


class TestPreviewEndpoints(unittest.TestCase):
    """GET /display/preview and WebSocket /display/preview/stream."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def tearDown(self):
        api_module._current_image = None
        api_module._display_dispatcher = None

    def test_preview_no_image(self):
        api_module._current_image = None
        resp = self.client.get("/display/preview")
        self.assertEqual(resp.status_code, 503)

    def test_preview_returns_png(self):
        api_module._current_image = Image.new('RGB', (320, 320), (255, 0, 0))
        resp = self.client.get("/display/preview")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.headers["content-type"], "image/png")
        # Verify it's a valid PNG (starts with PNG magic bytes)
        self.assertTrue(resp.content[:4] == b'\x89PNG')

    def test_preview_stream_rejects_bad_token(self):
        from starlette.websockets import WebSocketDisconnect as WSDisconnect

        configure_auth("secret123")
        with pytest.raises(WSDisconnect) as exc_info:
            with self.client.websocket_connect(
                "/display/preview/stream?token=wrong"
            ):
                pass
        self.assertEqual(exc_info.value.code, 4001)
        configure_auth(None)

    def test_preview_stream_sends_frame(self):
        api_module._current_image = Image.new('RGB', (100, 100), (0, 0, 255))
        with self.client.websocket_connect("/display/preview/stream") as ws:
            data = ws.receive_bytes()
            # Should be JPEG (starts with FF D8)
            self.assertTrue(data[:2] == b'\xff\xd8')

    def test_preview_stream_accepts_control_message(self):
        api_module._current_image = Image.new('RGB', (100, 100), (0, 0, 255))
        with self.client.websocket_connect("/display/preview/stream") as ws:
            # Read the first frame
            ws.receive_bytes()
            # Send control message
            ws.send_text('{"fps": 5, "quality": 50}')
            # Change image to trigger another frame
            api_module._current_image = Image.new('RGB', (100, 100), (255, 0, 0))
            data = ws.receive_bytes()
            self.assertTrue(data[:2] == b'\xff\xd8')


# ── LED endpoints ──────────────────────────────────────────────────────

class TestLEDEndpoints(unittest.TestCase):
    """LED control endpoints (POST /led/*)."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)
        self.mock_led = MagicMock()
        self.mock_led.connected = True
        self.mock_led.status = "AX120 Digital (style 1)"
        api_module._led_dispatcher = self.mock_led

    def tearDown(self):
        api_module._led_dispatcher = None

    def test_led_status_connected(self):
        resp = self.client.get("/led/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["connected"])
        self.assertIn("AX120", data["status"])

    def test_led_status_not_connected(self):
        api_module._led_dispatcher = None
        resp = self.client.get("/led/status")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["connected"])

    def test_set_color_invalid_hex(self):
        resp = self.client.post("/led/color", json={"hex": "zz"})
        self.assertEqual(resp.status_code, 400)

    def test_set_mode_invalid(self):
        self.mock_led.set_mode.return_value = {
            "success": False, "error": "Unknown mode 'invalid'"}
        resp = self.client.post("/led/mode", json={"mode": "invalid"})
        self.assertEqual(resp.status_code, 400)

    def test_set_brightness_invalid(self):
        resp = self.client.post("/led/brightness", json={"level": 150})
        self.assertEqual(resp.status_code, 422)  # Pydantic rejects level > 100

    def test_set_sensor_invalid(self):
        self.mock_led.set_sensor_source.return_value = {
            "success": False, "error": "Source must be 'cpu' or 'gpu'"}
        resp = self.client.post("/led/sensor", json={"source": "ram"})
        self.assertEqual(resp.status_code, 400)

    def test_set_temp_unit_invalid(self):
        self.mock_led.set_temp_unit.return_value = {
            "success": False, "error": "Unit must be 'C' or 'F'"}
        resp = self.client.post("/led/temp-unit", json={"unit": "K"})
        self.assertEqual(resp.status_code, 400)

    def test_led_no_device_returns_409(self):
        api_module._led_dispatcher = None
        resp = self.client.post("/led/color", json={"hex": "ff0000"})
        self.assertEqual(resp.status_code, 409)


# ── Theme operation endpoints ──────────────────────────────────────────

class TestThemeOperations(unittest.TestCase):
    """Theme load/save/import endpoints."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def tearDown(self):
        api_module._display_dispatcher = None

    def test_load_theme_no_device(self):
        api_module._display_dispatcher = None
        resp = self.client.post("/themes/load", json={"name": "Theme001"})
        self.assertEqual(resp.status_code, 409)

    @patch('trcc.api.themes.ThemeService.discover_local')
    @patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution',
           return_value=MagicMock(__str__=lambda s: '/tmp/themes'))
    def test_load_theme_not_found(self, mock_dir, mock_discover):
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd
        mock_discover.return_value = []

        resp = self.client.post("/themes/load", json={"name": "NonExistent"})
        self.assertEqual(resp.status_code, 404)

    @patch('trcc.api.themes.ThemeService.discover_local')
    @patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution',
           return_value=MagicMock(__str__=lambda s: '/tmp/themes'))
    def test_load_theme_invalid_resolution(self, mock_dir, mock_discover):
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd
        mock_discover.return_value = []

        resp = self.client.post("/themes/load",
                                json={"name": "Theme001", "resolution": "bad"})
        self.assertEqual(resp.status_code, 400)

    @patch('trcc.conf.settings')
    def test_save_theme(self, mock_settings):
        mock_settings.load_config.return_value = {"some": "config"}
        resp = self.client.post("/themes/save", json={"name": "MyTheme"})
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json()["name"], "MyTheme")

    def test_import_theme_wrong_extension(self):
        buf = io.BytesIO(b"not a theme")
        resp = self.client.post(
            "/themes/import",
            files={"file": ("theme.zip", buf, "application/octet-stream")},
        )
        self.assertEqual(resp.status_code, 400)


# ── System endpoints ───────────────────────────────────────────────────

class TestSystemEndpoints(unittest.TestCase):
    """System metrics and report endpoints."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def tearDown(self):
        api_module._system_svc = None

    def test_get_metrics(self):
        from trcc.core.models import HardwareMetrics
        mock_svc = MagicMock()
        m = HardwareMetrics()
        m.cpu_temp = 65.0
        m.cpu_percent = 42.0
        m.gpu_temp = 70.0
        mock_svc.all_metrics = m
        api_module._system_svc = mock_svc

        resp = self.client.get("/system/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["cpu_temp"], 65.0)
        self.assertEqual(data["gpu_temp"], 70.0)

    def test_get_metrics_by_category_cpu(self):
        from trcc.core.models import HardwareMetrics
        mock_svc = MagicMock()
        m = HardwareMetrics()
        m.cpu_temp = 65.0
        m.cpu_percent = 42.0
        m.gpu_temp = 70.0
        mock_svc.all_metrics = m
        api_module._system_svc = mock_svc

        resp = self.client.get("/system/metrics/cpu")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIn("cpu_temp", data)
        self.assertIn("cpu_percent", data)
        self.assertNotIn("gpu_temp", data)

    def test_get_metrics_invalid_category(self):
        api_module._system_svc = MagicMock()
        from trcc.core.models import HardwareMetrics
        api_module._system_svc.all_metrics = HardwareMetrics()

        resp = self.client.get("/system/metrics/invalid")
        self.assertEqual(resp.status_code, 400)

    @patch('trcc.adapters.infra.debug_report.DebugReport')
    def test_get_report(self, mock_report_class):
        mock_rpt = MagicMock()
        mock_rpt.__str__ = lambda s: "TRCC Linux Diagnostic Report\n..."
        mock_report_class.return_value = mock_rpt

        resp = self.client.get("/system/report")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("report", resp.json())


# ── Web/mask theme endpoints ─────────────────────────────────────────

class TestWebThemeEndpoints(unittest.TestCase):
    """GET /themes/web and /themes/masks."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/nonexistent')
    def test_list_web_themes_empty_dir(self, mock_dir):
        resp = self.client.get("/themes/web?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    @patch('trcc.api.themes.os.listdir', return_value=['a001.png', 'b002.png', 'readme.txt'])
    @patch('trcc.api.themes.os.path.isfile', return_value=False)
    @patch('trcc.api.themes.os.path.isdir', return_value=True)
    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/tmp/web')
    def test_list_web_themes_with_pngs(self, mock_dir, mock_isdir, mock_isfile, mock_listdir):
        resp = self.client.get("/themes/web?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 2)
        self.assertEqual(data[0]["id"], "a001")
        self.assertEqual(data[0]["category"], "a")
        self.assertEqual(data[0]["preview_url"], "/static/web/a001.png")
        self.assertEqual(data[1]["id"], "b002")

    def test_list_web_themes_invalid_resolution(self):
        resp = self.client.get("/themes/web?resolution=bad")
        self.assertEqual(resp.status_code, 400)

    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_masks_dir', return_value='/nonexistent')
    def test_list_masks_empty_dir(self, mock_dir):
        resp = self.client.get("/themes/masks?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.json(), [])

    def test_list_masks_invalid_resolution(self):
        resp = self.client.get("/themes/masks?resolution=nope")
        self.assertEqual(resp.status_code, 400)

    @patch('trcc.api.themes.os.listdir', return_value=['a001.png'])
    @patch('trcc.api.themes.os.path.isfile', return_value=False)
    @patch('trcc.api.themes.os.path.isdir', return_value=True)
    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/tmp/web')
    def test_list_web_themes_includes_download_url(self, *_mocks):
        resp = self.client.get("/themes/web?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data[0]["download_url"], "/themes/web/a001/download")

    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.download_theme', return_value='/tmp/web/a001.mp4')
    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.is_cached', return_value=False)
    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/tmp/web')
    def test_download_web_theme_success(self, *_mocks):
        resp = self.client.post("/themes/web/a001/download?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(data["id"], "a001")
        self.assertEqual(data["cached_path"], "/tmp/web/a001.mp4")
        self.assertEqual(data["resolution"], "320x320")
        self.assertFalse(data["already_cached"])

    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.download_theme', return_value='/tmp/web/a001.mp4')
    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.is_cached', return_value=True)
    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/tmp/web')
    def test_download_web_theme_already_cached(self, *_mocks):
        resp = self.client.post("/themes/web/a001/download?resolution=320x320")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["already_cached"])

    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.download_theme', return_value=None)
    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.is_cached', return_value=False)
    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/tmp/web')
    def test_download_web_theme_not_found(self, *_mocks):
        resp = self.client.post("/themes/web/z999/download?resolution=320x320")
        self.assertEqual(resp.status_code, 404)
        self.assertIn("not found", resp.json()["detail"])

    def test_download_web_theme_send_no_device(self):
        api_module._display_dispatcher = None
        resp = self.client.post("/themes/web/a001/download?resolution=320x320&send=true")
        self.assertEqual(resp.status_code, 409)

    def test_download_web_theme_invalid_resolution(self):
        resp = self.client.post("/themes/web/a001/download?resolution=bad")
        self.assertEqual(resp.status_code, 400)

    @patch('trcc.api.start_video_playback', return_value=True)
    @patch('trcc.api.stop_video_playback')
    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.download_theme', return_value='/tmp/web/a001.mp4')
    @patch('trcc.adapters.infra.theme_cloud.CloudThemeDownloader.is_cached', return_value=False)
    @patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/tmp/web')
    def test_download_web_theme_with_send(self, *_mocks):
        # Set up mock display dispatcher
        mock_disp = MagicMock()
        mock_disp.connected = True
        mock_disp.resolution = (320, 320)
        api_module._display_dispatcher = mock_disp

        resp = self.client.post("/themes/web/a001/download?resolution=320x320&send=true")

        self.assertEqual(resp.status_code, 200)
        # Video playback should have been started with the downloaded file
        from trcc.api import start_video_playback
        start_video_playback.assert_called_once()  # type: ignore[union-attr]
        api_module._display_dispatcher = None


# ── Video playback endpoints ─────────────────────────────────────────

class TestVideoPlaybackEndpoints(unittest.TestCase):
    """Video playback control endpoints (POST /display/video/*)."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def tearDown(self):
        api_module._media_service = None
        api_module._video_thread = None
        api_module._video_stop_event = None

    def test_video_status_no_video(self):
        api_module._media_service = None
        resp = self.client.get("/display/video/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertFalse(data["playing"])
        self.assertFalse(data["paused"])

    def test_video_status_with_media(self):
        from trcc.core.models import PlaybackState, VideoState

        mock_media = MagicMock()
        mock_state = VideoState()
        mock_state.state = PlaybackState.PLAYING
        mock_state.fps = 24
        mock_state.total_frames = 100
        mock_state.current_frame = 50
        mock_state.loop = True
        mock_media.state = mock_state
        mock_media.source_path = "/tmp/video.mp4"
        api_module._media_service = mock_media

        resp = self.client.get("/display/video/status")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data["playing"])
        self.assertFalse(data["paused"])
        self.assertEqual(data["fps"], 24)
        self.assertTrue(data["loop"])

    def test_video_stop(self):
        api_module._media_service = MagicMock()
        api_module._video_stop_event = MagicMock()
        api_module._video_thread = MagicMock()
        api_module._video_thread.is_alive.return_value = False

        resp = self.client.post("/display/video/stop")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.json()["success"])
        # Should have been cleaned up
        self.assertIsNone(api_module._media_service)

    def test_video_pause_no_video(self):
        api_module._media_service = None
        resp = self.client.post("/display/video/pause")
        self.assertEqual(resp.status_code, 409)

    def test_video_pause_with_video(self):
        mock_media = MagicMock()
        mock_media.is_playing = False  # After toggle
        api_module._media_service = mock_media

        resp = self.client.post("/display/video/pause")
        self.assertEqual(resp.status_code, 200)
        mock_media.toggle.assert_called_once()

    @patch('trcc.api.start_video_playback', return_value=True)
    @patch('trcc.api.stop_video_playback')
    @patch('trcc.api.themes.ThemeService.discover_local')
    @patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution',
           return_value=MagicMock(__str__=lambda s: '/tmp/themes'))
    def test_load_animated_theme_starts_video(self, mock_dir, mock_discover,
                                               mock_stop, mock_start):
        """Loading an animated theme starts background video playback."""
        import tempfile
        from pathlib import Path

        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd

        mock_theme = MagicMock()
        mock_theme.name = "VideoTheme"
        mock_theme.is_animated = True
        mock_discover.return_value = [mock_theme]

        # Create a temp dir with a fake video file
        with tempfile.TemporaryDirectory() as tmpdir:
            theme_path = Path(tmpdir) / "VideoTheme"
            theme_path.mkdir()
            (theme_path / "Theme.mp4").write_bytes(b"fake")
            mock_dir.return_value = MagicMock(__str__=lambda s: tmpdir)

            resp = self.client.post("/themes/load", json={"name": "VideoTheme"})

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertTrue(data.get("animated"))
        mock_start.assert_called_once()
        api_module._display_dispatcher = None

    def test_display_route_stops_video_on_static_send(self):
        """Sending a static color stops any running video playback."""
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.frame.send_color.return_value = {
            "success": True, "message": "Sent"}
        api_module._display_dispatcher = mock_lcd

        # Simulate running video
        api_module._media_service = MagicMock()
        api_module._video_stop_event = MagicMock()
        api_module._video_thread = MagicMock()
        api_module._video_thread.is_alive.return_value = False

        self.client.post("/display/color", json={"hex": "ff0000"})

        # Video should be stopped
        self.assertIsNone(api_module._media_service)
        api_module._display_dispatcher = None


# =============================================================================
# Overlay metrics loop
# =============================================================================

class TestOverlayLoop(unittest.TestCase):
    """Overlay metrics loop (background thread for static themes)."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def tearDown(self):
        api_module._overlay_svc = None
        api_module._overlay_thread = None
        api_module._overlay_stop_event = None
        api_module._display_dispatcher = None

    @patch('trcc.api.stop_overlay_loop')
    @patch('trcc.api.stop_video_playback')
    def test_display_route_stops_overlay_on_static_send(self, mock_stop_video, mock_stop_overlay):
        """Sending a static color stops any running overlay loop."""
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.frame.send_color.return_value = {"success": True, "message": "Sent"}
        api_module._display_dispatcher = mock_lcd

        self.client.post("/display/color", json={"hex": "ff0000"})
        mock_stop_overlay.assert_called_once()

    @patch('trcc.api.start_overlay_loop', return_value=True)
    @patch('trcc.api.stop_overlay_loop')
    @patch('trcc.api.stop_video_playback')
    @patch('trcc.api._device_svc')
    @patch('trcc.api.themes.ThemeService.discover_local')
    @patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution')
    def test_load_static_theme_with_dc_starts_overlay(
        self, mock_dir, mock_discover, mock_svc,
        mock_stop_video, mock_stop_overlay, mock_start_overlay,
    ):
        """Loading a static theme with config1.dc starts overlay loop."""
        import tempfile
        from pathlib import Path

        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd
        mock_svc.send_pil.return_value = True

        mock_theme = MagicMock()
        mock_theme.name = "StaticWithDC"
        mock_theme.is_animated = False
        mock_discover.return_value = [mock_theme]

        with tempfile.TemporaryDirectory() as tmpdir:
            theme_path = Path(tmpdir) / "StaticWithDC"
            theme_path.mkdir()
            # Create image + DC file
            img = Image.new('RGB', (320, 320), 'blue')
            img.save(str(theme_path / "01.png"))
            (theme_path / "config1.dc").write_bytes(b"\x00" * 64)
            mock_dir.return_value = MagicMock(__str__=lambda s: tmpdir)

            resp = self.client.post("/themes/load", json={"name": "StaticWithDC"})

        self.assertEqual(resp.status_code, 200)
        mock_start_overlay.assert_called_once()

    @patch('trcc.api.start_overlay_loop', return_value=True)
    @patch('trcc.api.stop_overlay_loop')
    @patch('trcc.api.stop_video_playback')
    @patch('trcc.api._device_svc')
    @patch('trcc.api.themes.ThemeService.discover_local')
    @patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution')
    def test_load_static_theme_without_dc_no_overlay(
        self, mock_dir, mock_discover, mock_svc,
        mock_stop_video, mock_stop_overlay, mock_start_overlay,
    ):
        """Loading a static theme without DC config does NOT start overlay loop."""
        import tempfile
        from pathlib import Path

        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd
        mock_svc.send_pil.return_value = True

        mock_theme = MagicMock()
        mock_theme.name = "PlainTheme"
        mock_theme.is_animated = False
        mock_discover.return_value = [mock_theme]

        with tempfile.TemporaryDirectory() as tmpdir:
            theme_path = Path(tmpdir) / "PlainTheme"
            theme_path.mkdir()
            img = Image.new('RGB', (320, 320), 'red')
            img.save(str(theme_path / "01.png"))
            mock_dir.return_value = MagicMock(__str__=lambda s: tmpdir)

            resp = self.client.post("/themes/load", json={"name": "PlainTheme"})

        self.assertEqual(resp.status_code, 200)
        mock_start_overlay.assert_not_called()

    def test_stop_overlay_loop_cleans_up(self):
        """stop_overlay_loop() clears all overlay state."""
        api_module._overlay_svc = MagicMock()
        api_module._overlay_stop_event = MagicMock()
        api_module._overlay_thread = MagicMock()
        api_module._overlay_thread.is_alive.return_value = False

        api_module.stop_overlay_loop()

        self.assertIsNone(api_module._overlay_svc)
        self.assertIsNone(api_module._overlay_thread)
        self.assertIsNone(api_module._overlay_stop_event)

    @patch('trcc.services.system.get_all_metrics')
    @patch('trcc.api._device_svc')
    def test_start_overlay_loop_runs(self, mock_svc, mock_metrics):
        """start_overlay_loop() starts a daemon thread that renders."""
        import time

        from trcc.core.models import HardwareMetrics

        mock_metrics.return_value = HardwareMetrics()
        mock_svc.send_pil.return_value = True

        bg = Image.new('RGB', (320, 320), 'black')

        # Use a non-existent DC path — overlay will load empty config
        ok = api_module.start_overlay_loop(bg, "/nonexistent/config1.dc", 320, 320)
        self.assertTrue(ok)
        self.assertIsNotNone(api_module._overlay_thread)
        self.assertTrue(api_module._overlay_thread.is_alive())

        # Let it run briefly then stop
        time.sleep(0.1)
        api_module.stop_overlay_loop()
        self.assertIsNone(api_module._overlay_thread)


# =============================================================================
# IPC frame sharing (GUI daemon mode)
# =============================================================================

class TestIPCFrameSharing(unittest.TestCase):
    """IPC daemon detection and direct frame reading."""

    def setUp(self):
        configure_auth(None)
        self.client = TestClient(app)

    def tearDown(self):
        api_module._display_dispatcher = None
        api_module._led_dispatcher = None
        api_module._current_image = None

    def test_ipc_server_get_frame(self):
        """IPCServer._get_frame() returns base64 JPEG when frame is available."""
        import base64

        from trcc.ipc import IPCServer

        server = IPCServer(None, None)
        img = Image.new('RGB', (320, 320), 'blue')
        server.capture_frame(img)

        result = server._get_frame()
        self.assertTrue(result["success"])
        self.assertIn("frame", result)
        # Verify it's valid JPEG
        raw = base64.b64decode(result["frame"])
        self.assertTrue(raw[:2] == b'\xff\xd8')  # JPEG magic

    def test_ipc_server_get_frame_no_image(self):
        """IPCServer._get_frame() returns error when no frame captured."""
        from trcc.ipc import IPCServer

        server = IPCServer(None, None)
        result = server._get_frame()
        self.assertFalse(result["success"])

    @patch('trcc.ipc.IPCClient')
    def test_select_device_uses_ipc_when_daemon_available(self, mock_ipc):
        """select_device() uses IPC proxies when GUI daemon is running."""
        mock_ipc.available.return_value = True
        mock_ipc.send.return_value = {
            "lcd": {"resolution": [320, 320], "path": "/dev/sg0"},
        }

        dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                         protocol="scsi", resolution=(320, 320))
        _device_svc._devices = [dev]

        resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        # Should have IPC proxies, not direct dispatchers
        from trcc.ipc import IPCDisplayProxy
        self.assertIsInstance(api_module._display_dispatcher, IPCDisplayProxy)

        api_module._display_dispatcher = None
        api_module._led_dispatcher = None

    @patch('trcc.ipc.IPCClient')
    def test_select_device_ipc_syncs_resolution_from_daemon(self, mock_ipc):
        """select_device() syncs real resolution from daemon when device has (0,0)."""
        mock_ipc.available.return_value = True
        mock_ipc.send.return_value = {
            "lcd": {"resolution": [320, 320], "path": "/dev/sg0"},
        }

        # Device starts with (0, 0) — resolution not yet discovered
        dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                         protocol="scsi", resolution=(0, 0))
        _device_svc._devices = [dev]

        resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()

        # Resolution should be synced from daemon, not (0, 0)
        self.assertEqual(data["resolution"], [320, 320])
        self.assertEqual(dev.resolution, (320, 320))

        api_module._display_dispatcher = None
        api_module._led_dispatcher = None

    def test_led_status_returns_string_in_ipc_mode(self):
        """IPCLEDProxy.status returns a string, not a proxy function."""
        from trcc.ipc import IPCLEDProxy

        with patch('trcc.ipc.IPCClient') as mock_ipc:
            mock_ipc.send.return_value = {"led": {"connected": True}}
            proxy = IPCLEDProxy()
            self.assertIsInstance(proxy.status, str)

        api_module._led_dispatcher = IPCLEDProxy()
        with patch('trcc.ipc.IPCClient') as mock_ipc:
            mock_ipc.send.return_value = {"led": {"connected": True}}
            resp = self.client.get("/led/status")
            self.assertEqual(resp.status_code, 200)
            data = resp.json()
            self.assertIn("status", data)
            self.assertIsInstance(data["status"], str)
        api_module._led_dispatcher = None

    @patch('trcc.ipc.IPCClient')
    @patch('trcc.cli._device.discover_resolution')
    def test_select_device_standalone_when_no_daemon(self, mock_discover, mock_ipc):
        """select_device() uses direct USB when no GUI daemon."""
        mock_ipc.available.return_value = False

        dev = DeviceInfo(name="LCD1", path="/dev/sg0", vid=0x0402, pid=0x3922,
                         protocol="scsi", resolution=(320, 320))
        _device_svc._devices = [dev]

        resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        # Standalone mode — not using IPC proxies
        from trcc.ipc import IPCDisplayProxy
        self.assertNotIsInstance(api_module._display_dispatcher, IPCDisplayProxy)

        api_module._display_dispatcher = None

    def test_preview_fetches_from_ipc_when_daemon_active(self):
        """GET /preview reads frame from IPC daemon when proxy is active."""
        from trcc.ipc import IPCDisplayProxy

        api_module._display_dispatcher = IPCDisplayProxy()

        with patch('trcc.api.display._fetch_ipc_frame') as mock_fetch:
            mock_fetch.return_value = Image.new('RGB', (320, 320), 'red')
            resp = self.client.get("/display/preview")
            self.assertEqual(resp.status_code, 200)
            self.assertEqual(resp.headers["content-type"], "image/png")
            mock_fetch.assert_called_once()

    def test_preview_uses_local_image_in_standalone(self):
        """GET /preview reads _current_image when no IPC proxy."""
        api_module._display_dispatcher = None
        api_module._current_image = Image.new('RGB', (320, 320), 'green')

        resp = self.client.get("/display/preview")
        self.assertEqual(resp.status_code, 200)
        self.assertTrue(resp.content[:4] == b'\x89PNG')


# =============================================================================
# dispatch_result — shared API helper
# =============================================================================

class TestDispatchResult:
    """dispatch_result() — strips non-serializable keys, raises on failure."""

    def test_success_passthrough(self):
        result = {"success": True, "message": "ok", "value": 42}
        assert dispatch_result(result) == {"success": True, "message": "ok", "value": 42}

    def test_strips_image_key(self):
        img = Image.new("RGB", (10, 10))
        result = {"success": True, "image": img, "message": "sent"}
        out = dispatch_result(result)
        assert "image" not in out
        assert out["message"] == "sent"

    def test_strips_colors_key(self):
        result = {"success": True, "colors": [1, 2, 3], "message": "set"}
        out = dispatch_result(result)
        assert "colors" not in out
        assert out["message"] == "set"

    def test_failure_raises_400(self):
        with pytest.raises(HTTPException) as exc_info:
            dispatch_result({"success": False, "error": "bad input"})
        assert exc_info.value.status_code == 400
        assert "bad input" in exc_info.value.detail

    def test_failure_default_message(self):
        with pytest.raises(HTTPException) as exc_info:
            dispatch_result({"success": False})
        assert "Unknown error" in exc_info.value.detail


# ── Helpers (from merged test_api_ext.py) ────────────────────────────────────


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


# ── Auth edge cases ──────────────────────────────────────────────────────────

class TestAuthEdgeCases(unittest.TestCase):
    """Edge cases in token auth middleware."""

    def tearDown(self) -> None:
        configure_auth(None)

    def test_empty_string_token_treated_as_no_auth(self) -> None:
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
        configure_auth("Secret")
        client = TestClient(app)
        resp = client.get("/devices", headers={"X-API-Token": "secret"})
        self.assertEqual(resp.status_code, 401)

    def test_health_endpoint_bypasses_auth_any_token(self) -> None:
        configure_auth("valid_token")
        client = TestClient(app)
        resp = client.get("/health", headers={"X-API-Token": "completely_wrong"})
        self.assertEqual(resp.status_code, 200)

    def test_token_required_for_post_endpoints(self) -> None:
        configure_auth("tok123")
        client = TestClient(app)
        resp = client.post("/devices/detect")
        self.assertEqual(resp.status_code, 401)


# ── Health response shape ────────────────────────────────────────────────────

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


# ── Device endpoint edge cases ───────────────────────────────────────────────

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
        dev = _scsi_dev(resolution=(320, 320))
        _device_svc._devices = [dev]
        with patch("trcc.cli._device.discover_resolution"), \
             patch("trcc.core.lcd_device.LCDDevice") as mock_disp_cls, \
             patch("trcc.api.mount_static_dirs"):
            mock_disp = MagicMock()
            mock_disp_cls.return_value = mock_disp
            resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("selected", resp.json())

    def test_select_led_device_failed_connect_clears_dispatcher(self) -> None:
        dev = DeviceInfo(name="HR10", path="hid:0416:8001", vid=0x0416, pid=0x8001,
                         protocol="led", implementation="hid_led")
        _device_svc._devices = [dev]
        with patch("trcc.core.led_device.LEDDevice") as mock_cls:
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
             patch("trcc.core.lcd_device.LCDDevice"), \
             patch("trcc.api.mount_static_dirs"):
            resp = self.client.post("/devices/0/select")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("resolution", resp.json())


# ── send_image edge cases ────────────────────────────────────────────────────

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


# ── Display endpoint error paths ─────────────────────────────────────────────

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
        resp = self.client.post("/display/brightness", json={"level": 0})
        self.assertEqual(resp.status_code, 422)

    def test_brightness_negative_rejected(self) -> None:
        resp = self.client.post("/display/brightness", json={"level": -1})
        self.assertEqual(resp.status_code, 422)

    def test_split_mode_out_of_range(self) -> None:
        resp = self.client.post("/display/split", json={"mode": 4})
        self.assertEqual(resp.status_code, 422)

    def test_split_mode_negative_rejected(self) -> None:
        resp = self.client.post("/display/split", json={"mode": -1})
        self.assertEqual(resp.status_code, 422)

    def test_color_too_short_rejected(self) -> None:
        resp = self.client.post("/display/color", json={"hex": "ff00"})
        self.assertEqual(resp.status_code, 400)

    def test_color_eight_digit_hex_rejected(self) -> None:
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
        self.mock_lcd.connected = False
        resp = self.client.get("/display/status")
        self.assertEqual(resp.status_code, 200)
        self.assertFalse(resp.json()["connected"])

    def test_display_status_has_device_path(self) -> None:
        resp = self.client.get("/display/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("device_path", resp.json())


# ── LED endpoint error paths ─────────────────────────────────────────────────

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
        self.mock_led.set_zone_sync.return_value = {"success": True, "message": "ok"}
        resp = self.client.post("/led/sync", json={"enabled": False})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_zone_sync.assert_called_once_with(False, None)


# ── Theme endpoint edge cases ────────────────────────────────────────────────

class TestThemeEdgeCases(unittest.TestCase):
    """Uncovered theme paths."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)
        api_module._display_dispatcher = None

    def tearDown(self) -> None:
        api_module._display_dispatcher = None

    def test_list_themes_resolution_boundary_min(self) -> None:
        with patch("trcc.api.themes.ThemeService.discover_local", return_value=[]), \
             patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_td:
            mock_td.return_value = MagicMock(path="/tmp/none", __str__=lambda s: "/tmp/none")
            resp = self.client.get("/themes?resolution=100x100")
        self.assertEqual(resp.status_code, 200)

    def test_list_themes_resolution_out_of_range(self) -> None:
        resp = self.client.get("/themes?resolution=99x99")
        self.assertEqual(resp.status_code, 400)

    def test_list_themes_resolution_above_max(self) -> None:
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
        with patch("trcc.api.themes.ThemeService.import_tr", return_value=(False, "bad archive")), \
             patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_td:
            mock_td.return_value = MagicMock(path="/tmp", __str__=lambda s: "/tmp")
            resp = self.client.post(
                "/themes/import",
                files={"file": ("x.tr", io.BytesIO(b"junk"), "application/octet-stream")},
            )
        self.assertEqual(resp.status_code, 400)

    def test_save_theme_empty_config_returns_500(self) -> None:
        with patch("trcc.conf.load_config", return_value={}):
            resp = self.client.post("/themes/save", json={"name": "Empty"})
        self.assertEqual(resp.status_code, 500)

    def test_load_theme_sends_image_to_device(self) -> None:
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
        mock_lcd = MagicMock()
        mock_lcd.connected = True
        mock_lcd.resolution = (320, 320)
        api_module._display_dispatcher = mock_lcd

        mock_theme = MagicMock()
        mock_theme.name = "NoImages"
        mock_theme.config_path = None

        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "NoImages").mkdir()

            with patch("trcc.api.themes.ThemeService.discover_local", return_value=[mock_theme]), \
                 patch("trcc.adapters.infra.data_repository.ThemeDir.for_resolution") as mock_tdr:
                mock_tdr.return_value = MagicMock(path=td, __str__=lambda s: td)
                resp = self.client.post("/themes/load", json={"name": "NoImages"})

        self.assertEqual(resp.status_code, 404)

    def test_load_theme_with_jpg_fallback(self) -> None:
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
        with tempfile.TemporaryDirectory() as td:
            (Path(td) / "b002.png").write_bytes(b"fake")

            with patch("trcc.adapters.infra.data_repository.DataManager.get_web_dir",
                       return_value=td):
                resp = self.client.get("/themes/web?resolution=480x480")

        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertEqual(len(data), 1)
        self.assertFalse(data[0]["has_video"])


# ── System endpoint edge cases ───────────────────────────────────────────────

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
        self._mock_svc_with_metrics()
        resp = self.client.get("/system/metrics/poweruser")
        self.assertEqual(resp.status_code, 400)
        self.assertIn("cpu", resp.json()["detail"])

    def test_get_metrics_all_fields_present(self) -> None:
        self._mock_svc_with_metrics(cpu_temp=72.5)
        resp = self.client.get("/system/metrics")
        self.assertEqual(resp.status_code, 200)
        data = resp.json()
        self.assertIsInstance(data, dict)
        self.assertIn("cpu_temp", data)
        self.assertEqual(data["cpu_temp"], 72.5)

    def test_system_svc_lazily_created(self) -> None:
        api_module._system_svc = None
        with patch("trcc.services.SystemService") as mock_cls:
            mock_inst = MagicMock()
            from trcc.core.models import HardwareMetrics
            mock_inst.all_metrics = HardwareMetrics()
            mock_cls.return_value = mock_inst
            resp = self.client.get("/system/metrics")
        self.assertEqual(resp.status_code, 200)
        mock_cls.assert_called_once()


# ── Static mount edge cases ──────────────────────────────────────────────────

class TestStaticMountEdgeCases(unittest.TestCase):
    """mount_static_dirs() with non-existent directories."""

    def setUp(self) -> None:
        configure_auth(None)
        self.client = TestClient(app)

    def test_mount_static_dirs_nonexistent_web_dir_skipped(self) -> None:
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


# ── parse_hex_or_400 unit tests ──────────────────────────────────────────────

class TestParseHexOr400:
    """Pure-unit tests for parse_hex_or_400."""

    def test_lowercase(self) -> None:
        r, g, b = parse_hex_or_400("aabbcc")
        assert r == 0xAA
        assert g == 0xBB
        assert b == 0xCC

    def test_uppercase(self) -> None:
        r, g, b = parse_hex_or_400("FFFFFF")
        assert (r, g, b) == (255, 255, 255)

    def test_with_hash(self) -> None:
        r, g, b = parse_hex_or_400("#000000")
        assert (r, g, b) == (0, 0, 0)

    def test_invalid_raises_http_400(self) -> None:
        with pytest.raises(HTTPException) as exc_info:
            parse_hex_or_400("gg0000")
        assert exc_info.value.status_code == 400

    def test_too_short_raises_400(self) -> None:
        with pytest.raises(HTTPException):
            parse_hex_or_400("ff00")

    def test_empty_raises_400(self) -> None:
        with pytest.raises(HTTPException):
            parse_hex_or_400("")


if __name__ == '__main__':
    unittest.main()
