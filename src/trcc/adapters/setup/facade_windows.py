"""Windows platform setup — 7-Zip, WinUSB/Zadig guidance."""
from __future__ import annotations

import logging
import os
import shutil
import subprocess
from pathlib import Path
from typing import Any

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


def _copy_assets_to_user_dir(pkg_assets_dir: Path) -> Path:
    """Copy bundled assets to ~/.trcc/assets/gui/ on first run."""
    user_assets = Path.home() / '.trcc' / 'assets' / 'gui'
    if user_assets.exists() and any(user_assets.glob('*.png')):
        return user_assets
    if pkg_assets_dir.exists():
        user_assets.mkdir(parents=True, exist_ok=True)
        try:
            for f in pkg_assets_dir.iterdir():
                shutil.copy2(f, user_assets / f.name)
            log.info("Copied %d assets to %s",
                     len(list(user_assets.glob('*'))), user_assets)
            return user_assets
        except Exception:
            log.warning("Failed to copy assets to user dir", exc_info=True)
    return pkg_assets_dir


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
    print("\n  Run 'trcc gui' to launch.\n")
