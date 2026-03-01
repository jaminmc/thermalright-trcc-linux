#!/usr/bin/env python3
"""Bump version across all project files.

Usage: python3 scripts/bump_version.py 6.5.3
"""
from __future__ import annotations

import re
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sub(path: Path, pattern: str, repl: str) -> None:
    """Regex-replace in file. Raises if no match found."""
    text = path.read_text()
    new, n = re.subn(pattern, repl, text, flags=re.MULTILINE)
    if n == 0:
        raise RuntimeError(f"No match for {pattern!r} in {path}")
    path.write_text(new)
    print(f"  {path.relative_to(ROOT)}: {n} replacement(s)")


def bump(new: str) -> None:
    """Update version in all project files."""
    if not re.fullmatch(r"\d+\.\d+\.\d+", new):
        print(f"Error: invalid version '{new}' (expected X.Y.Z)")
        sys.exit(1)

    print(f"Bumping to {new}:\n")

    # 1. __version__.py
    _sub(
        ROOT / "src/trcc/__version__.py",
        r'__version__ = "[^"]+"',
        f'__version__ = "{new}"',
    )

    # 2. pyproject.toml
    _sub(
        ROOT / "pyproject.toml",
        r'^version = "[^"]+"',
        f'version = "{new}"',
    )

    # 3. RPM spec — update Version line
    spec = ROOT / "packaging/rpm/trcc-linux.spec"
    _sub(spec, r"^Version:\s+\S+", f"Version:        {new}")

    # 4. Arch PKGBUILD
    _sub(
        ROOT / "packaging/arch/PKGBUILD",
        r"^pkgver=\S+",
        f"pkgver={new}",
    )

    # 5. Arch .SRCINFO — version + source URL
    srcinfo = ROOT / "packaging/arch/.SRCINFO"
    text = srcinfo.read_text()
    text = re.sub(r"pkgver = \S+", f"pkgver = {new}", text)
    text = re.sub(
        r"source = trcc-linux-\S+\.tar\.gz::.*",
        f"source = trcc-linux-{new}.tar.gz::"
        f"https://github.com/Lexonight1/thermalright-trcc-linux/archive/v{new}.tar.gz",
        text,
    )
    srcinfo.write_text(text)
    print(f"  {srcinfo.relative_to(ROOT)}: pkgver + source URL")

    # 6. Debian changelog — prepend new entry
    dch = ROOT / "packaging/debian/changelog"
    now = datetime.now(timezone.utc)
    day = now.strftime("%a, %d %b %Y %H:%M:%S +0000")
    entry = (
        f"trcc-linux ({new}-1) unstable; urgency=medium\n"
        f"\n"
        f"  * See https://github.com/Lexonight1/thermalright-trcc-linux/releases/tag/v{new}\n"
        f"\n"
        f" -- TRCC Linux Contributors <noreply@github.com>  {day}\n"
        f"\n"
    )
    dch.write_text(entry + dch.read_text())
    print(f"  {dch.relative_to(ROOT)}: prepended new entry")

    # 7. Gentoo ebuild — rename file
    gentoo = ROOT / "packaging/gentoo"
    old_ebuilds = list(gentoo.glob("trcc-linux-*.ebuild"))
    if old_ebuilds:
        old = old_ebuilds[0]
        dest = gentoo / f"trcc-linux-{new}.ebuild"
        old.rename(dest)
        print(f"  {old.relative_to(ROOT)} -> {dest.name}")
    else:
        print("  packaging/gentoo/: no ebuild found to rename")

    print(f"\nDone. Version is now {new} everywhere.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print(f"Usage: {sys.argv[0]} <version>")
        print(f"Example: {sys.argv[0]} 6.5.3")
        sys.exit(1)
    bump(sys.argv[1])
