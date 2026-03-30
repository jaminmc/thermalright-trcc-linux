"""Tests for core/models.py – ThemeInfo, DeviceInfo, VideoState, resolution pipeline."""

import tempfile
import unittest
from pathlib import Path

import pytest

from trcc.core.models import (
    FBL_PROFILES,
    DeviceInfo,
    DeviceProfile,
    ThemeInfo,
    ThemeType,
    VideoState,
    fbl_to_resolution,
    get_profile,
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

    def test_button_image_default(self):
        d = DeviceInfo(name='LCD', path='/dev/sg0')
        self.assertEqual(d.button_image, 'A1CZTV')

    def test_button_image_custom(self):
        d = DeviceInfo(name='LCD', path='/dev/sg0',
                       button_image='A1FROZEN WARFRAME PRO')
        self.assertEqual(d.button_image, 'A1FROZEN WARFRAME PRO')


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

    def test_every_fbl_resolution(self):
        """Every FBL in FBL_PROFILES resolves to the correct resolution."""
        expected = {
            36:  (240, 240),
            37:  (240, 240),
            50:  (320, 240),
            51:  (320, 240),
            53:  (320, 240),
            54:  (360, 360),
            58:  (320, 240),
            64:  (640, 480),
            72:  (480, 480),
            100: (320, 320),
            101: (320, 320),
            102: (320, 320),
            114: (1600, 720),
            128: (1280, 480),
            129: (480, 480),
            192: (1920, 462),
            224: (854, 480),
        }
        for fbl, res in expected.items():
            with self.subTest(fbl=fbl):
                self.assertEqual(fbl_to_resolution(fbl), res)

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
# DeviceProfile — encoding properties per FBL
# =============================================================================


class TestDeviceProfileCompleteness(unittest.TestCase):
    """Every FBL in FBL_PROFILES has correct encoding properties."""

    def test_all_fbls_accounted_for(self):
        """FBL_PROFILES contains exactly the expected 17 device entries."""
        expected_fbls = {36, 37, 50, 51, 53, 54, 58, 64, 72,
                         100, 101, 102, 114, 128, 129, 192, 224}
        self.assertEqual(set(FBL_PROFILES.keys()), expected_fbls)

    def test_jpeg_fbls(self):
        """Only JPEG FBLs are flagged as JPEG."""
        jpeg_fbls = {fbl for fbl, p in FBL_PROFILES.items() if p.jpeg}
        self.assertEqual(jpeg_fbls, {54, 114, 128, 192, 224})

    def test_big_endian_fbls(self):
        """Only big-endian FBLs are flagged as big-endian."""
        be_fbls = {fbl for fbl, p in FBL_PROFILES.items() if p.big_endian}
        self.assertEqual(be_fbls, {100, 101, 102})

    def test_rotate_fbls(self):
        """Only portrait/landscape-rotated FBLs are flagged."""
        rot_fbls = {fbl for fbl, p in FBL_PROFILES.items() if p.rotate}
        self.assertEqual(rot_fbls, {50, 51, 53, 58, 64, 114, 128, 192, 224})

    def test_byte_order_property(self):
        """byte_order returns '>' for big-endian, '<' for little-endian."""
        for fbl, profile in FBL_PROFILES.items():
            with self.subTest(fbl=fbl):
                expected = '>' if profile.big_endian else '<'
                self.assertEqual(profile.byte_order, expected)

    def test_resolution_property(self):
        """resolution property returns (width, height) tuple."""
        for fbl, profile in FBL_PROFILES.items():
            with self.subTest(fbl=fbl):
                self.assertEqual(profile.resolution, (profile.width, profile.height))

    def test_get_profile_returns_profile_for_every_fbl(self):
        """get_profile() returns a DeviceProfile for every known FBL."""
        for fbl in FBL_PROFILES:
            with self.subTest(fbl=fbl):
                p = get_profile(fbl)
                self.assertIsInstance(p, DeviceProfile)
                self.assertEqual(p.resolution, FBL_PROFILES[fbl].resolution)

    def test_get_profile_unknown_fbl_defaults_320x320(self):
        """Unknown FBL defaults to 320x320 big-endian."""
        p = get_profile(999)
        self.assertEqual(p.resolution, (320, 320))
        self.assertTrue(p.big_endian)
        self.assertFalse(p.jpeg)


class TestDeviceProfilePerFbl(unittest.TestCase):
    """Per-FBL encoding property tests — one test per device type."""

    def test_fbl_36_240x240_rgb565_le(self):
        p = get_profile(36)
        self.assertEqual(p.resolution, (240, 240))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)
        self.assertFalse(p.rotate)

    def test_fbl_37_240x240_rgb565_le(self):
        """FBL 37 is an alias for 36 — same device, same encoding."""
        p = get_profile(37)
        self.assertEqual(p.resolution, (240, 240))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)

    def test_fbl_50_320x240_rgb565_le_rotated(self):
        p = get_profile(50)
        self.assertEqual(p.resolution, (320, 240))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)
        self.assertTrue(p.rotate)

    def test_fbl_51_320x240_rgb565_le(self):
        """FBL 51 HID Type 2 — little-endian RGB565 (SPIMode=2 only for SPI mode 1)."""
        p = get_profile(51)
        self.assertEqual(p.resolution, (320, 240))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)
        self.assertTrue(p.rotate)

    def test_fbl_53_320x240_rgb565_le(self):
        """FBL 53 HID Type 2 — little-endian RGB565."""
        p = get_profile(53)
        self.assertEqual(p.resolution, (320, 240))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)
        self.assertTrue(p.rotate)

    def test_fbl_54_360x360_jpeg(self):
        p = get_profile(54)
        self.assertEqual(p.resolution, (360, 360))
        self.assertTrue(p.jpeg)
        self.assertFalse(p.rotate)

    def test_fbl_58_320x240_rgb565_le_rotated(self):
        p = get_profile(58)
        self.assertEqual(p.resolution, (320, 240))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)
        self.assertTrue(p.rotate)

    def test_fbl_64_640x480_rgb565_le_rotated(self):
        p = get_profile(64)
        self.assertEqual(p.resolution, (640, 480))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)
        self.assertTrue(p.rotate)

    def test_fbl_72_480x480_rgb565_le(self):
        p = get_profile(72)
        self.assertEqual(p.resolution, (480, 480))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)
        self.assertFalse(p.rotate)

    def test_fbl_100_320x320_rgb565_be(self):
        p = get_profile(100)
        self.assertEqual(p.resolution, (320, 320))
        self.assertFalse(p.jpeg)
        self.assertTrue(p.big_endian)
        self.assertFalse(p.rotate)

    def test_fbl_101_320x320_rgb565_be(self):
        """FBL 101 is an alias for 100."""
        p = get_profile(101)
        self.assertEqual(p.resolution, (320, 320))
        self.assertTrue(p.big_endian)

    def test_fbl_102_320x320_rgb565_be(self):
        """FBL 102 is an alias for 100."""
        p = get_profile(102)
        self.assertEqual(p.resolution, (320, 320))
        self.assertTrue(p.big_endian)

    def test_fbl_114_1600x720_jpeg_rotated(self):
        p = get_profile(114)
        self.assertEqual(p.resolution, (1600, 720))
        self.assertTrue(p.jpeg)
        self.assertTrue(p.rotate)

    def test_fbl_128_1280x480_jpeg_rotated(self):
        p = get_profile(128)
        self.assertEqual(p.resolution, (1280, 480))
        self.assertTrue(p.jpeg)
        self.assertTrue(p.rotate)

    def test_fbl_129_480x480_rgb565_le(self):
        """FBL 129 is an alias for 72."""
        p = get_profile(129)
        self.assertEqual(p.resolution, (480, 480))
        self.assertFalse(p.jpeg)
        self.assertFalse(p.big_endian)

    def test_fbl_192_1920x462_jpeg_rotated(self):
        p = get_profile(192)
        self.assertEqual(p.resolution, (1920, 462))
        self.assertTrue(p.jpeg)
        self.assertTrue(p.rotate)

    def test_fbl_224_854x480_jpeg_rotated(self):
        p = get_profile(224)
        self.assertEqual(p.resolution, (854, 480))
        self.assertTrue(p.jpeg)
        self.assertTrue(p.rotate)


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


class TestGetButtonImage:
    """get_button_image() — PM+SUB → button image name (#69)."""

    def test_stream_vision_pm7_sub1(self):
        """PM=7, SUB=1 → Stream Vision (not Frozen Warframe Pro)."""
        from trcc.core.models import get_button_image
        assert get_button_image(7, 1) == 'A1Stream Vision'

    def test_fbl64_sub0_is_frozen_warframe_pro(self):
        """FBL=64 with sub=0 → Frozen Warframe Pro (the old buggy lookup)."""
        from trcc.core.models import get_button_image
        assert get_button_image(64, 0) == 'A1FROZEN WARFRAME PRO'

    def test_pm7_sub1_differs_from_fbl64(self):
        """PM=7/SUB=1 and FBL=64/SUB=0 must resolve differently (#69)."""
        from trcc.core.models import get_button_image
        assert get_button_image(7, 1) != get_button_image(64, 0)

    def test_pm32_sub1_frozen_warframe_pro(self):
        from trcc.core.models import get_button_image
        assert get_button_image(32, 1) == 'A1FROZEN WARFRAME PRO'

    def test_unknown_pm_returns_none(self):
        from trcc.core.models import get_button_image
        assert get_button_image(255) is None


# =============================================================================
# Overlay config builders (parse_metric_spec, build_overlay_config)
# =============================================================================


class TestParseMetricSpec:
    """Tests for parse_metric_spec() — CLI metric spec → overlay element."""

    def test_basic_spec(self):
        from trcc.core.models import parse_metric_spec
        key, elem = parse_metric_spec('gpu_temp:10,20', 0)
        assert key == 'cli_elem_0'
        assert elem['x'] == 10
        assert elem['y'] == 20
        assert elem['metric'] == 'gpu_temp'
        assert elem['enabled'] is True
        assert elem['color'] == '#ffffff'
        assert elem['font']['size'] == 14

    def test_with_color_override(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('cpu_percent:50,100:ff0000', 1)
        assert elem['color'] == '#ff0000'
        assert elem['font']['size'] == 14

    def test_with_color_and_size_override(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('time:150,10:ffffff:24', 2)
        assert elem['color'] == '#ffffff'
        assert elem['font']['size'] == 24
        assert elem['metric'] == 'time'

    def test_custom_defaults(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec(
            'gpu_usage:5,5', 0,
            default_color='00ff00', default_size=20,
            default_font='Arial', default_style='bold')
        assert elem['color'] == '#00ff00'
        assert elem['font']['size'] == 20
        assert elem['font']['name'] == 'Arial'
        assert elem['font']['style'] == 'bold'

    def test_time_format_field(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('time:10,10', 0)
        assert 'time_format' in elem

    def test_date_format_field(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('date:10,10', 0)
        assert 'date_format' in elem

    def test_temp_metric_has_temp_unit(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('cpu_temp:10,10', 0)
        assert 'temp_unit' in elem

    def test_invalid_key_raises(self):
        from trcc.core.models import parse_metric_spec
        with pytest.raises(ValueError, match="Unknown metric key"):
            parse_metric_spec('not_a_metric:10,10', 0)

    def test_missing_coords_raises(self):
        from trcc.core.models import parse_metric_spec
        with pytest.raises(ValueError, match="Invalid"):
            parse_metric_spec('gpu_temp', 0)

    def test_bad_coords_raises(self):
        from trcc.core.models import parse_metric_spec
        with pytest.raises(ValueError, match="Invalid coordinates"):
            parse_metric_spec('gpu_temp:abc,def', 0)

    def test_bad_size_raises(self):
        from trcc.core.models import parse_metric_spec
        with pytest.raises(ValueError, match="Invalid size"):
            parse_metric_spec('gpu_temp:10,20:ff0000:notanint', 0)

    def test_color_with_hash_stripped(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('gpu_temp:10,20:#aabbcc', 0)
        assert elem['color'] == '#aabbcc'

    def test_empty_color_uses_default(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('gpu_temp:10,20::18', 0)
        assert elem['color'] == '#ffffff'
        assert elem['font']['size'] == 18

    def test_per_metric_font_override(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('gpu_temp:10,20:ff0000:18:Arial:bold', 0)
        assert elem['font']['name'] == 'Arial'
        assert elem['font']['style'] == 'bold'
        assert elem['font']['size'] == 18
        assert elem['color'] == '#ff0000'

    def test_per_metric_font_without_style(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('cpu_temp:10,20::16:Courier', 0)
        assert elem['font']['name'] == 'Courier'
        assert elem['font']['style'] == 'regular'
        assert elem['font']['size'] == 16

    def test_per_metric_font_uses_global_when_empty(self):
        from trcc.core.models import parse_metric_spec
        _, elem = parse_metric_spec('gpu_temp:10,20', 0,
                                     default_font='Mono', default_style='bold')
        assert elem['font']['name'] == 'Mono'
        assert elem['font']['style'] == 'bold'


class TestBuildOverlayConfig:
    """Tests for build_overlay_config() — multiple specs → config dict."""

    def test_single_metric(self):
        from trcc.core.models import build_overlay_config
        config = build_overlay_config(['gpu_temp:10,20'])
        assert len(config) == 1
        assert 'cli_elem_0' in config

    def test_multiple_metrics(self):
        from trcc.core.models import build_overlay_config
        config = build_overlay_config([
            'gpu_temp:10,20',
            'cpu_percent:10,50',
            'time:150,10',
        ])
        assert len(config) == 3

    def test_global_defaults_applied(self):
        from trcc.core.models import build_overlay_config
        config = build_overlay_config(
            ['gpu_temp:10,20'],
            default_color='00ff00',
            default_font_size=20,
            default_font='Arial',
            default_style='bold',
        )
        elem = config['cli_elem_0']
        assert elem['color'] == '#00ff00'
        assert elem['font']['size'] == 20
        assert elem['font']['name'] == 'Arial'
        assert elem['font']['style'] == 'bold'

    def test_format_overrides(self):
        from trcc.core.models import build_overlay_config
        config = build_overlay_config(
            ['time:10,10', 'date:10,30', 'cpu_temp:10,50'],
            time_format=1, date_format=2, temp_unit=1,
        )
        assert config['cli_elem_0']['time_format'] == 1
        assert config['cli_elem_1']['date_format'] == 2
        assert config['cli_elem_2']['temp_unit'] == 1

    def test_invalid_metric_raises(self):
        from trcc.core.models import build_overlay_config
        with pytest.raises(ValueError, match="Unknown metric key"):
            build_overlay_config(['bogus:10,10'])

    def test_empty_list(self):
        from trcc.core.models import build_overlay_config
        config = build_overlay_config([])
        assert config == {}


class TestValidOverlayKeys:
    """Tests for VALID_OVERLAY_KEYS completeness."""

    def test_contains_hardware_metrics(self):
        from trcc.core.models import HARDWARE_METRICS, VALID_OVERLAY_KEYS
        for metric_name in HARDWARE_METRICS.values():
            assert metric_name in VALID_OVERLAY_KEYS

    def test_contains_time_date_weekday(self):
        from trcc.core.models import VALID_OVERLAY_KEYS
        assert 'time' in VALID_OVERLAY_KEYS
        assert 'date' in VALID_OVERLAY_KEYS
        assert 'weekday' in VALID_OVERLAY_KEYS

    def test_is_frozenset(self):
        from trcc.core.models import VALID_OVERLAY_KEYS
        assert isinstance(VALID_OVERLAY_KEYS, frozenset)


if __name__ == '__main__':
    unittest.main()
