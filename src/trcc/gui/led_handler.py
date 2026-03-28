"""LEDHandler — one per LED device.

Self-contained handler for a single LED device. Owns an LEDDevice,
manages animation timer, signal wiring, and GUI state sync.
TRCCApp creates one LEDHandler per connected LED device.
"""
from __future__ import annotations

import logging
from typing import Any

from PySide6.QtCore import QTimer

import trcc.conf as _conf

from ..core.command_bus import CommandBus
from ..core.commands.led import (
    SetLEDBrightnessCommand,
    SetLEDColorCommand,
    SetLEDModeCommand,
)
from ..core.led_device import LEDDevice
from ..core.models import DeviceInfo
from .base import BaseHandler
from .uc_led_control import UCLedControl

log = logging.getLogger(__name__)


class LEDHandler(BaseHandler):
    """Handler for a single LED device.

    Owns LEDDevice lifecycle, animation timer, signal wiring.
    GUI signal handlers update state only — the 150 ms tick handles
    animation + send.
    """

    _SAVE_INTERVAL = 20  # save config every N ticks (~3 s)

    def __init__(
        self,
        led: LEDDevice,
        panel: UCLedControl,
        on_temp_unit_changed: Any,
        bus: CommandBus | None = None,
    ) -> None:
        if bus is None:
            raise ValueError("LEDHandler requires a CommandBus — inject via build_led_gui_bus()")
        self._panel = panel
        self._on_temp_unit_changed = on_temp_unit_changed
        self._led = led
        self._bus: CommandBus = bus
        self._active = False
        self._style_id = 0
        self._save_counter = 0

        self._timer = QTimer(panel)
        self._timer.timeout.connect(self._on_tick)
        self._connect_signals()

    # ── BaseHandler interface ────────────────────────────────────────

    @property
    def view_name(self) -> str:
        return 'led'

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._led.device_info if self._led else None

    def cleanup(self) -> None:
        log.info("LED: cleanup")
        self._timer.stop()
        if self._led:
            self._led.save_config()
            self._led.cleanup()

    def stop_timers(self) -> None:
        self._timer.stop()

    # ── Public API ───────────────────────────────────────────────────

    @property
    def active(self) -> bool:
        return self._active

    @property
    def has_controller(self) -> bool:
        return self._led is not None

    @property
    def led_port(self) -> LEDDevice | None:
        return self._led

    def show(self, device: DeviceInfo) -> None:
        """Initialize LED device and start animation."""
        model = device.model or ''
        from ..services.led import LEDService
        led_style = device.led_style_id or LEDService.resolve_style_id(model)

        self._led.initialize(device, led_style)
        self._style_id = led_style

        style_info = LEDService.get_style_info(led_style)
        if style_info:
            self._panel.initialize(
                led_style, style_info.segment_count, style_info.zone_count,
                model=model,
            )
        self._panel.set_memory_ratio(self._led.state.memory_ratio)
        self._sync_ui_from_state()

        seg_unit = "F" if _conf.settings.temp_unit == 1 else "C"
        self._led.set_seg_temp_unit(seg_unit)

        self._active = True
        self._timer.start(150)
        log.info("LED: show model=%s style=%d, tick timer started (150ms)", model, led_style)

    def stop(self) -> None:
        log.info("LED: stop (active=%s)", self._active)
        self._timer.stop()
        self._active = False
        if self._led:
            self._led.save_config()
            self._led.cleanup()

    def set_temp_unit(self, unit: str) -> None:
        if self._led:
            log.debug("LED: temp_unit=%s", unit)
            self._led.set_seg_temp_unit(unit)

    def restart_if_needed(self) -> None:
        """Restart animation timer if active but stopped (e.g. after window hide)."""
        if self._active and not self._timer.isActive():
            log.warning("LED tick timer was stopped — restarting")
            self._timer.start(150)

    def update_from_metrics(self, metrics: Any) -> None:
        if not self._led:
            return
        self._led.update_metrics(metrics)
        self._panel.update_metrics(metrics)

    # ── Private ──────────────────────────────────────────────────────

    def _sync_ui_from_state(self) -> None:
        if not self._led:
            return
        state = self._led.state
        if state.zones:
            z = state.zones[0]
            self._panel.load_zone_state(0, z.mode.value, z.color, z.brightness, z.on)
        else:
            self._panel.load_zone_state(
                0, state.mode.value, state.color, state.brightness, state.global_on)
        log.debug("LED: synced UI from state (zones=%d)", len(state.zones))

    def _connect_signals(self) -> None:
        if not self._led:
            return
        p = self._panel
        p.mode_changed.connect(self._on_mode_changed)
        p.color_changed.connect(self._on_color_changed)
        p.brightness_changed.connect(self._on_brightness_changed)
        p.global_toggled.connect(self._on_global_toggled)
        p.segment_clicked.connect(self._on_segment_clicked)
        p.zone_selected.connect(self._on_zone_selected)
        p.zone_toggled.connect(self._on_zone_toggled)
        p.carousel_changed.connect(self._on_carousel_changed)
        p.carousel_zone_changed.connect(self._on_carousel_zone_changed)
        p.carousel_interval_changed.connect(self._on_carousel_interval_changed)
        p.clock_format_changed.connect(self._on_clock_format_changed)
        p.week_start_changed.connect(self._on_week_start_changed)
        p.temp_unit_changed.connect(self._on_temp_unit_changed)
        p.disk_index_changed.connect(self._on_disk_index_changed)
        p.memory_ratio_changed.connect(self._on_memory_ratio_changed)
        p.test_mode_changed.connect(self._on_test_mode_changed)

    def _on_mode_changed(self, mode: Any) -> None:
        if not self._led:
            return
        self._bus.dispatch(SetLEDModeCommand(mode=mode))
        if self._led.state.zones:
            self._led.update_zone_mode(self._panel.selected_zone, mode)
        self._save_counter = self._SAVE_INTERVAL

    def _on_color_changed(self, r: int, g: int, b: int) -> None:
        if not self._led:
            return
        self._bus.dispatch(SetLEDColorCommand(r=r, g=g, b=b))
        if self._led.state.zones:
            self._led.update_zone_color(self._panel.selected_zone, r, g, b)

    def _on_brightness_changed(self, val: int) -> None:
        if not self._led:
            return
        self._bus.dispatch(SetLEDBrightnessCommand(level=val))
        if self._led.state.zones:
            self._led.update_zone_brightness(self._panel.selected_zone, val)

    def _on_global_toggled(self, on: bool) -> None:
        if self._led:
            self._led.update_global_on(on)

    def _on_segment_clicked(self, idx: int) -> None:
        if self._led and 0 <= idx < len(self._led.state.segment_on):
            self._led.update_segment(idx, not self._led.state.segment_on[idx])

    def _on_zone_selected(self, zone_index: int) -> None:
        if not self._led or not self._led.state.zones:
            return
        self._led.update_selected_zone(zone_index)
        zones = self._led.state.zones
        if 0 <= zone_index < len(zones):
            z = zones[zone_index]
            self._panel.load_zone_state(zone_index, z.mode.value, z.color, z.brightness, z.on)

    def _on_zone_toggled(self, zi: int, on: bool) -> None:
        if self._led:
            self._led.update_zone_on(zi, on)

    def _on_carousel_changed(self, on: bool) -> None:
        if self._led:
            self._led.update_zone_sync(on)

    def _on_carousel_zone_changed(self, zi: int, sel: Any) -> None:
        if self._led:
            self._led.update_zone_sync_zone(zi, sel)

    def _on_carousel_interval_changed(self, secs: int) -> None:
        if self._led:
            self._led.update_zone_sync_interval(secs)

    def _on_clock_format_changed(self, is_24h: bool) -> None:
        if self._led:
            self._led.update_clock_format(is_24h)

    def _on_week_start_changed(self, is_sun: bool) -> None:
        if self._led:
            self._led.update_week_start(is_sun)

    def _on_disk_index_changed(self, idx: int) -> None:
        if self._led:
            self._led.update_disk_index(idx)

    def _on_memory_ratio_changed(self, ratio: int) -> None:
        if self._led:
            self._led.update_memory_ratio(ratio)

    def _on_test_mode_changed(self, on: bool) -> None:
        if self._led:
            self._led.update_test_mode(on)

    def _on_tick(self) -> None:
        if not (self._led and self._active):
            return
        try:
            result = self._led.tick_with_result()
            display_colors = result.get('display_colors')
            if display_colors is not None:
                self._panel.set_led_colors(display_colors)
            self._save_counter += 1
            if self._save_counter >= self._SAVE_INTERVAL:
                self._save_counter = 0
                self._led.save_config()
        except Exception:
            log.exception("LED tick error")
