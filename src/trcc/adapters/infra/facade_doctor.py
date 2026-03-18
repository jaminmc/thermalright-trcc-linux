"""Dependency health check for TRCC Linux.

Usage: trcc doctor

Provides both print-based checks (run_doctor) and structured-return
checks (check_*) for programmatic consumers like the setup wizard GUI.
"""

from __future__ import annotations

import ctypes.util
import os
import platform
import shutil
import sys
from dataclasses import dataclass, field

from trcc.core.platform import LINUX, WINDOWS

# ── Distro → package manager mapping ────────────────────────────────────────

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

# Fallback: ID_LIKE family → package manager
_FAMILY_TO_PM: dict[str, str] = {
    'fedora': 'dnf', 'rhel': 'dnf',
    'debian': 'apt', 'ubuntu': 'apt',
    'arch': 'pacman',
    'suse': 'zypper',
}

# ── Package names per package manager ────────────────────────────────────────

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

# sudo prefix per package manager
_INSTALL_CMD: dict[str, str] = {
    'dnf': 'sudo dnf install', 'apt': 'sudo apt install',
    'pacman': 'sudo pacman -S', 'zypper': 'sudo zypper install',
    'xbps': 'sudo xbps-install', 'apk': 'sudo apk add',
    'emerge': 'sudo emerge', 'eopkg': 'sudo eopkg install',
    'rpm-ostree': 'sudo rpm-ostree install', 'swupd': 'sudo swupd bundle-add',
    'winget': 'winget install', 'brew': 'brew install',
    'pkg': 'sudo pkg install',
}


# ── Distro detection ────────────────────────────────────────────────────────

def _read_os_release() -> dict[str, str]:
    """Read /etc/os-release into a dict."""
    # Python 3.10+ API
    _os_release = getattr(platform, 'freedesktop_os_release', None)
    if _os_release is not None:
        try:
            return _os_release()
        except OSError:
            pass
    # Fallback for Python < 3.10 or missing file
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
    """Detect the system package manager."""
    from trcc.core.platform import BSD, MACOS, WINDOWS

    if WINDOWS:
        return 'winget' if shutil.which('winget') else None
    if MACOS:
        return 'brew' if shutil.which('brew') else None
    if BSD:
        return 'pkg' if shutil.which('pkg') else None

    # Linux: detect from os-release
    info = _read_os_release()
    distro_id = info.get('ID', '').lower()

    # Exact match
    if pm := _DISTRO_TO_PM.get(distro_id):
        return pm

    # ID_LIKE fallback (space-separated list of parent distros)
    for like in info.get('ID_LIKE', '').lower().split():
        if pm := _FAMILY_TO_PM.get(like):
            return pm

    return None


def _provides_search(dep: str, pm: str) -> str | None:
    """Use PM's native 'provides' to find which package owns a file.

    Best-effort fallback for deps not in ``_INSTALL_MAP``.  Returns the
    package name or ``None``.  Runs with a 15 s timeout so the wizard
    never hangs.
    """
    import re
    import subprocess

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
            # "sg3_utils-1.47-3.fc43.x86_64 : Utilities for SCSI"
            m = re.match(r'([\w][\w.+-]*)-\d', first)
            return m.group(1) if m else None
        if pm == 'pacman':
            # "extra/sg3_utils" → "sg3_utils"
            return first.split('/')[-1].strip() or None
        if pm == 'zypper':
            # Table: "i | pkg-name | Summary | ..."
            for line in r.stdout.strip().split('\n'):
                parts = [p.strip() for p in line.split('|')]
                if len(parts) >= 2 and parts[1] and parts[1] != 'Name':
                    return parts[1]
            return None
        if pm == 'apk':
            # "p7zip-17.05-r0" → "p7zip"
            m = re.match(r'([\w][\w.+-]*)-\d', first)
            return m.group(1) if m else None
        if pm == 'xbps':
            # "[*] sg3_utils-1.47_1  Utilities" → "sg3_utils"
            m = re.search(r'[\]\\s]+([\w][\w.+-]*)-\d', first)
            return m.group(1) if m else None

        return None
    except (subprocess.TimeoutExpired, FileNotFoundError, OSError):
        return None


def _install_hint(dep: str, pm: str | None) -> str:
    """Build 'sudo dnf install pkg' string, or generic fallback."""
    if pm and dep in _INSTALL_MAP and pm in _INSTALL_MAP[dep]:
        cmd = _INSTALL_CMD.get(pm, f'sudo {pm} install')
        return f"{cmd} {_INSTALL_MAP[dep][pm]}"

    # PM detected but dep not mapped — try native provides search
    if pm:
        pkg = _provides_search(dep, pm)
        if pkg:
            cmd = _INSTALL_CMD.get(pm, f'sudo {pm} install')
            return f"{cmd} {pkg}"

    if dep in _INSTALL_MAP:
        # Show all distros as fallback
        lines = [f"  {_INSTALL_CMD.get(m, m)} {pkg}"
                 for m, pkg in _INSTALL_MAP[dep].items()]
        return "install one of:\n" + "\n".join(lines)
    return f"install {dep}"


# ── Check helpers ────────────────────────────────────────────────────────────

def get_module_version(import_name: str) -> str | None:
    """Get version string for a Python module, or None if not installed.

    Handles PySide6 (version attribute), hidapi (tuple version), and
    standard __version__ / version attributes.
    """
    try:
        mod = __import__(import_name)
        ver = getattr(mod, '__version__', getattr(mod, 'version', ''))
        if isinstance(ver, tuple):
            ver = '.'.join(str(x) for x in ver)
        # PySide6 stores version in PySide6.__version__
        if not ver and import_name == 'PySide6':
            try:
                import PySide6
                ver = PySide6.__version__
            except ImportError:
                pass
        return str(ver) if ver else ''
    except ImportError:
        return None


def _enable_ansi_windows() -> None:
    """Enable ANSI escape codes on Windows (virtual terminal processing)."""
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
        # STD_OUTPUT_HANDLE = -11, ENABLE_VIRTUAL_TERMINAL_PROCESSING = 0x0004
        handle = kernel32.GetStdHandle(-11)
        mode = ctypes.c_ulong()
        kernel32.GetConsoleMode(handle, ctypes.byref(mode))
        kernel32.SetConsoleMode(handle, mode.value | 0x0004)
    except Exception:
        pass


if WINDOWS:
    _enable_ansi_windows()

_OK = "\033[32m[OK]\033[0m"
_MISS = "\033[31m[MISSING]\033[0m"
_OPT = "\033[33m[--]\033[0m"


def _check_python_module(
    label: str, import_name: str, required: bool, pm: str | None,
) -> bool:
    """Try importing a Python module. Print status. Return True if OK."""
    ver = get_module_version(import_name)
    if ver is not None:
        ver_str = f" {ver}" if ver else ""
        print(f"  {_OK}  {label}{ver_str}")
        return True
    if required:
        print(f"  {_MISS}  {label} — pip install {label.lower()}")
        return False
    print(f"  {_OPT}  {label} not installed (optional)")
    return True  # optional — not a failure


def _check_binary(
    name: str, required: bool, pm: str | None, note: str = '',
) -> bool:
    """Check if a CLI binary is on PATH. Return True if OK."""
    if shutil.which(name):
        print(f"  {_OK}  {name}")
        return True
    suffix = f" ({note})" if note else ""
    hint = _install_hint(name, pm)
    if required:
        print(f"  {_MISS}  {name} — {hint}{suffix}")
        return False
    print(f"  {_OPT}  {name} not found — {hint}{suffix}")
    return True  # optional


def _check_library(
    label: str, so_name: str, required: bool, pm: str | None,
    dep_key: str = '',
) -> bool:
    """Check if a shared library is loadable. Return True if OK."""
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
    """Print GPU detection results (delegates to check_gpu())."""
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
    """Print udev rules check (delegates to check_udev())."""
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
    """Print RAPL sensor check (delegates to check_rapl())."""
    result = check_rapl()
    if not result.applicable:
        return True
    if result.ok:
        print(f"  {_OK}  RAPL power sensors ({result.domain_count} domain(s))")
    else:
        print(f"  {_OPT}  RAPL power sensors not readable — run: trcc setup-udev")
    return result.ok


# ── Structured check results (for setup wizard GUI) ──────────────────────────

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
    vendor: str           # 'nvidia', 'amd', 'intel'
    label: str            # 'NVIDIA GPU detected'
    package_installed: bool
    install_cmd: str = ''  # 'pip install nvidia-ml-py' or ''


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


def get_setup_info() -> SetupInfo:
    """Get system info for setup wizard."""
    from trcc.core.platform import BSD, MACOS, WINDOWS

    v = sys.version_info
    if WINDOWS:
        distro = f"Windows {platform.version()}"
    elif MACOS:
        distro = f"macOS {platform.mac_ver()[0]}"
    elif BSD:
        distro = f"FreeBSD {platform.release()}"
    else:
        distro = _read_os_release().get('PRETTY_NAME', 'Unknown Linux')
    return SetupInfo(
        distro=distro,
        pkg_manager=_detect_pkg_manager(),
        python_version=f"{v.major}.{v.minor}.{v.micro}",
    )


def check_system_deps(pm: str | None = None) -> list[DepResult]:
    """Check all dependencies and return structured results."""
    if pm is None:
        pm = _detect_pkg_manager()
    results: list[DepResult] = []

    # Python version
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    results.append(DepResult(
        name='Python', ok=v >= (3, 9), required=True, version=ver,
        note='' if v >= (3, 9) else 'need >= 3.9',
    ))

    # Python modules (required)
    for label, imp in [
        ('PySide6', 'PySide6'), ('Pillow', 'PIL'), ('numpy', 'numpy'),
        ('psutil', 'psutil'), ('pyusb', 'usb.core'),
    ]:
        mod_ver = get_module_version(imp)
        results.append(DepResult(
            name=label, ok=mod_ver is not None, required=True,
            version=mod_ver or '',
            install_cmd=f'pip install {label.lower()}',
        ))

    # Python modules (optional)
    hid_ver = get_module_version('hid')
    results.append(DepResult(
        name='hidapi', ok=hid_ver is not None, required=False,
        version=hid_ver or '', install_cmd='pip install hidapi',
    ))

    from trcc.core.platform import LINUX, WINDOWS

    # System libraries — libusb (not needed on Windows, WinUSB provides it)
    if not WINDOWS:
        libusb_ok = ctypes.util.find_library('usb-1.0') is not None
        results.append(DepResult(
            name='libusb-1.0', ok=libusb_ok, required=True,
            install_cmd=_install_hint('libusb', pm),
        ))

    # System binaries
    _binaries: list[tuple[str, bool, str]] = [
        ('7z', True, 'theme extraction'),
        ('ffmpeg', False, 'video playback'),
    ]
    if LINUX:
        _binaries.insert(0, ('sg_raw', True, 'SCSI LCD devices'))

    for name, required, note in _binaries:
        results.append(DepResult(
            name=name, ok=shutil.which(name) is not None,
            required=required, note=note,
            install_cmd=_install_hint(name, pm),
        ))

    # libxcb-cursor — apt distros only (Ubuntu 22.04+ segfaults without it)
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
    from pathlib import Path

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


@dataclass
class SelinuxResult:
    """Result of SELinux policy check."""
    ok: bool
    message: str
    enforcing: bool = False
    module_loaded: bool = False


def check_selinux() -> SelinuxResult:
    """Check if SELinux is enforcing and if USB device access is allowed.

    Returns ok=True when no action is needed: SELinux absent, permissive,
    disabled, or enforcing with USB access already permitted (via trcc_usb
    module or base policy).

    Detection order:
    1. ``semodule -l`` — checks module list (requires root)
    2. ``sesearch`` — queries loaded kernel policy (works without root)
    """
    import subprocess

    # Check if SELinux is present and enforcing
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

    # SELinux is enforcing — check if trcc_usb module is loaded
    # semodule -l requires root; try it first, fall back to sesearch
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

    # semodule failed (non-root) or module not listed — check if the
    # needed USB permissions exist in the loaded policy via sesearch
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
    """Check if the loaded SELinux policy allows USB device access.

    Uses ``sesearch`` to query the kernel policy — works without root.
    Our trcc_usb module grants:
        allow unconfined_t usb_device_t:chr_file { ioctl open read write }
    The base policy may already cover this via attribute rules.
    """
    import subprocess

    try:
        r = subprocess.run(
            ['sesearch', '--allow', '-s', 'unconfined_t',
             '-t', 'usb_device_t', '-c', 'chr_file'],
            capture_output=True, text=True, timeout=10,
        )
        if r.returncode != 0:
            return False
        # Check that all required permissions are present
        for perm in ('ioctl', 'open', 'read', 'write'):
            if perm not in r.stdout:
                return False
        return True
    except (FileNotFoundError, Exception):
        return False


@dataclass
class RaplResult:
    """Result of RAPL power sensor check."""
    ok: bool
    message: str
    applicable: bool = True   # False if no powercap subsystem
    domain_count: int = 0


def check_rapl() -> RaplResult:
    """Check if RAPL power sensors are readable by non-root users."""
    from pathlib import Path

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


@dataclass
class PolkitResult:
    """Result of polkit policy check."""
    ok: bool
    message: str


def check_polkit() -> PolkitResult:
    """Check if TRCC polkit policy is installed for passwordless dmidecode/smartctl."""
    policy_path = '/usr/share/polkit-1/actions/com.github.lexonight1.trcc.policy'
    if os.path.isfile(policy_path):
        return PolkitResult(ok=True, message='polkit policy installed')
    return PolkitResult(ok=False, message='polkit policy not installed (dmidecode needs sudo)')


def check_desktop_entry() -> bool:
    """Check if .desktop file is installed."""
    from pathlib import Path
    return (Path.home() / '.local' / 'share' / 'applications' / 'trcc-linux.desktop').exists()


# ── Main entry point ─────────────────────────────────────────────────────────

def run_doctor() -> int:
    """Run dependency health check. Returns 0 if all required deps pass."""
    pm = _detect_pkg_manager()
    if LINUX:
        distro = _read_os_release().get('PRETTY_NAME', 'Unknown')
    else:
        distro = platform.platform()
    all_ok = True

    print(f"\n  TRCC Doctor — {distro}\n")

    # Python version
    v = sys.version_info
    ver = f"{v.major}.{v.minor}.{v.micro}"
    if v >= (3, 9):
        print(f"  {_OK}  Python {ver}")
    else:
        print(f"  {_MISS}  Python {ver} (need >= 3.9)")
        all_ok = False

    # Python modules (required)
    print()
    for label, imp in [
        ('PySide6', 'PySide6'),
        ('Pillow', 'PIL'),
        ('numpy', 'numpy'),
        ('psutil', 'psutil'),
        ('pyusb', 'usb.core'),
    ]:
        if not _check_python_module(label, imp, required=True, pm=pm):
            all_ok = False

    # Python modules (optional)
    _check_python_module('hidapi', 'hid', required=False, pm=pm)

    # GPU detection
    print()
    _check_gpu_packages()

    # Linux-only checks — system libraries, binaries, udev, SELinux, RAPL, polkit
    if LINUX:
        # System libraries
        print()
        if not _check_library('libusb-1.0', 'usb-1.0', required=True, pm=pm,
                              dep_key='libusb'):
            all_ok = False
        if pm == 'apt':
            if not _check_library('libxcb-cursor', 'xcb-cursor', required=True, pm=pm,
                                  dep_key='libxcb-cursor'):
                all_ok = False

        # System binaries
        print()
        if not _check_binary('sg_raw', required=True, pm=pm,
                             note='SCSI LCD devices'):
            all_ok = False
        if not _check_binary('7z', required=True, pm=pm,
                             note='theme extraction'):
            all_ok = False
        _check_binary('ffmpeg', required=False, pm=pm, note='video playback')

        # udev rules
        print()
        if not _check_udev_rules():
            all_ok = False

        # SELinux
        se = check_selinux()
        if se.enforcing:
            print()
            if se.ok:
                print(f"  {_OK}  {se.message}")
            else:
                print(f"  {_MISS}  {se.message}")
                print("         run: sudo trcc setup-selinux")
                all_ok = False

        # RAPL power sensors
        print()
        _check_rapl_permissions()

        # Polkit policy
        print()
        pk = check_polkit()
        if pk.ok:
            print(f"  {_OK}  {pk.message}")
        else:
            print(f"  {_OPT}  {pk.message}")
            print("         run: trcc setup (or sudo trcc setup-polkit)")

    # Windows-only: check for devices needing WinUSB
    if WINDOWS:
        print()
        _check_winusb_devices()

    # Summary
    print()
    if all_ok:
        print("  All required dependencies OK.\n")
        return 0
    print("  Some required dependencies are missing.\n")
    return 1


def _check_winusb_devices() -> None:
    """Check if connected devices need WinUSB driver (Windows only)."""
    try:
        import wmi as wmi_mod  # pyright: ignore[reportMissingImports]
    except ImportError:
        return

    from trcc.adapters.device.detector import (
        _BULK_DEVICES,
        _HID_LCD_DEVICES,
        _LED_DEVICES,
        _LY_DEVICES,
    )
    winusb_registries = {**_BULK_DEVICES, **_HID_LCD_DEVICES,
                         **_LED_DEVICES, **_LY_DEVICES}

    try:
        w = wmi_mod.WMI()
        for usb in w.Win32_PnPEntity():
            dev_id = getattr(usb, 'DeviceID', '') or ''
            if 'VID_' not in dev_id:
                continue
            import re
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
