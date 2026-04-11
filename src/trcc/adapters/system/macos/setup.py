"""macOS platform setup — Homebrew deps, libusb."""
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
from trcc.core.paths import masks_dir_name, theme_dir_name, web_dir_name
from trcc.core.ports import PlatformSetup

log = logging.getLogger(__name__)


class MacOSSetup(PlatformSetup):
    """macOS setup wizard — Homebrew deps and libusb."""

    def get_distro_name(self) -> str:
        return f"macOS {platform.mac_ver()[0]}"

    def get_pkg_manager(self) -> str | None:
        return 'brew' if shutil.which('brew') else None

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
        return os.path.join(self.data_dir(), theme_dir_name(width, height))

    def web_dir(self, width: int, height: int) -> str:
        return os.path.join(self.data_dir(), 'web', web_dir_name(width, height))

    def web_masks_dir(self, width: int, height: int) -> str:
        return os.path.join(self.data_dir(), 'web', masks_dir_name(width, height))

    def user_masks_dir(self, width: int, height: int) -> str:
        return os.path.join(self.user_content_dir(), 'data', 'web', masks_dir_name(width, height))

    def ffmpeg_install_help(self) -> str:
        return "ffmpeg not found. Install:\n  brew install ffmpeg"

    def resolve_assets_dir(self, pkg_assets_dir: Path) -> Path:
        """macOS: copy to ~/.trcc/assets/gui/ to avoid app bundle paths."""
        return _copy_assets_to_user_dir(pkg_assets_dir)

    def archive_tool_install_help(self) -> str:
        return (
            "7z not found. Install via Homebrew:\n"
            "  brew install p7zip"
        )

    def wire_ipc_raise(self, app: Any, window: Any) -> None:
        """Install SIGUSR1 handler via AF_UNIX socketpair + QSocketNotifier."""
        import signal
        import socket

        from PySide6.QtCore import QSocketNotifier
        rsock, wsock = socket.socketpair(socket.AF_UNIX, socket.SOCK_STREAM)
        rsock.setblocking(False)
        wsock.setblocking(False)

        def _on_sigusr1(signum: Any, frame: Any) -> None:
            try:
                wsock.send(b'\x01')
            except OSError:
                pass

        signal.signal(signal.SIGUSR1, _on_sigusr1)
        notifier = QSocketNotifier(rsock.fileno(), QSocketNotifier.Type.Read, app)

        def _raise_window() -> None:
            try:
                rsock.recv(1)
            except OSError:
                pass
            window.showNormal()
            window.raise_()
            window.activateWindow()

        notifier.activated.connect(_raise_window)

    def get_screencast_capture(
        self, x: int, y: int, w: int, h: int,
    ) -> tuple[str, str, list[str]] | None:
        region_args = ['-video_size', f'{w}x{h}'] if (w and h) else []
        return 'avfoundation', '1:none', region_args

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

        # Step 1/2: System dependencies
        print("  Step 1/2: System dependencies")
        if not pm:
            print("    [!!]  Homebrew not found — install from https://brew.sh/")
            print()
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

        # Step 2/2: USB access
        print("  Step 2/2: USB access")
        print("    SCSI devices need sudo to detach the kernel driver.")
        print("    HID devices work without root.")
        print(
            "    Apple Silicon: powermetrics needs root — use the optional "
            "trcc-powermetrics-helper LaunchDaemon (native/macos/) or sudo.",
        )
        print()

        _print_summary(actions)
        return 0


