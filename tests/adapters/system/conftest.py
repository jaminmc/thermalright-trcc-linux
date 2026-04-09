"""Shared fixtures and tests for platform sensor enumerator base class."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from trcc.core.models import SensorInfo

# Patch target for shared base class (NVML_AVAILABLE, pynvml, psutil, time, datetime)
BASE = 'trcc.adapters.system._base'


@pytest.fixture
def base_enum():
    """Create a base enumerator (via BSD — lightest subclass) for shared tests."""
    with patch(f'{BASE}.NVML_AVAILABLE', False):
        from trcc.adapters.system.bsd.sensors import BSDSensorEnumerator
        return BSDSensorEnumerator()


class TestBaseDiscoverPsutil:
    """_discover_psutil_base — tested once, covers all platforms."""

    def test_registers_cpu_memory_disk_net(self, base_enum):
        base_enum._discover_psutil_base()
        ids = [s.id for s in base_enum._sensors]
        assert 'psutil:cpu_percent' in ids
        assert 'psutil:cpu_freq' in ids
        assert 'psutil:mem_used' in ids
        assert 'psutil:mem_available' in ids
        assert 'psutil:mem_total' in ids
        assert 'psutil:mem_percent' in ids
        assert 'computed:disk_percent' in ids
        assert 'computed:disk_read' in ids
        assert 'computed:disk_write' in ids
        assert 'computed:disk_activity' in ids
        assert 'computed:net_up' in ids
        assert 'computed:net_down' in ids
        assert 'computed:net_total_up' in ids
        assert 'computed:net_total_down' in ids

    def test_all_have_source(self, base_enum):
        base_enum._discover_psutil_base()
        for s in base_enum._sensors:
            assert s.source in ('psutil', 'computed')


class TestBaseDiscoverComputed:
    """_discover_computed — datetime sensors, tested once."""

    def test_datetime_sensors(self, base_enum):
        base_enum._discover_computed()
        ids = [s.id for s in base_enum._sensors]
        assert 'computed:date_year' in ids
        assert 'computed:day_of_week' in ids
        assert len(base_enum._sensors) == 7


class TestBaseDiscoverNvidia:
    """_discover_nvidia — tested once, covers all platforms."""

    @patch(f'{BASE}.pynvml', None)
    @patch(f'{BASE}.NVML_AVAILABLE', False)
    def test_noop_without_nvml(self, base_enum):
        base_enum._discover_nvidia()
        assert base_enum._sensors == []

    @patch(f'{BASE}.NVML_AVAILABLE', True)
    @patch(f'{BASE}.pynvml')
    def test_discovers_gpu(self, mock_nvml, base_enum):
        mock_nvml.nvmlDeviceGetCount.return_value = 1
        mock_nvml.nvmlDeviceGetHandleByIndex.return_value = 'h'
        mock_nvml.nvmlDeviceGetName.return_value = 'RTX 4090'

        base_enum._discover_nvidia()
        ids = [s.id for s in base_enum._sensors]
        assert 'nvidia:0:temp' in ids
        assert 'nvidia:0:gpu_busy' in ids
        assert 'nvidia:0:power' in ids
        assert 'nvidia:0:fan' in ids
        assert 'nvidia:0:mem_used' in ids
        assert 'nvidia:0:mem_total' in ids
        assert len(base_enum._sensors) == 7


class TestBasePollNvidia:
    """_poll_nvidia — tested once, covers all platforms."""

    @patch(f'{BASE}.pynvml')
    @patch(f'{BASE}.NVML_AVAILABLE', True)
    def test_reads_gpu(self, mock_nvml, base_enum):
        mock_nvml.NVML_TEMPERATURE_GPU = 0
        mock_nvml.nvmlDeviceGetTemperature.return_value = 68
        mock_nvml.nvmlDeviceGetUtilizationRates.return_value = MagicMock(gpu=80)
        mock_nvml.nvmlDeviceGetPowerUsage.return_value = 250000
        mock_nvml.nvmlDeviceGetFanSpeed.return_value = 55
        mock_nvml.nvmlDeviceGetClockInfo.return_value = 1800
        mock_nvml.nvmlDeviceGetMemoryInfo.return_value = MagicMock(
            used=4 * 1024 ** 3, total=16 * 1024 ** 3)

        base_enum._nvidia_handles = {0: 'h'}
        readings: dict[str, float] = {}
        base_enum._poll_nvidia(readings)
        assert readings['nvidia:0:temp'] == 68.0
        assert readings['nvidia:0:gpu_busy'] == 80.0
        assert readings['nvidia:0:power'] == 250.0
        assert readings['nvidia:0:fan'] == 55.0


class TestBasePollComputedIO:
    """_poll_computed_io — tested once, covers all platforms."""

    @patch(f'{BASE}.psutil')
    @patch(f'{BASE}.time')
    def test_network_totals_first_call(self, mock_time, mock_psutil, base_enum):
        mock_time.monotonic.return_value = 100.0
        mock_psutil.disk_io_counters.return_value = None
        mock_psutil.net_io_counters.return_value = MagicMock(
            bytes_sent=10 * 1024 * 1024, bytes_recv=20 * 1024 * 1024)
        readings: dict[str, float] = {}
        base_enum._poll_computed_io(readings)
        assert readings['computed:net_total_up'] == 10.0
        assert readings['computed:net_total_down'] == 20.0
        assert 'computed:net_up' not in readings

    @patch(f'{BASE}.psutil')
    @patch(f'{BASE}.time')
    def test_disk_and_net_rates_second_call(self, mock_time, mock_psutil, base_enum):
        mock_time.monotonic.side_effect = [100.0, 102.0]
        mock_psutil.disk_io_counters.side_effect = [
            MagicMock(read_bytes=0, write_bytes=0),
            MagicMock(read_bytes=2 * 1024 * 1024, write_bytes=1 * 1024 * 1024),
        ]
        mock_psutil.net_io_counters.side_effect = [
            MagicMock(bytes_sent=0, bytes_recv=0),
            MagicMock(bytes_sent=2048, bytes_recv=4096),
        ]
        r1: dict[str, float] = {}
        base_enum._poll_computed_io(r1)
        assert 'computed:disk_read' not in r1

        r2: dict[str, float] = {}
        base_enum._poll_computed_io(r2)
        assert r2['computed:disk_read'] == 1.0
        assert r2['computed:disk_write'] == 0.5
        assert r2['computed:net_up'] == 1.0
        assert r2['computed:net_down'] == 2.0

    @patch(f'{BASE}.psutil')
    @patch(f'{BASE}.time')
    def test_disk_without_busy_time(self, mock_time, mock_psutil, base_enum):
        mock_time.monotonic.return_value = 101.0
        disk = MagicMock(
            read_bytes=10 * 1024 * 1024, write_bytes=5 * 1024 * 1024,
            spec=['read_bytes', 'write_bytes'])
        mock_psutil.disk_io_counters.return_value = disk
        mock_psutil.net_io_counters.return_value = None
        prev_disk = MagicMock(
            read_bytes=0, write_bytes=0, spec=['read_bytes', 'write_bytes'])
        base_enum._disk_prev = (prev_disk, 100.0)
        readings: dict[str, float] = {}
        base_enum._poll_computed_io(readings)
        assert 'computed:disk_read' in readings
        assert 'computed:disk_activity' not in readings

    @patch(f'{BASE}.psutil')
    @patch(f'{BASE}.time')
    def test_disk_exception(self, mock_time, mock_psutil, base_enum):
        mock_time.monotonic.return_value = 100.0
        mock_psutil.disk_io_counters.side_effect = RuntimeError
        mock_psutil.net_io_counters.return_value = None
        readings: dict[str, float] = {}
        base_enum._poll_computed_io(readings)
        assert 'computed:disk_read' not in readings

    @patch(f'{BASE}.psutil')
    @patch(f'{BASE}.time')
    def test_net_exception(self, mock_time, mock_psutil, base_enum):
        mock_time.monotonic.return_value = 100.0
        mock_psutil.disk_io_counters.return_value = None
        mock_psutil.net_io_counters.side_effect = RuntimeError
        readings: dict[str, float] = {}
        base_enum._poll_computed_io(readings)
        assert readings == {}


class TestBasePolling:
    """start_polling / stop_polling — tested once."""

    def test_start_stop(self, base_enum):
        with patch.object(base_enum, '_poll_once'):
            base_enum.start_polling(interval=0.01)
            assert base_enum._poll_thread is not None
            assert base_enum._poll_thread.is_alive()
            base_enum.stop_polling()
            assert base_enum._poll_thread is None


class TestBaseReadAll:
    """read_all bootstrap — tested once."""

    def test_returns_copy(self, base_enum):
        base_enum._readings = {'x': 1.0}
        r = base_enum.read_all()
        r['x'] = 999.0
        assert base_enum._readings['x'] == 1.0

    def test_does_not_repoll_when_populated(self, base_enum):
        base_enum._readings = {'psutil:cpu_percent': 55.0}
        with patch.object(base_enum, '_poll_once') as mock_poll:
            readings = base_enum.read_all()
        mock_poll.assert_not_called()
        assert readings['psutil:cpu_percent'] == 55.0


class TestBaseFindFirst:
    """_find_first static helper — tested once."""

    def test_finds_by_source(self):
        from trcc.adapters.system._base import SensorEnumeratorBase
        sensors = [
            SensorInfo('a', 'A', 'temperature', '°C', 'hwmon'),
            SensorInfo('b', 'B', 'temperature', '°C', 'nvidia'),
        ]
        assert SensorEnumeratorBase._find_first(sensors, source='nvidia') == 'b'

    def test_returns_empty_on_no_match(self):
        from trcc.adapters.system._base import SensorEnumeratorBase
        assert SensorEnumeratorBase._find_first([], source='nvidia') == ''

    def test_finds_by_name_and_category(self):
        from trcc.adapters.system._base import SensorEnumeratorBase
        sensors = [
            SensorInfo('a', 'CPU Die', 'temperature', '°C', 'iokit'),
            SensorInfo('b', 'GPU Die', 'temperature', '°C', 'iokit'),
        ]
        assert SensorEnumeratorBase._find_first(
            sensors, name_contains='GPU', category='temperature') == 'b'
