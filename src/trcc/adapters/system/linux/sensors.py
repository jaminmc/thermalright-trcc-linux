"""
Linux hardware sensor discovery and reading.

Replaces Windows HWiNFO64 shared memory with native Linux sensor sources:
- hwmon: /sys/class/hwmon/* (temperatures, fans, voltages, power, frequency)
- NVIDIA GPU: nvidia-ml-py / pynvml (temperature, utilization, clock, power, VRAM, fan)
- DRM: /sys/class/drm/card* (AMD gpu_busy_percent, Intel gt_cur_freq_mhz)
- psutil: CPU usage/frequency, memory, disk I/O, network I/O
- Intel RAPL: CPU package power via /sys/class/powercap/

Sensor IDs follow the format:
    hwmon:{driver}:{input}    e.g., hwmon:coretemp:temp1
    nvidia:{gpu}:{metric}     e.g., nvidia:0:temp
    drm:{card}:{metric}       e.g., drm:card0:gpu_busy
    psutil:{metric}           e.g., psutil:cpu_percent
    rapl:{domain}             e.g., rapl:package-0
    computed:{metric}         e.g., computed:disk_read
"""

import logging
import time
from pathlib import Path
from typing import Optional

import psutil

from trcc.adapters.infra.data_repository import SysUtils
from trcc.adapters.system._base import NVML_AVAILABLE, SensorEnumeratorBase, pynvml
from trcc.core.models import SensorInfo

log = logging.getLogger(__name__)


# Maps hwmon input prefix to (category, unit)
_HWMON_TYPES = {
    'temp': ('temperature', '°C'),
    'fan': ('fan', 'RPM'),
    'in': ('voltage', 'V'),
    'power': ('power', 'W'),
    'freq': ('clock', 'MHz'),
}

# Maps hwmon input prefix to value divisor (sysfs uses millidegrees, microvolts, etc.)
_HWMON_DIVISORS = {
    'temp': 1000.0,    # millidegrees → degrees
    'fan': 1.0,        # already RPM
    'in': 1000.0,      # millivolts → volts
    'power': 1000000.0,  # microwatts → watts
    'freq': 1000000.0,  # Hz → MHz
}

# GPU vendor IDs (PCI sysfs)
_GPU_VENDOR_NVIDIA = '10de'
_GPU_VENDOR_AMD = '1002'
_GPU_VENDOR_INTEL = '8086'


def _detect_gpu_vendors() -> list[str]:
    """Detect GPU vendors via PCI sysfs, discrete first.

    Scans /sys/bus/pci/devices/*/class for VGA (0x0300) and 3D (0x0302)
    controllers, returns vendor ID strings ordered: NVIDIA > AMD > Intel.
    """
    pci_base = Path('/sys/bus/pci/devices')
    if not pci_base.exists():
        return []

    vendors: list[str] = []
    for dev_dir in pci_base.iterdir():
        class_path = dev_dir / 'class'
        vendor_path = dev_dir / 'vendor'
        if not class_path.exists() or not vendor_path.exists():
            continue
        try:
            pci_class = class_path.read_text().strip()
            if not (pci_class.startswith('0x0300') or pci_class.startswith('0x0302')):
                continue
            vendor = vendor_path.read_text().strip().removeprefix('0x')
            if vendor not in vendors:
                vendors.append(vendor)
        except OSError:
            continue

    # Prefer discrete (NVIDIA/AMD) over integrated (Intel)
    priority = {_GPU_VENDOR_NVIDIA: 0, _GPU_VENDOR_AMD: 1, _GPU_VENDOR_INTEL: 2}
    vendors.sort(key=lambda v: priority.get(v, 99))
    return vendors


class SensorEnumerator(SensorEnumeratorBase):
    """Discovers and reads all available hardware sensors on Linux."""

    def __init__(self) -> None:
        super().__init__()
        self._hwmon_paths: dict[str, str] = {}   # sensor_id -> sysfs path
        self._drm_paths: dict[str, str] = {}     # sensor_id -> drm sysfs path
        self._rapl_paths: dict[str, str] = {}    # sensor_id -> energy_uj path
        self._rapl_prev: dict[str, tuple[float, float]] = {}  # id -> (energy, time)

    def discover(self) -> list[SensorInfo]:
        self._sensors = []
        self._hwmon_paths = {}
        self._nvidia_handles = {}
        self._drm_paths = {}
        self._rapl_paths = {}

        self._discover_hwmon()
        self._discover_nvidia()
        self._discover_drm()
        self._discover_psutil()
        self._discover_rapl()
        self._discover_computed()

        return self._sensors

    # ── Linux-specific discovery ──────────────────────────────────────

    def _discover_psutil(self) -> None:
        """Register psutil sensors — base + Linux mem_available."""
        self._discover_psutil_base()
        self._sensors.append(
            SensorInfo('psutil:mem_available', 'Memory / Available', 'other', 'MB', 'psutil'),
        )

    def _discover_nvidia(self) -> None:
        """Discover NVIDIA GPUs with extended Linux-specific metrics."""
        if not NVML_AVAILABLE or pynvml is None:
            return
        try:
            count = pynvml.nvmlDeviceGetCount()
        except Exception:
            return

        for i in range(count):
            try:
                handle = pynvml.nvmlDeviceGetHandleByIndex(i)
                gpu_name = pynvml.nvmlDeviceGetName(handle)
                if isinstance(gpu_name, bytes):
                    gpu_name = gpu_name.decode()
                gpu_name = str(gpu_name)
            except Exception as e:
                log.warning("NVIDIA GPU %d handle/name failed — skipping: %s", i, e)
                continue

            self._nvidia_handles[i] = handle
            prefix = f"nvidia:{i}"
            label = gpu_name if count == 1 else f"GPU {i} ({gpu_name})"

            # Linux extended: gpu_util/mem_util/mem_clock/vram (not just gpu_busy)
            sensors = [
                ('temp', f'{label} / Temperature', 'temperature', '°C'),
                ('gpu_util', f'{label} / GPU Utilization', 'usage', '%'),
                ('mem_util', f'{label} / Memory Utilization', 'usage', '%'),
                ('clock', f'{label} / Graphics Clock', 'clock', 'MHz'),
                ('mem_clock', f'{label} / Memory Clock', 'clock', 'MHz'),
                ('power', f'{label} / Power Draw', 'power', 'W'),
                ('vram_used', f'{label} / VRAM Used', 'other', 'MB'),
                ('vram_total', f'{label} / VRAM Total', 'other', 'MB'),
                ('fan', f'{label} / Fan Speed', 'fan', '%'),
            ]
            for metric, name, cat, unit in sensors:
                self._sensors.append(SensorInfo(
                    id=f"{prefix}:{metric}", name=name,
                    category=cat, unit=unit, source='nvidia',
                ))

    def _discover_hwmon(self) -> None:
        """Discover sensors from /sys/class/hwmon/."""
        hwmon_base = Path('/sys/class/hwmon')
        if not hwmon_base.exists():
            return

        driver_counts: dict[str, int] = {}

        for hwmon_dir in sorted(hwmon_base.iterdir()):
            driver_name = SysUtils.read_sysfs(str(hwmon_dir / 'name')) or hwmon_dir.name

            driver_counts[driver_name] = driver_counts.get(driver_name, 0) + 1
            if driver_counts[driver_name] > 1:
                driver_key = f"{driver_name}.{driver_counts[driver_name] - 1}"
            else:
                driver_key = driver_name

            for input_file in sorted(hwmon_dir.glob('*_input')):
                fname = input_file.name
                input_name = fname.replace('_input', '')

                prefix = None
                for pfx in _HWMON_TYPES:
                    if input_name.startswith(pfx):
                        prefix = pfx
                        break
                if prefix is None:
                    continue

                category, unit = _HWMON_TYPES[prefix]
                label_path = hwmon_dir / f'{input_name}_label'
                if (label := SysUtils.read_sysfs(str(label_path))):
                    name = f'{driver_key} / {label}'
                else:
                    name = f'{driver_key} / {input_name}'

                sensor_id = f'hwmon:{driver_key}:{input_name}'
                self._sensors.append(SensorInfo(
                    id=sensor_id, name=name,
                    category=category, unit=unit, source='hwmon',
                ))
                self._hwmon_paths[sensor_id] = str(input_file)

    def _discover_drm(self) -> None:
        """Discover GPU sensors from /sys/class/drm/ (AMD utilization, Intel freq)."""
        drm_base = Path('/sys/class/drm')
        if not drm_base.exists():
            return

        for card_dir in sorted(drm_base.glob('card[0-9]*')):
            if '-' in card_dir.name:
                continue

            vendor_path = card_dir / 'device' / 'vendor'
            if not vendor_path.exists():
                continue
            try:
                vendor = vendor_path.read_text().strip().removeprefix('0x')
            except OSError:
                continue

            card = card_dir.name

            if vendor == _GPU_VENDOR_AMD:
                busy_path = card_dir / 'device' / 'gpu_busy_percent'
                if busy_path.exists():
                    sid = f"drm:{card}:gpu_busy"
                    self._sensors.append(SensorInfo(
                        id=sid, name=f"GPU / Utilization ({card})",
                        category='usage', unit='%', source='drm',
                    ))
                    self._drm_paths[sid] = str(busy_path)

            if vendor == _GPU_VENDOR_INTEL:
                freq_path = card_dir / 'gt_cur_freq_mhz'
                if freq_path.exists():
                    sid = f"drm:{card}:freq"
                    self._sensors.append(SensorInfo(
                        id=sid, name=f"GPU / Frequency ({card})",
                        category='clock', unit='MHz', source='drm',
                    ))
                    self._drm_paths[sid] = str(freq_path)

    def _discover_rapl(self) -> None:
        """Discover Intel RAPL power sensors."""
        rapl_base = Path('/sys/class/powercap')
        if not rapl_base.exists():
            return

        for rapl_dir in sorted(rapl_base.glob('intel-rapl:*')):
            # Only top-level domains (not sub-zones like intel-rapl:0:0)
            if ':' in rapl_dir.name.split('intel-rapl:')[1]:
                continue

            energy_path = rapl_dir / 'energy_uj'
            name_path = rapl_dir / 'name'
            if not energy_path.exists():
                continue

            domain_name = SysUtils.read_sysfs(str(name_path)) or rapl_dir.name
            sensor_id = f"rapl:{domain_name}"

            self._sensors.append(SensorInfo(
                id=sensor_id,
                name=f"RAPL / {domain_name.title()} Power",
                category='power', unit='W', source='rapl',
            ))
            self._rapl_paths[sensor_id] = str(energy_path)

    # ── Linux-specific polling ────────────────────────────────────────

    def _poll_once(self) -> None:
        """Linux-specific poll: hwmon, DRM, RAPL + shared base."""
        readings: dict[str, float] = {}

        # hwmon sensors
        for sid, path in self._hwmon_paths.items():
            if (val := SysUtils.read_sysfs(path)) is not None:
                try:
                    raw = float(val)
                    prefix = sid.split(':')[-1]
                    for pfx, div in _HWMON_DIVISORS.items():
                        if prefix.startswith(pfx):
                            readings[sid] = raw / div
                            break
                    else:
                        readings[sid] = raw
                except ValueError:
                    pass

        # NVIDIA (Linux extended metrics)
        self._poll_nvidia_linux(readings)

        # psutil
        self._poll_psutil_linux(readings)

        # RAPL power
        self._poll_rapl(readings)

        # DRM sensors (AMD/Intel GPU)
        for sid, path in self._drm_paths.items():
            if (val := SysUtils.read_sysfs(path)) is not None:
                try:
                    readings[sid] = float(val)
                except ValueError:
                    pass

        # Computed I/O rates
        self._poll_computed_io(readings)

        # Date/time
        self._poll_datetime(readings)

        with self._lock:
            self._readings = readings

    _cpu_freq_cache: float = 0.0
    _cpu_freq_time: float = 0.0
    _CPU_FREQ_TTL: float = 10.0

    def _poll_psutil_linux(self, readings: dict[str, float]) -> None:
        """Linux psutil: cpu_percent + cached cpu_freq + memory."""
        try:
            readings['psutil:cpu_percent'] = psutil.cpu_percent(interval=None)
        except Exception:
            pass
        try:
            now = time.monotonic()
            if now - self._cpu_freq_time >= self._CPU_FREQ_TTL:
                if (freq := psutil.cpu_freq()):
                    self._cpu_freq_cache = freq.current
                else:
                    self._cpu_freq_cache = 0.0
                self._cpu_freq_time = now
            if self._cpu_freq_cache > 0:
                readings['psutil:cpu_freq'] = self._cpu_freq_cache
        except Exception:
            pass
        try:
            mem = psutil.virtual_memory()
            readings['psutil:mem_percent'] = mem.percent
            readings['psutil:mem_available'] = mem.available / (1024 * 1024)
        except Exception:
            pass

    def _poll_nvidia_linux(self, readings: dict[str, float]) -> None:
        """Linux NVIDIA: extended metrics (gpu_util, mem_util, mem_clock, vram)."""
        if not NVML_AVAILABLE or pynvml is None:
            return
        for i, handle in self._nvidia_handles.items():
            prefix = f"nvidia:{i}"
            try:
                readings[f"{prefix}:temp"] = float(
                    pynvml.nvmlDeviceGetTemperature(handle, pynvml.NVML_TEMPERATURE_GPU))
            except Exception:
                pass
            try:
                util = pynvml.nvmlDeviceGetUtilizationRates(handle)
                readings[f"{prefix}:gpu_util"] = float(util.gpu)
                readings[f"{prefix}:mem_util"] = float(util.memory)
            except Exception:
                pass
            try:
                readings[f"{prefix}:clock"] = float(
                    pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_GRAPHICS))
            except Exception:
                pass
            try:
                readings[f"{prefix}:mem_clock"] = float(
                    pynvml.nvmlDeviceGetClockInfo(handle, pynvml.NVML_CLOCK_MEM))
            except Exception:
                pass
            try:
                readings[f"{prefix}:power"] = pynvml.nvmlDeviceGetPowerUsage(handle) / 1000.0
            except Exception:
                pass
            try:
                mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                readings[f"{prefix}:vram_used"] = int(mem.used) / (1024 * 1024)
                readings[f"{prefix}:vram_total"] = int(mem.total) / (1024 * 1024)
            except Exception:
                pass
            try:
                readings[f"{prefix}:fan"] = float(pynvml.nvmlDeviceGetFanSpeed(handle))
            except Exception:
                pass

    def _poll_rapl(self, readings: dict[str, float]) -> None:
        """Read Intel RAPL power (energy delta → watts)."""
        now = time.monotonic()
        for sid, path in self._rapl_paths.items():
            val = SysUtils.read_sysfs(path)
            if val is None:
                continue
            try:
                energy_uj = float(val)
            except ValueError:
                continue
            if sid in self._rapl_prev:
                prev_energy, prev_time = self._rapl_prev[sid]
                dt = now - prev_time
                if dt > 0:
                    power_w = (energy_uj - prev_energy) / (dt * 1_000_000)
                    if power_w >= 0:
                        readings[sid] = power_w
            self._rapl_prev[sid] = (energy_uj, now)

    def read_one(self, sensor_id: str) -> Optional[float]:
        """Read a single sensor by ID (Linux: direct sysfs for hwmon/drm)."""
        if sensor_id in self._hwmon_paths:
            if (val := SysUtils.read_sysfs(self._hwmon_paths[sensor_id])) is not None:
                try:
                    raw = float(val)
                    prefix = sensor_id.split(':')[-1]
                    for pfx, div in _HWMON_DIVISORS.items():
                        if prefix.startswith(pfx):
                            return raw / div
                    return raw
                except ValueError:
                    return None

        if sensor_id in self._drm_paths:
            if (val := SysUtils.read_sysfs(self._drm_paths[sensor_id])) is not None:
                try:
                    return float(val)
                except ValueError:
                    return None

        readings = self.read_all()
        return readings.get(sensor_id)

    # ── Linux-specific mapping ────────────────────────────────────────

    def _build_mapping(self) -> dict[str, str]:
        sensors = self._sensors
        _ff = self._find_first
        mapping: dict[str, str] = {}
        self._map_common(mapping)

        # CPU
        mapping['cpu_temp'] = (
            _ff(sensors, source='hwmon', name_contains='Package')
            or _ff(sensors, source='hwmon', name_contains='Tctl')
            or _ff(sensors, source='hwmon', name_contains='coretemp')
            or _ff(sensors, source='hwmon', name_contains='k10temp')
        )
        mapping['cpu_power'] = _ff(sensors, source='rapl')

        # GPU — pick best by VRAM
        gpu = self._best_gpu()
        if gpu.get('vendor') == 'nvidia':
            prefix = f"nvidia:{gpu['nvidia_idx']}"
            mapping['gpu_temp'] = f"{prefix}:temp"
            mapping['gpu_usage'] = f"{prefix}:gpu_util"
            mapping['gpu_clock'] = f"{prefix}:clock"
            mapping['gpu_power'] = f"{prefix}:power"
        elif gpu.get('vendor') == 'amd':
            drv = gpu['hwmon_driver']
            card = gpu['drm_card']
            mapping['gpu_temp'] = _ff(sensors, source='hwmon', name_contains=drv, category='temperature')
            mapping['gpu_usage'] = _ff(sensors, source='drm', name_contains=card, category='usage')
            mapping['gpu_clock'] = _ff(sensors, source='hwmon', name_contains=drv, category='clock')
            mapping['gpu_power'] = _ff(sensors, source='hwmon', name_contains=drv, category='power')
        elif _GPU_VENDOR_INTEL in _detect_gpu_vendors():
            mapping['gpu_temp'] = _ff(sensors, source='hwmon', name_contains='i915', category='temperature')
            mapping['gpu_usage'] = ''
            mapping['gpu_clock'] = _ff(sensors, source='drm', category='clock')
            mapping['gpu_power'] = _ff(sensors, source='hwmon', name_contains='i915', category='power')
        else:
            mapping['gpu_temp'] = ''
            mapping['gpu_usage'] = ''
            mapping['gpu_clock'] = ''
            mapping['gpu_power'] = ''

        # Memory
        mapping['mem_temp'] = _ff(sensors, source='hwmon', name_contains='spd')
        mapping['mem_clock'] = ''

        # Disk
        mapping['disk_temp'] = (
            _ff(sensors, source='hwmon', name_contains='nvme')
            or _ff(sensors, source='hwmon', name_contains='drivetemp')
        )

        # Fans
        self._map_fans(mapping, fan_sources=('hwmon',))

        return mapping

    def _best_gpu(self) -> dict:
        """Find the GPU with the most VRAM across all vendors.

        Returns {'vendor': str, 'nvidia_idx': int|None, 'drm_card': str,
                 'hwmon_driver': str, 'vram': int}.
        """
        best: dict = {}

        # NVIDIA: check VRAM via pynvml
        if NVML_AVAILABLE and pynvml is not None:
            for idx, handle in self._nvidia_handles.items():
                try:
                    mem = pynvml.nvmlDeviceGetMemoryInfo(handle)
                    vram = int(mem.total)
                    if vram > best.get('vram', 0):
                        best = {'vendor': 'nvidia', 'nvidia_idx': idx,
                                'drm_card': '', 'hwmon_driver': '', 'vram': vram}
                except Exception:
                    pass

        # AMD/Intel: check from DRM sysfs
        drm_base = Path('/sys/class/drm')
        if drm_base.exists():
            for card_dir in sorted(drm_base.glob('card[0-9]*')):
                if '-' in card_dir.name:
                    continue
                vendor_path = card_dir / 'device' / 'vendor'
                if not vendor_path.exists():
                    continue
                try:
                    vendor = vendor_path.read_text().strip().removeprefix('0x')
                except OSError:
                    continue

                if vendor not in (_GPU_VENDOR_AMD, _GPU_VENDOR_INTEL):
                    continue

                # Try to read VRAM from DRM
                mem_path = card_dir / 'device' / 'mem_info_vram_total'
                vram = 0
                if mem_path.exists():
                    if (val := SysUtils.read_sysfs(str(mem_path))):
                        try:
                            vram = int(val)
                        except ValueError:
                            pass

                if vram > best.get('vram', 0):
                    # Find hwmon driver for this card
                    hwmon_driver = ''
                    hwmon_path = card_dir / 'device' / 'hwmon'
                    if hwmon_path.exists():
                        for hdir in hwmon_path.iterdir():
                            if (name := SysUtils.read_sysfs(str(hdir / 'name'))):
                                hwmon_driver = name
                                break
                    vendor_name = 'amd' if vendor == _GPU_VENDOR_AMD else 'intel'
                    best = {'vendor': vendor_name, 'nvidia_idx': None,
                            'drm_card': card_dir.name, 'hwmon_driver': hwmon_driver,
                            'vram': vram}

        return best


# Backward-compat alias
def map_defaults(enumerator: SensorEnumerator) -> dict[str, str]:
    """Legacy wrapper — delegates to enumerator.map_defaults()."""
    return enumerator.map_defaults()
