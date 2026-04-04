"""Tests for trcc.core.orientation — Orientation model + standalone helpers."""
from __future__ import annotations

from pathlib import Path

import pytest

from trcc.core.models import ThemeDir
from trcc.core.orientation import Orientation, output_resolution

# =========================================================================
# output_resolution (standalone function)
# =========================================================================


class TestOutputResolution:
    """output_resolution(w, h, rotation) — swaps dims for non-square at 90/270."""

    # Non-square landscape
    @pytest.mark.parametrize("rot,expected", [
        (0, (1280, 480)),
        (90, (480, 1280)),
        (180, (1280, 480)),
        (270, (480, 1280)),
    ])
    def test_non_square_1280x480(self, rot, expected):
        assert output_resolution(1280, 480, rot) == expected

    @pytest.mark.parametrize("rot,expected", [
        (0, (800, 480)),
        (90, (480, 800)),
        (180, (800, 480)),
        (270, (480, 800)),
    ])
    def test_non_square_800x480(self, rot, expected):
        assert output_resolution(800, 480, rot) == expected

    @pytest.mark.parametrize("rot,expected", [
        (0, (1600, 720)),
        (90, (720, 1600)),
        (180, (1600, 720)),
        (270, (720, 1600)),
    ])
    def test_non_square_1600x720(self, rot, expected):
        assert output_resolution(1600, 720, rot) == expected

    # Square — never swaps
    @pytest.mark.parametrize("rot", [0, 90, 180, 270])
    def test_square_320x320_never_swaps(self, rot):
        assert output_resolution(320, 320, rot) == (320, 320)

    @pytest.mark.parametrize("rot", [0, 90, 180, 270])
    def test_square_480x480_never_swaps(self, rot):
        assert output_resolution(480, 480, rot) == (480, 480)

    @pytest.mark.parametrize("rot", [0, 90, 180, 270])
    def test_square_240x240_never_swaps(self, rot):
        assert output_resolution(240, 240, rot) == (240, 240)

    def test_zero_resolution(self):
        assert output_resolution(0, 0, 90) == (0, 0)


# =========================================================================
# Orientation class
# =========================================================================


class TestOrientationSquare:
    """Orientation on a square device — dirs never swap."""

    def test_is_square(self):
        o = Orientation(320, 320)
        assert o.is_square is True

    def test_is_portrait_always_false(self):
        o = Orientation(320, 320)
        o.rotation = 90
        assert o.is_portrait is False

    def test_output_resolution_never_swaps(self):
        o = Orientation(320, 320)
        o.rotation = 90
        assert o.output_resolution == (320, 320)

    def test_canvas_resolution_never_swaps(self):
        o = Orientation(320, 320)
        o.rotation = 90
        assert o.canvas_resolution == (320, 320)

    def test_image_rotation_returns_actual(self):
        o = Orientation(320, 320)
        o.rotation = 90
        assert o.image_rotation == 90


class TestOrientationNonSquare:
    """Orientation on a non-square device — dirs swap when portrait dirs exist."""

    def _make(self, with_portrait: bool = False) -> Orientation:
        o = Orientation(1280, 480)
        o.landscape_theme_dir = ThemeDir('/data/theme1280480')
        o.landscape_web_dir = Path('/data/web/1280480')
        o.landscape_masks_dir = Path('/data/web/zt1280480')
        if with_portrait:
            o.portrait_theme_dir = ThemeDir('/data/theme4801280')
            o.portrait_web_dir = Path('/data/web/4801280')
            o.portrait_masks_dir = Path('/data/web/zt4801280')
        return o

    # Without portrait dirs — pixel rotation
    def test_no_portrait_swaps_dirs_false(self):
        o = self._make(with_portrait=False)
        o.rotation = 90
        assert o.swaps_dirs is False

    def test_no_portrait_has_rotated_dirs_false(self):
        o = self._make(with_portrait=False)
        assert o.has_rotated_dirs is False

    def test_no_portrait_theme_dir_is_landscape(self):
        o = self._make(with_portrait=False)
        o.rotation = 90
        assert 'theme1280480' in str(o.theme_dir.path)

    def test_no_portrait_image_rotation_is_actual(self):
        o = self._make(with_portrait=False)
        o.rotation = 90
        assert o.image_rotation == 90

    def test_no_portrait_canvas_stays_landscape(self):
        o = self._make(with_portrait=False)
        o.rotation = 90
        assert o.canvas_resolution == (1280, 480)

    # With web/mask portrait dirs only (no portrait themes) — no canvas swap
    def test_web_only_portrait_no_canvas_swap(self):
        o = self._make(with_portrait=False)
        o.portrait_web_dir = Path('/data/web/4801280')
        o.portrait_masks_dir = Path('/data/web/zt4801280')
        o.rotation = 90
        assert o.has_rotated_dirs is True
        assert o.swaps_dirs is False  # no portrait theme dir
        assert o.canvas_resolution == (1280, 480)  # stays landscape
        assert o.image_rotation == 90  # pixel-rotate

    def test_web_only_portrait_dirs_swap_independently(self):
        o = self._make(with_portrait=False)
        o.portrait_web_dir = Path('/data/web/4801280')
        o.rotation = 90
        assert 'theme1280480' in str(o.theme_dir.path)  # theme stays landscape
        assert str(o.web_dir) == '/data/web/4801280'  # web swaps to portrait

    # With all portrait dirs — dir swap
    def test_portrait_swaps_dirs_true_at_90(self):
        o = self._make(with_portrait=True)
        o.rotation = 90
        assert o.swaps_dirs is True

    def test_portrait_theme_dir_is_portrait(self):
        o = self._make(with_portrait=True)
        o.rotation = 90
        assert 'theme4801280' in str(o.theme_dir.path)

    def test_portrait_image_rotation_is_zero(self):
        o = self._make(with_portrait=True)
        o.rotation = 90
        assert o.image_rotation == 0

    def test_portrait_canvas_swaps(self):
        o = self._make(with_portrait=True)
        o.rotation = 90
        assert o.canvas_resolution == (480, 1280)

    def test_output_resolution_always_swaps(self):
        o = self._make(with_portrait=False)
        o.rotation = 90
        assert o.output_resolution == (480, 1280)

    # At 0° — always landscape
    def test_zero_rotation_uses_landscape(self):
        o = self._make(with_portrait=True)
        o.rotation = 0
        assert 'theme1280480' in str(o.theme_dir.path)
        assert o.swaps_dirs is False


class TestOrientationToDict:
    """to_dict serializes dir paths for config persistence."""

    def test_all_dirs_populated(self):
        o = Orientation(1280, 480)
        o.landscape_theme_dir = ThemeDir('/a')
        o.landscape_web_dir = Path('/b')
        o.landscape_masks_dir = Path('/c')
        o.portrait_theme_dir = ThemeDir('/d')
        o.portrait_web_dir = Path('/e')
        o.portrait_masks_dir = Path('/f')
        d = o.to_dict()
        assert d == {
            'theme': '/a', 'web': '/b', 'masks': '/c',
            'theme_portrait': '/d', 'web_portrait': '/e', 'masks_portrait': '/f',
        }

    def test_none_dirs(self):
        o = Orientation(320, 320)
        d = o.to_dict()
        assert all(v is None for v in d.values())


class TestOrientationFromDict:
    """from_dict restores Orientation from config values."""

    def test_round_trip(self):
        o = Orientation(1280, 480)
        o.landscape_theme_dir = ThemeDir('/a')
        o.landscape_web_dir = Path('/b')
        o.landscape_masks_dir = Path('/c')
        o.portrait_theme_dir = ThemeDir('/d')
        o.portrait_web_dir = Path('/e')
        o.portrait_masks_dir = Path('/f')
        restored = Orientation.from_dict(1280, 480, o.to_dict())
        assert restored is not None
        assert str(restored.landscape_theme_dir.path) == '/a'
        assert str(restored.portrait_web_dir) == '/e'

    def test_returns_none_for_malformed(self):
        assert Orientation.from_dict(320, 320, {}) is None
        assert Orientation.from_dict(320, 320, 'bad') is None

    def test_returns_none_when_no_theme(self):
        assert Orientation.from_dict(320, 320, {'web': '/b'}) is None
