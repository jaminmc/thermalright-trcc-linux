"""Linux platform setup — udev, SELinux, polkit, desktop entry."""
from __future__ import annotations

import logging
import os
import subprocess
import sys
from pathlib import Path
from typing import Any

from trcc.core.ports import PlatformSetup

log = logging.getLogger(__name__)


class LinuxSetup(PlatformSetup):
    """Linux setup wizard — system deps, GPU, udev, SELinux, polkit, desktop."""

    def get_distro_name(self) -> str:
        from trcc.adapters.infra.doctor import _read_os_release
        return _read_os_release().get('PRETTY_NAME', 'Unknown Linux')

    def get_pkg_manager(self) -> str | None:
        from trcc.adapters.infra.doctor import _detect_pkg_manager
        return _detect_pkg_manager()

    def check_deps(self) -> list[Any]:
        from trcc.adapters.infra.doctor import check_system_deps
        return check_system_deps(self.get_pkg_manager())

    def config_dir(self) -> str:
        from trcc.core.paths import USER_CONFIG_DIR
        return USER_CONFIG_DIR

    def data_dir(self) -> str:
        from trcc.core.paths import USER_DATA_DIR
        return USER_DATA_DIR

    def user_content_dir(self) -> str:
        from trcc.core.paths import USER_CONTENT_DIR
        return USER_CONTENT_DIR

    def theme_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import DATA_DIR
        return os.path.join(DATA_DIR, f'theme{width}{height}')

    def web_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import get_web_dir
        return get_web_dir(width, height)

    def web_masks_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import get_web_masks_dir
        return get_web_masks_dir(width, height)

    def user_masks_dir(self, width: int, height: int) -> str:
        from trcc.core.paths import get_user_masks_dir
        return get_user_masks_dir(width, height)

    def ffmpeg_install_help(self) -> str:
        from trcc.adapters.infra.doctor import _detect_pkg_manager, _install_hint
        pm = _detect_pkg_manager()
        hint = _install_hint('ffmpeg', pm)
        return f"ffmpeg not found. Install:\n  {hint}" if hint else "ffmpeg not found"

    def resolve_assets_dir(self, pkg_assets_dir: Path) -> Path:
        """Linux: use package dir directly — no sandboxing issues."""
        return pkg_assets_dir

    def archive_tool_install_help(self) -> str:
        from trcc.adapters.infra.doctor import _install_hint
        pm = self.get_pkg_manager()
        hint = _install_hint('7z', pm)
        if hint:
            return f"7z not found. Install:\n  {hint}"
        return (
            "7z not found. Install p7zip for your distro:\n"
            "  Fedora/RHEL:    sudo dnf install p7zip p7zip-plugins\n"
            "  Ubuntu/Debian:  sudo apt install p7zip-full\n"
            "  Arch:           sudo pacman -S p7zip"
        )

    def run(self, auto_yes: bool = False) -> int:
        from trcc.adapters.infra.doctor import (
            check_desktop_entry,
            check_gpu,
            check_polkit,
            check_rapl,
            check_selinux,
            check_system_deps,
            check_udev,
        )

        pm = self.get_pkg_manager()
        print(f"\n  TRCC Setup — {self.get_distro_name()}\n")
        actions: list[str] = []

        # Step 1/6: System dependencies
        print("  Step 1/6: System dependencies")
        deps = check_system_deps(pm)
        missing_required: list[str] = []
        missing_optional: list[str] = []
        for dep in deps:
            if dep.ok:
                ver = f" {dep.version}" if dep.version else ""
                print(f"    [OK]  {dep.name}{ver}")
            elif dep.required:
                note = f" ({dep.note})" if dep.note else ""
                print(f"    [!!]  {dep.name} — MISSING{note}")
                missing_required.append(dep.install_cmd)
            else:
                note = f" ({dep.note})" if dep.note else ""
                print(f"    [--]  {dep.name} — not installed{note}")
                missing_optional.append(dep.install_cmd)

        for cmd in missing_required:
            if _confirm(f"Install? -> {cmd}", auto_yes):
                print(f"    -> {cmd}")
                import shlex
                result = subprocess.run(shlex.split(cmd))
                if result.returncode == 0:
                    actions.append(f"Installed: {cmd}")
                else:
                    print(f"    [!!] Command failed (exit {result.returncode})")
        for cmd in missing_optional:
            if _confirm(f"Install? -> {cmd}", auto_yes):
                print(f"    -> {cmd}")
                import shlex
                result = subprocess.run(shlex.split(cmd))
                if result.returncode == 0:
                    actions.append(f"Installed: {cmd}")
        print()

        # Step 2/6: GPU detection
        print("  Step 2/6: GPU detection")
        gpus = check_gpu()
        if not gpus:
            print("    [--]  No discrete GPU detected")
        for gpu in gpus:
            if gpu.package_installed:
                print(f"    [OK]  {gpu.label}")
            else:
                print(f"    [--]  {gpu.label} — {gpu.install_cmd}")
                if _confirm(f"Install? -> {gpu.install_cmd}", auto_yes):
                    print(f"    -> {gpu.install_cmd}")
                    result = subprocess.run(
                        [sys.executable, "-m", "pip", "install"]
                        + gpu.install_cmd.split()[-1:],
                    )
                    if result.returncode == 0:
                        actions.append(f"Installed: {gpu.install_cmd}")
                    else:
                        print(f"    [!!] pip failed (exit {result.returncode})")
        print()

        # Step 3/6: USB device permissions (udev + RAPL)
        print("  Step 3/6: USB device permissions")
        udev = check_udev()
        if udev.ok:
            print(f"    [OK]  {udev.message}")
        else:
            print(f"    [!!]  {udev.message}")
            if _confirm("Install udev rules? (requires sudo)", auto_yes):
                from trcc.cli._system import setup_udev
                rc = setup_udev()
                if rc == 0:
                    actions.append("Installed udev rules")
                else:
                    print("    [!!] udev setup failed")

        rapl = check_rapl()
        if rapl.applicable:
            if rapl.ok:
                print(f"    [OK]  {rapl.message}")
            else:
                print(f"    [--]  {rapl.message}")
                if _confirm("Fix RAPL permissions? (requires sudo)", auto_yes):
                    from trcc.cli._system import _is_root, _setup_rapl_permissions, _sudo_reexec
                    if not _is_root():
                        rc = _sudo_reexec("setup-udev")
                    else:
                        _setup_rapl_permissions()
                        rc = 0
                    if rc == 0:
                        actions.append("Fixed RAPL power sensor permissions")
        print()

        # Step 4/6: SELinux policy
        se = check_selinux()
        if se.enforcing:
            print("  Step 4/6: SELinux policy")
            if se.ok:
                print(f"    [OK]  {se.message}")
            else:
                print(f"    [!!]  {se.message}")
                if _confirm("Install SELinux USB policy? (requires sudo)", auto_yes):
                    from trcc.cli._system import setup_selinux
                    rc = setup_selinux()
                    if rc == 0:
                        actions.append("Installed SELinux policy")
                    else:
                        print("    [!!] SELinux setup failed")
            print()

        # Step 5/6: Polkit policy
        print("  Step 5/6: Hardware info access")
        pk = check_polkit()
        if pk.ok:
            print(f"    [OK]  {pk.message}")
        else:
            print(f"    [--]  {pk.message}")
            if _confirm("Install polkit policy for hardware info? (requires sudo)", auto_yes):
                from trcc.cli._system import setup_polkit
                rc = setup_polkit()
                if rc == 0:
                    actions.append("Installed polkit policy")
                else:
                    print("    [!!] polkit setup failed")
        print()

        # Step 6/6: Desktop integration
        print("  Step 6/6: Desktop integration")
        if check_desktop_entry():
            print("    [OK]  Application menu entry installed")
        else:
            print("    [--]  No application menu entry")
            if _confirm("Install application menu entry?", auto_yes):
                from trcc.cli._system import install_desktop
                rc = install_desktop()
                if rc == 0:
                    actions.append("Installed desktop entry")
        print()

        _print_summary(actions)
        return 0


def _confirm(prompt: str, auto_yes: bool) -> bool:
    if auto_yes:
        print(f"  {prompt} [Y/n]: y (auto)")
        return True
    try:
        answer = input(f"  {prompt} [Y/n]: ").strip().lower()
        return answer in ('', 'y', 'yes')
    except (EOFError, KeyboardInterrupt):
        print()
        return False


def _print_summary(actions: list[str]) -> None:
    print("  Summary")
    if actions:
        for a in actions:
            print(f"    + {a}")
    else:
        print("    Nothing to do — system is ready.")
    print("\n  Run 'trcc gui' to launch, or find TRCC in your app menu.\n")
