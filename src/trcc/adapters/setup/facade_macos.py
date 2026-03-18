"""macOS platform setup — Homebrew deps, libusb."""
from __future__ import annotations

import logging
import os
import platform
import shutil
import subprocess
from pathlib import Path
from typing import Any

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
        return os.path.join(self.data_dir(), f'theme{width}{height}')

    def web_dir(self, width: int, height: int) -> str:
        return os.path.join(self.data_dir(), 'web', f'{width}{height}')

    def web_masks_dir(self, width: int, height: int) -> str:
        return os.path.join(self.data_dir(), 'web', f'zt{width}{height}')

    def user_masks_dir(self, width: int, height: int) -> str:
        return os.path.join(self.user_content_dir(), 'data', 'web', f'zt{width}{height}')

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
        print("    Apple Silicon: sensor reading needs sudo for powermetrics.")
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
