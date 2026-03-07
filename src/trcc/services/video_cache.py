"""Video frame cache — C#-matching per-frame compositing.

Two-layer cache:
  L2: Frames + theme mask (pre-composited at load time, immutable)
  L4: Device-encoded bytes (lazily computed per frame on access)

C# approach (FormCZTV.Timer_event): overlay text re-renders every ~1s
(64 ticks × 15ms), but compositing + encoding happens per-frame at
send time — NOT bulk re-encoding all frames.

We match this: text overlay is a separate surface updated on metrics
change. Per-tick, only the CURRENT frame is composited + encoded.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.models import HardwareMetrics

log = logging.getLogger(__name__)


class VideoFrameCache:
    """Video frame cache with lazy per-frame encoding.

    L2 (video + mask) is built once at load time.
    Text overlay, brightness, rotation are applied per-frame on access.
    Only the current frame is encoded — not the entire set.
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

        # Per-frame encoding cache: only cache the last encoded frame
        self._last_index: int = -1
        self._last_encoded: bytes | None = None
        self._last_preview: Any | None = None
        self._last_text_key: tuple | None = None
        self._last_brightness: int = 100
        self._last_rotation: int = 0

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

        # Convert PIL frames → native surfaces if needed
        try:
            r.surface_size(frames[0])
        except (AttributeError, TypeError):
            frames = [r.from_pil(f) for f in frames]

        self._brightness = brightness
        self._rotation = rotation
        self._protocol = protocol
        self._resolution = resolution
        self._fbl = fbl
        self._use_jpeg = use_jpeg

        self._build_layer2(frames, mask, mask_position)
        self._render_text(overlay_svc, metrics)
        self._invalidate_frame_cache()
        self._active = True
        log.info("VideoFrameCache: built %d frames", len(self._masked_frames))

    # -- Partial rebuilds ------------------------------------------------------

    def rebuild_from_metrics(
        self,
        overlay_svc: Any | None,
        metrics: HardwareMetrics,
    ) -> None:
        """Update text overlay surface. Next get_encoded() will re-encode."""
        if not self._masked_frames:
            return
        self._render_text(overlay_svc, metrics)
        # Don't rebuild all frames — invalidate cache so next access re-encodes

    def rebuild_from_brightness(self, brightness: int) -> None:
        """Update brightness. Next get_encoded() will re-encode."""
        if not self._masked_frames:
            return
        self._brightness = brightness
        self._invalidate_frame_cache()

    def rebuild_from_rotation(self, rotation: int) -> None:
        """Update rotation. Next get_encoded() will re-encode."""
        if not self._masked_frames:
            return
        self._rotation = rotation
        self._invalidate_frame_cache()

    # -- Per-tick access -------------------------------------------------------

    def get_encoded(self, index: int) -> bytes | None:
        """Get encoded bytes for frame index. Encodes on demand."""
        if not (0 <= index < len(self._masked_frames)):
            return None
        self._ensure_frame(index)
        return self._last_encoded

    def get_preview(self, index: int) -> Any | None:
        """Get composited preview for frame index. Composites on demand."""
        if not (0 <= index < len(self._masked_frames)):
            return None
        self._ensure_frame(index)
        return self._last_preview

    # -- Private ---------------------------------------------------------------

    def _ensure_frame(self, index: int) -> None:
        """Composite + encode a single frame if not already cached."""
        if (index == self._last_index
                and self._text_cache_key == self._last_text_key
                and self._brightness == self._last_brightness
                and self._rotation == self._last_rotation
                and self._last_encoded is not None):
            return  # Cache hit

        from .image import ImageService
        r = ImageService._r()

        frame = r.copy_surface(self._masked_frames[index])

        # Composite text overlay
        if self._text_overlay is not None:
            frame = r.composite(frame, self._text_overlay, (0, 0))

        # Apply brightness
        if self._brightness < 100:
            frame = ImageService.apply_brightness(frame, self._brightness)

        # Apply rotation
        if self._rotation:
            frame = ImageService.apply_rotation(frame, self._rotation)

        # Cache preview + encoded
        self._last_preview = frame
        self._last_encoded = ImageService.encode_for_device(
            frame, self._protocol, self._resolution,
            self._fbl, self._use_jpeg)
        self._last_index = index
        self._last_text_key = self._text_cache_key
        self._last_brightness = self._brightness
        self._last_rotation = self._rotation

    def _invalidate_frame_cache(self) -> None:
        """Force re-encode on next access."""
        self._last_index = -1
        self._last_encoded = None
        self._last_preview = None

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
