"""Tests for LCDDevice (core/lcd_device.py) + CLI display wrappers (_display.py).

Fixtures build mock services and inject them into LCDDevice. Tests verify
LCDDevice methods return correct result dicts, and CLI wrappers
print/exit correctly.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from conftest import make_test_surface

from trcc.core.lcd_device import LCDDevice

# =========================================================================
# Patch-path constants
# =========================================================================
_IMG_SVC = "trcc.services.ImageService"
_OVL_SVC = "trcc.services.OverlayService"
_METRICS = "trcc.services.system.get_all_metrics"
_DEV_SVC = "trcc.services.DeviceService"
_CONNECT = "trcc.cli._display._connect_or_fail"
_SETTINGS_KEY = "trcc.conf.Settings.device_config_key"
_SETTINGS_SAVE = "trcc.conf.Settings.save_device_setting"


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def mock_device_info():
    """A mock DeviceInfo (the selected device)."""
    dev = MagicMock()
    dev.resolution = (320, 320)
    dev.path = "/dev/sg0"
    dev.vid = 0x0402
    dev.pid = 0x3922
    dev.device_index = 0
    return dev


@pytest.fixture
def mock_device_svc(mock_device_info):
    """Mock DeviceService with a pre-selected device."""
    svc = MagicMock()
    svc.selected = mock_device_info
    svc.send_frame.return_value = True
    svc.is_busy = False
    return svc


@pytest.fixture
def mock_display_svc():
    """Mock DisplayService."""
    svc = MagicMock()
    svc.lcd_width = 320
    svc.lcd_height = 320
    svc.overlay = MagicMock()
    svc.overlay.enabled = False
    svc.media = MagicMock()
    svc.media.has_frames = False
    svc.current_image = None
    svc.auto_send = False
    return svc


@pytest.fixture
def mock_theme_svc():
    """Mock ThemeService."""
    return MagicMock()


@pytest.fixture
def lcd(mock_device_svc, mock_display_svc, mock_theme_svc):
    """Fully wired LCDDevice with mock services."""
    return LCDDevice(
        device_svc=mock_device_svc,
        display_svc=mock_display_svc,
        theme_svc=mock_theme_svc,
    )


@pytest.fixture
def lcd_empty():
    """LCDDevice with no services (not connected)."""
    return LCDDevice()


@pytest.fixture
def mock_connect(lcd):
    """Patch _connect_or_fail to return 0 (success) and wire TrccApp.lcd_device + lcd_bus.

    lcd_bus is a REAL CommandBus wired to the mock lcd so tests can verify
    that bus dispatch reaches the right service methods.
    """
    from trcc.core.app import TrccApp
    mock_app = TrccApp._instance
    mock_app.lcd_device = lcd
    mock_app.lcd_bus = TrccApp.build_lcd_bus(mock_app, lcd)  # type: ignore[arg-type]
    with patch(_CONNECT, return_value=0):
        yield lcd


@pytest.fixture
def mock_connect_fail():
    """Patch _connect_or_fail to simulate no device (returns 1)."""
    with patch(_CONNECT, return_value=1):
        yield


def _make_png(path: Path, w=10, h=10, color=(255, 0, 0)) -> Path:
    """Write a minimal PNG to *path* and return it."""
    make_test_surface(w, h, color).save(str(path), "PNG")
    return path


# =========================================================================
# TestLCDDeviceInit — construction, properties
# =========================================================================

class TestLCDDeviceInit:
    def test_default_no_services(self, lcd_empty):
        assert lcd_empty.frame is lcd_empty
        assert lcd_empty.overlay is lcd_empty
        assert lcd_empty.video is lcd_empty
        assert lcd_empty.theme is lcd_empty
        # settings points to self (methods inlined on LCDDevice)
        assert lcd_empty.settings is lcd_empty

    def test_injected_services_compose(self, lcd):
        assert lcd.frame is lcd
        assert lcd.overlay is lcd
        assert lcd.video is lcd
        assert lcd.theme is lcd
        assert lcd.settings is lcd

    def test_connected_false_when_no_svc(self, lcd_empty):
        assert lcd_empty.connected is False

    def test_connected_false_when_no_selected(self):
        svc = MagicMock()
        svc.selected = None
        lcd = LCDDevice(device_svc=svc, display_svc=MagicMock(),
                        theme_svc=MagicMock())
        assert lcd.connected is False

    def test_connected_true_when_selected(self, lcd):
        assert lcd.connected is True

    def test_device_info_returns_selected(self, lcd, mock_device_info):
        assert lcd.device_info is mock_device_info

    def test_device_info_none_when_no_svc(self, lcd_empty):
        assert lcd_empty.device_info is None

    def test_resolution_with_services(self, lcd):
        assert lcd.resolution == (320, 320)

    def test_resolution_no_services(self, lcd_empty):
        assert lcd_empty.resolution == (0, 0)

    def test_device_path_with_device(self, lcd):
        assert lcd.device_path == "/dev/sg0"

    def test_device_path_no_device(self, lcd_empty):
        assert lcd_empty.device_path is None


# =========================================================================
# TestLCDDeviceConnect
# =========================================================================

def _mock_build_services_fn():
    """Create a mock build_services_fn for testing."""
    def _build(device_svc, renderer=None):
        return {
            'display_svc': MagicMock(),
            'theme_svc': MagicMock(),
            'renderer': renderer or MagicMock(),
            'dc_config_cls': MagicMock(),
            'load_config_json_fn': MagicMock(),
        }
    return _build


class TestLCDDeviceConnect:
    def test_connect_success(self):
        svc = MagicMock()
        dev = MagicMock()
        dev.resolution = (320, 320)
        dev.path = "/dev/sg0"
        svc.selected = dev

        lcd = LCDDevice(device_svc=svc, build_services_fn=_mock_build_services_fn())
        result = lcd.connect()

        assert result["success"] is True
        assert result["resolution"] == (320, 320)
        assert result["device_path"] == "/dev/sg0"

    def test_connect_no_device(self):
        svc = MagicMock()
        svc.selected = None

        lcd = LCDDevice(device_svc=svc, build_services_fn=_mock_build_services_fn())
        result = lcd.connect()

        assert result["success"] is False
        assert "No LCD device" in result["error"]

    def test_connect_with_device_path(self):
        svc = MagicMock()
        dev = MagicMock()
        dev.resolution = (640, 480)
        dev.path = "/dev/sg1"
        svc.selected = dev

        lcd = LCDDevice(device_svc=svc, build_services_fn=_mock_build_services_fn())
        lcd.connect("/dev/sg1")

        svc.scan_and_select.assert_called_once_with("/dev/sg1")

    def test_connect_builds_capabilities(self):
        svc = MagicMock()
        dev = MagicMock()
        dev.resolution = (320, 320)
        dev.path = "/dev/sg0"
        svc.selected = dev

        lcd = LCDDevice(device_svc=svc, build_services_fn=_mock_build_services_fn())
        assert lcd.frame is lcd  # frame always points to self
        lcd.connect()
        assert lcd.frame is lcd  # still self after connect


# =========================================================================
# TestFrameOps
# =========================================================================

class TestFrameOps:
    def test_send_image_missing_file(self, lcd):
        result = lcd.frame.send_image("/nonexistent/file.png")
        assert result["success"] is False
        assert "File not found" in result["error"]

    def test_send_image_success(self, lcd, mock_device_svc, tmp_path):
        img_path = str(_make_png(tmp_path / "test.png"))
        mock_img = make_test_surface(10, 10)

        with patch(f"{_IMG_SVC}.open_and_resize", return_value=mock_img):
            result = lcd.frame.send_image(img_path)

        assert result["success"] is True
        assert "image" in result
        assert "Sent" in result["message"]
        mock_device_svc.send_frame.assert_called_once()

    def test_send_color_success(self, lcd, mock_device_svc):
        mock_img = make_test_surface(320, 320, (255, 0, 0))

        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            result = lcd.frame.send_color(255, 0, 0)

        assert result["success"] is True
        assert "ff0000" in result["message"]
        mock_device_svc.send_frame.assert_called_once_with(mock_img, 320, 320)

    def test_send_color_args(self, lcd):
        mock_img = make_test_surface(320, 320)

        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img) as mock_sc:
            lcd.frame.send_color(0, 128, 255)

        mock_sc.assert_called_once_with(0, 128, 255, 320, 320)

    def test_reset_sends_red_frame(self, lcd, mock_device_svc):
        mock_img = make_test_surface(320, 320, (255, 0, 0))

        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img) as mock_sc:
            result = lcd.frame.reset()

        assert result["success"] is True
        assert "RED" in result["message"]
        mock_sc.assert_called_once_with(255, 0, 0, 320, 320)
        mock_device_svc.send_frame.assert_called_once_with(mock_img, 320, 320)


# =========================================================================
# TestDisplaySettings
# =========================================================================

class TestDisplaySettings:
    def test_set_brightness_level_1(self, lcd, mock_display_svc):
        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            result = lcd.settings.set_brightness(1)

        assert result["success"] is True
        assert "25%" in result["message"]
        mock_display_svc.set_brightness.assert_called_once_with(25)

    def test_set_brightness_level_2(self, lcd, mock_display_svc):
        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            result = lcd.settings.set_brightness(2)

        assert result["success"] is True
        assert "50%" in result["message"]
        mock_display_svc.set_brightness.assert_called_once_with(50)

    def test_set_brightness_level_3(self, lcd, mock_display_svc):
        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            result = lcd.settings.set_brightness(3)

        assert result["success"] is True
        assert "100%" in result["message"]

    def test_set_brightness_percent_50(self, lcd, mock_display_svc):
        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            result = lcd.settings.set_brightness(50)

        assert result["success"] is True
        assert "50%" in result["message"]

    def test_set_brightness_invalid_negative(self, lcd):
        result = lcd.settings.set_brightness(-1)
        assert result["success"] is False

    def test_set_brightness_invalid_over_100(self, lcd):
        result = lcd.settings.set_brightness(101)
        assert result["success"] is False

    def test_set_brightness_persists(self, lcd):
        with patch(_SETTINGS_KEY, return_value="0") as mk, \
             patch(_SETTINGS_SAVE) as ms:
            lcd.settings.set_brightness(2)

        mk.assert_called_once_with(0, 0x0402, 0x3922)
        ms.assert_called_once_with("0", "brightness_level", 2)

    def test_set_rotation_0(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), \
             patch(_SETTINGS_SAVE) as ms:
            result = lcd.settings.set_rotation(0)

        assert result["success"] is True
        assert "0°" in result["message"]
        ms.assert_called_once_with("k", "rotation", 0)

    def test_set_rotation_90(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), patch(_SETTINGS_SAVE):
            result = lcd.settings.set_rotation(90)
        assert result["success"] is True
        assert "90°" in result["message"]

    def test_set_rotation_180(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), patch(_SETTINGS_SAVE):
            result = lcd.settings.set_rotation(180)
        assert result["success"] is True

    def test_set_rotation_270(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), patch(_SETTINGS_SAVE):
            result = lcd.settings.set_rotation(270)
        assert result["success"] is True

    def test_set_rotation_invalid_45(self, lcd):
        result = lcd.settings.set_rotation(45)
        assert result["success"] is False
        assert "0, 90, 180, or 270" in result["error"]

    def test_set_split_mode_0_off(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), \
             patch(_SETTINGS_SAVE) as ms:
            result = lcd.settings.set_split_mode(0)

        assert result["success"] is True
        assert "off" in result["message"]
        ms.assert_called_once_with("k", "split_mode", 0)

    def test_set_split_mode_1(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), patch(_SETTINGS_SAVE):
            result = lcd.settings.set_split_mode(1)
        assert result["success"] is True
        assert "style 1" in result["message"]

    def test_set_split_mode_2(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), patch(_SETTINGS_SAVE):
            result = lcd.settings.set_split_mode(2)
        assert result["success"] is True

    def test_set_split_mode_3(self, lcd):
        with patch(_SETTINGS_KEY, return_value="k"), patch(_SETTINGS_SAVE):
            result = lcd.settings.set_split_mode(3)
        assert result["success"] is True

    def test_set_split_mode_invalid_5(self, lcd):
        result = lcd.settings.set_split_mode(5)
        assert result["success"] is False
        assert "0, 1, 2, or 3" in result["error"]


# =========================================================================
# TestOverlayOps — standalone CLI overlay operations
# =========================================================================

class TestOverlayOps:
    def test_load_mask_standalone_missing_path(self, lcd):
        result = lcd.load_mask_standalone("/nonexistent/mask.png")
        assert result["success"] is False
        assert "Path not found" in result["error"]

    def test_load_mask_standalone_with_file(self, lcd, tmp_path):
        mask_file = tmp_path / "mask.png"
        make_test_surface(10, 10, (255, 255, 255, 128)).save(str(mask_file), "PNG")
        result_img = make_test_surface(10, 10)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(f"{_IMG_SVC}._r") as mock_r:
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img
            mock_renderer = MagicMock()
            mock_r.return_value = mock_renderer
            mock_renderer.convert_to_rgba.return_value = MagicMock()
            mock_renderer.open_image.return_value = MagicMock()
            mock_renderer.surface_size.return_value = (10, 10)

            result = lcd.load_mask_standalone(str(mask_file))

        assert result["success"] is True
        assert "mask.png" in result["message"]

    def test_load_mask_standalone_directory_01_png(self, lcd, tmp_path):
        mask_dir = tmp_path / "masks"
        mask_dir.mkdir()
        make_test_surface(10, 10, (0, 0, 0, 255)).save(str(mask_dir / "01.png"), "PNG")
        result_img = make_test_surface(10, 10)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(f"{_IMG_SVC}._r") as mock_r:
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img
            mock_renderer = MagicMock()
            mock_r.return_value = mock_renderer
            mock_renderer.convert_to_rgba.return_value = MagicMock()
            mock_renderer.open_image.return_value = MagicMock()
            mock_renderer.surface_size.return_value = (10, 10)

            result = lcd.load_mask_standalone(str(mask_dir))

        assert result["success"] is True
        assert "01.png" in result["message"]

    def test_load_mask_standalone_directory_fallback_png(self, lcd, tmp_path):
        mask_dir = tmp_path / "masks2"
        mask_dir.mkdir()
        make_test_surface(10, 10, (0, 0, 0, 255)).save(str(mask_dir / "other.png"), "PNG")
        result_img = make_test_surface(10, 10)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(f"{_IMG_SVC}._r") as mock_r:
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img
            mock_renderer = MagicMock()
            mock_r.return_value = mock_renderer
            mock_renderer.convert_to_rgba.return_value = MagicMock()
            mock_renderer.open_image.return_value = MagicMock()
            mock_renderer.surface_size.return_value = (10, 10)

            result = lcd.load_mask_standalone(str(mask_dir))

        assert result["success"] is True
        assert "other.png" in result["message"]

    def test_load_mask_standalone_empty_directory(self, lcd, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()
        result = lcd.load_mask_standalone(str(empty_dir))
        assert result["success"] is False
        assert "No PNG files" in result["error"]

    def test_render_overlay_missing_path(self, lcd):
        result = lcd.render_overlay_from_dc("/nonexistent/config1.dc")
        assert result["success"] is False
        assert "Path not found" in result["error"]

    def test_render_overlay_success(self, lcd, tmp_path):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)
        result_img = make_test_surface(320, 320)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {"key": "value"}
            mock_overlay.config = [MagicMock()] * 3
            mock_overlay.render.return_value = result_img

            result = lcd.render_overlay_from_dc(str(dc_file))

        assert result["success"] is True
        assert result["elements"] == 3

    def test_render_overlay_with_send(self, lcd, mock_device_svc, tmp_path):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)
        result_img = make_test_surface(320, 320)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            result = lcd.render_overlay_from_dc(str(dc_file), send=True)

        assert result["success"] is True
        assert "/dev/sg0" in result["message"]

    def test_render_overlay_with_output(self, lcd, tmp_path):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)
        output_file = str(tmp_path / "out.png")
        result_img = MagicMock()

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            result = lcd.render_overlay_from_dc(
                str(dc_file), output=output_file)

        assert result["success"] is True
        assert output_file in result["message"]
        result_img.save.assert_called_once_with(output_file)

    def test_render_overlay_dc_directory(self, lcd, tmp_path):
        """Accepts directory, uses config1.dc inside it."""
        theme_dir = tmp_path / "theme"
        theme_dir.mkdir()
        (theme_dir / "config1.dc").write_bytes(b"\xDD" + b"\x00" * 50)
        result_img = make_test_surface(320, 320)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            result = lcd.render_overlay_from_dc(str(theme_dir))

        assert result["success"] is True


# =========================================================================
# TestCLIHelpers — _connect_or_fail, _print_result, _display_command
# =========================================================================

class TestCLIHelpers:
    def test_connect_or_fail_success(self, capsys):
        from trcc.cli._display import _connect_or_fail
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult

        mock_app = TrccApp.get()
        mock_app.os_bus.dispatch.return_value = CommandResult.ok(message="1 device(s) found")  # type: ignore[union-attr]
        mock_app.has_lcd = True  # type: ignore[union-attr]
        rc = _connect_or_fail()

        assert rc == 0

    def test_connect_or_fail_no_device(self, capsys):
        from trcc.cli._display import _connect_or_fail
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult

        mock_app = TrccApp.get()
        mock_app.os_bus.dispatch.return_value = CommandResult.fail("No LCD device found.")  # type: ignore[union-attr]
        mock_app.has_lcd = False  # type: ignore[union-attr]
        rc = _connect_or_fail()

        assert rc == 1
        assert "trcc report" in capsys.readouterr().out

    def test_connect_or_fail_passes_device_arg(self):
        from trcc.cli._display import _connect_or_fail
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult
        from trcc.core.commands.initialize import DiscoverDevicesCommand

        mock_app = TrccApp.get()
        mock_app.os_bus.dispatch.return_value = CommandResult.ok(message="ok")  # type: ignore[union-attr]
        mock_app.has_lcd = True  # type: ignore[union-attr]
        _connect_or_fail("/dev/sg2")

        mock_app.os_bus.dispatch.assert_called_once_with(DiscoverDevicesCommand(path="/dev/sg2"))  # type: ignore[union-attr]

    def test_print_result_success(self, capsys):
        from trcc.cli._display import _print_result

        rc = _print_result({"success": True, "message": "All good"})
        assert rc == 0
        assert "All good" in capsys.readouterr().out

    def test_print_result_failure(self, capsys):
        from trcc.cli._display import _print_result

        rc = _print_result({"success": False, "error": "Something broke"})
        assert rc == 1
        assert "Error: Something broke" in capsys.readouterr().out

    def test_print_result_with_warning(self, capsys):
        from trcc.cli._display import _print_result

        _print_result({"success": True, "message": "Done",
                       "warning": "Watch out"})
        out = capsys.readouterr().out
        assert "Warning: Watch out" in out
        assert "Done" in out

    def test_print_result_with_preview(self, capsys):
        from trcc.cli._display import _print_result

        fake_img = MagicMock()
        with patch(f"{_IMG_SVC}.to_ansi", return_value="ANSI_ART"):
            _print_result({"success": True, "message": "OK",
                          "image": fake_img}, preview=True)
        assert "ANSI_ART" in capsys.readouterr().out

    def test_print_result_no_preview_when_no_image(self, capsys):
        from trcc.cli._display import _print_result

        with patch(f"{_IMG_SVC}.to_ansi") as mock_ansi:
            _print_result({"success": True, "message": "OK"}, preview=True)
        mock_ansi.assert_not_called()



# =========================================================================
# TestCLIImageCommands
# =========================================================================

class TestCLIImageCommands:
    def test_send_image_cli_success(self, _mock_builder, mock_connect, tmp_path):
        from trcc.cli._display import send_image

        img_path = str(_make_png(tmp_path / "pic.png", w=10, h=10))
        mock_img = make_test_surface(10, 10)

        with patch(f"{_IMG_SVC}.open_and_resize", return_value=mock_img):
            rc = send_image(_mock_builder, img_path)
        assert rc == 0

    def test_send_image_cli_missing_file(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import send_image

        # Real bus + real lcd: send_image("/nonexistent") → lcd.send_image fails → rc=1
        rc = send_image(_mock_builder, "/nonexistent/file.png")
        assert rc == 1
        assert "Error" in capsys.readouterr().out

    def test_send_color_cli_valid_hex(self, _mock_builder, mock_connect):
        from trcc.cli._display import send_color

        mock_img = make_test_surface(320, 320)
        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            rc = send_color(_mock_builder, "ff0000")
        assert rc == 0

    def test_send_color_cli_with_hash_prefix(self, _mock_builder, mock_connect):
        from trcc.cli._display import send_color

        mock_img = make_test_surface(320, 320)
        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            rc = send_color(_mock_builder, "#00ff00")
        assert rc == 0

    def test_send_color_cli_invalid_hex_too_short(self, _mock_builder, capsys):
        from trcc.cli._display import send_color

        rc = send_color(_mock_builder, "fff")
        assert rc == 1
        assert "Invalid hex color" in capsys.readouterr().out

    def test_send_color_cli_invalid_hex_too_long(self, _mock_builder, capsys):
        from trcc.cli._display import send_color

        rc = send_color(_mock_builder, "ff000000")
        assert rc == 1

    def test_send_color_cli_invalid_hex_non_hex_chars(self, _mock_builder, capsys):
        from trcc.cli._display import send_color

        rc = send_color(_mock_builder, "zzzzzz")
        assert rc == 1


# =========================================================================
# TestCLISettingCommands
# =========================================================================

class TestCLISettingCommands:
    def test_set_brightness_cli_valid_1(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_brightness

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_brightness(_mock_builder, 1)
        assert rc == 0

    def test_set_brightness_cli_valid_2(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_brightness

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_brightness(_mock_builder, 2)
        assert rc == 0

    def test_set_brightness_cli_valid_3(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_brightness

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_brightness(_mock_builder, 3)
        assert rc == 0

    def test_set_brightness_cli_invalid_prints_help(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import set_brightness

        # Real bus + real lcd: set_brightness(-1) → lcd.set_brightness(-1) fails
        rc = set_brightness(_mock_builder, -1)
        assert rc == 1
        out = capsys.readouterr().out
        assert "25%" in out
        assert "50%" in out
        assert "100%" in out

    def test_set_brightness_cli_no_device(self, _mock_builder, mock_connect_fail, capsys):
        from trcc.cli._display import set_brightness

        rc = set_brightness(_mock_builder, 2)
        assert rc == 1

    def test_set_rotation_cli_valid_0(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_rotation

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(_mock_builder, 0)
        assert rc == 0

    def test_set_rotation_cli_valid_90(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_rotation

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(_mock_builder, 90)
        assert rc == 0

    def test_set_rotation_cli_valid_180(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_rotation

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(_mock_builder, 180)
        assert rc == 0

    def test_set_rotation_cli_valid_270(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_rotation

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(_mock_builder, 270)
        assert rc == 0

    def test_set_rotation_cli_invalid_45(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import set_rotation

        # Real bus + real lcd: set_rotation(45) → lcd.set_rotation(45) fails
        rc = set_rotation(_mock_builder, 45)
        assert rc == 1
        assert "Error" in capsys.readouterr().out

    def test_set_split_mode_cli_valid(self, _mock_builder, mock_connect):
        from trcc.cli._display import set_split_mode

        with patch(_SETTINGS_KEY, return_value="0"), \
             patch(_SETTINGS_SAVE):
            rc = set_split_mode(_mock_builder, 0)
        assert rc == 0

    def test_set_split_mode_cli_invalid(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import set_split_mode

        # Real bus + real lcd: set_split_mode(5) → lcd.set_split_mode(5) fails
        rc = set_split_mode(_mock_builder, 5)
        assert rc == 1


# =========================================================================
# TestCLIOverlayCommands
# =========================================================================

class TestCLIOverlayCommands:
    def test_load_mask_cli_success(self, _mock_builder, mock_connect, tmp_path):
        from trcc.cli._display import load_mask

        mask_file = tmp_path / "mask.png"
        make_test_surface(10, 10, (255, 255, 255, 128)).save(str(mask_file), "PNG")
        result_img = make_test_surface(10, 10)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(f"{_IMG_SVC}._r") as mock_r:
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img
            mock_renderer = MagicMock()
            mock_r.return_value = mock_renderer
            mock_renderer.convert_to_rgba.return_value = MagicMock()
            mock_renderer.open_image.return_value = MagicMock()
            mock_renderer.surface_size.return_value = (10, 10)

            rc = load_mask(_mock_builder, str(mask_file))
        assert rc == 0

    def test_load_mask_cli_missing_path(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import load_mask

        rc = load_mask(_mock_builder, "/nonexistent/mask.png")
        assert rc == 1

    def test_render_overlay_cli_success(self, _mock_builder, mock_connect, tmp_path, capsys):
        from trcc.cli._display import render_overlay

        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)
        result_img = make_test_surface(320, 320)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {"orientation": "landscape"}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            rc = render_overlay(_mock_builder, str(dc_file))

        assert rc == 0
        out = capsys.readouterr().out
        assert "orientation" in out

    def test_render_overlay_cli_missing_path(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import render_overlay

        rc = render_overlay(_mock_builder, "/nonexistent/config1.dc")
        assert rc == 1
        assert "Error" in capsys.readouterr().out

    def test_render_overlay_cli_with_preview(self, _mock_builder, mock_connect, tmp_path,
                                             capsys):
        from trcc.cli._display import render_overlay

        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)
        result_img = make_test_surface(320, 320)

        with patch(_OVL_SVC) as mock_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(f"{_IMG_SVC}.to_ansi", return_value="ANSI_PREVIEW"), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            rc = render_overlay(_mock_builder, str(dc_file), preview=True)

        assert rc == 0
        assert "ANSI_PREVIEW" in capsys.readouterr().out


# =========================================================================
# TestCLIReset
# =========================================================================

class TestCLIReset:
    def test_reset_cli_success(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import reset

        mock_img = make_test_surface(320, 320, (255, 0, 0))
        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            rc = reset(_mock_builder)

        assert rc == 0
        out = capsys.readouterr().out
        assert "/dev/sg0" in out

    def test_reset_cli_no_device(self, _mock_builder, mock_connect_fail, capsys):
        from trcc.cli._display import reset

        rc = reset(_mock_builder)
        assert rc == 1

    def test_reset_cli_prints_device_path(self, _mock_builder, mock_connect, capsys):
        from trcc.cli._display import reset

        mock_img = make_test_surface(320, 320, (255, 0, 0))
        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            reset(_mock_builder)

        out = capsys.readouterr().out
        assert "Device:" in out
        assert "/dev/sg0" in out


# =========================================================================
# TestCLIVideoStatus
# =========================================================================

class TestCLIVideoStatus:
    def test_video_status_prints_instructions(self, capsys):
        from trcc.cli._display import video_status

        rc = video_status()

        assert rc == 0
        assert "video" in capsys.readouterr().out.lower()


# =========================================================================
# TestCLIResume — headless theme send (uses DeviceService directly)
# =========================================================================

_TIME = "time.sleep"


class TestCLIResume:
    """resume() — dispatches DiscoverDevicesCommand + RestoreLastThemeCommand via TrccApp."""

    def test_resume_no_devices(self, _mock_builder, capsys):
        """No LCD found after 10 attempts → rc=1, prints 'No compatible'."""
        from trcc.cli._display import resume
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult

        mock_app = TrccApp._instance
        mock_app.has_lcd = False
        mock_app.os_bus.dispatch.return_value = CommandResult.ok()

        with patch(_TIME):
            rc = resume(_mock_builder)

        assert rc == 1
        assert "No compatible" in capsys.readouterr().out

    def test_resume_no_theme(self, _mock_builder, capsys):
        """Device found but RestoreLastThemeCommand fails → rc=1, prints error."""
        from trcc.cli._display import resume
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult

        mock_app = TrccApp._instance
        mock_app.has_lcd = True
        mock_app.lcd_bus.dispatch.return_value = CommandResult.fail("No saved theme")

        with patch(_TIME):
            rc = resume(_mock_builder)

        assert rc == 1
        assert "No saved theme" in capsys.readouterr().out

    def test_resume_success(self, _mock_builder, capsys):
        """Device found and RestoreLastThemeCommand succeeds → rc=0, prints 'Resumed'."""
        from trcc.cli._display import resume
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult

        mock_app = TrccApp._instance
        mock_app.has_lcd = True
        mock_app.lcd_device.device_path = "/dev/sg0"
        mock_app.lcd_bus.dispatch.return_value = CommandResult.ok()

        with patch(_TIME):
            rc = resume(_mock_builder)

        assert rc == 0
        assert "Resumed 1 device" in capsys.readouterr().out

    def test_resume_waits_for_device(self, _mock_builder, capsys):
        """Device not found initially → prints 'Waiting', succeeds when found."""
        from trcc.cli._display import resume
        from trcc.core.app import TrccApp
        from trcc.core.command_bus import CommandResult

        mock_app = TrccApp._instance
        mock_app.lcd_device.device_path = "/dev/sg0"
        # First 2 dispatches: has_lcd=False; 3rd: has_lcd=True
        call_count = 0

        def _dispatch(cmd):
            nonlocal call_count
            call_count += 1
            mock_app.has_lcd = call_count >= 3
            return CommandResult.ok()

        mock_app.os_bus.dispatch.side_effect = _dispatch
        mock_app.lcd_bus.dispatch.return_value = CommandResult.ok()

        with patch(_TIME):
            rc = resume(_mock_builder)

        out = capsys.readouterr().out
        assert "Waiting for device" in out
        assert rc == 0
