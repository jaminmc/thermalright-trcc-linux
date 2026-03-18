"""Hardware info queries — subprocess-based, no service dependencies.

Static hardware enumeration for memory DIMMs and physical disks.
Used by LED memory/disk info panels (C# UCLEDMemoryInfo, UCLEDHarddiskInfo).
"""
from __future__ import annotations

import os
import shutil
import subprocess
from typing import Optional

# Fields to extract from dmidecode -t memory (Type 17: Memory Device)
_DMI_MEMORY_FIELDS = {
    'manufacturer', 'part_number', 'type', 'speed',
    'configured_memory_speed', 'size', 'locator', 'form_factor',
    'rank', 'data_width', 'total_width', 'configured_voltage',
    'minimum_voltage', 'maximum_voltage', 'memory_technology',
}

_POLKIT_POLICY = '/usr/share/polkit-1/actions/com.github.lexonight1.trcc.policy'


def _privileged_cmd(binary: str, args: list[str]) -> list[str]:
    """Build command with pkexec elevation when polkit policy is installed.

    If running as root already, call the binary directly.
    If polkit policy exists, use pkexec with the full binary path
    (pkexec matches the exec.path annotation, so it must be absolute).
    Otherwise, call directly (will fail silently if root is needed).
    """
    if hasattr(os, 'geteuid') and os.geteuid() == 0:
        return [binary] + args
    full_path = shutil.which(binary)
    if full_path and os.path.isfile(_POLKIT_POLICY) and shutil.which('pkexec'):
        return ['pkexec', full_path] + args
    return [binary] + args


def get_memory_info() -> list[dict[str, str]]:
    """Get DRAM slot info (C# UCLEDMemoryInfo fields).

    Returns one dict per populated DIMM slot. Uses pkexec for dmidecode
    when polkit policy is installed; falls back to psutil for basic totals.

    Fields from dmidecode Type 17: manufacturer, part_number, type (DDR4/5),
    speed, configured_memory_speed, size, form_factor (DIMM/SODIMM),
    rank, data_width, configured_voltage, memory_technology.
    """
    slots: list[dict[str, str]] = []
    try:
        result = subprocess.run(
            _privileged_cmd('dmidecode', ['-t', 'memory']),
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            current: dict[str, str] = {}
            for line in result.stdout.splitlines():
                line = line.strip()
                if line.startswith('Memory Device'):
                    if current.get('size') and current['size'] != 'No Module Installed':
                        slots.append(current)
                    current = {}
                elif ':' in line:
                    key, _, val = line.partition(':')
                    val = val.strip()
                    key = key.strip().lower().replace(' ', '_')
                    if key in _DMI_MEMORY_FIELDS:
                        current[key] = val
            if current.get('size') and current['size'] != 'No Module Installed':
                slots.append(current)
    except Exception:
        pass

    # Fallback: at least report total from psutil
    if not slots:
        try:
            import psutil
            mem = psutil.virtual_memory()
            total_gb = f"{mem.total / (1024**3):.1f} GB"
            slots.append({'size': total_gb, 'type': 'Unknown',
                          'speed': 'Unknown', 'manufacturer': 'Unknown'})
        except Exception:
            pass
    return slots


def get_disk_info() -> list[dict[str, str]]:
    """Get disk info (C# UCLEDHarddiskInfo fields) via lsblk + smartctl.

    Returns one dict per physical disk with model, size, type (SSD/HDD),
    and health status (PASSED/FAILED) from SMART if available.
    """
    disks: list[dict[str, str]] = []
    try:
        import json as _json
        result = subprocess.run(
            ['lsblk', '-J', '-o', 'NAME,MODEL,SIZE,TYPE,ROTA'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            data = _json.loads(result.stdout)
            for dev in data.get('blockdevices', []):
                if dev.get('type') != 'disk' or not dev.get('model'):
                    continue
                disk_type = 'HDD' if dev.get('rota') else 'SSD'
                disk = {
                    'name': dev.get('name', ''),
                    'model': dev.get('model', 'Unknown').strip(),
                    'size': dev.get('size', 'Unknown'),
                    'type': disk_type,
                }
                # Try SMART health (uses pkexec if polkit policy installed)
                health = _get_smart_health(dev['name'])
                if health:
                    disk['health'] = health
                disks.append(disk)
    except Exception:
        pass
    return disks


def _get_smart_health(dev_name: str) -> Optional[str]:
    """Get SMART health status via smartctl. Returns 'PASSED'/'FAILED' or None."""
    try:
        result = subprocess.run(
            _privileged_cmd('smartctl', ['-H', f'/dev/{dev_name}']),
            capture_output=True, text=True, timeout=5,
        )
        for line in result.stdout.splitlines():
            if 'overall-health' in line.lower() or 'health status' in line.lower():
                if 'PASSED' in line:
                    return 'PASSED'
                if 'FAILED' in line:
                    return 'FAILED'
    except Exception:
        pass
    return None
