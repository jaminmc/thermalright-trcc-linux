"""Diagnostic report for bug reports.

Collects version, OS, devices, udev rules, SELinux, dependencies,
handshake results, and config into a single copyable text block.

Usage:
    from trcc.debug_report import DebugReport

    rpt = DebugReport()
    rpt.collect()
    print(rpt)           # formatted text
    rpt.sections          # list of (title, body) tuples
"""

from __future__ import annotations

import logging
import os
import platform
import subprocess
from dataclasses import dataclass, field
from pathlib import Path

log = logging.getLogger(__name__)

# All known Thermalright VIDs (lowercase hex, no prefix)
_KNOWN_VIDS = ("0416", "0418", "87cd", "87ad", "0402")

_UDEV_PATH = "/etc/udev/rules.d/99-trcc-lcd.rules"

_WIDTH = 60


@dataclass
class _Section:
    title: str
    lines: list[str] = field(default_factory=list)


class DebugReport:
    """Collects and formats system diagnostics for GitHub issues."""

    def __init__(self) -> None:
        self._sections: list[_Section] = []
        self._detected_devices: list = []  # Cached DetectedDevice list

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def collect(self) -> None:
        """Gather all diagnostic sections."""
        self._version()
        self._lsusb()
        self._udev_rules()
        self._selinux()
        self._rapl_permissions()
        self._dependencies()
        self._devices()
        self._device_permissions()
        self._handshakes()
        self._process_usage()
        self._config()
        self._recent_log()

    @property
    def sections(self) -> list[tuple[str, str]]:
        """Return collected sections as (title, body) pairs."""
        return [(s.title, "\n".join(s.lines)) for s in self._sections]

    def __str__(self) -> str:
        parts: list[str] = []
        for s in self._sections:
            parts.append(f"\n{'─' * _WIDTH}")
            parts.append(s.title)
            parts.append(f"{'─' * _WIDTH}")
            parts.extend(s.lines)
        parts.append(f"\n{'=' * _WIDTH}")
        parts.append("Copy everything above and paste it into your GitHub issue:")
        parts.append("  https://github.com/Lexonight1/thermalright-trcc-linux/issues/new")
        return "\n".join(parts)

    # ------------------------------------------------------------------
    # Section collectors
    # ------------------------------------------------------------------

    def _add(self, title: str) -> _Section:
        sec = _Section(title)
        self._sections.append(sec)
        return sec

    def _version(self) -> None:
        from trcc.__version__ import __version__

        sec = self._add("Version")
        sec.lines.append(f"  trcc-linux:  {__version__}")
        sec.lines.append(f"  Python:      {platform.python_version()}")
        sec.lines.append(f"  Distro:      {self._distro_name()}")
        sec.lines.append(f"  OS:          {platform.platform()}")
        sec.lines.append(f"  Kernel:      {platform.release()}")

    @staticmethod
    def _distro_name() -> str:
        """Get Linux distro name (e.g. 'Fedora 43', 'Ubuntu 24.04')."""
        try:
            # Python 3.10+ — pyright may not know about this on older stubs
            info: dict[str, str] = platform.freedesktop_os_release()  # type: ignore[attr-defined]
            return info.get("PRETTY_NAME", info.get("NAME", "Unknown"))
        except (OSError, AttributeError):
            return "Unknown"

    def _lsusb(self) -> None:
        sec = self._add("lsusb (filtered)")
        try:
            result = subprocess.run(
                ["lsusb"], capture_output=True, text=True, timeout=5,
            )
            matches = [
                line for line in result.stdout.splitlines()
                if any(vid in line.lower() for vid in _KNOWN_VIDS)
            ]
            if matches:
                for line in matches:
                    sec.lines.append(f"  {line}")
            else:
                sec.lines.append("  (no Thermalright devices found)")
        except Exception as e:
            sec.lines.append(f"  lsusb failed: {e}")

    def _udev_rules(self) -> None:
        sec = self._add(f"udev rules ({_UDEV_PATH})")
        try:
            with open(_UDEV_PATH) as f:
                for line in f:
                    stripped = line.rstrip()
                    if stripped and not stripped.startswith("#"):
                        sec.lines.append(f"  {stripped}")
            if not sec.lines:
                sec.lines.append("  (file exists but no active rules)")
        except FileNotFoundError:
            sec.lines.append("  NOT INSTALLED — run: trcc setup-udev")
        except PermissionError:
            sec.lines.append("  (permission denied reading udev rules)")
        except Exception as e:
            sec.lines.append(f"  Error: {e}")

    def _selinux(self) -> None:
        sec = self._add("SELinux")
        try:
            result = subprocess.run(
                ["getenforce"], capture_output=True, text=True, timeout=5,
            )
            sec.lines.append(f"  {result.stdout.strip()}")
        except FileNotFoundError:
            sec.lines.append("  not installed")
        except Exception as e:
            sec.lines.append(f"  getenforce failed: {e}")

    def _rapl_permissions(self) -> None:
        sec = self._add("RAPL power sensors")
        rapl_base = Path("/sys/class/powercap")
        if not rapl_base.exists():
            sec.lines.append("  not available (no powercap subsystem)")
            return
        energy_files = sorted(rapl_base.glob("intel-rapl:*/energy_uj"))
        if not energy_files:
            sec.lines.append("  not available (no RAPL domains)")
            return
        for f in energy_files:
            domain = f.parent.name
            readable = os.access(str(f), os.R_OK)
            mode = oct(f.stat().st_mode)[-3:]
            status = "readable" if readable else "NO ACCESS"
            sec.lines.append(f"  {domain}: mode={mode}  {status}")

    def _dependencies(self) -> None:
        from .doctor import get_module_version

        sec = self._add("Dependencies")
        for import_name, pkg_name in [
            ("PySide6", "PySide6"),
            ("usb.core", "pyusb"),
            ("hid", "hidapi"),
        ]:
            ver = get_module_version(import_name)
            if ver is not None:
                sec.lines.append(f"  {pkg_name}: {ver or '?'}")
            else:
                sec.lines.append(f"  {pkg_name}: not installed")

    def _devices(self) -> None:
        sec = self._add("Detected devices")
        try:
            from trcc.adapters.device.detector import DeviceDetector

            devices = DeviceDetector.detect()
            self._detected_devices = devices
            if not devices:
                sec.lines.append("  (none)")
                return
            for i, dev in enumerate(devices, 1):
                proto = dev.protocol.upper()
                sec.lines.append(
                    f"  [{i}] {dev.vid:04x}:{dev.pid:04x}  "
                    f"{dev.product_name}  ({proto})  "
                    f"path={dev.scsi_device or dev.usb_path}"
                )
        except Exception as e:
            sec.lines.append(f"  detect failed: {e}")

    def _device_permissions(self) -> None:
        sec = self._add("Device permissions")
        # Check /dev/sg* for SCSI devices
        sg_found = False
        for entry in sorted(os.listdir("/dev")):
            if entry.startswith("sg"):
                path = f"/dev/{entry}"
                try:
                    mode = oct(os.stat(path).st_mode)[-3:]
                    readable = os.access(path, os.R_OK | os.W_OK)
                    status = "OK" if readable else "NO ACCESS"
                    sec.lines.append(f"  {path}: mode={mode}  {status}")
                    sg_found = True
                except Exception:
                    pass
        if not sg_found:
            sec.lines.append("  (no /dev/sg* devices)")

    def _handshakes(self) -> None:
        sec = self._add("Handshakes")
        try:
            scsi_devs = [d for d in self._detected_devices if d.protocol == "scsi"]
            hid_devs = [d for d in self._detected_devices if d.protocol == "hid"]
            bulk_devs = [d for d in self._detected_devices if d.protocol == "bulk"]
            ly_devs = [d for d in self._detected_devices if d.protocol == "ly"]

            if not scsi_devs and not hid_devs and not bulk_devs and not ly_devs:
                sec.lines.append("  (no devices to handshake)")
                return

            for dev in scsi_devs:
                sec.lines.append(f"\n  {dev.vid:04x}:{dev.pid:04x} — SCSI")
                try:
                    self._handshake_scsi(dev, sec)
                except Exception as e:
                    sec.lines.append(f"    FAILED: {e}")

            for dev in hid_devs:
                is_led = dev.implementation == "hid_led"
                kind = "LED" if is_led else f"HID-LCD (Type {dev.device_type})"
                sec.lines.append(f"\n  {dev.vid:04x}:{dev.pid:04x} — {kind}")
                try:
                    if is_led:
                        self._handshake_led(dev, sec)
                    else:
                        self._handshake_hid_lcd(dev, sec)
                except Exception as e:
                    sec.lines.append(f"    FAILED: {e}")

            for dev in bulk_devs:
                sec.lines.append(f"\n  {dev.vid:04x}:{dev.pid:04x} — Bulk")
                try:
                    self._handshake_bulk(dev, sec)
                except Exception as e:
                    sec.lines.append(f"    FAILED: {e}")

            for dev in ly_devs:
                sec.lines.append(f"\n  {dev.vid:04x}:{dev.pid:04x} — LY")
                try:
                    self._handshake_ly(dev, sec)
                except Exception as e:
                    sec.lines.append(f"    FAILED: {e}")

        except Exception as e:
            sec.lines.append(f"  Error: {e}")

    def _process_usage(self) -> None:
        sec = self._add("Process usage")
        try:
            result = subprocess.run(
                ["ps", "-eo", "pid,pcpu,pmem,rss,comm", "--no-headers"],
                capture_output=True, text=True, timeout=5,
            )
            trcc_procs = [
                line.strip() for line in result.stdout.splitlines()
                if "trcc" in line.split()[-1]
            ]
            if not trcc_procs:
                sec.lines.append("  (no trcc process running)")
                return
            sec.lines.append("  PID    %CPU  %MEM   RSS(MB)  CMD")
            for proc in trcc_procs:
                parts = proc.split(None, 4)
                if len(parts) >= 5:
                    pid, cpu, mem, rss, cmd = parts
                    rss_mb = f"{int(rss) / 1024:.0f}"
                    sec.lines.append(
                        f"  {pid:>6}  {cpu:>5}  {mem:>4}  {rss_mb:>7}  {cmd}")
        except Exception as e:
            sec.lines.append(f"  Error: {e}")

    def _config(self) -> None:
        sec = self._add("Config")
        try:
            from trcc.conf import CONFIG_PATH, load_config

            config = load_config()
            if not config:
                sec.lines.append(f"  {CONFIG_PATH}: (empty or missing)")
                return
            sec.lines.append(f"  path: {CONFIG_PATH}")
            # Show non-sensitive keys
            for key in ("resolution", "temp_unit", "format_prefs"):
                if key in config:
                    sec.lines.append(f"  {key}: {config[key]}")
            # Device count
            devices = config.get("devices", {})
            if devices:
                sec.lines.append(f"  devices: {len(devices)} configured")
        except Exception as e:
            sec.lines.append(f"  Error: {e}")

    # ------------------------------------------------------------------
    # Handshake helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _ebusy_fallback(sec: _Section) -> None:
        """Show cached handshake data when device is in use by the GUI."""
        from trcc.conf import load_last_handshake

        cached = load_last_handshake()
        if cached and cached.get("resolution"):
            res = cached["resolution"]
            pm = cached.get("model_id", "?")
            raw = cached.get("raw", "")
            sec.lines.append(
                f"    PM={pm}, resolution=({res[0]}, {res[1]}), "
                f"serial={cached.get('serial', '')}")
            if raw:
                sec.lines.append(f"    raw[0:64]={raw[:128]}")
            sec.lines.append("    (from cache — device in use by trcc gui)")
        else:
            sec.lines.append("    (device in use by trcc gui)")

    def _handshake_scsi(self, dev, sec: _Section) -> None:
        from trcc.adapters.device.factory import ScsiProtocol
        from trcc.core.models import FBL_TO_RESOLUTION

        protocol = ScsiProtocol(dev.scsi_device)
        try:
            result = protocol.handshake()
            if result is None:
                sec.lines.append(
                    "    Result: None (poll failed)")
                return
            fbl = result.model_id
            known = "KNOWN" if fbl in FBL_TO_RESOLUTION else "UNKNOWN"
            res = result.resolution or (0, 0)
            sec.lines.append(
                f"    FBL={fbl} ({known}), "
                f"resolution={res[0]}x{res[1]}")
            if result.raw_response:
                sec.lines.append(f"    raw[0:64]={result.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _handshake_hid_lcd(self, dev, sec: _Section) -> None:
        from trcc.adapters.device.factory import (
            _ERRNO_EACCES,
            _ERRNO_EBUSY,
            HidProtocol,
            _has_usb_errno,
        )
        from trcc.adapters.device.hid import HidHandshakeInfo
        from trcc.core.models import fbl_to_resolution, pm_to_fbl

        protocol = HidProtocol(vid=dev.vid, pid=dev.pid, device_type=dev.device_type)
        try:
            info = protocol.handshake()
            if info is None:
                error = protocol.last_error
                if error and _has_usb_errno(error, _ERRNO_EACCES):
                    sec.lines.append(
                        "    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(
                        f"    Result: None ({error or 'no response'})")
                return

            assert isinstance(info, HidHandshakeInfo)
            pm = info.mode_byte_1
            sub = info.mode_byte_2
            fbl = info.fbl if info.fbl is not None else pm_to_fbl(pm, sub)
            resolution = info.resolution or fbl_to_resolution(fbl, pm)
            sec.lines.append(f"    PM={pm} (0x{pm:02x}), SUB={sub} (0x{sub:02x}), "
                             f"FBL={fbl}, resolution={resolution[0]}x{resolution[1]}")
            if info.serial:
                sec.lines.append(f"    serial={info.serial}")
            if info.raw_response:
                sec.lines.append(f"    raw[0:64]={info.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _handshake_led(self, dev, sec: _Section) -> None:
        from trcc.adapters.device.factory import (
            _ERRNO_EACCES,
            _ERRNO_EBUSY,
            LedProtocol,
            _has_usb_errno,
        )
        from trcc.adapters.device.led import LedHandshakeInfo, PmRegistry

        protocol = LedProtocol(vid=dev.vid, pid=dev.pid)
        try:
            info = protocol.handshake()
            if info is None:
                error = protocol.last_error
                if error and _has_usb_errno(error, _ERRNO_EACCES):
                    sec.lines.append(
                        "    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(
                        f"    Result: None ({error or 'no response'})")
                return

            assert isinstance(info, LedHandshakeInfo)
            known = "KNOWN" if info.pm in PmRegistry.PM_TO_STYLE else "UNKNOWN"
            style_info = ""
            if info.style:
                style_info = (f", LEDs={info.style.led_count}, "
                              f"segments={info.style.segment_count}")
            sec.lines.append(
                f"    PM={info.pm} (0x{info.pm:02x}), SUB={info.sub_type}, "
                f"model={info.model_name}, {known}{style_info}"
            )
            if info.raw_response:
                sec.lines.append(f"    raw[0:64]={info.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _handshake_bulk(self, dev, sec: _Section) -> None:
        from trcc.adapters.device.factory import (
            _ERRNO_EACCES,
            _ERRNO_EBUSY,
            BulkProtocol,
            _has_usb_errno,
        )

        protocol = BulkProtocol(vid=dev.vid, pid=dev.pid)
        try:
            result = protocol.handshake()
            if result is None:
                error = protocol.last_error
                if error and _has_usb_errno(error, _ERRNO_EACCES):
                    sec.lines.append(
                        "    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(
                        f"    Result: None ({error or 'no response'})")
                return
            sec.lines.append(
                f"    PM={result.model_id}, resolution={result.resolution}, "
                f"serial={result.serial}"
            )
            if result.raw_response:
                sec.lines.append(f"    raw[0:64]={result.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _recent_log(self) -> None:
        sec = self._add("Recent log (last 50 lines)")
        log_path = Path.home() / ".trcc" / "trcc.log"
        if not log_path.exists():
            sec.lines.append("  (no log file)")
            return
        try:
            lines = log_path.read_text(errors="replace").splitlines()
            tail = lines[-50:] if len(lines) > 50 else lines
            if not tail:
                sec.lines.append("  (empty log)")
                return
            for line in tail:
                sec.lines.append(f"  {line}")
        except Exception as e:
            sec.lines.append(f"  Error reading log: {e}")

    def _handshake_ly(self, dev, sec: _Section) -> None:
        from trcc.adapters.device.factory import (
            _ERRNO_EACCES,
            _ERRNO_EBUSY,
            LyProtocol,
            _has_usb_errno,
        )

        protocol = LyProtocol(vid=dev.vid, pid=dev.pid)
        try:
            result = protocol.handshake()
            if result is None:
                error = protocol.last_error
                if error and _has_usb_errno(error, _ERRNO_EACCES):
                    sec.lines.append(
                        "    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(
                        f"    Result: None ({error or 'no response'})")
                return
            sec.lines.append(
                f"    PM={result.model_id}, resolution={result.resolution}, "
                f"serial={result.serial}"
            )
            if result.raw_response:
                sec.lines.append(f"    raw[0:64]={result.raw_response[:64].hex()}")
        finally:
            protocol.close()
