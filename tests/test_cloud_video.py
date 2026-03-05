"""Test cloud video playback pipeline — end to end.

Reproduces: cloud theme loads, shows one frame, then disappears.
"""
from pathlib import Path
from unittest.mock import MagicMock

import pytest

from trcc.core.controllers import create_controller
from trcc.core.models import ThemeInfo
from trcc.services.image import ImageService

DATA_DIR = Path(__file__).parent.parent / 'src' / 'trcc' / 'data'
VIDEO_DIR = Path.home() / '.trcc' / 'data' / 'web' / '320320'


def _find_test_video() -> Path | None:
    """Find a cached cloud theme MP4 for testing."""
    if VIDEO_DIR.exists():
        for f in VIDEO_DIR.iterdir():
            if f.suffix == '.mp4':
                return f
    return None


@pytest.fixture
def controller():
    """Create a fully initialized controller."""
    ctrl = create_controller(DATA_DIR)
    return ctrl


@pytest.fixture
def preview_log():
    """Track every call to on_preview_update."""
    calls = []

    def recorder(image):
        calls.append(image)

    return calls, recorder


class TestCloudVideoPlayback:
    """Test the full cloud video pipeline."""

    def test_video_loads_and_plays(self, controller):
        """Cloud video: load → frames exist → is_playing."""
        video = _find_test_video()
        if not video:
            pytest.skip("No cached cloud video MP4")

        theme = ThemeInfo.from_video(video)
        controller.load_cloud_theme(theme)

        assert controller.is_video_playing()
        assert len(controller._display.media._frames) > 0

    def test_video_tick_returns_frames(self, controller):
        """Each video_tick must return a valid frame."""
        video = _find_test_video()
        if not video:
            pytest.skip("No cached cloud video MP4")

        theme = ThemeInfo.from_video(video)
        controller.load_cloud_theme(theme)

        # Tick 10 times — every tick must produce a frame
        none_count = 0
        for i in range(10):
            result = controller._display.video_tick()
            if result is None:
                none_count += 1
            else:
                # Cached path returns encoded (bytes), fallback returns preview (PIL)
                if result.get('encoded') is not None:
                    assert isinstance(result['encoded'], bytes)
                else:
                    assert result['preview'] is not None
                    r = ImageService._r()
                    assert r.surface_size(result['preview']) == (320, 320)

        assert none_count == 0, f"{none_count}/10 ticks returned None"

    def test_fire_preview_called_every_tick(self, controller, preview_log):
        """Preview must fire every tick via on_preview_update (PIL)."""
        video = _find_test_video()
        if not video:
            pytest.skip("No cached cloud video MP4")

        calls, recorder = preview_log
        controller.on_preview_update = recorder

        theme = ThemeInfo.from_video(video)
        controller.load_cloud_theme(theme)

        # First frame from load
        assert len(calls) >= 1, "load_cloud_theme should fire preview"
        assert calls[0] is not None, "First preview frame is None!"

        # Tick 10 more times
        for _ in range(10):
            controller.video_tick()

        # Dedup may skip 1 when load + first tick return same frame object
        assert len(calls) >= 10, (
            f"Expected 10+ preview calls, got {len(calls)}")

        # Check NONE of the calls are None
        for i, img in enumerate(calls):
            assert img is not None, f"Preview call {i} was None!"

    def test_overlay_render_doesnt_return_none(self, controller):
        """overlay.render() must never return None during video playback."""
        video = _find_test_video()
        if not video:
            pytest.skip("No cached cloud video MP4")

        theme = ThemeInfo.from_video(video)
        controller.load_cloud_theme(theme)

        overlay = controller._display.overlay
        overlay.enabled = True

        for i in range(10):
            frame = controller._display.media.advance_frame()
            assert frame is not None, f"Frame {i} is None"

            result = overlay.render(frame)
            assert result is not None, f"overlay.render returned None on frame {i}"
            r = ImageService._r()
            assert r.surface_size(result) == (320, 320), (
                f"overlay.render size wrong: {r.surface_size(result)}")

    def test_render_overlay_and_preview_during_video(self, controller, preview_log):
        """render_overlay_and_preview must NOT clear the preview during video."""
        video = _find_test_video()
        if not video:
            pytest.skip("No cached cloud video MP4")

        calls, recorder = preview_log
        controller.on_preview_update = recorder

        theme = ThemeInfo.from_video(video)
        controller.load_cloud_theme(theme)

        initial_count = len(calls)

        # Simulate what metrics timer does
        controller.render_overlay_and_preview()

        # Should have added one more call, and it should NOT be None
        assert len(calls) > initial_count
        assert calls[-1] is not None, "render_overlay_and_preview sent None to preview!"

    def test_no_none_preview_after_state_change(self, controller, preview_log):
        """Simulate PLAYING state change — preview must not get cleared."""
        video = _find_test_video()
        if not video:
            pytest.skip("No cached cloud video MP4")

        calls, recorder = preview_log
        controller.on_preview_update = recorder

        theme = ThemeInfo.from_video(video)
        controller.load_cloud_theme(theme)

        # Simulate what _on_video_state_changed does
        controller.on_video_state_changed = MagicMock()

        # Run 20 ticks
        for _ in range(20):
            controller.video_tick()

        none_frames = [i for i, img in enumerate(calls) if img is None]
        assert not none_frames, f"None frames at indices: {none_frames}"
