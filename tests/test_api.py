"""Tests for api/ — FastAPI REST endpoints."""

import io
import unittest
from unittest.mock import MagicMock, patch

from fastapi.testclient import TestClient
from PIL import Image

import trcc.api as api_module
from trcc.api import _device_svc, app, configure_auth
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
        # Set up a mock DisplayDispatcher
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

    def test_set_color_success(self):
        self.mock_lcd.send_color.return_value = {
            "success": True, "message": "Sent color #ff0000"}
        resp = self.client.post("/display/color", json={"hex": "ff0000"})
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.send_color.assert_called_once_with(255, 0, 0)

    def test_set_color_with_hash(self):
        self.mock_lcd.send_color.return_value = {
            "success": True, "message": "Sent color"}
        resp = self.client.post("/display/color", json={"hex": "#00ff00"})
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.send_color.assert_called_once_with(0, 255, 0)

    def test_set_color_invalid_hex(self):
        resp = self.client.post("/display/color", json={"hex": "xyz"})
        self.assertEqual(resp.status_code, 400)

    def test_set_brightness_success(self):
        self.mock_lcd.set_brightness.return_value = {
            "success": True, "message": "Brightness set to L2"}
        resp = self.client.post("/display/brightness", json={"level": 2})
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.set_brightness.assert_called_once_with(2)

    def test_set_brightness_invalid(self):
        self.mock_lcd.set_brightness.return_value = {
            "success": False, "error": "Brightness level must be 1, 2, or 3"}
        resp = self.client.post("/display/brightness", json={"level": 5})
        self.assertEqual(resp.status_code, 400)

    def test_set_rotation_success(self):
        self.mock_lcd.set_rotation.return_value = {
            "success": True, "message": "Rotation set to 90°"}
        resp = self.client.post("/display/rotation", json={"degrees": 90})
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.set_rotation.assert_called_once_with(90)

    def test_set_rotation_invalid(self):
        self.mock_lcd.set_rotation.return_value = {
            "success": False, "error": "Rotation must be 0, 90, 180, or 270"}
        resp = self.client.post("/display/rotation", json={"degrees": 45})
        self.assertEqual(resp.status_code, 400)

    def test_set_split_success(self):
        self.mock_lcd.set_split_mode.return_value = {
            "success": True, "message": "Split mode set to style 1"}
        resp = self.client.post("/display/split", json={"mode": 1})
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.set_split_mode.assert_called_once_with(1)

    def test_reset_display(self):
        self.mock_lcd.reset.return_value = {
            "success": True, "message": "Device reset"}
        resp = self.client.post("/display/reset")
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.reset.assert_called_once()

    def test_display_no_device_returns_409(self):
        api_module._display_dispatcher = None
        resp = self.client.post("/display/color", json={"hex": "ff0000"})
        self.assertEqual(resp.status_code, 409)

    def test_overlay_path_success(self):
        self.mock_lcd.render_overlay.return_value = {
            "success": True, "elements": 5, "display_opts": {},
            "message": "Overlay config loaded"}
        resp = self.client.post("/display/overlay?dc_path=/tmp/config1.dc&send=true")
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.render_overlay.assert_called_once()

    def test_mask_upload(self):
        self.mock_lcd.load_mask.return_value = {
            "success": True, "message": "Sent mask"}
        img = Image.new('RGBA', (100, 100), (255, 0, 0, 128))
        buf = io.BytesIO()
        img.save(buf, format='PNG')
        buf.seek(0)

        resp = self.client.post(
            "/display/mask",
            files={"image": ("mask.png", buf, "image/png")},
        )
        self.assertEqual(resp.status_code, 200)
        self.mock_lcd.load_mask.assert_called_once()


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

    def test_set_color(self):
        self.mock_led.set_color.return_value = {
            "success": True, "message": "LED color set to #ff0000"}
        resp = self.client.post("/led/color", json={"hex": "ff0000"})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_color.assert_called_once_with(255, 0, 0)

    def test_set_color_invalid_hex(self):
        resp = self.client.post("/led/color", json={"hex": "zz"})
        self.assertEqual(resp.status_code, 400)

    def test_set_mode_success(self):
        self.mock_led.set_mode.return_value = {
            "success": True, "message": "LED mode: breathing", "animated": True}
        resp = self.client.post("/led/mode", json={"mode": "breathing"})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_mode.assert_called_once_with("breathing")

    def test_set_mode_invalid(self):
        self.mock_led.set_mode.return_value = {
            "success": False, "error": "Unknown mode 'invalid'"}
        resp = self.client.post("/led/mode", json={"mode": "invalid"})
        self.assertEqual(resp.status_code, 400)

    def test_set_brightness(self):
        self.mock_led.set_brightness.return_value = {
            "success": True, "message": "LED brightness set to 75%"}
        resp = self.client.post("/led/brightness", json={"level": 75})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_brightness.assert_called_once_with(75)

    def test_set_brightness_invalid(self):
        self.mock_led.set_brightness.return_value = {
            "success": False, "error": "Brightness must be 0-100"}
        resp = self.client.post("/led/brightness", json={"level": 150})
        self.assertEqual(resp.status_code, 400)

    def test_turn_off(self):
        self.mock_led.off.return_value = {
            "success": True, "message": "LEDs turned off"}
        resp = self.client.post("/led/off")
        self.assertEqual(resp.status_code, 200)
        self.mock_led.off.assert_called_once()

    def test_set_sensor(self):
        self.mock_led.set_sensor_source.return_value = {
            "success": True, "message": "LED sensor source set to CPU"}
        resp = self.client.post("/led/sensor", json={"source": "cpu"})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_sensor_source.assert_called_once_with("cpu")

    def test_set_sensor_invalid(self):
        self.mock_led.set_sensor_source.return_value = {
            "success": False, "error": "Source must be 'cpu' or 'gpu'"}
        resp = self.client.post("/led/sensor", json={"source": "ram"})
        self.assertEqual(resp.status_code, 400)

    def test_set_zone_color(self):
        self.mock_led.set_zone_color.return_value = {
            "success": True, "message": "Zone 0 color set"}
        resp = self.client.post("/led/zones/0/color", json={"hex": "00ff00"})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_zone_color.assert_called_once_with(0, 0, 255, 0)

    def test_set_zone_mode(self):
        self.mock_led.set_zone_mode.return_value = {
            "success": True, "message": "Zone 1 mode set"}
        resp = self.client.post("/led/zones/1/mode", json={"mode": "rainbow"})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_zone_mode.assert_called_once_with(1, "rainbow")

    def test_set_zone_brightness(self):
        self.mock_led.set_zone_brightness.return_value = {
            "success": True, "message": "Zone 2 brightness set"}
        resp = self.client.post("/led/zones/2/brightness", json={"level": 50})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_zone_brightness.assert_called_once_with(2, 50)

    def test_toggle_zone(self):
        self.mock_led.toggle_zone.return_value = {
            "success": True, "message": "Zone 0 turned ON"}
        resp = self.client.post("/led/zones/0/toggle", json={"on": True})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.toggle_zone.assert_called_once_with(0, True)

    def test_set_sync(self):
        self.mock_led.set_zone_sync.return_value = {
            "success": True, "message": "Zone sync enabled"}
        resp = self.client.post("/led/sync", json={"enabled": True, "interval": 2})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_zone_sync.assert_called_once_with(True, 2)

    def test_toggle_segment(self):
        self.mock_led.toggle_segment.return_value = {
            "success": True, "message": "Segment 0 turned OFF"}
        resp = self.client.post("/led/segments/0/toggle", json={"on": False})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.toggle_segment.assert_called_once_with(0, False)

    def test_set_clock_format(self):
        self.mock_led.set_clock_format.return_value = {
            "success": True, "message": "Clock format set to 24h"}
        resp = self.client.post("/led/clock", json={"is_24h": True})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_clock_format.assert_called_once_with(True)

    def test_set_temp_unit(self):
        self.mock_led.set_temp_unit.return_value = {
            "success": True, "message": "Temperature unit set to Fahrenheit"}
        resp = self.client.post("/led/temp-unit", json={"unit": "F"})
        self.assertEqual(resp.status_code, 200)
        self.mock_led.set_temp_unit.assert_called_once_with("F")

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


class TestStaticMounts(unittest.TestCase):
    """mount_static_dirs() mounts existing directories."""

    def test_mount_static_dirs_creates_routes(self):
        import tempfile
        from pathlib import Path

        from trcc.api import mount_static_dirs

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create a fake theme directory structure
            theme_dir = Path(tmpdir) / 'theme320320' / 'TestTheme'
            theme_dir.mkdir(parents=True)
            (theme_dir / 'Theme.png').write_bytes(b'fake')

            with patch('trcc.adapters.infra.data_repository.ThemeDir.for_resolution') as mock_td, \
                 patch('trcc.adapters.infra.data_repository.DataManager.get_web_dir', return_value='/nonexistent'), \
                 patch('trcc.adapters.infra.data_repository.DataManager.get_web_masks_dir', return_value='/nonexistent'):
                mock_td_obj = MagicMock()
                mock_td_obj.path = str(Path(tmpdir) / 'theme320320')
                mock_td.return_value = mock_td_obj
                mount_static_dirs(320, 320)

            # Verify at least the theme mount was created
            from trcc.api import _mounted_routes
            self.assertIn("/static/themes", _mounted_routes)


if __name__ == '__main__':
    unittest.main()
