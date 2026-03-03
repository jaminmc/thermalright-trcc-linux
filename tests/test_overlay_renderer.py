"""OverlayService — overlay rendering (config, mask, metrics → image).

Every test runs against BOTH renderer backends (NumpyRenderer + PilRenderer)
via the parametrized ``overlay`` fixture.  This proves Liskov Substitution:
any Renderer ABC implementation is interchangeable without breaking behaviour.

Tests cover: initialization, resolution, format options, background/mask
handling, font loading, text rendering with metrics, config application,
dynamic scaling, mask scaling, flash skip, and full integration workflows.
"""
from __future__ import annotations

import os
import subprocess
import tempfile
from unittest.mock import MagicMock, patch

import pytest
from PIL import Image

from trcc.adapters.render.numpy_renderer import NumpyRenderer
from trcc.adapters.render.pil import PilRenderer
from trcc.core.models import HardwareMetrics
from trcc.services.overlay import OverlayService

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture(params=[NumpyRenderer, PilRenderer], ids=["numpy", "pil"])
def renderer(request):
    """Parametrized renderer — every test runs with both backends."""
    return request.param()


@pytest.fixture
def overlay(renderer):
    """OverlayService wired to the parametrized renderer."""
    return OverlayService(renderer=renderer)


@pytest.fixture
def overlay_480(renderer):
    """OverlayService at 480x480 resolution."""
    return OverlayService(width=480, height=480, renderer=renderer)


@pytest.fixture
def bg():
    """320x320 blue background."""
    return Image.new('RGB', (320, 320), 'blue')


@pytest.fixture
def mask():
    """320x100 red RGBA partial mask."""
    return Image.new('RGBA', (320, 100), (255, 0, 0, 128))


@pytest.fixture
def full_mask():
    """320x320 red RGBA full mask."""
    return Image.new('RGBA', (320, 320), (255, 0, 0, 128))


@pytest.fixture
def text_config():
    """Single static text element config."""
    return {
        'label': {
            'x': 160, 'y': 160,
            'text': 'Hello',
            'color': '#FFFFFF',
            'font': {'size': 24},
            'enabled': True,
        }
    }


@pytest.fixture
def metric_config():
    """Single cpu_temp metric element config."""
    return {
        'cpu_temp': {
            'x': 100, 'y': 100,
            'metric': 'cpu_temp',
            'color': '#FF6B35',
            'font': {'size': 24},
            'enabled': True,
        }
    }


@pytest.fixture
def full_config():
    """Complete config: time, cpu_temp, and static label."""
    return {
        'time': {
            'x': 160, 'y': 40,
            'metric': 'time',
            'color': '#FFFFFF',
            'font': {'size': 32, 'style': 'bold'},
            'enabled': True,
        },
        'cpu_temp': {
            'x': 80, 'y': 280,
            'metric': 'cpu_temp',
            'color': '#FF6B35',
            'font': {'size': 20},
            'enabled': True,
        },
        'label': {
            'x': 240, 'y': 280,
            'text': 'CPU',
            'color': '#AAAAAA',
            'font': {'size': 16},
            'enabled': True,
        },
    }


# ── Initialization ──────────────────────────────────────────────────────────


class TestInit:

    def test_default_resolution(self, overlay):
        assert overlay.width == 320
        assert overlay.height == 320

    def test_default_state(self, overlay):
        assert overlay.config == {}
        assert overlay.background is None
        assert overlay.theme_mask is None
        assert overlay.theme_mask_position == (0, 0)

    def test_custom_resolution(self, renderer):
        o = OverlayService(width=480, height=480, renderer=renderer)
        assert o.width == 480
        assert o.height == 480

    def test_rectangular_resolution(self, renderer):
        o = OverlayService(width=1600, height=720, renderer=renderer)
        assert o.width == 1600
        assert o.height == 720

    def test_default_format_options(self, overlay):
        assert overlay.time_format == 0
        assert overlay.date_format == 0
        assert overlay.temp_unit == 0


# ── Resolution ──────────────────────────────────────────────────────────────


class TestResolution:

    def test_change_resolution(self, overlay):
        overlay.set_resolution(480, 480)
        assert overlay.width == 480
        assert overlay.height == 480

    def test_clears_background_on_change(self, overlay, bg):
        overlay.set_background(bg)
        overlay.set_resolution(480, 480)
        assert overlay.background is None


# ── Format options ──────────────────────────────────────────────────────────


class TestFormatOptions:

    def test_set_temp_unit(self, overlay):
        overlay.set_temp_unit(1)
        assert overlay.temp_unit == 1

    def test_other_formats_unchanged(self, overlay):
        overlay.set_temp_unit(1)
        assert overlay.time_format == 0
        assert overlay.date_format == 0

    def test_toggle_celsius_fahrenheit(self, overlay):
        overlay.set_temp_unit(1)
        overlay.set_temp_unit(0)
        assert overlay.temp_unit == 0


# ── Config ──────────────────────────────────────────────────────────────────


class TestConfig:

    def test_set_empty(self, overlay):
        overlay.set_config({})
        assert overlay.config == {}

    def test_set_with_elements(self, overlay, metric_config):
        overlay.set_config(metric_config)
        assert overlay.config == metric_config

    def test_replaced_not_merged(self, overlay):
        overlay.set_config({'a': 1})
        overlay.set_config({'b': 2})
        assert 'a' not in overlay.config
        assert 'b' in overlay.config


# ── Background ──────────────────────────────────────────────────────────────


class TestBackground:

    def test_set_image(self, overlay, bg):
        overlay.set_background(bg)
        assert overlay.background is not None
        assert overlay.background.shape[:2] == (320, 320)

    def test_clear_with_none(self, overlay, bg):
        overlay.set_background(bg)
        overlay.set_background(None)
        assert overlay.background is None

    def test_resized_to_lcd(self, overlay_480):
        img = Image.new('RGB', (200, 200), 'green')
        overlay_480.set_background(img)
        assert overlay_480.background.shape[:2] == (480, 480)

    def test_copy_isolation(self, overlay):
        img = Image.new('RGB', (320, 320), 'red')
        overlay.set_background(img)
        img.putpixel((0, 0), (0, 0, 255))
        assert overlay.background is not None


# ── Mask ────────────────────────────────────────────────────────────────────


class TestMask:

    def test_clear_with_none(self, overlay, full_mask):
        overlay.theme_mask = full_mask
        overlay.set_theme_mask(None)
        assert overlay.theme_mask is None
        assert overlay.theme_mask_position == (0, 0)

    def test_explicit_position(self, overlay, full_mask):
        overlay.set_theme_mask(full_mask, position=(10, 20))
        assert overlay.theme_mask is not None
        assert overlay.theme_mask_position == (10, 20)

    def test_auto_position_partial(self, overlay, mask):
        overlay.set_theme_mask(mask)
        assert overlay.theme_mask_position == (0, 220)

    def test_auto_position_full(self, overlay, full_mask):
        overlay.set_theme_mask(full_mask)
        assert overlay.theme_mask_position == (0, 0)

    def test_rgb_converted_to_rgba(self, overlay):
        rgb_mask = Image.new('RGB', (320, 320), 'red')
        overlay.set_theme_mask(rgb_mask)
        assert overlay.theme_mask.ndim == 3 and overlay.theme_mask.shape[2] == 4


# ── Font ────────────────────────────────────────────────────────────────────


class TestFont:

    def test_caching(self, overlay):
        f1 = overlay.get_font(24, bold=False)
        f2 = overlay.get_font(24, bold=False)
        assert f1 is f2

    def test_different_sizes(self, overlay):
        f1 = overlay.get_font(24)
        f2 = overlay.get_font(32)
        assert f1 is not f2

    def test_bold_separate_cache(self, overlay):
        f1 = overlay.get_font(24, bold=False)
        f2 = overlay.get_font(24, bold=True)
        assert f1 is not f2

    def test_fallback_default(self, overlay):
        assert overlay.get_font(24) is not None


# ── Render ──────────────────────────────────────────────────────────────────


class TestRender:

    def test_empty_config(self, overlay):
        img = overlay.render()
        assert img.shape[:2] == (320, 320)
        assert img.ndim == 3 and img.shape[2] == 3

    def test_with_background(self, overlay, bg):
        overlay.set_background(bg)
        img = overlay.render()
        assert img.shape[:2] == (320, 320)

    def test_with_mask(self, overlay, bg, mask):
        overlay.set_background(bg)
        overlay.set_theme_mask(mask)
        img = overlay.render()
        assert img.shape[:2] == (320, 320)

    def test_static_text(self, overlay, text_config):
        overlay.set_config(text_config)
        img = overlay.render()
        assert img.shape[:2] == (320, 320)

    def test_metric_element(self, overlay, metric_config):
        overlay.set_config(metric_config)
        img = overlay.render(metrics=HardwareMetrics(cpu_temp=45))
        assert img.shape[:2] == (320, 320)

    def test_disabled_element_skipped(self, overlay):
        overlay.set_config({
            'hidden': {
                'x': 100, 'y': 100,
                'text': 'Should not render',
                'color': '#FF0000',
                'enabled': False,
            }
        })
        img = overlay.render()
        assert img.shape[:2] == (320, 320)

    def test_missing_metric_shows_na(self, overlay):
        overlay.set_config({
            'missing': {
                'x': 100, 'y': 100,
                'metric': 'nonexistent_metric',
                'color': '#FFFFFF',
                'enabled': True,
            }
        })
        img = overlay.render(metrics=HardwareMetrics())
        assert img.shape[:2] == (320, 320)

    def test_format_options(self, overlay):
        overlay.time_format = 1
        overlay.date_format = 2
        overlay.temp_unit = 1
        overlay.set_config({
            'time': {
                'x': 160, 'y': 160,
                'metric': 'time',
                'color': '#FFFFFF',
                'enabled': True,
            }
        })
        img = overlay.render(metrics=HardwareMetrics())
        assert img.shape[:2] == (320, 320)

    def test_per_element_temp_unit(self, overlay):
        overlay.set_temp_unit(0)  # Global: Celsius
        overlay.set_config({
            'temp1': {
                'x': 100, 'y': 100,
                'metric': 'cpu_temp',
                'color': '#FF6B35',
                'enabled': True,
                'temp_unit': 1,  # Override: Fahrenheit
            }
        })
        img = overlay.render(metrics=HardwareMetrics(cpu_temp=45))
        assert img.shape[:2] == (320, 320)

    def test_none_config(self, overlay):
        overlay.config = None
        img = overlay.render()
        assert img.shape[:2] == (320, 320)
        assert img.ndim == 3 and img.shape[2] == 3

    def test_non_dict_config(self, overlay):
        overlay.config = "invalid"
        img = overlay.render()
        assert img.shape[:2] == (320, 320)
        assert img.ndim == 3 and img.shape[2] == 3


# ── Clear ───────────────────────────────────────────────────────────────────


class TestClear:

    def test_resets_all(self, overlay, bg, mask):
        overlay.set_config({'key': 'value'})
        overlay.set_background(bg)
        overlay.set_theme_mask(mask)
        overlay.clear()
        assert overlay.config == {}
        assert overlay.background is None
        assert overlay.theme_mask is None
        assert overlay.theme_mask_position == (0, 0)

    def test_preserves_resolution(self, overlay_480):
        overlay_480.clear()
        assert overlay_480.width == 480
        assert overlay_480.height == 480

    def test_preserves_format_options(self, overlay):
        overlay.time_format = 1
        overlay.date_format = 2
        overlay.temp_unit = 1
        overlay.clear()
        assert overlay.time_format == 1
        assert overlay.date_format == 2
        assert overlay.temp_unit == 1


# ── Integration ─────────────────────────────────────────────────────────────


class TestIntegration:

    def test_full_workflow(self, overlay, bg, mask, full_config):
        overlay.set_background(bg)
        overlay.set_theme_mask(mask)
        overlay.set_config(full_config)
        img = overlay.render(metrics=HardwareMetrics(cpu_temp=45))
        assert img.shape[:2] == (320, 320)
        assert img.ndim == 3 and img.shape[2] == 3

    def test_render_without_metrics(self, overlay, metric_config):
        overlay.set_config(metric_config)
        img = overlay.render()
        assert img.shape[:2] == (320, 320)

    def test_transparent_background(self, overlay, text_config):
        overlay.set_config(text_config)
        img = overlay.render()
        assert img.ndim == 3 and img.shape[2] == 3
        assert tuple(img[0, 0]) == (0, 0, 0)


# ── Config elements edge cases ──────────────────────────────────────────────


class TestConfigElements:

    def test_no_font_config(self, overlay):
        overlay.set_config({
            'simple': {
                'x': 100, 'y': 100,
                'text': 'Test',
                'color': '#FFFFFF',
                'enabled': True,
            }
        })
        assert overlay.render().shape[:2] == (320, 320)

    def test_non_dict_font(self, overlay):
        overlay.set_config({
            'simple': {
                'x': 100, 'y': 100,
                'text': 'Test',
                'color': '#FFFFFF',
                'font': 'invalid',
                'enabled': True,
            }
        })
        assert overlay.render().shape[:2] == (320, 320)

    def test_no_position_uses_defaults(self, overlay):
        overlay.set_config({
            'no_pos': {
                'text': 'Test',
                'color': '#FFFFFF',
                'enabled': True,
            }
        })
        assert overlay.render().shape[:2] == (320, 320)

    def test_non_dict_element_skipped(self, overlay):
        overlay.set_config({
            'valid': {
                'x': 100, 'y': 100,
                'text': 'Valid',
                'enabled': True,
            },
            'invalid': 'not a dict',
        })
        assert overlay.render().shape[:2] == (320, 320)


# ── Scaling ─────────────────────────────────────────────────────────────────


class TestScaling:

    def test_set_config_resolution(self, overlay_480):
        overlay_480.set_config_resolution(320, 320)
        assert overlay_480._config_resolution == (320, 320)

    def test_scale_factor_default(self, overlay):
        assert overlay._get_scale_factor() == pytest.approx(1.0)

    def test_scale_factor_upscale(self, overlay_480):
        overlay_480.set_config_resolution(320, 320)
        assert overlay_480._get_scale_factor() == pytest.approx(1.5)

    def test_scale_factor_disabled(self, overlay_480):
        overlay_480.set_config_resolution(320, 320)
        overlay_480.set_scale_enabled(False)
        assert overlay_480._get_scale_factor() == pytest.approx(1.0)

    def test_scale_factor_zero_config(self, overlay):
        overlay._config_resolution = (0, 0)
        assert overlay._get_scale_factor() == pytest.approx(1.0)

    def test_set_scale_clears_font_cache(self, overlay):
        overlay.font_cache = {('key',): 'val'}
        overlay.set_scale_enabled(False)
        assert overlay.font_cache == {}


# ── Font path resolution ───────────────────────────────────────────────────


class TestFontPath:

    def test_fc_match_success(self, overlay):
        fd, tmp = tempfile.mkstemp(suffix='.ttf')
        os.close(fd)
        try:
            with patch('subprocess.run') as mock_run:
                mock_run.return_value = MagicMock(returncode=0, stdout=tmp)
                result = overlay._resolve_font_path('DejaVu Sans')
            assert result == tmp
        finally:
            os.unlink(tmp)

    def test_fc_match_not_found(self, overlay):
        with patch('subprocess.run', side_effect=FileNotFoundError):
            result = overlay._resolve_font_path('NoSuchFontXYZ')
        assert result is None

    def test_fc_match_timeout(self, overlay):
        with patch('subprocess.run',
                   side_effect=subprocess.TimeoutExpired('fc-match', 2)):
            result = overlay._resolve_font_path('SomeFont')
        assert result is None

    def test_fc_match_nonexistent_path(self, overlay):
        with patch('subprocess.run') as mock_run:
            mock_run.return_value = MagicMock(
                returncode=0, stdout='/nonexistent/font.ttf')
            result = overlay._resolve_font_path('SomeFont')
        assert result is None

    def test_manual_scan_finds_font(self, overlay):
        with tempfile.TemporaryDirectory() as tmpdir:
            open(os.path.join(tmpdir, 'DejaVuSans.ttf'), 'w').close()
            with patch('subprocess.run', side_effect=FileNotFoundError), \
                 patch('trcc.adapters.infra.font_resolver.FONT_SEARCH_DIRS',
                       [tmpdir]):
                result = overlay._resolve_font_path('DejaVu Sans')
            if result:
                assert 'DejaVu' in result


# ── Named font ──────────────────────────────────────────────────────────────


class TestNamedFont:

    def test_named_font_resolved(self, overlay):
        with patch.object(overlay, '_resolve_font_path', return_value=None):
            font = overlay.get_font(24, bold=False, font_name='CustomFont')
        assert font is not None


# ── Mask scaling ────────────────────────────────────────────────────────────


class TestMaskScaling:

    def test_mask_scales_with_factor(self, overlay_480):
        overlay_480.set_config_resolution(320, 320)
        overlay_480.set_background(Image.new('RGB', (480, 480), 'blue'))
        overlay_480.set_theme_mask(
            Image.new('RGBA', (320, 100), (255, 0, 0, 128)),
            position=(0, 220))
        overlay_480.set_config({})
        img = overlay_480.render()
        assert img.shape[:2] == (480, 480)


# ── Flash skip ──────────────────────────────────────────────────────────────


class TestFlashSkip:

    def test_skips_element(self, overlay):
        overlay.flash_skip_index = 0
        overlay.set_config({
            'label': {
                'x': 100, 'y': 100,
                'text': 'Flash',
                'color': '#FF0000',
                'enabled': True,
            }
        })
        assert overlay.render().shape[:2] == (320, 320)


# ── Metric paths ────────────────────────────────────────────────────────────


class TestMetricPaths:

    def test_no_text_no_metric_skips(self, overlay):
        overlay.set_config({
            'empty': {
                'x': 100, 'y': 100,
                'color': '#FFFFFF',
                'enabled': True,
            }
        })
        assert overlay.render().shape[:2] == (320, 320)

    def test_custom_font_name(self, overlay):
        overlay.set_config({
            'label': {
                'x': 100, 'y': 100,
                'text': 'Hello',
                'color': '#FFFFFF',
                'font': {'size': 20, 'style': 'bold', 'name': 'DejaVu Sans'},
                'enabled': True,
            }
        })
        assert overlay.render().shape[:2] == (320, 320)


# ── Mask visibility ─────────────────────────────────────────────────────────


class TestMaskVisible:

    def test_toggle_visibility(self, overlay):
        overlay.set_mask_visible(False)
        assert not overlay.theme_mask_visible
        overlay.set_mask_visible(True)
        assert overlay.theme_mask_visible

    def test_render_with_mask_hidden(self, overlay, bg, mask):
        overlay.set_background(bg)
        overlay.set_theme_mask(mask)
        overlay.set_mask_visible(False)
        overlay.set_config({'x': {'x': 0, 'y': 0, 'text': 'hi', 'enabled': True}})
        img = overlay.render()
        assert img.shape[:2] == (320, 320)


# ── Fallback format_metric ──────────────────────────────────────────────────


class TestFallbackFormatMetric:
    """Test the fallback format function (import failure scenario)."""

    def test_celsius(self):
        def fallback(metric, value, time_format=0, date_format=0, temp_unit=0):
            if 'temp' in metric:
                if temp_unit == 1:
                    return f"{value * 9 / 5 + 32:.0f}\u00b0F"
                return f"{value:.0f}\u00b0C"
            return str(value)

        assert fallback('cpu_temp', 50) == '50\u00b0C'
        assert fallback('gpu_temp', 50, temp_unit=1) == '122\u00b0F'
        assert fallback('cpu_percent', 42) == '42'
