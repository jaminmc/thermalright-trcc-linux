"""Tests for macOS sensor enumerator — platform-specific behavior only.

Shared base behavior (psutil, nvidia, computed I/O, polling, read_all)
is tested in tests/adapters/system/conftest.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.adapters.system.conftest import BASE

MODULE = 'trcc.adapters.system.macos.sensors'


def _make_enum(**flags):
    """Create MacOSSensorEnumerator with optional feature flags."""
    with patch(f'{BASE}.NVML_AVAILABLE', flags.get('nvml', False)), \
         patch(f'{MODULE}.IS_APPLE_SILICON', flags.get('arm', False)):
        from trcc.adapters.system.macos.sensors import MacOSSensorEnumerator
        return MacOSSensorEnumerator()


class TestDiscoverAppleSilicon:

    def test_registers_common_sensors(self):
        enum = _make_enum(arm=True)
        enum._discover_apple_silicon()
        ids = [s.id for s in enum._sensors]
        assert 'iokit:cpu_die' in ids
        assert 'iokit:gpu_die' in ids
        assert 'iokit:soc' in ids
        assert 'iokit:gpu_busy' in ids
        assert 'iokit:gpu_clock' in ids
        assert 'iokit:gpu_power' in ids
        assert 'iokit:fan0' in ids
        assert 'iokit:fan1' in ids
        assert all(s.source == 'iokit' for s in enum._sensors)


class TestDiscoverSmc:

    @patch(f'{MODULE}._iokit', None)
    def test_noop_without_iokit(self):
        enum = _make_enum()
        enum._discover_smc()
        assert not any(s.source == 'smc' for s in enum._sensors)


class TestDiscoverEndToEnd:

    @patch(f'{BASE}.NVML_AVAILABLE', False)
    @patch(f'{MODULE}.IS_APPLE_SILICON', True)
    @patch(f'{MODULE}._iokit', None)
    def test_discover_apple_silicon(self):
        enum = _make_enum(arm=True)
        sensors = enum.discover()
        sources = {s.source for s in sensors}
        assert 'psutil' in sources
        assert 'iokit' in sources
        assert 'computed' in sources

    @patch(f'{BASE}.NVML_AVAILABLE', False)
    @patch(f'{MODULE}.IS_APPLE_SILICON', False)
    @patch(f'{MODULE}._iokit', None)
    def test_discover_intel(self):
        enum = _make_enum()
        sensors = enum.discover()
        sources = {s.source for s in sensors}
        assert 'psutil' in sources
        assert 'computed' in sources
        assert 'smc' not in sources


class TestPollAppleSilicon:

    @patch(f'{MODULE}.subprocess')
    def test_parses_powermetrics(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            stdout=(
                "CPU die temperature: 45.23 C\n"
                "GPU die temperature: 52.1 C\n"
                "Fan: 1200 rpm\n"
                "Fan: 1350 rpm\n"
                "CPU 0 frequency: 1690 MHz\n"
                "CPU 4 frequency: 2937 MHz\n"
                "GPU active residency: 31%\n"
                "GPU Power: 4.5 W\n"
                "GPU HW active frequency: 1398 MHz\n"
            ),
        )
        enum = _make_enum(arm=True)
        readings: dict[str, float] = {}
        enum._poll_apple_silicon(readings)
        assert readings['iokit:cpu_die'] == 45.23
        assert readings['iokit:gpu_die'] == 52.1
        assert readings['iokit:fan0'] == 1200.0
        assert readings['iokit:fan1'] == 1350.0
        assert readings['psutil:cpu_freq'] == 2937.0
        assert readings['iokit:gpu_busy'] == 31.0
        assert readings['iokit:gpu_power'] == 4.5
        assert readings['iokit:gpu_clock'] == 1398.0

    @patch(f'{MODULE}.subprocess')
    def test_parses_gpu_power_milliwatts(self, mock_sub):
        mock_sub.run.return_value = MagicMock(stdout="GPU Power: 150 mW\n")
        enum = _make_enum(arm=True)
        readings: dict[str, float] = {}
        enum._poll_apple_silicon(readings)
        assert readings['iokit:gpu_power'] == 0.15

    @patch(f'{MODULE}.subprocess')
    def test_handles_failure(self, mock_sub):
        mock_sub.run.side_effect = RuntimeError("no root")
        enum = _make_enum(arm=True)
        readings: dict[str, float] = {}
        enum._poll_apple_silicon(readings)
        assert len(readings) == 0


class TestPollApfsDiskPercent:

    DISKUTIL_OUTPUT = (
        "APFS Container Reference:     disk1\n"
        "Size (Capacity Ceiling):      500107862016 B (500.1 GB)\n"
        "Minimum Size:                 N/A\n"
        "Capacity In Use By Volumes:   400086323200 B (400.1 GB)\n"
        "Capacity Not Allocated:       100021538816 B (100.0 GB)\n"
    )

    @patch(f'{MODULE}.subprocess')
    def test_parses_apfs_container(self, mock_sub):
        mock_sub.run.return_value = MagicMock(stdout=self.DISKUTIL_OUTPUT)
        enum = _make_enum()
        pct = enum._poll_apfs_disk_percent()
        assert pct == round(400086323200 / 500107862016 * 100, 1)

    @patch(f'{MODULE}.subprocess')
    @patch(f'{MODULE}.psutil')
    def test_falls_back_to_psutil_on_error(self, mock_psutil, mock_sub):
        mock_sub.run.side_effect = FileNotFoundError("no diskutil")
        mock_psutil.disk_usage.return_value = MagicMock(percent=55.0)
        enum = _make_enum()
        pct = enum._poll_apfs_disk_percent()
        assert pct == 55.0


class TestMapDefaults:

    @patch(f'{BASE}.NVML_AVAILABLE', False)
    @patch(f'{MODULE}.IS_APPLE_SILICON', True)
    @patch(f'{MODULE}._iokit', None)
    def test_apple_silicon_maps_gpu_and_net(self):
        enum = _make_enum(arm=True)
        enum.discover()
        mapping = enum.map_defaults()
        assert mapping['gpu_usage'] == 'iokit:gpu_busy'
        assert mapping['gpu_clock'] == 'iokit:gpu_clock'
        assert mapping['gpu_power'] == 'iokit:gpu_power'
        assert mapping['mem_available'] == 'psutil:mem_available'
        assert mapping['mem_temp'] == 'iokit:soc'
        assert mapping['disk_activity'] == 'computed:disk_activity'
        assert mapping['net_total_up'] == 'computed:net_total_up'
        assert mapping['fan_cpu'] == 'iokit:fan0'
        assert mapping['fan_gpu'] == 'iokit:fan1'


class TestParseMetric:

    def test_temperature(self):
        from trcc.adapters.system.macos.sensors import _parse_metric
        assert _parse_metric('CPU die temperature: 45.23 C') == 45.23

    def test_fan(self):
        from trcc.adapters.system.macos.sensors import _parse_metric
        assert _parse_metric('Fan: 1200 rpm') == 1200.0

    def test_no_number(self):
        from trcc.adapters.system.macos.sensors import _parse_metric
        assert _parse_metric('no numbers here') == 0.0
