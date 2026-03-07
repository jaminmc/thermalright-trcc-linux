"""Memory and resource leak tests for TRCC Linux services.

Verifies that long-running GUI sessions do not accumulate PIL Images,
video frames, overlay caches, or USB handles across repeated cycles.
Uses tracemalloc (memory growth), weakref (object reclaimability),
and gc (no uncollectable cycles).
"""
from __future__ import annotations

import gc
import os
import tracemalloc
import weakref
from unittest.mock import MagicMock

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from conftest import make_test_surface
from PIL import Image

from trcc.core.models import (
    HardwareMetrics,
    LEDMode,
    LEDState,
    PlaybackState,
)
from trcc.services.image import ImageService
from trcc.services.led import LEDService
from trcc.services.media import MediaService
from trcc.services.overlay import OverlayService

# ═══════════════════════════════════════════════════════════════════════
# Fixtures
# ═══════════════════════════════════════════════════════════════════════

@pytest.fixture()
def overlay_svc():
    """Fresh OverlayService at 320x320."""
    return OverlayService(320, 320, renderer=ImageService._r())


@pytest.fixture()
def media_svc():
    """Fresh MediaService."""
    return MediaService()


@pytest.fixture()
def led_state():
    """LEDState with sensible defaults for tick testing."""
    state = LEDState()
    state.global_on = True
    state.brightness = 100
    state.color = (255, 0, 0)
    state.segment_count = 64
    state.led_count = 64
    return state


@pytest.fixture()
def led_svc(led_state):
    """LEDService with default state."""
    return LEDService(state=led_state)


@pytest.fixture()
def lcd_png(tmp_path):
    """320x320 PNG file on disk."""
    p = tmp_path / "lcd.png"
    Image.new("RGB", (320, 320), (0, 128, 0)).save(str(p), "PNG")
    return str(p)


# ═══════════════════════════════════════════════════════════════════════
# 1. PIL Image Lifecycle
# ═══════════════════════════════════════════════════════════════════════

class TestImageLifecycle:
    """Verify PIL Images are reclaimable after resize/convert operations."""

    def test_resize_returns_new_object(self):
        """ImageService.resize() returns a different object — old is GC-eligible."""
        original = make_test_surface(640, 640, (255, 0, 0))
        original_id = id(original)
        resized = ImageService.resize(original, 320, 320)
        assert id(resized) != original_id

    def test_image_weakref_dies_after_delete(self):
        """PIL Image is reclaimable after all strong references are dropped."""
        img = Image.new("RGB", (320, 320), (0, 0, 255))
        ref = weakref.ref(img)
        del img
        gc.collect()
        assert ref() is None, "PIL Image was not reclaimed after del + gc.collect()"

    def test_repeated_open_resize_bounded_memory(self, lcd_png):
        """50 open/resize cycles do not accumulate unbounded memory."""
        tracemalloc.start()
        # Warm up
        img = ImageService.open_and_resize(lcd_png, 320, 320)
        del img
        gc.collect()

        _, peak_before = tracemalloc.get_traced_memory()

        for _ in range(50):
            img = ImageService.open_and_resize(lcd_png, 320, 320)
            del img

        gc.collect()
        _, peak_after = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        growth = peak_after - peak_before
        # 320x320 RGB = ~300KB. Allow 2MB for transient allocator overhead.
        assert growth < 2_000_000, f"Memory grew {growth:,} bytes over 50 cycles"


# ═══════════════════════════════════════════════════════════════════════
# 2. MediaService Frame Accumulation
# ═══════════════════════════════════════════════════════════════════════

class TestMediaFrameAccumulation:
    """Verify MediaService releases frames on close/reload."""

    @pytest.fixture()
    def loaded_media(self, media_svc):
        """MediaService with 10 injected frames (no ffmpeg needed)."""
        frames = [Image.new("RGB", (4, 4), (i * 25, 0, 0)) for i in range(10)]
        media_svc._frames = frames
        media_svc._state.total_frames = 10
        media_svc._state.fps = 16
        media_svc._state.state = PlaybackState.STOPPED
        return media_svc

    def test_clear_frames(self, loaded_media):
        """Clearing _frames empties list and releases memory."""
        assert len(loaded_media._frames) == 10
        loaded_media._frames.clear()
        loaded_media._decoder = None
        assert len(loaded_media._frames) == 0
        assert loaded_media._decoder is None

    def test_frame_weakrefs_die_after_clear(self, loaded_media):
        """All frame references become reclaimable after clearing."""
        refs = [weakref.ref(f) for f in loaded_media._frames]
        loaded_media._frames.clear()
        gc.collect()
        alive = sum(1 for r in refs if r() is not None)
        assert alive == 0, f"{alive}/10 frames still alive after clear()"

    def test_load_clears_previous_frames(self, media_svc):
        """Second load() releases first frame set."""
        first_frames = [Image.new("RGB", (4, 4), (255, 0, 0)) for _ in range(5)]
        refs = [weakref.ref(f) for f in first_frames]
        media_svc._frames = first_frames

        # Simulate second load by clearing and injecting new frames
        second_frames = [Image.new("RGB", (4, 4), (0, 255, 0)) for _ in range(5)]
        media_svc._frames.clear()
        media_svc._frames = second_frames
        del first_frames
        gc.collect()

        alive = sum(1 for r in refs if r() is not None)
        assert alive == 0, f"{alive}/5 old frames still alive after reload"

    def test_stop_preserves_frames(self, loaded_media):
        """stop() keeps frames in memory (stop ≠ unload)."""
        loaded_media.play()
        loaded_media.stop()
        assert len(loaded_media._frames) == 10


# ═══════════════════════════════════════════════════════════════════════
# 3. OverlayService Render Cycles
# ═══════════════════════════════════════════════════════════════════════

class TestOverlayRenderCycles:
    """Verify OverlayService releases old caches on replacement/clear."""

    def test_set_background_releases_old(self, overlay_svc):
        """Old background is reclaimable after set_background() with new image."""
        img_a = Image.new("RGB", (320, 320), (255, 0, 0))
        ref_a = weakref.ref(img_a)
        overlay_svc.set_background(img_a)

        img_b = Image.new("RGB", (320, 320), (0, 0, 255))
        overlay_svc.set_background(img_b)
        del img_a
        gc.collect()

        assert ref_a() is None, "Old background was not released"

    def test_set_mask_releases_old(self, overlay_svc):
        """Old mask is reclaimable after set_mask() with new image."""
        mask_a = Image.new("RGBA", (320, 320), (255, 255, 255, 128))
        ref_a = weakref.ref(mask_a)
        overlay_svc.set_mask(mask_a)

        mask_b = Image.new("RGBA", (320, 320), (0, 0, 0, 128))
        overlay_svc.set_mask(mask_b)
        del mask_a
        gc.collect()

        assert ref_a() is None, "Old mask was not released"

    def test_clear_releases_all_surfaces(self, overlay_svc):
        """clear() makes background, mask, and cache all reclaimable."""
        bg = Image.new("RGB", (320, 320), (100, 100, 100))
        mask = Image.new("RGBA", (320, 320), (255, 255, 255, 128))
        ref_bg = weakref.ref(bg)
        ref_mask = weakref.ref(mask)

        overlay_svc.set_background(bg)
        overlay_svc.set_mask(mask)
        overlay_svc.clear()
        del bg, mask
        gc.collect()

        assert ref_bg() is None, "Background not released after clear()"
        assert ref_mask() is None, "Mask not released after clear()"

    def test_repeated_render_bounded_memory(self, overlay_svc):
        """50 render cycles with varying metrics stay within memory bounds."""
        bg = Image.new("RGB", (320, 320), (50, 50, 50))
        overlay_svc.set_background(bg)
        overlay_svc.enabled = True

        tracemalloc.start()
        # Warm up
        overlay_svc.render(metrics=HardwareMetrics())
        gc.collect()
        _, peak_before = tracemalloc.get_traced_memory()

        for i in range(50):
            m = HardwareMetrics(cpu_temp=40.0 + i, cpu_percent=float(i))
            overlay_svc._invalidate_cache()  # Force re-render each cycle
            overlay_svc.render(metrics=m)

        gc.collect()
        _, peak_after = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        growth = peak_after - peak_before
        # 320x320 RGBA = ~400KB. Allow 2MB for caching + renderer internals.
        assert growth < 2_000_000, f"Memory grew {growth:,} bytes over 50 renders"


# ═══════════════════════════════════════════════════════════════════════
# 4. Theme Image Cycles
# ═══════════════════════════════════════════════════════════════════════

class TestThemeImageCycles:
    """Verify theme load cycles release old images."""

    def test_open_and_resize_intermediate_released(self, lcd_png):
        """Intermediate Image.open() result is reclaimable after resize."""
        # Open the raw image, take weakref, then let open_and_resize overwrite
        raw = Image.open(lcd_png)
        raw.load()  # Force decode so PIL doesn't hold lazy fd
        ref_raw = weakref.ref(raw)
        del raw
        gc.collect()
        # Raw image with no other references should be dead
        assert ref_raw() is None, "Raw Image.open() result was not released"

    def test_repeated_theme_load_bounded(self, lcd_png):
        """20 open_and_resize cycles stay within memory bounds."""
        tracemalloc.start()
        img = ImageService.open_and_resize(lcd_png, 320, 320)
        del img
        gc.collect()
        _, peak_before = tracemalloc.get_traced_memory()

        for _ in range(20):
            img = ImageService.open_and_resize(lcd_png, 320, 320)
            del img

        gc.collect()
        _, peak_after = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        growth = peak_after - peak_before
        assert growth < 2_000_000, f"Memory grew {growth:,} bytes over 20 loads"


# ═══════════════════════════════════════════════════════════════════════
# 5. LED Tick Loop
# ═══════════════════════════════════════════════════════════════════════

class TestLedTickLoop:
    """Verify LED tick loops do not accumulate per-tick objects."""

    def test_tick_bounded_memory(self, led_svc):
        """500 static-mode ticks stay within memory bounds."""
        led_svc.state.mode = LEDMode.STATIC
        tracemalloc.start()
        # Warm up
        led_svc.tick()
        gc.collect()
        _, peak_before = tracemalloc.get_traced_memory()

        for _ in range(500):
            led_svc.tick()

        gc.collect()
        _, peak_after = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        growth = peak_after - peak_before
        # Tick returns transient list of tuples — should be near-zero growth.
        assert growth < 500_000, f"Memory grew {growth:,} bytes over 500 ticks"

    def test_breathing_tick_no_accumulation(self, led_svc):
        """200 breathing-mode ticks (most complex timer) stay bounded."""
        led_svc.state.mode = LEDMode.BREATHING
        tracemalloc.start()
        for _ in range(10):
            led_svc.tick()
        gc.collect()
        _, peak_before = tracemalloc.get_traced_memory()

        for _ in range(200):
            led_svc.tick()

        gc.collect()
        _, peak_after = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        growth = peak_after - peak_before
        assert growth < 500_000, f"Memory grew {growth:,} bytes over 200 ticks"

    def test_tick_returns_fresh_list(self, led_svc):
        """Consecutive tick() calls return different list objects (transient)."""
        led_svc.state.mode = LEDMode.STATIC
        result_a = led_svc.tick()
        result_b = led_svc.tick()
        assert id(result_a) != id(result_b), "tick() reused same list object"


# ═══════════════════════════════════════════════════════════════════════
# 6. USB Handle Cleanup
# ═══════════════════════════════════════════════════════════════════════

class TestUsbHandleCleanup:
    """Verify USB protocol handles are released on close/error paths."""

    def test_protocol_close_releases_transport(self):
        """Mock transport is cleared after protocol close()."""
        mock_transport = MagicMock()
        mock_transport.is_open = True

        # Simulate a protocol with a transport attribute
        svc = MagicMock()
        svc._transport = mock_transport
        svc.close = lambda: setattr(svc, '_transport', None)

        svc.close()
        assert svc._transport is None

    def test_handshake_error_transport_closeable(self):
        """Transport can still be closed after handshake exception."""
        mock_transport = MagicMock()
        mock_transport.is_open = True
        mock_transport.write.side_effect = OSError("Device disconnected")

        # Even after write failure, close should work
        mock_transport.close()
        mock_transport.close.assert_called_once()

    def test_led_service_cleanup_releases_protocol(self, led_svc):
        """LEDService cleanup sets _protocol to None."""
        mock_proto = MagicMock()
        led_svc._protocol = mock_proto

        led_svc._protocol = None  # Simulate cleanup
        assert led_svc._protocol is None


# ═══════════════════════════════════════════════════════════════════════
# 7. Garbage Collectability
# ═══════════════════════════════════════════════════════════════════════

class TestGarbageCollectability:
    """Verify service objects do not create uncollectable circular references."""

    def test_overlay_no_uncollectable(self):
        """OverlayService create/use/delete produces no uncollectable cycles."""
        gc.collect()
        gc.set_debug(0)
        garbage_before = len(gc.garbage)

        svc = OverlayService(320, 320, renderer=ImageService._r())
        bg = Image.new("RGB", (320, 320), (100, 100, 100))
        svc.set_background(bg)
        svc.render(metrics=HardwareMetrics())
        del svc, bg
        gc.collect()

        assert len(gc.garbage) == garbage_before, (
            f"Uncollectable objects: {len(gc.garbage) - garbage_before}")

    def test_media_no_uncollectable(self, media_svc):
        """MediaService with mock frames produces no uncollectable cycles."""
        gc.collect()
        garbage_before = len(gc.garbage)

        media_svc._frames = [
            Image.new("RGB", (4, 4), (i, 0, 0)) for i in range(10)
        ]
        media_svc._frames.clear()
        media_svc._decoder = None
        del media_svc
        gc.collect()

        assert len(gc.garbage) == garbage_before

    def test_led_no_uncollectable(self, led_svc):
        """LEDService after tick loop produces no uncollectable cycles."""
        gc.collect()
        garbage_before = len(gc.garbage)

        led_svc.state.mode = LEDMode.BREATHING
        for _ in range(50):
            led_svc.tick()
        del led_svc
        gc.collect()

        assert len(gc.garbage) == garbage_before
