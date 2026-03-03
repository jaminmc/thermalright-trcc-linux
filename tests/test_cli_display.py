"""Tests for trcc.cli._display — DisplayDispatcher and CLI wrappers."""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

# =========================================================================
# Patch-path constants (lazy imports inside _display.py methods)
# =========================================================================
_IMG_SVC  = "trcc.services.ImageService"
_OVL_SVC  = "trcc.services.OverlayService"
_METRICS  = "trcc.services.system.get_all_metrics"
_SETTINGS_KEY = "trcc.conf.Settings.device_config_key"
_SETTINGS_SAVE = "trcc.conf.Settings.save_device_setting"
_GET_SVC  = "trcc.cli._device._get_service"


# =========================================================================
# Shared helpers
# =========================================================================

def _make_mock_svc(resolution=(320, 320), path="/dev/sg0",
                   vid=0x0402, pid=0x3922, device_index=0):
    """Build a mock DeviceService with a pre-selected device."""
    mock_svc = MagicMock()
    mock_dev = MagicMock()
    mock_dev.resolution = resolution
    mock_dev.path = path
    mock_dev.vid = vid
    mock_dev.pid = pid
    mock_dev.device_index = device_index
    mock_svc.selected = mock_dev
    mock_svc.send_pil.return_value = True
    return mock_svc, mock_dev


def _make_dispatcher(resolution=(320, 320), path="/dev/sg0"):
    """Return a DisplayDispatcher wired to a mock service."""
    from trcc.cli._display import DisplayDispatcher
    svc, _ = _make_mock_svc(resolution=resolution, path=path)
    return DisplayDispatcher(svc)


def _make_png(path: Path, w=10, h=10, color=(255, 0, 0)) -> Path:
    """Write a minimal PNG to *path* and return it."""
    img = Image.new("RGB", (w, h), color)
    img.save(path)
    return path


# =========================================================================
# TestDisplayDispatcherInit
# =========================================================================

class TestDisplayDispatcherInit:
    def test_default_no_service(self):
        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher()
        assert d._device_svc is None

    def test_injected_service_stored(self):
        from trcc.cli._display import DisplayDispatcher
        svc = MagicMock()
        d = DisplayDispatcher(svc)
        assert d._device_svc is svc

    def test_connected_false_when_no_svc(self):
        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher()
        assert d.connected is False

    def test_connected_false_when_svc_has_no_selected(self):
        from trcc.cli._display import DisplayDispatcher
        svc = MagicMock()
        svc.selected = None
        d = DisplayDispatcher(svc)
        assert d.connected is False

    def test_connected_true_when_selected(self):
        d = _make_dispatcher()
        assert d.connected is True

    def test_device_property_returns_selected(self):
        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc()
        d = DisplayDispatcher(svc)
        assert d.device is dev

    def test_device_property_none_when_no_svc(self):
        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher()
        assert d.device is None

    def test_service_property_returns_svc(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        assert d.service is svc

    def test_resolution_property_with_device(self):
        d = _make_dispatcher(resolution=(640, 480))
        assert d.resolution == (640, 480)

    def test_resolution_property_no_device(self):
        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher()
        assert d.resolution == (0, 0)

    def test_device_path_property_with_device(self):
        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc(path="/dev/sg1")
        d = DisplayDispatcher(svc)
        assert d.device_path == "/dev/sg1"

    def test_device_path_property_no_device(self):
        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher()
        assert d.device_path is None

    def test_dev_property_asserts_on_none(self):
        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher()
        with pytest.raises(AssertionError, match="connect\\(\\) must succeed"):
            _ = d._dev

    def test_dev_property_returns_device_when_connected(self):
        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc()
        d = DisplayDispatcher(svc)
        assert d._dev is dev


# =========================================================================
# TestDisplayDispatcherConnect
# =========================================================================

class TestDisplayDispatcherConnect:
    def test_connect_success(self):
        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc(resolution=(320, 320), path="/dev/sg0")
        with patch(_GET_SVC, return_value=svc):
            d = DisplayDispatcher()
            result = d.connect()
        assert result["success"] is True
        assert result["resolution"] == (320, 320)
        assert result["device_path"] == "/dev/sg0"

    def test_connect_no_device_found(self):
        from trcc.cli._display import DisplayDispatcher
        svc = MagicMock()
        svc.selected = None
        with patch(_GET_SVC, return_value=svc):
            d = DisplayDispatcher()
            result = d.connect()
        assert result["success"] is False
        assert "No device found" in result["error"]

    def test_connect_with_explicit_device_path(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc) as mock_gs:
            d = DisplayDispatcher()
            d.connect("/dev/sg1")
        mock_gs.assert_called_once_with("/dev/sg1")

    def test_connect_updates_svc(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            d = DisplayDispatcher()
            assert d._device_svc is None
            d.connect()
            assert d._device_svc is svc


# =========================================================================
# TestDisplayDispatcherImageOps
# =========================================================================

class TestDisplayDispatcherImageOps:
    def test_send_image_missing_file(self):
        d = _make_dispatcher()
        result = d.send_image("/nonexistent/file.png")
        assert result["success"] is False
        assert "File not found" in result["error"]

    def test_send_image_success(self, tmp_path):
        img_path = str(_make_png(tmp_path / "test.png"))
        svc, dev = _make_mock_svc(resolution=(10, 10))

        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher(svc)

        mock_img = Image.new("RGB", (10, 10), (255, 0, 0))

        with patch(f"{_IMG_SVC}.resize", return_value=mock_img):
            result = d.send_image(img_path)

        assert result["success"] is True
        assert "image" in result
        assert "Sent" in result["message"]
        svc.send_pil.assert_called_once()

    def test_send_image_includes_device_path(self, tmp_path):
        img_path = str(_make_png(tmp_path / "test.png"))
        svc, dev = _make_mock_svc(path="/dev/sg2", resolution=(10, 10))

        from trcc.cli._display import DisplayDispatcher
        d = DisplayDispatcher(svc)
        mock_img = Image.new("RGB", (10, 10))

        with patch(f"{_IMG_SVC}.resize", return_value=mock_img):
            result = d.send_image(img_path)

        assert "/dev/sg2" in result["message"]

    def test_send_color_success(self):
        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc(resolution=(320, 320))
        d = DisplayDispatcher(svc)
        mock_img = Image.new("RGB", (320, 320), (255, 0, 0))

        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            result = d.send_color(255, 0, 0)

        assert result["success"] is True
        assert "image" in result
        assert "ff0000" in result["message"]
        svc.send_pil.assert_called_once_with(mock_img, 320, 320)

    def test_send_color_calls_solid_color_with_correct_args(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(640, 480))
        d = DisplayDispatcher(svc)
        mock_img = Image.new("RGB", (640, 480))

        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img) as mock_sc:
            d.send_color(0, 128, 255)
        mock_sc.assert_called_once_with(0, 128, 255, 640, 480)

    def test_reset_sends_red_frame(self):
        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc(resolution=(320, 320), path="/dev/sg0")
        d = DisplayDispatcher(svc)
        mock_img = Image.new("RGB", (320, 320), (255, 0, 0))

        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img) as mock_sc:
            result = d.reset()

        assert result["success"] is True
        assert "RED" in result["message"]
        mock_sc.assert_called_once_with(255, 0, 0, 320, 320)
        svc.send_pil.assert_called_once_with(mock_img, 320, 320)

    def test_reset_message_includes_device_path(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(path="/dev/sg3")
        d = DisplayDispatcher(svc)
        mock_img = Image.new("RGB", (320, 320))

        with patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            result = d.reset()

        assert "/dev/sg3" in result["message"]


# =========================================================================
# TestDisplayDispatcherSettings
# =========================================================================

class TestDisplayDispatcherSettings:
    def test_persist_setting_calls_settings(self):
        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc(vid=0x0402, pid=0x3922, device_index=1)
        d = DisplayDispatcher(svc)

        with patch(_SETTINGS_KEY, return_value="1:0402_3922") as mock_key, \
             patch(_SETTINGS_SAVE) as mock_save:
            d._persist_setting("brightness_level", 2)

        mock_key.assert_called_once_with(1, 0x0402, 0x3922)
        mock_save.assert_called_once_with("1:0402_3922", "brightness_level", 2)

    # --- set_brightness ---

    def test_set_brightness_level_1(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting") as mock_persist:
            result = d.set_brightness(1)
        assert result["success"] is True
        assert "L1" in result["message"]
        assert "25%" in result["message"]
        mock_persist.assert_called_once_with("brightness_level", 1)

    def test_set_brightness_level_2(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_brightness(2)
        assert result["success"] is True
        assert "50%" in result["message"]

    def test_set_brightness_level_3(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_brightness(3)
        assert result["success"] is True
        assert "100%" in result["message"]

    def test_set_brightness_invalid_0(self):
        d = _make_dispatcher()
        result = d.set_brightness(0)
        assert result["success"] is False
        assert "1, 2, or 3" in result["error"]

    def test_set_brightness_invalid_4(self):
        d = _make_dispatcher()
        result = d.set_brightness(4)
        assert result["success"] is False

    # --- set_rotation ---

    def test_set_rotation_0(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting") as mock_persist:
            result = d.set_rotation(0)
        assert result["success"] is True
        assert "0°" in result["message"]
        mock_persist.assert_called_once_with("rotation", 0)

    def test_set_rotation_90(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_rotation(90)
        assert result["success"] is True
        assert "90°" in result["message"]

    def test_set_rotation_180(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_rotation(180)
        assert result["success"] is True

    def test_set_rotation_270(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc()
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_rotation(270)
        assert result["success"] is True

    def test_set_rotation_invalid_45(self):
        d = _make_dispatcher()
        result = d.set_rotation(45)
        assert result["success"] is False
        assert "0, 90, 180, or 270" in result["error"]

    # --- set_split_mode ---

    def test_set_split_mode_0_off(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(1600, 720))
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting") as mock_persist:
            result = d.set_split_mode(0)
        assert result["success"] is True
        assert "off" in result["message"]
        mock_persist.assert_called_once_with("split_mode", 0)

    def test_set_split_mode_1(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(1600, 720))
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_split_mode(1)
        assert result["success"] is True
        assert "style 1" in result["message"]

    def test_set_split_mode_2(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(1600, 720))
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_split_mode(2)
        assert result["success"] is True

    def test_set_split_mode_3(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(1600, 720))
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_split_mode(3)
        assert result["success"] is True

    def test_set_split_mode_invalid_5(self):
        d = _make_dispatcher()
        result = d.set_split_mode(5)
        assert result["success"] is False
        assert "0, 1, 2, or 3" in result["error"]

    def test_set_split_mode_warns_non_widescreen(self):
        # 320x320 is not in SPLIT_MODE_RESOLUTIONS
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(320, 320))
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_split_mode(1)
        assert result["success"] is True
        assert "warning" in result
        assert "320x320" in result["warning"]

    def test_set_split_mode_no_warning_for_widescreen(self):
        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(1600, 720))
        d = DisplayDispatcher(svc)
        with patch.object(d, "_persist_setting"):
            result = d.set_split_mode(1)
        assert "warning" not in result


# =========================================================================
# TestDisplayDispatcherOverlay
# =========================================================================

class TestDisplayDispatcherOverlay:
    def test_load_mask_missing_path(self):
        d = _make_dispatcher()
        result = d.load_mask("/nonexistent/mask.png")
        assert result["success"] is False
        assert "Path not found" in result["error"]

    def test_load_mask_with_file(self, tmp_path):
        mask_file = tmp_path / "mask.png"
        Image.new("RGBA", (10, 10), (255, 255, 255, 128)).save(str(mask_file))

        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc(resolution=(10, 10))
        d = DisplayDispatcher(svc)
        result_img = Image.new("RGB", (10, 10))

        with patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img

            result = d.load_mask(str(mask_file))

        assert result["success"] is True
        assert "image" in result
        assert "mask.png" in result["message"]

    def test_load_mask_with_directory_01_png(self, tmp_path):
        mask_dir = tmp_path / "masks"
        mask_dir.mkdir()
        Image.new("RGBA", (10, 10)).save(str(mask_dir / "01.png"))

        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(10, 10))
        d = DisplayDispatcher(svc)
        result_img = Image.new("RGB", (10, 10))

        with patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img

            result = d.load_mask(str(mask_dir))

        assert result["success"] is True
        assert "01.png" in result["message"]

    def test_load_mask_with_directory_fallback_png(self, tmp_path):
        mask_dir = tmp_path / "masks2"
        mask_dir.mkdir()
        # No "01.png" — use another PNG
        Image.new("RGBA", (10, 10)).save(str(mask_dir / "other.png"))

        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(10, 10))
        d = DisplayDispatcher(svc)
        result_img = Image.new("RGB", (10, 10))

        with patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img

            result = d.load_mask(str(mask_dir))

        assert result["success"] is True
        assert "other.png" in result["message"]

    def test_load_mask_empty_directory(self, tmp_path):
        empty_dir = tmp_path / "empty"
        empty_dir.mkdir()

        d = _make_dispatcher()
        result = d.load_mask(str(empty_dir))

        assert result["success"] is False
        assert "No PNG files" in result["error"]

    def test_render_overlay_missing_path(self):
        d = _make_dispatcher()
        result = d.render_overlay("/nonexistent/config1.dc")
        assert result["success"] is False
        assert "Path not found" in result["error"]

    def test_render_overlay_success_no_send_no_output(self, tmp_path):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)

        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(320, 320))
        d = DisplayDispatcher(svc)
        result_img = Image.new("RGB", (320, 320))

        with patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {"key": "value"}
            mock_overlay.config = [MagicMock()] * 3
            mock_overlay.render.return_value = result_img

            result = d.render_overlay(str(dc_file))

        assert result["success"] is True
        assert result["elements"] == 3
        assert "image" in result

    def test_render_overlay_with_send(self, tmp_path):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)

        from trcc.cli._display import DisplayDispatcher
        svc, dev = _make_mock_svc(resolution=(320, 320), path="/dev/sg0")
        d = DisplayDispatcher(svc)
        result_img = Image.new("RGB", (320, 320))

        with patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            result = d.render_overlay(str(dc_file), send=True)

        assert result["success"] is True
        assert "/dev/sg0" in result["message"]
        svc.send_pil.assert_called_once_with(result_img, 320, 320)

    def test_render_overlay_with_output(self, tmp_path):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)
        output_file = str(tmp_path / "out.png")

        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(320, 320))
        d = DisplayDispatcher(svc)
        result_img = MagicMock()

        with patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            result = d.render_overlay(str(dc_file), output=output_file)

        assert result["success"] is True
        assert output_file in result["message"]
        result_img.save.assert_called_once_with(output_file)

    def test_render_overlay_dc_directory(self, tmp_path):
        """render_overlay accepts a directory and uses config1.dc inside it."""
        theme_dir = tmp_path / "theme"
        theme_dir.mkdir()
        (theme_dir / "config1.dc").write_bytes(b"\xDD" + b"\x00" * 50)

        from trcc.cli._display import DisplayDispatcher
        svc, _ = _make_mock_svc(resolution=(320, 320))
        d = DisplayDispatcher(svc)
        result_img = Image.new("RGB", (320, 320))

        with patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            result = d.render_overlay(str(theme_dir))

        assert result["success"] is True


# =========================================================================
# TestCLIHelpers
# =========================================================================

class TestCLIHelpers:
    def test_connect_or_fail_success(self, capsys):
        from trcc.cli._display import DisplayDispatcher, _connect_or_fail
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            lcd, rc = _connect_or_fail()
        assert rc == 0
        assert isinstance(lcd, DisplayDispatcher)
        assert lcd.connected

    def test_connect_or_fail_no_device(self, capsys):
        from trcc.cli._display import _connect_or_fail
        svc = MagicMock()
        svc.selected = None
        with patch(_GET_SVC, return_value=svc):
            lcd, rc = _connect_or_fail()
        assert rc == 1
        out = capsys.readouterr().out
        assert "No device found" in out

    def test_connect_or_fail_passes_device_arg(self):
        from trcc.cli._display import _connect_or_fail
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc) as mock_gs:
            _connect_or_fail("/dev/sg2")
        mock_gs.assert_called_once_with("/dev/sg2")

    def test_print_result_success(self, capsys):
        from trcc.cli._display import _print_result
        result = {"success": True, "message": "All good"}
        rc = _print_result(result)
        assert rc == 0
        out = capsys.readouterr().out
        assert "All good" in out

    def test_print_result_failure(self, capsys):
        from trcc.cli._display import _print_result
        result = {"success": False, "error": "Something broke"}
        rc = _print_result(result)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Error: Something broke" in out

    def test_print_result_with_warning(self, capsys):
        from trcc.cli._display import _print_result
        result = {"success": True, "message": "Done", "warning": "Watch out"}
        _print_result(result)
        out = capsys.readouterr().out
        assert "Warning: Watch out" in out
        assert "Done" in out

    def test_print_result_with_preview(self, capsys):
        from trcc.cli._display import _print_result
        fake_img = MagicMock()
        result = {"success": True, "message": "OK", "image": fake_img}
        with patch(f"{_IMG_SVC}.to_ansi", return_value="ANSI_ART"):
            _print_result(result, preview=True)
        out = capsys.readouterr().out
        assert "ANSI_ART" in out

    def test_print_result_no_preview_when_no_image(self, capsys):
        from trcc.cli._display import _print_result
        result = {"success": True, "message": "OK"}
        with patch(f"{_IMG_SVC}.to_ansi") as mock_ansi:
            _print_result(result, preview=True)
        mock_ansi.assert_not_called()

    def test_display_command_delegates(self):
        from trcc.cli._display import _display_command
        mock_lcd = MagicMock()
        mock_lcd.some_method.return_value = {"success": True, "message": "OK"}
        with patch("trcc.cli._display._connect_or_fail",
                   return_value=(mock_lcd, 0)), \
             patch("trcc.cli._display._print_result", return_value=0):
            rc = _display_command("some_method", "arg1", device=None)
        mock_lcd.some_method.assert_called_once_with("arg1")
        assert rc == 0

    def test_display_command_returns_1_on_connect_failure(self):
        from trcc.cli._display import _display_command
        mock_lcd = MagicMock()
        with patch("trcc.cli._display._connect_or_fail",
                   return_value=(mock_lcd, 1)):
            rc = _display_command("any_method", device=None)
        assert rc == 1


# =========================================================================
# TestCLIImageCommands
# =========================================================================

class TestCLIImageCommands:
    def test_send_image_cli_success(self, tmp_path):
        img_path = str(_make_png(tmp_path / "pic.png", w=10, h=10))
        svc, _ = _make_mock_svc(resolution=(10, 10))
        mock_img = Image.new("RGB", (10, 10))

        from trcc.cli._display import send_image
        with patch(_GET_SVC, return_value=svc), \
             patch(f"{_IMG_SVC}.resize", return_value=mock_img):
            rc = send_image(img_path)
        assert rc == 0

    def test_send_image_cli_missing_file(self, capsys):
        from trcc.cli._display import send_image
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            rc = send_image("/nonexistent/file.png")
        assert rc == 1
        out = capsys.readouterr().out
        assert "Error" in out

    def test_send_color_cli_valid_hex(self):
        from trcc.cli._display import send_color
        svc, _ = _make_mock_svc()
        mock_img = Image.new("RGB", (320, 320))
        with patch(_GET_SVC, return_value=svc), \
             patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            rc = send_color("ff0000")
        assert rc == 0

    def test_send_color_cli_with_hash_prefix(self):
        from trcc.cli._display import send_color
        svc, _ = _make_mock_svc()
        mock_img = Image.new("RGB", (320, 320))
        with patch(_GET_SVC, return_value=svc), \
             patch(f"{_IMG_SVC}.solid_color", return_value=mock_img):
            rc = send_color("#00ff00")
        assert rc == 0

    def test_send_color_cli_invalid_hex_too_short(self, capsys):
        from trcc.cli._display import send_color
        rc = send_color("fff")
        assert rc == 1
        out = capsys.readouterr().out
        assert "Invalid hex color" in out

    def test_send_color_cli_invalid_hex_too_long(self, capsys):
        from trcc.cli._display import send_color
        rc = send_color("ff000000")
        assert rc == 1

    def test_send_color_cli_invalid_hex_non_hex_chars(self, capsys):
        from trcc.cli._display import send_color
        rc = send_color("zzzzzz")
        assert rc == 1


# =========================================================================
# TestCLISettingCommands
# =========================================================================

class TestCLISettingCommands:
    def test_set_brightness_cli_valid_1(self):
        from trcc.cli._display import set_brightness
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_brightness(1)
        assert rc == 0

    def test_set_brightness_cli_valid_2(self):
        from trcc.cli._display import set_brightness
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_brightness(2)
        assert rc == 0

    def test_set_brightness_cli_valid_3(self):
        from trcc.cli._display import set_brightness
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_brightness(3)
        assert rc == 0

    def test_set_brightness_cli_invalid_prints_help(self, capsys):
        from trcc.cli._display import set_brightness
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            rc = set_brightness(0)
        assert rc == 1
        out = capsys.readouterr().out
        assert "25%" in out
        assert "50%" in out
        assert "100%" in out

    def test_set_brightness_cli_no_device(self, capsys):
        from trcc.cli._display import set_brightness
        svc = MagicMock()
        svc.selected = None
        with patch(_GET_SVC, return_value=svc):
            rc = set_brightness(2)
        assert rc == 1

    def test_set_rotation_cli_valid_0(self):
        from trcc.cli._display import set_rotation
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(0)
        assert rc == 0

    def test_set_rotation_cli_valid_90(self):
        from trcc.cli._display import set_rotation
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(90)
        assert rc == 0

    def test_set_rotation_cli_valid_180(self):
        from trcc.cli._display import set_rotation
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(180)
        assert rc == 0

    def test_set_rotation_cli_valid_270(self):
        from trcc.cli._display import set_rotation
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_rotation(270)
        assert rc == 0

    def test_set_rotation_cli_invalid_45(self, capsys):
        from trcc.cli._display import set_rotation
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            rc = set_rotation(45)
        assert rc == 1
        out = capsys.readouterr().out
        assert "Error" in out

    def test_set_split_mode_cli_valid(self):
        from trcc.cli._display import set_split_mode
        svc, _ = _make_mock_svc(resolution=(1600, 720))
        with patch(_GET_SVC, return_value=svc), \
             patch(_SETTINGS_KEY, return_value="0:0402_3922"), \
             patch(_SETTINGS_SAVE):
            rc = set_split_mode(0)
        assert rc == 0

    def test_set_split_mode_cli_invalid(self, capsys):
        from trcc.cli._display import set_split_mode
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            rc = set_split_mode(5)
        assert rc == 1


# =========================================================================
# TestCLIOverlayCommands
# =========================================================================

class TestCLIOverlayCommands:
    def test_load_mask_cli_success(self, tmp_path):
        mask_file = tmp_path / "mask.png"
        Image.new("RGBA", (10, 10), (255, 255, 255, 128)).save(str(mask_file))

        from trcc.cli._display import load_mask
        svc, _ = _make_mock_svc(resolution=(10, 10))
        result_img = Image.new("RGB", (10, 10))

        with patch(_GET_SVC, return_value=svc), \
             patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.render.return_value = result_img
            rc = load_mask(str(mask_file))

        assert rc == 0

    def test_load_mask_cli_missing_path(self, capsys):
        from trcc.cli._display import load_mask
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            rc = load_mask("/nonexistent/mask.png")
        assert rc == 1

    def test_render_overlay_cli_success_no_flags(self, tmp_path, capsys):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)

        from trcc.cli._display import render_overlay
        svc, _ = _make_mock_svc(resolution=(320, 320))
        result_img = Image.new("RGB", (320, 320))

        with patch(_GET_SVC, return_value=svc), \
             patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {"orientation": "landscape"}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            rc = render_overlay(str(dc_file))

        assert rc == 0
        out = capsys.readouterr().out
        # display_opts printed when no --output, --send, or --preview
        assert "orientation" in out

    def test_render_overlay_cli_missing_path(self, capsys):
        from trcc.cli._display import render_overlay
        svc, _ = _make_mock_svc()
        with patch(_GET_SVC, return_value=svc):
            rc = render_overlay("/nonexistent/config1.dc")
        assert rc == 1
        out = capsys.readouterr().out
        assert "Error" in out

    def test_render_overlay_cli_with_preview(self, tmp_path, capsys):
        dc_file = tmp_path / "config1.dc"
        dc_file.write_bytes(b"\xDD" + b"\x00" * 50)

        from trcc.cli._display import render_overlay
        svc, _ = _make_mock_svc(resolution=(320, 320))
        result_img = Image.new("RGB", (320, 320))

        with patch(_GET_SVC, return_value=svc), \
             patch(_OVL_SVC) as mock_overlay_cls, \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img), \
             patch(f"{_IMG_SVC}.to_ansi", return_value="ANSI_PREVIEW"), \
             patch(_METRICS, return_value={}):
            mock_overlay = MagicMock()
            mock_overlay_cls.return_value = mock_overlay
            mock_overlay.load_from_dc.return_value = {}
            mock_overlay.config = []
            mock_overlay.render.return_value = result_img

            rc = render_overlay(str(dc_file), preview=True)

        assert rc == 0
        out = capsys.readouterr().out
        assert "ANSI_PREVIEW" in out


# =========================================================================
# TestCLIReset
# =========================================================================

class TestCLIReset:
    def test_reset_cli_success(self, capsys):
        from trcc.cli._display import reset
        svc, _ = _make_mock_svc(path="/dev/sg0")
        result_img = Image.new("RGB", (320, 320), (255, 0, 0))

        with patch(_GET_SVC, return_value=svc), \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img):
            rc = reset()

        assert rc == 0
        out = capsys.readouterr().out
        assert "/dev/sg0" in out

    def test_reset_cli_no_device(self, capsys):
        from trcc.cli._display import reset
        svc = MagicMock()
        svc.selected = None
        with patch(_GET_SVC, return_value=svc):
            rc = reset()
        assert rc == 1

    def test_reset_cli_prints_device_before_result(self, capsys):
        from trcc.cli._display import reset
        svc, _ = _make_mock_svc(path="/dev/sg1")
        result_img = Image.new("RGB", (320, 320), (255, 0, 0))

        with patch(_GET_SVC, return_value=svc), \
             patch(f"{_IMG_SVC}.solid_color", return_value=result_img):
            reset()

        out = capsys.readouterr().out
        assert "Device:" in out
        assert "/dev/sg1" in out


# =========================================================================
# TestCLIVideoStatus
# =========================================================================

class TestCLIDisplayStatus:
    def test_display_status_connected(self, capsys):
        from trcc.cli._display import display_status
        mock_lcd = MagicMock()
        mock_lcd.status.return_value = {
            "success": True, "connected": True,
            "device_path": "/dev/sg0", "protocol": "scsi",
            "resolution": [320, 320], "rotation": 0,
            "brightness": 50, "split_mode": 0,
            "overlay_enabled": False, "video_playing": False,
        }
        with patch("trcc.cli._display._connect_or_fail",
                   return_value=(mock_lcd, 0)):
            rc = display_status()
        assert rc == 0
        out = capsys.readouterr().out
        assert "Device:" in out
        assert "/dev/sg0" in out
        assert "320x320" in out

    def test_display_status_no_device(self, capsys):
        from trcc.cli._display import display_status
        mock_lcd = MagicMock()
        with patch("trcc.cli._display._connect_or_fail",
                   return_value=(mock_lcd, 1)):
            rc = display_status()
        assert rc == 1


class TestCLIDaemonControl:
    """Tests for video-play, video-pause, video-stop, overlay-toggle CLI commands."""

    def _mock_lcd(self, method: str, return_value: dict):
        mock = MagicMock()
        getattr(mock, method).return_value = return_value
        return mock

    def test_video_play(self, capsys):
        from trcc.cli._display import video_play
        mock_lcd = self._mock_lcd("play_video", {"success": True, "message": "Video playing"})
        with patch("trcc.cli._display._connect_or_fail", return_value=(mock_lcd, 0)):
            rc = video_play()
        assert rc == 0
        assert "Video playing" in capsys.readouterr().out

    def test_video_pause(self, capsys):
        from trcc.cli._display import video_pause
        mock_lcd = self._mock_lcd("pause_video", {"success": True, "message": "Video paused"})
        with patch("trcc.cli._display._connect_or_fail", return_value=(mock_lcd, 0)):
            rc = video_pause()
        assert rc == 0
        assert "Video paused" in capsys.readouterr().out

    def test_video_stop(self, capsys):
        from trcc.cli._display import video_stop
        mock_lcd = self._mock_lcd("stop_video", {"success": True, "message": "Video stopped"})
        with patch("trcc.cli._display._connect_or_fail", return_value=(mock_lcd, 0)):
            rc = video_stop()
        assert rc == 0
        assert "Video stopped" in capsys.readouterr().out

    def test_overlay_toggle_on(self, capsys):
        from trcc.cli._display import overlay_toggle
        mock_lcd = self._mock_lcd("enable_overlay", {"success": True, "message": "Overlay enabled"})
        with patch("trcc.cli._display._connect_or_fail", return_value=(mock_lcd, 0)):
            rc = overlay_toggle(True)
        assert rc == 0
        assert "Overlay enabled" in capsys.readouterr().out

    def test_overlay_toggle_off(self, capsys):
        from trcc.cli._display import overlay_toggle
        mock_lcd = self._mock_lcd("enable_overlay", {"success": True, "message": "Overlay disabled"})
        with patch("trcc.cli._display._connect_or_fail", return_value=(mock_lcd, 0)):
            rc = overlay_toggle(False)
        assert rc == 0
        assert "Overlay disabled" in capsys.readouterr().out

    def test_daemon_command_connect_fail(self, capsys):
        from trcc.cli._display import video_play
        mock_lcd = MagicMock()
        with patch("trcc.cli._display._connect_or_fail", return_value=(mock_lcd, 1)):
            rc = video_play()
        assert rc == 1


# =========================================================================
# TestCLIResume
# =========================================================================

_DEV_SVC_CLS  = "trcc.services.DeviceService"
_DISC_RES     = "trcc.cli._device.discover_resolution"
_SETTINGS_CLS = "trcc.conf.Settings"
_IMG_SVC_CLS  = "trcc.services.ImageService"
_PIL_IMAGE    = "trcc.cli._display.Image"
_TIME         = "time.sleep"


class TestCLIResume:
    def _make_scsi_dev(self, product="LCD", resolution=(320, 320)):
        dev = MagicMock()
        dev.protocol = "scsi"
        dev.product = product
        dev.resolution = resolution
        dev.vid = 0x0402
        dev.pid = 0x3922
        dev.device_index = 0
        return dev

    def test_resume_no_devices(self, capsys):
        from trcc.cli._display import resume

        mock_svc = MagicMock()
        mock_svc.detect.return_value = []

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_TIME):
            rc = resume()

        assert rc == 1
        out = capsys.readouterr().out
        assert "No compatible" in out

    def test_resume_device_not_scsi_skipped(self, capsys):
        from trcc.cli._display import resume

        dev = MagicMock()
        dev.protocol = "hid"

        mock_svc = MagicMock()
        mock_svc.detect.return_value = [dev]

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_TIME):
            rc = resume()

        # No SCSI devices → nothing sent → returns 1
        assert rc == 1
        out = capsys.readouterr().out
        assert "No themes were sent" in out

    def test_resume_no_resolution_skipped(self, capsys):
        from trcc.cli._display import resume

        dev = self._make_scsi_dev(resolution=(0, 0))
        mock_svc = MagicMock()
        mock_svc.detect.return_value = [dev]

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_DISC_RES), \
             patch(_SETTINGS_CLS) as mock_settings, \
             patch(_TIME):
            mock_settings.device_config_key.return_value = "0:0402_3922"
            mock_settings.get_device_config.return_value = {}
            rc = resume()

        assert rc == 1

    def test_resume_no_theme_path_skipped(self, capsys):
        from trcc.cli._display import resume

        dev = self._make_scsi_dev(resolution=(320, 320))
        mock_svc = MagicMock()
        mock_svc.detect.return_value = [dev]

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_DISC_RES), \
             patch(_SETTINGS_CLS) as mock_settings, \
             patch(_TIME):
            mock_settings.device_config_key.return_value = "0:0402_3922"
            mock_settings.get_device_config.return_value = {}  # no theme_path
            rc = resume()

        assert rc == 1
        out = capsys.readouterr().out
        assert "No saved theme" in out

    def test_resume_theme_path_not_found(self, tmp_path, capsys):
        from trcc.cli._display import resume

        dev = self._make_scsi_dev(resolution=(320, 320))
        mock_svc = MagicMock()
        mock_svc.detect.return_value = [dev]

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_DISC_RES), \
             patch(_SETTINGS_CLS) as mock_settings, \
             patch(_TIME):
            mock_settings.device_config_key.return_value = "0:0402_3922"
            mock_settings.get_device_config.return_value = {
                "theme_path": "/nonexistent/theme"
            }
            rc = resume()

        assert rc == 1
        out = capsys.readouterr().out
        assert "Theme not found" in out

    def test_resume_success_with_image_file(self, tmp_path, capsys):
        from trcc.cli._display import resume

        img_file = tmp_path / "theme.png"
        Image.new("RGB", (320, 320), (100, 100, 100)).save(str(img_file))

        dev = self._make_scsi_dev(resolution=(320, 320))
        mock_svc = MagicMock()
        mock_svc.detect.return_value = [dev]

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_DISC_RES), \
             patch(_SETTINGS_CLS) as mock_settings, \
             patch(f"{_IMG_SVC_CLS}.resize") as mock_resize, \
             patch(f"{_IMG_SVC_CLS}.apply_brightness") as mock_brightness, \
             patch(f"{_IMG_SVC_CLS}.apply_rotation") as mock_rotation, \
             patch(_TIME):
            mock_settings.device_config_key.return_value = "0:0402_3922"
            mock_settings.get_device_config.return_value = {
                "theme_path": str(img_file),
                "brightness_level": 3,
                "rotation": 0,
            }
            fake_img = MagicMock()
            mock_resize.return_value = fake_img
            mock_brightness.return_value = fake_img
            mock_rotation.return_value = fake_img

            rc = resume()

        assert rc == 0
        out = capsys.readouterr().out
        assert "Resumed 1 device" in out
        mock_svc.send_pil.assert_called_once()

    def test_resume_success_with_theme_directory(self, tmp_path, capsys):
        from trcc.cli._display import resume

        theme_dir = tmp_path / "MyTheme"
        theme_dir.mkdir()
        Image.new("RGB", (320, 320), (50, 50, 50)).save(str(theme_dir / "00.png"))

        dev = self._make_scsi_dev(resolution=(320, 320))
        mock_svc = MagicMock()
        mock_svc.detect.return_value = [dev]

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_DISC_RES), \
             patch(_SETTINGS_CLS) as mock_settings, \
             patch(f"{_IMG_SVC_CLS}.resize") as mock_resize, \
             patch(f"{_IMG_SVC_CLS}.apply_brightness") as mock_brightness, \
             patch(f"{_IMG_SVC_CLS}.apply_rotation") as mock_rotation, \
             patch(_TIME):
            mock_settings.device_config_key.return_value = "0:0402_3922"
            mock_settings.get_device_config.return_value = {
                "theme_path": str(theme_dir),
                "brightness_level": 2,
                "rotation": 90,
            }
            fake_img = MagicMock()
            mock_resize.return_value = fake_img
            mock_brightness.return_value = fake_img
            mock_rotation.return_value = fake_img

            rc = resume()

        assert rc == 0
        out = capsys.readouterr().out
        assert "Resumed 1 device" in out

    def test_resume_device_exception_continues(self, tmp_path, capsys):
        from trcc.cli._display import resume

        img_file = tmp_path / "theme.png"
        Image.new("RGB", (320, 320), (100, 100, 100)).save(str(img_file))

        dev = self._make_scsi_dev(resolution=(320, 320))
        mock_svc = MagicMock()
        mock_svc.detect.return_value = [dev]
        mock_svc.send_pil.side_effect = OSError("USB error")

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_DISC_RES), \
             patch(_SETTINGS_CLS) as mock_settings, \
             patch(f"{_IMG_SVC_CLS}.resize") as mock_resize, \
             patch(f"{_IMG_SVC_CLS}.apply_brightness") as mock_brightness, \
             patch(f"{_IMG_SVC_CLS}.apply_rotation") as mock_rotation, \
             patch(_TIME):
            mock_settings.device_config_key.return_value = "0:0402_3922"
            mock_settings.get_device_config.return_value = {
                "theme_path": str(img_file),
            }
            fake_img = MagicMock()
            mock_resize.return_value = fake_img
            mock_brightness.return_value = fake_img
            mock_rotation.return_value = fake_img

            rc = resume()

        # Error in send → sent=0 → returns 1
        assert rc == 1
        out = capsys.readouterr().out
        assert "Error" in out

    def test_resume_waits_for_device_to_appear(self, capsys):
        from trcc.cli._display import resume

        dev = self._make_scsi_dev(resolution=(320, 320))
        call_count = 0

        def _detect():
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return []
            return [dev]

        mock_svc = MagicMock()
        mock_svc.detect.side_effect = _detect

        with patch(_DEV_SVC_CLS, return_value=mock_svc), \
             patch(_DISC_RES), \
             patch(_SETTINGS_CLS) as mock_settings, \
             patch(_TIME):
            mock_settings.device_config_key.return_value = "0:0402_3922"
            mock_settings.get_device_config.return_value = {}  # no theme → skip

            rc = resume()

        out = capsys.readouterr().out
        assert "Waiting for device" in out
        # After device found, fails because no theme
        assert rc == 1
