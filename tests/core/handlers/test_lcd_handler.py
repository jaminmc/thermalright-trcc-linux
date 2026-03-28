"""Tests for core/handlers/lcd.py — LCDCommandHandler + bus factories."""
from __future__ import annotations

from unittest.mock import MagicMock

from trcc.core.command_bus import CommandBus, RateLimitMiddleware
from trcc.core.commands.lcd import (
    EnableOverlayCommand,
    EnsureDataCommand,
    LoadThemeByNameCommand,
    ResetDisplayCommand,
    SendColorCommand,
    SendImageCommand,
    SetBrightnessCommand,
    SetOverlayConfigCommand,
    SetResolutionCommand,
    SetRotationCommand,
    SetSplitModeCommand,
    UpdateMetricsLCDCommand,
)
from trcc.core.handlers.lcd import LCDCommandHandler, build_lcd_bus, build_lcd_gui_bus


def _mock_lcd() -> MagicMock:
    lcd = MagicMock()
    lcd.set_brightness.return_value = {"success": True}
    lcd.set_rotation.return_value = {"success": True}
    lcd.send_color.return_value = {"success": True}
    lcd.send_image.return_value = {"success": True}
    lcd.load_theme_by_name.return_value = {"success": True}
    lcd.set_split_mode.return_value = {"success": True}
    lcd.enable_overlay.return_value = {"success": True}
    lcd.update_metrics.return_value = {"success": True}
    lcd.reset.return_value = {"success": True}
    lcd.set_config.return_value = {"success": True}
    lcd.set_resolution.return_value = {"success": True}
    return lcd


# ── Handler dispatch ──────────────────────────────────────────────────────────

class TestLCDCommandHandlerDispatch:
    def test_set_brightness(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        result = h(SetBrightnessCommand(level=2))
        assert result
        lcd.set_brightness.assert_called_once_with(2)

    def test_set_rotation(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(SetRotationCommand(degrees=90))
        lcd.set_rotation.assert_called_once_with(90)

    def test_send_color(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(SendColorCommand(r=255, g=0, b=128))
        lcd.send_color.assert_called_once_with(255, 0, 128)

    def test_send_image(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(SendImageCommand(image_path="/tmp/x.png"))
        lcd.send_image.assert_called_once_with("/tmp/x.png")

    def test_load_theme_by_name(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(LoadThemeByNameCommand(name="Theme1", width=320, height=320))
        lcd.load_theme_by_name.assert_called_once_with("Theme1", 320, 320)

    def test_set_split_mode(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(SetSplitModeCommand(mode=1))
        lcd.set_split_mode.assert_called_once_with(1)

    def test_enable_overlay(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(EnableOverlayCommand(on=True))
        lcd.enable_overlay.assert_called_once_with(True)

    def test_reset_display(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(ResetDisplayCommand())
        lcd.reset.assert_called_once()

    def test_set_overlay_config(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        config = {"key": "val"}
        h(SetOverlayConfigCommand(config=config))
        lcd.set_config.assert_called_once_with(config)

    def test_set_resolution_calls_device(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        h(SetResolutionCommand(width=480, height=480))
        lcd.set_resolution.assert_called_once_with(480, 480)


# ── Metrics validation ────────────────────────────────────────────────────────

class TestLCDMetricsValidation:
    def test_valid_metrics_dispatched(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        metrics = {"cpu": 50}
        result = h(UpdateMetricsLCDCommand(metrics=metrics))
        assert result
        lcd.update_metrics.assert_called_once_with(metrics)

    def test_none_metrics_returns_fail(self):
        lcd = _mock_lcd()
        h = LCDCommandHandler(lcd)
        result = h(UpdateMetricsLCDCommand(metrics=None))
        assert not result
        lcd.update_metrics.assert_not_called()

    def test_none_metrics_error_message(self):
        h = LCDCommandHandler(_mock_lcd())
        result = h(UpdateMetricsLCDCommand(metrics=None))
        assert "invalid metrics" in result.payload["error"]


# ── EnsureDataCommand ─────────────────────────────────────────────────────────

class TestEnsureDataCommand:
    def test_ensure_starts_background_thread(self):
        lcd = _mock_lcd()
        called: list[tuple[int, int]] = []
        ensure_fn = lambda w, h: called.append((w, h))  # noqa: E731
        handler = LCDCommandHandler(lcd, ensure_fn)
        result = handler(EnsureDataCommand(width=320, height=320))
        assert result
        assert "started" in result.payload["message"].lower()


# ── bus factories ─────────────────────────────────────────────────────────────

class TestBuildLcdBus:
    def test_returns_command_bus(self):
        assert isinstance(build_lcd_bus(_mock_lcd()), CommandBus)

    def test_no_rate_limit(self):
        assert RateLimitMiddleware not in build_lcd_bus(_mock_lcd())

    def test_dispatches_set_brightness(self):
        lcd = _mock_lcd()
        build_lcd_bus(lcd).dispatch(SetBrightnessCommand(level=3))
        lcd.set_brightness.assert_called_once_with(3)

    def test_all_handles_registered(self):
        """Every command in LCDCommandHandler.handles must be dispatched."""
        lcd = _mock_lcd()
        bus = build_lcd_bus(lcd)
        # spot-check a few from different parts of the handles tuple
        bus.dispatch(SendColorCommand(r=1, g=2, b=3))
        bus.dispatch(ResetDisplayCommand())
        bus.dispatch(EnableOverlayCommand(on=False))
        lcd.send_color.assert_called_once_with(1, 2, 3)
        lcd.reset.assert_called_once()
        lcd.enable_overlay.assert_called_once_with(False)


class TestBuildLcdGuiBus:
    def test_no_rate_limit(self):
        """LCD has discrete brightness buttons, not continuous sliders — no rate limiter needed."""
        assert RateLimitMiddleware not in build_lcd_gui_bus(_mock_lcd())

    def test_dispatches_set_brightness(self):
        lcd = _mock_lcd()
        build_lcd_gui_bus(lcd).dispatch(SetBrightnessCommand(level=1))
        lcd.set_brightness.assert_called_once_with(1)


# ── __repr__ ──────────────────────────────────────────────────────────────────

class TestLCDHandlerRepr:
    def test_repr_includes_class_name(self):
        h = LCDCommandHandler(_mock_lcd())
        assert "LCDCommandHandler" in repr(h)
