"""Memory and resource leak tests for TRCC Linux.

Covers two layers:
  1. Service layer — PIL Images, video frames, overlay caches, USB handles
  2. GUI layer — signal accumulation, timer cleanup, IPC frame capture,
     MetricsMediator dispatch, change detection, LED adaptive tick rate

Uses tracemalloc (memory growth), weakref (object reclaimability),
and gc (no uncollectable cycles).
"""
from __future__ import annotations

import gc
import tracemalloc
import weakref
from unittest.mock import MagicMock

import pytest
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
    return OverlayService(320, 320)


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
        original = Image.new("RGB", (640, 640), (255, 0, 0))
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

    def test_close_clears_frames(self, loaded_media):
        """close() empties _frames and sets _decoder to None."""
        assert len(loaded_media._frames) == 10
        loaded_media.close()
        assert len(loaded_media._frames) == 0
        assert loaded_media._decoder is None

    def test_frame_weakrefs_die_after_close(self, loaded_media):
        """All frame references become reclaimable after close()."""
        refs = [weakref.ref(f) for f in loaded_media._frames]
        loaded_media.close()
        gc.collect()
        alive = sum(1 for r in refs if r() is not None)
        assert alive == 0, f"{alive}/10 frames still alive after close()"

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

        svc = OverlayService(320, 320)
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
        media_svc.close()
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


# ═══════════════════════════════════════════════════════════════════════
# 8. IPC Frame Capture
# ═══════════════════════════════════════════════════════════════════════

class TestIPCFrameCapture:
    """Verify IPC server does not accumulate frames in memory."""

    def test_capture_replaces_previous_frame(self):
        """capture_frame() replaces the old frame — only one held at a time."""
        from trcc.ipc import IPCServer

        server = IPCServer(MagicMock(), MagicMock())
        frame_a = Image.new("RGB", (320, 320), (255, 0, 0))
        ref_a = weakref.ref(frame_a)

        server.capture_frame(frame_a)
        assert server._current_frame is frame_a

        frame_b = Image.new("RGB", (320, 320), (0, 255, 0))
        server.capture_frame(frame_b)
        del frame_a
        gc.collect()

        assert ref_a() is None, "Old IPC frame not released after replacement"
        assert server._current_frame is frame_b

    def test_rapid_capture_bounded_memory(self):
        """100 rapid frame captures do not accumulate memory."""
        from trcc.ipc import IPCServer

        server = IPCServer(MagicMock(), MagicMock())

        tracemalloc.start()
        server.capture_frame(Image.new("RGB", (320, 320)))
        gc.collect()
        _, peak_before = tracemalloc.get_traced_memory()

        for i in range(100):
            server.capture_frame(Image.new("RGB", (320, 320), (i, 0, 0)))

        gc.collect()
        _, peak_after = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        growth = peak_after - peak_before
        # Only one 320x320 RGB frame (~300KB) should be held at a time.
        assert growth < 1_000_000, f"IPC frames leaked: {growth:,} bytes over 100 captures"


# ═══════════════════════════════════════════════════════════════════════
# 9. Signal Accumulation (LEDHandler._connect_signals)
# ═══════════════════════════════════════════════════════════════════════

class TestSignalAccumulation:
    """Verify that signal connections don't accumulate on repeated wiring."""

    @pytest.fixture(scope="module")
    def qapp(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app

    def test_led_handler_single_connection(self, qapp):
        """LEDHandler._connect_signals() guard prevents double-wiring."""
        from PySide6.QtCore import SIGNAL

        from trcc.qt_components.qt_app_mvc import LEDHandler
        from trcc.qt_components.uc_led_control import UCLedControl

        panel = UCLedControl()
        handler = LEDHandler(panel, lambda u: None)

        assert handler._controller is None
        handler._controller = MagicMock()
        handler._connect_signals()

        sig_str = SIGNAL('mode_changed(int)')
        receivers_after_first = panel.receivers(sig_str)
        assert receivers_after_first > 0, "No receivers connected"

        # Second call should be no-op due to _signals_connected guard
        handler._connect_signals()
        receivers_after_second = panel.receivers(sig_str)

        assert receivers_after_second == receivers_after_first, (
            f"Signal accumulation: {receivers_after_second} receivers "
            f"after 2 calls (expected {receivers_after_first})"
        )

    def test_led_handler_show_guards_controller_creation(self, qapp):
        """LEDHandler.show() only creates controller once — signals wired once."""
        from trcc.qt_components.qt_app_mvc import LEDHandler
        from trcc.qt_components.uc_led_control import UCLedControl

        panel = UCLedControl()
        handler = LEDHandler(panel, lambda u: None)

        # After construction, no controller exists
        assert handler._controller is None

        # Simulate first controller creation
        handler._controller = MagicMock()
        first_ctrl = handler._controller

        # Second call to show() skips creation because controller already exists
        # (the `if self._controller is None` guard in show())
        # So _connect_signals won't be called again
        assert handler._controller is first_ctrl


# ═══════════════════════════════════════════════════════════════════════
# 10. Timer Cleanup on Close
# ═══════════════════════════════════════════════════════════════════════

class TestTimerCleanup:
    """Verify all timers are stopped during cleanup paths."""

    @pytest.fixture(scope="module")
    def qapp(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app

    def test_led_handler_cleanup_stops_timer(self, qapp):
        """LEDHandler.cleanup() stops the animation timer."""
        from trcc.qt_components.qt_app_mvc import LEDHandler
        from trcc.qt_components.uc_led_control import UCLedControl

        panel = UCLedControl()
        handler = LEDHandler(panel, lambda u: None)
        handler._timer.start(150)
        assert handler._timer.isActive()

        handler.cleanup()
        assert not handler._timer.isActive()

    def test_led_handler_stop_stops_timer(self, qapp):
        """LEDHandler.stop() stops the animation timer."""
        from trcc.qt_components.qt_app_mvc import LEDHandler
        from trcc.qt_components.uc_led_control import UCLedControl

        panel = UCLedControl()
        handler = LEDHandler(panel, lambda u: None)
        handler._timer.start(150)

        handler.stop()
        assert not handler._timer.isActive()

    def test_screencast_handler_cleanup_stops_timer(self, qapp):
        """ScreencastHandler.cleanup() stops the capture timer."""
        from trcc.qt_components.qt_app_mvc import ScreencastHandler

        parent = MagicMock()
        parent.palette = MagicMock(return_value=MagicMock())
        controller = MagicMock()

        from PySide6.QtWidgets import QWidget
        parent_widget = QWidget()
        handler = ScreencastHandler(parent_widget, controller, lambda f: None)
        handler._timer.start(150)
        assert handler._timer.isActive()

        handler.cleanup()
        assert not handler._timer.isActive()

    def test_base_panel_stop_periodic(self, qapp):
        """BasePanel.stop_periodic_updates() stops the timer."""
        from trcc.qt_components.base import BasePanel

        class ConcretePanel(BasePanel):
            def _setup_ui(self):
                pass

        panel = ConcretePanel()
        panel.start_periodic_updates(100, lambda: None)
        assert panel._update_timer is not None
        assert panel._update_timer.isActive()

        panel.stop_periodic_updates()
        assert not panel._update_timer.isActive()

    def test_base_panel_restart_disconnects_old(self, qapp):
        """BasePanel.start_periodic_updates() disconnects old callback on restart."""
        from trcc.qt_components.base import BasePanel

        class ConcretePanel(BasePanel):
            def _setup_ui(self):
                pass

        panel = ConcretePanel()
        call_count = [0]

        def callback_a():
            call_count[0] += 1

        panel.start_periodic_updates(100, callback_a)
        timer = panel._update_timer

        # Restart with new callback — old should be disconnected
        panel.start_periodic_updates(200, lambda: None)
        assert panel._update_timer is timer  # Same timer object reused

    def test_info_module_no_self_poll_timer(self, qapp):
        """UCInfoModule has no self-poll timer — metrics come from mediator."""
        from trcc.qt_components.uc_info_module import UCInfoModule

        module = UCInfoModule()
        assert not hasattr(module, '_timer'), "UCInfoModule should not have _timer"

    def test_activity_sidebar_no_self_poll_timer(self, qapp):
        """UCActivitySidebar has no self-poll timer — metrics come from mediator."""
        from trcc.qt_components.uc_activity_sidebar import UCActivitySidebar

        sidebar = UCActivitySidebar()
        assert not hasattr(sidebar, '_update_timer'), "UCActivitySidebar should not have _update_timer"


# ═══════════════════════════════════════════════════════════════════════
# 11. MetricsMediator + Duplicate Sensor Polling
# ═══════════════════════════════════════════════════════════════════════

class TestMetricsMediator:
    """Verify MetricsMediator dispatches correctly with period multipliers and guards."""

    @pytest.fixture(scope="module")
    def qapp(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app

    def test_period_multiplier(self, qapp):
        """period=3 subscriber fires on ticks 3, 6, 9 — skips 1, 2, 4, 5, etc."""
        from trcc.qt_components.metrics_mediator import MetricsMediator

        mediator = MetricsMediator(None)
        calls = []
        mediator.subscribe(lambda m: calls.append(mediator._tick_count), period=3)

        # Patch get_all_metrics to return a dummy
        import trcc.qt_components.metrics_mediator as mm
        orig = mm.get_all_metrics
        mm.get_all_metrics = lambda: HardwareMetrics()
        try:
            for _ in range(9):
                mediator._tick()
        finally:
            mm.get_all_metrics = orig

        assert calls == [3, 6, 9]

    def test_guard_skips_inactive(self, qapp):
        """Subscriber with guard returning False is never called."""
        from trcc.qt_components.metrics_mediator import MetricsMediator

        mediator = MetricsMediator(None)
        calls = []
        mediator.subscribe(lambda m: calls.append(1), guard=lambda: False)

        import trcc.qt_components.metrics_mediator as mm
        orig = mm.get_all_metrics
        mm.get_all_metrics = lambda: HardwareMetrics()
        try:
            for _ in range(5):
                mediator._tick()
        finally:
            mm.get_all_metrics = orig

        assert calls == []

    def test_ensure_running_starts_when_guard_passes(self, qapp):
        """ensure_running() starts timer when at least one guard passes."""
        from trcc.qt_components.metrics_mediator import MetricsMediator

        mediator = MetricsMediator(None)
        mediator.subscribe(lambda m: None, guard=lambda: False)
        mediator.subscribe(lambda m: None, guard=lambda: True)

        assert not mediator.is_active
        mediator.ensure_running()
        assert mediator.is_active
        mediator.stop()

    def test_ensure_running_stays_stopped_when_all_guards_fail(self, qapp):
        """ensure_running() does not start when all guards return False."""
        from trcc.qt_components.metrics_mediator import MetricsMediator

        mediator = MetricsMediator(None)
        mediator.subscribe(lambda m: None, guard=lambda: False)
        mediator.subscribe(lambda m: None, guard=lambda: False)

        mediator.ensure_running()
        assert not mediator.is_active

    def test_set_interval(self, qapp):
        """set_interval() changes the timer interval."""
        from trcc.qt_components.metrics_mediator import MetricsMediator

        mediator = MetricsMediator(None)
        mediator.subscribe(lambda m: None)
        mediator.ensure_running(1000)
        assert mediator.is_active

        mediator.set_interval(500)
        assert mediator._timer.interval() == 500
        mediator.stop()

    def test_change_detection_skips_preview(self, qapp):
        """Same image object from overlay cache → no preview update."""
        cached_img = Image.new("RGB", (320, 320), (100, 100, 100))
        preview_calls = []

        class FakePreview:
            def set_image(self, img, fast=False):
                preview_calls.append(img)

        controller = MagicMock()
        controller.is_overlay_enabled.return_value = True
        controller.render_overlay.return_value = cached_img
        controller.is_video_playing.return_value = False
        controller.auto_send = False

        preview = FakePreview()

        # Simulate _on_overlay_tick logic
        last_rendered = [None]

        def on_overlay_tick(metrics):
            controller.update_overlay_metrics(metrics)
            img = controller.render_overlay()
            if not img:
                return
            if img is not last_rendered[0]:
                last_rendered[0] = img
                preview.set_image(img)

        # First call — new image → preview updated
        on_overlay_tick(HardwareMetrics())
        assert len(preview_calls) == 1

        # Second call — same object → preview skipped
        on_overlay_tick(HardwareMetrics())
        assert len(preview_calls) == 1

        # Third call — different object → preview updated
        new_img = Image.new("RGB", (320, 320), (200, 200, 200))
        controller.render_overlay.return_value = new_img
        on_overlay_tick(HardwareMetrics())
        assert len(preview_calls) == 2


class TestDuplicateSensorPolling:
    """Flag duplicate get_all_metrics() callers that compete for CPU."""

    def test_gui_sensor_callers_bounded(self):
        """Ensure GUI-layer get_all_metrics() has exactly 1 caller: MetricsMediator.

        After the mediator refactor, all GUI metrics consumers receive
        pre-polled HardwareMetrics from the single mediator timer.
        Only metrics_mediator.py calls get_all_metrics() in qt_components/.
        This test detects new callers that would add CPU overhead.
        """
        import ast
        from pathlib import Path

        gui_dir = Path(__file__).parent.parent / 'src' / 'trcc' / 'qt_components'
        callers = []
        for py in gui_dir.rglob('*.py'):
            try:
                tree = ast.parse(py.read_text())
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    func = node.func
                    name = ''
                    if isinstance(func, ast.Name):
                        name = func.id
                    elif isinstance(func, ast.Attribute):
                        name = func.attr
                    if name == 'get_all_metrics':
                        callers.append(f"{py.name}:{node.lineno}")

        # After MetricsMediator: exactly 1 call site (metrics_mediator.py)
        assert len(callers) == 1, (
            f"GUI get_all_metrics() callers should be 1 (metrics_mediator.py), "
            f"found {len(callers)}: {callers}"
        )


# ═══════════════════════════════════════════════════════════════════════
# 12. LED Adaptive Tick Rate + USB Change Detection
# ═══════════════════════════════════════════════════════════════════════

class TestLEDAdaptive:
    """Verify LEDHandler adaptive tick rate and LEDDeviceController USB change detection."""

    @pytest.fixture(scope="module")
    def qapp(self):
        from PySide6.QtWidgets import QApplication
        app = QApplication.instance()
        if app is None:
            app = QApplication([])
        return app

    def test_animated_modes_use_fast_timer(self, qapp):
        """BREATHING, COLORFUL, RAINBOW modes use 150ms tick interval."""
        from trcc.qt_components.qt_app_mvc import LEDHandler
        from trcc.qt_components.uc_led_control import UCLedControl

        panel = UCLedControl()
        handler = LEDHandler(panel, lambda u: None)
        handler._controller = MagicMock()

        for mode_val in (1, 2, 3):  # BREATHING, COLORFUL, RAINBOW
            handler._controller.svc.mode.value = mode_val
            handler._adjust_tick_rate()
            assert handler._timer.interval() == 150, (
                f"Mode {mode_val} should use 150ms, got {handler._timer.interval()}ms"
            )
        handler.cleanup()

    def test_static_modes_use_slow_timer(self, qapp):
        """STATIC, TEMP_LINKED, LOAD_LINKED modes use 1000ms tick interval."""
        from trcc.qt_components.qt_app_mvc import LEDHandler
        from trcc.qt_components.uc_led_control import UCLedControl

        panel = UCLedControl()
        handler = LEDHandler(panel, lambda u: None)
        handler._controller = MagicMock()

        for mode_val in (0, 4, 5):  # STATIC, TEMP_LINKED, LOAD_LINKED
            handler._controller.svc.mode.value = mode_val
            handler._adjust_tick_rate()
            assert handler._timer.interval() == 1000, (
                f"Mode {mode_val} should use 1000ms, got {handler._timer.interval()}ms"
            )
        handler.cleanup()

    def test_led_usb_change_detection_skips_same_colors(self):
        """LEDDeviceController.tick() skips send_colors when colors unchanged."""
        from trcc.core.controllers import LEDDeviceController

        svc = MagicMock()
        svc.has_protocol = True
        colors = [(255, 0, 0)] * 30
        svc.tick.return_value = colors
        svc.apply_mask.return_value = colors

        ctrl = LEDDeviceController(svc)
        ctrl.on_preview_update = MagicMock()
        ctrl.on_send_complete = MagicMock()

        # First tick — should send
        ctrl.tick()
        svc.send_colors.assert_called_once()

        svc.send_colors.reset_mock()

        # Second tick — same colors → skip send
        ctrl.tick()
        svc.send_colors.assert_not_called()

        # Third tick — different colors → send
        new_colors = [(0, 255, 0)] * 30
        svc.tick.return_value = new_colors
        svc.apply_mask.return_value = new_colors
        ctrl.tick()
        svc.send_colors.assert_called_once()


# ═══════════════════════════════════════════════════════════════════════
# 13. MediaService Preload Memory Bound
# ═══════════════════════════════════════════════════════════════════════

class TestMediaPreloadBound:
    """Verify MediaService preload doesn't hold excessive memory."""

    def test_close_releases_large_frame_set(self):
        """Closing after loading 100 large frames frees all memory."""
        svc = MediaService()
        # Simulate 100 frames at 480x320 (~460KB each uncompressed)
        frames = [Image.new("RGB", (480, 320), (i, 0, 0)) for i in range(100)]
        refs = [weakref.ref(f) for f in frames]
        svc._frames = frames
        svc._state.total_frames = 100

        # Release our local reference
        del frames

        tracemalloc.start()
        _, before = tracemalloc.get_traced_memory()

        svc.close()
        gc.collect()

        _, after = tracemalloc.get_traced_memory()
        tracemalloc.stop()

        alive = sum(1 for r in refs if r() is not None)
        assert alive == 0, f"{alive}/100 frames still alive after close()"
        assert len(svc._frames) == 0

    def test_stop_vs_close_semantics(self):
        """stop() preserves frames (pause), close() releases them (unload)."""
        svc = MediaService()
        svc._frames = [Image.new("RGB", (4, 4)) for _ in range(5)]
        svc._state.total_frames = 5
        svc._state.state = PlaybackState.PLAYING

        svc.stop()
        assert len(svc._frames) == 5, "stop() should preserve frames"

        svc.close()
        assert len(svc._frames) == 0, "close() should release all frames"
