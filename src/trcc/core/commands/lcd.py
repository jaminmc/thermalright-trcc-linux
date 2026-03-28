"""LCD command dataclasses.

Each command corresponds to one LCDDevice operation.
All are frozen + slotted — value objects with no behaviour.
__post_init__ validates bounded fields at construction time.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any

from ..command_bus import LCDCommand


@dataclass(frozen=True, slots=True)
class SendImageCommand(LCDCommand):
    """Send a static image file to the LCD."""
    image_path: str = ""


@dataclass(frozen=True, slots=True)
class SendColorCommand(LCDCommand):
    """Fill the LCD with a solid RGB colour."""
    r: int = 0
    g: int = 0
    b: int = 0


@dataclass(frozen=True, slots=True)
class SetBrightnessCommand(LCDCommand):
    """Set display brightness (0–100)."""
    level: int = 3

    def __post_init__(self) -> None:
        if not 0 <= self.level <= 100:
            raise ValueError(f"brightness level must be 0–100, got {self.level}")


@dataclass(frozen=True, slots=True)
class SetRotationCommand(LCDCommand):
    """Rotate the display (0 | 90 | 180 | 270 degrees)."""
    degrees: int = 0


@dataclass(frozen=True, slots=True)
class SetSplitModeCommand(LCDCommand):
    """Set split-screen mode (0–3)."""
    mode: int = 0

    def __post_init__(self) -> None:
        if self.mode not in range(4):
            raise ValueError(f"split mode must be 0–3, got {self.mode}")


@dataclass(frozen=True, slots=True)
class LoadThemeByNameCommand(LCDCommand):
    """Load a named theme, optionally at a specific resolution."""
    name: str = ""
    width: int = 0
    height: int = 0


@dataclass(frozen=True, slots=True)
class PlayVideoLoopCommand(LCDCommand):
    """Start video/GIF/ZT playback."""
    video_path: str = ""
    loop: bool = True
    duration: float = 0.0


@dataclass(frozen=True, slots=True)
class EnableOverlayCommand(LCDCommand):
    """Enable or disable the overlay pipeline."""
    on: bool = True


@dataclass(frozen=True, slots=True)
class UpdateMetricsLCDCommand(LCDCommand):
    """Push fresh sensor metrics to the LCD overlay renderer."""
    metrics: Any = field(default=None, hash=False, compare=False)


@dataclass(frozen=True, slots=True)
class SelectThemeCommand(LCDCommand):
    """Select and load a ThemeInfo object (GUI — caller already has the object)."""
    theme: Any = field(default=None, hash=False, compare=False)


@dataclass(frozen=True, slots=True)
class SaveThemeCommand(LCDCommand):
    """Save current display state as a named theme."""
    name: str = ""
    data_dir: str = ""


@dataclass(frozen=True, slots=True)
class ExportThemeCommand(LCDCommand):
    """Export a theme directory to a .tr archive."""
    path: str = ""


@dataclass(frozen=True, slots=True)
class ImportThemeCommand(LCDCommand):
    """Import a .tr theme archive into the theme directory."""
    path: str = ""
    data_dir: str = ""


@dataclass(frozen=True, slots=True)
class LoadMaskCommand(LCDCommand):
    """Load a mask overlay and composite with current background."""
    mask_path: str = ""


@dataclass(frozen=True, slots=True)
class RenderOverlayFromDCCommand(LCDCommand):
    """Render overlay from a DC config file (CLI/API standalone)."""
    dc_path: str = ""
    send: bool = False
    output: str = ""
    metrics: Any = field(default=None, hash=False, compare=False)


@dataclass(frozen=True, slots=True)
class SetOverlayConfigCommand(LCDCommand):
    """Apply an overlay element config dict to the overlay service."""
    config: Any = field(default=None, hash=False, compare=False)


@dataclass(frozen=True, slots=True)
class ResetDisplayCommand(LCDCommand):
    """Reset the LCD display to a solid red frame (device test)."""


@dataclass(frozen=True, slots=True)
class SetResolutionCommand(LCDCommand):
    """Set the active display resolution (runtime resolution change).

    Use InitializeDeviceCommand on initial device connect instead.
    """
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class EnsureDataCommand(LCDCommand):
    """Download and extract theme/web/mask archives for a resolution.

    Fired automatically by InitializeDeviceCommand and SetResolutionCommand
    once the device resolution is known. Safe to dispatch multiple times —
    no-op if already cached. All three adapters (CLI, API, GUI) get data
    via this single path.
    """
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class InitializeDeviceCommand(LCDCommand):
    """Initialize display pipeline for a newly connected device.

    Dispatched unconditionally on every device connect, carrying the real
    w×h from the USB handshake. Sets media target size, overlay resolution,
    theme dirs, and triggers data download — regardless of whether the
    resolution changed since the last session.
    """
    width: int
    height: int


@dataclass(frozen=True, slots=True)
class RestoreLastThemeCommand(LCDCommand):
    """Restore the last-used theme, mask, and overlay from per-device config.

    All three adapters (CLI, GUI, API) dispatch this single command on device
    connect to restore the previous session state. The handler reads config,
    loads the theme, applies mask and overlay, and returns the result dict so
    each adapter can update its own presentation layer.
    """
