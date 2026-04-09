"""Tests for macOS sensor enumerator (mocked — runs on Linux)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from trcc.core.models import SensorInfo

MODULE = 'trcc.adapters.system.macos.sensors'


def _make_enum(**flags):
    """Create MacOSSensorEnumerator with optional feature flags."""
    with patch(f'{MODULE}.NVML_AVAILABLE', flags.get('nvml', False)), \
         patch(f'{MODULE}.IS_APPLE_SILICON', flags.get('arm', False)):
        from trcc.adapters.system.macos.sensors import MacOSSensorEnumerator
        return MacOSSensorEnumerator()


class TestDiscoverPsutil:

    def test_discovers_cpu_memory_disk_net(self):
        enum = _make_enum()
        enum._discover_psutil()
        ids = [s.id for s in enum._sensors]
        assert 'psutil:cpu_percent' in ids
        assert 'psutil:cpu_freq' in ids
        assert 'psutil:mem_used' in ids
        assert 'psutil:mem_available' in ids
        assert 'computed:disk_percent' in ids
        assert 'computed:disk_read' in ids
        assert 'computed:disk_activity' in ids
        assert 'computed:net_up' in ids
        assert 'computed:net_total_up' in ids
        assert 'computed:net_total_down' in ids

    def test_all_have_source(self):
        enum = _make_enum()
        enum._discover_psutil()
        for s in enum._sensors:
            assert s.source in ('psutil', 'computed')


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
        assert 'iokit:fan2' in ids
        assert 'iokit:fan3' in ids
        assert all(s.source == 'iokit' for s in enum._sensors)


class TestDiscoverSmc:

    @patch(f'{MODULE}._iokit', None)
    def test_noop_without_iokit(self):
        enum = _make_enum()
        enum._discover_smc()
        assert not any(s.source == 'smc' for s in enum._sensors)


class TestDiscoverNvidia:

    @patch(f'{MODULE}.pynvml', None)
    @patch(f'{MODULE}.NVML_AVAILABLE', False)
    def test_noop_without_nvml(self):
        enum = _make_enum()
        enum._discover_nvidia()
        assert enum._sensors == []

    @patch(f'{MODULE}.NVML_AVAILABLE', True)
    @patch(f'{MODULE}.pynvml')
    def test_discovers_egpu(self, mock_nvml):
        mock_nvml.nvmlDeviceGetCount.return_value = 1
        mock_nvml.nvmlDeviceGetHandleByIndex.return_value = 'h'
        mock_nvml.nvmlDeviceGetName.return_value = 'RTX 4090'

        enum = _make_enum()
        enum._discover_nvidia()
        assert len(enum._sensors) == 4
        ids = [s.id for s in enum._sensors]
        assert 'nvidia:0:temp' in ids
        assert 'nvidia:0:gpu_busy' in ids
        assert 'nvidia:0:power' in ids
        assert 'nvidia:0:fan' in ids


class TestDiscoverComputed:

    def test_datetime_sensors(self):
        enum = _make_enum()
        enum._discover_computed()
        ids = [s.id for s in enum._sensors]
        assert 'computed:date_year' in ids
        assert 'computed:day_of_week' in ids
        assert len(enum._sensors) == 7


class TestDiscoverEndToEnd:

    @patch(f'{MODULE}.NVML_AVAILABLE', False)
    @patch(f'{MODULE}.IS_APPLE_SILICON', True)
    @patch(f'{MODULE}._iokit', None)
    def test_discover_apple_silicon(self):
        enum = _make_enum(arm=True)
        sensors = enum.discover()
        sources = {s.source for s in sensors}
        assert 'psutil' in sources
        assert 'iokit' in sources
        assert 'computed' in sources

    @patch(f'{MODULE}.NVML_AVAILABLE', False)
    @patch(f'{MODULE}.IS_APPLE_SILICON', False)
    @patch(f'{MODULE}._iokit', None)
    def test_discover_intel(self):
        enum = _make_enum()
        sensors = enum.discover()
        sources = {s.source for s in sensors}
        assert 'psutil' in sources
        assert 'computed' in sources
        # No smc without IOKit
        assert 'smc' not in sources

    def test_discover_clears_previous(self):
        enum = _make_enum()
        enum._sensors = [SensorInfo('old', 'Old', 'x', 'x', 'x')]
        enum.discover()
        assert not any(s.id == 'old' for s in enum._sensors)


class TestPollPsutil:

    @patch(f'{MODULE}.psutil')
    @patch(f'{MODULE}.datetime')
    def test_reads_cpu_and_memory(self, mock_dt, mock_psutil):
        mock_psutil.cpu_percent.return_value = 42.0
        mock_psutil.cpu_freq.return_value = MagicMock(current=3200.0)
        mock_psutil.virtual_memory.return_value = MagicMock(
            used=8 * 1024 ** 2, available=7 * 1024 ** 2,
            total=16 * 1024 ** 2, percent=50.0,
        )
        from datetime import datetime
        mock_dt.datetime.now.return_value = datetime(2026, 3, 13, 14, 0, 0)

        enum = _make_enum()
        with patch.object(enum, '_poll_apfs_disk_percent', return_value=45.0), \
             patch.object(enum, '_poll_computed_io'), \
             patch.object(enum, '_poll_smc'), \
             patch.object(enum, '_poll_apple_silicon'):
            enum._poll_once()
        readings = enum.read_all()
        assert readings['psutil:cpu_percent'] == 42.0
        assert readings['psutil:cpu_freq'] == 3200.0
        assert readings['psutil:mem_available'] == 7.0
        assert readings['computed:disk_percent'] == 45.0

    @patch(f'{MODULE}.psutil')
    @patch(f'{MODULE}.datetime')
    def test_cpu_percent_bootstraps_with_short_interval(self, mock_dt, mock_psutil):
        """First poll uses interval=0.08, subsequent polls use interval=None."""
        mock_psutil.cpu_percent.return_value = 7.0
        mock_psutil.cpu_freq.return_value = MagicMock(current=3200.0)
        mock_psutil.virtual_memory.return_value = MagicMock(
            used=1 * 1024 ** 2, available=1 * 1024 ** 2,
            total=2 * 1024 ** 2, percent=50.0,
        )
        from datetime import datetime
        mock_dt.datetime.now.return_value = datetime(2026, 3, 13, 14, 0, 0)

        enum = _make_enum()
        with patch.object(enum, '_poll_apfs_disk_percent', return_value=45.0), \
             patch.object(enum, '_poll_computed_io'), \
             patch.object(enum, '_poll_smc'), \
             patch.object(enum, '_poll_apple_silicon'):
            enum._poll_once()

        # First call uses short interval for bootstrap
        mock_psutil.cpu_percent.assert_called_once_with(interval=0.08)
        assert enum._cpu_pct_bootstrapped is True
        assert enum.read_all()['psutil:cpu_percent'] == 7.0


class TestReadAllBootstrap:

    @patch(f'{MODULE}.psutil')
    @patch(f'{MODULE}.datetime')
    def test_read_all_triggers_poll_on_empty(self, mock_dt, mock_psutil):
        """read_all() calls _poll_once() if no readings exist yet."""
        mock_psutil.cpu_percent.return_value = 10.0
        mock_psutil.cpu_freq.return_value = MagicMock(current=2400.0)
        mock_psutil.virtual_memory.return_value = MagicMock(
            used=4 * 1024 ** 2, available=4 * 1024 ** 2,
            total=8 * 1024 ** 2, percent=50.0,
        )
        from datetime import datetime
        mock_dt.datetime.now.return_value = datetime(2026, 3, 13, 14, 0, 0)

        enum = _make_enum()
        assert enum._readings == {}
        with patch.object(enum, '_poll_apfs_disk_percent', return_value=30.0), \
             patch.object(enum, '_poll_computed_io'), \
             patch.object(enum, '_poll_smc'), \
             patch.object(enum, '_poll_apple_silicon'):
            readings = enum.read_all()
        assert readings['psutil:cpu_percent'] == 10.0
        assert readings != {}

    def test_read_all_does_not_repoll_when_populated(self):
        """read_all() returns cached readings without re-polling."""
        enum = _make_enum()
        enum._readings = {'psutil:cpu_percent': 55.0}
        with patch.object(enum, '_poll_once') as mock_poll:
            readings = enum.read_all()
        mock_poll.assert_not_called()
        assert readings['psutil:cpu_percent'] == 55.0


class TestPollComputedIO:

    @patch(f'{MODULE}.psutil')
    @patch(f'{MODULE}.time')
    def test_network_totals_on_first_call(self, mock_time, mock_psutil):
        mock_time.monotonic.return_value = 100.0
        mock_psutil.disk_io_counters.return_value = None
        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=10 * 1024 * 1024, bytes_recv=20 * 1024 * 1024,
        )
        enum = _make_enum()
        readings: dict[str, float] = {}
        enum._poll_computed_io(readings)
        assert readings['computed:net_total_up'] == 10.0
        assert readings['computed:net_total_down'] == 20.0
        # No rates on first call (no previous sample)
        assert 'computed:net_up' not in readings
        assert 'computed:net_down' not in readings

    @patch(f'{MODULE}.psutil')
    @patch(f'{MODULE}.time')
    def test_disk_and_net_rates_on_second_call(self, mock_time, mock_psutil):
        mock_time.monotonic.side_effect = [100.0, 102.0]  # 2-second gap
        mock_psutil.disk_io_counters.side_effect = [
            MagicMock(read_bytes=0, write_bytes=0),
            MagicMock(read_bytes=2 * 1024 * 1024, write_bytes=1 * 1024 * 1024),
        ]
        mock_psutil.net_io_counters.side_effect = [
            MagicMock(bytes_sent=0, bytes_recv=0),
            MagicMock(bytes_sent=2048, bytes_recv=4096),
        ]
        enum = _make_enum()

        # First call — sets baseline
        r1: dict[str, float] = {}
        enum._poll_computed_io(r1)
        assert 'computed:disk_read' not in r1

        # Second call — computes rates
        r2: dict[str, float] = {}
        enum._poll_computed_io(r2)
        assert r2['computed:disk_read'] == 1.0   # 2 MB / 2s = 1 MB/s
        assert r2['computed:disk_write'] == 0.5   # 1 MB / 2s = 0.5 MB/s
        assert r2['computed:net_up'] == 1.0       # 2048 B / 2s = 1024 B/s = 1 KB/s
        assert r2['computed:net_down'] == 2.0     # 4096 B / 2s = 2048 B/s = 2 KB/s


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
        # 400086323200 / 500107862016 ≈ 79.999... → 80.0
        assert pct == round(400086323200 / 500107862016 * 100, 1)

    @patch(f'{MODULE}.subprocess')
    @patch(f'{MODULE}.psutil')
    def test_falls_back_to_psutil_on_error(self, mock_psutil, mock_sub):
        mock_sub.run.side_effect = FileNotFoundError("no diskutil")
        mock_psutil.disk_usage.return_value = MagicMock(percent=55.0)
        enum = _make_enum()
        pct = enum._poll_apfs_disk_percent()
        assert pct == 55.0

    @patch(f'{MODULE}.subprocess')
    @patch(f'{MODULE}.psutil')
    def test_falls_back_when_capacity_zero(self, mock_psutil, mock_sub):
        mock_sub.run.return_value = MagicMock(stdout="no capacity lines here\n")
        mock_psutil.disk_usage.return_value = MagicMock(percent=30.0)
        enum = _make_enum()
        pct = enum._poll_apfs_disk_percent()
        assert pct == 30.0


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
        mock_sub.run.return_value = MagicMock(
            stdout="GPU Power: 150 mW\n",
        )
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


class TestPollNvidia:

    @patch(f'{MODULE}.pynvml')
    def test_reads_egpu(self, mock_nvml):
        mock_nvml.nvmlDeviceGetCount.return_value = 1
        mock_nvml.nvmlDeviceGetHandleByIndex.return_value = 'h'
        mock_nvml.NVML_TEMPERATURE_GPU = 0
        mock_nvml.nvmlDeviceGetTemperature.return_value = 68
        mock_nvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=80)
        mock_nvml.nvmlDeviceGetPowerUsage.return_value = 250000
        mock_nvml.nvmlDeviceGetFanSpeed.return_value = 55

        enum = _make_enum()
        readings: dict[str, float] = {}
        enum._poll_nvidia(readings)
        assert readings['nvidia:0:temp'] == 68.0
        assert readings['nvidia:0:gpu_busy'] == 80.0
        assert readings['nvidia:0:power'] == 250.0
        assert readings['nvidia:0:fan'] == 55.0


class TestPolling:

    def test_start_stop(self):
        enum = _make_enum()
        with patch.object(enum, '_poll_once'):
            enum.start_polling(interval=0.01)
            assert enum._poll_thread is not None
            assert enum._poll_thread.is_alive()
            enum.stop_polling()
            assert not enum._poll_thread.is_alive()


class TestGetters:

    def test_get_by_category(self):
        enum = _make_enum()
        enum._sensors = [
            SensorInfo('a', 'A', 'temperature', '°C', 'smc'),
            SensorInfo('b', 'B', 'fan', 'RPM', 'smc'),
        ]
        assert len(enum.get_by_category('temperature')) == 1

    def test_read_all_copy(self):
        enum = _make_enum()
        enum._readings = {'x': 1.0}
        r = enum.read_all()
        r['x'] = 999.0
        assert enum._readings['x'] == 1.0


class TestMapDefaults:

    @patch(f'{MODULE}.NVML_AVAILABLE', False)
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
        assert mapping['net_total_down'] == 'computed:net_total_down'
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
