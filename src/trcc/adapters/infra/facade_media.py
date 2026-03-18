"""Media frame decoders for TRCC Linux.

Pure infrastructure — decodes video/animation files into frames + metadata.
No playback state (play/pause/stop/seek). That belongs in MediaService.

Decoders:
    VideoDecoder   — FFmpeg pipe → list of PIL frames + fps
    ThemeZtDecoder — Theme.zt binary → list of PIL frames + per-frame delays
"""

from __future__ import annotations

import io
import logging
import os
import struct
import subprocess

from PIL import Image

log = logging.getLogger(__name__)


def _check_ffmpeg() -> bool:
    """Check if ffmpeg is available in PATH."""
    try:
        result = subprocess.run(
            ['ffmpeg', '-version'], capture_output=True, timeout=5,
        )
        return result.returncode == 0
    except Exception:
        return False


FFMPEG_AVAILABLE = _check_ffmpeg()


class VideoDecoder:
    """Decode video frames via FFmpeg pipe. No playback state."""

    def __init__(self, video_path: str, target_size: tuple[int, int] = (320, 320),
                 fit_mode: str = 'fill') -> None:
        if not FFMPEG_AVAILABLE:
            from trcc.core.builder import ControllerBuilder
            raise RuntimeError(
                ControllerBuilder.build_setup().ffmpeg_install_help()
            )
        self.frames: list[Image.Image] = []
        self.fps: int = 16  # Windows: originalImageHz = 16

        self._decode(video_path, target_size, fit_mode)

    def _decode(self, video_path: str, target_size: tuple[int, int],
                fit_mode: str = 'fill') -> None:
        """Decode all frames through FFmpeg pipe.

        fit_mode:
            'fill'   — stretch to fill LCD (current default)
            'width'  — scale width to LCD, letterbox/crop height (C# buttonTPJCW)
            'height' — scale height to LCD, letterbox/crop width (C# buttonTPJCH)
        """
        w, h = target_size

        if fit_mode in ('width', 'height'):
            video_dims = self._probe_dimensions(video_path)
            if video_dims:
                vw, vh = video_dims
                if fit_mode == 'width':
                    scale_w, scale_h = w, max(2, int(vh * w / vw) & ~1)
                else:
                    scale_w, scale_h = max(2, int(vw * h / vh) & ~1), h
            else:
                scale_w, scale_h = w, h
        else:
            scale_w, scale_h = w, h

        result = subprocess.run([
            'ffmpeg', '-i', video_path,
            '-r', str(self.fps),
            '-vf', f'scale={scale_w}:{scale_h}',
            '-f', 'rawvideo', '-pix_fmt', 'rgb24',
            '-loglevel', 'error', 'pipe:1',
        ], capture_output=True, timeout=300)

        if result.returncode != 0:
            raise RuntimeError(f"FFmpeg failed: {result.stderr.decode()[:200]}")

        raw = result.stdout
        frame_size = scale_w * scale_h * 3
        need_composite = fit_mode in ('width', 'height') and (scale_w != w or scale_h != h)

        for i in range(0, len(raw), frame_size):
            chunk = raw[i:i + frame_size]
            if len(chunk) < frame_size:
                break
            frame = Image.frombytes('RGB', (scale_w, scale_h), chunk)

            if need_composite:
                # Composite onto black canvas — letterbox or center-crop
                canvas = Image.new('RGB', (w, h), (0, 0, 0))
                px = (w - scale_w) // 2
                py = (h - scale_h) // 2
                if scale_w > w or scale_h > h:
                    # Center-crop: frame overflows canvas
                    left = max(0, (scale_w - w) // 2)
                    top = max(0, (scale_h - h) // 2)
                    frame = frame.crop((left, top, left + w, top + h))
                    canvas.paste(frame, (max(0, px), max(0, py)))
                else:
                    # Letterbox: frame fits inside canvas
                    canvas.paste(frame, (px, py))
                self.frames.append(canvas)
            else:
                self.frames.append(frame)

    @staticmethod
    def _probe_dimensions(video_path: str) -> tuple[int, int] | None:
        """Get original video dimensions via ffprobe."""
        try:
            result = subprocess.run([
                'ffprobe', '-v', 'error',
                '-select_streams', 'v:0',
                '-show_entries', 'stream=width,height',
                '-of', 'csv=p=0',
                video_path,
            ], capture_output=True, timeout=10, text=True)
            if result.returncode == 0 and result.stdout.strip():
                parts = result.stdout.strip().split(',')
                if len(parts) >= 2:
                    return int(parts[0]), int(parts[1])
        except Exception:
            pass
        return None

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    def close(self) -> None:
        self.frames = []

    @staticmethod
    def extract_frames(
        video_path: str,
        output_dir: str,
        target_size: tuple[int, int] = (320, 320),
        max_frames: int | None = None,
    ) -> int:
        """Extract video frames to PNG files via FFmpeg."""
        if not FFMPEG_AVAILABLE:
            log.warning("FFmpeg not available for video extraction")
            return 0

        os.makedirs(output_dir, exist_ok=True)
        w, h = target_size

        cmd = [
            'ffmpeg', '-i', video_path, '-y',
            '-vf', f'scale={w}:{h}',
        ]
        if max_frames:
            cmd.extend(['-vframes', str(max_frames)])
        cmd.extend(['-f', 'image2', os.path.join(output_dir, 'frame_%04d.png')])

        try:
            result = subprocess.run(cmd, capture_output=True, timeout=600)
            if result.returncode != 0:
                log.error("FFmpeg error: %s", result.stderr.decode()[:200])
                return 0
        except subprocess.TimeoutExpired:
            log.error("FFmpeg timed out")
            return 0
        except Exception:
            log.exception("FFmpeg failed")
            return 0

        extracted = len([
            f for f in os.listdir(output_dir)
            if f.startswith('frame_') and f.endswith('.png')
        ])
        log.info("Extracted %d frames to %s", extracted, output_dir)
        return extracted


class ThemeZtDecoder:
    """Decode Theme.zt animation files. No playback state.

    Theme.zt format (Windows UCVideoCut.BmpToThemeFile):
    - byte: 0xDC magic (220)
    - int32: frame_count
    - int32[frame_count]: timestamps in ms
    - for each frame: int32 size + JPEG bytes
    """

    def __init__(self, zt_path: str, target_size: tuple[int, int] | None = None) -> None:
        self.frames: list[Image.Image] = []
        self.timestamps: list[int] = []
        self.delays: list[int] = []

        with open(zt_path, 'rb') as f:
            magic = struct.unpack('B', f.read(1))[0]
            if magic != 0xDC:
                raise ValueError(f"Invalid Theme.zt magic: 0x{magic:02X}, expected 0xDC")

            frame_count = struct.unpack('<i', f.read(4))[0]

            for _ in range(frame_count):
                self.timestamps.append(struct.unpack('<i', f.read(4))[0])

            for _ in range(frame_count):
                size = struct.unpack('<i', f.read(4))[0]
                img = Image.open(io.BytesIO(f.read(size)))
                if target_size and img.size != target_size:
                    img = img.resize(target_size, Image.Resampling.LANCZOS)
                if img.mode != 'RGB':
                    img = img.convert('RGB')
                self.frames.append(img)

        # Calculate delays from timestamps
        for i in range(len(self.timestamps)):
            if i < len(self.timestamps) - 1:
                delay = self.timestamps[i + 1] - self.timestamps[i]
            else:
                delay = self.delays[-1] if self.delays else 42  # ~24fps default
            self.delays.append(max(1, delay))

    @property
    def frame_count(self) -> int:
        return len(self.frames)

    @property
    def fps(self) -> float:
        """Average fps derived from delays."""
        if not self.delays:
            return 24.0
        avg_delay = sum(self.delays) / len(self.delays)
        return 1000.0 / avg_delay if avg_delay > 0 else 24.0

    def close(self) -> None:
        for frame in self.frames:
            if hasattr(frame, 'close'):
                frame.close()
        self.frames = []


# Backward-compat aliases
VideoPlayer = VideoDecoder
ThemeZtPlayer = ThemeZtDecoder
GIFAnimator = VideoDecoder
GIFThemeLoader = VideoDecoder
