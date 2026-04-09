"""Shared sensor enumerator base — concrete logic reused by all platforms.

Platform subclasses override discover(), _poll_platform(), and
_build_mapping() with platform-specific sensor sources. Everything
else (polling lifecycle, computed I/O, nvidia, psutil basics, datetime,
_find_first, map_defaults caching) lives here once.

Hex-compliant: adapter layer, imports only from core/.
"""
from __future__ import annotations

import datetime
import logging
import threading
import time
from typing import Any, Optional

import psutil

from trcc.core.models import SensorInfo
from trcc.core.ports import SensorEnumerator as SensorEnumeratorABC

log = logging.getLogger(__name__)

# ── Optional: pynvml (cross-platform NVIDIA) ─────────────────────────
try:
    import pynvml  # pyright: ignore[reportMissingImports]
    pynvml.nvmlInit()
    NVML_AVAILABLE = True
except ImportError:
    pynvml = None  # type: ignore[assignment]
    NVML_AVAILABLE = False
    log.debug("pynvml not installed — NVIDIA GPU sensors unavailable")
except Exception as e:
    pynvml = None  # type: ignore[assignment]
    NVML_AVAILABLE = False
    log.warning("pynvml init failed — NVIDIA GPU sensors unavailable: %s", e)


class SensorEnumeratorBase(SensorEnumeratorABC):
    """Shared implementation for all platform sensor enumerators.

    Subclasses must implement:
        discover()          — register platform-specific sensors
        _poll_platform()    — read platform-specific sensors into readings dict
        _build_mapping()    — return platform-specific metric→sensor_id dict

    Subclasses call super helpers from discover():
        _discover_psutil_base()  — CPU/mem/disk/net sensor registration
        _discover_nvidia()       — pynvml GPU probe
        _discover_computed()     — datetime sensor registration

    Subclasses call super helpers from their _poll_once() override or
    rely on the default _poll_once() which calls _poll_platform():
        _poll_psutil_base()      — cpu_percent, cpu_freq, mem readings
        _poll_nvidia()           — pynvml GPU readings
        _poll_computed_io()      — disk/net rate deltas
        _poll_datetime()         — date/time readings
    """

    def __init__(self) -> None:
        self._sensors: list[SensorInfo] = []
        self._readings: dict[str, float] = {}
        self._lock = threading.Lock()
        self._poll_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._poll_interval: float = 2.0
        self._default_map: Optional[dict[str, str]] = None
        # I/O rate tracking (delta-based)
        self._disk_prev: Optional[tuple[Any, float]] = None
        self._net_prev: Optional[tuple[Any, float]] = None
        # cpu_percent bootstrap: first call uses short interval
        self._cpu_pct_bootstrapped: bool = False
        # nvidia handles (populated by _discover_nvidia)
        self._nvidia_handles: dict[int, object] = {}

    # ══════════════════════════════════════════════════════════════════
    # ABC implementation — concrete shared methods
    # ══════════════════════════════════════════════════════════════════

    def get_sensors(self) -> list[SensorInfo]:
        return self._sensors

    def get_by_category(self, category: str) -> list[SensorInfo]:
        return [s for s in self._sensors if s.category == category]

    def read_all(self) -> dict[str, float]:
        """Return current readings, bootstrapping on first call."""
        with self._lock:
            empty = not self._readings
        if empty:
            self._poll_once()
        with self._lock:
            return dict(self._readings)

    def read_one(self, sensor_id: str) -> Optional[float]:
        with self._lock:
            return self._readings.get(sensor_id)

    def set_poll_interval(self, seconds: float) -> None:
        self._poll_interval = max(0.5, seconds)

    def start_polling(self, interval: float = 2.0) -> None:
        if self._poll_thread and self._poll_thread.is_alive():
            return
        self._stop_event.clear()

        def _loop() -> None:
            while not self._stop_event.is_set():
                self._poll_once()
                self._stop_event.wait(self._poll_interval)

        self._poll_thread = threading.Thread(
            target=_loop, daemon=True, name="sensor-poll",
        )
        self._poll_thread.start()
        log.debug("sensor polling started (interval=%.1fs)", self._poll_interval)

    def stop_polling(self) -> None:
        self._stop_event.set()
        if self._poll_thread:
            self._poll_thread.join(timeout=3)
            self._poll_thread = None
        self._on_stop()

    def _on_stop(self) -> None:
        """Hook for subclass cleanup on stop (e.g. LHM close)."""

    def map_defaults(self) -> dict[str, str]:
        if self._default_map is not None:
            return self._default_map
        mapping = self._build_mapping()
        self._default_map = {k: v for k, v in mapping.items() if v}
        return self._default_map

    # ══════════════════════════════════════════════════════════════════
    # Abstract — subclasses must implement
    # ══════════════════════════════════════════════════════════════════

    # discover() is inherited from ABC — subclasses implement it and
    # call the _discover_* helpers below.

    def _poll_platform(self, readings: dict[str, float]) -> None:
        """Read platform-specific sensors into readings dict.

        Override in subclass. Called by the default _poll_once().
        """

    def _build_mapping(self) -> dict[str, str]:
        """Build metric_key→sensor_id mapping with platform-specific priorities.

        Override in subclass. Called by map_defaults().
        """
        return {}

    # ══════════════════════════════════════════════════════════════════
    # Default _poll_once — subclasses can override for custom flow
    # ══════════════════════════════════════════════════════════════════

    def _poll_once(self) -> None:
        """Read all sensors once and update cached readings."""
        readings: dict[str, float] = {}
        self._poll_psutil_base(readings)
        self._poll_computed_io(readings)
        self._poll_platform(readings)
        self._poll_nvidia(readings)
        self._poll_datetime(readings)
        with self._lock:
            self._readings = readings

    # ══════════════════════════════════════════════════════════════════
    # Discovery helpers — call from subclass discover()
    # ══════════════════════════════════════════════════════════════════

    def _discover_psutil_base(self) -> None:
        """Register cross-platform psutil sensors (CPU, memory, disk, net)."""
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

    def _discover_nvidia(self) -> None:
        """Probe NVIDIA GPUs via pynvml and register sensors."""
        if not NVML_AVAILABLE or pynvml is None:
            return
        try:
            count = pynvml.nvmlDeviceGetCount()
            for i in range(count):
                try:
                    handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                    name = pynvml.nvmlDeviceGetName(handle)
                    if isinstance(name, bytes):
                        name = name.decode()
                    name = str(name)
                except Exception:
                    log.debug("nvidia:%d handle/name failed", i)
                    continue

                self._nvidia_handles[i] = handle
                prefix = f'nvidia:{i}'
                label = name if count == 1 else f'GPU {i} ({name})'
                self._sensors.extend([
                    SensorInfo(f'{prefix}:temp', f'{label} Temp', 'temperature', '°C', 'nvidia'),
                    SensorInfo(f'{prefix}:gpu_busy', f'{label} Usage', 'gpu_busy', '%', 'nvidia'),
                    SensorInfo(f'{prefix}:clock', f'{label} Clock', 'clock', 'MHz', 'nvidia'),
                    SensorInfo(f'{prefix}:power', f'{label} Power', 'power', 'W', 'nvidia'),
                    SensorInfo(f'{prefix}:fan', f'{label} Fan', 'fan', '%', 'nvidia'),
                    SensorInfo(f'{prefix}:mem_used', f'{label} VRAM Used', 'gpu_memory', 'MB', 'nvidia'),
                    SensorInfo(f'{prefix}:mem_total', f'{label} VRAM Total', 'gpu_memory', 'MB', 'nvidia'),
                ])
        except Exception:
            log.debug("NVIDIA GPU discovery failed")

    def _discover_computed(self) -> None:
        """Register date/time computed sensors."""
        for metric in ('date_year', 'date_month', 'date_day',
                       'time_hour', 'time_minute', 'time_second',
                       'day_of_week'):
            self._sensors.append(
                SensorInfo(f'computed:{metric}', metric, 'datetime', '', 'computed'),
            )

    # ══════════════════════════════════════════════════════════════════
    # Polling helpers — call from subclass _poll_once() or default
    # ══════════════════════════════════════════════════════════════════

    def _poll_psutil_base(self, readings: dict[str, float]) -> None:
        """Read cross-platform psutil sensors (CPU, memory)."""
        if not self._cpu_pct_bootstrapped:
            readings['psutil:cpu_percent'] = psutil.cpu_percent(interval=0.08)
            self._cpu_pct_bootstrapped = True
        else:
            readings['psutil:cpu_percent'] = psutil.cpu_percent(interval=None)
        if (freq := psutil.cpu_freq()):
            readings['psutil:cpu_freq'] = freq.current
        mem = psutil.virtual_memory()
        readings['psutil:mem_used'] = mem.used / (1024 * 1024)
        readings['psutil:mem_available'] = mem.available / (1024 * 1024)
        readings['psutil:mem_total'] = mem.total / (1024 * 1024)
        readings['psutil:mem_percent'] = mem.percent

    def _poll_nvidia(self, readings: dict[str, float]) -> None:
        """Read NVIDIA GPU sensors via pynvml."""
        if not NVML_AVAILABLE or pynvml is None:
            return
        for i, handle in self._nvidia_handles.items():
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
                readings[f'{prefix}:clock'] = float(
                    pynvml.nvmlDeviceGetClockInfo(
                        handle, pynvml.NVML_CLOCK_GRAPHICS))
            except Exception:
                pass
            try:
                readings[f'{prefix}:power'] = (
                    pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0)
            except Exception:
                pass
            try:
                readings[f'{prefix}:fan'] = float(
                    pynvml.nvmlDeviceGetFanSpeed(handle))
            except Exception:
                pass
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                readings[f'{prefix}:mem_used'] = float(mem.used) / (1024 * 1024)
                readings[f'{prefix}:mem_total'] = float(mem.total) / (1024 * 1024)
            except Exception:
                pass

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
                    readings['computed:disk_read'] = (
                        (disk.read_bytes - prev_disk.read_bytes) / (dt * 1024 * 1024))
                    readings['computed:disk_write'] = (
                        (disk.write_bytes - prev_disk.write_bytes) / (dt * 1024 * 1024))
                    if hasattr(disk, 'busy_time') and hasattr(prev_disk, 'busy_time'):
                        busy_ms = disk.busy_time - prev_disk.busy_time
                        readings['computed:disk_activity'] = min(100.0, busy_ms / (dt * 10))
            if disk:
                self._disk_prev = (disk, now)
        except Exception:
            log.debug("computed disk I/O failed", exc_info=True)

        # Network I/O totals + rates
        try:
            if (net := psutil.net_io_counters()):
                readings['computed:net_total_up'] = net.bytes_sent / (1024 * 1024)
                readings['computed:net_total_down'] = net.bytes_recv / (1024 * 1024)
                if self._net_prev:
                    prev_net, prev_time = self._net_prev
                    dt = now - prev_time
                    if dt > 0:
                        readings['computed:net_up'] = (
                            (net.bytes_sent - prev_net.bytes_sent) / (dt * 1024))
                        readings['computed:net_down'] = (
                            (net.bytes_recv - prev_net.bytes_recv) / (dt * 1024))
                self._net_prev = (net, now)
        except Exception:
            log.debug("computed network I/O failed", exc_info=True)

    def _poll_datetime(self, readings: dict[str, float]) -> None:
        """Add date/time readings."""
        now = datetime.datetime.now()
        readings['computed:date_year'] = float(now.year)
        readings['computed:date_month'] = float(now.month)
        readings['computed:date_day'] = float(now.day)
        readings['computed:time_hour'] = float(now.hour)
        readings['computed:time_minute'] = float(now.minute)
        readings['computed:time_second'] = float(now.second)
        readings['computed:day_of_week'] = float(now.weekday())

    # ══════════════════════════════════════════════════════════════════
    # Mapping helpers — used by subclass _build_mapping()
    # ══════════════════════════════════════════════════════════════════

    @staticmethod
    def _find_first(
        sensors: list[SensorInfo],
        source: str = '',
        name_contains: str = '',
        category: str = '',
    ) -> str:
        """Find first sensor matching criteria. Returns sensor ID or ''."""
        for s in sensors:
            if source and s.source != source:
                continue
            if category and s.category != category:
                continue
            if name_contains and name_contains.lower() not in s.name.lower():
                continue
            return s.id
        return ''

    def _map_common(self, mapping: dict[str, str]) -> None:
        """Fill mapping entries shared across all platforms."""
        mapping['cpu_percent'] = 'psutil:cpu_percent'
        mapping['cpu_freq'] = 'psutil:cpu_freq'
        mapping['mem_percent'] = 'psutil:mem_percent'
        mapping['mem_available'] = 'psutil:mem_available'
        mapping['disk_read'] = 'computed:disk_read'
        mapping['disk_write'] = 'computed:disk_write'
        mapping['disk_activity'] = 'computed:disk_activity'
        mapping['net_up'] = 'computed:net_up'
        mapping['net_down'] = 'computed:net_down'
        mapping['net_total_up'] = 'computed:net_total_up'
        mapping['net_total_down'] = 'computed:net_total_down'

    def _map_fans(self, mapping: dict[str, str],
                  fan_sources: tuple[str, ...] = ('nvidia',)) -> None:
        """Map fan sensors by keyword matching, then positional fill."""
        sensors = self._sensors
        fan_sensors = [s for s in sensors
                       if s.category == 'fan' and s.source in fan_sources]
        _fan_slots = [
            ('fan_cpu', ('cpu',)),
            ('fan_gpu', ('gpu',)),
            ('fan_ssd', ('ssd', 'nvme', 'm.2')),
            ('fan_sys2', ('sys', 'chassis', 'case', 'pump')),
        ]
        fan_mapped: dict[str, str] = {}
        unmatched: list[SensorInfo] = []
        for sensor in fan_sensors:
            name_lower = sensor.name.lower()
            matched = False
            for key, keywords in _fan_slots:
                if key not in fan_mapped and any(kw in name_lower for kw in keywords):
                    fan_mapped[key] = sensor.id
                    matched = True
                    break
            if not matched:
                unmatched.append(sensor)
        empty_keys = [k for k, _ in _fan_slots if k not in fan_mapped]
        for sensor, key in zip(unmatched, empty_keys):
            fan_mapped[key] = sensor.id
        mapping.update(fan_mapped)
