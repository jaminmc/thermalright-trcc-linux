"""
Tests for qt_app_mvc.py (LEDHandler, ScreencastHandler) and uc_system_info.py
(SystemInfoPanel, UCSystemInfo).

Covers:
- LEDHandler: construction, show/stop lifecycle, signal wiring, state sync, tick
- ScreencastHandler: construction, toggle, stop, params, cleanup, state machine
- uc_system_info module constants: PANEL_W, PANEL_H, grid layout, PANELS_PER_PAGE
- SystemInfoPanel: construction, update_values formatting, set_temp_unit, signals
- UCSystemInfo: construction, page navigation, add/delete panels, timer management
"""
from __future__ import annotations

import os

# Must set BEFORE any Qt imports
os.environ["QT_QPA_PLATFORM"] = "offscreen"

from unittest.mock import MagicMock, patch

import pytest
from PySide6.QtCore import QTimer
from PySide6.QtGui import QPixmap
from PySide6.QtWidgets import QWidget

from trcc.adapters.system.config import (
    CATEGORY_COLORS,
    CATEGORY_IMAGES,
    PanelConfig,
    SensorBinding,
    SysInfoConfig,
)
from trcc.core.models import LEDMode, LEDZoneState
from trcc.qt_components.uc_system_info import (
    COLUMNS,
    PAGE_NEXT_POS,
    PAGE_PREV_POS,
    PANEL_H,
    PANEL_W,
    PANELS_PER_PAGE,
    ROWS_PER_PAGE,
    SELECTOR_POSITIONS,
    SPACING_X,
    SPACING_Y,
    START_X,
    START_Y,
    VALUE_POSITIONS,
    SystemInfoPanel,
    UCSystemInfo,
)

# =========================================================================
# Helpers
# =========================================================================


def _make_panel_config(
    category_id: int = 1,
    name: str = "CPU",
    sensors: list[SensorBinding] | None = None,
) -> PanelConfig:
    """Build a PanelConfig with sensible defaults."""
    if sensors is None:
        sensors = [
            SensorBinding("TEMP", "hwmon:coretemp:temp1", "°C"),
            SensorBinding("Usage", "psutil:cpu_percent", "%"),
            SensorBinding("Clock", "psutil:cpu_freq", "MHz"),
            SensorBinding("Power", "rapl:package-0", "W"),
        ]
    return PanelConfig(category_id=category_id, name=name, sensors=sensors)


def _make_custom_panel_config(name: str = "Custom") -> PanelConfig:
    """Build a custom (category_id=0) PanelConfig."""
    return _make_panel_config(
        category_id=0,
        name=name,
        sensors=[
            SensorBinding("Sensor 1", "", ""),
            SensorBinding("Sensor 2", "", ""),
            SensorBinding("Sensor 3", "", ""),
            SensorBinding("Sensor 4", "", ""),
        ],
    )


def _make_mock_enumerator() -> MagicMock:
    """Create a mock SensorEnumerator that returns empty results."""
    enum = MagicMock()
    enum.discover.return_value = []
    enum.read_all.return_value = {}
    return enum


def _make_mock_led_state(
    *,
    zones: list[LEDZoneState] | None = None,
    mode: LEDMode = LEDMode.STATIC,
    color: tuple[int, int, int] = (255, 0, 0),
    brightness: int = 65,
    global_on: bool = True,
    memory_ratio: int = 1,
) -> MagicMock:
    """Create a mock LED state object."""
    state = MagicMock()
    state.zones = zones or []
    state.mode = mode
    state.color = color
    state.brightness = brightness
    state.global_on = global_on
    state.memory_ratio = memory_ratio
    state.segment_on = [True] * 10
    return state


# =========================================================================
# Module constants (uc_system_info)
# =========================================================================


class TestSystemInfoModuleConstants:
    """Verify module-level grid layout constants from Windows C#."""

    def test_panel_dimensions(self, qapp):
        assert PANEL_W == 266
        assert PANEL_H == 189

    def test_grid_start_position(self, qapp):
        assert START_X == 44
        assert START_Y == 36

    def test_grid_spacing(self, qapp):
        assert SPACING_X == 300
        assert SPACING_Y == 199

    def test_grid_layout(self, qapp):
        assert COLUMNS == 4
        assert ROWS_PER_PAGE == 3

    def test_panels_per_page(self, qapp):
        assert PANELS_PER_PAGE == COLUMNS * ROWS_PER_PAGE
        assert PANELS_PER_PAGE == 12

    def test_value_positions_count(self, qapp):
        assert len(VALUE_POSITIONS) == 4

    def test_value_positions_x_coord(self, qapp):
        """All value labels share x=240."""
        for vx, _ in VALUE_POSITIONS:
            assert vx == 240

    def test_value_positions_y_increasing(self, qapp):
        """Y positions increase for each row."""
        ys = [vy for _, vy in VALUE_POSITIONS]
        assert ys == sorted(ys)

    def test_selector_positions_count(self, qapp):
        assert len(SELECTOR_POSITIONS) == 4

    def test_selector_positions_dimensions(self, qapp):
        """All selector buttons share same w=16, h=30."""
        for _, _, sw, sh in SELECTOR_POSITIONS:
            assert sw == 16
            assert sh == 30

    def test_page_nav_positions(self, qapp):
        """Page nav buttons have correct dimensions."""
        _, _, pw, ph = PAGE_PREV_POS
        assert pw == 64
        assert ph == 24
        _, _, nw, nh = PAGE_NEXT_POS
        assert nw == 64
        assert nh == 24

    def test_page_prev_left_of_next(self, qapp):
        px, _, _, _ = PAGE_PREV_POS
        nx, _, _, _ = PAGE_NEXT_POS
        assert px < nx


# =========================================================================
# SystemInfoPanel
# =========================================================================


class TestSystemInfoPanel:
    """Test single SystemInfoPanel widget."""

    @pytest.fixture
    def panel(self, qapp):
        """Create a SystemInfoPanel with mocked Assets."""
        config = _make_panel_config()
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        return p

    @pytest.fixture
    def custom_panel(self, qapp):
        """Create a custom (deletable) SystemInfoPanel."""
        config = _make_custom_panel_config()
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        return p

    def test_construction_size(self, panel):
        assert panel.width() == PANEL_W
        assert panel.height() == PANEL_H

    def test_construction_config_stored(self, panel):
        assert panel.config.category_id == 1
        assert panel.config.name == "CPU"

    def test_construction_value_labels_created(self, panel):
        assert len(panel._value_labels) == 4

    def test_construction_selector_buttons_created(self, panel):
        assert len(panel._selector_btns) == 4

    def test_construction_initial_values_are_dashes(self, panel):
        for lbl in panel._value_labels:
            assert lbl.text() == "--"

    def test_construction_selected_is_false(self, panel):
        assert panel._selected is False

    def test_construction_temp_unit_default(self, panel):
        assert panel._temp_unit == 0

    def test_construction_color_from_category(self, panel):
        expected = CATEGORY_COLORS.get(1)
        assert panel._color == expected

    def test_custom_panel_has_delete_button(self, custom_panel):
        assert hasattr(custom_panel, "_del_btn")

    def test_custom_panel_has_name_edit(self, custom_panel):
        assert hasattr(custom_panel, "_name_edit")
        assert custom_panel._name_edit.text() == "Custom"

    def test_non_custom_panel_no_delete_button(self, panel):
        assert not hasattr(panel, "_del_btn")

    # ── update_values ──

    def test_update_values_celsius(self, panel):
        readings = {"hwmon:coretemp:temp1": 65.0}
        panel.update_values(readings)
        assert panel._value_labels[0].text() == "65°C"

    def test_update_values_fahrenheit(self, panel):
        panel.set_temp_unit(1)
        readings = {"hwmon:coretemp:temp1": 100.0}
        panel.update_values(readings)
        # 100°C = 212°F
        assert panel._value_labels[0].text() == "212°F"

    def test_update_values_percent(self, panel):
        readings = {"psutil:cpu_percent": 42.0}
        panel.update_values(readings)
        assert panel._value_labels[1].text() == "42%"

    def test_update_values_mhz(self, panel):
        readings = {"psutil:cpu_freq": 3600.0}
        panel.update_values(readings)
        assert panel._value_labels[2].text() == "3600MHz"

    def test_update_values_watts(self, panel):
        readings = {"rapl:package-0": 95.0}
        panel.update_values(readings)
        assert panel._value_labels[3].text() == "95W"

    def test_update_values_missing_sensor(self, panel):
        """Missing sensor_id in readings shows '--'."""
        panel.update_values({})
        assert panel._value_labels[0].text() == "--"

    def test_update_values_empty_sensor_id(self, qapp):
        """Empty sensor_id in binding shows '--'."""
        config = PanelConfig(
            category_id=1,
            name="Test",
            sensors=[SensorBinding("X", "", "")],
        )
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        p.update_values({"some_key": 99.0})
        assert p._value_labels[0].text() == "--"

    def test_update_values_rpm(self, qapp):
        config = PanelConfig(
            category_id=6,
            name="Fan",
            sensors=[SensorBinding("CPUFAN", "hwmon:nct6798:fan1", "RPM")],
        )
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        p.update_values({"hwmon:nct6798:fan1": 1200.0})
        assert p._value_labels[0].text() == "1200RPM"

    def test_update_values_voltage(self, qapp):
        config = PanelConfig(
            category_id=0,
            name="Custom",
            sensors=[SensorBinding("VCORE", "hwmon:nct6798:in0", "V")],
        )
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        p.update_values({"hwmon:nct6798:in0": 1.23})
        assert p._value_labels[0].text() == "1.23V"

    def test_update_values_mb(self, qapp):
        config = PanelConfig(
            category_id=3,
            name="Memory",
            sensors=[SensorBinding("Available", "psutil:mem_avail", "MB")],
        )
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        p.update_values({"psutil:mem_avail": 8192.5})
        assert p._value_labels[0].text() == "8192.5MB"

    def test_update_values_kbs(self, qapp):
        config = PanelConfig(
            category_id=5,
            name="Net",
            sensors=[SensorBinding("UP", "computed:net_up", "KB/s")],
        )
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        p.update_values({"computed:net_up": 256.3})
        assert p._value_labels[0].text() == "256.3KB/s"

    def test_update_values_mbs(self, qapp):
        config = PanelConfig(
            category_id=4,
            name="HDD",
            sensors=[SensorBinding("Read", "computed:disk_read", "MB/s")],
        )
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        p.update_values({"computed:disk_read": 123.4})
        assert p._value_labels[0].text() == "123.4MB/s"

    def test_format_unknown_unit(self, qapp):
        """Unknown unit uses 1 decimal place."""
        config = PanelConfig(
            category_id=0,
            name="Custom",
            sensors=[SensorBinding("X", "some:sensor", "units")],
        )
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            p = SystemInfoPanel(config)
        p.update_values({"some:sensor": 3.14159})
        assert p._value_labels[0].text() == "3.1"

    # ── set_temp_unit ──

    def test_set_temp_unit_celsius(self, panel):
        panel.set_temp_unit(0)
        assert panel._temp_unit == 0

    def test_set_temp_unit_fahrenheit(self, panel):
        panel.set_temp_unit(1)
        assert panel._temp_unit == 1

    # ── set_selected ──

    def test_set_selected_true(self, panel):
        panel.set_selected(True)
        assert panel._selected is True

    def test_set_selected_false_after_true(self, panel):
        panel.set_selected(True)
        panel.set_selected(False)
        assert panel._selected is False

    # ── Signal emissions ──

    def test_signal_sensor_select_requested(self, panel):
        """Clicking a selector button emits sensor_select_requested."""
        received = []
        panel.sensor_select_requested.connect(lambda p, r: received.append((p, r)))
        panel._selector_btns[2].click()
        assert len(received) == 1
        assert received[0] == (panel, 2)

    def test_signal_delete_requested(self, custom_panel):
        """Delete button emits delete_requested signal."""
        received = []
        custom_panel.delete_requested.connect(lambda p: received.append(p))
        custom_panel._del_btn.click()
        assert len(received) == 1
        assert received[0] is custom_panel

    def test_signal_clicked(self, panel):
        """mousePressEvent emits clicked signal."""
        received = []
        panel.clicked.connect(lambda p: received.append(p))
        # Simulate mouse press via direct call
        from PySide6.QtCore import QPointF, Qt
        from PySide6.QtGui import QMouseEvent

        event = QMouseEvent(
            QMouseEvent.Type.MouseButtonPress,
            QPointF(10, 10),
            QPointF(10, 10),
            Qt.MouseButton.LeftButton,
            Qt.MouseButton.LeftButton,
            Qt.KeyboardModifier.NoModifier,
        )
        panel.mousePressEvent(event)
        assert len(received) == 1
        assert received[0] is panel


# =========================================================================
# UCSystemInfo
# =========================================================================


class TestUCSystemInfo:
    """Test the UCSystemInfo dashboard container."""

    @pytest.fixture
    def sysinfo(self, qapp, tmp_path):
        """Create UCSystemInfo with mocked dependencies."""
        mock_enum = _make_mock_enumerator()
        config_path = tmp_path / "system_config.json"
        with (
            patch("trcc.qt_components.uc_system_info.Assets") as mock_assets,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
            patch.object(SysInfoConfig, "CONFIG_PATH", config_path),
        ):
            mock_assets.load_pixmap.return_value = QPixmap()
            mock_assets.SYSINFO_BG = "A0test.png"
            widget = UCSystemInfo(mock_enum)
        return widget

    def test_construction(self, sysinfo):
        assert sysinfo is not None

    def test_initial_page_is_zero(self, sysinfo):
        assert sysinfo._page == 0

    def test_default_panels_created(self, sysinfo):
        """Default config creates 6 panels (CPU, GPU, Mem, HDD, Net, Fan)."""
        assert len(sysinfo._config.panels) == 6

    def test_panels_list_populated(self, sysinfo):
        """Visible panels created for first page."""
        assert len(sysinfo._panels_list) == 6

    def test_temp_unit_default(self, sysinfo):
        assert sysinfo._temp_unit == 0

    def test_has_update_timer(self, sysinfo):
        assert isinstance(sysinfo._update_timer, QTimer)

    def test_add_button_visible_when_space(self, sysinfo):
        """Add button appears when fewer than PANELS_PER_PAGE panels."""
        assert sysinfo._add_btn is not None

    def test_first_panel_selected_by_default(self, sysinfo):
        """First panel is auto-selected on construction."""
        assert sysinfo._selected_panel is not None
        if sysinfo._panels_list:
            assert sysinfo._selected_panel is sysinfo._panels_list[0]

    # ── Page navigation ──

    def test_change_page_forward(self, sysinfo):
        """Adding enough panels to need a second page, then navigating."""
        # Add 7 more panels to get 13 total (need 2 pages)
        for i in range(7):
            sysinfo._config.panels.append(
                _make_custom_panel_config(name=f"Extra{i}")
            )
        sysinfo._rebuild_grid()
        assert sysinfo._page == 0
        # Now navigate forward
        sysinfo._change_page(1)
        assert sysinfo._page == 1

    def test_change_page_backward(self, sysinfo):
        for i in range(7):
            sysinfo._config.panels.append(
                _make_custom_panel_config(name=f"Extra{i}")
            )
        sysinfo._rebuild_grid()
        sysinfo._change_page(1)
        assert sysinfo._page == 1
        sysinfo._change_page(-1)
        assert sysinfo._page == 0

    def test_page_clamped_to_max(self, sysinfo):
        """Page doesn't exceed max_page on rebuild."""
        sysinfo._page = 999
        sysinfo._rebuild_grid()
        # With 6 panels, max_page is 0
        assert sysinfo._page == 0

    # ── Add panel ──

    def test_on_add_clicked_adds_panel(self, sysinfo):
        initial_count = len(sysinfo._config.panels)
        with patch.object(SysInfoConfig, "save"):
            sysinfo._on_add_clicked()
        assert len(sysinfo._config.panels) == initial_count + 1

    def test_on_add_clicked_new_panel_is_custom(self, sysinfo):
        with patch.object(SysInfoConfig, "save"):
            sysinfo._on_add_clicked()
        last = sysinfo._config.panels[-1]
        assert last.category_id == 0
        assert last.name == "Custom"

    def test_on_add_clicked_navigates_to_new_panel_page(self, sysinfo):
        """After adding, page should be the page of the new panel."""
        with patch.object(SysInfoConfig, "save"):
            sysinfo._on_add_clicked()
        new_idx = len(sysinfo._config.panels) - 1
        expected_page = new_idx // PANELS_PER_PAGE
        assert sysinfo._page == expected_page

    # ── Delete panel ──

    def test_on_delete_clicked_removes_panel(self, sysinfo):
        # Add a custom panel first
        custom = _make_custom_panel_config()
        sysinfo._config.panels.append(custom)
        count_before = len(sysinfo._config.panels)
        with (
            patch.object(SysInfoConfig, "save"),
            patch("trcc.qt_components.uc_system_info.Assets") as mock_a,
            patch("trcc.qt_components.uc_system_info.set_background_pixmap"),
        ):
            mock_a.load_pixmap.return_value = QPixmap()
            # Create a panel widget for deletion
            panel_widget = MagicMock()
            panel_widget.config = custom
            sysinfo._on_delete_clicked(panel_widget)
        assert len(sysinfo._config.panels) == count_before - 1

    # ── Panel selection ──

    def test_on_panel_clicked_selects_panel(self, sysinfo):
        if len(sysinfo._panels_list) >= 2:
            second = sysinfo._panels_list[1]
            sysinfo._on_panel_clicked(second)
            assert sysinfo._selected_panel is second
            assert second._selected is True

    def test_on_panel_clicked_deselects_previous(self, sysinfo):
        if len(sysinfo._panels_list) >= 2:
            first = sysinfo._panels_list[0]
            second = sysinfo._panels_list[1]
            sysinfo._on_panel_clicked(first)
            sysinfo._on_panel_clicked(second)
            assert first._selected is False
            assert second._selected is True

    def test_panel_clicked_signal_emitted(self, sysinfo):
        received = []
        sysinfo.panel_clicked.connect(lambda p: received.append(p))
        if sysinfo._panels_list:
            sysinfo._on_panel_clicked(sysinfo._panels_list[0])
            assert len(received) == 1

    # ── Timer management ──

    def test_start_updates(self, sysinfo):
        mock_enum = sysinfo._enumerator
        mock_enum.read_all.return_value = {}
        sysinfo.start_updates()
        assert sysinfo._update_timer.isActive()
        sysinfo.stop_updates()

    def test_stop_updates(self, sysinfo):
        mock_enum = sysinfo._enumerator
        mock_enum.read_all.return_value = {}
        sysinfo.start_updates()
        sysinfo.stop_updates()
        assert not sysinfo._update_timer.isActive()

    def test_start_updates_calls_update_metrics(self, sysinfo):
        """start_updates() immediately calls _update_metrics."""
        mock_enum = sysinfo._enumerator
        mock_enum.read_all.return_value = {}
        sysinfo.start_updates()
        mock_enum.read_all.assert_called()
        sysinfo.stop_updates()

    # ── Temperature unit ──

    def test_set_temp_unit_propagates_to_panels(self, sysinfo):
        sysinfo.set_temp_unit(1)
        assert sysinfo._temp_unit == 1
        for panel in sysinfo._panels_list:
            assert panel._temp_unit == 1

    def test_set_temp_unit_celsius(self, sysinfo):
        sysinfo.set_temp_unit(0)
        assert sysinfo._temp_unit == 0

    # ── Name change ──

    def test_on_name_changed(self, sysinfo):
        if sysinfo._panels_list:
            panel = sysinfo._panels_list[0]
            with patch.object(SysInfoConfig, "save"):
                sysinfo._on_name_changed(panel, "NewName")
            assert panel.config.name == "NewName"

    # ── Update metrics error handling ──

    def test_update_metrics_handles_exception(self, sysinfo):
        """_update_metrics doesn't crash when enumerator raises."""
        sysinfo._enumerator.read_all.side_effect = RuntimeError("sensor fail")
        # Should not raise
        sysinfo._update_metrics()

    def test_update_metrics_updates_panels(self, sysinfo):
        """_update_metrics forwards readings to all panels."""
        readings = {"hwmon:coretemp:temp1": 70.0}
        sysinfo._enumerator.read_all.return_value = readings
        sysinfo._update_metrics()
        # First panel's first sensor is coretemp:temp1
        if sysinfo._panels_list:
            first = sysinfo._panels_list[0]
            # After update, first label should show the value
            text = first._value_labels[0].text()
            assert text != "--" or first.config.sensors[0].sensor_id != "hwmon:coretemp:temp1"


# =========================================================================
# LEDHandler
# =========================================================================


class TestLEDHandler:
    """Test the LEDHandler mediator from qt_app_mvc."""

    @pytest.fixture
    def mock_panel(self, qapp):
        """Create a mock UCLedControl panel with the required signals."""
        panel = MagicMock()
        # Real signals need to be on a QObject, so use a helper
        # Instead, mock the signal connects to track them
        panel.mode_changed = MagicMock()
        panel.color_changed = MagicMock()
        panel.brightness_changed = MagicMock()
        panel.global_toggled = MagicMock()
        panel.segment_clicked = MagicMock()
        panel.zone_selected = MagicMock()
        panel.zone_toggled = MagicMock()
        panel.carousel_changed = MagicMock()
        panel.carousel_zone_changed = MagicMock()
        panel.carousel_interval_changed = MagicMock()
        panel.clock_format_changed = MagicMock()
        panel.week_start_changed = MagicMock()
        panel.temp_unit_changed = MagicMock()
        panel.disk_index_changed = MagicMock()
        panel.memory_ratio_changed = MagicMock()
        panel.test_mode_changed = MagicMock()
        panel.selected_zone = 0
        return panel

    @pytest.fixture
    def handler(self, qapp, mock_panel):
        """Create a LEDHandler with a real QWidget parent for QTimer."""
        parent = QWidget()
        from trcc.qt_components.qt_app_mvc import LEDHandler

        h = LEDHandler(parent, lambda u: None)
        # Keep parent alive so QTimer's C++ parent isn't deleted
        h._qt_parent = parent
        # Replace internal panel ref with mock
        h._panel = mock_panel
        return h

    def test_construction(self, handler):
        assert handler._active is False
        assert handler._controller is None
        assert handler._style_id == 0

    def test_active_property_false_initially(self, handler):
        assert handler.active is False

    def test_has_controller_false_initially(self, handler):
        assert handler.has_controller is False

    def test_stop_when_inactive(self, handler):
        """stop() when never started should not raise."""
        handler.stop()
        assert handler.active is False

    def test_stop_sets_active_false(self, handler):
        handler._active = True
        handler.stop()
        assert handler.active is False

    def test_cleanup_stops_timer(self, handler):
        handler._timer.start(100)
        handler.cleanup()
        assert not handler._timer.isActive()

    def test_set_temp_unit_no_controller(self, handler):
        """set_temp_unit when no controller does not raise."""
        handler.set_temp_unit("C")

    def test_set_temp_unit_with_controller(self, handler):
        mock_ctrl = MagicMock()
        handler._controller = mock_ctrl
        handler.set_temp_unit("F")
        mock_ctrl.set_seg_temp_unit.assert_called_once_with("F")

    def test_sync_ui_no_controller(self, handler):
        """_sync_ui_from_state() with no controller is a no-op."""
        handler._sync_ui_from_state()  # Should not raise

    def test_sync_ui_with_zones(self, handler):
        """_sync_ui_from_state() with zone state loads zone 0."""
        mock_ctrl = MagicMock()
        zone = LEDZoneState(
            mode=LEDMode.BREATHING, color=(0, 255, 0), brightness=80, on=True
        )
        mock_ctrl.state = _make_mock_led_state(zones=[zone])
        mock_ctrl.state.zones = [zone]
        handler._controller = mock_ctrl
        handler._sync_ui_from_state()
        handler._panel.load_zone_state.assert_called_once_with(
            0, LEDMode.BREATHING.value, (0, 255, 0), 80, True
        )

    def test_sync_ui_without_zones(self, handler):
        """_sync_ui_from_state() with no zones loads global state."""
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state(
            mode=LEDMode.RAINBOW, color=(100, 200, 50), brightness=90
        )
        handler._controller = mock_ctrl
        handler._sync_ui_from_state()
        handler._panel.load_zone_state.assert_called_once_with(
            0, LEDMode.RAINBOW.value, (100, 200, 50), 90, True
        )

    def test_show_creates_controller(self, handler):
        """show() creates LEDDeviceController if not already present."""
        device = MagicMock()
        device.model = "AX120_DIGITAL"
        device.led_style_id = 1
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state()

        mock_style_info = MagicMock()
        mock_style_info.segment_count = 10
        mock_style_info.zone_count = 1

        with (
            patch(
                "trcc.qt_components.qt_app_mvc.LEDDeviceController",
                return_value=mock_ctrl,
            ),
            patch(
                "trcc.services.led.LEDService"
            ) as mock_led_svc,
            patch.object(handler, "_connect_signals"),
            patch("trcc.qt_components.qt_app_mvc.settings") as mock_settings,
        ):
            mock_led_svc.resolve_style_id.return_value = 1
            mock_led_svc.get_style_info.return_value = mock_style_info
            mock_settings.temp_unit = 0
            handler.show(device)

        assert handler._controller is mock_ctrl
        assert handler._active is True

    def test_show_starts_timer(self, handler):
        device = MagicMock()
        device.model = "AX120_DIGITAL"
        device.led_style_id = 1
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state()

        mock_style_info = MagicMock()
        mock_style_info.segment_count = 10
        mock_style_info.zone_count = 1

        with (
            patch(
                "trcc.qt_components.qt_app_mvc.LEDDeviceController",
                return_value=mock_ctrl,
            ),
            patch(
                "trcc.services.led.LEDService"
            ) as mock_led_svc,
            patch.object(handler, "_connect_signals"),
            patch("trcc.qt_components.qt_app_mvc.settings") as mock_settings,
        ):
            mock_led_svc.resolve_style_id.return_value = 1
            mock_led_svc.get_style_info.return_value = mock_style_info
            mock_settings.temp_unit = 0
            handler.show(device)

        assert handler._timer.isActive()
        handler.stop()

    def test_show_initializes_controller(self, handler):
        device = MagicMock()
        device.model = "PA120_DIGITAL"
        device.led_style_id = 2
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state()

        mock_style_info = MagicMock()
        mock_style_info.segment_count = 10
        mock_style_info.zone_count = 4

        with (
            patch(
                "trcc.qt_components.qt_app_mvc.LEDDeviceController",
                return_value=mock_ctrl,
            ),
            patch(
                "trcc.services.led.LEDService"
            ) as mock_led_svc,
            patch.object(handler, "_connect_signals"),
            patch("trcc.qt_components.qt_app_mvc.settings") as mock_settings,
        ):
            mock_led_svc.resolve_style_id.return_value = 2
            mock_led_svc.get_style_info.return_value = mock_style_info
            mock_settings.temp_unit = 0
            handler.show(device)

        mock_ctrl.initialize.assert_called_once_with(device, 2)
        handler.stop()

    def test_stop_cleans_up_controller(self, handler):
        mock_ctrl = MagicMock()
        handler._controller = mock_ctrl
        handler._active = True
        handler.stop()
        mock_ctrl.cleanup.assert_called_once()

    def test_tick_no_controller(self, handler):
        """_on_tick without controller is a no-op."""
        handler._on_tick()  # Should not raise

    def test_tick_not_active(self, handler):
        """_on_tick when not active is a no-op."""
        mock_ctrl = MagicMock()
        handler._controller = mock_ctrl
        handler._active = False
        handler._on_tick()
        mock_ctrl.tick.assert_not_called()

    def test_tick_calls_controller_tick(self, handler):
        mock_ctrl = MagicMock()
        handler._controller = mock_ctrl
        handler._active = True
        handler._on_tick()
        mock_ctrl.tick.assert_called_once()

    def test_on_mode_changed_no_controller(self, handler):
        """_on_mode_changed with no controller is a no-op."""
        handler._on_mode_changed(0)  # Should not raise

    def test_on_mode_changed_sets_global(self, handler):
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state()
        handler._controller = mock_ctrl
        handler._on_mode_changed(2)
        mock_ctrl.set_mode.assert_called_once_with(2)

    def test_on_mode_changed_sets_zone_when_zones(self, handler):
        mock_ctrl = MagicMock()
        zones = [LEDZoneState(), LEDZoneState()]
        mock_ctrl.state = _make_mock_led_state(zones=zones)
        mock_ctrl.state.zones = zones
        handler._controller = mock_ctrl
        handler._panel.selected_zone = 1
        handler._on_mode_changed(3)
        mock_ctrl.set_zone_mode.assert_called_once_with(1, 3)

    def test_on_color_changed_no_controller(self, handler):
        handler._on_color_changed(255, 0, 0)  # Should not raise

    def test_on_color_changed_sets_global(self, handler):
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state()
        handler._controller = mock_ctrl
        handler._on_color_changed(0, 128, 255)
        mock_ctrl.set_color.assert_called_once_with(0, 128, 255)

    def test_on_brightness_changed_no_controller(self, handler):
        handler._on_brightness_changed(50)  # Should not raise

    def test_on_brightness_changed_sets_global(self, handler):
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state()
        handler._controller = mock_ctrl
        handler._on_brightness_changed(80)
        mock_ctrl.set_brightness.assert_called_once_with(80)

    def test_on_zone_selected_no_controller(self, handler):
        handler._on_zone_selected(0)  # Should not raise

    def test_on_zone_selected_loads_zone_state(self, handler):
        mock_ctrl = MagicMock()
        z0 = LEDZoneState(mode=LEDMode.COLORFUL, color=(10, 20, 30), brightness=50, on=False)
        z1 = LEDZoneState(mode=LEDMode.RAINBOW, color=(40, 50, 60), brightness=70, on=True)
        mock_ctrl.state = _make_mock_led_state(zones=[z0, z1])
        mock_ctrl.state.zones = [z0, z1]
        handler._controller = mock_ctrl
        handler._on_zone_selected(1)
        handler._panel.load_zone_state.assert_called_once_with(
            1, LEDMode.RAINBOW.value, (40, 50, 60), 70, True
        )

    def test_on_zone_selected_no_zones_no_op(self, handler):
        mock_ctrl = MagicMock()
        mock_ctrl.state = _make_mock_led_state()
        mock_ctrl.state.zones = []
        handler._controller = mock_ctrl
        handler._on_zone_selected(0)
        handler._panel.load_zone_state.assert_not_called()

    def test_on_colors_update_forwards_to_panel(self, handler):
        colors = [(255, 0, 0), (0, 255, 0)]
        handler._on_colors_update(colors)
        handler._panel.set_led_colors.assert_called_once_with(colors)

    def test_update_from_metrics_no_controller(self, handler):
        """update_from_metrics with no controller is a no-op."""
        handler.update_from_metrics(MagicMock())  # Should not raise

    def test_update_from_metrics_forwards_to_controller_and_panel(self, handler):
        mock_ctrl = MagicMock()
        handler._controller = mock_ctrl
        metrics = MagicMock()
        handler.update_from_metrics(metrics)
        mock_ctrl.update_metrics.assert_called_once_with(metrics)
        handler._panel.update_metrics.assert_called_once_with(metrics)


# =========================================================================
# ScreencastHandler
# =========================================================================


class TestScreencastHandler:
    """Test the ScreencastHandler state machine from qt_app_mvc."""

    @pytest.fixture
    def handler(self, qapp):
        from trcc.qt_components.qt_app_mvc import ScreencastHandler

        parent = QWidget()
        mock_ctrl = MagicMock()
        mock_ctrl.lcd_width = 320
        mock_ctrl.lcd_height = 320
        on_frame = MagicMock()
        h = ScreencastHandler(parent, mock_ctrl, on_frame)
        # Keep parent alive so QTimer's C++ parent isn't deleted
        h._qt_parent = parent
        return h

    def test_construction(self, handler):
        assert handler.active is False
        assert handler._x == 0
        assert handler._y == 0
        assert handler._w == 0
        assert handler._h == 0
        assert handler.border is True
        assert handler._pipewire_cast is None

    def test_active_property(self, handler):
        assert handler.active is False
        handler.active = True
        assert handler.active is True

    def test_set_params(self, handler):
        handler.set_params(10, 20, 640, 480)
        assert handler._x == 10
        assert handler._y == 20
        assert handler._w == 640
        assert handler._h == 480

    def test_set_border(self, handler):
        handler.set_border(False)
        assert handler.border is False
        handler.set_border(True)
        assert handler.border is True

    def test_stop_sets_inactive(self, handler):
        handler._active = True
        handler.stop()
        assert handler.active is False

    def test_stop_stops_timer(self, handler):
        handler._timer.start(100)
        handler.stop()
        assert not handler._timer.isActive()

    def test_cleanup_stops_timer(self, handler):
        handler._timer.start(100)
        handler.cleanup()
        assert not handler._timer.isActive()

    def test_cleanup_stops_pipewire(self, handler):
        mock_cast = MagicMock()
        handler._pipewire_cast = mock_cast
        handler.cleanup()
        mock_cast.stop.assert_called_once()
        assert handler._pipewire_cast is None

    def test_toggle_on_starts_timer(self, handler):
        with patch("trcc.qt_components.qt_app_mvc.ScreencastHandler._try_start_pipewire"):
            with patch("trcc.qt_components.qt_app_mvc.ScreencastHandler.__init__", lambda *a, **kw: None):
                pass
        # Direct test of toggle
        with patch.object(handler, "_try_start_pipewire"):
            with patch("trcc.qt_components.screen_capture.is_wayland", return_value=False):
                handler.toggle(True)
        assert handler.active is True
        assert handler._timer.isActive()
        handler.stop()

    def test_toggle_off_stops_timer(self, handler):
        with patch("trcc.qt_components.screen_capture.is_wayland", return_value=False):
            handler.toggle(True)
        handler.toggle(False)
        assert handler.active is False
        assert not handler._timer.isActive()

    def test_tick_no_op_when_inactive(self, handler):
        """_tick does nothing when not active."""
        handler._active = False
        handler._w = 100
        handler._h = 100
        handler._tick()  # Should not raise

    def test_tick_no_op_when_zero_dimensions(self, handler):
        """_tick does nothing when dimensions are zero."""
        handler._active = True
        handler._w = 0
        handler._h = 0
        handler._tick()  # Should not raise


# =========================================================================
# Category images / colors domain data
# =========================================================================


class TestCategoryData:
    """Verify category domain data consistency."""

    def test_category_images_has_all_ids(self, qapp):
        for i in range(7):
            assert i in CATEGORY_IMAGES

    def test_category_colors_has_all_ids(self, qapp):
        for i in range(7):
            assert i in CATEGORY_COLORS

    def test_category_colors_are_hex(self, qapp):
        for color in CATEGORY_COLORS.values():
            assert color.startswith("#")
            assert len(color) == 7

    def test_category_images_are_png(self, qapp):
        for img in CATEGORY_IMAGES.values():
            assert img.endswith(".png")
