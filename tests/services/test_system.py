"""Tests for services/system.py — system monitoring service.

Covers:
- Construction and strict DI
- Sensor discovery (lazy, cached)
- Metric reading (via enumerator, via legacy keys)
- format_metric() — all metric types
- Fallback methods — subprocess parsing
- all_metrics — aggregation with fallbacks
- find_hwmon_by_name() — sysfs lookup
- Module-level convenience API
"""
from __future__ import annotations

from datetime import datetime
from unittest.mock import MagicMock, patch

import pytest

from trcc.core.models import HardwareMetrics
from trcc.services.system import SystemService, _read_sysfs

# =========================================================================
# Construction
# =========================================================================


class TestConstruction:
    def test_strict_di(self):
        with pytest.raises(RuntimeError, match="requires"):
            SystemService()

    def test_initial_state(self):
        enum = MagicMock()
        svc = SystemService(enumerator=enum)
        assert svc._discovered is False


# =========================================================================
# Discovery
# =========================================================================


class TestDiscovery:
    def test_discover_calls_enumerator(self):
        enum = MagicMock()
        enum.discover.return_value = ['sensor1', 'sensor2']
        svc = SystemService(enumerator=enum)
        result = svc.discover()
        assert result == ['sensor1', 'sensor2']
        enum.start_polling.assert_called_once()
        assert svc._discovered is True

    def test_lazy_discovery_on_sensors_access(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.get_sensors.return_value = ['s1']
        svc = SystemService(enumerator=enum)
        _ = svc.sensors
        enum.discover.assert_called_once()

    def test_no_double_discovery(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.get_sensors.return_value = []
        svc = SystemService(enumerator=enum)
        svc.discover()
        _ = svc.sensors
        assert enum.discover.call_count == 1


# =========================================================================
# Readings
# =========================================================================


class TestReadings:
    def test_read_all(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.read_all.return_value = {'cpu_temp': 65.0}
        svc = SystemService(enumerator=enum)
        result = svc.read_all()
        assert result == {'cpu_temp': 65.0}

    def test_read_one(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.read_one.return_value = 42.0
        svc = SystemService(enumerator=enum)
        assert svc.read_one('cpu_temp') == 42.0

    def test_set_poll_interval(self):
        enum = MagicMock()
        svc = SystemService(enumerator=enum)
        svc.set_poll_interval(2.5)
        enum.set_poll_interval.assert_called_once_with(2.5)

    def test_start_stop_polling(self):
        enum = MagicMock()
        enum.discover.return_value = []
        svc = SystemService(enumerator=enum)
        svc.start_polling()
        enum.start_polling.assert_called()
        svc.stop_polling()
        enum.stop_polling.assert_called_once()


# =========================================================================
# format_metric() — static method, pure computation
# =========================================================================


class TestFormatMetric:
    def test_temp_celsius(self):
        assert SystemService.format_metric('cpu_temp', 65.3) == "65°C"

    def test_temp_fahrenheit(self):
        assert SystemService.format_metric('cpu_temp', 149.0, temp_unit=1) == "149°F"

    def test_percent(self):
        assert SystemService.format_metric('cpu_percent', 42.7) == "43%"

    def test_usage(self):
        assert SystemService.format_metric('gpu_usage', 90.0) == "90%"

    def test_activity(self):
        assert SystemService.format_metric('disk_activity', 55.0) == "55%"

    def test_freq_mhz(self):
        assert SystemService.format_metric('cpu_freq', 800.0) == "800MHz"

    def test_freq_ghz(self):
        assert SystemService.format_metric('cpu_freq', 3600.0) == "3.6GHz"

    def test_clock_ghz(self):
        assert SystemService.format_metric('gpu_clock', 2100.0) == "2.1GHz"

    def test_disk_read(self):
        assert SystemService.format_metric('disk_read', 123.4) == "123.4MB/s"

    def test_disk_write(self):
        assert SystemService.format_metric('disk_write', 0.5) == "0.5MB/s"

    def test_net_up_kb(self):
        assert SystemService.format_metric('net_up', 512.0) == "512KB/s"

    def test_net_up_mb(self):
        assert SystemService.format_metric('net_up', 2048.0) == "2.0MB/s"

    def test_net_down_kb(self):
        assert SystemService.format_metric('net_down', 100.0) == "100KB/s"

    def test_net_total_up_mb(self):
        assert SystemService.format_metric('net_total_up', 500.0) == "500MB"

    def test_net_total_up_gb(self):
        assert SystemService.format_metric('net_total_up', 2048.0) == "2.0GB"

    def test_fan_speed(self):
        assert SystemService.format_metric('fan_cpu', 1200.0) == "1200RPM"

    def test_mem_available_mb(self):
        assert SystemService.format_metric('mem_available', 512.0) == "512MB"

    def test_mem_available_gb(self):
        assert SystemService.format_metric('mem_available', 8192.0) == "8.0GB"

    def test_time_fields_padded(self):
        assert SystemService.format_metric('time_hour', 9) == "09"
        assert SystemService.format_metric('date_month', 3) == "03"

    def test_date_format(self):
        result = SystemService.format_metric('date', 0, date_format=0)
        now = datetime.now()
        assert str(now.year) in result

    def test_time_format(self):
        result = SystemService.format_metric('time', 0, time_format=0)
        assert ':' in result

    def test_weekday(self):
        result = SystemService.format_metric('weekday', 0)
        assert isinstance(result, str)
        assert len(result) > 0

    def test_day_of_week(self):
        result = SystemService.format_metric('day_of_week', 0)
        assert result == "MON"

    def test_fallback_format(self):
        assert SystemService.format_metric('unknown_metric', 3.14159) == "3.1"


# =========================================================================
# Fallback methods
# =========================================================================


class TestFallbacks:
    @patch('trcc.services.system.subprocess.run')
    def test_fallback_cpu_temp(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="coretemp-isa-0000\ntemp1_input: 65.000\n",
            returncode=0)
        enum = MagicMock()
        svc = SystemService(enumerator=enum)
        assert svc._fallback_cpu_temp() == 65.0

    @patch('trcc.services.system.subprocess.run')
    def test_fallback_cpu_temp_none(self, mock_run):
        mock_run.side_effect = FileNotFoundError
        enum = MagicMock()
        svc = SystemService(enumerator=enum)
        assert svc._fallback_cpu_temp() is None

    @patch('trcc.services.system._read_sysfs')
    def test_fallback_cpu_usage(self, mock_read):
        mock_read.return_value = "2.50 1.80 1.20 4/512 12345"
        result = SystemService._fallback_cpu_usage()
        assert result == 25.0  # 2.50 * 10, capped at 100

    @patch('trcc.services.system._read_sysfs')
    def test_fallback_cpu_usage_capped(self, mock_read):
        mock_read.return_value = "15.00 10.00 8.00 4/512 12345"
        result = SystemService._fallback_cpu_usage()
        assert result == 100.0

    @patch('builtins.open')
    def test_fallback_cpu_freq(self, mock_open):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.__iter__ = lambda s: iter([
            "processor\t: 0\n",
            "cpu MHz\t\t: 3600.000\n",
        ])
        result = SystemService._fallback_cpu_freq()
        assert result == 3600.0

    @patch('trcc.services.system.subprocess.run')
    def test_fallback_disk_temp(self, mock_run):
        # Parser finds first digit < 100 on a Temperature line.
        # Use minimal output matching what the parser actually extracts.
        mock_run.return_value = MagicMock(
            stdout="Temperature: 42\n",
            returncode=0)
        result = SystemService._fallback_disk_temp()
        assert result == 42.0

    @patch('trcc.services.system.subprocess.run')
    def test_probe_mem_clock_dmidecode(self, mock_run):
        mock_run.return_value = MagicMock(
            stdout="Memory Device\n\tConfigured Memory Speed: 3200 MT/s\n",
            returncode=0)
        result = SystemService._probe_mem_clock(
            lambda cmd, args: [cmd, *args])
        assert result == 3200.0


# =========================================================================
# all_metrics
# =========================================================================


class TestAllMetrics:
    @patch('trcc.conf.settings')
    def test_all_metrics_basic(self, mock_settings):
        mock_settings.hdd_enabled = True
        enum = MagicMock()
        enum.discover.return_value = []
        enum.map_defaults.return_value = {'cpu_temp': 'hwmon:cpu_temp'}
        enum.read_all.return_value = {'hwmon:cpu_temp': 72.0}
        svc = SystemService(enumerator=enum)
        svc._fallback_cache = {}  # Pre-populate to skip subprocess

        m = svc.all_metrics
        assert isinstance(m, HardwareMetrics)
        assert m.cpu_temp == 72  # int-truncated at read boundary

    @patch('trcc.conf.settings')
    def test_int_truncation_at_read_boundary(self, mock_settings):
        """Non-rate metrics are truncated to int (matches C# app)."""
        mock_settings.hdd_enabled = True
        enum = MagicMock()
        enum.discover.return_value = []
        enum.map_defaults.return_value = {
            'cpu_temp': 's:temp', 'cpu_percent': 's:pct',
            'disk_read': 's:dr', 'mem_available': 's:ma',
        }
        enum.read_all.return_value = {
            's:temp': 45.7, 's:pct': 42.9,
            's:dr': 0.5, 's:ma': 18534.4,
        }
        svc = SystemService(enumerator=enum)
        svc._fallback_cache = {}

        m = svc.all_metrics
        assert m.cpu_temp == 45        # int-truncated (floor)
        assert m.cpu_percent == 42     # int-truncated (floor)
        assert m.disk_read == 0.5      # float preserved (rate)
        assert m.mem_available == 18534.4  # float preserved (size)

    @patch('trcc.conf.settings')
    def test_populated_tracks_set_fields(self, mock_settings):
        """_populated contains only fields that got sensor data."""
        mock_settings.hdd_enabled = True
        enum = MagicMock()
        enum.discover.return_value = []
        enum.map_defaults.return_value = {'cpu_temp': 's:temp'}
        enum.read_all.return_value = {'s:temp': 55.0}
        svc = SystemService(enumerator=enum)
        svc._fallback_cache = {}

        m = svc.all_metrics
        assert 'cpu_temp' in m._populated
        assert 'gpu_temp' not in m._populated
        # Date/time always populated
        assert 'date' in m._populated
        assert 'time' in m._populated

    @patch('trcc.conf.settings')
    def test_hdd_disabled_zeros_disk(self, mock_settings):
        mock_settings.hdd_enabled = False
        enum = MagicMock()
        enum.discover.return_value = []
        enum.map_defaults.return_value = {
            'disk_temp': 's1',
            'disk_activity': 's2',
        }
        enum.read_all.return_value = {'s1': 45.0, 's2': 80.0}
        svc = SystemService(enumerator=enum)
        svc._fallback_cache = {}

        m = svc.all_metrics
        assert m.disk_temp == 0.0
        assert m.disk_activity == 0.0

    @patch('trcc.conf.settings')
    def test_fallback_cache_computed_once(self, mock_settings):
        mock_settings.hdd_enabled = True
        enum = MagicMock()
        enum.discover.return_value = []
        enum.map_defaults.return_value = {}
        enum.read_all.return_value = {}
        svc = SystemService(enumerator=enum)
        svc._fallback_cache = {'cpu_temp': 55.0}

        m = svc.all_metrics
        assert m.cpu_temp == 55  # int-truncated fallback
        assert 'cpu_temp' in m._populated


# =========================================================================
# find_hwmon_by_name
# =========================================================================


class TestFindHwmon:
    @patch('trcc.services.system.os.path.exists')
    @patch('trcc.services.system._read_sysfs')
    def test_finds_matching_hwmon(self, mock_read, mock_exists):
        mock_exists.return_value = True
        mock_read.side_effect = lambda p: {
            '/sys/class/hwmon/hwmon0/name': 'acpitz',
            '/sys/class/hwmon/hwmon1/name': 'k10temp',
        }.get(p)
        result = SystemService.find_hwmon_by_name('k10temp')
        assert result == '/sys/class/hwmon/hwmon1'

    @patch('trcc.services.system.os.path.exists')
    def test_no_hwmon_base(self, mock_exists):
        mock_exists.return_value = False
        assert SystemService.find_hwmon_by_name('k10temp') is None


# =========================================================================
# _read_sysfs helper
# =========================================================================


class TestReadSysfs:
    @patch('builtins.open')
    def test_reads_file(self, mock_open):
        mock_open.return_value.__enter__ = lambda s: s
        mock_open.return_value.__exit__ = MagicMock(return_value=False)
        mock_open.return_value.read.return_value = "  42000  \n"
        assert _read_sysfs('/sys/class/hwmon/hwmon0/temp1_input') == "42000"

    def test_returns_none_on_error(self):
        assert _read_sysfs('/nonexistent/path') is None


# =========================================================================
# Metric properties
# =========================================================================


class TestMetricProperties:
    def _make_svc(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.map_defaults.return_value = {}
        enum.read_one.return_value = None
        svc = SystemService(enumerator=enum)
        return svc

    def test_disk_stats(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.read_all.return_value = {
            'computed:disk_read': 100.0,
            'computed:disk_write': 50.0,
            'computed:disk_activity': 75.0,
        }
        svc = SystemService(enumerator=enum)
        stats = svc.disk_stats
        assert stats['disk_read'] == 100.0
        assert stats['disk_write'] == 50.0

    def test_network_stats(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.read_all.return_value = {
            'computed:net_up': 1024.0,
            'computed:net_down': 512.0,
        }
        svc = SystemService(enumerator=enum)
        stats = svc.network_stats
        assert stats['net_up'] == 1024.0

    def test_fan_speeds(self):
        enum = MagicMock()
        enum.discover.return_value = []
        enum.map_defaults.return_value = {
            'fan_cpu': 'hwmon:fan1',
        }
        enum.read_all.return_value = {'hwmon:fan1': 1200.0}
        svc = SystemService(enumerator=enum)
        fans = svc.fan_speeds
        assert fans['fan_cpu'] == 1200.0
