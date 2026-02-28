"""Tests for core/models.py – ThemeInfo, DeviceInfo, VideoState, resolution pipeline."""

import tempfile
import unittest
from pathlib import Path

import pytest

from trcc.core.models import (
    DeviceInfo,
    ThemeInfo,
    ThemeType,
    VideoState,
    fbl_to_resolution,
    parse_hex_color,
    pm_to_fbl,
)

# =============================================================================
# ThemeInfo
# =============================================================================

class TestThemeInfoFromDirectory(unittest.TestCase):
    """ThemeInfo.from_directory() filesystem scanning."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir)

    def _make_theme(self, name, files=('00.png',)):
        d = Path(self.tmpdir) / name
        d.mkdir()
        for f in files:
            (d / f).write_bytes(b'\x89PNG')
        return d

    def test_basic_theme(self):
        d = self._make_theme('001a', ['00.png'])
        info = ThemeInfo.from_directory(d)
        self.assertEqual(info.name, '001a')
        self.assertEqual(info.theme_type, ThemeType.LOCAL)
        self.assertIsNotNone(info.background_path)

    def test_animated_theme(self):
        d = self._make_theme('002a', ['00.png', 'Theme.zt'])
        info = ThemeInfo.from_directory(d)
        self.assertTrue(info.is_animated)
        self.assertIsNotNone(info.animation_path)

    def test_mask_only_theme(self):
        d = self._make_theme('mask', ['01.png'])
        info = ThemeInfo.from_directory(d)
        self.assertTrue(info.is_mask_only)
        self.assertIsNone(info.background_path)

    def test_resolution_passed_through(self):
        d = self._make_theme('003a', ['00.png'])
        info = ThemeInfo.from_directory(d, resolution=(480, 480))
        self.assertEqual(info.resolution, (480, 480))

    def test_thumbnail_fallback_to_background(self):
        """When Theme.png missing, thumbnail falls back to 00.png."""
        d = self._make_theme('004a', ['00.png'])
        info = ThemeInfo.from_directory(d)
        self.assertIsNotNone(info.thumbnail_path)
        self.assertEqual(info.thumbnail_path.name, '00.png')

    def test_with_config_dc(self):
        d = self._make_theme('005a', ['00.png', 'config1.dc'])
        info = ThemeInfo.from_directory(d)
        self.assertIsNotNone(info.config_path)


class TestThemeInfoFromVideo(unittest.TestCase):
    """ThemeInfo.from_video() cloud theme creation."""

    def test_basic(self):
        info = ThemeInfo.from_video(Path('/tmp/a_test.mp4'))
        self.assertEqual(info.name, 'a_test')
        self.assertEqual(info.theme_type, ThemeType.CLOUD)
        self.assertTrue(info.is_animated)

    def test_category_from_name(self):
        info = ThemeInfo.from_video(Path('/tmp/b_galaxy.mp4'))
        self.assertEqual(info.category, 'b')


# =============================================================================
# DeviceInfo
# =============================================================================

class TestDeviceInfo(unittest.TestCase):

    def test_resolution_str(self):
        d = DeviceInfo(name='LCD', path='/dev/sg0', resolution=(480, 480))
        self.assertEqual(d.resolution_str, '480x480')

    def test_defaults(self):
        d = DeviceInfo(name='LCD', path='/dev/sg0')
        self.assertEqual(d.brightness, 65)
        self.assertEqual(d.rotation, 0)
        self.assertTrue(d.connected)


# =============================================================================
# Resolution Pipeline (pm_to_fbl, fbl_to_resolution)
# =============================================================================

class TestPmToFbl(unittest.TestCase):
    """PM byte → FBL byte mapping (C# FormCZTVInit)."""

    def test_identity_for_unknown_pm(self):
        """Unknown PM values pass through as PM=FBL."""
        self.assertEqual(pm_to_fbl(36), 36)
        self.assertEqual(pm_to_fbl(72), 72)

    def test_known_overrides(self):
        """PM values with explicit FBL overrides."""
        self.assertEqual(pm_to_fbl(5), 50)
        self.assertEqual(pm_to_fbl(7), 64)
        self.assertEqual(pm_to_fbl(9), 224)
        self.assertEqual(pm_to_fbl(32), 100)
        self.assertEqual(pm_to_fbl(64), 114)
        self.assertEqual(pm_to_fbl(65), 192)

    def test_new_v212_overrides(self):
        """New PM→FBL entries from v2.1.2 audit."""
        self.assertEqual(pm_to_fbl(13), 224)   # 960x320
        self.assertEqual(pm_to_fbl(14), 64)    # 640x480
        self.assertEqual(pm_to_fbl(15), 224)   # 640x172
        self.assertEqual(pm_to_fbl(16), 224)   # 960x540
        self.assertEqual(pm_to_fbl(17), 224)   # 960x320
        self.assertEqual(pm_to_fbl(66), 192)   # 1920x462
        self.assertEqual(pm_to_fbl(68), 192)   # 1280x480
        self.assertEqual(pm_to_fbl(69), 192)   # 1920x440

    def test_pm_sub_compound_keys(self):
        """PM+SUB compound keys for special device configurations."""
        self.assertEqual(pm_to_fbl(1, sub=48), 114)  # 1600x720
        self.assertEqual(pm_to_fbl(1, sub=49), 192)  # 1920x462
        # Without sub, PM=1 → FBL=1 (identity)
        self.assertEqual(pm_to_fbl(1), 1)


class TestFblToResolution(unittest.TestCase):
    """FBL byte → (width, height) mapping."""

    def test_basic_fbl_table(self):
        """Core FBL entries from FBL_TO_RESOLUTION."""
        self.assertEqual(fbl_to_resolution(36), (240, 240))
        self.assertEqual(fbl_to_resolution(50), (320, 240))
        self.assertEqual(fbl_to_resolution(54), (360, 360))
        self.assertEqual(fbl_to_resolution(64), (640, 480))
        self.assertEqual(fbl_to_resolution(72), (480, 480))
        self.assertEqual(fbl_to_resolution(100), (320, 320))
        self.assertEqual(fbl_to_resolution(114), (1600, 720))
        self.assertEqual(fbl_to_resolution(128), (1280, 480))

    def test_unknown_fbl_defaults_320x320(self):
        self.assertEqual(fbl_to_resolution(999), (320, 320))

    def test_fbl_224_default_854x480(self):
        """FBL 224 without PM disambiguation → 854x480."""
        self.assertEqual(fbl_to_resolution(224), (854, 480))

    def test_fbl_224_disambiguation(self):
        """FBL 224 with PM byte → correct resolution."""
        self.assertEqual(fbl_to_resolution(224, pm=9), (854, 480))   # default
        self.assertEqual(fbl_to_resolution(224, pm=10), (960, 540))
        self.assertEqual(fbl_to_resolution(224, pm=11), (854, 480))  # default
        self.assertEqual(fbl_to_resolution(224, pm=12), (800, 480))

    def test_fbl_224_new_resolutions(self):
        """New FBL 224 entries from v2.1.2: 960x320 and 640x172."""
        self.assertEqual(fbl_to_resolution(224, pm=13), (960, 320))
        self.assertEqual(fbl_to_resolution(224, pm=15), (640, 172))
        self.assertEqual(fbl_to_resolution(224, pm=16), (960, 540))
        self.assertEqual(fbl_to_resolution(224, pm=17), (960, 320))

    def test_fbl_192_default_1920x462(self):
        """FBL 192 without PM disambiguation → 1920x462."""
        self.assertEqual(fbl_to_resolution(192), (1920, 462))
        self.assertEqual(fbl_to_resolution(192, pm=65), (1920, 462))

    def test_fbl_192_disambiguation(self):
        """New FBL 192 entries from v2.1.2: 1280x480 and 1920x440."""
        self.assertEqual(fbl_to_resolution(192, pm=68), (1280, 480))
        self.assertEqual(fbl_to_resolution(192, pm=69), (1920, 440))


class TestEndToEndResolutionPipeline(unittest.TestCase):
    """Full PM → pm_to_fbl → fbl_to_resolution pipeline per C# v2.1.2 reference."""

    def _resolve(self, pm: int, sub: int = 0) -> tuple[int, int]:
        fbl = pm_to_fbl(pm, sub)
        return fbl_to_resolution(fbl, pm)

    def test_pm5_320x240(self):
        self.assertEqual(self._resolve(5), (320, 240))

    def test_pm7_640x480(self):
        self.assertEqual(self._resolve(7), (640, 480))

    def test_pm9_854x480(self):
        self.assertEqual(self._resolve(9), (854, 480))

    def test_pm10_960x540(self):
        self.assertEqual(self._resolve(10), (960, 540))

    def test_pm12_800x480(self):
        self.assertEqual(self._resolve(12), (800, 480))

    def test_pm13_960x320(self):
        self.assertEqual(self._resolve(13), (960, 320))

    def test_pm14_640x480(self):
        self.assertEqual(self._resolve(14), (640, 480))

    def test_pm15_640x172(self):
        self.assertEqual(self._resolve(15), (640, 172))

    def test_pm16_960x540(self):
        self.assertEqual(self._resolve(16), (960, 540))

    def test_pm17_960x320(self):
        self.assertEqual(self._resolve(17), (960, 320))

    def test_pm32_320x320(self):
        self.assertEqual(self._resolve(32), (320, 320))

    def test_pm64_1600x720(self):
        self.assertEqual(self._resolve(64), (1600, 720))

    def test_pm65_1920x462(self):
        self.assertEqual(self._resolve(65), (1920, 462))

    def test_pm66_1920x462(self):
        self.assertEqual(self._resolve(66), (1920, 462))

    def test_pm68_1280x480(self):
        self.assertEqual(self._resolve(68), (1280, 480))

    def test_pm69_1920x440(self):
        self.assertEqual(self._resolve(69), (1920, 440))

    def test_pm1_sub48_1600x720(self):
        self.assertEqual(self._resolve(1, sub=48), (1600, 720))

    def test_pm1_sub49_1920x462(self):
        self.assertEqual(self._resolve(1, sub=49), (1920, 462))


# =============================================================================
# VideoState
# =============================================================================

class TestVideoState(unittest.TestCase):

    def test_progress_zero_frames(self):
        s = VideoState(total_frames=0)
        self.assertEqual(s.progress, 0.0)

    def test_progress_halfway(self):
        s = VideoState(current_frame=50, total_frames=100)
        self.assertAlmostEqual(s.progress, 50.0)

    def test_time_str(self):
        s = VideoState(current_frame=960, total_frames=1920, fps=16.0)
        self.assertEqual(s.current_time_str, '01:00')
        self.assertEqual(s.total_time_str, '02:00')

    def test_frame_interval(self):
        s = VideoState(fps=16.0)
        self.assertEqual(s.frame_interval_ms, 62)

    def test_frame_interval_zero_fps(self):
        s = VideoState(fps=0)
        self.assertEqual(s.frame_interval_ms, 62)

    def test_time_str_zero_fps(self):
        s = VideoState(fps=0)
        self.assertEqual(s.current_time_str, '00:00')


class TestVideoStateTotalTimeStr(unittest.TestCase):

    def test_zero_fps(self):
        vs = VideoState()
        vs.fps = 0
        self.assertEqual(vs.total_time_str, "00:00")


# =============================================================================
# parse_hex_color
# =============================================================================

class TestParseHexColor:
    """parse_hex_color() — shared hex color parser."""

    @pytest.mark.parametrize("input_hex,expected", [
        ("ff0000", (255, 0, 0)),
        ("#ff0000", (255, 0, 0)),
        ("00ff00", (0, 255, 0)),
        ("#00FF00", (0, 255, 0)),
        ("0000ff", (0, 0, 255)),
        ("000000", (0, 0, 0)),
        ("ffffff", (255, 255, 255)),
        ("#abcdef", (171, 205, 239)),
    ])
    def test_valid_colors(self, input_hex, expected):
        assert parse_hex_color(input_hex) == expected

    @pytest.mark.parametrize("invalid", [
        "", "fff", "fffffff", "gggggg", "#xyz", "12345",
        "#12345g", "not-a-color",
    ])
    def test_invalid_returns_none(self, invalid):
        assert parse_hex_color(invalid) is None


# =============================================================================
# ProtocolTraits
# =============================================================================


class TestProtocolTraits:
    """PROTOCOL_TRAITS registry — single source of truth for protocol behavior."""

    def test_all_protocols_have_traits(self):
        """Every known protocol has an entry in PROTOCOL_TRAITS."""
        from trcc.core.models import PROTOCOL_TRAITS
        for proto in ('scsi', 'hid', 'bulk', 'ly', 'led'):
            assert proto in PROTOCOL_TRAITS, f"Missing traits for {proto}"

    def test_scsi_traits(self):
        from trcc.core.models import PROTOCOL_TRAITS
        t = PROTOCOL_TRAITS['scsi']
        assert t.udev_subsystems == ('scsi_generic',)
        assert t.backend_key == 'sg_raw'
        assert t.fallback_backend is None
        assert t.requires_reboot is True
        assert t.supports_jpeg is False
        assert t.is_led is False

    def test_hid_traits(self):
        from trcc.core.models import PROTOCOL_TRAITS
        t = PROTOCOL_TRAITS['hid']
        assert t.udev_subsystems == ('hidraw', 'usb')
        assert t.backend_key == 'pyusb'
        assert t.fallback_backend == 'hidapi'
        assert t.requires_reboot is False

    def test_bulk_ly_support_jpeg(self):
        from trcc.core.models import PROTOCOL_TRAITS
        assert PROTOCOL_TRAITS['bulk'].supports_jpeg is True
        assert PROTOCOL_TRAITS['ly'].supports_jpeg is True

    def test_led_is_led(self):
        from trcc.core.models import PROTOCOL_TRAITS
        t = PROTOCOL_TRAITS['led']
        assert t.is_led is True
        assert t.supports_jpeg is False

    def test_only_scsi_requires_reboot(self):
        from trcc.core.models import PROTOCOL_TRAITS
        for name, t in PROTOCOL_TRAITS.items():
            if name == 'scsi':
                assert t.requires_reboot is True
            else:
                assert t.requires_reboot is False, f"{name} should not require reboot"

    def test_traits_are_frozen(self):
        from trcc.core.models import PROTOCOL_TRAITS
        t = PROTOCOL_TRAITS['scsi']
        with pytest.raises(AttributeError):
            t.requires_reboot = False  # type: ignore[misc]


if __name__ == '__main__':
    unittest.main()
