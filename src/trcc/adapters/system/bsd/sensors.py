"""FreeBSD hardware sensor discovery and reading.

Platform-specific sources:
- sysctl dev.cpu.*.temperature: Per-core CPU temp (coretemp/amdtemp modules)
- sysctl hw.acpi.thermal.tz*: ACPI thermal zones
- psutil: CPU usage/frequency, memory, disk I/O, network I/O
- pynvml: NVIDIA GPU (if present)

Sensor IDs follow the same format as Linux for compatibility:
    sysctl:{key}           e.g., sysctl:cpu0_temp
    psutil:{metric}        e.g., psutil:cpu_percent
    nvidia:{gpu}:{metric}  e.g., nvidia:0:temp
    computed:{metric}       e.g., computed:disk_read
"""
from __future__ import annotations

import logging
import re
import subprocess

from trcc.adapters.system._base import SensorEnumeratorBase
from trcc.core.models import SensorInfo

log = logging.getLogger(__name__)


class BSDSensorEnumerator(SensorEnumeratorBase):
    """Discover and read hardware sensors on FreeBSD."""

    def discover(self) -> list[SensorInfo]:
        self._sensors.clear()
        self._discover_psutil_base()
        self._discover_sysctl()
        self._discover_nvidia()
        self._discover_computed()
        return self._sensors

    # ── BSD-specific discovery ────────────────────────────────────────

    def _discover_sysctl(self) -> None:
        """Discover CPU temp sensors via sysctl dev.cpu.*.temperature."""
        try:
            result = subprocess.run(
                ['sysctl', '-a'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return

            for line in result.stdout.splitlines():
                if 'dev.cpu.' in line and '.temperature' in line:
                    match = re.match(r'dev\.cpu\.(\d+)\.temperature', line)
                    if match:
                        cpu_id = match.group(1)
                        self._sensors.append(SensorInfo(
                            f'sysctl:cpu{cpu_id}_temp',
                            f'CPU Core {cpu_id} Temp',
                            'temperature', '°C', 'sysctl',
                        ))

                if 'hw.acpi.thermal.tz' in line and '.temperature' in line:
                    match = re.match(r'hw\.acpi\.thermal\.tz(\d+)\.temperature', line)
                    if match:
                        tz_id = match.group(1)
                        self._sensors.append(SensorInfo(
                            f'sysctl:tz{tz_id}_temp',
                            f'ACPI Thermal Zone {tz_id}',
                            'temperature', '°C', 'sysctl',
                        ))

        except Exception:
            log.debug("sysctl sensor discovery failed")

    # ── BSD-specific polling ──────────────────────────────────────────

    def _poll_platform(self, readings: dict[str, float]) -> None:
        """Read BSD-specific sensors (sysctl temps)."""
        self._poll_sysctl(readings)

    def _poll_sysctl(self, readings: dict[str, float]) -> None:
        """Read CPU temps via sysctl."""
        try:
            result = subprocess.run(
                ['sysctl', '-a'],
                capture_output=True, text=True, timeout=5,
            )
            if result.returncode != 0:
                return

            for line in result.stdout.splitlines():
                if 'dev.cpu.' in line and '.temperature' in line:
                    match = re.match(
                        r'dev\.cpu\.(\d+)\.temperature:\s*([\d.]+)', line,
                    )
                    if match:
                        cpu_id = match.group(1)
                        readings[f'sysctl:cpu{cpu_id}_temp'] = float(match.group(2))

                if 'hw.acpi.thermal.tz' in line and '.temperature' in line:
                    match = re.match(
                        r'hw\.acpi\.thermal\.tz(\d+)\.temperature:\s*([\d.]+)', line,
                    )
                    if match:
                        tz_id = match.group(1)
                        readings[f'sysctl:tz{tz_id}_temp'] = float(match.group(2))

        except Exception:
            pass

    # ── BSD-specific mapping ──────────────────────────────────────────

    def _build_mapping(self) -> dict[str, str]:
        sensors = self._sensors
        _ff = self._find_first
        mapping: dict[str, str] = {}
        self._map_common(mapping)

        # CPU
        mapping['cpu_temp'] = (
            _ff(sensors, source='sysctl', name_contains='Core 0', category='temperature')
            or _ff(sensors, source='sysctl', category='temperature')
        )

        # GPU (NVIDIA only on BSD)
        mapping['gpu_temp'] = _ff(sensors, source='nvidia', category='temperature')
        mapping['gpu_usage'] = _ff(sensors, source='nvidia', category='gpu_busy')
        mapping['gpu_power'] = _ff(sensors, source='nvidia', category='power')

        # Memory
        mapping['mem_temp'] = ''

        # Fans
        self._map_fans(mapping, fan_sources=('nvidia',))

        return mapping
