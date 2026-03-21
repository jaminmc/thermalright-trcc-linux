"""Shared helpers for platform setup adapters.

Functions here are identical across 3-4 platform adapters. Import them
instead of repeating the implementation in each adapter.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

# ── Interactive prompt ────────────────────────────────────────────────────────

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


def _print_summary(
    actions: list[str],
    launch_hint: str = "Run 'trcc gui' to launch.",
) -> None:
    print("  Summary")
    if actions:
        for a in actions:
            print(f"    + {a}")
    else:
        print("    Nothing to do — system is ready.")
    print(f"\n  {launch_hint}\n")


# ── Asset copy (non-Linux platforms avoid sandboxed pkg paths) ────────────────

def _copy_assets_to_user_dir(pkg_assets_dir: Path) -> Path:
    """Copy bundled assets to ~/.trcc/assets/gui/ on first run."""
    import logging
    log = logging.getLogger(__name__)
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


# ── Process listing (psutil — Windows / macOS / BSD) ─────────────────────────



# ── Single-instance lock (POSIX — Linux / macOS / BSD) ───────────────────────

def _posix_acquire_instance_lock(config_dir: str) -> object | None:
    """Acquire an exclusive lock file via fcntl. Returns handle or None."""
    import fcntl
    lock_path = Path(config_dir) / "trcc-linux.lock"
    lock_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        fh = open(lock_path, "w")  # noqa: SIM115
        fcntl.flock(fh, fcntl.LOCK_EX | fcntl.LOCK_NB)
        fh.write(str(os.getpid()))
        fh.flush()
        return fh
    except OSError:
        return None


def _posix_raise_existing_instance(config_dir: str) -> None:
    """Send SIGUSR1 to the PID stored in the lock file."""
    import signal
    lock_path = Path(config_dir) / "trcc-linux.lock"
    try:
        pid = int(lock_path.read_text().strip())
        os.kill(pid, signal.SIGUSR1)
    except (FileNotFoundError, ValueError, ProcessLookupError, PermissionError):
        pass
