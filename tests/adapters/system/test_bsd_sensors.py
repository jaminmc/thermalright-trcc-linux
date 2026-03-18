"""Tests for BSD sensor enumerator (mocked — runs on Linux)."""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from trcc.core.models import SensorInfo

MODULE = 'trcc.adapters.sensors.facade_bsd'


def _make_enum(**flags):
    """Create BSDSensorEnumerator with optional feature flags."""
    with patch(f'{MODULE}.NVML_AVAILABLE', flags.get('nvml', False)):
        from trcc.adapters.sensors.facade_bsd import BSDSensorEnumerator
        return BSDSensorEnumerator()


class TestDiscoverPsutil:

    def test_discovers_cpu_memory_disk_net(self):
        enum = _make_enum()
        enum._discover_psutil()
        ids = [s.id for s in enum._sensors]
        assert 'psutil:cpu_percent' in ids
        assert 'psutil:cpu_freq' in ids
        assert 'psutil:mem_used' in ids
        assert 'computed:disk_read' in ids
        assert 'computed:net_up' in ids

    def test_all_have_source(self):
        enum = _make_enum()
        enum._discover_psutil()
        for s in enum._sensors:
            assert s.source in ('psutil', 'computed')


class TestDiscoverSysctl:

    @patch(f'{MODULE}.subprocess')
    def test_discovers_cpu_temps(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            returncode=0,
            stdout='dev.cpu.0.temperature: 45.0C\ndev.cpu.1.temperature: 47.0C\n',
        )
        enum = _make_enum()
        enum._discover_sysctl()
        ids = [s.id for s in enum._sensors]
        assert 'sysctl:cpu0_temp' in ids
        assert 'sysctl:cpu1_temp' in ids
        assert all(s.source == 'sysctl' for s in enum._sensors)

    @patch(f'{MODULE}.subprocess')
    def test_discovers_acpi_thermal_zones(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            returncode=0,
            stdout='hw.acpi.thermal.tz0.temperature: 40.0C\n',
        )
        enum = _make_enum()
        enum._discover_sysctl()
        ids = [s.id for s in enum._sensors]
        assert 'sysctl:tz0_temp' in ids

    @patch(f'{MODULE}.subprocess')
    def test_handles_failure(self, mock_sub):
        mock_sub.run.side_effect = RuntimeError("no sysctl")
        enum = _make_enum()
        enum._discover_sysctl()
        assert not any(s.source == 'sysctl' for s in enum._sensors)


class TestDiscoverNvidia:

    @patch(f'{MODULE}.pynvml', None)
    @patch(f'{MODULE}.NVML_AVAILABLE', False)
    def test_noop_without_nvml(self):
        enum = _make_enum()
        enum._discover_nvidia()
        assert enum._sensors == []

    @patch(f'{MODULE}.NVML_AVAILABLE', True)
    @patch(f'{MODULE}.pynvml')
    def test_discovers_gpu(self, mock_nvml):
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


class TestPollSysctl:

    @patch(f'{MODULE}.subprocess')
    def test_reads_cpu_temps(self, mock_sub):
        mock_sub.run.return_value = MagicMock(
            returncode=0,
            stdout='dev.cpu.0.temperature: 45.0C\nhw.acpi.thermal.tz0.temperature: 38.5C\n',
        )
        enum = _make_enum()
        readings: dict[str, float] = {}
        enum._poll_sysctl(readings)
        assert readings['sysctl:cpu0_temp'] == 45.0
        assert readings['sysctl:tz0_temp'] == 38.5

    @patch(f'{MODULE}.subprocess')
    def test_handles_failure(self, mock_sub):
        mock_sub.run.side_effect = RuntimeError("sysctl failed")
        enum = _make_enum()
        readings: dict[str, float] = {}
        enum._poll_sysctl(readings)
        assert len(readings) == 0


class TestPollNvidia:

    @patch(f'{MODULE}.pynvml')
    def test_reads_gpu(self, mock_nvml):
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
            SensorInfo('a', 'A', 'temperature', '°C', 'sysctl'),
            SensorInfo('b', 'B', 'fan', 'RPM', 'sysctl'),
        ]
        assert len(enum.get_by_category('temperature')) == 1

    def test_read_all_copy(self):
        enum = _make_enum()
        enum._readings = {'x': 1.0}
        r = enum.read_all()
        r['x'] = 999.0
        assert enum._readings['x'] == 1.0
