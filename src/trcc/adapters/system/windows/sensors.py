"""Windows hardware sensor discovery and reading.

Platform-specific sources:
- LibreHardwareMonitor (LHM): GPU hotspot, memory junction, voltage — via
  undocumented NVAPI calls only available on Windows. Primary GPU source.
- pynvml: NVIDIA GPU fallback (cross-platform, fewer sensors)
- psutil: CPU usage/frequency, memory, disk I/O, network I/O
- WMI: thermal zones, fan speeds

Sensor IDs follow the same format as Linux for compatibility:
    lhm:{hardware}:{sensor}    e.g., lhm:gpu0:hotspot
    nvidia:{gpu}:{metric}      e.g., nvidia:0:temp
    psutil:{metric}            e.g., psutil:cpu_percent
    wmi:{class}:{property}     e.g., wmi:thermal:zone0
    computed:{metric}           e.g., computed:disk_read
"""
from __future__ import annotations

import logging
from typing import Any

import psutil

from trcc.adapters.system._base import SensorEnumeratorBase
from trcc.core.models import SensorInfo

log = logging.getLogger(__name__)

# ── Optional: LibreHardwareMonitor via pythonnet ──────────────────────
try:
    from HardwareMonitor.Hardware import Computer  # pyright: ignore[reportMissingImports]
    LHM_AVAILABLE = True
except Exception:
    LHM_AVAILABLE = False

# LHM SensorType → our category mapping
_LHM_TYPE_MAP: dict[str, tuple[str, str]] = {
    'Temperature': ('temperature', '°C'),
    'Fan': ('fan', 'RPM'),
    'Clock': ('clock', 'MHz'),
    'Load': ('usage', '%'),
    'Power': ('power', 'W'),
    'Voltage': ('voltage', 'V'),
    'SmallData': ('memory', 'MB'),
    'Data': ('memory', 'GB'),
    'Throughput': ('throughput', 'B/s'),
}


class WindowsSensorEnumerator(SensorEnumeratorBase):
    """Discovers and reads hardware sensors on Windows.

    Sensor priority for GPU:
    1. LibreHardwareMonitor — hotspot temp, memory junction temp, voltage
       (Windows-exclusive via NVAPI undocumented calls)
    2. pynvml fallback — basic temp, utilization, clock, power, fan, VRAM
    """

    def __init__(self) -> None:
        super().__init__()
        self._lhm_computer: Any = None
        self._lhm_gpu_used = False

    def discover(self) -> list[SensorInfo]:
        self._sensors.clear()
        self._lhm_gpu_used = False
        self._discover_psutil_windows()
        self._discover_lhm()
        if not self._lhm_gpu_used:
            self._discover_nvidia()
        self._discover_wmi()
        self._discover_computed()
        log.info("Windows sensor discovery: %d sensors", len(self._sensors))
        return self._sensors

    def _on_stop(self) -> None:
        """Close LHM computer on stop."""
        if self._lhm_computer is not None:
            try:
                self._lhm_computer.Close()
            except Exception:
                pass
            self._lhm_computer = None

    # ── Windows-specific discovery ────────────────────────────────────

    def _discover_psutil_windows(self) -> None:
        """Register psutil sensors — base + Windows CPU temps."""
        self._discover_psutil_base()

        # CPU temperature (Windows: requires admin or LHM)
        temps = psutil.sensors_temperatures() if hasattr(psutil, 'sensors_temperatures') else {}
        for chip, entries in temps.items():
            for i, entry in enumerate(entries):
                sid = f'psutil:temp:{chip}:{i}'
                label = entry.label or f'{chip} temp{i}'
                self._sensors.append(
                    SensorInfo(sid, label, 'temperature', '°C', 'psutil'),
                )

    def _discover_lhm(self) -> None:
        """Discover sensors via LibreHardwareMonitor."""
        if not LHM_AVAILABLE:
            return
        try:
            computer = Computer()
            computer.IsGpuEnabled = True
            computer.IsCpuEnabled = True
            computer.IsMotherboardEnabled = True
            computer.Open()
            self._lhm_computer = computer

            for hw in computer.Hardware:
                hw.Update()
                hw_type = str(hw.HardwareType)
                hw_name = str(hw.Name)

                if 'Gpu' in hw_type:
                    self._lhm_gpu_used = True

                hw_key = hw_name.lower().replace(' ', '_')[:20]
                self._register_lhm_sensors(hw_key, hw)

                for sub in hw.SubHardware:
                    sub.Update()
                    sub_key = str(sub.Name).lower().replace(' ', '_')[:20]
                    self._register_lhm_sensors(sub_key, sub)

            log.info("LHM discovery: %d sensors (GPU via NVAPI: %s)",
                     len(self._sensors), self._lhm_gpu_used)

        except Exception:
            log.warning("LibreHardwareMonitor discovery failed — falling back to pynvml",
                        exc_info=True)

    def _register_lhm_sensors(self, hw_key: str, hw: Any) -> None:
        """Register sensors from an LHM hardware node."""
        hw_name = str(hw.Name)
        for sensor in hw.Sensors:
            s_type = str(sensor.SensorType)
            s_name = str(sensor.Name)
            if not (mapping := _LHM_TYPE_MAP.get(s_type)):
                continue
            category, unit = mapping
            sid = f'lhm:{hw_key}:{s_name.lower().replace(" ", "_")}'
            self._sensors.append(
                SensorInfo(sid, f'{hw_name} {s_name}', category, unit, 'lhm'),
            )

    def _discover_wmi(self) -> None:
        """Discover sensors via WMI (thermal zones)."""
        try:
            import wmi  # pyright: ignore[reportMissingImports]
            w = wmi.WMI(namespace='root\\WMI')
            try:
                for tz in w.MSAcpi_ThermalZoneTemperature():
                    sid = f'wmi:thermal:{tz.InstanceName}'
                    self._sensors.append(
                        SensorInfo(sid, 'Thermal Zone', 'temperature', '°C', 'wmi'),
                    )
            except Exception:
                log.debug("WMI thermal zones not accessible (requires admin elevation)")
        except ImportError:
            log.debug("wmi package not available")
        except Exception:
            log.debug("WMI sensor discovery failed")

    # ── Windows-specific polling ──────────────────────────────────────

    def _poll_platform(self, readings: dict[str, float]) -> None:
        """Read Windows-specific sensors (LHM, WMI, psutil temps)."""
        # psutil CPU temps
        if hasattr(psutil, 'sensors_temperatures'):
            temps = psutil.sensors_temperatures()
            for chip, entries in temps.items():
                for i, entry in enumerate(entries):
                    readings[f'psutil:temp:{chip}:{i}'] = entry.current

        # LHM or NVIDIA fallback
        if self._lhm_computer is not None:
            self._poll_lhm(readings)
        # nvidia is handled by base _poll_nvidia via default _poll_once

    def _poll_lhm(self, readings: dict[str, float]) -> None:
        """Read all sensors from LibreHardwareMonitor."""
        try:
            for hw in self._lhm_computer.Hardware:
                hw.Update()
                hw_key = str(hw.Name).lower().replace(' ', '_')[:20]
                self._read_lhm_node(readings, hw_key, hw)
                for sub in hw.SubHardware:
                    sub.Update()
                    sub_key = str(sub.Name).lower().replace(' ', '_')[:20]
                    self._read_lhm_node(readings, sub_key, sub)
        except Exception:
            log.debug("LHM poll failed", exc_info=True)

    @staticmethod
    def _read_lhm_node(readings: dict[str, float], hw_key: str, hw: Any) -> None:
        """Read sensor values from an LHM hardware node."""
        for sensor in hw.Sensors:
            val = sensor.Value
            if val is None:
                continue
            s_name = str(sensor.Name).lower().replace(' ', '_')
            readings[f'lhm:{hw_key}:{s_name}'] = float(val)

    # ── Windows-specific mapping ──────────────────────────────────────

    def _build_mapping(self) -> dict[str, str]:
        sensors = self._sensors
        _ff = self._find_first
        mapping: dict[str, str] = {}
        self._map_common(mapping)

        # CPU — LHM > psutil
        mapping['cpu_temp'] = (
            _ff(sensors, source='lhm', name_contains='Package', category='temperature')
            or _ff(sensors, source='lhm', name_contains='CPU', category='temperature')
            or _ff(sensors, source='psutil', category='temperature')
        )
        mapping['cpu_power'] = (
            _ff(sensors, source='lhm', name_contains='Package', category='power')
            or _ff(sensors, source='lhm', name_contains='CPU', category='power')
        )

        # GPU — LHM > NVIDIA
        lhm_gpu_temp = _ff(sensors, source='lhm', name_contains='GPU', category='temperature')
        nvidia_gpu_temp = _ff(sensors, source='nvidia', category='temperature')
        if lhm_gpu_temp:
            mapping['gpu_temp'] = lhm_gpu_temp
            mapping['gpu_usage'] = _ff(sensors, source='lhm', name_contains='GPU', category='usage')
            mapping['gpu_clock'] = _ff(sensors, source='lhm', name_contains='GPU', category='clock')
            mapping['gpu_power'] = _ff(sensors, source='lhm', name_contains='GPU', category='power')
        elif nvidia_gpu_temp:
            mapping['gpu_temp'] = nvidia_gpu_temp
            mapping['gpu_usage'] = _ff(sensors, source='nvidia', category='gpu_busy')
            mapping['gpu_clock'] = _ff(sensors, source='nvidia', category='clock')
            mapping['gpu_power'] = _ff(sensors, source='nvidia', category='power')
        else:
            mapping['gpu_temp'] = ''
            mapping['gpu_usage'] = ''
            mapping['gpu_clock'] = ''
            mapping['gpu_power'] = ''

        # Memory
        mapping['mem_temp'] = _ff(sensors, source='lhm', name_contains='Memory', category='temperature')

        # Disk
        mapping['disk_temp'] = (
            _ff(sensors, source='lhm', name_contains='Drive', category='temperature')
            or _ff(sensors, source='lhm', name_contains='SSD', category='temperature')
            or _ff(sensors, source='lhm', name_contains='NVMe', category='temperature')
        )

        # Fans
        self._map_fans(mapping, fan_sources=('lhm', 'nvidia'))

        return mapping
