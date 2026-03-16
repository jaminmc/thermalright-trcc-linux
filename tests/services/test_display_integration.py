"""Integration tests for DisplayService + LCDDevice with real services.

Tests state wiring that mocks can't catch — the exact class of bug
that caused v8.0.1 theme save failures. Real OverlayService, real
ImageService/Renderer, mocked DeviceService + MediaService.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from conftest import get_pixel

from trcc.core.lcd_device import LCDDevice
from trcc.core.models import ThemeInfo, ThemeType
from trcc.services.display import DisplayService
from trcc.services.image import ImageService
from trcc.services.overlay import OverlayService
from trcc.services.theme_persistence import ThemePersistence

# ── Fixtures ──────────────────────────────────────────────────────────────


@pytest.fixture()
def renderer() -> Any:
    return ImageService._r()


@pytest.fixture()
def mock_media() -> MagicMock:
    media = MagicMock()
    media._frames = []
    media.has_frames = False
    media.is_playing = False
    media.source_path = None
    media.get_frame.return_value = None
    media.frame_interval_ms = 33
    return media


@pytest.fixture()
def display_svc(renderer: Any, mock_media: MagicMock) -> DisplayService:
    """Real DisplayService with real OverlayService, mocked device/media."""
    devices = MagicMock()
    devices.selected.encoding_params = ('scsi', (320, 320), None, False)
    overlay = OverlayService(320, 320, renderer=renderer)
    svc = DisplayService(devices, overlay, mock_media)
    return svc


@pytest.fixture()
def lcd(display_svc: DisplayService, renderer: Any) -> LCDDevice:
    """LCDDevice wired to real display_svc."""
    return LCDDevice(
        device_svc=display_svc.devices,
        display_svc=display_svc,
        theme_svc=MagicMock(),
        renderer=renderer,
    )


@pytest.fixture()
def mock_settings():
    """Patch settings for 320x320."""
    with patch('trcc.conf.settings') as s:
        s.width = 320
        s.height = 320
        yield s


@pytest.fixture()
def static_theme(tmp_path: Path, renderer: Any) -> ThemeInfo:
    """Local theme with a blue 00.png background."""
    theme_dir = tmp_path / 'TestTheme'
    theme_dir.mkdir()
    bg = renderer.create_surface(320, 320, (0, 0, 255))
    bg.save(str(theme_dir / '00.png'))
    return ThemeInfo(
        name='TestTheme', path=theme_dir, theme_type=ThemeType.LOCAL,
        background_path=theme_dir / '00.png',
    )


@pytest.fixture()
def mask_theme(tmp_path: Path, renderer: Any) -> tuple[ThemeInfo, Path]:
    """Local theme with background + mask + DC config."""
    theme_dir = tmp_path / 'MaskTheme'
    theme_dir.mkdir()
    # Blue background
    bg = renderer.create_surface(320, 320, (0, 0, 255))
    bg.save(str(theme_dir / '00.png'))
    # Semi-transparent mask
    mask = renderer.create_surface(320, 320, (255, 255, 255, 128))
    mask.save(str(theme_dir / '01.png'))
    theme = ThemeInfo(
        name='MaskTheme', path=theme_dir, theme_type=ThemeType.LOCAL,
        background_path=theme_dir / '00.png',
        mask_path=theme_dir / '01.png',
    )
    return theme, theme_dir


# ═════════════════════════════════════════════════════════════════════════
# Group 1: load_local_theme() state wiring
# ═════════════════════════════════════════════════════════════════════════


class TestLoadLocalThemeStateWiring:
    """Verify that load_local_theme correctly wires internal state."""

    def test_static_theme_sets_clean_background(
        self, display_svc: DisplayService, static_theme: ThemeInfo,
        mock_settings: Any,
    ) -> None:
        """Loading a static theme must set _clean_background."""
        result = display_svc.load_local_theme(static_theme)

        assert result['image'] is not None
        assert display_svc._clean_background is not None
        # Clean bg should be the loaded image (not overlay-composited)
        assert display_svc._clean_background is display_svc.current_image

    def test_static_theme_sets_current_theme_path(
        self, display_svc: DisplayService, static_theme: ThemeInfo,
        mock_settings: Any,
    ) -> None:
        """Loading a theme must set current_theme_path to theme dir."""
        display_svc.load_local_theme(static_theme)

        assert display_svc.current_theme_path == static_theme.path

    def test_mask_theme_sets_mask_source_dir(
        self, display_svc: DisplayService,
        mask_theme: tuple[ThemeInfo, Path], mock_settings: Any,
    ) -> None:
        """Theme with mask must set _mask_source_dir."""
        theme, theme_dir = mask_theme
        display_svc.load_local_theme(theme)

        assert display_svc._mask_source_dir == theme_dir

    def test_no_mask_theme_clears_stale_mask_source_dir(
        self, display_svc: DisplayService, static_theme: ThemeInfo,
        mask_theme: tuple[ThemeInfo, Path], mock_settings: Any,
    ) -> None:
        """Loading theme WITHOUT mask after one WITH mask clears _mask_source_dir."""
        theme_with_mask, _ = mask_theme
        display_svc.load_local_theme(theme_with_mask)
        assert display_svc._mask_source_dir is not None

        # Now load theme without mask
        display_svc.load_local_theme(static_theme)
        assert display_svc._mask_source_dir is None

    def test_animated_theme_sets_clean_background_from_first_frame(
        self, display_svc: DisplayService, mock_media: MagicMock,
        renderer: Any, mock_settings: Any, tmp_path: Path,
    ) -> None:
        """Animated theme must set _clean_background from first video frame."""
        # Create a theme dir with a video reference
        theme_dir = tmp_path / 'AnimTheme'
        theme_dir.mkdir()
        # No 00.png — animated themes get their bg from first frame

        frame = renderer.create_surface(320, 320, (50, 100, 150))
        mock_media.get_frame.return_value = frame
        mock_media.has_frames = True

        # Patch the loader to return an animated result
        result = {
            'image': None, 'is_animated': True,
            'status': 'Theme: AnimTheme',
            'mask_source_dir': None, 'theme_path': theme_dir,
        }
        with patch.object(display_svc._loader, 'load_local_theme', return_value=result):
            display_svc.load_local_theme(MagicMock())

        assert display_svc._clean_background is frame


# ═════════════════════════════════════════════════════════════════════════
# Group 2: set_brightness / set_rotation with real images
# ═════════════════════════════════════════════════════════════════════════


class TestBrightnessRotationRealImages:
    """Verify actual pixel-level transformations."""

    def test_brightness_25_darkens_image(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any,
    ) -> None:
        """set_brightness(25) must darken a white image."""
        white = renderer.create_surface(320, 320, (255, 255, 255))
        display_svc.current_image = white
        display_svc._clean_background = white

        result = display_svc.set_brightness(25)
        assert result is not None

        r, g, b = get_pixel(result, 160, 160)[:3]
        # 25% brightness on white should be significantly darker
        assert r < 200, f"Expected darkened pixel, got r={r}"
        assert g < 200, f"Expected darkened pixel, got g={g}"
        assert b < 200, f"Expected darkened pixel, got b={b}"

    def test_brightness_100_is_identity(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any,
    ) -> None:
        """set_brightness(100) must not change pixels."""
        red = renderer.create_surface(320, 320, (200, 50, 30))
        display_svc.current_image = red
        display_svc._clean_background = red

        result = display_svc.set_brightness(100)
        assert result is not None

        r, g, b = get_pixel(result, 160, 160)[:3]
        assert abs(r - 200) <= 1
        assert abs(g - 50) <= 1
        assert abs(b - 30) <= 1

    def test_rotation_90_moves_pixels(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any,
    ) -> None:
        """set_rotation(90) must move pixels to rotated positions."""
        # Create image with red top-left quadrant, blue elsewhere
        from PIL import Image
        pil = Image.new('RGB', (320, 320), (0, 0, 255))
        # Paint top-left 10x10 red
        for x in range(10):
            for y in range(10):
                pil.putpixel((x, y), (255, 0, 0))
        img = renderer.from_pil(pil)

        display_svc.current_image = img
        display_svc._clean_background = img

        result = display_svc.set_rotation(90)
        assert result is not None

        # After 90 CW rotation, top-left red should NOT still be at (0, 0)
        r, g, b = get_pixel(result, 0, 0)[:3]
        # Top-left of rotated image should be blue (from bottom-left of original)
        assert r < 50, f"Expected blue after rotation, got r={r}"

    def test_rotation_0_is_identity(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any,
    ) -> None:
        """set_rotation(0) must not change pixels."""
        green = renderer.create_surface(320, 320, (0, 200, 0))
        display_svc.current_image = green
        display_svc._clean_background = green
        display_svc.brightness = 100  # avoid brightness dimming

        result = display_svc.set_rotation(0)
        assert result is not None

        r, g, b = get_pixel(result, 160, 160)[:3]
        assert abs(g - 200) <= 1


# ═════════════════════════════════════════════════════════════════════════
# Group 3: Theme load -> save round-trip
# ═════════════════════════════════════════════════════════════════════════


class TestThemeSaveRoundTrip:
    """Verify save captures correct state after various operations."""

    def test_save_uses_clean_bg_not_overlay(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any, tmp_path: Path,
    ) -> None:
        """Save after overlay must write clean bg to 00.png, not composited."""
        blue = renderer.create_surface(320, 320, (0, 0, 255))
        display_svc.current_image = blue
        display_svc._clean_background = blue

        # Enable overlay with text (changes the rendered image)
        display_svc.overlay.enabled = True
        display_svc.overlay.set_config({
            'label': {'x': 10, 'y': 10, 'text': 'HELLO',
                      'color': '#FF0000', 'enabled': True},
        })

        ok, msg = display_svc.save_theme('OverlayTest', tmp_path)
        assert ok is True

        # 00.png should be clean blue bg
        theme_path = tmp_path / 'theme320320' / 'Custom_OverlayTest'
        bg_path = theme_path / '00.png'
        assert bg_path.exists()

        saved_bg = renderer.open_image(bg_path)
        r, g, b = get_pixel(saved_bg, 160, 160)[:3]
        assert b > 200, f"00.png should be blue (clean bg), got b={b}"

    def test_save_after_mask_includes_mask_path(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any, tmp_path: Path,
    ) -> None:
        """Save after mask load must include mask dir in config.json."""
        blue = renderer.create_surface(320, 320, (0, 0, 255))
        display_svc.current_image = blue
        display_svc._clean_background = blue

        mask_dir = tmp_path / 'masks' / 'TestMask'
        mask_dir.mkdir(parents=True)
        mask = renderer.create_surface(320, 320, (0, 0, 0, 128))
        mask.save(str(mask_dir / '01.png'))

        # Load mask into overlay (as load_mask_standalone would)
        mask_img = renderer.open_image(mask_dir / '01.png')
        display_svc.overlay.set_mask(mask_img, (0, 0))
        display_svc._mask_source_dir = mask_dir
        display_svc.overlay.enabled = True

        save_dir = tmp_path / 'save_data'
        save_dir.mkdir()
        ok, msg = display_svc.save_theme('MaskSave', save_dir)
        assert ok is True

        config = json.loads(
            (save_dir / 'theme320320' / 'Custom_MaskSave' / 'config.json').read_text())
        assert config['mask'] == str(mask_dir)

    def test_save_after_cloud_load_no_stale_mask(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any, mock_media: MagicMock, tmp_path: Path,
    ) -> None:
        """Cloud load must clear mask, so save has no stale mask ref."""
        # Set up stale mask state
        display_svc._mask_source_dir = Path('/old/stale/mask')
        display_svc.current_image = renderer.create_surface(320, 320, (0, 0, 0))
        display_svc._clean_background = display_svc.current_image

        # Simulate cloud theme load
        frame = renderer.create_surface(320, 320, (50, 50, 50))
        mock_media.get_frame.return_value = frame
        mock_media.has_frames = True
        cloud_result = {
            'image': None, 'is_animated': True,
            'status': 'Cloud Theme: vid',
            'mask_source_dir': None, 'theme_path': None,
        }
        with patch.object(display_svc._loader, 'load_cloud_theme', return_value=cloud_result):
            display_svc.load_cloud_theme(MagicMock())

        assert display_svc._mask_source_dir is None

        # Save should NOT reference old mask
        with patch.object(ThemePersistence, 'save', return_value=(True, 'ok')) as mock_save:
            display_svc.save_theme('CloudSave', tmp_path)
        assert mock_save.call_args.kwargs.get('mask_source_dir') is None

    def test_save_after_brightness_uses_clean_bg(
        self, display_svc: DisplayService, renderer: Any,
        mock_settings: Any, tmp_path: Path,
    ) -> None:
        """Save after brightness change must write undimmed clean bg."""
        white = renderer.create_surface(320, 320, (255, 255, 255))
        display_svc.current_image = white
        display_svc._clean_background = white

        display_svc.set_brightness(25)

        ok, msg = display_svc.save_theme('BrightSave', tmp_path)
        assert ok is True

        theme_path = tmp_path / 'theme320320' / 'Custom_BrightSave'
        saved_bg = renderer.open_image(theme_path / '00.png')
        r, g, b = get_pixel(saved_bg, 160, 160)[:3]
        # Clean bg is white, NOT dimmed
        assert r > 240, f"00.png should be white (clean bg), got r={r}"
        assert g > 240, f"00.png should be white (clean bg), got g={g}"
        assert b > 240, f"00.png should be white (clean bg), got b={b}"


# ═════════════════════════════════════════════════════════════════════════
# Group 4: LCDDevice facade integration
# ═════════════════════════════════════════════════════════════════════════


class TestLCDDeviceIntegration:
    """Test LCDDevice methods with real services underneath."""

    def test_select_theme_wires_state(
        self, lcd: LCDDevice, display_svc: DisplayService,
        static_theme: ThemeInfo, mock_settings: Any,
    ) -> None:
        """lcd.select() must wire current_image and current_theme_path."""
        result = lcd.select(static_theme)

        assert result['success'] is True
        assert lcd.current_image is not None
        assert lcd.current_theme_path == static_theme.path

    def test_set_brightness_returns_transformed_image(
        self, lcd: LCDDevice, display_svc: DisplayService,
        renderer: Any, mock_settings: Any,
    ) -> None:
        """lcd.set_brightness() must return an actually transformed image."""
        white = renderer.create_surface(320, 320, (255, 255, 255))
        display_svc.current_image = white
        display_svc._clean_background = white

        with patch.object(lcd, '_persist'):
            result = lcd.settings.set_brightness(1)  # level 1 = 25%
        assert result['success'] is True
        assert result['image'] is not None

        r, g, b = get_pixel(result['image'], 160, 160)[:3]
        assert r < 200, f"Expected dimmed image, got r={r}"

    def test_save_round_trip(
        self, lcd: LCDDevice, display_svc: DisplayService,
        renderer: Any, mock_settings: Any, tmp_path: Path,
    ) -> None:
        """lcd.save() must write correct files to disk."""
        blue = renderer.create_surface(320, 320, (0, 0, 255))
        display_svc.current_image = blue
        display_svc._clean_background = blue

        result = lcd.save('RoundTrip', tmp_path)
        assert result['success'] is True

        theme_path = tmp_path / 'theme320320' / 'Custom_RoundTrip'
        assert (theme_path / '00.png').exists()
        assert (theme_path / 'Theme.png').exists()
        assert (theme_path / 'config.json').exists()

        # 00.png should be blue
        saved = renderer.open_image(theme_path / '00.png')
        r, g, b = get_pixel(saved, 160, 160)[:3]
        assert b > 200
