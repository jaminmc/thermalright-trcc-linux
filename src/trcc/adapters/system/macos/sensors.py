"""macOS hardware sensor discovery and reading.

Platform-specific sources:
- IOKit SMC: CPU/GPU temp, fan speed (Intel Macs)
- powermetrics: thermal sensors, GPU usage/power (Apple Silicon)
- psutil: CPU usage/frequency, memory, disk I/O, network I/O
- pynvml: NVIDIA GPU (rare on Mac, eGPU only)

Sensor IDs follow the same format as Linux for compatibility:
    smc:{key}              e.g., smc:TC0P (CPU temp)
    iokit:{sensor}         e.g., iokit:cpu_die (Apple Silicon)
    psutil:{metric}        e.g., psutil:cpu_percent
    nvidia:{gpu}:{metric}  e.g., nvidia:0:temp
    computed:{metric}      e.g., computed:disk_read
"""
from __future__ import annotations

import ctypes
import ctypes.util
import logging
import platform
import re
import struct
import subprocess
from typing import Any

import psutil

from trcc.adapters.system._base import SensorEnumeratorBase
from trcc.core.models import SensorInfo

log = logging.getLogger(__name__)

# Detect Apple Silicon vs Intel
IS_APPLE_SILICON = platform.machine() == 'arm64'

# ── IOKit framework bindings ─────────────────────────────────────────

_iokit_path = ctypes.util.find_library('IOKit')
_cf_path = ctypes.util.find_library('CoreFoundation')
_iokit = ctypes.cdll.LoadLibrary(_iokit_path) if _iokit_path else None
_cf = ctypes.cdll.LoadLibrary(_cf_path) if _cf_path else None

# SMC keys for Intel Macs
_SMC_KEYS: dict[str, tuple[str, str, str]] = {
    'TC0P': ('CPU Proximity', 'temperature', '°C'),
    'TC0D': ('CPU Die', 'temperature', '°C'),
    'TC0E': ('CPU Core 0', 'temperature', '°C'),
    'TC1C': ('CPU Core 1', 'temperature', '°C'),
    'TC2C': ('CPU Core 2', 'temperature', '°C'),
    'TC3C': ('CPU Core 3', 'temperature', '°C'),
    'TG0P': ('GPU Proximity', 'temperature', '°C'),
    'TG0D': ('GPU Die', 'temperature', '°C'),
    'Tm0P': ('Memory Proximity', 'temperature', '°C'),
    'TN0P': ('Northbridge', 'temperature', '°C'),
    'TB0T': ('Battery', 'temperature', '°C'),
    'F0Ac': ('Fan 0 Speed', 'fan', 'RPM'),
    'F1Ac': ('Fan 1 Speed', 'fan', 'RPM'),
    'F2Ac': ('Fan 2 Speed', 'fan', 'RPM'),
}

# ── SMC structures for Intel Macs ────────────────────────────────────

KERNEL_INDEX_SMC = 2


class SMCKeyData_vers_t(ctypes.Structure):
    _fields_ = [
        ('major', ctypes.c_uint8),
        ('minor', ctypes.c_uint8),
        ('build', ctypes.c_uint8),
        ('reserved', ctypes.c_uint8),
        ('release', ctypes.c_uint16),
    ]


class SMCKeyData_pLimitData_t(ctypes.Structure):
    _fields_ = [
        ('version', ctypes.c_uint16),
        ('length', ctypes.c_uint16),
        ('cpuPLimit', ctypes.c_uint32),
        ('gpuPLimit', ctypes.c_uint32),
        ('memPLimit', ctypes.c_uint32),
    ]


class SMCKeyData_keyInfo_t(ctypes.Structure):
    _fields_ = [
        ('dataSize', ctypes.c_uint32),
        ('dataType', ctypes.c_uint32),
        ('dataAttributes', ctypes.c_uint8),
    ]


class SMCKeyData_t(ctypes.Structure):
    _fields_ = [
        ('key', ctypes.c_uint32),
        ('vers', SMCKeyData_vers_t),
        ('pLimitData', SMCKeyData_pLimitData_t),
        ('keyInfo', SMCKeyData_keyInfo_t),
        ('result', ctypes.c_uint8),
        ('status', ctypes.c_uint8),
        ('data8', ctypes.c_uint8),
        ('data32', ctypes.c_uint32),
        ('bytes', ctypes.c_uint8 * 32),
    ]


def _smc_key_to_int(key: str) -> int:
    """Convert 4-char SMC key to uint32."""
    return struct.unpack('>I', key.encode('ascii'))[0]


class MacOSSensorEnumerator(SensorEnumeratorBase):
    """Discovers and reads hardware sensors on macOS.

    Intel Macs: reads SMC via IOKit for CPU/GPU temp and fan speed.
    Apple Silicon: reads powermetrics for thermal/GPU sensors.
    """

    def __init__(self) -> None:
        super().__init__()
        self._smc_conn: Any = None

    def discover(self) -> list[SensorInfo]:
        self._sensors.clear()
        self._discover_psutil_base()
        if IS_APPLE_SILICON:
            self._discover_apple_silicon()
        else:
            self._discover_smc()
        self._discover_nvidia()
        self._discover_computed()
        log.info("macOS sensor discovery: %d sensors", len(self._sensors))
        return self._sensors

    # ── macOS-specific discovery ──────────────────────────────────────

    def _discover_smc(self) -> None:
        """Discover Intel Mac sensors via SMC."""
        if _iokit is None:
            log.debug("IOKit not available")
            return
        for key, (name, category, unit) in _SMC_KEYS.items():
            val = self._read_smc_key(key)
            if val is not None and val > 0:
                self._sensors.append(
                    SensorInfo(f'smc:{key}', name, category, unit, 'smc'),
                )

    def _discover_apple_silicon(self) -> None:
        """Discover Apple Silicon thermal + GPU sensors."""
        common_sensors = [
            ('iokit:cpu_die', 'CPU Die', 'temperature', '°C'),
            ('iokit:gpu_die', 'GPU Die', 'temperature', '°C'),
            ('iokit:soc', 'SoC', 'temperature', '°C'),
            ('iokit:gpu_busy', 'GPU Usage', 'gpu_busy', '%'),
            ('iokit:gpu_clock', 'GPU Clock', 'clock', 'MHz'),
            ('iokit:gpu_power', 'GPU Power', 'power', 'W'),
            ('iokit:fan0', 'Fan 0', 'fan', 'RPM'),
            ('iokit:fan1', 'Fan 1', 'fan', 'RPM'),
            ('iokit:fan2', 'Fan 2', 'fan', 'RPM'),
            ('iokit:fan3', 'Fan 3', 'fan', 'RPM'),
        ]
        for sid, name, category, unit in common_sensors:
            self._sensors.append(
                SensorInfo(sid, name, category, unit, 'iokit'),
            )

    # ── macOS-specific polling ────────────────────────────────────────

    def _poll_once(self) -> None:
        """macOS poll: base psutil + platform-specific + shared I/O."""
        readings: dict[str, float] = {}
        self._poll_psutil_base(readings)
        readings['computed:disk_percent'] = self._poll_apfs_disk_percent()
        self._poll_computed_io(readings)

        if IS_APPLE_SILICON:
            self._poll_apple_silicon(readings)
        else:
            self._poll_smc(readings)

        self._poll_nvidia(readings)
        self._poll_datetime(readings)

        with self._lock:
            self._readings = readings

    def _poll_smc(self, readings: dict[str, float]) -> None:
        """Read SMC sensors on Intel Mac."""
        for sensor in self._sensors:
            if sensor.source != 'smc':
                continue
            key = sensor.id.split(':', 1)[1]
            val = self._read_smc_key(key)
            if val is not None:
                readings[sensor.id] = val

    def _poll_apple_silicon(self, readings: dict[str, float]) -> None:
        """Read thermal/GPU sensors on Apple Silicon via powermetrics."""
        try:
            result = subprocess.run(
                ['powermetrics', '--samplers', 'smc,gpu_power',
                 '-n', '1', '-i', '100'],
                capture_output=True, text=True, timeout=5,
            )
            fan_index = 0
            cpu_core_freqs: list[float] = []
            for line in result.stdout.splitlines():
                line = line.strip()
                lo = line.lower()

                # Temperatures
                if re.search(r'\bcpu\s+(?:die\s+)?(?:temperature|temp)\b', lo):
                    readings['iokit:cpu_die'] = _parse_metric(line)
                elif re.search(r'\bgpu\s+die\s+(?:temperature|temp)\b', lo):
                    readings['iokit:gpu_die'] = _parse_metric(line)
                elif re.search(
                    r'\b(?:soc|system\s+on\s+chip)\s+(?:temperature|temp)\b', lo,
                ):
                    readings['iokit:soc'] = _parse_metric(line)

                # Fans
                elif 'fan' in lo and 'rpm' in lo:
                    readings[f'iokit:fan{fan_index}'] = _parse_metric(line)
                    fan_index += 1

                # GPU usage
                elif (
                    'iokit:gpu_busy' not in readings
                    and 'gpu' in lo
                    and any(kw in lo for kw in (
                        'active residency', 'usage', 'utilization', 'busy',
                    ))
                ):
                    m = re.search(r'([\d.]+)\s*%', line)
                    if m:
                        v = float(m.group(1))
                        if 0.0 <= v <= 100.0:
                            readings['iokit:gpu_busy'] = v

                # GPU power
                elif (
                    'iokit:gpu_power' not in readings
                    and 'gpu' in lo
                    and 'power' in lo
                ):
                    mw = re.search(r'([\d.]+)\s*mW', line, re.IGNORECASE)
                    w = re.search(r'([\d.]+)\s*W\b', line, re.IGNORECASE)
                    if mw:
                        readings['iokit:gpu_power'] = float(mw.group(1)) / 1000.0
                    elif w:
                        readings['iokit:gpu_power'] = float(w.group(1))

                # GPU clock
                elif (
                    'iokit:gpu_clock' not in readings
                    and 'gpu' in lo
                    and 'mhz' in lo
                ):
                    m = re.search(r'([\d.]+)\s*MHz', line, re.IGNORECASE)
                    if m and 100.0 <= float(m.group(1)) <= 4000.0:
                        readings['iokit:gpu_clock'] = float(m.group(1))

                # Per-core CPU frequency
                else:
                    m = re.match(
                        r'cpu\s+\d+\s+frequency:\s*([\d.]+)\s*mhz', lo,
                    )
                    if m:
                        v = float(m.group(1))
                        if 1.0 <= v <= 8000.0:
                            cpu_core_freqs.append(v)

            if cpu_core_freqs:
                readings['psutil:cpu_freq'] = max(cpu_core_freqs)

        except Exception:
            log.debug("powermetrics failed (needs root)", exc_info=True)

    def _poll_apfs_disk_percent(self) -> float:
        """Read APFS container disk usage via diskutil."""
        try:
            result = subprocess.run(
                ['diskutil', 'apfs', 'list'],
                capture_output=True, text=True, timeout=5,
            )
            capacity = 0
            in_use = 0
            for line in result.stdout.splitlines():
                if 'Size (Capacity Ceiling)' in line:
                    m = re.search(r'(\d+)\s+B', line)
                    if m:
                        capacity = int(m.group(1))
                elif 'Capacity In Use By Volumes' in line:
                    m = re.search(r'(\d+)\s+B', line)
                    if m:
                        in_use = int(m.group(1))
            if capacity > 0:
                return round(in_use / capacity * 100, 1)
        except Exception:
            log.debug("diskutil apfs list failed", exc_info=True)
        return psutil.disk_usage('/').percent

    def _read_smc_key(self, key: str) -> float | None:
        """Read a single SMC key value (Intel Macs only)."""
        if _iokit is None:
            return None
        try:
            result = subprocess.run(
                ['powermetrics', '--samplers', 'smc', '-n', '1', '-i', '100'],
                capture_output=True, text=True, timeout=5,
            )
            if not (key_info := _SMC_KEYS.get(key)):
                return None
            name = key_info[0]
            for line in result.stdout.splitlines():
                if name.lower() in line.lower():
                    return _parse_metric(line)
        except Exception:
            pass
        return None

    # ── macOS-specific mapping ────────────────────────────────────────

    def _build_mapping(self) -> dict[str, str]:
        sensors = self._sensors
        _ff = self._find_first
        mapping: dict[str, str] = {}
        self._map_common(mapping)

        # CPU
        mapping['cpu_temp'] = (
            _ff(sensors, source='smc', name_contains='CPU', category='temperature')
            or _ff(sensors, source='iokit', name_contains='cpu', category='temperature')
        )

        # GPU
        mapping['gpu_temp'] = (
            _ff(sensors, source='smc', name_contains='GPU', category='temperature')
            or _ff(sensors, source='iokit', name_contains='gpu', category='temperature')
            or _ff(sensors, source='nvidia', category='temperature')
        )
        mapping['gpu_usage'] = (
            _ff(sensors, source='nvidia', category='gpu_busy')
            or _ff(sensors, source='iokit', category='gpu_busy')
        )
        mapping['gpu_clock'] = _ff(sensors, source='iokit', category='clock')
        mapping['gpu_power'] = (
            _ff(sensors, source='nvidia', category='power')
            or _ff(sensors, source='iokit', category='power')
        )

        # Memory
        mapping['mem_temp'] = (
            _ff(sensors, source='smc', name_contains='Memory', category='temperature')
            or _ff(sensors, source='iokit', name_contains='SoC', category='temperature')
        )

        # Fans
        self._map_fans(mapping, fan_sources=('smc', 'iokit', 'nvidia'))

        return mapping


def _parse_metric(line: str) -> float:
    """Extract numeric value from powermetrics output line."""
    match = re.search(r'([\d.]+)', line.split(':')[-1])
    if match:
        return float(match.group(1))
    return 0.0
