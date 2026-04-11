"""Tests for PyInstaller ``TRCC.app`` argv normalization (macOS)."""

from __future__ import annotations

from pathlib import Path

import pytest

from trcc.core.macos_app_bundle_launch import (
    argv_tail_without_launch_services_noise,
    is_frozen_macos_trcc_pyinstaller_bundle,
    should_inject_typer_subcommand,
    subcommand_for_bundle_double_click,
)


def test_argv_tail_strips_psn() -> None:
    exe = '/Applications/TRCC.app/Contents/MacOS/TRCC'
    assert argv_tail_without_launch_services_noise([exe]) == []
    assert argv_tail_without_launch_services_noise(
        [exe, '-psn_0_12345'],
    ) == []
    assert argv_tail_without_launch_services_noise(
        [exe, '-psn_0_1', 'gui'],
    ) == ['gui']


@pytest.mark.parametrize(
    ('parts', 'name', 'expected'),
    [
        (
            ('/', 'Applications', 'TRCC.app', 'Contents', 'MacOS'),
            'TRCC',
            True,
        ),
        (
            ('/', 'Applications', 'TRCC.app', 'Contents', 'MacOS'),
            'trcc',
            True,
        ),
        (
            ('/', 'opt', 'bin', 'trcc'),
            'trcc',
            False,
        ),
    ],
)
def test_is_frozen_bundle(
    parts: tuple[str, ...],
    name: str,
    expected: bool,
) -> None:
    root = Path(*parts)
    executable = str(root / name)
    assert is_frozen_macos_trcc_pyinstaller_bundle(
        'darwin', True, executable,
    ) is expected


def test_should_inject() -> None:
    assert should_inject_typer_subcommand([]) is True
    assert should_inject_typer_subcommand(['gui']) is False
    assert should_inject_typer_subcommand(['--help']) is False
    assert should_inject_typer_subcommand(['-h']) is False
    assert should_inject_typer_subcommand(['--version']) is False


def test_subcommand_respects_marker(tmp_path: Path) -> None:
    marker = tmp_path / 'done'
    argv = ['/Applications/TRCC.app/Contents/MacOS/TRCC']
    exe = argv[0]
    assert subcommand_for_bundle_double_click(
        argv,
        platform='darwin',
        frozen=True,
        executable=exe,
        marker=marker,
    ) == 'setup-gui'
    marker.write_text('x', encoding='utf-8')
    assert subcommand_for_bundle_double_click(
        argv,
        platform='darwin',
        frozen=True,
        executable=exe,
        marker=marker,
    ) == 'gui'


def test_subcommand_non_macos_none() -> None:
    assert subcommand_for_bundle_double_click(
        ['/foo/TRCC.app/Contents/MacOS/TRCC'],
        platform='linux',
        frozen=True,
        executable='/foo/TRCC.app/Contents/MacOS/TRCC',
        marker=Path('/dev/null'),
    ) is None
