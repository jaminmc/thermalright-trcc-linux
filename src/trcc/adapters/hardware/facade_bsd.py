"""FreeBSD hardware info via sysctl and geom.

Replaces Linux dmidecode/lsblk with FreeBSD-native queries.
Same return types as Linux hardware.py — list[dict[str, str]].
"""
from __future__ import annotations

import logging
import re
import subprocess

log = logging.getLogger(__name__)


def _sysctl(key: str) -> str:
    """Read a single sysctl value. Returns empty string on failure."""
    try:
        result = subprocess.run(
            ['sysctl', '-n', key],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            return result.stdout.strip()
    except Exception:
        pass
    return ''


def get_memory_info() -> list[dict[str, str]]:
    """Get memory info via sysctl.

    FreeBSD doesn't expose per-DIMM details via sysctl like dmidecode.
    Returns a single entry with total memory from hw.physmem.
    """
    slots: list[dict[str, str]] = []

    physmem = _sysctl('hw.physmem')
    if physmem:
        try:
            total_bytes = int(physmem)
            total_gb = total_bytes / (1024 ** 3)
            slots.append({
                'manufacturer': 'Unknown',
                'part_number': '',
                'type': _sysctl('dev.cpu.0.freq') and 'DDR' or 'Unknown',
                'speed': 'Unknown',
                'size': f'{total_gb:.0f} GB',
                'form_factor': 'Unknown',
                'locator': 'Total',
            })
        except (ValueError, TypeError):
            pass

    # Fallback: psutil
    if not slots:
        import psutil
        mem = psutil.virtual_memory()
        slots.append({
            'manufacturer': 'Unknown',
            'part_number': '',
            'type': 'Unknown',
            'speed': 'Unknown',
            'size': f'{mem.total // (1024 ** 3)} GB',
            'form_factor': 'Unknown',
            'locator': 'Total',
        })

    return slots


def get_disk_info() -> list[dict[str, str]]:
    """Get disk info via geom disk list.

    Parses `geom disk list` output for name, size, and description.
    """
    disks: list[dict[str, str]] = []

    try:
        result = subprocess.run(
            ['geom', 'disk', 'list'],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode != 0:
            return []

        current: dict[str, str] = {}
        for line in result.stdout.splitlines():
            line = line.strip()

            # "Geom name: ada0" or "Geom name: nvd0"
            if line.startswith('Geom name:'):
                if current.get('name'):
                    disks.append(current)
                current = {'name': line.split(':', 1)[1].strip()}

            # "descr: Samsung SSD 970 EVO 500GB"
            elif line.startswith('descr:'):
                current['model'] = line.split(':', 1)[1].strip()

            # "Mediasize: 500107862016 (466G)"
            elif line.startswith('Mediasize:'):
                raw = line.split(':', 1)[1].strip()
                match = re.search(r'\(([^)]+)\)', raw)
                if match:
                    current['size'] = match.group(1)
                else:
                    # Parse raw bytes
                    parts = raw.split()
                    if parts:
                        try:
                            b = int(parts[0])
                            if b >= 1024 ** 4:
                                current['size'] = f'{b / (1024 ** 4):.1f} TB'
                            elif b >= 1024 ** 3:
                                current['size'] = f'{b / (1024 ** 3):.0f} GB'
                        except (ValueError, TypeError):
                            current['size'] = raw

            # "rotationrate: 0" (0 = SSD, >0 = HDD RPM)
            elif line.startswith('rotationrate:'):
                rate = line.split(':', 1)[1].strip()
                current['type'] = 'HDD' if rate != '0' else 'SSD'

        if current.get('name'):
            disks.append(current)

        # Default type to SSD if not set
        for d in disks:
            d.setdefault('type', 'Unknown')
            d.setdefault('model', '')
            d.setdefault('size', '')
            d.setdefault('health', 'Unknown')

    except Exception:
        log.debug("geom disk list failed")

    return disks
