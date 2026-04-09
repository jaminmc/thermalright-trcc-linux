"""Tests for BSD sensor enumerator — platform-specific behavior only.

Shared base behavior (psutil, nvidia, computed I/O, polling, read_all)
is tested in tests/adapters/system/conftest.py.
"""
from __future__ import annotations

from unittest.mock import MagicMock, patch

from tests.adapters.system.conftest import BASE

MODULE = 'trcc.adapters.system.bsd.sensors'


def _make_enum(**flags):
    """Create BSDSensorEnumerator with optional feature flags."""
    with patch(f'{BASE}.NVML_AVAILABLE', flags.get('nvml', False)):
        from trcc.adapters.system.bsd.sensors import BSDSensorEnumerator
        return BSDSensorEnumerator()


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
