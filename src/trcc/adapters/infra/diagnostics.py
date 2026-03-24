"""TRCC diagnostics — single module for logging, health checks, and device debug.

``trcc report`` (DebugReport) is the base. Every protocol debug helper
(_debug_scsi, _debug_hid_lcd, _debug_hid_led, _debug_bulk, _debug_ly) is
shared by both the compact report sections and the verbose interactive
commands (device_debug, led_debug_interactive).

Structure
---------
1. Logging       — TrccLoggingConfigurator, StandardLoggingConfigurator
2. Doctor data   — distro/PM maps, install hints, check helpers
3. Result types  — DepResult, GpuResult, UdevResult, SelinuxResult, …
4. Doctor checks — get_module_version, check_*, run_doctor
5. Protocol debug helpers — shared between report and interactive CLI
6. Interactive debug      — device_debug, led_debug_interactive
7. DebugReport            — collect(), __str__(), all section methods
"""

from __future__ import annotations

import ctypes.util
import logging
import logging.handlers
import os
import platform
import re
import shutil
import subprocess
import sys
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any, Callable, Optional

if TYPE_CHECKING:
    from trcc.core.ports import DoctorPlatformConfig, ReportPlatformConfig

log = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────────────────────
# 1. Logging
# ─────────────────────────────────────────────────────────────────────────────

_DEFAULT_LOG_FILE = Path.home() / '.trcc' / 'trcc.log'


class TrccLoggingConfigurator(ABC):
    """Port: TRCC application logging configuration.

    Named TrccLoggingConfigurator to avoid confusion with Python's
    standard logging.config.BaseConfigurator.
    """

    @abstractmethod
    def configure(self, verbosity: int = 0) -> None:
        """Configure root logger with file + console handlers.

        Args:
            verbosity: 0 = WARNING on console, 1 = INFO, 2+ = DEBUG.
                       File handler is always DEBUG regardless.
        """


class StandardLoggingConfigurator(TrccLoggingConfigurator):
    """Configures file + console logging with a consistent format.

    Both handlers share the same format string. %(funcName)s is included
    so every log line names its calling method — refactoring automatically
    updates log output.
    """

    FORMAT = '%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s'
    DATE_FMT = '%Y-%m-%d %H:%M:%S'
    DATE_FMT_CONSOLE = '%H:%M:%S'

    def __init__(self, log_file: Path = _DEFAULT_LOG_FILE) -> None:
        self._log_file = log_file

    def configure(self, verbosity: int = 0) -> None:
        """Replace all root logger handlers with file + console.

        Clears handlers set by the early __main__.py bootstrap so there
        are no duplicates.
        """
        root = logging.getLogger()
        root.handlers.clear()
        root.setLevel(logging.DEBUG)

        self._log_file.parent.mkdir(parents=True, exist_ok=True)
        fh = logging.handlers.RotatingFileHandler(
            self._log_file, maxBytes=1_000_000, backupCount=3,
        )
        fh.setLevel(logging.DEBUG)
        fh.setFormatter(logging.Formatter(self.FORMAT, datefmt=self.DATE_FMT))
        root.addHandler(fh)

        console_level = (
            logging.DEBUG if verbosity >= 2
            else logging.INFO if verbosity == 1
            else logging.WARNING
        )
        ch = logging.StreamHandler()
        ch.setLevel(console_level)
        ch.setFormatter(logging.Formatter(self.FORMAT, datefmt=self.DATE_FMT_CONSOLE))
        root.addHandler(ch)


# ─────────────────────────────────────────────────────────────────────────────
# 2. Doctor data — distro/PM maps, install hints
# ─────────────────────────────────────────────────────────────────────────────

_DISTRO_TO_PM: dict[str, str] = {
    # dnf
    'fedora': 'dnf', 'rhel': 'dnf', 'centos': 'dnf',
    'rocky': 'dnf', 'alma': 'dnf', 'nobara': 'dnf',
    # apt
    'ubuntu': 'apt', 'debian': 'apt', 'linuxmint': 'apt',
    'pop': 'apt', 'zorin': 'apt', 'elementary': 'apt',
    'neon': 'apt', 'raspbian': 'apt', 'kali': 'apt',
    # pacman
    'arch': 'pacman', 'manjaro': 'pacman', 'endeavouros': 'pacman',
    'cachyos': 'pacman', 'garuda': 'pacman', 'artix': 'pacman',
    'arcolinux': 'pacman', 'steamos': 'pacman',
    # immutable
    'bazzite': 'rpm-ostree',
    # zypper
    'opensuse-tumbleweed': 'zypper', 'opensuse-leap': 'zypper', 'sles': 'zypper',
    # others
    'void': 'xbps',
    'alpine': 'apk', 'postmarketos': 'apk',
    'gentoo': 'emerge', 'funtoo': 'emerge', 'calculate': 'emerge',
    'solus': 'eopkg', 'clear-linux-os': 'swupd',
}

_FAMILY_TO_PM: dict[str, str] = {
    'fedora': 'dnf', 'rhel': 'dnf',
    'debian': 'apt', 'ubuntu': 'apt',
    'arch': 'pacman',
    'suse': 'zypper',
}

_INSTALL_MAP: dict[str, dict[str, str]] = {
    'sg_raw': {
        'dnf': 'sg3_utils', 'apt': 'sg3-utils', 'pacman': 'sg3_utils',
        'zypper': 'sg3_utils', 'xbps': 'sg3_utils', 'apk': 'sg3_utils',
        'emerge': 'sg3_utils', 'eopkg': 'sg3_utils',
        'rpm-ostree': 'sg3_utils', 'swupd': 'devpkg-sg3_utils',
    },
    '7z': {
        'dnf': 'p7zip p7zip-plugins', 'apt': 'p7zip-full', 'pacman': 'p7zip',
        'zypper': 'p7zip-full', 'xbps': 'p7zip', 'apk': '7zip',
        'emerge': 'p7zip',
        'winget': '7zip.7zip', 'brew': 'p7zip', 'pkg': 'p7zip',
    },
    'ffmpeg': {
        'dnf': 'ffmpeg', 'apt': 'ffmpeg', 'pacman': 'ffmpeg',
        'zypper': 'ffmpeg', 'xbps': 'ffmpeg', 'apk': 'ffmpeg',
        'emerge': 'ffmpeg', 'eopkg': 'ffmpeg',
        'winget': 'Gyan.FFmpeg', 'brew': 'ffmpeg', 'pkg': 'ffmpeg',
    },
    'libusb': {
        'dnf': 'libusb1', 'apt': 'libusb-1.0-0', 'pacman': 'libusb',
        'zypper': 'libusb-1_0-0', 'xbps': 'libusb', 'apk': 'libusb',
        'emerge': 'dev-libs/libusb',
        'brew': 'libusb', 'pkg': 'libusb',
    },
    'libxcb-cursor': {
        'apt': 'libxcb-cursor0',
    },
    'checkmodule': {
        'dnf': 'checkpolicy', 'apt': 'checkpolicy', 'pacman': 'checkpolicy',
        'zypper': 'checkpolicy', 'rpm-ostree': 'checkpolicy',
    },
    'semodule_package': {
        'dnf': 'policycoreutils', 'apt': 'semodule-utils',
        'pacman': 'semodule-utils', 'zypper': 'policycoreutils',
        'rpm-ostree': 'policycoreutils',
    },
}

_INSTALL_CMD: dict[str, str] = {
    'dnf': 'sudo dnf install', 'apt': 'sudo apt install',
    'pacman': 'sudo pacman -S', 'zypper': 'sudo zypper install',
    'xbps': 'sudo xbps-install', 'apk': 'sudo apk add',
    'emerge': 'sudo emerge', 'eopkg': 'sudo eopkg install',
    'rpm-ostree': 'sudo rpm-ostree install', 'swupd': 'sudo swupd bundle-add',
    'winget': 'winget install', 'brew': 'brew install',
    'pkg': 'sudo pkg install',
}


def _read_os_release() -> dict[str, str]:
    """Read /etc/os-release into a dict."""
    _os_release = getattr(platform, 'freedesktop_os_release', None)
    if _os_release is not None:
        try:
            return _os_release()
        except OSError:
            pass
    result: dict[str, str] = {}
    for path in ('/etc/os-release', '/usr/lib/os-release'):
        if os.path.isfile(path):
            with open(path) as f:
                for line in f:
                    line = line.strip()
                    if '=' in line:
                        k, _, v = line.partition('=')
                        result[k] = v.strip('"')
            break
    return result


def _detect_pkg_manager() -> str | None:
    """Detect the Linux package manager from os-release."""
    info = _read_os_release()
    distro_id = info.get('ID', '').lower()
    if pm := _DISTRO_TO_PM.get(distro_id):
        return pm
    for like in info.get('ID_LIKE', '').lower().split():
        if pm := _FAMILY_TO_PM.get(like):
            return pm
    return None


def _provides_search(dep: str, pm: str) -> str | None:
    """Use PM's native 'provides' to find which package owns a file."""
    if pm == 'dnf':
        cmd = ['dnf', 'provides', '--quiet', f'*/{dep}*']
    elif pm == 'pacman':
        cmd = ['pacman', '-Fq', dep]
    elif pm == 'zypper':
        cmd = ['zypper', '--non-interactive', 'search', '--provides', dep]
    elif pm == 'apk':
        cmd = ['apk', 'search', dep]
    elif pm == 'xbps':
        cmd = ['xbps-query', '-Rs', dep]
    else:
        return None

    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        if r.returncode != 0 or not r.stdout.strip():
            return None
        first = r.stdout.strip().split('\n')[0]
        if pm == 'dnf':
            m = re.match(r'([\w][\w.+-]*)-\d', first)
            return m.group(1) if m else None
        if pm == 'pacman':
            return first.split('/')[-1].strip() or None
        if pm == 'zypper':
            for line in r.stdout.strip().split('\n'):
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2 and parts[1] and parts[1] != 'Name':
                    return parts[1]
            return None
        if pm == 'apk':
            m = re.match(r'([\w][\w.+-]*)-\d', first)
            return m.group(1) if m else None
        if pm == 'xbps':
            m = re.search(r'[\]\\s]+([\w][\w.+-]*)-\d', first)
            return m.group(1) if m else None
        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _install_hint(dep: str, pm: str | None) -> str:
    """Build install command string, or generic fallback."""
    if pm and dep in _INSTALL_MAP and pm in _INSTALL_MAP[dep]:
        cmd = _INSTALL_CMD.get(pm, f'sudo {pm} install')
        return f"{cmd} {_INSTALL_MAP[dep][pm]}"
    if pm:
        pkg = _provides_search(dep, pm)
        if pkg:
            cmd = _INSTALL_CMD.get(pm, f'sudo {pm} install')
            return f"{cmd} {pkg}"
    if dep in _INSTALL_MAP:
        lines = [f"  {_INSTALL_CMD.get(m, m)} {pkg}"
                 for m, pkg in _INSTALL_MAP[dep].items()]
        return "install one of:\n" + "\n".join(lines)
    return f"install {dep}"


def _enable_ansi_windows() -> None:
    """Enable ANSI escape codes on Windows (virtual terminal processing)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


_OK = "\033[32m[OK]\033[0m"
_MISS = "\033[31m[MISSING]\033[0m"
_OPT = "\033[33m[--]\033[0m"


def _check_python_module(
    label: str, import_name: str, required: bool, pm: str | None,
) -> bool:
    ver = get_module_version(import_name)
    if ver is not None:
        ver_str = f" {ver}" if ver else ""
        print(f"  {_OK}  {label}{ver_str}")
        return True
    if required:
        print(f"  {_MISS}  {label} — pip install {label.lower()}")
        return False
    print(f"  {_OPT}  {label} not installed (optional)")
    return True


def _check_binary(
    name: str, required: bool, pm: str | None, note: str = '',
) -> bool:
    if shutil.which(name):
        print(f"  {_OK}  {name}")
        return True
    suffix = f" ({note})" if note else ""
    hint = _install_hint(name, pm)
    if required:
        print(f"  {_MISS}  {name} — {hint}{suffix}")
        return False
    print(f"  {_OPT}  {name} not found — {hint}{suffix}")
    return True


def _check_library(
    label: str, so_name: str, required: bool, pm: str | None,
    dep_key: str = '',
) -> bool:
    if ctypes.util.find_library(so_name):
        print(f"  {_OK}  {label}")
        return True
    hint = _install_hint(dep_key or label, pm)
    if required:
        print(f"  {_MISS}  {label} — {hint}")
        return False
    print(f"  {_OPT}  {label} not found — {hint}")
    return True


def _check_gpu_packages() -> None:
    results = check_gpu()
    if not results:
        print(f"  {_OPT}  No discrete GPU detected")
        return
    for g in results:
        if g.vendor == 'nvidia' and not g.package_installed:
            print(f"  {_OPT}  NVIDIA GPU detected — {g.install_cmd}"
                  " (enables GPU temp/usage/clock)")
        elif g.vendor == 'nvidia':
            ver = get_module_version('pynvml')
            print(f"  {_OK}  nvidia-ml-py{f' {ver}' if ver else ''} (NVIDIA GPU detected)")
        else:
            print(f"  {_OK}  {g.label}")


def _check_udev_rules() -> bool:
    result = check_udev()
    if not result.ok and result.missing_vids:
        print(f"  {_MISS}  udev rules outdated — missing VID(s): {', '.join(result.missing_vids)}")
        print("         run: trcc setup-udev")
    elif not result.ok:
        print(f"  {_MISS}  udev rules — run: trcc setup-udev")
    else:
        print(f"  {_OK}  udev rules (/etc/udev/rules.d/99-trcc-lcd.rules)")
    return result.ok


def _check_rapl_permissions() -> bool:
    result = check_rapl()
    if not result.applicable:
        return True
    if result.ok:
        print(f"  {_OK}  RAPL power sensors ({result.domain_count} domain(s))")
    else:
        print(f"  {_OPT}  RAPL power sensors not readable — run: trcc setup-udev")
    return result.ok


def _check_winusb_devices() -> None:
    """Check if connected devices need WinUSB driver (Windows only)."""
    try:
        import wmi as wmi_mod  # pyright: ignore[reportMissingImports]
    except ImportError:
        return

    from trcc.core.models import BULK_DEVICES, HID_LCD_DEVICES, LED_DEVICES, LY_DEVICES
    winusb_registries = {**BULK_DEVICES, **HID_LCD_DEVICES, **LED_DEVICES, **LY_DEVICES}

    try:
        w = wmi_mod.WMI()
        for usb in w.Win32_PnPEntity():
            dev_id = getattr(usb, 'DeviceID', '') or ''
            if 'VID_' not in dev_id:
                continue
            m = re.search(r'VID_([0-9A-Fa-f]{4})&PID_([0-9A-Fa-f]{4})', dev_id)
            if not m:
                continue
            vid, pid = int(m.group(1), 16), int(m.group(2), 16)
            if (vid, pid) not in winusb_registries:
                continue
            entry = winusb_registries[(vid, pid)]
            status = getattr(usb, 'Status', 'Unknown')
            service = getattr(usb, 'Service', '') or ''
            if service.lower() == 'winusb':
                print(f"  {_OK}  {entry.product} ({vid:04X}:{pid:04X}) — WinUSB")
            else:
                print(f"  {_OPT}  {entry.product} ({vid:04X}:{pid:04X}) — "
                      f"needs WinUSB (status: {status})")
                print("         Install via Zadig: https://zadig.akeo.ie/")
                print("         Or run: trcc setup-winusb")
    except Exception:
        pass


# ─────────────────────────────────────────────────────────────────────────────
# 3. Structured result types
# ─────────────────────────────────────────────────────────────────────────────

@dataclass
class DepResult:
    """Result of a single dependency check."""
    name: str
    ok: bool
    required: bool
    version: str = ''
    note: str = ''
    install_cmd: str = ''


@dataclass
class GpuResult:
    """Result of GPU vendor detection."""
    vendor: str
    label: str
    package_installed: bool
    install_cmd: str = ''


@dataclass
class UdevResult:
    """Result of udev rules check."""
    ok: bool
    message: str
    missing_vids: list[str] = field(default_factory=list)


@dataclass
class SetupInfo:
    """System info for setup wizard header."""
    distro: str
    pkg_manager: str | None
    python_version: str


@dataclass
class SelinuxResult:
    """Result of SELinux policy check."""
    ok: bool
    message: str
    enforcing: bool = False
    module_loaded: bool = False


@dataclass
class RaplResult:
    """Result of RAPL power sensor check."""
    ok: bool
    message: str
    applicable: bool = True
    domain_count: int = 0


@dataclass
class PolkitResult:
    """Result of polkit policy check."""
    ok: bool
    message: str


# ─────────────────────────────────────────────────────────────────────────────
# 4. Doctor checks — public API
# ─────────────────────────────────────────────────────────────────────────────

def get_module_version(import_name: str) -> str | None:
    """Get version string for a Python module, or None if not installed."""
    try:
        mod = __import__(import_name)
        ver = getattr(mod, '__version__', getattr(mod, 'version', ''))
        if isinstance(ver, tuple):
            ver = '.'.join(str(x) for x in ver)
        if not ver and import_name == 'PySide6':
            try:
                import PySide6
                ver = PySide6.__version__
            except ImportError:
                pass
        return str(ver) if ver else ''
    except ImportError:
        return None


def get_setup_info(doctor_config: 'DoctorPlatformConfig | None' = None) -> SetupInfo:
    """Get system info for setup wizard."""
    if doctor_config is None:
        from trcc.core.builder import ControllerBuilder
        doctor_config = ControllerBuilder.for_current_os().build_setup().get_doctor_config()
    v = sys.version_info
    return SetupInfo(
        distro=doctor_config.distro_name,
        pkg_manager=doctor_config.pkg_manager,
        python_version=f"{v.major}.{v.minor}.{v.micro}",
    )


def check_system_deps(
    pm: str | None = None,
    doctor_config: 'DoctorPlatformConfig | None' = None,
) -> list[DepResult]:
    """Check all dependencies and return structured results."""
    if doctor_config is None:
        from trcc.core.builder import ControllerBuilder
        doctor_config = ControllerBuilder.for_current_os().build_setup().get_doctor_config()
    if pm is None:
        pm = doctor_config.pkg_manager
    results: list[DepResult] = []

    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    results.append(DepResult(
        name='Python', ok=v >= (3, 9), required=True, version=ver,
        note='' if v >= (3, 9) else 'need >= 3.9',
    ))

    for label, imp in [
        ('PySide6', 'PySide6'), ('numpy', 'numpy'),
        ('psutil', 'psutil'), ('pyusb', 'usb.core'),
    ]:
        mod_ver = get_module_version(imp)
        results.append(DepResult(
            name=label, ok=mod_ver is not None, required=True,
            version=mod_ver or '',
            install_cmd=f'pip install {label.lower()}',
        ))

    hid_ver = get_module_version('hid')
    results.append(DepResult(
        name='hidapi', ok=hid_ver is not None, required=False,
        version=hid_ver or '', install_cmd='pip install hidapi',
    ))

    if doctor_config.check_libusb:
        libusb_ok = ctypes.util.find_library('usb-1.0') is not None
        results.append(DepResult(
            name='libusb-1.0', ok=libusb_ok, required=True,
            install_cmd=_install_hint('libusb', pm),
        ))

    _binaries: list[tuple[str, bool, str]] = [
        *doctor_config.extra_binaries,
        ('7z', True, 'theme extraction'),
        ('ffmpeg', False, 'video playback'),
    ]
    for name, required, note in _binaries:
        results.append(DepResult(
            name=name, ok=shutil.which(name) is not None,
            required=required, note=note,
            install_cmd=_install_hint(name, pm),
        ))

    if pm == 'apt':
        xcb_ok = ctypes.util.find_library('xcb-cursor') is not None
        results.append(DepResult(
            name='libxcb-cursor', ok=xcb_ok, required=True,
            note='PySide6 segfaults without it',
            install_cmd=_install_hint('libxcb-cursor', pm),
        ))

    return results


def check_gpu() -> list[GpuResult]:
    """Detect GPU vendors and check matching packages."""
    from pathlib import Path  # local so tests can patch pathlib.Path
    pci_base = Path('/sys/bus/pci/devices')
    if not pci_base.exists():
        return []

    vendors: set[str] = set()
    for dev_dir in pci_base.iterdir():
        class_path = dev_dir / 'class'
        vendor_path = dev_dir / 'vendor'
        if not class_path.exists() or not vendor_path.exists():
            continue
        try:
            pci_class = class_path.read_text().strip()
            if pci_class.startswith('0x0300') or pci_class.startswith('0x0302'):
                vendors.add(vendor_path.read_text().strip().removeprefix('0x'))
        except OSError:
            continue

    results: list[GpuResult] = []
    if '10de' in vendors:
        ver = get_module_version('pynvml')
        results.append(GpuResult(
            vendor='nvidia', label='NVIDIA GPU',
            package_installed=ver is not None,
            install_cmd='pip install nvidia-ml-py',
        ))
    if '1002' in vendors:
        results.append(GpuResult(
            vendor='amd', label='AMD GPU (sensors via sysfs)',
            package_installed=True,
        ))
    if '8086' in vendors:
        results.append(GpuResult(
            vendor='intel', label='Intel GPU (sensors via sysfs)',
            package_installed=True,
        ))
    return results


def check_udev() -> UdevResult:
    """Check udev rules status (structured return)."""
    path = '/etc/udev/rules.d/99-trcc-lcd.rules'
    if not os.path.isfile(path):
        return UdevResult(ok=False, message='udev rules not installed')
    try:
        with open(path) as f:
            content = f.read()
        from trcc.adapters.device.detector import DeviceDetector
        all_devices = DeviceDetector._get_all_registries()
        all_vids = {f"{vid:04x}" for vid, _ in all_devices}
        missing = [vid for vid in sorted(all_vids) if vid not in content]
        if missing:
            return UdevResult(
                ok=False,
                message=f'udev rules outdated — missing VID(s): {", ".join(missing)}',
                missing_vids=missing,
            )
        return UdevResult(ok=True, message='udev rules installed')
    except Exception:
        return UdevResult(ok=True, message='udev rules installed')


def check_selinux() -> SelinuxResult:
    """Check if SELinux is enforcing and if USB device access is allowed."""
    try:
        r = subprocess.run(
            ['getenforce'], capture_output=True, text=True, timeout=5,
        )
        status = r.stdout.strip().lower()
    except FileNotFoundError:
        return SelinuxResult(ok=True, message='SELinux not installed')
    except Exception:
        return SelinuxResult(ok=True, message='SELinux status unknown')

    if status != 'enforcing':
        return SelinuxResult(ok=True, message=f'SELinux {status} (no policy needed)')

    try:
        r = subprocess.run(
            ['semodule', '-l'], capture_output=True, text=True, timeout=10,
        )
        if r.returncode == 0 and 'trcc_usb' in r.stdout:
            return SelinuxResult(
                ok=True, message='SELinux enforcing — trcc_usb module loaded',
                enforcing=True, module_loaded=True,
            )
    except (FileNotFoundError, Exception):
        pass

    if _selinux_usb_access_allowed():
        return SelinuxResult(
            ok=True,
            message='SELinux enforcing — USB access permitted by policy',
            enforcing=True, module_loaded=True,
        )

    return SelinuxResult(
        ok=False, message='SELinux enforcing — USB policy not installed',
        enforcing=True, module_loaded=False,
    )


def _selinux_usb_access_allowed() -> bool:
    """Check if loaded SELinux policy allows USB device access via sesearch."""
    try:
        r = subprocess.run(
            ['sesearch', '--allow', '-s', 'unconfined_t',
             '-t', 'usb_device_t', '-c', 'chr_file'],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return False
        for perm in ('ioctl', 'open', 'read', 'write'):
            if perm not in r.stdout:
                return False
        return True
    except (FileNotFoundError, Exception):
        return False


def check_rapl() -> RaplResult:
    """Check if RAPL power sensors are readable by non-root users."""
    from pathlib import Path  # local so tests can patch pathlib.Path
    rapl_base = Path('/sys/class/powercap')
    if not rapl_base.exists():
        return RaplResult(ok=True, message='No powercap subsystem', applicable=False)

    energy_files = sorted(rapl_base.glob('intel-rapl:*/energy_uj'))
    if not energy_files:
        return RaplResult(ok=True, message='No RAPL domains found', applicable=False)

    unreadable = [f for f in energy_files if not os.access(str(f), os.R_OK)]
    if unreadable:
        return RaplResult(
            ok=False,
            message=f'RAPL power sensors not readable ({len(unreadable)} domain(s))',
            domain_count=len(energy_files),
        )
    return RaplResult(
        ok=True,
        message=f'RAPL power sensors readable ({len(energy_files)} domain(s))',
        domain_count=len(energy_files),
    )


def check_polkit() -> PolkitResult:
    """Check if TRCC polkit policy is installed."""
    policy_path = '/usr/share/polkit-1/actions/com.github.lexonight1.trcc.policy'
    if os.path.isfile(policy_path):
        return PolkitResult(ok=True, message='polkit policy installed')
    return PolkitResult(ok=False, message='polkit policy not installed (dmidecode needs sudo)')


def check_desktop_entry() -> bool:
    """Check if .desktop file is installed."""
    return (Path.home() / '.local' / 'share' / 'applications' / 'trcc-linux.desktop').exists()


def run_doctor(doctor_config: 'DoctorPlatformConfig | None' = None) -> int:
    """Run dependency health check. Returns 0 if all required deps pass."""
    if doctor_config is None:
        from trcc.core.builder import ControllerBuilder
        doctor_config = ControllerBuilder.for_current_os().build_setup().get_doctor_config()

    if doctor_config.enable_ansi:
        _enable_ansi_windows()

    pm = doctor_config.pkg_manager
    all_ok = True

    print(f"\n  TRCC Doctor — {doctor_config.distro_name}\n")

    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 9):
        print(f"  {_OK}  Python {ver}")
    else:
        print(f"  {_MISS}  Python {ver} (need >= 3.9)")
        all_ok = False

    print()
    for label, imp in [
        ('PySide6', 'PySide6'), ('numpy', 'numpy'),
        ('psutil', 'psutil'), ('pyusb', 'usb.core'),
    ]:
        if not _check_python_module(label, imp, required=True, pm=pm):
            all_ok = False

    _check_python_module('hidapi', 'hid', required=False, pm=pm)

    if doctor_config.run_gpu_check:
        print()
        _check_gpu_packages()

    if doctor_config.check_libusb:
        print()
        if not _check_library('libusb-1.0', 'usb-1.0', required=True, pm=pm,
                              dep_key='libusb'):
            all_ok = False
        if pm == 'apt':
            if not _check_library('libxcb-cursor', 'xcb-cursor', required=True, pm=pm,
                                  dep_key='libxcb-cursor'):
                all_ok = False

    print()
    for name, required, note in doctor_config.extra_binaries:
        if not _check_binary(name, required=required, pm=pm, note=note):
            all_ok = False
    if not _check_binary('7z', required=True, pm=pm, note='theme extraction'):
        all_ok = False
    _check_binary('ffmpeg', required=False, pm=pm, note='video playback')

    if doctor_config.run_udev_check:
        print()
        if not _check_udev_rules():
            all_ok = False

    if doctor_config.run_selinux_check:
        se = check_selinux()
        if se.enforcing:
            print()
            if se.ok:
                print(f"  {_OK}  {se.message}")
            else:
                print(f"  {_MISS}  {se.message}")
                print("         run: sudo trcc setup-selinux")
                all_ok = False

    if doctor_config.run_rapl_check:
        print()
        _check_rapl_permissions()

    if doctor_config.run_polkit_check:
        print()
        pk = check_polkit()
        if pk.ok:
            print(f"  {_OK}  {pk.message}")
        else:
            print(f"  {_OPT}  {pk.message}")
            print("         run: trcc setup (or sudo trcc setup-polkit)")

    if doctor_config.run_winusb_check:
        print()
        _check_winusb_devices()

    print()
    if all_ok:
        print("  All required dependencies OK.\n")
        return 0
    print("  Some required dependencies are missing.\n")
    return 1


# ─────────────────────────────────────────────────────────────────────────────
# 5. Protocol debug helpers — shared by DebugReport sections + interactive CLI
# ─────────────────────────────────────────────────────────────────────────────

_KNOWN_VIDS = ("0416", "0418", "87cd", "87ad", "0402")
_UDEV_PATH = "/etc/udev/rules.d/99-trcc-lcd.rules"
_WIDTH = 60


@dataclass
class _Section:
    title: str
    lines: list[str] = field(default_factory=list)


def _hex_dump(data: bytes, max_bytes: int = 64) -> None:
    """Print a hex dump of data to stdout."""
    for row in range(0, min(len(data), max_bytes), 16):
        hex_str = ' '.join(f'{b:02x}' for b in data[row:row + 16])
        ascii_str = ''.join(
            chr(b) if 32 <= b < 127 else '.'
            for b in data[row:row + 16]
        )
        print(f"  {row:04x}: {hex_str:<48s} {ascii_str}")


def _ebusy_fallback(sec: _Section) -> None:
    """Write cached handshake data to sec when device is in use by the GUI."""
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


def _send_test_frame(protocol: Any, resolution: tuple[int, int], fbl: int) -> None:
    """Send a solid red test frame and print transfer details."""
    from trcc.core.models import JPEG_MODE_FBLS

    w, h = resolution
    print(f"\n  Sending RED test frame ({w}x{h})...")
    try:
        from trcc.services.image import ImageService

        img = ImageService.solid_color(255, 0, 0, w, h)
        is_jpeg = fbl in JPEG_MODE_FBLS
        if is_jpeg:
            data = ImageService.to_jpeg(img)
            print(f"    Encoding: JPEG ({len(data):,} bytes)")
        else:
            data = ImageService.to_rgb565(img, '<')
            print(f"    Encoding: RGB565 LE ({len(data):,} bytes)")

        packet = protocol._device.build_frame_packet(data, w, h)
        print(f"    Packet size: {len(packet):,} bytes")
        print(f"    Header: {packet[:20].hex()}")
        ok = protocol._device.send_frame(data)
        print(f"    Send result: {'OK' if ok else 'FAILED'}")
        print("    >>> Check your LCD — did it turn RED?")
    except Exception as e:
        print(f"    Test frame FAILED: {e}")


def _debug_scsi_interactive(dev: Any) -> None:
    """Interactive SCSI handshake diagnostic."""
    from trcc.adapters.device.factory import DeviceProtocolFactory
    from trcc.core.models import FBL_TO_RESOLUTION

    protocol = DeviceProtocolFactory.create_protocol(dev)
    try:
        result = protocol.handshake()
        if result is None:
            print("  Handshake returned None (poll failed)")
            return
        fbl = result.model_id
        known = "KNOWN" if fbl in FBL_TO_RESOLUTION else "UNKNOWN"
        res = result.resolution or (0, 0)
        print("  Handshake OK!")
        print(f"  FBL      = {fbl} (0x{fbl:02x})  [{known}]")
        print(f"  Resolution = {res[0]}x{res[1]}")
        print(f"  Path     = {dev.scsi_device}")
        if result.raw_response:
            print("\n  Raw handshake response (first 64 bytes):")
            _hex_dump(result.raw_response)
    finally:
        protocol.close()


def _debug_hid_lcd_interactive(dev: Any, test_frame: bool = False) -> None:
    """Interactive HID LCD handshake diagnostic."""
    from trcc.adapters.device.factory import HidProtocol
    from trcc.adapters.device.hid import HidHandshakeInfo, get_button_image
    from trcc.core.models import FBL_TO_RESOLUTION, JPEG_MODE_FBLS, fbl_to_resolution, pm_to_fbl

    protocol = HidProtocol(vid=dev.vid, pid=dev.pid, device_type=dev.device_type)
    info = protocol.handshake()

    if info is None:
        error = protocol.last_error
        print(f"  Handshake FAILED: {error}" if error
              else "  Handshake returned None (no response from device)")
        protocol.close()
        return

    assert isinstance(info, HidHandshakeInfo)
    pm = info.mode_byte_1
    sub = info.mode_byte_2
    fbl = info.fbl if info.fbl is not None else pm_to_fbl(pm, sub)
    resolution = info.resolution or fbl_to_resolution(fbl, pm)

    print("  Handshake OK!")
    print(f"  PM byte    = {pm} (0x{pm:02x})")
    print(f"  SUB byte   = {sub} (0x{sub:02x})")
    print(f"  FBL        = {fbl} (0x{fbl:02x})")
    print(f"  Serial     = {info.serial}")
    print(f"  Resolution = {resolution[0]}x{resolution[1]}")
    print(f"  Encoding   = {'JPEG' if fbl in JPEG_MODE_FBLS else 'RGB565'}")

    button = get_button_image(pm, sub)
    if button:
        print(f"  Button image = {button}")
    else:
        print(f"  Button image = unknown PM={pm} SUB={sub} (defaulting to CZTV)")

    known = "KNOWN" if fbl in FBL_TO_RESOLUTION else "UNKNOWN (not in mapping table)"
    print(f"  FBL {fbl} = {known}")

    if info.raw_response:
        print("\n  Raw handshake response (first 64 bytes):")
        _hex_dump(info.raw_response)

    if test_frame:
        _send_test_frame(protocol, resolution, fbl)

    protocol.close()


def _debug_hid_led_interactive(dev: Any) -> None:
    """Interactive HID LED handshake diagnostic."""
    from trcc.adapters.device.factory import LedProtocol
    from trcc.adapters.device.led import LedHandshakeInfo, PmRegistry

    protocol = LedProtocol(vid=dev.vid, pid=dev.pid)
    info = protocol.handshake()

    if info is None:
        error = protocol.last_error
        print(f"  Handshake FAILED: {error}" if error
              else "  Handshake returned None (no response from device)")
        protocol.close()
        return

    assert isinstance(info, LedHandshakeInfo)
    print("  Handshake OK!")
    print(f"  PM byte    = {info.pm} (0x{info.pm:02x})")
    print(f"  Sub-type   = {info.sub_type} (0x{info.sub_type:02x})")
    print(f"  Model      = {info.model_name}")

    style = info.style
    if style:
        print(f"  Style ID   = {style.style_id}")
        print(f"  LED count  = {style.led_count}")
        print(f"  Segments   = {style.segment_count}")
        print(f"  Zones      = {style.zone_count}")

    if info.pm in PmRegistry.PM_TO_STYLE:
        print(f"\n  Status: KNOWN device (PM {info.pm} in tables)")
    else:
        print(f"\n  Status: UNKNOWN PM byte ({info.pm})")
        print("  This device falls back to AX120 defaults.")
        print(f"  Please report PM {info.pm} in your GitHub issue.")

    if info.raw_response:
        print("\n  Raw handshake response (first 64 bytes):")
        _hex_dump(info.raw_response)

    protocol.close()


def _debug_bulk_interactive(dev: Any, test_frame: bool = False) -> None:
    """Interactive Bulk protocol handshake diagnostic."""
    from trcc.adapters.device.factory import BulkProtocol

    protocol = BulkProtocol(vid=dev.vid, pid=dev.pid)
    try:
        result = protocol.handshake()
        if result is None:
            error = protocol.last_error
            print(f"  Handshake FAILED: {error}" if error
                  else "  Handshake returned None (no response from device)")
            return
        print("  Handshake OK!")
        print(f"  PM byte    = {result.pm_byte} (0x{result.pm_byte:02x})")
        print(f"  SUB byte   = {result.sub_byte} (0x{result.sub_byte:02x})")
        print(f"  FBL        = {result.model_id} (0x{result.model_id:02x})")
        res = result.resolution or (0, 0)
        print(f"  Resolution = {res[0]}x{res[1]}")
        if result.serial:
            print(f"  Serial     = {result.serial}")
        if result.raw_response:
            print("\n  Raw handshake response (first 64 bytes):")
            _hex_dump(result.raw_response)
        if test_frame and result.resolution:
            _send_test_frame(protocol, result.resolution, result.model_id)
    finally:
        protocol.close()


def _debug_ly_interactive(dev: Any, test_frame: bool = False) -> None:
    """Interactive LY protocol handshake diagnostic."""
    from trcc.adapters.device.factory import LyProtocol

    protocol = LyProtocol(vid=dev.vid, pid=dev.pid)
    try:
        result = protocol.handshake()
        if result is None:
            error = protocol.last_error
            print(f"  Handshake FAILED: {error}" if error
                  else "  Handshake returned None (no response from device)")
            return
        print("  Handshake OK!")
        print(f"  PM byte    = {result.pm_byte} (0x{result.pm_byte:02x})")
        print(f"  SUB byte   = {result.sub_byte} (0x{result.sub_byte:02x})")
        print(f"  FBL        = {result.model_id} (0x{result.model_id:02x})")
        res = result.resolution or (0, 0)
        print(f"  Resolution = {res[0]}x{res[1]}")
        if result.serial:
            print(f"  Serial     = {result.serial}")
        if result.raw_response:
            print("\n  Raw handshake response (first 64 bytes):")
            _hex_dump(result.raw_response)
        if test_frame and result.resolution:
            _send_test_frame(protocol, result.resolution, result.model_id)
    finally:
        protocol.close()


# ─────────────────────────────────────────────────────────────────────────────
# 6. Interactive debug commands (CLI entry points)
# ─────────────────────────────────────────────────────────────────────────────

def device_debug(
    detect_fn: Optional[Callable[[], list[Any]]] = None,
    test_frame: bool = False,
) -> int:
    """Interactive handshake diagnostic for all connected devices.

    Routes each device to the appropriate protocol debug function.
    Output is designed to be pasted into GitHub issues.
    """
    try:
        if detect_fn is None:
            from trcc.core.builder import ControllerBuilder
            detect_fn = ControllerBuilder.for_current_os().build_detect_fn()

        print("Device Debug — Handshake Diagnostic")
        print("=" * _WIDTH)

        devices = detect_fn()
        if not devices:
            print("\nNo devices found.")
            print("Make sure the device is plugged in and try:")
            print("  trcc setup-udev   (then unplug/replug USB cable)")
            return 0

        for dev in devices:
            print(f"\nDevice: {dev.vendor_name} {dev.product_name}")
            print(f"  VID:PID        = {dev.vid:04x}:{dev.pid:04x}")
            print(f"  Protocol       = {dev.protocol.upper()}")
            print(f"  Implementation = {dev.implementation}")

            print("\n  Attempting handshake...")
            try:
                proto = dev.protocol
                if proto == 'scsi':
                    _debug_scsi_interactive(dev)
                elif proto == 'hid':
                    if dev.implementation == 'hid_led':
                        _debug_hid_led_interactive(dev)
                    else:
                        _debug_hid_lcd_interactive(dev, test_frame=test_frame)
                elif proto == 'bulk':
                    _debug_bulk_interactive(dev, test_frame=test_frame)
                elif proto == 'ly':
                    _debug_ly_interactive(dev, test_frame=test_frame)
                else:
                    print(f"  Unknown protocol: {proto}")
            except ImportError as e:
                print(f"  Missing dependency: {e}")
                print("  Install: pip install pyusb  (or pip install hidapi)")
            except Exception as e:
                print(f"  Handshake FAILED: {e}")
                import traceback
                traceback.print_exc()

        print(f"\n{'=' * _WIDTH}")
        print("Copy the output above and paste it in your GitHub issue.")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def led_debug_interactive(test_colors: bool = False) -> int:
    """Diagnose LED device — handshake, PM byte discovery, optional test colors."""
    try:
        import time

        from trcc.adapters.device.factory import LedProtocol
        from trcc.adapters.device.led import LED_PID, LED_VID, LedHandshakeInfo, PmRegistry

        print("LED Device Diagnostic")
        print("=" * 50)
        print(f"  Target: VID=0x{LED_VID:04x} PID=0x{LED_PID:04x}")

        protocol = LedProtocol(vid=LED_VID, pid=LED_PID)
        info = protocol.handshake()

        if info is None:
            error = protocol.last_error
            print(f"\nHandshake failed: {error or 'no response'}")
            protocol.close()
            return 1

        assert isinstance(info, LedHandshakeInfo)
        print(f"\n  PM byte:    {info.pm}")
        print(f"  Sub-type:   {info.sub_type}")
        print(f"  Model:      {info.model_name}")
        style = info.style
        if style is None:
            print("  Style:      (unknown — handshake returned no style)")
            protocol.close()
            return 1
        print(f"  Style ID:   {style.style_id}")
        print(f"  LED count:  {style.led_count}")
        print(f"  Segments:   {style.segment_count}")
        print(f"  Zones:      {style.zone_count}")

        if info.pm in PmRegistry.PM_TO_STYLE:
            print(f"\n  Status: KNOWN device (PM {info.pm} in tables)")
        else:
            print(f"\n  Status: UNKNOWN PM byte ({info.pm})")
            print("  This device falls back to AX120 defaults.")
            print(f"  Add PM {info.pm} to led_device.py _PM_REGISTRY.")

        if test_colors:
            print("\n  Sending test colors...")
            led_count = style.led_count
            for name, color in [("RED", (255, 0, 0)), ("GREEN", (0, 255, 0)),
                                 ("BLUE", (0, 0, 255)), ("WHITE", (255, 255, 255))]:
                protocol.send_led_data([color] * led_count, brightness=100)
                print(f"    {name}")
                time.sleep(1.5)
            protocol.send_led_data(
                [(0, 0, 0)] * led_count, global_on=False, brightness=0)
            print("    OFF")

        protocol.close()
        print("\nDone.")
        return 0

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


# ─────────────────────────────────────────────────────────────────────────────
# 7. DebugReport — the base, collects all sections for trcc report
# ─────────────────────────────────────────────────────────────────────────────

class DebugReport:
    """Collects and formats system diagnostics for GitHub issues.

    ``report_config`` and ``detect_fn`` are optional — both are resolved
    lazily from ControllerBuilder when not provided, so tests can construct
    DebugReport() with no arguments.
    """

    def __init__(
        self,
        report_config: 'ReportPlatformConfig | None' = None,
        detect_fn: Optional[Callable[[], list[Any]]] = None,
    ) -> None:
        self._sections: list[_Section] = []
        self._detected_devices: list[Any] = []
        self._config = report_config
        self._detect_fn = detect_fn

    def _get_config(self) -> 'ReportPlatformConfig':
        if self._config is None:
            from trcc.core.builder import ControllerBuilder
            self._config = ControllerBuilder.for_current_os().build_setup().get_report_config()
        return self._config

    def _get_detect_fn(self) -> Callable[[], list[Any]]:
        if self._detect_fn is None:
            from trcc.core.builder import ControllerBuilder
            self._detect_fn = ControllerBuilder.for_current_os().build_detect_fn()
        return self._detect_fn

    # ── Public API ───────────────────────────────────────────────────────────

    def collect(self) -> None:
        """Gather all diagnostic sections."""
        config = self._get_config()
        self._version()
        if config.collect_lsusb:
            self._lsusb()
        if config.collect_udev:
            self._udev_rules()
        if config.collect_selinux:
            self._selinux()
        if config.collect_rapl:
            self._rapl_permissions()
        self._dependencies()
        self._devices()
        if config.collect_device_permissions:
            self._device_permissions()
        self._handshakes()
        self._app_config()
        self._last_cpu_baseline()
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
        return "\n".join(parts)

    # ── Section helpers ──────────────────────────────────────────────────────

    def _add(self, title: str) -> _Section:
        sec = _Section(title)
        self._sections.append(sec)
        return sec

    # ── OS + env sections ────────────────────────────────────────────────────

    def _version(self) -> None:
        from trcc.__version__ import __version__

        sec = self._add("Version")
        sec.lines.append(f"  trcc-linux:  {__version__}")
        sec.lines.append(f"  Python:      {platform.python_version()}")
        sec.lines.append(f"  Installed:   {self._install_method()}")
        sec.lines.append(f"  Distro:      {self._get_config().distro_name}")
        sec.lines.append(f"  OS:          {platform.platform()}")
        sec.lines.append(f"  Kernel:      {platform.release()}")

    @staticmethod
    def _install_method() -> str:
        try:
            from trcc.conf import Settings
            info = Settings.get_install_info()
            if info and info.get('method'):
                return info['method']
        except Exception:
            pass
        try:
            from trcc.core.platform import detect_install_method
            return detect_install_method()
        except Exception:
            return "unknown"

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
            devices = self._get_detect_fn()()
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

    # ── Protocol handshake sections ──────────────────────────────────────────

    def _handshakes(self) -> None:
        sec = self._add("Handshakes")
        try:
            scsi_devs = [d for d in self._detected_devices if d.protocol == "scsi"]
            hid_devs  = [d for d in self._detected_devices if d.protocol == "hid"]
            bulk_devs = [d for d in self._detected_devices if d.protocol == "bulk"]
            ly_devs   = [d for d in self._detected_devices if d.protocol == "ly"]

            if not any([scsi_devs, hid_devs, bulk_devs, ly_devs]):
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

    def _handshake_scsi(self, dev: Any, sec: _Section) -> None:
        from trcc.adapters.device.factory import DeviceProtocolFactory
        from trcc.core.models import FBL_TO_RESOLUTION

        protocol = DeviceProtocolFactory.create_protocol(dev)
        try:
            result = protocol.handshake()
            if result is None:
                sec.lines.append("    Result: None (poll failed)")
                return
            fbl = result.model_id
            known = "KNOWN" if fbl in FBL_TO_RESOLUTION else "UNKNOWN"
            res = result.resolution or (0, 0)
            sec.lines.append(
                f"    FBL={fbl} ({known}), resolution={res[0]}x{res[1]}")
            if result.raw_response:
                sec.lines.append(f"    raw[0:64]={result.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _handshake_hid_lcd(self, dev: Any, sec: _Section) -> None:
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
                    sec.lines.append("    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(f"    Result: None ({error or 'no response'})")
                return

            assert isinstance(info, HidHandshakeInfo)
            pm = info.mode_byte_1
            sub = info.mode_byte_2
            fbl = info.fbl if info.fbl is not None else pm_to_fbl(pm, sub)
            resolution = info.resolution or fbl_to_resolution(fbl, pm)
            sec.lines.append(
                f"    PM={pm} (0x{pm:02x}), SUB={sub} (0x{sub:02x}), "
                f"FBL={fbl}, resolution={resolution[0]}x{resolution[1]}")
            if info.serial:
                sec.lines.append(f"    serial={info.serial}")
            if info.raw_response:
                sec.lines.append(f"    raw[0:64]={info.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _handshake_led(self, dev: Any, sec: _Section) -> None:
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
                    sec.lines.append("    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(f"    Result: None ({error or 'no response'})")
                return

            assert isinstance(info, LedHandshakeInfo)
            known = "KNOWN" if info.pm in PmRegistry.PM_TO_STYLE else "UNKNOWN"
            style_info = ""
            if info.style:
                style_info = (f", LEDs={info.style.led_count}, "
                              f"segments={info.style.segment_count}")
            sec.lines.append(
                f"    PM={info.pm} (0x{info.pm:02x}), SUB={info.sub_type}, "
                f"model={info.model_name}, {known}{style_info}")
            if info.raw_response:
                sec.lines.append(f"    raw[0:64]={info.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _handshake_bulk(self, dev: Any, sec: _Section) -> None:
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
                    sec.lines.append("    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(f"    Result: None ({error or 'no response'})")
                return
            sec.lines.append(
                f"    PM={result.pm_byte}, SUB={result.sub_byte}, "
                f"FBL={result.model_id}, resolution={result.resolution}, "
                f"serial={result.serial}")
            if result.raw_response:
                sec.lines.append(f"    raw[0:64]={result.raw_response[:64].hex()}")
        finally:
            protocol.close()

    def _handshake_ly(self, dev: Any, sec: _Section) -> None:
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
                    sec.lines.append("    Permission denied — run 'trcc setup-udev'")
                elif error and _has_usb_errno(error, _ERRNO_EBUSY):
                    self._ebusy_fallback(sec)
                else:
                    sec.lines.append(f"    Result: None ({error or 'no response'})")
                return
            sec.lines.append(
                f"    PM={result.pm_byte}, SUB={result.sub_byte}, "
                f"FBL={result.model_id}, resolution={result.resolution}, "
                f"serial={result.serial}")
            if result.raw_response:
                sec.lines.append(f"    raw[0:64]={result.raw_response[:64].hex()}")
        finally:
            protocol.close()

    @staticmethod
    def _ebusy_fallback(sec: _Section) -> None:
        """Write cached handshake to sec when device is in use by the GUI."""
        _ebusy_fallback(sec)

    # ── App state sections ───────────────────────────────────────────────────

    def _app_config(self) -> None:
        sec = self._add("Config")
        try:
            from trcc.conf import CONFIG_PATH, load_config

            app_config = load_config()
            if not app_config:
                sec.lines.append(f"  {CONFIG_PATH}: (empty or missing)")
                return
            sec.lines.append(f"  path: {CONFIG_PATH}")
            for key in ("resolution", "temp_unit", "format_prefs"):
                if key in app_config:
                    sec.lines.append(f"  {key}: {app_config[key]}")
            devices = app_config.get("devices", {})
            if devices:
                sec.lines.append(f"  devices: {len(devices)} configured")
        except Exception as e:
            sec.lines.append(f"  Error: {e}")

    def _last_cpu_baseline(self) -> None:
        sec = self._add("CPU baseline (last theme cache)")
        log_path = Path.home() / ".trcc" / "trcc.log"
        if not log_path.exists():
            sec.lines.append("  (no log file — load a theme in the GUI first)")
            return
        try:
            lines = log_path.read_text(errors="replace").splitlines()
            for line in reversed(lines):
                if "trcc CPU" in line:
                    sec.lines.append(f"  {line.strip()}")
                    return
            sec.lines.append("  (not found — load a theme in the GUI first)")
        except Exception as e:
            sec.lines.append(f"  Error reading log: {e}")

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
