"""LEDHandler — one per LED device.

Self-contained handler for a single LED device. Owns an LEDDevice,
signal wiring, and GUI state sync. TRCCApp creates one LEDHandler
per connected LED device.

Only the active handler updates the shared panel — `_active` bool
gates all signal handlers via `_guard()`. Panel updates are driven
by the metrics signal (same refresh rate as LCD overlay), not a
separate timer.

Hardware sends happen in the background metrics loop via device.tick().
"""
from __future__ import annotations

import logging
from typing import Any

import trcc.conf as _conf

from ..core.led_device import LEDDevice
from ..core.models import LED_STYLES, DeviceInfo, resolve_led_style_id
from .base import BaseHandler
from .uc_led_control import UCLedControl

log = logging.getLogger(__name__)


class LEDHandler(BaseHandler):
    """Handler for a single LED device.

    Owns LEDDevice lifecycle, animation timer, signal wiring.
    GUI signal handlers call update_* methods directly on the device
    (state-only). The 150ms tick handles animation + hardware send.
    """

    _SAVE_INTERVAL = 20  # save config every N ticks (~3 s)

    def __init__(
        self,
        led: LEDDevice,
        panel: UCLedControl,
        on_temp_unit_changed: Any,
        make_timer: Any = None,
    ) -> None:
        self._panel = panel
        self._on_temp_unit_changed = on_temp_unit_changed
        self._led = led
        self._active = False
        self._style_id = 0
        self._metrics_count = 0
        self._connect_signals()

    # ── BaseHandler interface ────────────────────────────────────────

    @property
    def view_name(self) -> str:
        return 'led'

    @property
    def device_info(self) -> DeviceInfo | None:
        return self._led.device_info if self._led else None

    def stop_timers(self) -> None:
        pass  # No timer — panel updates driven by metrics signal

    def _cleanup_device(self) -> None:
        log.info("LED: cleanup")
        if self._led:
            self._led.save_config()
            self._led.cleanup()

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
        led_style = device.led_style_id or resolve_led_style_id(model)

        self._led.initialize(device, led_style)
        self._style_id = led_style

        style_info = LED_STYLES.get(led_style)
        if not style_info:
            log.warning("LED show: unknown style %d — panel init skipped", led_style)
        if style_info:
            self._panel.initialize(
                led_style, style_info.segment_count, style_info.zone_count,
                model=model,
            )
        self._panel.set_memory_ratio(self._led.state.memory_ratio)
        self._sync_ui_from_state()

        self._led.set_seg_temp_unit(_conf.settings.temp_unit)

        self._active = True
        log.info("LED: show model=%s style=%d, active (metrics-driven)", model, led_style)

    def deactivate(self) -> None:
        """Deactivate — stop panel updates, save config. Device keeps running."""
        log.info("LED: deactivate (was active=%s)", self._active)
        self._active = False
        if self._led:
            self._led.save_config()

    def stop(self) -> None:
        """Alias for deactivate (BaseHandler interface)."""
        self.deactivate()

    def set_temp_unit(self, unit: int) -> None:
        if self._led:
            log.debug("LED: temp_unit=%d", unit)
            self._led.set_seg_temp_unit(unit)

    def restart_if_needed(self) -> None:
        """No-op — LED updates are metrics-driven, no timer to restart."""
        pass

    def update_metrics(self, metrics: Any) -> None:
        if not (self._led and self._active):
            return
        self._led.update_metrics(metrics)
        # Push display colors to panel (replaces old 150ms timer tick)
        result = self._led.tick_with_result()
        display_colors = result.get('display_colors')
        if display_colors is not None:
            self._panel.set_led_colors(display_colors)
        self._panel.update_metrics(metrics)
        # Periodic config save
        self._metrics_count += 1
        if self._metrics_count >= self._SAVE_INTERVAL:
            self._metrics_count = 0
            self._led.save_config()

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

    def _guard(self, fn):
        """Wrap a slot so it only fires when this handler is active with a device."""
        def wrapper(*args, **kwargs):
            if self._led and self._active:
                fn(*args, **kwargs)
        return wrapper

    def _connect_signals(self) -> None:
        if not self._led:
            return
        p = self._panel
        p.mode_changed.connect(self._guard(self._on_mode_changed))
        p.color_changed.connect(self._guard(self._on_color_changed))
        p.brightness_changed.connect(self._guard(self._on_brightness_changed))
        p.global_toggled.connect(self._guard(self._on_global_toggled))
        p.segment_clicked.connect(self._guard(self._on_segment_clicked))
        p.zone_selected.connect(self._guard(self._on_zone_selected))
        p.zone_toggled.connect(self._guard(self._on_zone_toggled))
        p.carousel_changed.connect(self._guard(self._on_carousel_changed))
        p.carousel_zone_changed.connect(self._guard(self._on_carousel_zone_changed))
        p.carousel_interval_changed.connect(self._guard(self._on_carousel_interval_changed))
        p.clock_format_changed.connect(self._guard(self._on_clock_format_changed))
        p.week_start_changed.connect(self._guard(self._on_week_start_changed))
        p.temp_unit_changed.connect(self._guard(self._on_temp_unit_changed))
        p.disk_index_changed.connect(self._guard(self._on_disk_index_changed))
        p.memory_ratio_changed.connect(self._guard(self._on_memory_ratio_changed))
        p.test_mode_changed.connect(self._guard(self._on_test_mode_changed))

    def _on_mode_changed(self, mode: Any) -> None:
        self._led.update_mode(mode)
        if self._led.state.zones:
            self._led.update_zone_mode(self._panel.selected_zone, mode)
        self._metrics_count = self._SAVE_INTERVAL  # force save on next update

    def _on_color_changed(self, r: int, g: int, b: int) -> None:
        self._led.update_color(r, g, b)
        if self._led.state.zones:
            self._led.update_zone_color(self._panel.selected_zone, r, g, b)

    def _on_brightness_changed(self, val: int) -> None:
        self._led.update_brightness(val)
        if self._led.state.zones:
            self._led.update_zone_brightness(self._panel.selected_zone, val)

    def _on_global_toggled(self, on: bool) -> None:
        self._led.update_global_on(on)

    def _on_segment_clicked(self, idx: int) -> None:
        if 0 <= idx < len(self._led.state.segment_on):
            self._led.update_segment(idx, not self._led.state.segment_on[idx])

    def _on_zone_selected(self, zone_index: int) -> None:
        if not self._led.state.zones:
            return
        self._led.update_selected_zone(zone_index)
        zones = self._led.state.zones
        if 0 <= zone_index < len(zones):
            z = zones[zone_index]
            self._panel.load_zone_state(zone_index, z.mode.value, z.color, z.brightness, z.on)

    def _on_zone_toggled(self, zi: int, on: bool) -> None:
        self._led.update_zone_on(zi, on)

    def _on_carousel_changed(self, on: bool) -> None:
        self._led.update_zone_sync(on)

    def _on_carousel_zone_changed(self, zi: int, sel: Any) -> None:
        self._led.update_zone_sync_zone(zi, sel)

    def _on_carousel_interval_changed(self, secs: int) -> None:
        self._led.update_zone_sync_interval(secs)

    def _on_clock_format_changed(self, is_24h: bool) -> None:
        self._led.update_clock_format(is_24h)

    def _on_week_start_changed(self, is_sun: bool) -> None:
        self._led.update_week_start(is_sun)

    def _on_disk_index_changed(self, idx: int) -> None:
        self._led.update_disk_index(idx)

    def _on_memory_ratio_changed(self, ratio: int) -> None:
        self._led.update_memory_ratio(ratio)

    def _on_test_mode_changed(self, on: bool) -> None:
        self._led.update_test_mode(on)

    def _on_tick(self) -> None:
        """Manual tick — used by tests. Normal path is update_metrics()."""
        if not (self._led and self._active):
            return
        try:
            result = self._led.tick_with_result()
            display_colors = result.get('display_colors')
            if display_colors is not None:
                self._panel.set_led_colors(display_colors)
            self._metrics_count += 1
            if self._metrics_count >= self._SAVE_INTERVAL:
                self._metrics_count = 0
                self._led.save_config()
        except Exception:
            log.exception("LED tick error")
