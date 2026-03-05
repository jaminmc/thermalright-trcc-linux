"""Pre-baked video frame cache — zero per-tick work during playback.

Three-layer compositing cache:
  L1: Raw video frames (owned by MediaService, native surfaces)
  L2: Frames + theme mask (pre-composited at load time)
  L4: Device-encoded bytes (RGB565 or JPEG, ready for send_rgb565())

Text overlay and brightness are baked into L4 at build time.
When metrics/brightness/rotation change, L4 is rebuilt from L2.
Steady-state per-tick cost: one list index + one SCSI write.
"""
from __future__ import annotations

import logging
from typing import Any

from ..core.models import HardwareMetrics

log = logging.getLogger(__name__)


class VideoFrameCache:
    """Pre-baked video frame cache — eliminates per-tick image work.

    Build once at video load; per-tick access is O(1) list index.
    Rebuild individual layers when parameters change (brightness, metrics).
    """

    def __init__(self) -> None:
        # L2: video frames + mask composite
        self._masked_frames: list[Any] = []
        # L4: device-encoded bytes (RGB565 or JPEG)
        self._encoded_frames: list[bytes] = []
        # Preview: composited frames (same source as L4, before encoding)
        self._preview_frames: list[Any] = []

        # Text overlay state
        self._text_overlay: Any | None = None
        self._text_cache_key: tuple | None = None

        # Brightness / rotation
        self._brightness: int = 100
        self._rotation: int = 0

        # Dimensions
        self._width: int = 0
        self._height: int = 0

        # Encoding params (from DeviceInfo)
        self._protocol: str = 'scsi'
        self._resolution: tuple[int, int] = (320, 320)
        self._fbl: int | None = None
        self._use_jpeg: bool = False

        self._active: bool = False

    # -- Properties ------------------------------------------------------------

    @property
    def active(self) -> bool:
        return self._active and bool(self._encoded_frames)

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
        """Full cache build. Called at video load time."""
        if not frames:
            return

        from .image import ImageService
        r = ImageService._r()

        # Convert PIL frames → native surfaces if needed (VideoDecoder
        # produces PIL Images; QtRenderer needs QImage).
        try:
            r.surface_size(frames[0])
        except (AttributeError, TypeError):
            frames = [r.from_pil(f) for f in frames]

        self._width, self._height = r.surface_size(frames[0])
        self._brightness = brightness
        self._rotation = rotation
        self._protocol = protocol
        self._resolution = resolution
        self._fbl = fbl
        self._use_jpeg = use_jpeg

        self._build_layer2(frames, mask, mask_position)
        self._render_text(overlay_svc, metrics)
        self._build_layer4()
        self._active = True
        log.info("VideoFrameCache: built %d frames (%d bytes each)",
                 len(self._encoded_frames),
                 len(self._encoded_frames[0]) if self._encoded_frames else 0)

    # -- Partial rebuilds ------------------------------------------------------

    def rebuild_from_metrics(
        self,
        overlay_svc: Any | None,
        metrics: HardwareMetrics,
    ) -> None:
        """Rebuild L4 with new metrics text. Called when display values change."""
        if not self._masked_frames:
            return
        self._render_text(overlay_svc, metrics)
        self._build_layer4()

    def rebuild_from_brightness(self, brightness: int) -> None:
        """Rebuild L4 with new brightness."""
        if not self._masked_frames:
            return
        self._brightness = brightness
        self._build_layer4()

    def rebuild_from_rotation(self, rotation: int) -> None:
        """Rebuild L4 with new rotation."""
        if not self._masked_frames:
            return
        self._rotation = rotation
        self._build_layer4()

    # -- Per-tick access -------------------------------------------------------

    def get_encoded(self, index: int) -> bytes | None:
        """Get pre-encoded bytes for frame index. O(1)."""
        if 0 <= index < len(self._encoded_frames):
            return self._encoded_frames[index]
        return None

    def get_preview(self, index: int) -> Any | None:
        """Return the composited frame for GUI preview.

        Same source image that was encoded for the LCD — single pipeline,
        no lazy reconstruction.  What you see = what the LCD shows.
        """
        if 0 <= index < len(self._preview_frames):
            return self._preview_frames[index]
        return None

    # -- Private: layer builders -----------------------------------------------

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

    def _build_layer4(self) -> None:
        """Encode all composited frames to device bytes → _encoded_frames.

        Also stores the composited frames in _preview_frames so
        preview and LCD use the exact same source (single pipeline).
        """
        from .image import ImageService
        r = ImageService._r()

        self._encoded_frames = []
        self._preview_frames = []
        for masked in self._masked_frames:
            frame = r.copy_surface(masked)

            # Composite text overlay
            if self._text_overlay is not None:
                frame = r.composite(frame, self._text_overlay, (0, 0))

            # Apply brightness
            if self._brightness < 100:
                frame = ImageService.apply_brightness(frame, self._brightness)

            # Apply user rotation
            if self._rotation:
                frame = ImageService.apply_rotation(frame, self._rotation)

            # Save composited frame for preview (before lossy encoding)
            self._preview_frames.append(frame)

            # Encode for device
            encoded = ImageService.encode_for_device(
                frame, self._protocol, self._resolution,
                self._fbl, self._use_jpeg)
            self._encoded_frames.append(encoded)

    def _render_text(
        self,
        overlay_svc: Any | None,
        metrics: HardwareMetrics,
    ) -> None:
        """Render text-only overlay via OverlayService."""
        if overlay_svc is None or not overlay_svc.enabled:
            self._text_overlay = None
            self._text_cache_key = None
            return

        text_surface, cache_key = overlay_svc.render_text_only(metrics)
        if cache_key == self._text_cache_key:
            return  # Text unchanged, skip L4 rebuild
        self._text_overlay = text_surface
        self._text_cache_key = cache_key
