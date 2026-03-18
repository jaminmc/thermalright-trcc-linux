"""System setup and administration commands."""
from __future__ import annotations

import os
import shutil
import site
import subprocess
import sys
from pathlib import Path

from trcc.cli import _cli_handler
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


def _real_user_home() -> Path:
    """Return the real (non-root) user's home directory.

    Under sudo, ``Path.home()`` returns ``/root/``.  Check ``SUDO_USER``
    first so that desktop entries and icons land in the actual user's
    ``~/.local/`` instead of root's.
    """
    sudo_user = os.environ.get("SUDO_USER")
    if sudo_user and sudo_user != "root":
        import pwd
        return Path(pwd.getpwnam(sudo_user).pw_dir)
    return Path.home()


def _sudo_reexec(subcommand):
    """Re-exec `trcc <subcommand>` as root via sudo with correct PYTHONPATH.

    sudo strips user site-packages (~/.local/lib), so we include both
    the trcc package root and all site-packages where dependencies live.

    PYTHONPATH order: system site-packages first, then user site-packages,
    then the trcc package root last. This ensures pip-installed dependencies
    take priority over dev clones that might shadow them.
    """
    paths: list[str] = []
    paths.extend(site.getsitepackages())
    paths.append(site.getusersitepackages())
    # trcc package root last — prevents dev clones from shadowing pip installs
    trcc_pkg = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    paths.append(trcc_pkg)
    pythonpath = os.pathsep.join(paths)
    cmd = [
        "sudo", "env", f"PYTHONPATH={pythonpath}",
        sys.executable, "-m", "trcc.cli", subcommand,
    ]
    print("Root required — requesting sudo...")
    result = subprocess.run(cmd)
    if result.returncode != 0:
        print(f"\n  sudo re-exec failed (exit {result.returncode}).")
        print(f"  Try running directly:  sudo trcc {subcommand}")
        print(f"  Or with full path:     sudo {sys.executable} -m trcc.cli {subcommand}")
    return result.returncode


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


def _setup_rapl_permissions():
    """Make Intel/AMD RAPL energy counters readable by non-root users.

    Newer kernels (5.10+) restrict powercap sysfs to root only (Platypus
    side-channel mitigation). This writes a tmpfiles.d rule for persistence
    across reboots, and chmods existing files for immediate effect.
    """
    rapl_base = Path("/sys/class/powercap")
    if not rapl_base.exists():
        return  # No powercap subsystem — nothing to do

    # Find all top-level RAPL energy files (skip sub-zones like intel-rapl:0:0)
    energy_files = sorted(rapl_base.glob("intel-rapl:*/energy_uj"))
    if not energy_files:
        return  # No RAPL domains found

    # Write tmpfiles.d rule (persistent across reboots)
    tmpfiles_path = "/etc/tmpfiles.d/trcc-rapl.conf"
    lines = [
        "# Thermalright TRCC — allow non-root CPU power reading (RAPL)",
        "# Auto-generated by trcc setup-udev",
    ]
    for energy_file in energy_files:
        lines.append(f"z {energy_file} 0444 root root -")
    tmpfiles_content = "\n".join(lines) + "\n"

    with open(tmpfiles_path, "w") as f:
        f.write(tmpfiles_content)
    print(f"Wrote {tmpfiles_path}")

    # Apply immediately (chmod existing files)
    for energy_file in energy_files:
        try:
            energy_file.chmod(0o444)
        except OSError:
            pass
    print(f"RAPL power sensors: {len(energy_files)} domain(s) made readable")

    # SELinux: restorecon if available
    restorecon = subprocess.run(
        ["which", "restorecon"], capture_output=True, text=True,
    )
    if restorecon.returncode == 0:
        subprocess.run(
            ["restorecon", tmpfiles_path], capture_output=True, check=False,
        )


@_cli_handler
def setup_udev(dry_run=False):
    """Generate and install udev rules + USB storage quirks from KNOWN_DEVICES.

    Without quirks, UAS claims these LCD devices and the kernel ignores them
    (no /dev/sgX created). The :u quirk forces usb-storage bulk-only transport.
    """
    if err := _require_linux("setup-udev"):
        return err
    from trcc.adapters.device.detector import (
        _BULK_DEVICES,
        _HID_LCD_DEVICES,
        _LED_DEVICES,
        _LY_DEVICES,
        KNOWN_DEVICES,
    )

    # Always include ALL devices in udev rules (so hardware is ready
    # when users plug in HID/bulk devices, even without --testing-hid)
    all_devices = {**KNOWN_DEVICES, **_HID_LCD_DEVICES, **_LED_DEVICES, **_BULK_DEVICES, **_LY_DEVICES}

    # --- 1. udev rules (permissions) ---
    rules_path = "/etc/udev/rules.d/99-trcc-lcd.rules"
    rules_lines = ["# Thermalright LCD/LED cooler devices — auto-generated by trcc setup-udev"]

    from trcc.core.models import PROTOCOL_TRAITS

    for (vid, pid), info in sorted(all_devices.items()):
        vendor = info.vendor
        product = info.product
        traits = PROTOCOL_TRAITS.get(info.protocol, PROTOCOL_TRAITS['scsi'])
        rule_parts = [f'# {vendor} {product}']
        for subsystem in traits.udev_subsystems:
            # hidraw/scsi_generic use ATTRS (parent match), usb uses ATTR (direct)
            attr = 'ATTRS' if subsystem in ('hidraw', 'scsi_generic') else 'ATTR'
            rule_parts.append(
                f'SUBSYSTEM=="{subsystem}", '
                f'{attr}{{idVendor}}=="{vid:04x}", '
                f'{attr}{{idProduct}}=="{pid:04x}", '
                f'MODE="0666"'
            )
        rules_lines.append('\n'.join(rule_parts))

    rules_content = "\n\n".join(rules_lines) + "\n"

    # --- 2. usb-storage quirks (UAS bypass) ---
    quirk_entries = [f"{vid:04x}:{pid:04x}:u" for vid, pid in sorted(KNOWN_DEVICES)]
    quirks_param = ",".join(quirk_entries)

    # modprobe config (persistent across reboots)
    modprobe_path = "/etc/modprobe.d/trcc-lcd.conf"
    modprobe_content = (
        "# Thermalright LCD — force usb-storage bulk-only (bypass UAS)\n"
        "# Without this, devices are ignored and /dev/sgX is never created\n"
        "# Auto-generated by trcc setup-udev\n"
        f"options usb-storage quirks={quirks_param}\n"
    )

    if dry_run:
        print("=== udev rules ===")
        print(rules_content)
        print(f"# Would write to {rules_path}\n")
        print("=== usb-storage quirks ===")
        print(modprobe_content)
        print(f"# Would write to {modprobe_path}\n")
        print("=== sg module autoload ===")
        print("sg")
        print("# Would write to /etc/modules-load.d/trcc-sg.conf")
        return 0

    # Need root — re-exec with sudo automatically
    if not _is_root():
        return _sudo_reexec("setup-udev")

    # Write udev rules
    with open(rules_path, "w") as f:
        f.write(rules_content)
    print(f"Wrote {rules_path}")

    # Write modprobe config
    with open(modprobe_path, "w") as f:
        f.write(modprobe_content)
    print(f"Wrote {modprobe_path}")

    # Apply quirks immediately (without reboot)
    quirks_sysfs = "/sys/module/usb_storage/parameters/quirks"
    if os.path.exists(quirks_sysfs):
        with open(quirks_sysfs, "w") as f:
            f.write(quirks_param)
        print(f"Applied quirks: {quirks_param}")

    # --- 3. Ensure sg (SCSI generic) kernel module loads on boot ---
    # Some distros (CachyOS, Arch) don't load sg by default. Without it,
    # SCSI USB devices only get /dev/sdX (block) but no /dev/sgX.
    # Our detector falls back to block devices, but sg is still preferred.
    modules_load_path = "/etc/modules-load.d/trcc-sg.conf"
    modules_load_content = (
        "# Thermalright LCD — ensure SCSI generic (/dev/sgX) is available\n"
        "# Without this, some distros only create /dev/sdX for USB mass storage\n"
        "# Auto-generated by trcc setup-udev\n"
        "sg\n"
    )
    with open(modules_load_path, "w") as f:
        f.write(modules_load_content)
    print(f"Wrote {modules_load_path}")

    # Load sg immediately (no reboot needed)
    subprocess.run(["modprobe", "sg"], check=False, capture_output=True)

    # --- 4. RAPL power sensor permissions ---
    # Newer kernels (5.10+) restrict /sys/class/powercap/ to root only,
    # preventing non-root apps from reading CPU package power.
    # tmpfiles.d rule makes permissions persistent across reboots.
    _setup_rapl_permissions()

    # Reload udev
    subprocess.run(["udevadm", "control", "--reload-rules"], check=False)
    subprocess.run(["udevadm", "trigger"], check=False)
    print("\nDone. Unplug and replug the USB cable (or reboot if it's not easily accessible).")
    return 0


def setup_selinux():
    """Install SELinux policy module allowing USB device access.

    Compiles trcc_usb.te -> .mod -> .pp, then loads via semodule.
    Required on SELinux-enforcing systems (Bazzite, Silverblue) where
    detach_kernel_driver() is silently blocked.
    """
    if err := _require_linux("setup-selinux"):
        return err
    import tempfile

    # Must be root
    if not _is_root():
        return _sudo_reexec("setup-selinux")

    # Check if SELinux is enforcing
    try:
        r = subprocess.run(
            ["getenforce"], capture_output=True, text=True, timeout=5,
        )
        status = r.stdout.strip().lower()
    except FileNotFoundError:
        print("SELinux not installed — nothing to do.")
        return 0

    if status != 'enforcing':
        print(f"SELinux is {status} — no policy needed.")
        return 0

    # Check if already loaded
    try:
        r = subprocess.run(
            ["semodule", "-l"], capture_output=True, text=True, timeout=10,
        )
        if 'trcc_usb' in r.stdout:
            print("SELinux module trcc_usb already loaded.")
            return 0
    except FileNotFoundError:
        print("semodule not found — cannot manage SELinux policies.")
        return 1

    # Check for checkmodule and semodule_package
    from trcc.adapters.infra.doctor import _detect_pkg_manager, _install_hint
    pm = _detect_pkg_manager()

    missing: list[str] = []
    for tool in ('checkmodule', 'semodule_package'):
        if not shutil.which(tool):
            missing.append(tool)
    if missing:
        for tool in missing:
            print(f"  {tool} not found — {_install_hint(tool, pm)}")
        return 1

    # Find .te source (shipped in package data)
    # __file__ is trcc/cli/_system.py — parent.parent = trcc/
    trcc_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    te_src = os.path.join(trcc_root, 'data', 'trcc_usb.te')
    if not os.path.isfile(te_src):
        print(f"SELinux policy source not found: {te_src}")
        return 1

    # Compile and install in temp directory
    try:
        with tempfile.TemporaryDirectory() as tmp:
            te_path = os.path.join(tmp, 'trcc_usb.te')
            mod_path = os.path.join(tmp, 'trcc_usb.mod')
            pp_path = os.path.join(tmp, 'trcc_usb.pp')

            shutil.copy2(te_src, te_path)

            # checkmodule -M -m -o trcc_usb.mod trcc_usb.te
            r = subprocess.run(
                ['checkmodule', '-M', '-m', '-o', mod_path, te_path],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"checkmodule failed: {r.stderr.strip()}")
                return 1

            # semodule_package -o trcc_usb.pp -m trcc_usb.mod
            r = subprocess.run(
                ['semodule_package', '-o', pp_path, '-m', mod_path],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"semodule_package failed: {r.stderr.strip()}")
                return 1

            # semodule -i trcc_usb.pp
            r = subprocess.run(
                ['semodule', '-i', pp_path],
                capture_output=True, text=True,
            )
            if r.returncode != 0:
                print(f"semodule install failed: {r.stderr.strip()}")
                return 1

        print("Installed SELinux module trcc_usb (USB device access for TRCC).")
        return 0

    except Exception as e:
        print(f"Error installing SELinux policy: {e}")
        return 1


def install_desktop():
    """Install .desktop menu entry and icon for app launchers (Linux only).

    Reads the shipped .desktop file from the package assets directory.
    Works from both pip install and git clone.
    """
    if err := _require_linux("install-desktop"):
        return err
    home = _real_user_home()
    app_dir = home / ".local" / "share" / "applications"

    # Package root: __file__ is trcc/cli/_system.py — parent.parent = trcc/
    pkg_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    icon_pkg_dir = pkg_root / "assets" / "icons"
    desktop_src = pkg_root / "assets" / "trcc-linux.desktop"

    # Install .desktop file (copy from package assets, or generate if missing)
    app_dir.mkdir(parents=True, exist_ok=True)
    desktop_dst = app_dir / "trcc-linux.desktop"
    if desktop_src.exists():
        shutil.copy2(desktop_src, desktop_dst)
    else:
        desktop_dst.write_text(
            "[Desktop Entry]\nName=TRCC Linux\n"
            "Comment=Thermalright LCD Control Center\nExec=trcc gui\n"
            "Icon=trcc\nTerminal=false\nType=Application\n"
            "Categories=Utility;System;\n"
            "Keywords=thermalright;lcd;cooler;aio;cpu;\n"
            "StartupWMClass=trcc-linux\n"
        )
    print(f"Installed {desktop_dst}")

    # Install icons to XDG hicolor theme
    installed_icon = False
    for size in [256, 128, 64, 48, 32, 24, 16]:
        icon_src = icon_pkg_dir / f"trcc_{size}x{size}.png"
        if icon_src.exists():
            icon_dir = home / ".local" / "share" / "icons" / "hicolor" / f"{size}x{size}" / "apps"
            icon_dir.mkdir(parents=True, exist_ok=True)
            shutil.copy2(icon_src, icon_dir / "trcc.png")
            installed_icon = True

    if installed_icon:
        # Update icon cache
        subprocess.run(
            ["gtk-update-icon-cache", str(home / ".local" / "share" / "icons" / "hicolor")],
            check=False, capture_output=True
        )
    else:
        print("Warning: icons not found, menu entry will use a generic icon")

    print("\nTRCC should now appear in your application menu.")
    print("If it doesn't show up immediately, log out and back in.")
    return 0


@_cli_handler
def setup_polkit():
    """Install polkit policy for passwordless dmidecode/smartctl access.

    Copies the shipped policy XML to /usr/share/polkit-1/actions/ so that
    active desktop sessions can run dmidecode and smartctl without a
    password prompt. Requires root. Linux only.
    """
    if err := _require_linux("setup-polkit"):
        return err
    if not _is_root():
        return _sudo_reexec("setup-polkit")

    # Package root: __file__ is trcc/cli/_system.py — parent.parent = trcc/
    pkg_root = Path(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    policy_src = pkg_root / "assets" / "com.github.lexonight1.trcc.policy"

    if not policy_src.exists():
        print(f"Policy file not found: {policy_src}")
        return 1

    # Resolve canonical binary paths — root PATH may differ from user PATH
    # (e.g. root's which returns /usr/sbin/dmidecode but user uses /usr/bin/).
    # realpath resolves symlinks so UsrMerge distros get /usr/bin consistently.
    policy_text = policy_src.read_text()
    for binary in ('dmidecode', 'smartctl'):
        found = shutil.which(binary)
        if found:
            real_path = os.path.realpath(found)
            policy_text = policy_text.replace(f'/usr/bin/{binary}', real_path)

    policy_dst = Path("/usr/share/polkit-1/actions/com.github.lexonight1.trcc.policy")
    policy_dst.parent.mkdir(parents=True, exist_ok=True)
    policy_dst.write_text(policy_text)

    # JavaScript rules file — scoped to the installing user only.
    # XML allow_active=yes doesn't work on all DEs (e.g. XFCE),
    # so this guarantees passwordless access regardless of session state.
    invoking_user = os.environ.get('SUDO_USER', '')
    if invoking_user:
        rules_dst = Path("/etc/polkit-1/rules.d/50-trcc.rules")
        rules_dst.parent.mkdir(parents=True, exist_ok=True)
        rules_dst.write_text(
            '// TRCC Linux — passwordless dmidecode/smartctl for installing user\n'
            'polkit.addRule(function(action, subject) {\n'
            '    if ((action.id == "com.github.lexonight1.trcc.dmidecode" ||\n'
            '         action.id == "com.github.lexonight1.trcc.smartctl") &&\n'
            f'        subject.user == "{invoking_user}") {{\n'
            '        return polkit.Result.YES;\n'
            '    }\n'
            '});\n'
        )
        print(f"Installed {rules_dst} (user: {invoking_user})")

    # Fix SELinux contexts
    restore_paths = [str(policy_dst)]
    if invoking_user:
        restore_paths.append(str(rules_dst))
    if shutil.which('restorecon'):
        subprocess.run(['restorecon'] + restore_paths, check=False)
    print(f"Installed {policy_dst}")
    print(f"User '{invoking_user}' can now run dmidecode/smartctl without a password.")
    return 0


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
