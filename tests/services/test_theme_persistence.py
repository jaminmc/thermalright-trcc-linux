"""Tests for theme save bug fixes (v8.0.1).

Verifies:
1. ThemePersistence.save() saves clean bg as 00.png, rendered preview as Theme.png
2. DisplayService.save_theme() passes _clean_background, not current_image
3. load_mask_standalone() wires _mask_source_dir so save writes mask to config.json
4. Cloud theme load clears stale _mask_source_dir
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from conftest import make_test_surface

from trcc.core.lcd_device import LCDDevice
from trcc.services.display import DisplayService
from trcc.services.image import ImageService
from trcc.services.overlay import OverlayService
from trcc.services.theme_persistence import ThemePersistence

# ── Fixtures ──────────────────────────────────────────────────────────────────


@pytest.fixture()
def renderer() -> Any:
    return ImageService._r()


@pytest.fixture()
def lcd_size() -> tuple[int, int]:
    return (320, 320)


@pytest.fixture()
def blue_bg(renderer: Any) -> Any:
    """Clean background — blue."""
    return renderer.create_surface(320, 320, (0, 0, 255))


@pytest.fixture()
def green_bg(renderer: Any) -> Any:
    """Rendered overlay result — green."""
    return renderer.create_surface(320, 320, (0, 255, 0))


@pytest.fixture()
def mock_overlay(green_bg: Any) -> MagicMock:
    """OverlayService mock that returns green from render()."""
    overlay = MagicMock(spec=OverlayService)
    overlay.render.return_value = green_bg
    overlay.get_mask.return_value = (None, None)
    overlay.config = {'time': {'x': 10, 'y': 20, 'metric': 'time', 'enabled': True}}
    return overlay


@pytest.fixture()
def mask_dir(tmp_path: Path, renderer: Any) -> Path:
    """Theme mask directory with 01.png."""
    d = tmp_path / 'zt320320' / 'Theme5'
    d.mkdir(parents=True)
    mask = renderer.create_surface(320, 320, (0, 0, 0, 128))
    mask.save(str(d / '01.png'))
    return d


@pytest.fixture()
def display_svc(renderer: Any) -> DisplayService:
    """DisplayService with real OverlayService, mocked device/media."""
    devices = MagicMock()
    overlay = OverlayService(320, 320, renderer=renderer)
    media = MagicMock()
    media._frames = []
    media.has_frames = False
    media.is_playing = False
    media.source_path = None
    media.get_frame.return_value = None

    svc = DisplayService(devices, overlay, media)
    svc.current_image = renderer.create_surface(320, 320, (0, 0, 255))
    svc._clean_background = svc.current_image
    return svc


@pytest.fixture()
def lcd(display_svc: DisplayService, renderer: Any) -> LCDDevice:
    """LCDDevice wired to display_svc (the GUI path)."""
    return LCDDevice(
        device_svc=display_svc.devices,
        display_svc=display_svc,
        renderer=renderer,
    )


@pytest.fixture()
def mock_settings():
    """Patch settings for 320x320."""
    with patch('trcc.conf.settings') as s:
        s.width = 320
        s.height = 320
        yield s


# ── ThemePersistence.save() ───────────────────────────────────────────────────


class TestThemePersistenceSave:

    def test_saves_clean_bg_not_rendered(
        self, tmp_path: Path, lcd_size: tuple[int, int],
        blue_bg: Any, mock_overlay: MagicMock,
    ) -> None:
        """00.png must be the clean background, not the overlay-composited image."""
        ok, _ = ThemePersistence.save(
            'TestClean', tmp_path, lcd_size,
            current_image=blue_bg, overlay=mock_overlay,
            mask_source_dir=None, media_source_path=None,
            media_is_playing=False, current_theme_path=None,
        )
        assert ok is True

        theme_path = tmp_path / 'theme320320' / 'Custom_TestClean'
        bg_data = (theme_path / '00.png').read_bytes()
        thumb_data = (theme_path / 'Theme.png').read_bytes()
        assert bg_data != thumb_data, \
            "00.png (clean bg) must differ from Theme.png (rendered preview)"

    def test_overlay_render_called_for_thumbnail(
        self, tmp_path: Path, lcd_size: tuple[int, int],
        blue_bg: Any, mock_overlay: MagicMock,
    ) -> None:
        """overlay.render() must be called to produce the thumbnail preview."""
        ThemePersistence.save(
            'RenderCall', tmp_path, lcd_size,
            current_image=blue_bg, overlay=mock_overlay,
            mask_source_dir=None, media_source_path=None,
            media_is_playing=False, current_theme_path=None,
        )
        mock_overlay.render.assert_called_once_with(blue_bg)

    def test_overlay_config_saved(
        self, tmp_path: Path, lcd_size: tuple[int, int],
        blue_bg: Any, mock_overlay: MagicMock,
    ) -> None:
        """Overlay config must be written to config.json dc field."""
        ThemePersistence.save(
            'CfgSave', tmp_path, lcd_size,
            current_image=blue_bg, overlay=mock_overlay,
            mask_source_dir=None, media_source_path=None,
            media_is_playing=False, current_theme_path=None,
        )
        config = json.loads(
            (tmp_path / 'theme320320' / 'Custom_CfgSave' / 'config.json').read_text())
        assert config['dc'] == mock_overlay.config

    def test_mask_source_propagated(
        self, tmp_path: Path, lcd_size: tuple[int, int],
        blue_bg: Any, mock_overlay: MagicMock, mask_dir: Path,
    ) -> None:
        """mask_source_dir must flow through to config.json mask field."""
        mock_overlay.get_mask.return_value = (blue_bg, (0, 0))

        ThemePersistence.save(
            'MaskProp', tmp_path, lcd_size,
            current_image=blue_bg, overlay=mock_overlay,
            mask_source_dir=mask_dir, media_source_path=None,
            media_is_playing=False, current_theme_path=None,
        )
        config = json.loads(
            (tmp_path / 'theme320320' / 'Custom_MaskProp' / 'config.json').read_text())
        assert config['mask'] == str(mask_dir)

    def test_no_image_returns_false(
        self, tmp_path: Path, lcd_size: tuple[int, int],
        mock_overlay: MagicMock,
    ) -> None:
        ok, msg = ThemePersistence.save(
            'NoImg', tmp_path, lcd_size,
            current_image=None, overlay=mock_overlay,
            mask_source_dir=None, media_source_path=None,
            media_is_playing=False, current_theme_path=None,
        )
        assert ok is False
        assert 'No image' in msg


# ── DisplayService.save_theme() ──────────────────────────────────────────────


class TestDisplayServiceSaveTheme:

    def test_passes_clean_background(
        self, display_svc: DisplayService, tmp_path: Path,
        mock_settings: Any, renderer: Any,
    ) -> None:
        """save_theme must pass _clean_background, not current_image."""
        clean = renderer.create_surface(320, 320, (0, 0, 255))
        dirty = renderer.create_surface(320, 320, (255, 0, 0))
        display_svc._clean_background = clean
        display_svc.current_image = dirty

        with patch.object(ThemePersistence, 'save', return_value=(True, 'ok')) as mock_save:
            display_svc.save_theme('Test', tmp_path)

        passed = mock_save.call_args.kwargs.get('current_image') or mock_save.call_args[0][3]
        assert passed is clean

    def test_falls_back_to_current_image(
        self, display_svc: DisplayService, tmp_path: Path,
        mock_settings: Any, renderer: Any,
    ) -> None:
        """When _clean_background is None, falls back to current_image."""
        current = renderer.create_surface(320, 320, (255, 0, 0))
        display_svc._clean_background = None
        display_svc.current_image = current

        with patch.object(ThemePersistence, 'save', return_value=(True, 'ok')) as mock_save:
            display_svc.save_theme('Fallback', tmp_path)

        passed = mock_save.call_args.kwargs.get('current_image') or mock_save.call_args[0][3]
        assert passed is current


# ── load_mask_standalone → save round-trip ────────────────────────────────────


class TestLoadMaskStandaloneWiring:
    """The REAL bug: load_mask_standalone bypassed DisplayService.apply_mask,
    so _mask_source_dir was never set. Save then wrote mask=null."""

    def test_sets_mask_source_dir(
        self, lcd: LCDDevice, display_svc: DisplayService, mask_dir: Path,
    ) -> None:
        """load_mask_standalone must update _display_svc._mask_source_dir."""
        result = lcd.load_mask_standalone(str(mask_dir))

        assert result['success'] is True
        assert display_svc._mask_source_dir == mask_dir

    def test_save_after_mask_has_mask_in_config(
        self, lcd: LCDDevice, display_svc: DisplayService,
        mask_dir: Path, tmp_path: Path, mock_settings: Any,
    ) -> None:
        """Full flow: load_mask_standalone → save → config.json has mask."""
        lcd.load_mask_standalone(str(mask_dir))

        data_dir = tmp_path / 'save_data'
        data_dir.mkdir()
        ok, msg = display_svc.save_theme('MaskTest', data_dir)
        assert ok is True

        config = json.loads(
            (data_dir / 'theme320320' / 'Custom_MaskTest' / 'config.json').read_text())
        assert config['mask'] == str(mask_dir), \
            f"Expected mask={mask_dir}, got {config['mask']}"


# ── Cloud theme load clears stale state ──────────────────────────────────────


class TestCloudThemeStateWiring:

    def test_clears_stale_mask_source_dir(
        self, display_svc: DisplayService, mock_settings: Any,
    ) -> None:
        """Loading a cloud theme must clear _mask_source_dir from previous theme."""
        display_svc._mask_source_dir = Path('/old/mask')

        cloud_result = {
            'image': None, 'is_animated': True,
            'status': 'Cloud Theme: vid',
            'mask_source_dir': None,
            'theme_path': None,
        }
        with patch.object(display_svc._loader, 'load_cloud_theme', return_value=cloud_result):
            display_svc.load_cloud_theme(MagicMock())

        assert display_svc._mask_source_dir is None

    def test_wires_theme_path(
        self, display_svc: DisplayService, mock_settings: Any,
    ) -> None:
        """load_cloud_theme must set current_theme_path."""
        fake_path = Path('/fake/theme')
        cloud_result = {
            'image': None, 'is_animated': True,
            'status': 'Cloud Theme: vid',
            'mask_source_dir': None,
            'theme_path': fake_path,
        }
        with patch.object(display_svc._loader, 'load_cloud_theme', return_value=cloud_result):
            display_svc.load_cloud_theme(MagicMock())

        assert display_svc.current_theme_path is fake_path

    def test_sets_clean_background_from_first_frame(
        self, display_svc: DisplayService, mock_settings: Any, renderer: Any,
    ) -> None:
        """load_cloud_theme must set _clean_background from first video frame."""
        frame = renderer.create_surface(320, 320, (50, 50, 50))
        display_svc.media.get_frame.return_value = frame

        cloud_result = {
            'image': None, 'is_animated': True,
            'status': 'Cloud Theme: vid',
            'mask_source_dir': None,
            'theme_path': None,
        }
        with patch.object(display_svc._loader, 'load_cloud_theme', return_value=cloud_result):
            display_svc.load_cloud_theme(MagicMock())

        assert display_svc._clean_background is frame

    def test_save_after_cloud_load_no_stale_mask(
        self, display_svc: DisplayService, tmp_path: Path, mock_settings: Any,
    ) -> None:
        """Save after cloud load must NOT reference old mask."""
        display_svc._mask_source_dir = Path('/old/mask')
        display_svc.media.get_frame.return_value = make_test_surface(320, 320, (50, 50, 50))

        cloud_result = {
            'image': None, 'is_animated': True,
            'status': 'Cloud Theme: vid',
            'mask_source_dir': None,
            'theme_path': None,
        }
        with patch.object(display_svc._loader, 'load_cloud_theme', return_value=cloud_result):
            display_svc.load_cloud_theme(MagicMock())

        with patch.object(ThemePersistence, 'save', return_value=(True, 'ok')) as mock_save:
            display_svc.save_theme('CloudSave', tmp_path)

        assert mock_save.call_args.kwargs.get('mask_source_dir') is None
