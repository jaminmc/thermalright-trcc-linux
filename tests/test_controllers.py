"""
Tests for core.controllers — Facade controllers driving the PyQt6 GUI.

LCDDeviceController and LEDDeviceController are Facades: take request →
call service → fire callback. Business logic is tested in test_services.py.
These tests verify:
- Callbacks fire at the right time
- Service methods are called via facade
- State is accessible through controller properties
"""

import json
import shutil
import tempfile
import unittest
from pathlib import Path
from unittest.mock import MagicMock, PropertyMock, patch

import numpy as np
from PIL import Image

from tests.conftest import make_test_image as _make_test_image
from trcc.core.controllers import (
    LCDDeviceController,
    create_controller,
)
from trcc.core.models import (
    DeviceInfo,
    HardwareMetrics,
    PlaybackState,
    ThemeInfo,
    ThemeType,
)

# Patches to avoid file I/O and downloads during LCDDeviceController tests
LCD_SVC_PATCHES = [
    ('trcc.adapters.infra.data_repository.DataManager.ensure_all', None),
    ('trcc.conf.Settings._save_resolution', None),
]


def _make_form_controller():
    """Create a LCDDeviceController with path functions mocked."""
    from trcc.conf import settings as _settings
    _settings._width = 320
    _settings._height = 320

    patches = []
    for target, return_val in LCD_SVC_PATCHES:
        m = patch(target, return_value=return_val)
        patches.append(m)
        m.start()
    ctrl = LCDDeviceController()
    return ctrl, patches


def _stop_patches(patches):
    for p in patches:
        p.stop()

# =============================================================================
# Theme Facade Methods
# =============================================================================

class TestThemeFacade(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_initial_state(self):
        self.assertIsNone(self.ctrl.get_selected_theme())
        self.assertEqual(self.ctrl.get_themes(), [])

    def test_set_directories(self):
        local = Path('/tmp/themes')
        web = Path('/tmp/web')
        masks = Path('/tmp/masks')
        self.ctrl.set_theme_directories(local_dir=local, web_dir=web, masks_dir=masks)
        self.assertEqual(self.ctrl.theme_svc.local_dir, local)
        self.assertEqual(self.ctrl.theme_svc.web_dir, web)
        self.assertEqual(self.ctrl.theme_svc.masks_dir, masks)

    def test_set_filter(self):
        fired = []
        self.ctrl.on_filter_changed = lambda mode: fired.append(mode)
        self.ctrl.set_theme_filter('user')
        self.assertEqual(fired, ['user'])

    def test_set_category(self):
        self.ctrl.set_theme_category('b')
        self.assertEqual(self.ctrl.theme_svc._category, 'b')
        self.ctrl.set_theme_category('all')
        self.assertIsNone(self.ctrl.theme_svc._category)

    def test_select_theme_routes_to_local(self):
        """select_theme(local) routes to load_local_theme."""
        theme = ThemeInfo(name='Test', path=Path('/tmp/test'))
        with patch.object(self.ctrl, 'load_local_theme') as m:
            self.ctrl.select_theme(theme)
            m.assert_called_once_with(theme)

    def test_select_theme_routes_to_cloud(self):
        """select_theme(cloud) routes to load_cloud_theme."""
        theme = ThemeInfo(name='Cloud', theme_type=ThemeType.CLOUD)
        with patch.object(self.ctrl, 'load_cloud_theme') as m:
            self.ctrl.select_theme(theme)
            m.assert_called_once_with(theme)

    def test_load_local_themes_with_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            theme_dir = Path(tmp) / 'Theme1'
            theme_dir.mkdir()
            (theme_dir / '00.png').write_bytes(b'PNG')
            (theme_dir / 'Theme.png').write_bytes(b'PNG')

            self.ctrl.set_theme_directories(local_dir=Path(tmp))
            self.ctrl.load_local_themes((320, 320))
            themes = self.ctrl.get_themes()
            self.assertEqual(len(themes), 1)
            self.assertEqual(themes[0].name, 'Theme1')

    def test_on_themes_loaded_callback(self):
        fired = []
        self.ctrl.on_themes_loaded = lambda themes: fired.append(len(themes))

        with tempfile.TemporaryDirectory() as tmp:
            theme_dir = Path(tmp) / 'T1'
            theme_dir.mkdir()
            (theme_dir / '00.png').write_bytes(b'x')

            self.ctrl.set_theme_directories(local_dir=Path(tmp))
            self.ctrl.load_local_themes()

        self.assertEqual(len(fired), 1)

    def test_categories_dict(self):
        self.assertIn('all', LCDDeviceController.CATEGORIES)
        self.assertIn('a', LCDDeviceController.CATEGORIES)

    def test_set_directories_local_only(self):
        self.ctrl.set_theme_directories(local_dir=Path('/tmp/loc'))
        self.assertEqual(self.ctrl.theme_svc.local_dir, Path('/tmp/loc'))

    def test_load_cloud_themes(self):
        with patch('trcc.services.theme.ThemeService.discover_cloud', return_value=[]):
            self.ctrl.theme_svc._web_dir = Path('/tmp/web')
            self.ctrl.load_cloud_themes()

    def test_select_theme_none(self):
        """select_theme(None) is a no-op — no crash."""
        self.ctrl.select_theme(None)

    def test_set_filter_no_callback(self):
        self.ctrl.on_filter_changed = None
        self.ctrl.set_theme_filter('default')
        # No crash


# =============================================================================
# Device Facade Methods
# =============================================================================

class TestDeviceFacade(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_initial_state(self):
        self.assertEqual(self.ctrl.get_devices(), [])
        self.assertIsNone(self.ctrl.get_selected_device())

    def test_select_device(self):
        fired = []
        self.ctrl.on_device_selected = lambda d: fired.append(d)
        dev = DeviceInfo(name='LCD', path='/dev/sg0')
        self.ctrl.select_device(dev)
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0].path, '/dev/sg0')

    def test_send_started_callback(self):
        started = []
        self.ctrl.on_send_started = lambda: started.append(True)
        self.ctrl._display.devices._send_busy = False
        self.ctrl._display.devices.select(DeviceInfo(name='LCD', path='/dev/sg0'))

        with patch.object(self.ctrl._display.devices, 'send_rgb565_async'):
            self.ctrl.send_image_async(b'\x00' * 100, 10, 10)

        self.assertTrue(started)

    def test_send_skipped_when_busy(self):
        started = []
        self.ctrl.on_send_started = lambda: started.append(True)
        self.ctrl._display.devices._send_busy = True
        self.ctrl.send_image_async(b'\x00', 1, 1)
        self.assertEqual(started, [])

    def test_detect_devices_delegates(self):
        with patch.object(self.ctrl._display.devices, 'detect') as m:
            self.ctrl.detect_devices()
            m.assert_called_once()

    def test_get_protocol_info_no_device(self):
        info = self.ctrl.get_protocol_info()
        self.assertIsNotNone(info)


# =============================================================================
# Video Facade Methods
# =============================================================================

class TestVideoFacade(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_initial_state(self):
        self.assertFalse(self.ctrl.is_video_playing())
        self.assertFalse(self.ctrl.video_has_frames())

    def test_play_pause_stop(self):
        self.ctrl._display.media._frames = [MagicMock()] * 10
        self.ctrl._display.media._state.total_frames = 10

        self.ctrl.play_video()
        self.assertTrue(self.ctrl.is_video_playing())

        self.ctrl.pause_video()
        self.assertFalse(self.ctrl.is_video_playing())

        self.ctrl.play_video()
        self.ctrl.stop_video()
        self.assertFalse(self.ctrl.is_video_playing())

    def test_toggle_play_pause(self):
        self.ctrl._display.media._frames = [MagicMock()] * 10
        self.ctrl._display.media._state.total_frames = 10

        self.ctrl.toggle_play_pause()
        self.assertTrue(self.ctrl.is_video_playing())

        self.ctrl.toggle_play_pause()
        self.assertFalse(self.ctrl.is_video_playing())

    def test_seek(self):
        self.ctrl._display.media._state.total_frames = 100
        self.ctrl.seek_video(50.0)
        self.assertEqual(self.ctrl._display.media._state.current_frame, 50)

    def test_video_tick_no_frame(self):
        """video_tick is a no-op when nothing is playing."""
        with patch.object(self.ctrl._display, 'video_tick', return_value=None):
            self.ctrl.video_tick()  # No crash

    def test_get_video_interval(self):
        ms = self.ctrl.get_video_interval()
        self.assertGreater(ms, 0)
        self.assertEqual(ms, 62)

    def test_on_video_loaded_callback(self):
        fired = []
        self.ctrl.on_video_loaded = lambda s: fired.append(s)

        with patch.object(self.ctrl._display.media, 'load', return_value=True):
            self.ctrl.load_video(Path('fake.mp4'))

        self.assertEqual(len(fired), 1)

    def test_load_failure(self):
        fired = []
        self.ctrl.on_video_loaded = lambda s: fired.append(s)
        with patch.object(self.ctrl._display.media, 'load', return_value=False):
            result = self.ctrl.load_video(Path('bad.mp4'))
        self.assertFalse(result)
        self.assertEqual(fired, [])

    def test_has_frames_with_data(self):
        self.ctrl._display.media._frames = [MagicMock()]
        self.assertTrue(self.ctrl.video_has_frames())

    def test_state_changed_callback_on_play(self):
        """play_video fires on_video_state_changed."""
        fired = []
        self.ctrl.on_video_state_changed = lambda s: fired.append(s)
        self.ctrl._display.media._frames = [MagicMock()] * 10
        self.ctrl._display.media._state.total_frames = 10

        self.ctrl.play_video()
        self.assertEqual(len(fired), 1)
        self.assertEqual(fired[0], PlaybackState.PLAYING)


class TestVideoFacadeFrameSkip(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_tick_frame_skip(self):
        self.ctrl._display.media.LCD_SEND_INTERVAL = 3

        frames = [_make_test_image()] * 10
        self.ctrl._display.media._frames = frames
        self.ctrl._display.media._state.state = PlaybackState.PLAYING
        self.ctrl._display.media._state.total_frames = 10
        self.ctrl._display.media._state.current_frame = 0
        self.ctrl._display.media._state.loop = True

        with patch.object(self.ctrl, 'send_pil_async') as mock_send:
            self.ctrl.video_tick()
            self.ctrl.video_tick()
            self.assertEqual(mock_send.call_count, 0)
            self.ctrl.video_tick()
            self.assertEqual(mock_send.call_count, 1)


# =============================================================================
# Overlay Facade Methods
# =============================================================================

class TestOverlayFacade(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_initial_state(self):
        self.assertFalse(self.ctrl.is_overlay_enabled())

    def test_enable_disable(self):
        self.ctrl.enable_overlay(True)
        self.assertTrue(self.ctrl.is_overlay_enabled())
        self.ctrl.enable_overlay(False)
        self.assertFalse(self.ctrl.is_overlay_enabled())

    def test_on_config_changed_callback(self):
        fired = []
        self.ctrl.on_overlay_config_changed = lambda: fired.append(True)
        self.ctrl.set_overlay_config({'key': 'val'})
        self.assertEqual(len(fired), 1)

    def test_update_metrics(self):
        self.ctrl.update_overlay_metrics(HardwareMetrics(cpu_temp=65))

    def test_render_no_config_returns_background(self):
        """With no config/mask, render returns background as-is (fast path)."""
        bg = Image.new('RGB', (320, 320), 'blue')
        self.ctrl.set_overlay_background(bg)
        result = self.ctrl.render_overlay(bg)
        self.assertIsInstance(result, np.ndarray)
        self.assertEqual(result.shape, (320, 320, 3))
        self.assertEqual(tuple(result[0, 0]), (0, 0, 255))


class TestOverlayFacadeRenderer(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_set_theme_mask(self):
        mask_img = Image.new('RGBA', (320, 100), (255, 0, 0, 128))
        self.ctrl.set_overlay_theme_mask(mask_img, (10, 20))
        self.assertIsNotNone(self.ctrl.overlay_svc.theme_mask)
        self.assertEqual(self.ctrl.overlay_svc.theme_mask_position, (10, 20))

    def test_get_theme_mask(self):
        mask_img = Image.new('RGBA', (320, 100), (255, 0, 0, 128))
        self.ctrl.overlay_svc.theme_mask = mask_img
        self.ctrl.overlay_svc.theme_mask_position = (5, 5)
        mask, pos = self.ctrl.get_overlay_theme_mask()
        self.assertIs(mask, mask_img)
        self.assertEqual(pos, (5, 5))

    def test_set_mask_visible(self):
        self.ctrl.set_overlay_mask_visible(False)
        self.assertFalse(self.ctrl.overlay_svc.theme_mask_visible)

    def test_set_temp_unit(self):
        self.ctrl.set_overlay_temp_unit(1)
        self.assertEqual(self.ctrl.overlay_svc.temp_unit, 1)

    def test_set_config(self):
        self.ctrl.set_overlay_config({'key': 'val'})
        self.assertEqual(self.ctrl.overlay_svc.config, {'key': 'val'})

    def test_set_config_resolution(self):
        self.ctrl.overlay_svc.set_config_resolution(480, 480)
        self.assertEqual(self.ctrl.overlay_svc._config_resolution, (480, 480))

    def test_set_scale_enabled(self):
        self.ctrl.overlay_svc.set_scale_enabled(False)
        self.assertFalse(self.ctrl.overlay_svc._scale_enabled)

    def test_load_from_dc(self):
        with patch.object(self.ctrl.overlay_svc, 'load_from_dc', return_value={}) as m:
            result = self.ctrl.overlay_svc.load_from_dc(Path('/fake/config1.dc'))
            self.assertEqual(result, {})
            m.assert_called_once()

    def test_render_delegates_to_service(self):
        bg = Image.new('RGB', (320, 320), 'blue')
        with patch.object(self.ctrl._display.overlay, 'render', return_value=bg) as mock_render:
            result = self.ctrl.render_overlay(bg)
            mock_render.assert_called_once_with(bg)
            self.assertEqual(result, bg)

    def test_set_background(self):
        bg = Image.new('RGB', (320, 320), 'blue')
        self.ctrl.set_overlay_background(bg)
        self.assertIsNotNone(self.ctrl.overlay_svc.background)


class TestOverlayFacadeDefaults(unittest.TestCase):
    """Test overlay facade methods on fresh (empty) service."""

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_get_theme_mask_default(self):
        mask, pos = self.ctrl.get_overlay_theme_mask()
        self.assertIsNone(mask)
        self.assertEqual(pos, (0, 0))

    def test_set_mask_visible_default(self):
        self.ctrl.set_overlay_mask_visible(True)
        self.assertTrue(self.ctrl.overlay_svc.theme_mask_visible)

    def test_set_temp_unit_default(self):
        self.ctrl.set_overlay_temp_unit(0)
        self.assertEqual(self.ctrl.overlay_svc.temp_unit, 0)

    def test_set_config_empty(self):
        self.ctrl.set_overlay_config({})
        self.assertEqual(self.ctrl.overlay_svc.config, {})

    def test_set_config_resolution_default(self):
        self.ctrl.overlay_svc.set_config_resolution(320, 320)
        self.assertEqual(self.ctrl.overlay_svc._config_resolution, (320, 320))

    def test_set_scale_enabled_default(self):
        self.ctrl.overlay_svc.set_scale_enabled(True)
        self.assertTrue(self.ctrl.overlay_svc._scale_enabled)


# =============================================================================
# LCDDeviceController — thin waiter over DisplayService
# =============================================================================

class TestLCDDeviceController(unittest.TestCase):

    def setUp(self):
        from trcc.conf import settings as _settings
        _settings._width = 320
        _settings._height = 320

        self.patches = [
            patch('trcc.adapters.infra.data_repository.DataManager.ensure_all'),
            patch('trcc.conf.Settings._save_resolution'),
        ]
        for p in self.patches:
            p.start()

        self.ctrl = LCDDeviceController()

    def tearDown(self):
        self.ctrl.cleanup()
        for p in self.patches:
            p.stop()

    def test_initial_resolution(self):
        self.assertEqual(self.ctrl.lcd_width, 320)
        self.assertEqual(self.ctrl.lcd_height, 320)

    def test_working_dir_created(self):
        self.assertTrue(self.ctrl.working_dir.exists())
        self.assertTrue(self.ctrl.working_dir.is_dir())

    def test_cleanup_removes_working_dir(self):
        wd = self.ctrl.working_dir
        self.assertTrue(wd.exists())
        self.ctrl.cleanup()
        self.assertFalse(wd.exists())

    def test_set_resolution(self):
        fired = []
        self.ctrl.on_resolution_changed = lambda w, h: fired.append((w, h))
        self.ctrl.set_resolution(480, 480)
        self.assertEqual(self.ctrl.lcd_width, 480)
        self.assertEqual(self.ctrl.lcd_height, 480)
        self.assertEqual(fired, [(480, 480)])

    def test_set_resolution_no_op_same(self):
        fired = []
        self.ctrl.on_resolution_changed = lambda w, h: fired.append((w, h))
        self.ctrl.set_resolution(320, 320)
        self.assertEqual(fired, [])

    def test_set_rotation(self):
        self.ctrl._display.current_image = _make_test_image()
        self.ctrl.set_rotation(90)
        self.assertEqual(self.ctrl.rotation, 90)
        self.ctrl.set_rotation(450)
        self.assertEqual(self.ctrl.rotation, 90)

    def test_set_brightness_clamps(self):
        self.ctrl._display.current_image = _make_test_image()
        self.ctrl.set_brightness(150)
        self.assertEqual(self.ctrl.brightness, 100)
        self.ctrl.set_brightness(-10)
        self.assertEqual(self.ctrl.brightness, 0)

    def test_auto_send_default(self):
        self.assertTrue(self.ctrl.auto_send)

    def test_play_pause(self):
        with patch.object(self.ctrl._display.media, 'toggle') as mock:
            self.ctrl.play_pause()
            mock.assert_called_once()

    def test_seek_video(self):
        with patch.object(self.ctrl._display.media, 'seek') as mock:
            self.ctrl.seek_video(50.0)
            mock.assert_called_once_with(50.0)

    def test_is_video_playing(self):
        self.assertFalse(self.ctrl.is_video_playing())

    def test_fire_status(self):
        fired = []
        self.ctrl.on_status_update = lambda s: fired.append(s)
        self.ctrl._fire_status('testing')
        self.assertEqual(fired, ['testing'])

    def test_fire_error(self):
        errors = []
        self.ctrl.on_error = lambda e: errors.append(e)
        self.ctrl._fire_error('broke')
        self.assertEqual(errors, ['broke'])

    def test_send_current_image_no_image(self):
        self.ctrl._display.current_image = None
        self.ctrl.send_current_image()  # Should not raise

    def test_current_image_property(self):
        img = _make_test_image()
        self.ctrl.current_image = img
        self.assertIs(self.ctrl.current_image, img)

    def test_current_theme_path_property(self):
        p = Path('/tmp/theme')
        self.ctrl.current_theme_path = p
        self.assertEqual(self.ctrl.current_theme_path, p)

    def test_service_accessors(self):
        """Facade exposes service instances via properties."""
        from trcc.services.device import DeviceService
        from trcc.services.display import DisplayService
        from trcc.services.media import MediaService
        from trcc.services.overlay import OverlayService
        from trcc.services.theme import ThemeService
        self.assertIsInstance(self.ctrl.lcd_svc, DisplayService)
        self.assertIsInstance(self.ctrl.theme_svc, ThemeService)
        self.assertIsInstance(self.ctrl.device_svc, DeviceService)
        self.assertIsInstance(self.ctrl.overlay_svc, OverlayService)
        self.assertIsInstance(self.ctrl.media_svc, MediaService)


# =============================================================================
# LCDDeviceController — theme operations (delegate to DisplayService)
# =============================================================================

class TestFormCZTVThemeOps(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_theme_dir(self, name='TestTheme', with_bg=True, with_mask=False):
        d = Path(self.tmp) / name
        d.mkdir(parents=True, exist_ok=True)
        if with_bg:
            img = _make_test_image(self.ctrl.lcd_width, self.ctrl.lcd_height)
            img.save(str(d / '00.png'))
        if with_mask:
            mask = _make_test_image(self.ctrl.lcd_width, self.ctrl.lcd_height, (0, 0, 255))
            mask.save(str(d / '01.png'))
        return d

    def test_load_local_theme_static(self):
        theme_dir = self._make_theme_dir(with_bg=True)
        theme = ThemeInfo(name='T', path=theme_dir)

        statuses = []
        self.ctrl.on_status_update = lambda s: statuses.append(s)

        self.ctrl.load_local_theme(theme)

        self.assertIsNotNone(self.ctrl.current_image)
        self.assertEqual(self.ctrl.current_theme_path, theme_dir)
        self.assertIn('Theme: T', statuses)

    def test_load_local_theme_mask_only(self):
        theme_dir = self._make_theme_dir(with_bg=False, with_mask=True)
        theme = ThemeInfo(name='Mask', path=theme_dir, is_mask_only=True)

        self.ctrl.load_local_theme(theme)
        self.assertIsNotNone(self.ctrl.current_image)

    def test_load_cloud_theme(self):
        theme = ThemeInfo(
            name='Cloud', theme_type=ThemeType.CLOUD,
            animation_path=Path('/fake/cloud.mp4'),
        )
        with patch.object(self.ctrl._display.media, 'load', return_value=True), \
             patch.object(self.ctrl._display.media, 'play'), \
             patch.object(self.ctrl._display.media, 'get_frame',
                          return_value=_make_test_image()):
            previews = []
            self.ctrl.on_preview_update = lambda img: previews.append(img)
            self.ctrl.load_cloud_theme(theme)
            self.assertIsNotNone(self.ctrl.current_image)

    def test_load_cloud_theme_no_path(self):
        theme = ThemeInfo(name='Empty', theme_type=ThemeType.CLOUD)
        self.ctrl.load_cloud_theme(theme)
        self.assertIsNone(self.ctrl.current_image)

    def test_apply_mask(self):
        self.ctrl._display.current_image = _make_test_image()
        mask_dir = self._make_theme_dir('Mask', with_mask=True)

        self.ctrl.apply_mask(mask_dir)
        self.assertTrue(self.ctrl.is_overlay_enabled())

    def test_apply_mask_no_background(self):
        self.ctrl._display.current_image = None
        mask_dir = self._make_theme_dir('Mask', with_mask=True)

        self.ctrl.apply_mask(mask_dir)
        self.assertIsNotNone(self.ctrl.current_image)

    def test_apply_mask_nonexistent_dir(self):
        self.ctrl.apply_mask(Path('/nonexistent'))

    def test_save_theme_no_image(self):
        self.ctrl._display.current_image = None
        ok, msg = self.ctrl.save_theme('test', Path(self.tmp))
        self.assertFalse(ok)
        self.assertIn('No image', msg)

    def test_save_theme_success(self):
        self.ctrl._display.current_image = _make_test_image()
        ok, msg = self.ctrl.save_theme('MyTheme', Path(self.tmp))
        self.assertTrue(ok)
        self.assertIn('Custom_MyTheme', msg)
        theme_path = Path(self.tmp) / 'theme320320' / 'Custom_MyTheme'
        self.assertTrue(theme_path.exists())

    def test_save_theme_already_custom(self):
        self.ctrl._display.current_image = _make_test_image()
        ok, msg = self.ctrl.save_theme('Custom_Existing', Path(self.tmp))
        self.assertTrue(ok)
        self.assertIn('Custom_Existing', msg)
        self.assertFalse(
            (Path(self.tmp) / 'theme320320' / 'Custom_Custom_Existing').exists())

    def test_save_theme_generates_thumbnail(self):
        self.ctrl._display.current_image = _make_test_image()
        ok, _ = self.ctrl.save_theme('Thumb', Path(self.tmp))
        self.assertTrue(ok)
        theme_path = Path(self.tmp) / 'theme320320' / 'Custom_Thumb'
        self.assertTrue((theme_path / 'Theme.png').exists())

    def test_export_config_no_theme(self):
        self.ctrl._display.current_theme_path = None
        ok, msg = self.ctrl.export_config(Path('/tmp/out.tr'))
        self.assertFalse(ok)
        self.assertIn('No theme', msg)

    def test_export_config_tr(self):
        self.ctrl._display.current_theme_path = Path('/tmp/theme')
        with patch('trcc.adapters.infra.dc_writer.export_theme') as mock_export:
            ok, msg = self.ctrl.export_config(Path('/tmp/out.tr'))
            self.assertTrue(ok)
            mock_export.assert_called_once()

    def test_export_config_json(self):
        self.ctrl._display.current_theme_path = Path('/tmp/theme')
        out_path = Path(self.tmp) / 'config.json'
        ok, msg = self.ctrl.export_config(out_path)
        self.assertTrue(ok)
        with open(out_path) as f:
            data = json.load(f)
        self.assertIn('theme_path', data)
        self.assertIn('resolution', data)

    def test_export_config_error(self):
        self.ctrl._display.current_theme_path = Path('/tmp/theme')
        with patch('trcc.adapters.infra.dc_writer.export_theme', side_effect=RuntimeError('boom')):
            ok, msg = self.ctrl.export_config(Path('/tmp/out.tr'))
            self.assertFalse(ok)
            self.assertIn('Export failed', msg)

    def test_import_config_json(self):
        theme_dir = self._make_theme_dir('ImportMe', with_bg=True)
        json_path = Path(self.tmp) / 'import.json'
        with open(json_path, 'w') as f:
            json.dump({'theme_path': str(theme_dir)}, f)

        with patch.object(self.ctrl, 'load_local_theme'):
            ok, msg = self.ctrl.import_config(json_path, Path(self.tmp))
            self.assertTrue(ok)

    def test_import_config_json_missing_path(self):
        json_path = Path(self.tmp) / 'bad.json'
        with open(json_path, 'w') as f:
            json.dump({'theme_path': '/nonexistent'}, f)

        ok, msg = self.ctrl.import_config(json_path, Path(self.tmp))
        self.assertFalse(ok)
        self.assertIn('not found', msg)

    def test_import_config_tr(self):
        tr_path = Path(self.tmp) / 'theme.tr'
        tr_path.write_bytes(b'\xdd\xdc\xdd\xdc')

        with patch('trcc.adapters.infra.dc_writer.import_theme'), \
             patch.object(self.ctrl._display, 'load_local_theme'):
            ok, msg = self.ctrl.import_config(tr_path, Path(self.tmp))
            self.assertTrue(ok)

    def test_import_config_error(self):
        tr_path = Path(self.tmp) / 'bad.tr'
        tr_path.write_bytes(b'junk')
        with patch('trcc.adapters.infra.dc_writer.import_theme', side_effect=RuntimeError('nope')):
            ok, msg = self.ctrl.import_config(tr_path, Path(self.tmp))
            self.assertFalse(ok)
            self.assertIn('Import failed', msg)

    def test_load_image_file(self):
        img_path = Path(self.tmp) / 'test.png'
        _make_test_image().save(str(img_path))
        self.ctrl.load_image_file(img_path)
        self.assertIsNotNone(self.ctrl.current_image)


# =============================================================================
# LCDDeviceController — video tick + LCD send
# =============================================================================

class TestFormCZTVVideoAndSend(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_video_tick_with_frame(self):
        """video_tick always fires preview callback with the frame."""
        previews = []
        self.ctrl.on_preview_update = lambda img: previews.append(img)

        fake_result = {'frame': _make_test_image(), 'send': False, 'progress': None}
        with patch.object(self.ctrl._display, 'video_tick', return_value=fake_result):
            self.ctrl.video_tick()

        self.assertEqual(len(previews), 1)

    def test_video_tick_no_frame(self):
        with patch.object(self.ctrl._display, 'video_tick', return_value=None):
            self.ctrl.video_tick()

    def test_video_tick_sends_to_lcd(self):
        send_img = _make_test_image()
        fake_result = {'frame': send_img, 'send': True, 'progress': None}

        with patch.object(self.ctrl._display, 'video_tick', return_value=fake_result), \
             patch.object(self.ctrl, 'send_pil_async') as mock_send:
            self.ctrl.video_tick()
            mock_send.assert_called_once_with(send_img, 320, 320)

    def test_get_video_interval(self):
        ms = self.ctrl.get_video_interval()
        self.assertIsInstance(ms, int)
        self.assertGreater(ms, 0)

    def test_send_current_image(self):
        self.ctrl._display.current_image = _make_test_image()
        statuses = []
        self.ctrl.on_status_update = lambda s: statuses.append(s)

        with patch.object(self.ctrl._display, 'send_current_image',
                          return_value=b'\x00' * 100), \
             patch.object(self.ctrl, 'send_image_async'):
            self.ctrl.send_current_image()

        self.assertIn('Sent to LCD', statuses)

    def test_send_frame_to_lcd_no_device(self):
        """_send_frame_to_lcd is a no-op without selected device."""
        self.ctrl._display.devices._selected = None
        self.ctrl._send_frame_to_lcd(_make_test_image())

    def test_send_frame_to_lcd_with_device(self):
        dev = DeviceInfo(name='LCD', path='/dev/sg0')
        self.ctrl._display.devices.select(dev)

        with patch.object(self.ctrl, 'send_pil_async') as mock_send:
            self.ctrl._send_frame_to_lcd(_make_test_image())
            mock_send.assert_called_once()
            args = mock_send.call_args
            self.assertEqual(args[0][1], 320)
            self.assertEqual(args[0][2], 320)


# =============================================================================
# LCDDeviceController — callbacks
# =============================================================================

class TestFormCZTVCallbacks(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)

    def test_render_overlay_and_preview(self):
        self.ctrl._display.current_image = _make_test_image()
        rendered = _make_test_image(color=(0, 255, 0))

        with patch.object(self.ctrl._display, 'render_overlay', return_value=rendered):
            previews = []
            self.ctrl.on_preview_update = lambda img: previews.append(img)
            result = self.ctrl.render_overlay_and_preview()
            self.assertEqual(result, rendered)
            self.assertEqual(len(previews), 1)

    def test_render_overlay_and_preview_no_image(self):
        self.ctrl._display.current_image = None

        with patch.object(self.ctrl._display, 'render_overlay',
                          return_value=_make_test_image()):
            result = self.ctrl.render_overlay_and_preview()
            self.assertIsNotNone(result)


# =============================================================================
# LCDDeviceController — initialize
# =============================================================================

class TestFormCZTVInitialize(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_initialize(self):
        data_dir = Path(self.tmp)
        (data_dir / 'theme320320').mkdir()

        with patch.object(self.ctrl, 'set_theme_directories') as mock_dirs, \
             patch.object(self.ctrl, 'load_local_themes') as mock_load, \
             patch.object(self.ctrl, 'detect_devices') as mock_detect:
            self.ctrl.initialize(data_dir)
            mock_dirs.assert_called_once()
            mock_load.assert_called_once()
            mock_detect.assert_called_once()

    def test_set_resolution_reloads_themes(self):
        with patch.object(self.ctrl, 'set_theme_directories') as mock_dirs, \
             patch.object(self.ctrl, 'load_local_themes') as mock_load:
            self.ctrl.set_resolution(480, 480)
            mock_dirs.assert_called_once()
            mock_load.assert_called_once()

    def test_set_resolution_no_persist(self):
        self.ctrl.set_resolution(240, 240, persist=False)
        self.assertEqual(self.ctrl.lcd_width, 240)


# =============================================================================
# Reference theme save/load
# =============================================================================

class TestReferenceThemeSaveLoad(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def _make_ref_theme(self, name='RefTheme', background=None, mask=None,
                        dc=None, mask_position=None):
        d = Path(self.tmp) / name
        d.mkdir(parents=True, exist_ok=True)
        img = _make_test_image(self.ctrl.lcd_width, self.ctrl.lcd_height)
        img.save(str(d / '00.png'))
        config = {
            'background': background,
            'mask': mask,
            'dc': dc or {},
        }
        if mask_position:
            config['mask_position'] = list(mask_position)
        with open(str(d / 'config.json'), 'w') as f:
            json.dump(config, f)
        return d

    def test_load_ref_static_image(self):
        bg_dir = Path(self.tmp) / 'bg_source'
        bg_dir.mkdir()
        bg_path = bg_dir / 'wallpaper.png'
        _make_test_image().save(str(bg_path))

        theme_dir = self._make_ref_theme(background=str(bg_path))
        theme = ThemeInfo(name='RefStatic', path=theme_dir)

        statuses = []
        self.ctrl.on_status_update = lambda s: statuses.append(s)
        self.ctrl.load_local_theme(theme)

        self.assertIsNotNone(self.ctrl.current_image)
        self.assertEqual(self.ctrl.current_theme_path, theme_dir)
        self.assertIn('Theme: RefStatic', statuses)

    def test_load_ref_video(self):
        video_path = Path(self.tmp) / 'source' / 'clip.mp4'
        video_path.parent.mkdir()
        video_path.write_bytes(b'\x00' * 100)

        theme_dir = self._make_ref_theme(background=str(video_path))
        theme = ThemeInfo(name='RefVideo', path=theme_dir)

        with patch.object(self.ctrl._display.media, 'load', return_value=True), \
             patch.object(self.ctrl._display.media, 'play'), \
             patch.object(self.ctrl._display.media, 'get_frame',
                          return_value=_make_test_image()):
            self.ctrl.load_local_theme(theme)

    def test_load_ref_zt(self):
        zt_path = Path(self.tmp) / 'source' / 'Theme.zt'
        zt_path.parent.mkdir()
        zt_path.write_bytes(b'\xdc\x00')

        theme_dir = self._make_ref_theme(background=str(zt_path))
        theme = ThemeInfo(name='RefZT', path=theme_dir)

        with patch.object(self.ctrl._display.media, 'load', return_value=True), \
             patch.object(self.ctrl._display.media, 'play'):
            self.ctrl.load_local_theme(theme)

    def test_load_ref_overlay_enabled(self):
        bg_dir = Path(self.tmp) / 'bg_src'
        bg_dir.mkdir()
        bg_path = bg_dir / 'bg.png'
        _make_test_image().save(str(bg_path))

        dc = {'time_0': {'x': 10, 'y': 20, 'metric': 'time'}}
        theme_dir = self._make_ref_theme(background=str(bg_path), dc=dc)
        theme = ThemeInfo(name='RefOverlay', path=theme_dir)

        self.ctrl.load_local_theme(theme)
        self.assertTrue(self.ctrl.is_overlay_enabled())

    def test_load_ref_overlay_disabled_empty_dc(self):
        bg_dir = Path(self.tmp) / 'bg_src2'
        bg_dir.mkdir()
        bg_path = bg_dir / 'bg.png'
        _make_test_image().save(str(bg_path))

        theme_dir = self._make_ref_theme(background=str(bg_path), dc={})
        theme = ThemeInfo(name='RefNoOverlay', path=theme_dir)

        self.ctrl.load_local_theme(theme)
        self.assertFalse(self.ctrl.is_overlay_enabled())

    def test_load_ref_with_mask(self):
        bg_dir = Path(self.tmp) / 'bg_src'
        bg_dir.mkdir()
        bg_path = bg_dir / 'bg.png'
        _make_test_image().save(str(bg_path))

        mask_dir = Path(self.tmp) / 'mask_src'
        mask_dir.mkdir()
        _make_test_image(color=(0, 0, 255)).save(str(mask_dir / '01.png'))

        theme_dir = self._make_ref_theme(
            background=str(bg_path), mask=str(mask_dir),
            mask_position=[160, 160])
        theme = ThemeInfo(name='RefMask', path=theme_dir)

        self.ctrl.load_local_theme(theme)
        self.assertIsNotNone(self.ctrl.current_image)

    def test_load_ref_missing_background(self):
        theme_dir = self._make_ref_theme(background='/nonexistent/bg.png')
        theme = ThemeInfo(name='RefMissing', path=theme_dir)

        statuses = []
        self.ctrl.on_status_update = lambda s: statuses.append(s)
        self.ctrl.load_local_theme(theme)
        self.assertIn('Theme: RefMissing', statuses)

    def test_load_fallback_no_config_json(self):
        d = Path(self.tmp) / 'OldTheme'
        d.mkdir()
        _make_test_image().save(str(d / '00.png'))
        theme = ThemeInfo(name='OldStyle', path=d)

        self.ctrl.load_local_theme(theme)
        self.assertIsNotNone(self.ctrl.current_image)

    def test_save_theme_writes_config_json(self):
        self.ctrl._display.current_image = _make_test_image()
        source_dir = Path(self.tmp) / 'source_theme'
        source_dir.mkdir()
        _make_test_image().save(str(source_dir / '00.png'))
        self.ctrl._display.current_theme_path = source_dir

        ok, msg = self.ctrl.save_theme('JsonSave', Path(self.tmp))
        self.assertTrue(ok)

        theme_path = Path(self.tmp) / 'theme320320' / 'Custom_JsonSave'
        self.assertTrue((theme_path / 'config.json').exists())
        self.assertTrue((theme_path / 'Theme.png').exists())
        self.assertTrue((theme_path / '00.png').exists())

        with open(str(theme_path / 'config.json')) as f:
            config = json.load(f)
        self.assertIn('background', config)
        self.assertIn('mask', config)
        self.assertIn('dc', config)
        self.assertEqual(config['background'], str(theme_path / '00.png'))

    def test_save_theme_video_background(self):
        self.ctrl._display.current_image = _make_test_image()
        self.ctrl._display.current_theme_path = Path(self.tmp) / 'src'
        self.ctrl._display.current_theme_path.mkdir()

        # Create a real video file (save copies it into the theme dir)
        video_file = Path(self.tmp) / 'clip.mp4'
        video_file.write_bytes(b'fake-video-data')

        with patch.object(type(self.ctrl._display.media), 'is_playing',
                          new_callable=PropertyMock, return_value=True), \
             patch.object(type(self.ctrl._display.media), 'source_path',
                          new_callable=PropertyMock,
                          return_value=video_file):
            ok, msg = self.ctrl.save_theme('VidRef', Path(self.tmp))

        self.assertTrue(ok)
        theme_path = Path(self.tmp) / 'theme320320' / 'Custom_VidRef'
        with open(str(theme_path / 'config.json')) as f:
            config = json.load(f)
        # Video should be copied with original extension preserved
        self.assertEqual(config['background'], str(theme_path / 'Theme.mp4'))
        self.assertTrue((theme_path / 'Theme.mp4').exists())

    def test_save_theme_with_mask(self):
        self.ctrl._display.current_image = _make_test_image()
        source_dir = Path(self.tmp) / 'mask_src'
        source_dir.mkdir()
        _make_test_image().save(str(source_dir / '00.png'))
        mask_img = _make_test_image(color=(0, 0, 255))
        mask_img.save(str(source_dir / '01.png'))
        self.ctrl._display.current_theme_path = source_dir
        self.ctrl._display._mask_source_dir = source_dir

        with patch.object(self.ctrl._display.overlay, 'get_mask',
                          return_value=(mask_img, (160, 160))):
            ok, msg = self.ctrl.save_theme('MaskRef', Path(self.tmp))

        self.assertTrue(ok)
        theme_path = Path(self.tmp) / 'theme320320' / 'Custom_MaskRef'
        with open(str(theme_path / 'config.json')) as f:
            config = json.load(f)
        self.assertEqual(config['mask'], str(source_dir))
        self.assertEqual(config['mask_position'], [160, 160])

    def test_save_theme_no_mask(self):
        self.ctrl._display.current_image = _make_test_image()
        self.ctrl._display.current_theme_path = Path(self.tmp) / 'nomask'
        self.ctrl._display.current_theme_path.mkdir()

        ok, msg = self.ctrl.save_theme('NoMask', Path(self.tmp))
        self.assertTrue(ok)
        theme_path = Path(self.tmp) / 'theme320320' / 'Custom_NoMask'
        with open(str(theme_path / 'config.json')) as f:
            config = json.load(f)
        self.assertIsNone(config['mask'])
        self.assertNotIn('mask_position', config)

    def test_save_theme_no_source_still_has_background(self):
        """Background path must reference saved 00.png even without a source theme."""
        self.ctrl._display.current_image = _make_test_image()
        self.ctrl._display.current_theme_path = None  # No source theme

        ok, msg = self.ctrl.save_theme('NoSource', Path(self.tmp))
        self.assertTrue(ok)
        theme_path = Path(self.tmp) / 'theme320320' / 'Custom_NoSource'
        with open(str(theme_path / 'config.json')) as f:
            config = json.load(f)
        # Must NOT be null — this was the bug causing black backgrounds
        self.assertIsNotNone(config['background'])
        self.assertEqual(config['background'], str(theme_path / '00.png'))
        self.assertTrue((theme_path / '00.png').exists())

    def test_save_theme_updates_current_path(self):
        self.ctrl._display.current_image = _make_test_image()
        self.ctrl._display.current_theme_path = Path(self.tmp) / 'original'
        self.ctrl._display.current_theme_path.mkdir()

        ok, _ = self.ctrl.save_theme('PathUpdate', Path(self.tmp))
        self.assertTrue(ok)
        expected = Path(self.tmp) / 'theme320320' / 'Custom_PathUpdate'
        self.assertEqual(self.ctrl.current_theme_path, expected)


# =============================================================================
# create_controller factory + autostart
# =============================================================================

class TestCreateController(unittest.TestCase):

    def test_create_without_data_dir(self):
        ctrl = create_controller()
        self.assertIsInstance(ctrl, LCDDeviceController)
        ctrl.cleanup()

    def test_create_with_data_dir(self):
        with tempfile.TemporaryDirectory() as tmp:
            data_dir = Path(tmp)
            (data_dir / 'theme320320').mkdir()

            with patch('trcc.adapters.infra.data_repository.DataManager.ensure_all'), \
                 patch('trcc.conf.Settings._save_resolution'):
                ctrl = create_controller(data_dir)
                self.assertIsInstance(ctrl, LCDDeviceController)
                ctrl.cleanup()


class TestAutostartDeviceRestore(unittest.TestCase):

    def setUp(self):
        self.ctrl, self.patches = _make_form_controller()
        self.tmp = tempfile.mkdtemp()

    def tearDown(self):
        self.ctrl.cleanup()
        _stop_patches(self.patches)
        shutil.rmtree(self.tmp, ignore_errors=True)

    def test_initialize_preselects_device(self):
        data_dir = Path(self.tmp)
        (data_dir / 'theme320320').mkdir()

        fake_device = DeviceInfo(
            name='LCD', path='/dev/sg0', resolution=(320, 320),
            vid=0x0402, pid=0x3922, device_index=0,
        )

        def fake_detect():
            self.ctrl._display.devices._devices = [fake_device]
            self.ctrl._display.devices.select(fake_device)
            return [fake_device]

        with patch.object(self.ctrl, 'detect_devices',
                          side_effect=fake_detect):
            self.ctrl.initialize(data_dir)

        selected = self.ctrl.get_selected_device()
        self.assertIsNotNone(selected)
        assert selected is not None
        self.assertEqual(selected.path, '/dev/sg0')

    def test_callback_after_preselection_not_called(self):
        data_dir = Path(self.tmp)
        (data_dir / 'theme320320').mkdir()

        fake_device = DeviceInfo(
            name='LCD', path='/dev/sg0', resolution=(320, 320),
            vid=0x0402, pid=0x3922, device_index=0,
        )

        view_calls = []

        def fake_detect():
            self.ctrl._display.devices._devices = [fake_device]
            self.ctrl._display.devices.select(fake_device)
            return [fake_device]

        with patch.object(self.ctrl, 'detect_devices',
                          side_effect=fake_detect):
            self.ctrl.initialize(data_dir)

        self.ctrl.on_device_selected = lambda d: view_calls.append(d)
        self.assertEqual(view_calls, [])

    def test_retrigger_with_get_selected(self):
        fake_device = DeviceInfo(
            name='LCD', path='/dev/sg0', resolution=(320, 320),
            vid=0x0402, pid=0x3922, device_index=0,
        )
        self.ctrl._display.devices.select(fake_device)

        view_calls = []
        self.ctrl.on_device_selected = lambda d: view_calls.append(d)

        selected = self.ctrl.get_selected_device()
        if selected:
            self.ctrl.on_device_selected(selected)

        self.assertEqual(len(view_calls), 1)
        self.assertEqual(view_calls[0].path, '/dev/sg0')

    def test_theme_selected_fires_status(self):
        data_dir = Path(self.tmp)
        theme_dir = data_dir / 'theme320320' / 'TestTheme'
        theme_dir.mkdir(parents=True)
        img = Image.new('RGB', (10, 10), color=(255, 0, 0))
        img.save(str(theme_dir / '00.png'))

        fake_device = DeviceInfo(
            name='LCD', path='/dev/sg0', resolution=(320, 320),
            vid=0x0402, pid=0x3922, device_index=0,
        )
        self.ctrl._display.devices.select(fake_device)

        statuses = []
        self.ctrl.on_status_update = lambda s: statuses.append(s)

        theme = ThemeInfo(
            name='TestTheme', path=theme_dir, theme_type=ThemeType.LOCAL
        )
        self.ctrl.select_theme(theme)

        self.assertIn('Theme: TestTheme', statuses)
