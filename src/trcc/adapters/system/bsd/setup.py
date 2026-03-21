"""FreeBSD platform setup — pkg deps."""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

from trcc.adapters.system._shared import (
    _confirm,
    _copy_assets_to_user_dir,
    _posix_acquire_instance_lock,
    _posix_raise_existing_instance,
    _print_summary,
)
from trcc.core.ports import PlatformSetup

log = logging.getLogger(__name__)


class BSDSetup(PlatformSetup):
    """FreeBSD setup wizard — pkg deps."""

    def get_distro_name(self) -> str:
        return f"FreeBSD {platform.release()}"

    def get_pkg_manager(self) -> str | None:
        return 'pkg' if shutil.which('pkg') else None

    def check_deps(self) -> list[Any]:
        from trcc.adapters.infra.doctor import check_system_deps
        return check_system_deps(self.get_pkg_manager())

    def config_dir(self) -> str:
        return os.path.join(Path.home(), '.trcc')

    def data_dir(self) -> str:
        return os.path.join(self.config_dir(), 'data')

    def user_content_dir(self) -> str:
        return os.path.join(Path.home(), '.trcc-user')

    def theme_dir(self, width: int, height: int) -> str:
        return os.path.join(self.data_dir(), f'theme{width}{height}')

    def web_dir(self, width: int, height: int) -> str:
        return os.path.join(self.data_dir(), 'web', f'{width}{height}')

    def web_masks_dir(self, width: int, height: int) -> str:
        return os.path.join(self.data_dir(), 'web', f'zt{width}{height}')

    def user_masks_dir(self, width: int, height: int) -> str:
        return os.path.join(self.user_content_dir(), 'data', 'web', f'zt{width}{height}')

    def ffmpeg_install_help(self) -> str:
        return "ffmpeg not found. Install:\n  sudo pkg install ffmpeg"

    def resolve_assets_dir(self, pkg_assets_dir: Path) -> Path:
        """BSD: copy to ~/.trcc/assets/gui/ to avoid pkg paths."""
        return _copy_assets_to_user_dir(pkg_assets_dir)

    def archive_tool_install_help(self) -> str:
        return (
            "7z not found. Install via pkg:\n"
            "  sudo pkg install p7zip"
        )

    def minimize_on_close(self) -> bool:
        return False

    def no_devices_hint(self) -> str | None:
        return None

    def check_device_permissions(self, devices: list) -> list[str]:
        return []

    def get_system_files(self) -> list[str]:
        return []

    def acquire_instance_lock(self) -> object | None:
        return _posix_acquire_instance_lock(self.config_dir())

    def raise_existing_instance(self) -> None:
        _posix_raise_existing_instance(self.config_dir())

    def get_doctor_config(self):
        from trcc.core.ports import DoctorPlatformConfig
        return DoctorPlatformConfig(
            distro_name=self.get_distro_name(),
            pkg_manager=self.get_pkg_manager(),
            check_libusb=True,
            extra_binaries=[],
            run_gpu_check=False,
            run_udev_check=False,
            run_selinux_check=False,
            run_rapl_check=False,
            run_polkit_check=False,
            run_winusb_check=False,
            enable_ansi=False,
        )

    def get_report_config(self):
        from trcc.core.ports import ReportPlatformConfig
        return ReportPlatformConfig(
            distro_name=self.get_distro_name(),
            collect_lsusb=False,
            collect_udev=False,
            collect_selinux=False,
            collect_rapl=False,
            collect_device_permissions=False,
        )

    def run(self, auto_yes: bool = False) -> int:
        from trcc.adapters.infra.doctor import check_system_deps

        pm = self.get_pkg_manager()
        print(f"\n  TRCC Setup — {self.get_distro_name()}\n")
        actions: list[str] = []

        # Step 1/1: System dependencies
        print("  Step 1/1: System dependencies")
        deps = check_system_deps(pm)
        for dep in deps:
            if dep.ok:
                ver = f" {dep.version}" if dep.version else ""
                print(f"    [OK]  {dep.name}{ver}")
            elif dep.required:
                note = f" ({dep.note})" if dep.note else ""
                print(f"    [!!]  {dep.name} — MISSING{note}")
                if dep.install_cmd and pm:
                    if _confirm(f"Install? -> {dep.install_cmd}", auto_yes):
                        result = subprocess.run(dep.install_cmd.split())
                        if result.returncode == 0:
                            actions.append(f"Installed: {dep.name}")
                        else:
                            print(f"    [!!] Install failed (exit {result.returncode})")
            else:
                note = f" ({dep.note})" if dep.note else ""
                print(f"    [--]  {dep.name} — not installed{note}")
        print()

        _print_summary(actions)
        return 0


