"""Video frame cache — C#-matching per-frame compositing.

Three-layer cache:
  L2: Frames + theme mask (pre-composited at load time, immutable)
  L3: Device-encoded bytes per frame (frame + mask + text overlay).
      Fills naturally during the first playback loop — each frame is
      encoded once on first access and reused on every subsequent loop.
      After one full loop with stable metrics, playback is pure USB send
      with zero compositing or encoding overhead.

      L3 is keyed by (text_cache_key, brightness, rotation). A metrics
      change that alters displayed text clears all slots; they refill
      lazily over the next loop. Metrics change rarely (CPU rounds to
      whole numbers, clock ticks once per minute) so L3 stays valid
      the vast majority of the time.

C# approach (FormCZTV.Timer_event): overlay text re-renders every ~1s
(64 ticks × 15ms), but compositing + encoding happens per-frame at
send time — NOT bulk re-encoding all frames.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.models import HardwareMetrics

log = logging.getLogger(__name__)


class VideoFrameCache:
    """Video frame cache with lazy per-frame L3 encoding.

    L2 (video + mask) is built once at load time.
    L3 (encoded bytes per frame, including text overlay) fills during the
    first playback loop. After one full loop with stable metrics, every
    get_encoded() call is a pure list lookup — no compositing, no encoding.
    """

    def __init__(self) -> None:
        # L2: video frames + mask composite (immutable after build)
        self._masked_frames: list[Any] = []

        # Text overlay state
        self._text_overlay: Any | None = None
        self._text_cache_key: tuple | None = None

        # Brightness / rotation
        self._brightness: int = 100
        self._rotation: int = 0

        # Encoding params (from DeviceInfo)
        self._protocol: str = 'scsi'
        self._resolution: tuple[int, int] = (320, 320)
        self._fbl: int | None = None
        self._use_jpeg: bool = False

        # L3: per-frame encoded bytes + preview.
        # None = not yet encoded for this frame index.
        # Keyed by (_l3_text_key, _l3_brightness, _l3_rotation).
        self._l3_encoded: list[bytes | None] = []
        self._l3_preview: list[Any | None] = []
        self._l3_text_key: tuple | None = None
        self._l3_brightness: int = 100
        self._l3_rotation: int = 0

        self._active: bool = False

    # -- Properties ------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active and bool(self._masked_frames)

    # -- Full build (video load) -----------------------------------------------

    def build(
        self,
        frames: list[Any],
        mask: Any | None,
        mask_position: tuple[int, int],
        overlay_svc: Any | None,
        metrics: HardwareMetrics,
        brightness: int,
        rotation: int,
        protocol: str,
        resolution: tuple[int, int],
        fbl: int | None,
        use_jpeg: bool,
    ) -> None:
        """Build L2 cache. Called at video load time."""
        if not frames:
            return

        from .image import ImageService
        r = ImageService._r()

        # Convert frames to native surfaces if needed
        from ..core.ports import RawFrame
        first = frames[0]
        if isinstance(first, RawFrame):
            frames = [r.from_raw_rgb24(f) for f in frames]
        else:
            try:
                r.surface_size(first)
            except (AttributeError, TypeError):
                frames = list(frames)  # Already native surfaces (QImage)

        self._brightness = brightness
        self._rotation = rotation
        self._protocol = protocol
        self._resolution = resolution
        self._fbl = fbl
        self._use_jpeg = use_jpeg

        self._build_layer2(frames, mask, mask_position)
        self._render_text(overlay_svc, metrics)
        self._reset_l3()
        self._active = True
        log.info("VideoFrameCache: built %d frames", len(self._masked_frames))

    # -- Partial rebuilds ------------------------------------------------------

    def rebuild_from_metrics(
        self,
        overlay_svc: Any | None,
        metrics: HardwareMetrics,
    ) -> None:
        """Update text overlay surface. L3 slots refill naturally on next access."""
        if not self._masked_frames:
            return
        self._render_text(overlay_svc, metrics)
        # L3 validity check in _ensure_frame detects the key change and clears slots

    def rebuild_from_brightness(self, brightness: int) -> None:
        """Update brightness. L3 slots refill naturally on next access."""
        if not self._masked_frames:
            return
        self._brightness = brightness
        self._reset_l3()

    def rebuild_from_rotation(self, rotation: int) -> None:
        """Update rotation. L3 slots refill naturally on next access."""
        if not self._masked_frames:
            return
        self._rotation = rotation
        self._reset_l3()

    # -- Per-tick access -------------------------------------------------------

    def get_frame(self, index: int) -> tuple[Any | None, bytes | None]:
        """Get preview + encoded bytes for frame index in one call.

        Calls _ensure_frame once per tick instead of twice.
        Returns (preview, encoded).
        """
        if not (0 <= index < len(self._masked_frames)):
            return None, None
        self._ensure_frame(index)
        return self._l3_preview[index], self._l3_encoded[index]

    def get_encoded(self, index: int) -> bytes | None:
        """Get encoded bytes for frame index. Use get_frame() when preview is also needed."""
        if not (0 <= index < len(self._masked_frames)):
            return None
        self._ensure_frame(index)
        return self._l3_encoded[index]

    def get_preview(self, index: int) -> Any | None:
        """Get composited preview for frame index. Use get_frame() when encoded is also needed."""
        if not (0 <= index < len(self._masked_frames)):
            return None
        self._ensure_frame(index)
        return self._l3_preview[index]

    # -- Private ---------------------------------------------------------------

    def _ensure_frame(self, index: int) -> None:
        """Composite + encode frame into L3 if not already cached.

        Detects settings changes (text/brightness/rotation) and clears all
        L3 slots so they refill with the new settings over the next loop.
        """
        if (self._text_cache_key != self._l3_text_key
                or self._brightness != self._l3_brightness
                or self._rotation != self._l3_rotation):
            self._reset_l3()

        if self._l3_encoded[index] is not None:
            return  # L3 hit — pure list lookup

        from .image import ImageService
        r = ImageService._r()

        frame = r.copy_surface(self._masked_frames[index])

        if self._text_overlay is not None:
            frame = r.composite(frame, self._text_overlay, (0, 0))

        if self._brightness < 100:
            frame = ImageService.apply_brightness(frame, self._brightness)

        if self._rotation:
            frame = ImageService.apply_rotation(frame, self._rotation)

        self._l3_preview[index] = frame
        self._l3_encoded[index] = ImageService.encode_for_device(
            frame, self._protocol, self._resolution,
            self._fbl, self._use_jpeg)

    def _reset_l3(self) -> None:
        """Clear all L3 slots. They refill lazily during the next playback loop."""
        n = len(self._masked_frames)
        self._l3_encoded = [None] * n
        self._l3_preview = [None] * n
        self._l3_text_key = self._text_cache_key
        self._l3_brightness = self._brightness
        self._l3_rotation = self._rotation

    def _build_layer2(
        self,
        frames: list[Any],
        mask: Any | None,
        mask_position: tuple[int, int],
    ) -> None:
        """Composite mask onto each video frame → _masked_frames.

        If no mask, L2 references L1 directly (zero copy).
        """
        if mask is None:
            self._masked_frames = list(frames)
            return

        from .image import ImageService
        r = ImageService._r()
        mask_rgba = r.convert_to_rgba(mask)
        self._masked_frames = []
        for frame in frames:
            composited = r.copy_surface(frame)
            composited = r.composite(composited, mask_rgba, mask_position)
            self._masked_frames.append(composited)

    def _render_text(
        self,
        overlay_svc: Any | None,
        metrics: HardwareMetrics,
    ) -> bool:
        """Render text-only overlay via OverlayService.

        Returns True if text changed.
        """
        if overlay_svc is None or not overlay_svc.enabled:
            changed = self._text_overlay is not None
            self._text_overlay = None
            self._text_cache_key = None
            return changed

        text_surface, cache_key = overlay_svc.render_text_only(metrics)
        if cache_key == self._text_cache_key:
            return False  # Text unchanged
        self._text_overlay = text_surface
        self._text_cache_key = cache_key
        return True
