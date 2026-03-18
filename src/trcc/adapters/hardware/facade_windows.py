"""Windows hardware info queries via WMI.

Replaces Linux dmidecode/lsblk/smartctl with WMI queries.
Same return types as Linux hardware.py — list[dict[str, str]].
"""
from __future__ import annotations

import logging
from typing import Optional

log = logging.getLogger(__name__)


def _privileged_cmd(binary: str, args: list[str]) -> list[str]:
    """Build command — no elevation needed on Windows for most queries.

    WMI runs in the user's security context. For operations that need
    admin (e.g., S.M.A.R.T.), the app should be launched elevated.
    """
    return [binary] + args


def get_memory_info() -> list[dict[str, str]]:
    """Get DRAM slot info via WMI Win32_PhysicalMemory.

    Returns one dict per populated DIMM slot, matching Linux format:
        manufacturer, part_number, type, speed, size, form_factor, rank, etc.
    """
    slots: list[dict[str, str]] = []
    try:
        import wmi  # pyright: ignore[reportMissingImports]
        w = wmi.WMI()
        for mem in w.Win32_PhysicalMemory():
            slot: dict[str, str] = {}
            slot['manufacturer'] = (mem.Manufacturer or '').strip()
            slot['part_number'] = (mem.PartNumber or '').strip()
            slot['speed'] = str(mem.ConfiguredClockSpeed or mem.Speed or '')
            slot['configured_memory_speed'] = str(mem.ConfiguredClockSpeed or '')
            slot['size'] = _format_size(mem.Capacity)
            slot['form_factor'] = _memory_form_factor(mem.FormFactor)
            slot['type'] = _memory_type(mem.SMBIOSMemoryType)
            slot['locator'] = mem.DeviceLocator or ''
            slot['rank'] = str(mem.Rank or '')
            slot['data_width'] = str(mem.DataWidth or '')
            slot['total_width'] = str(mem.TotalWidth or '')
            if slot['size'] and slot['size'] != '0':
                slots.append(slot)
    except ImportError:
        log.debug("wmi package not available — using psutil fallback")
        import psutil
        mem = psutil.virtual_memory()
        slots.append({
            'manufacturer': 'Unknown',
            'part_number': 'Unknown',
            'type': 'Unknown',
            'speed': 'Unknown',
            'size': f'{mem.total // (1024 ** 3)} GB',
            'form_factor': 'Unknown',
            'locator': 'Total',
        })
    except Exception:
        log.exception("WMI memory query failed")
    return slots


def get_disk_info() -> list[dict[str, str]]:
    """Get physical disk info via WMI Win32_DiskDrive.

    Returns one dict per disk, matching Linux format:
        name, model, size, type (SSD/HDD), health.
    """
    disks: list[dict[str, str]] = []
    try:
        import wmi  # pyright: ignore[reportMissingImports]
        w = wmi.WMI()
        for disk in w.Win32_DiskDrive():
            info: dict[str, str] = {}
            info['name'] = disk.DeviceID or ''
            info['model'] = (disk.Model or '').strip()
            info['size'] = _format_size(disk.Size)
            info['type'] = _disk_type(disk)
            info['health'] = _get_disk_health(disk.DeviceID)
            disks.append(info)
    except ImportError:
        log.debug("wmi package not available")
    except Exception:
        log.exception("WMI disk query failed")
    return disks


# ── Helpers ────────────────────────────────────────────────────────


def _format_size(size_bytes: Optional[str | int]) -> str:
    """Convert bytes to human-readable size."""
    if not size_bytes:
        return ''
    try:
        b = int(size_bytes)
        if b >= 1024 ** 4:
            return f'{b / (1024 ** 4):.1f} TB'
        if b >= 1024 ** 3:
            return f'{b / (1024 ** 3):.0f} GB'
        if b >= 1024 ** 2:
            return f'{b / (1024 ** 2):.0f} MB'
        return f'{b} B'
    except (ValueError, TypeError):
        return str(size_bytes)


def _memory_form_factor(code: Optional[int]) -> str:
    """WMI FormFactor code → string."""
    factors = {
        8: 'DIMM', 12: 'SODIMM', 13: 'RIMM',
        15: 'FB-DIMM', 16: 'Die',
    }
    return factors.get(code or 0, 'Unknown')


def _memory_type(code: Optional[int]) -> str:
    """WMI SMBIOSMemoryType code → string."""
    types = {
        20: 'DDR', 21: 'DDR2', 24: 'DDR3',
        26: 'DDR4', 30: 'LPDDR4', 34: 'DDR5', 35: 'LPDDR5',
    }
    return types.get(code or 0, 'Unknown')


def _disk_type(disk: object) -> str:
    """Guess SSD vs HDD from WMI disk properties."""
    model = (getattr(disk, 'Model', '') or '').upper()
    media_type = (getattr(disk, 'MediaType', '') or '').upper()
    if 'SSD' in model or 'NVME' in model or 'SOLID' in media_type:
        return 'SSD'
    if 'HDD' in model or 'FIXED' in media_type:
        return 'HDD'
    return 'Unknown'


def _get_disk_health(device_id: Optional[str]) -> str:
    """Query S.M.A.R.T. health via WMI (requires admin)."""
    if not device_id:
        return 'Unknown'
    try:
        import wmi  # pyright: ignore[reportMissingImports]
        w = wmi.WMI(namespace='root\\WMI')
        for status in w.MSStorageDriver_FailurePredictStatus():
            if status.Active:
                return 'FAILED' if status.PredictFailure else 'PASSED'
    except Exception:
        pass
    return 'Unknown'
