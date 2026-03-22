"""Windows platform setup — 7-Zip, WinUSB/Zadig guidance."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

from trcc.adapters.system._shared import (
    _confirm,
    _copy_assets_to_user_dir,
    _print_summary,
)
from trcc.core.ports import PlatformSetup

log = logging.getLogger(__name__)


class WindowsSetup(PlatformSetup):
    """Windows setup wizard — system deps and driver guidance."""

    def get_distro_name(self) -> str:
        import platform
        return f"Windows {platform.version()}"

    def get_pkg_manager(self) -> str | None:
        return 'winget' if shutil.which('winget') else None

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
        return (
            "ffmpeg not found. Install:\n"
            "  winget install Gyan.FFmpeg"
        )

    def resolve_assets_dir(self, pkg_assets_dir: Path) -> Path:
        """Windows: copy to ~/.trcc/assets/gui/ to avoid sandboxed paths."""
        return _copy_assets_to_user_dir(pkg_assets_dir)

    def archive_tool_install_help(self) -> str:
        return (
            "7z not found. Install 7-Zip for Windows:\n"
            "  Download from https://7-zip.org/ and install, or run:\n"
            "  winget install 7zip.7zip"
        )

    def configure_dpi(self) -> None:
        """Declare per-monitor DPI awareness so Windows doesn't bitmap-stretch our window.

        Our layout uses fixed pixel coordinates (96 DPI / 100% scale).
        Without this, Windows applies GDI virtualization at >100% display scale,
        displacing and clipping widgets.
        """
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)  # type: ignore[attr-defined]
        except Exception:
            pass

    def get_screencast_capture(
        self, x: int, y: int, w: int, h: int,
    ) -> tuple[str, str, list[str]] | None:
        region_args = ['-offset_x', str(x), '-offset_y', str(y),
                       '-video_size', f'{w}x{h}'] if (w and h) else []
        return 'gdigrab', 'desktop', region_args

    def supports_winusb(self) -> bool:
        return True

    def minimize_on_close(self) -> bool:
        return True

    def no_devices_hint(self) -> str | None:
        return (
            "\nOn Windows, non-SCSI devices (HID, Bulk, LY) need the\n"
            "WinUSB driver. Run 'trcc setup-winusb' for instructions."
        )

    def check_device_permissions(self, devices: list) -> list[str]:
        return []

    def get_system_files(self) -> list[str]:
        return []

    def acquire_instance_lock(self) -> object | None:
        import msvcrt  # pyright: ignore[reportMissingImports]
        from pathlib import Path
        lock_path = Path(self.config_dir()) / "trcc-linux.lock"
        lock_path.parent.mkdir(parents=True, exist_ok=True)
        try:
            fh = open(lock_path, "w")  # noqa: SIM115
            msvcrt.locking(fh.fileno(), msvcrt.LK_NBLCK, 1)  # pyright: ignore[reportAttributeAccessIssue]
            fh.write(str(os.getpid()))
            fh.flush()
            return fh
        except OSError:
            return None

    def raise_existing_instance(self) -> None:
        pass  # No SIGUSR1 on Windows — user must switch manually

    def get_doctor_config(self):
        from trcc.core.ports import DoctorPlatformConfig
        return DoctorPlatformConfig(
            distro_name=self.get_distro_name(),
            pkg_manager=self.get_pkg_manager(),
            check_libusb=False,
            extra_binaries=[],
            run_gpu_check=False,
            run_udev_check=False,
            run_selinux_check=False,
            run_rapl_check=False,
            run_polkit_check=False,
            run_winusb_check=True,
            enable_ansi=True,
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
                        result = subprocess.run(
                            dep.install_cmd.split(),
                            capture_output=True,
                        )
                        if result.returncode == 0:
                            actions.append(f"Installed: {dep.name}")
                        else:
                            print(f"    [!!] Install failed (exit {result.returncode})")
            else:
                note = f" ({dep.note})" if dep.note else ""
                print(f"    [--]  {dep.name} — not installed{note}")
        print()

        # Step 2/2: WinUSB driver guidance
        print("  Step 2/2: USB driver")
        print("    SCSI devices (Frozen Warframe, Elite Vision, CZTV)")
        print("    use the default USB Mass Storage driver — no setup needed.\n")
        print("    HID, Bulk, and LY devices need the WinUSB driver.")
        print("    Install via Zadig (https://zadig.akeo.ie/):")
        print("      1. Run Zadig -> Options -> List All Devices")
        print("      2. Select your Thermalright device")
        print("      3. Set target driver to WinUSB")
        print("      4. Click 'Replace Driver'")
        print("      5. Replug the USB device")
        print()

        _print_summary(actions)
        return 0


