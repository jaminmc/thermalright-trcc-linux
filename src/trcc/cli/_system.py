"""System setup and administration commands."""
from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

from trcc.core.platform import LINUX, detect_install_method, is_root

# Backward compat — internal callers use _is_root()
_is_root = is_root


def _require_linux(command: str) -> int | None:
    """Return error code if not on Linux, None if OK to proceed."""
    if not LINUX:
        print(f"'{command}' is for Linux only.")
        if sys.platform == 'win32':
            print("On Windows, use: trcc setup-winusb")
        return 1
    return None


# Setup functions moved to adapters/setup/facade_linux.py — import from there
from trcc.adapters.setup.facade_linux import (  # noqa: E402,F401
    _real_user_home,
    install_desktop,
    setup_polkit,
    setup_selinux,
    setup_udev,
)


def _sudo_run(cmd):
    """Run a command with sudo prepended. Returns subprocess.CompletedProcess."""
    return subprocess.run(["sudo"] + cmd)


def show_info(*, preview: bool = False, metric: str | None = None):
    """Show system metrics, optionally as ANSI terminal art.

    Args:
        preview: Render metrics as ANSI colored dashboard.
        metric: Filter to a group — cpu, gpu, mem, disk, net, fan, time.
    """
    try:
        from trcc.cli import _ensure_system
        from trcc.services.system import format_metric, get_all_metrics

        _ensure_system()
        metrics = get_all_metrics()

        if preview:
            from trcc.services import ImageService
            print(ImageService.metrics_to_ansi(metrics, group=metric))
            return 0

        # Text output (original behavior)
        print("System Information")
        print("=" * 40)

        groups = [
            ("CPU", ['cpu_temp', 'cpu_percent', 'cpu_freq', 'cpu_power']),
            ("GPU", ['gpu_temp', 'gpu_usage', 'gpu_clock', 'gpu_power']),
            ("Memory", ['mem_temp', 'mem_percent', 'mem_clock', 'mem_available']),
            ("Disk", ['disk_temp', 'disk_activity', 'disk_read', 'disk_write']),
            ("Network", ['net_up', 'net_down', 'net_total_up', 'net_total_down']),
            ("Fan", ['fan_cpu', 'fan_gpu', 'fan_ssd', 'fan_sys2']),
            ("Date/Time", ['date', 'time', 'weekday']),
        ]

        # Filter if metric specified
        if metric:
            key = metric.lower()
            alias = {'mem': 'Memory', 'cpu': 'CPU', 'gpu': 'GPU',
                     'disk': 'Disk', 'net': 'Network', 'fan': 'Fan',
                     'time': 'Date/Time'}
            target = alias.get(key)
            if target:
                groups = [(lb, ks) for lb, ks in groups if lb == target]

        for label, keys in groups:
            print(f"\n{label}:")
            for key in keys:
                val = getattr(metrics, key, None)
                if val is not None and (val != 0.0 or key in ('date', 'time', 'weekday')):
                    print(f"  {key}: {format_metric(key, val)}")

        return 0
    except Exception as e:
        print(f"Error getting metrics: {e}")
        return 1


# setup_udev, setup_selinux, setup_polkit, install_desktop,
# _setup_rapl_permissions — all imported from adapters/setup/facade_linux.py
# (see import block above). CLI entry points in __init__.py call them directly.


def setup_winusb():
    """Guide WinUSB driver installation for Thermalright USB devices (Windows only).

    SCSI devices (Frozen Warframe, Elite Vision, etc.) use the default
    USB Mass Storage driver and need no extra setup.

    HID, Bulk, and LY devices need WinUSB — installed via Zadig.
    """
    from trcc.core.platform import WINDOWS
    if not WINDOWS:
        print("This command is for Windows only.")
        print("On Linux, use: trcc setup-udev")
        return 1

    # Detect which devices are connected and need WinUSB
    from trcc.adapters.device.detector import (
        _BULK_DEVICES,
        _HID_LCD_DEVICES,
        _LED_DEVICES,
        _LY_DEVICES,
    )
    winusb_vids = set()
    for registry in (_BULK_DEVICES, _HID_LCD_DEVICES, _LED_DEVICES, _LY_DEVICES):
        for vid, pid in registry:
            winusb_vids.add((vid, pid))

    print("\n  TRCC WinUSB Driver Setup\n")
    print("  SCSI devices (Frozen Warframe, Elite Vision, CZTV, etc.)")
    print("  use the default USB Mass Storage driver — no setup needed.\n")
    print("  HID, Bulk, and LY devices need the WinUSB driver.")
    print("  Install it using Zadig (free, open-source):\n")
    print("  1. Download Zadig: https://zadig.akeo.ie/")
    print("  2. Run Zadig → Options → List All Devices")
    print("  3. Select your Thermalright device from the dropdown")
    print("  4. Set target driver to WinUSB")
    print("  5. Click 'Replace Driver' (or 'Install Driver')")
    print("  6. Replug the USB device\n")
    print("  Devices that need WinUSB:")
    for vid, pid in sorted(winusb_vids):
        # Look up friendly name
        for registry in (_BULK_DEVICES, _HID_LCD_DEVICES, _LED_DEVICES, _LY_DEVICES):
            if (vid, pid) in registry:
                entry = registry[(vid, pid)]
                print(f"    {vid:04X}:{pid:04X}  {entry.product}")
                break
    print()
    return 0


# _detect_install_method moved to core/platform.py as detect_install_method()
_detect_install_method = detect_install_method


def _is_externally_managed() -> bool:
    """Check if the Python environment has PEP 668 EXTERNALLY-MANAGED marker."""
    # The marker file lives next to the stdlib, e.g.
    # /usr/lib/python3.12/EXTERNALLY-MANAGED
    stdlib = Path(os.__file__).parent
    return (stdlib / "EXTERNALLY-MANAGED").exists()


def uninstall(*, yes: bool = False):
    """Remove all TRCC config, udev rules, autostart, and desktop files."""

    from trcc.conf import Settings

    # Clear resolution markers before wiping config dir
    Settings.clear_installed_resolutions()

    home = _real_user_home()

    # Files that require root to remove (Linux only)
    root_files = [
        "/etc/udev/rules.d/99-trcc-lcd.rules",
        "/etc/modprobe.d/trcc-lcd.conf",
        "/etc/modules-load.d/trcc-sg.conf",
        "/usr/share/polkit-1/actions/com.github.lexonight1.trcc.policy",
        "/etc/polkit-1/rules.d/50-trcc.rules",
    ] if LINUX else []

    # User files/dirs to remove
    user_items = [
        home / ".trcc",                                      # all trcc data + config
    ]
    # Glob for any trcc autostart/desktop files (catches current + legacy names)
    for d in (home / ".config" / "autostart", home / ".local" / "share" / "applications"):
        if d.is_dir():
            user_items.extend(d.glob("trcc*.desktop"))

    removed = []

    # Handle root files — auto-elevate with sudo if needed
    root_exists = [p for p in root_files if os.path.exists(p)]
    if root_exists and not _is_root():
        print("Root files found — requesting sudo to remove...")
        result = _sudo_run(["rm", "-f"] + root_exists)
        if result.returncode == 0:
            removed.extend(root_exists)
            _sudo_run(["udevadm", "control", "--reload-rules"])
            _sudo_run(["udevadm", "trigger"])
    else:
        for path_str in root_exists:
            os.remove(path_str)
            removed.append(path_str)

    # Handle user files/dirs
    for path in user_items:
        if path.exists():
            if path.is_dir():
                shutil.rmtree(path)
            else:
                path.unlink()
            removed.append(str(path))

    if removed:
        print("Removed:")
        for item in removed:
            print(f"  {item}")
    else:
        print("Nothing to remove — TRCC is already clean.")

    # Reload udev if we removed rules (and we're root — non-root already did it above)
    if _is_root() and any("udev" in r for r in removed):
        subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
        subprocess.run(["udevadm", "trigger"], check=False)

    # Detect install method and uninstall the package accordingly
    install_info = Settings.get_install_info()
    method = install_info.get('method', _detect_install_method())

    if method in ('pacman', 'dnf', 'apt'):
        # System package — tell user to remove via their package manager
        pkg_cmds = {
            'pacman': 'sudo pacman -R trcc-linux',
            'dnf': 'sudo dnf remove trcc-linux',
            'apt': 'sudo apt remove trcc-linux',
        }
        print(f"\nInstalled via {method} — remove with:")
        print(f"  {pkg_cmds[method]}")
    elif method == 'pipx':
        print("\nUninstalling trcc-linux via pipx...")
        subprocess.run(["pipx", "uninstall", "trcc-linux"], check=False)
    else:
        # pip install — may need --break-system-packages on PEP 668 distros
        print("\nUninstalling trcc-linux pip package...")
        pip_cmd = [sys.executable, "-m", "pip", "uninstall", "trcc-linux"]
        if yes:
            pip_cmd.append("--yes")
        if _is_externally_managed():
            pip_cmd.append("--break-system-packages")
        subprocess.run(pip_cmd, check=False)

    # Clean stale shadow binary from old pip/pipx installs
    stale_bin = _real_user_home() / ".local" / "bin" / "trcc"
    if stale_bin.exists():
        stale_bin.unlink()
        print(f"Removed stale binary: {stale_bin}")

    return 0


def report():
    """Generate a full diagnostic report for bug reports."""
    from trcc.adapters.infra.debug_report import DebugReport
    from trcc.adapters.infra.doctor import run_doctor

    rpt = DebugReport()
    rpt.collect()
    print(rpt)
    run_doctor()
    print("Copy everything above and paste it into your GitHub issue:")
    print("  https://github.com/Lexonight1/thermalright-trcc-linux/issues/new")
    return 0


def download_themes(pack=None, show_list=False, force=False, show_info=False):
    """Download theme packs (like spacy download)."""
    try:
        from trcc.adapters.infra.theme_downloader import download_pack, list_available
        from trcc.adapters.infra.theme_downloader import show_info as pack_info

        if show_list or pack is None:
            list_available()
            return 0

        if show_info:
            pack_info(pack)
            return 0

        if force:
            from trcc.conf import Settings
            Settings.clear_installed_resolutions()

        return download_pack(pack, force=force)

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()
        return 1


def _confirm(prompt: str, auto_yes: bool) -> bool:
    """Ask [Y/n] question. Returns True on yes/enter, False on n."""
    if auto_yes:
        print(f"  {prompt} [Y/n]: y (auto)")
        return True
    try:
        answer = input(f"  {prompt} [Y/n]: ").strip().lower()
        return answer in ('', 'y', 'yes')
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def run_setup(auto_yes: bool = False) -> int:
    """Interactive setup wizard — dispatches to platform-specific adapter."""
    from trcc.core.builder import ControllerBuilder
    return ControllerBuilder.build_setup().run(auto_yes=auto_yes)
