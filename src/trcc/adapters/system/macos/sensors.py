"""macOS hardware sensor discovery and reading.

Replaces Linux hwmon/RAPL with macOS-native sensor sources:
- IOKit SMC: CPU/GPU temp, fan speed (Intel Macs)
- IOHIDEventSystemClient: thermal sensors (Apple Silicon M1/M2/M3/M4)
- psutil: CPU usage/frequency, memory, disk I/O, network I/O
- pynvml: NVIDIA GPU (rare on Mac, eGPU only)

Sensor IDs follow the same format as Linux for compatibility:
    smc:{key}              e.g., smc:TC0P (CPU temp)
    iokit:{sensor}         e.g., iokit:cpu_die_0 (Apple Silicon)
    psutil:{metric}        e.g., psutil:cpu_percent
    nvidia:{gpu}:{metric}  e.g., nvidia:0:temp
    computed:{metric}      e.g., computed:disk_read
"""
from __future__ import annotations

import ctypes
import ctypes.util
import datetime
import json
import logging
import shutil
import platform
import re
import struct
import subprocess
import threading
import time
from typing import Any, Optional

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

# Detect Apple Silicon vs Intel
IS_APPLE_SILICON = platform.machine() == 'arm64'

# ── Optional iSMC (no root) fallback ─────────────────────────────────────────

def _ismc_json_cmd() -> list[str] | None:
    """Return iSMC JSON command if available, else None."""
    exe = shutil.which('ismc')
    if not exe:
        return None
    return [exe, '-o', 'json']


def _merge_ismc_sensor_readings(readings: dict[str, float]) -> None:
    """Merge fan RPM and die temps from iSMC output (best-effort, no root)."""
    cmd = _ismc_json_cmd()
    if not cmd:
        return
    try:
        result = subprocess.run(cmd, capture_output=True, text=True, timeout=4)
    except Exception:
        log.debug("ismc failed", exc_info=True)
        return
    if result.returncode != 0 or not (result.stdout or '').strip():
        return
    try:
        doc = json.loads(result.stdout)
    except Exception:
        return
    if not isinstance(doc, dict):
        return

    # iSMC schema: Fans -> dict of fan entries with quantity/unit.
    fans = doc.get('Fans')
    if isinstance(fans, dict):
        rpms: list[float] = []
        for _, entry in fans.items():
            if not isinstance(entry, dict):
                continue
            unit = str(entry.get('unit', '')).lower()
            if 'rpm' not in unit:
                continue
            q = entry.get('quantity')
            try:
                v = float(q)
            except Exception:
                continue
            if 50.0 <= v <= 30_000.0:
                rpms.append(v)
        for i, v in enumerate(rpms[:4]):
            key = f"iokit:fan{i}"
            readings.setdefault(key, v)

    # Temperatures are usually under "Temperature". Prefer max CPU/GPU core temps.
    bucket = doc.get('Temperature')
    if isinstance(bucket, dict):
        cpu: list[float] = []
        gpu: list[float] = []
        soc: list[float] = []
        for name, entry in bucket.items():
            if not isinstance(name, str) or not isinstance(entry, dict):
                continue
            unit = str(entry.get('unit', '')).lower()
            if 'c' not in unit:
                continue
            q = entry.get('quantity')
            try:
                v = float(q)
            except Exception:
                continue
            if not (0.0 <= v <= 125.0):
                continue
            lo = name.lower()
            if 'cpu' in lo and 'gpu' not in lo:
                cpu.append(v)
            elif lo.startswith('gpu'):
                gpu.append(v)
            elif lo.startswith('pmu'):
                # Best-effort "system temp" proxy.
                soc.append(v)
        if cpu:
            readings.setdefault('iokit:cpu_die', max(cpu))
        if gpu:
            readings.setdefault('iokit:gpu_die', max(gpu))
        if soc:
            readings.setdefault('iokit:soc', max(soc))

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


class MacOSSensorEnumerator(SensorEnumeratorABC):
    """Discovers and reads hardware sensors on macOS.

    Intel Macs: reads SMC via IOKit for CPU/GPU temp and fan speed.
    Apple Silicon: reads IOHIDEventSystemClient for thermal sensors.
    """

    def __init__(self) -> None:
        self._sensors: list[SensorInfo] = []
        self._readings: dict[str, float] = {}
        self._lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._poll_interval: float = 2.0
        self._smc_conn: Any = None  # IOKit SMC connection (Intel)
        self._default_map: Optional[dict[str, str]] = None
        # psutil's first cpu_percent sample is often 0.0; bootstrap once with a short interval.
        self._cpu_pct_bootstrapped: bool = False
        # Computed I/O deltas
        self._net_prev: Optional[tuple[Any, float]] = None   # (counters, time)
        self._disk_prev: Optional[tuple[Any, float]] = None  # (counters, time)

    def discover(self) -> list[SensorInfo]:
        """Scan system for all available sensors."""
        self._sensors.clear()
        self._discover_psutil()
        if IS_APPLE_SILICON:
            self._discover_apple_silicon()
        else:
            self._discover_smc()
        if NVML_AVAILABLE:
            self._discover_nvidia()
        self._discover_computed()
        log.info("macOS sensor discovery: %d sensors", len(self._sensors))
        return self._sensors

    def get_sensors(self) -> list[SensorInfo]:
        """Return previously discovered sensors."""
        return self._sensors

    def get_by_category(self, category: str) -> list[SensorInfo]:
        """Filter sensors by category."""
        return [s for s in self._sensors if s.category == category]

    def read_all(self) -> dict[str, float]:
        """Return current readings."""
        with self._lock:
            empty = not self._readings
        # Avoid empty cache before the poll thread's first tick (CLI / short-lived use).
        if empty:
            self._poll_once()
        with self._lock:
            return dict(self._readings)

    def read_one(self, sensor_id: str) -> Optional[float]:
        """Read a single sensor by ID from cached readings."""
        with self._lock:
            return self._readings.get(sensor_id)

    def set_poll_interval(self, seconds: float) -> None:
        """Set background poll interval (user's data refresh setting)."""
        self._poll_interval = max(0.5, seconds)

    def start_polling(self, interval: float = 2.0) -> None:
        """Start background polling thread."""
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop_event.clear()

        def _poll() -> None:
            while not self._stop_event.is_set():
                self._poll_once()
                self._stop_event.wait(self._poll_interval)

        self._poll_thread = threading.Thread(
            target=_poll, daemon=True, name="mac-sensors",
        )
        self._poll_thread.start()

    def stop_polling(self) -> None:
        """Stop background polling."""
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=3)

    # ── Discovery methods ──────────────────────────────────────────

    def _discover_psutil(self) -> None:
        """Add CPU, memory, disk, network sensors via psutil."""
        self._sensors.extend([
            SensorInfo('psutil:cpu_percent', 'CPU Usage', 'cpu_percent', '%', 'psutil'),
            SensorInfo('psutil:cpu_freq', 'CPU Frequency', 'clock', 'MHz', 'psutil'),
            SensorInfo('psutil:mem_used', 'Memory Used', 'memory', 'MB', 'psutil'),
            SensorInfo('psutil:mem_available', 'Memory Available', 'memory', 'MB', 'psutil'),
            SensorInfo('psutil:mem_total', 'Memory Total', 'memory', 'MB', 'psutil'),
            SensorInfo('psutil:mem_percent', 'Memory Usage', 'memory', '%', 'psutil'),
            SensorInfo('computed:disk_percent', 'Disk Usage', 'disk_io', '%', 'computed'),
            SensorInfo('computed:disk_read', 'Disk Read', 'disk_io', 'MB/s', 'computed'),
            SensorInfo('computed:disk_write', 'Disk Write', 'disk_io', 'MB/s', 'computed'),
            SensorInfo('computed:disk_activity', 'Disk Activity', 'disk_io', '%', 'computed'),
            SensorInfo('computed:net_up', 'Network Upload', 'network_io', 'KB/s', 'computed'),
            SensorInfo('computed:net_down', 'Network Download', 'network_io', 'KB/s', 'computed'),
            SensorInfo('computed:net_total_up', 'Network Total Upload', 'network_io', 'MB', 'computed'),
            SensorInfo('computed:net_total_down', 'Network Total Download', 'network_io', 'MB', 'computed'),
        ])

    def _discover_smc(self) -> None:
        """Discover Intel Mac sensors via SMC.

        Probes known SMC keys and registers sensors for keys that
        return valid readings.
        """
        if _iokit is None:
            log.debug("IOKit not available")
            return

        for key, (name, category, unit) in _SMC_KEYS.items():
            # Try reading to verify key exists on this hardware
            val = self._read_smc_key(key)
            if val is not None and val > 0:
                self._sensors.append(
                    SensorInfo(f'smc:{key}', name, category, unit, 'smc'),
                )

    def _discover_apple_silicon(self) -> None:
        """Discover Apple Silicon thermal sensors.

        Uses IOHIDEventSystemClient to enumerate thermal sensors.
        Sensor keys vary by M-chip generation — we discover dynamically.
        """
        # Apple Silicon thermal sensors via powermetrics (requires root)
        # or IOHIDEventSystemClient (private API via ctypes).
        # For the scaffold, register common sensor slots that powermetrics
        # reports on all M-series chips.
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

    def _discover_nvidia(self) -> None:
        """Probe NVIDIA GPU via pynvml (eGPU only on Mac)."""
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
            log.debug("NVIDIA GPU probe failed")

    def _discover_computed(self) -> None:
        """Add computed/derived metrics."""
        for metric in ('date_year', 'date_month', 'date_day',
                       'time_hour', 'time_minute', 'time_second',
                       'day_of_week'):
            self._sensors.append(
                SensorInfo(f'computed:{metric}', metric, 'datetime', '', 'computed'),
            )

    # ── Reading methods ────────────────────────────────────────────

    def _poll_once(self) -> None:
        """Read all sensors once and update cached readings."""
        readings: dict[str, float] = {}

        # psutil
        try:
            if not self._cpu_pct_bootstrapped:
                readings['psutil:cpu_percent'] = psutil.cpu_percent(interval=0.08)
                self._cpu_pct_bootstrapped = True
            else:
                readings['psutil:cpu_percent'] = psutil.cpu_percent(interval=None)
        except Exception:
            readings['psutil:cpu_percent'] = 0.0
        freq = psutil.cpu_freq()
        if freq:
            readings['psutil:cpu_freq'] = freq.current
        mem = psutil.virtual_memory()
        readings['psutil:mem_used'] = mem.used / (1024 * 1024)
        readings['psutil:mem_available'] = mem.available / (1024 * 1024)
        readings['psutil:mem_total'] = mem.total / (1024 * 1024)
        readings['psutil:mem_percent'] = mem.percent
        readings['computed:disk_percent'] = self._poll_apfs_disk_percent()
        self._poll_computed_io(readings)

        # SMC (Intel) or IOKit (Apple Silicon)
        if IS_APPLE_SILICON:
            self._poll_apple_silicon(readings)
        else:
            self._poll_smc(readings)

        # NVIDIA (rare — eGPU)
        if NVML_AVAILABLE and pynvml is not None:
            self._poll_nvidia(readings)

        # Date/time
        now = datetime.datetime.now()
        readings['computed:date_year'] = float(now.year)
        readings['computed:date_month'] = float(now.month)
        readings['computed:date_day'] = float(now.day)
        readings['computed:time_hour'] = float(now.hour)
        readings['computed:time_minute'] = float(now.minute)
        readings['computed:time_second'] = float(now.second)
        readings['computed:day_of_week'] = float(now.weekday())

        with self._lock:
            self._readings = readings

    def _poll_computed_io(self, readings: dict[str, float]) -> None:
        """Compute disk/network rates + totals from psutil counter deltas."""
        now = time.monotonic()

        # Disk I/O rates
        try:
            disk = psutil.disk_io_counters()
            if disk and self._disk_prev:
                prev_disk, prev_time = self._disk_prev
                dt = now - prev_time
                if dt > 0:
                    read_bytes = disk.read_bytes - prev_disk.read_bytes
                    write_bytes = disk.write_bytes - prev_disk.write_bytes
                    readings['computed:disk_read'] = read_bytes / (dt * 1024 * 1024)
                    readings['computed:disk_write'] = write_bytes / (dt * 1024 * 1024)
                    if hasattr(disk, 'busy_time') and hasattr(prev_disk, 'busy_time'):
                        busy_ms = disk.busy_time - prev_disk.busy_time
                        readings['computed:disk_activity'] = min(100.0, busy_ms / (dt * 10))
            if disk:
                self._disk_prev = (disk, now)
        except Exception:
            log.debug("computed disk I/O failed", exc_info=True)

        # Network I/O totals + rates
        try:
            net = psutil.net_io_counters()
            if net:
                readings['computed:net_total_up'] = net.bytes_sent / (1024 * 1024)
                readings['computed:net_total_down'] = net.bytes_recv / (1024 * 1024)
                if self._net_prev:
                    prev_net, prev_time = self._net_prev
                    dt = now - prev_time
                    if dt > 0:
                        readings['computed:net_up'] = (
                            (net.bytes_sent - prev_net.bytes_sent) / (dt * 1024)
                        )
                        readings['computed:net_down'] = (
                            (net.bytes_recv - prev_net.bytes_recv) / (dt * 1024)
                        )
                self._net_prev = (net, now)
        except Exception:
            log.debug("computed network I/O failed", exc_info=True)

    def _poll_smc(self, readings: dict[str, float]) -> None:
        """Read SMC sensors on Intel Mac."""
        for sensor in self._sensors:
            if sensor.source != 'smc':
                continue
            key = sensor.id.split(':', 1)[1]  # "smc:TC0P" → "TC0P"
            val = self._read_smc_key(key)
            if val is not None:
                readings[sensor.id] = val

    def _poll_apple_silicon(self, readings: dict[str, float]) -> None:
        """Read thermal sensors on Apple Silicon.

        Uses `powermetrics` subprocess as a reliable cross-generation approach.
        Private IOHIDEventSystemClient API changes between M-chip generations,
        but powermetrics output format is stable.
        """
        # iSMC can provide fans/temps without root; merge first so we still show something
        # when powermetrics is blocked or omits fan rows.
        _merge_ismc_sensor_readings(readings)
        try:
            result = subprocess.run(
                ['powermetrics', '-A', '-n', '1', '-i', '100'],
                capture_output=True, text=True, timeout=5,
            )
            cpu_core_freqs: list[float] = []
            for line in result.stdout.splitlines():
                line = line.strip()
                lo = line.lower()
                if (
                    re.search(r'\bcpu\s+die\s+(?:temperature|temp)\b', lo)
                    or re.search(r'\bcpu\s+package\s+temperature\b', lo)
                ):
                    readings['iokit:cpu_die'] = _parse_metric(line)
                elif re.search(r'\bgpu\s+die\s+(?:temperature|temp)\b', lo):
                    readings['iokit:gpu_die'] = _parse_metric(line)
                elif re.search(r'\b(?:soc|system\s+on\s+chip)\s+(?:temperature|temp)\b', lo):
                    readings['iokit:soc'] = _parse_metric(line)
                elif 'Fan' in line and 'rpm' in line.lower():
                    readings['iokit:fan0'] = _parse_metric(line)
                else:
                    m = re.match(r'^cpu\s+\d+\s+frequency:\s*([\d.]+)\s*mhz\b', lo)
                    if m:
                        v = float(m.group(1))
                        if 1.0 <= v <= 8000.0:
                            cpu_core_freqs.append(v)
                    if 'iokit:gpu_busy' not in readings and 'gpu' in lo:
                        pct = re.search(r'([\d.]+)\s*%', line)
                        if pct and any(x in lo for x in ('usage', 'utilization', 'utilisation', 'active', 'busy', 'residency')):
                            v = float(pct.group(1))
                            if 0.0 <= v <= 100.0:
                                readings['iokit:gpu_busy'] = v
                    if 'iokit:gpu_power' not in readings and 'gpu power' in lo:
                        mw = re.search(r'([\d.]+)\s*mW', line, re.IGNORECASE)
                        w = re.search(r'([\d.]+)\s*W\b', line, re.IGNORECASE)
                        if mw:
                            readings['iokit:gpu_power'] = float(mw.group(1)) / 1000.0
                        elif w:
                            readings['iokit:gpu_power'] = float(w.group(1))
                    if 'iokit:gpu_clock' not in readings and 'gpu' in lo and 'mhz' in lo:
                        m2 = re.search(r'([\d.]+)\s*MHz', line, re.IGNORECASE)
                        if m2 and 100.0 <= float(m2.group(1)) <= 4000.0:
                            readings['iokit:gpu_clock'] = float(m2.group(1))
            if cpu_core_freqs:
                # Keep the existing metric mapping: publish powermetrics MHz via psutil slot.
                readings['psutil:cpu_freq'] = max(cpu_core_freqs)
        except Exception:
            log.debug("powermetrics failed (needs root)", exc_info=True)

    def _poll_nvidia(self, readings: dict[str, float]) -> None:
        """Read NVIDIA GPU sensors via pynvml."""
        if pynvml is None:
            return
        try:
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                prefix = f'nvidia:{i}'
                try:
                    readings[f'{prefix}:temp'] = float(
                        pynvml.nvmlDeviceGetTemperature(
                            handle, pynvml.NVML_TEMPERATURE_GPU))
                except Exception:
                    pass
                try:
                    util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                    readings[f'{prefix}:gpu_busy'] = float(util.gpu)
                except Exception:
                    pass
                try:
                    readings[f'{prefix}:power'] = (
                        float(pynvml.nvmlDeviceGetPowerUsage(handle)) / 1000.0)
                except Exception:
                    pass
                try:
                    readings[f'{prefix}:fan'] = float(
                        pynvml.nvmlDeviceGetFanSpeed(handle))
                except Exception:
                    pass
        except Exception:
            pass

    def _poll_apfs_disk_percent(self) -> float:
        """Read APFS container disk usage via diskutil.

        psutil.disk_usage('/') only reports the root snapshot volume (~3%),
        not the actual APFS container usage. `diskutil apfs list` gives real
        container-level numbers.
        """
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
        """Read a single SMC key value (Intel Macs only).

        Opens IOKit connection to AppleSMC service and reads the key.
        Returns temperature in °C or fan speed in RPM, or None on failure.
        """
        if _iokit is None:
            return None
        try:
            # This is a simplified SMC read — full implementation needs
            # IOServiceOpen + IOConnectCallStructMethod with SMC structs.
            # For now, fall back to parsing `sysctl` or `powermetrics`.
            import subprocess
            result = subprocess.run(
                ['powermetrics', '--samplers', 'smc', '-n', '1', '-i', '100'],
                capture_output=True, text=True, timeout=5,
            )
            # Parse output for the specific key's sensor name
            key_info = _SMC_KEYS.get(key)
            if not key_info:
                return None
            name = key_info[0]
            for line in result.stdout.splitlines():
                if name.lower() in line.lower():
                    return _parse_metric(line)
        except Exception:
            pass
        return None

    # ── Default sensor mapping (legacy compat) ────────────────────

    def map_defaults(self) -> dict[str, str]:
        """Map legacy metric keys to macOS sensor IDs."""
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
            _find_first(source='smc', name_contains='CPU', category='temperature')
            or _find_first(source='iokit', name_contains='cpu', category='temperature')
            or ''
        )
        mapping['cpu_percent'] = 'psutil:cpu_percent'
        mapping['cpu_freq'] = 'psutil:cpu_freq'

        # GPU
        gpu_temp = (
            _find_first(source='smc', name_contains='GPU', category='temperature')
            or _find_first(source='iokit', name_contains='gpu', category='temperature')
            or _find_first(source='nvidia', category='temperature')
        )
        mapping['gpu_temp'] = gpu_temp or ''
        mapping['gpu_usage'] = (
            _find_first(source='nvidia', category='gpu_busy')
            or _find_first(source='iokit', category='gpu_busy')
            or ''
        )
        mapping['gpu_clock'] = _find_first(source='iokit', category='clock') or ''
        mapping['gpu_power'] = (
            _find_first(source='nvidia', category='power')
            or _find_first(source='iokit', category='power')
            or ''
        )

        # Memory
        mapping['mem_temp'] = (
            _find_first(source='smc', name_contains='Memory', category='temperature')
            or _find_first(source='iokit', name_contains='soc', category='temperature')
            or ''
        )
        mapping['mem_percent'] = 'psutil:mem_percent'
        mapping['mem_available'] = 'psutil:mem_available'

        # Disk / Network
        mapping['disk_percent'] = 'computed:disk_percent'
        mapping['disk_read'] = 'computed:disk_read'
        mapping['disk_write'] = 'computed:disk_write'
        mapping['disk_activity'] = 'computed:disk_activity'
        mapping['net_up'] = 'computed:net_up'
        mapping['net_down'] = 'computed:net_down'
        mapping['net_total_up'] = 'computed:net_total_up'
        mapping['net_total_down'] = 'computed:net_total_down'

        # Fans
        fan_sensors = [s for s in sensors if s.category == 'fan']
        if fan_sensors:
            mapping['fan_cpu'] = fan_sensors[0].id
            if len(fan_sensors) > 1:
                mapping['fan_gpu'] = fan_sensors[1].id

        self._default_map = {k: v for k, v in mapping.items() if v}
        return self._default_map


def _parse_metric(line: str) -> float:
    """Extract numeric value from powermetrics output line.

    Examples:
        "CPU die temperature: 45.23 C" → 45.23
        "Fan: 1200 rpm" → 1200.0
    """
    match = re.search(r'([\d.]+)', line.split(':')[-1])
    if match:
        return float(match.group(1))
    return 0.0
