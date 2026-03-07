"""Tests for VideoFrameCache — lazy per-frame encoding (C#-matching)."""
from __future__ import annotations

from unittest.mock import MagicMock

from conftest import make_test_surface, surface_size

from trcc.core.models import HardwareMetrics
from trcc.services.video_cache import VideoFrameCache


def _make_frames(count: int = 5, w: int = 32, h: int = 32) -> list:
    """Create test native renderer surfaces (small for speed)."""
    return [make_test_surface(w, h, (i * 50, 0, 0)) for i in range(count)]


def _make_mask(w: int = 32, h: int = 32):
    """Create test RGBA mask surface."""
    return make_test_surface(w, h, (255, 255, 255, 128))


def _make_overlay_svc(w: int = 32, h: int = 32):
    """Create a mock OverlayService with render_text_only."""
    svc = MagicMock()
    svc.enabled = True
    svc.theme_mask = None
    svc.theme_mask_visible = True
    svc.theme_mask_position = (0, 0)
    svc._metrics = HardwareMetrics()
    text_surface = make_test_surface(w, h, (0, 0, 0, 0))
    svc.render_text_only.return_value = (text_surface, ('key', 1))
    return svc


class TestBuild:
    """Test full cache build at video load."""

    def test_build_creates_active_cache(self):
        frames = _make_frames(5, 32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        assert cache.active
        # Lazy encoding: get_encoded produces correct bytes on access
        data = cache.get_encoded(0)
        assert isinstance(data, bytes)
        # RGB565: 32*32*2 = 2048 bytes per frame
        assert len(data) == 2048

    def test_build_with_mask_composites(self):
        frames = _make_frames(3, 32, 32)
        mask = _make_mask(32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=mask, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        assert cache.active
        assert len(cache._masked_frames) == 3
        # Masked frames should differ from originals (mask composited)
        assert bytes(cache._masked_frames[0].constBits()) != bytes(frames[0].constBits())

    def test_build_no_mask_shares_references(self):
        frames = _make_frames(3, 32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        # Without mask, L2 should reference L1 frames directly
        for i in range(3):
            assert cache._masked_frames[i] is frames[i]

    def test_build_empty_frames_inactive(self):
        cache = VideoFrameCache()
        cache.build(
            frames=[], mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        assert not cache.active

    def test_build_with_overlay_text(self):
        frames = _make_frames(3, 32, 32)
        overlay_svc = _make_overlay_svc(32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=overlay_svc, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        assert cache.active
        overlay_svc.render_text_only.assert_called_once()


class TestAccess:
    """Test per-tick frame access."""

    def test_get_encoded_returns_bytes(self):
        frames = _make_frames(3, 32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        data = cache.get_encoded(0)
        assert isinstance(data, bytes)
        assert len(data) == 2048

    def test_get_encoded_out_of_range(self):
        cache = VideoFrameCache()
        assert cache.get_encoded(0) is None
        assert cache.get_encoded(-1) is None

    def test_get_preview_returns_surface(self):
        frames = _make_frames(3, 32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        preview = cache.get_preview(1)
        assert preview is not None
        assert surface_size(preview) == (32, 32)

    def test_get_preview_out_of_range(self):
        cache = VideoFrameCache()
        assert cache.get_preview(0) is None

    def test_cache_hit_same_frame(self):
        """Accessing same frame twice reuses cached encoding."""
        frames = _make_frames(3, 32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        data1 = cache.get_encoded(1)
        data2 = cache.get_encoded(1)
        assert data1 is data2  # Same object, not re-encoded

    def test_different_frames_different_data(self):
        """Different frame indices produce different encoded data."""
        frames = _make_frames(3, 32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        data0 = cache.get_encoded(0)
        data1 = cache.get_encoded(1)
        # Frames have different colors, so encodings should differ
        assert data0 != data1


class TestRebuild:
    """Test partial cache rebuilds."""

    def test_rebuild_from_brightness(self):
        frames = [make_test_surface(32, 32, (255, 255, 255)) for _ in range(3)]
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        original_encoded = cache.get_encoded(0)

        cache.rebuild_from_brightness(50)
        assert cache._brightness == 50
        # Next access should re-encode with new brightness
        assert cache.get_encoded(0) != original_encoded

    def test_brightness_100_keeps_encoding(self):
        """Full brightness produces same encoding as original build."""
        frames = [make_test_surface(32, 32, (200, 200, 200)) for _ in range(3)]
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        original_encoded = cache.get_encoded(0)

        # Rebuild at same brightness — encoding should not change
        cache.rebuild_from_brightness(100)
        assert cache.get_encoded(0) == original_encoded

    def test_brightness_50_changes_encoding(self):
        """50% brightness produces different encoding than 100%."""
        frames = [make_test_surface(32, 32, (200, 200, 200)) for _ in range(3)]
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        original_encoded = cache.get_encoded(0)

        cache.rebuild_from_brightness(50)
        assert cache.get_encoded(0) != original_encoded

    def test_rebuild_from_rotation(self):
        from trcc.services.image import ImageService
        r = ImageService._r()
        base = r.create_surface(32, 32, (0, 0, 0))
        red_quad = r.create_surface(16, 16, (255, 0, 0))
        base = r.composite(base, red_quad, (0, 0))
        frames = [r.copy_surface(base) for _ in range(3)]
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=None, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )
        original_encoded = cache.get_encoded(0)

        cache.rebuild_from_rotation(90)
        assert cache._rotation == 90
        assert cache.get_encoded(0) != original_encoded

    def test_rebuild_from_metrics(self):
        frames = _make_frames(3, 32, 32)
        overlay_svc = _make_overlay_svc(32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=overlay_svc, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )

        # Change text overlay for rebuild
        new_text = make_test_surface(32, 32, (255, 0, 0, 128))
        overlay_svc.render_text_only.return_value = (new_text, ('key', 2))

        original_encoded = cache.get_encoded(0)
        cache.rebuild_from_metrics(overlay_svc, HardwareMetrics())
        # New cache key should produce different encoding on next access
        assert cache.get_encoded(0) != original_encoded

    def test_rebuild_from_metrics_same_key_skips(self):
        """When text cache key hasn't changed, encoding stays the same."""
        frames = _make_frames(3, 32, 32)
        overlay_svc = _make_overlay_svc(32, 32)
        cache = VideoFrameCache()
        cache.build(
            frames=frames, mask=None, mask_position=(0, 0),
            overlay_svc=overlay_svc, metrics=HardwareMetrics(),
            brightness=100, rotation=0,
            protocol='scsi', resolution=(32, 32),
            fbl=None, use_jpeg=False,
        )

        # Same key returned — encoding should be identical
        original_encoded = cache.get_encoded(0)
        cache.rebuild_from_metrics(overlay_svc, HardwareMetrics())
        assert cache.get_encoded(0) == original_encoded


class TestInactiveCache:
    """Test inactive cache behavior."""

    def test_inactive_cache_returns_none(self):
        cache = VideoFrameCache()
        assert not cache.active
        assert cache.get_encoded(0) is None
        assert cache.get_preview(0) is None
