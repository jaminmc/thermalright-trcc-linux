"""FreeBSD hardware sensor discovery and reading.

Replaces Linux hwmon/RAPL with FreeBSD-native sensor sources:
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

import datetime
import logging
import re
import subprocess
import threading
from typing import Optional

import psutil

from trcc.core.models import SensorInfo
from trcc.core.ports import SensorEnumerator as SensorEnumeratorABC

try:
    import pynvml  # pyright: ignore[reportMissingImports]
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except Exception:
    pynvml = None  # type: ignore[assignment]
    NVML_AVAILABLE = False

log = logging.getLogger(__name__)


class BSDSensorEnumerator(SensorEnumeratorABC):
    """Discover and read hardware sensors on FreeBSD."""

    def __init__(self) -> None:
        self._sensors: list[SensorInfo] = []
        self._readings: dict[str, float] = {}
        self._lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._poll_interval: float = 1.0
        self._default_map: Optional[dict[str, str]] = None

    # ── Discovery ────────────────────────────────────────────────

    def discover(self) -> list[SensorInfo]:
        """Discover all available sensors."""
        self._sensors.clear()
        self._discover_psutil()
        self._discover_sysctl()
        if NVML_AVAILABLE:
            self._discover_nvidia()
        self._discover_computed()
        return list(self._sensors)

    def _discover_psutil(self) -> None:
        """Register psutil-based sensors (CPU, memory, disk, network)."""
        self._sensors.extend([
            SensorInfo('psutil:cpu_percent', 'CPU Usage', 'cpu', '%', 'psutil'),
            SensorInfo('psutil:cpu_freq', 'CPU Frequency', 'cpu', 'MHz', 'psutil'),
            SensorInfo('psutil:mem_used', 'Memory Used', 'memory', 'MB', 'psutil'),
            SensorInfo('psutil:mem_percent', 'Memory %', 'memory', '%', 'psutil'),
            SensorInfo('psutil:mem_total', 'Memory Total', 'memory', 'MB', 'psutil'),
            SensorInfo('computed:disk_read', 'Disk Read', 'disk', 'MB/s', 'computed'),
            SensorInfo('computed:disk_write', 'Disk Write', 'disk', 'MB/s', 'computed'),
            SensorInfo('computed:net_up', 'Network Up', 'network', 'KB/s', 'computed'),
            SensorInfo('computed:net_down', 'Network Down', 'network', 'KB/s', 'computed'),
        ])

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
                # dev.cpu.0.temperature: 45.0C
                if 'dev.cpu.' in line and '.temperature' in line:
                    match = re.match(r'dev\.cpu\.(\d+)\.temperature', line)
                    if match:
                        cpu_id = match.group(1)
                        self._sensors.append(SensorInfo(
                            f'sysctl:cpu{cpu_id}_temp',
                            f'CPU Core {cpu_id} Temp',
                            'temperature', '°C', 'sysctl',
                        ))

                # hw.acpi.thermal.tz0.temperature: 40.0C
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

    def _discover_nvidia(self) -> None:
        """Probe NVIDIA GPU via pynvml."""
        if pynvml is None:
            return
        try:
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(name, bytes):
                    name = name.decode()
                name = str(name)
                prefix = f'nvidia:{i}'
                self._sensors.extend([
                    SensorInfo(f'{prefix}:temp', f'{name} Temp', 'temperature', '°C', 'nvidia'),
                    SensorInfo(f'{prefix}:gpu_busy', f'{name} Usage', 'gpu_busy', '%', 'nvidia'),
                    SensorInfo(f'{prefix}:power', f'{name} Power', 'power', 'W', 'nvidia'),
                    SensorInfo(f'{prefix}:fan', f'{name} Fan', 'fan', '%', 'nvidia'),
                ])
        except Exception:
            log.debug("NVIDIA GPU discovery failed")

    def _discover_computed(self) -> None:
        """Register date/time computed sensors."""
        self._sensors.extend([
            SensorInfo('computed:date_year', 'Year', 'datetime', '', 'computed'),
            SensorInfo('computed:date_month', 'Month', 'datetime', '', 'computed'),
            SensorInfo('computed:date_day', 'Day', 'datetime', '', 'computed'),
            SensorInfo('computed:time_hour', 'Hour', 'datetime', '', 'computed'),
            SensorInfo('computed:time_minute', 'Minute', 'datetime', '', 'computed'),
            SensorInfo('computed:time_second', 'Second', 'datetime', '', 'computed'),
            SensorInfo('computed:day_of_week', 'Day of Week', 'datetime', '', 'computed'),
        ])

    def get_sensors(self) -> list[SensorInfo]:
        """Return previously discovered sensors."""
        return self._sensors

    def read_one(self, sensor_id: str) -> Optional[float]:
        """Read a single sensor by ID from cached readings."""
        with self._lock:
            return self._readings.get(sensor_id)

    def set_poll_interval(self, seconds: float) -> None:
        """Set background poll interval (user's data refresh setting)."""
        self._poll_interval = max(0.5, seconds)

    # ── Polling ──────────────────────────────────────────────────

    def start_polling(self, interval: float = 1.0) -> None:
        """Start background sensor polling."""
        self._stop_event.clear()
        self._poll_thread = threading.Thread(
            target=self._poll_loop, daemon=True,
        )
        self._poll_thread.start()

    def stop_polling(self) -> None:
        """Stop background polling."""
        self._stop_event.set()
        if self._poll_thread is not None:
            self._poll_thread.join(timeout=3)

    def _poll_loop(self) -> None:
        """Polling loop running in background thread."""
        while not self._stop_event.wait(self._poll_interval):
            self._poll_once()

    def _poll_once(self) -> None:
        """Read all sensors once."""
        readings: dict[str, float] = {}
        self._poll_psutil(readings)
        self._poll_sysctl(readings)
        if NVML_AVAILABLE and pynvml is not None:
            self._poll_nvidia(readings)
        self._poll_computed(readings)
        with self._lock:
            self._readings = readings

    def _poll_psutil(self, readings: dict[str, float]) -> None:
        """Read psutil sensors."""
        try:
            readings['psutil:cpu_percent'] = psutil.cpu_percent()
            freq = psutil.cpu_freq()
            if freq:
                readings['psutil:cpu_freq'] = freq.current
            mem = psutil.virtual_memory()
            readings['psutil:mem_used'] = mem.used / (1024 ** 2)
            readings['psutil:mem_percent'] = mem.percent
            readings['psutil:mem_total'] = mem.total / (1024 ** 2)
        except Exception:
            pass

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
                        r'dev\.cpu\.(\d+)\.temperature:\s*([\d.]+)',
                        line,
                    )
                    if match:
                        cpu_id = match.group(1)
                        readings[f'sysctl:cpu{cpu_id}_temp'] = float(match.group(2))

                if 'hw.acpi.thermal.tz' in line and '.temperature' in line:
                    match = re.match(
                        r'hw\.acpi\.thermal\.tz(\d+)\.temperature:\s*([\d.]+)',
                        line,
                    )
                    if match:
                        tz_id = match.group(1)
                        readings[f'sysctl:tz{tz_id}_temp'] = float(match.group(2))

        except Exception:
            pass

    def _poll_nvidia(self, readings: dict[str, float]) -> None:
        """Read NVIDIA GPU metrics."""
        if pynvml is None:
            return
        try:
            nv = pynvml  # local ref satisfies pyright
            count = nv.nvmlDeviceGetCount()
            for i in range(count):
                handle = nv.nvmlDeviceGetHandleByIndex(i)
                prefix = f'nvidia:{i}'
                readings[f'{prefix}:temp'] = float(
                    nv.nvmlDeviceGetTemperature(handle, nv.NVML_TEMPERATURE_GPU))
                readings[f'{prefix}:gpu_busy'] = float(
                    nv.nvmlDeviceGetUtilizationRates(handle).gpu)
                readings[f'{prefix}:power'] = float(
                    nv.nvmlDeviceGetPowerUsage(handle)) / 1000.0
                readings[f'{prefix}:fan'] = float(
                    nv.nvmlDeviceGetFanSpeed(handle))
        except Exception:
            pass

    def _poll_computed(self, readings: dict[str, float]) -> None:
        """Compute date/time values."""
        now = datetime.datetime.now()
        readings['computed:date_year'] = float(now.year)
        readings['computed:date_month'] = float(now.month)
        readings['computed:date_day'] = float(now.day)
        readings['computed:time_hour'] = float(now.hour)
        readings['computed:time_minute'] = float(now.minute)
        readings['computed:time_second'] = float(now.second)
        readings['computed:day_of_week'] = float(now.weekday())

    # ── Accessors ────────────────────────────────────────────────

    def read_all(self) -> dict[str, float]:
        """Return a copy of the latest readings."""
        with self._lock:
            return dict(self._readings)

    def get_by_category(self, category: str) -> list[SensorInfo]:
        """Return sensors matching a category."""
        return [s for s in self._sensors if s.category == category]

    def map_defaults(self) -> dict[str, str]:
        """Map legacy metric keys to BSD sensor IDs."""
        if self._default_map is not None:
            return self._default_map

        sensors = self.get_sensors()
        mapping: dict[str, str] = {}

        def _find_first(source: str = '', name_contains: str = '',
                        category: str = '') -> Optional[str]:
            for s in sensors:
                if source and s.source != source:
                    continue
                if category and s.category != category:
                    continue
                if name_contains and name_contains.lower() not in s.name.lower():
                    continue
                return s.id
            return None

        # CPU
        mapping['cpu_temp'] = (
            _find_first(source='sysctl', name_contains='Core 0', category='temperature')
            or _find_first(source='sysctl', category='temperature')
            or ''
        )
        mapping['cpu_percent'] = 'psutil:cpu_percent'
        mapping['cpu_freq'] = 'psutil:cpu_freq'

        # GPU (NVIDIA only on BSD)
        mapping['gpu_temp'] = _find_first(source='nvidia', category='temperature') or ''
        mapping['gpu_usage'] = _find_first(source='nvidia', category='gpu_busy') or ''
        mapping['gpu_power'] = _find_first(source='nvidia', category='power') or ''

        # Memory
        mapping['mem_percent'] = 'psutil:mem_percent'
        mapping['mem_available'] = 'psutil:mem_used'

        # Disk / Network
        mapping['disk_read'] = 'computed:disk_read'
        mapping['disk_write'] = 'computed:disk_write'
        mapping['net_up'] = 'computed:net_up'
        mapping['net_down'] = 'computed:net_down'

        self._default_map = {k: v for k, v in mapping.items() if v}
        return self._default_map
