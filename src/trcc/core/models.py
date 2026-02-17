"""
TRCC Models - Pure data classes with no GUI dependencies.

These models can be used by any GUI framework (Tkinter, PyQt6, etc.)
"""

from dataclasses import dataclass, field
from enum import Enum, IntEnum, auto
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

from ..adapters.infra.data_repository import ThemeDir

# =============================================================================
# Browser Item Dataclasses (replace raw dicts in theme/mask panels)
# =============================================================================


@dataclass
class ThemeItem:
    """Base for all theme browser items."""
    name: str
    is_local: bool = True


@dataclass
class LocalThemeItem(ThemeItem):
    """Item in the local themes browser (UCThemeLocal)."""
    path: str = ""
    thumbnail: str = ""
    is_user: bool = False
    index: int = 0  # position in unfiltered list


@dataclass
class CloudThemeItem(ThemeItem):
    """Item in the cloud themes browser (UCThemeWeb)."""
    id: str = ""
    video: Optional[str] = None
    preview: Optional[str] = None


@dataclass
class MaskItem(ThemeItem):
    """Item in the cloud masks browser (UCThemeMask)."""
    path: Optional[str] = None
    preview: Optional[str] = None


# =============================================================================
# Theme Model
# =============================================================================

@dataclass
class ThemeData:
    """Bundle returned after loading a theme — everything needed to display it."""
    background: Any = None               # PIL Image
    animation_path: Optional[Path] = None  # video/zt path
    is_animated: bool = False
    mask: Any = None                     # PIL Image
    mask_position: Optional[Tuple[int, int]] = None
    mask_source_dir: Optional[Path] = None


class ThemeType(Enum):
    """Type of theme."""
    LOCAL = auto()      # Local theme from Theme{resolution}/ directory
    CLOUD = auto()      # Cloud theme (video) from Web/{W}{H}/ directory
    MASK = auto()       # Mask overlay from Web/zt{W}{H}/ directory
    USER = auto()       # User-created theme


@dataclass
class ThemeInfo:
    """
    Information about a single theme.

    Matches Windows FormCZTV theme data structure.
    """
    name: str
    path: Optional[Path] = None
    theme_type: ThemeType = ThemeType.LOCAL

    # Files within theme directory
    background_path: Optional[Path] = None      # 00.png
    mask_path: Optional[Path] = None            # 01.png
    thumbnail_path: Optional[Path] = None       # Theme.png
    animation_path: Optional[Path] = None       # Theme.zt or video file
    config_path: Optional[Path] = None          # config1.dc

    # Metadata
    resolution: Tuple[int, int] = (320, 320)
    is_animated: bool = False
    is_mask_only: bool = False

    # Cloud theme specific
    video_url: Optional[str] = None
    preview_url: Optional[str] = None
    category: Optional[str] = None  # a=Gallery, b=Tech, c=HUD, etc.

    @classmethod
    def from_directory(cls, path: Path, resolution: Tuple[int, int] = (320, 320)) -> 'ThemeInfo':
        """Create ThemeInfo from a theme directory."""
        td = ThemeDir(path)

        # Determine if animated — check Theme.zt first, then .mp4 files
        if td.zt.exists():
            is_animated = True
            animation_path = td.zt
        else:
            mp4_files = list(path.glob('*.mp4'))
            if mp4_files:
                is_animated = True
                animation_path = mp4_files[0]
            else:
                is_animated = False
                animation_path = None

        return cls(
            name=path.name,
            path=path,
            theme_type=ThemeType.LOCAL,
            background_path=td.bg if td.bg.exists() else None,
            mask_path=td.mask if td.mask.exists() else None,
            thumbnail_path=td.preview if td.preview.exists() else (td.bg if td.bg.exists() else None),
            animation_path=animation_path,
            config_path=td.dc if td.dc.exists() else None,
            resolution=resolution,
            is_animated=is_animated,
            is_mask_only=not td.bg.exists() and td.mask.exists(),
        )

    @classmethod
    def from_video(cls, video_path: Path, preview_path: Optional[Path] = None) -> 'ThemeInfo':
        """Create ThemeInfo from a cloud video file."""
        name = video_path.stem
        category = name[0] if name else None

        return cls(
            name=name,
            path=video_path.parent,
            theme_type=ThemeType.CLOUD,
            animation_path=video_path,
            thumbnail_path=preview_path,
            is_animated=True,
            category=category,
        )


@dataclass
class DeviceInfo:
    """
    Information about a connected LCD device.

    Matches Windows FormCZTV device data.
    """
    name: str
    path: str  # /dev/sgX
    resolution: Tuple[int, int] = (0, 0)  # Discovered via handshake

    # Device properties (from detection)
    vendor: Optional[str] = None
    product: Optional[str] = None
    model: Optional[str] = None
    vid: int = 0
    pid: int = 0
    device_index: int = 0  # 0-based ordinal among detected devices
    fbl_code: Optional[int] = None  # Resolution identifier
    protocol: str = "scsi"  # "scsi" or "hid"
    device_type: int = 1  # 1=SCSI, 2=HID Type 2 ("H"), 3=HID Type 3 ("ALi")
    implementation: str = "generic"  # e.g. "thermalright_lcd_v1", "hid_type2", "hid_led"
    led_style_id: Optional[int] = None  # LED style from probe (avoids name-based lookup)

    # State
    connected: bool = True
    brightness: int = 65  # 0-100% (C# default: 65)
    rotation: int = 0  # 0, 90, 180, 270

    @classmethod
    def from_dict(cls, d: dict) -> 'DeviceInfo':
        """Create DeviceInfo from a detection dict (find_lcd_devices output)."""
        return cls(
            name=d.get('name', 'LCD'),
            path=d.get('path', ''),
            resolution=d.get('resolution', (0, 0)),
            vendor=d.get('vendor'),
            product=d.get('product'),
            model=d.get('model'),
            vid=d.get('vid', 0),
            pid=d.get('pid', 0),
            device_index=d.get('device_index', 0),
            protocol=d.get('protocol', 'scsi'),
            device_type=d.get('device_type', 1),
            implementation=d.get('implementation', 'generic'),
            led_style_id=d.get('led_style_id'),
        )

    @property
    def resolution_str(self) -> str:
        """Get resolution as string (e.g., '320x320')."""
        return f"{self.resolution[0]}x{self.resolution[1]}"


@dataclass
class HandshakeResult:
    """Common output from any device handshake.

    Every protocol (SCSI, HID, LED, Bulk) produces at least these fields.
    Protocol-specific subclasses (HidHandshakeInfo, LedHandshakeInfo) add extras.
    """

    resolution: Optional[Tuple[int, int]] = None
    model_id: int = 0
    serial: str = ""
    raw_response: bytes = field(default=b"", repr=False)


@dataclass
class HidHandshakeInfo(HandshakeResult):
    """HID-specific handshake info (extends HandshakeResult)."""
    device_type: int = 0      # 2 or 3
    mode_byte_1: int = 0     # Type 2: resp[5] (PM), Type 3: resp[0]-1
    mode_byte_2: int = 0     # Type 2: resp[4] (SUB), Type 3: 0
    fbl: Optional[int] = None  # FBL code resolved from PM/SUB


# Implementation key → display name (SCSI LCD devices)
IMPL_NAMES: dict[str, str] = {
    "thermalright_lcd_v1": "Thermalright LCD v1 (USBLCD)",
    "ali_corp_lcd_v1": "ALi Corp LCD v1 (USBLCD)",
    "generic": "Generic LCD",
}


@dataclass
class LCDDeviceConfig:
    """SCSI LCD device config — resolution, pixel format, protocol constants.

    Pure data: no I/O, no business logic. Business logic lives in
    ImageService (rgb_to_bytes, byte_order) and DeviceService (detect_resolution).
    """
    name: str = "Generic LCD"
    width: int = 320
    height: int = 320
    pixel_format: str = "RGB565"
    fbl: Optional[int] = None
    resolution_detected: bool = False
    poll_command: Tuple[int, int] = (0xF5, 0xE100)
    init_command: Tuple[int, int] = (0x1F5, 0xE100)
    init_per_frame: bool = False
    init_delay: float = 0.0
    frame_delay: float = 0.0

    @property
    def resolution(self) -> Tuple[int, int]:
        return (self.width, self.height)

    @staticmethod
    def from_key(impl_key: str) -> 'LCDDeviceConfig':
        """Factory: create config from implementation key."""
        name = IMPL_NAMES.get(impl_key, "Generic LCD")
        return LCDDeviceConfig(name=name)

    @staticmethod
    def list_all() -> list[dict[str, str]]:
        """List all available implementations."""
        return [{"name": key, "class": dn} for key, dn in IMPL_NAMES.items()]


class PlaybackState(Enum):
    """Video playback state."""
    STOPPED = auto()
    PLAYING = auto()
    PAUSED = auto()


@dataclass
class VideoState:
    """
    State of video/animation playback.
    """
    state: PlaybackState = PlaybackState.STOPPED
    current_frame: int = 0
    total_frames: int = 0
    fps: float = 16.0
    loop: bool = True

    @property
    def progress(self) -> float:
        """Get playback progress (0-100)."""
        if self.total_frames <= 0:
            return 0.0
        return (self.current_frame / self.total_frames) * 100

    @property
    def current_time_str(self) -> str:
        """Get current time as MM:SS string."""
        if self.fps <= 0:
            return "00:00"
        secs = self.current_frame / self.fps
        return f"{int(secs // 60):02d}:{int(secs % 60):02d}"

    @property
    def total_time_str(self) -> str:
        """Get total time as MM:SS string."""
        if self.fps <= 0:
            return "00:00"
        secs = self.total_frames / self.fps
        return f"{int(secs // 60):02d}:{int(secs % 60):02d}"

    @property
    def frame_interval_ms(self) -> int:
        """Get frame interval in milliseconds."""
        if self.fps <= 0:
            return 62  # Default ~16fps (Windows: 62.5ms per frame)
        return int(1000 / self.fps)


class OverlayElementType(Enum):
    """Type of overlay element."""
    HARDWARE = 0    # CPU temp, GPU usage, etc.
    TIME = 1        # Current time
    WEEKDAY = 2     # Day of week
    DATE = 3        # Current date
    TEXT = 4        # Custom text


@dataclass
class OverlayElement:
    """
    Single overlay element configuration.

    Matches Windows UCXiTongXianShi element data.
    """
    element_type: OverlayElementType = OverlayElementType.TEXT
    enabled: bool = True
    x: int = 10
    y: int = 10
    color: Tuple[int, int, int] = (255, 255, 255)
    font_size: int = 16
    font_name: str = "Microsoft YaHei"

    # Hardware element specific
    metric_key: Optional[str] = None  # e.g., 'cpu_temp', 'gpu_usage'
    format_string: str = "{value}"    # e.g., "CPU: {value}°C"

    # Text element specific
    text: str = ""


# =============================================================================
# LED Model (FormLED equivalent)
# =============================================================================

class LEDMode(Enum):
    """LED effect modes from FormLED.cs timer functions."""
    STATIC = 0       # DSCL_Timer: solid color
    BREATHING = 1    # DSHX_Timer: fade in/out, period=66 ticks
    COLORFUL = 2     # QCJB_Timer: 6-phase gradient, period=168 ticks
    RAINBOW = 3      # CHMS_Timer: 768-entry table shift
    TEMP_LINKED = 4  # WDLD_Timer: color from CPU/GPU temperature
    LOAD_LINKED = 5  # FZLD_Timer: color from CPU/GPU load %


@dataclass
class LEDZoneState:
    """Per-zone state for multi-zone LED devices.

    Multi-zone devices (styles 2,3,5,6,7,8,11) have 2-4 independent zones,
    each with its own mode, color, brightness, and on/off state.
    From FormLED.cs: myLedMode1-4, rgbR1_1-4, myBrightness1-4, myOnOff1-4.
    """
    mode: LEDMode = LEDMode.STATIC
    color: Tuple[int, int, int] = (255, 0, 0)
    brightness: int = 65   # 0-100 (C# default: 65)
    on: bool = True


@dataclass
class LEDState:
    """Complete LED device state matching FormLED.cs globals.

    This is the serializable state that gets persisted and restored.
    Animation counters are transient (not saved).
    """
    # Device configuration (from handshake pm → LedDeviceStyle)
    style: int = 1              # nowLedStyle
    led_count: int = 30         # from LedDeviceStyle.led_count
    segment_count: int = 10     # from LedDeviceStyle.segment_count
    zone_count: int = 1         # from LedDeviceStyle.zone_count

    # Global state
    mode: LEDMode = LEDMode.STATIC    # myLedMode
    color: Tuple[int, int, int] = (255, 0, 0)  # rgbR1, rgbG1, rgbB1
    brightness: int = 65        # myBrightness (0-100, C# default: 65)
    global_on: bool = True      # myOnOff

    # Per-segment on/off (ucScreenLED1.isOn[] per logical segment)
    segment_on: List[bool] = field(default_factory=list)

    # Multi-zone states (styles with zone_count > 1)
    zones: List[LEDZoneState] = field(default_factory=list)

    # Animation counters (transient, not persisted)
    rgb_timer: int = 0          # rgbTimer for breathing/gradient/rainbow
    test_mode: bool = False     # C# checkBox1 — diagnostic color cycle
    test_timer: int = 0         # testTimer — tick counter for test mode
    test_color: int = 0         # testCount — 0=white, 1=red, 2=green, 3=blue

    # Sensor linkage (for TEMP_LINKED and LOAD_LINKED modes)
    temp_source: str = "cpu"    # "cpu" or "gpu"
    load_source: str = "cpu"    # "cpu" or "gpu"

    # LC1 (style 4) sub-style: 0=memory, 1=hard disk
    sub_style: int = 0              # nowLedStyleSub
    memory_ratio: int = 2           # DDR multiplier (1, 2, or 4) — C# default: 2

    # LF11 (style 10) disk selector (C# hardDiskCount, 0-based)
    disk_index: int = 0

    # Segment carousel interval (ticks per phase, ~30ms per tick → 100 = ~3s)
    carousel_interval: int = 100

    # Zone carousel (LunBo) — C# isLunBo + LunBo1-4 + nowLunbo
    zone_carousel: bool = False          # isLunBo: rotate between zones
    zone_carousel_zones: List[bool] = field(default_factory=list)  # LunBo1-4
    zone_carousel_current: int = 0       # nowLunbo: current active zone
    zone_carousel_ticks: int = 0         # ValCount: tick counter
    zone_carousel_interval: int = 36     # 6 * textBoxTimer (default 6s)

    # LC2 clock settings (style 9)
    is_timer_24h: bool = True
    is_week_sunday: bool = False

    def __post_init__(self):
        if not self.segment_on:
            self.segment_on = [True] * self.segment_count
        if not self.zones and self.zone_count > 1:
            self.zones = [LEDZoneState() for _ in range(self.zone_count)]
        if not self.zone_carousel_zones and self.zone_count > 1:
            self.zone_carousel_zones = [True] + [False] * (self.zone_count - 1)


# =============================================================================
# LED Device Styles (from FormLED.cs FormLEDInit, lines 1598-1750)
# =============================================================================

@dataclass
class LedDeviceStyle:
    """LED device configuration derived from FormLEDInit pm→nowLedStyle.

    Attributes:
        style_id: Internal style number (nowLedStyle in Windows).
        led_count: Total addressable LEDs (LedCountValN).
        segment_count: Logical segments (LedCountValNs).
        zone_count: Number of independent zones (1=single, 2-4=multi).
        model_name: Human-readable model name.
        preview_image: Device background asset name (D{Name}.png).
        background_base: Localized background base (D0{Name}).
    """
    style_id: int
    led_count: int
    segment_count: int
    zone_count: int = 1
    model_name: str = ""
    preview_image: str = ""
    background_base: str = "D0数码屏"


# All LED styles from FormLED.cs FormLEDInit and UCScreenLED.cs constants
LED_STYLES: dict[int, LedDeviceStyle] = {
    1: LedDeviceStyle(1, 30, 10, 1, "AX120_DIGITAL", "DAX120_DIGITAL", "D0数码屏"),
    2: LedDeviceStyle(2, 84, 18, 4, "PA120_DIGITAL", "DPA120_DIGITAL", "D0数码屏4区域"),
    3: LedDeviceStyle(3, 64, 10, 2, "AK120_DIGITAL", "DAK120_DIGITAL", "D0数码屏"),
    4: LedDeviceStyle(4, 31, 14, 1, "LC1", "DLC1", "D0LC1"),
    5: LedDeviceStyle(5, 93, 23, 2, "LF8", "DLF8", "D0LF8"),
    6: LedDeviceStyle(6, 124, 72, 2, "LF12", "DLF12", "D0LF12"),
    7: LedDeviceStyle(7, 116, 12, 3, "LF10", "DLF10", "D0LF10"),
    8: LedDeviceStyle(8, 18, 13, 4, "CZ1", "DCZ1", "D0CZ1"),
    9: LedDeviceStyle(9, 61, 31, 1, "LC2", "DLC2", "D0LC2"),
    10: LedDeviceStyle(10, 38, 17, 1, "LF11", "DLF11", "D0LF11"),
    11: LedDeviceStyle(11, 93, 72, 2, "LF15", "DLF15", "D0LF15"),
    12: LedDeviceStyle(12, 62, 62, 1, "LF13", "DLF13", "D0rgblf13"),
    # HR10 2280 Pro Digital — NVMe SSD heatsink with ARGB digital display.
    13: LedDeviceStyle(13, 31, 14, 1, "HR10_2280_PRO_DIGITAL", "DAX120_DIGITAL", "D0数码屏"),
}


@dataclass
class LedHandshakeInfo(HandshakeResult):
    """LED-specific handshake info (extends HandshakeResult)."""
    pm: int = 0
    sub_type: int = 0
    style: Optional[LedDeviceStyle] = None
    model_name: str = ""


# =============================================================================
# PM Registry — PM byte → (style, model, button image)
# =============================================================================

class PmEntry(NamedTuple):
    """PM registry entry mapping a firmware PM byte to device metadata."""
    style_id: int
    model_name: str
    button_image: str
    preview_image: str = ""  # PM-specific preview; empty = use style default


class PmRegistry:
    """Encapsulates all PM-to-device metadata lookups.

    Maps firmware PM bytes (from HID handshake) to device style, model name,
    and button image.  Handles sub-type overrides (e.g. HR10 vs LC1 on PM=128)
    and PA120 variant range (PMs 17-31).
    """

    # (pm, sub_type) → PmEntry override for devices that share a PM byte.
    _OVERRIDES: dict[tuple[int, int], PmEntry] = {
        (128, 129): PmEntry(13, "HR10_2280_PRO_DIGITAL", "A1HR10 2280 PRO DIGITAL"),
    }

    # PM → PmEntry base registry (built once at class load time).
    _REGISTRY: dict[int, PmEntry] = {
        1:   PmEntry(1, "FROZEN_HORIZON_PRO", "A1FROZEN HORIZON PRO", "DFROZEN_HORIZON_PRO"),
        2:   PmEntry(1, "FROZEN_MAGIC_PRO", "A1FROZEN MAGIC PRO", "DFROZEN_MAGIC_PRO"),
        3:   PmEntry(1, "AX120_DIGITAL", "A1AX120 DIGITAL"),
        16:  PmEntry(2, "PA120_DIGITAL", "A1PA120 DIGITAL"),
        23:  PmEntry(2, "RK120_DIGITAL", "A1RK120 DIGITAL"),
        32:  PmEntry(3, "AK120_DIGITAL", "A1AK120 Digital"),
        48:  PmEntry(5, "LF8", "A1LF8"),
        49:  PmEntry(5, "LF10", "A1LF10"),
        80:  PmEntry(6, "LF12", "A1LF12"),
        96:  PmEntry(7, "LF10", "A1LF10"),
        112: PmEntry(9, "LC2", "A1LC2"),
        128: PmEntry(4, "LC1", "A1LC1"),
        129: PmEntry(10, "LF11", "A1LF11"),
        144: PmEntry(11, "LF15", "A1LF15"),
        160: PmEntry(12, "LF13", "A1LF13"),
        208: PmEntry(8, "CZ1", "A1CZ1"),
        # PA120 variants (PMs 17-22, 24-31) all map to style 2.
        **{pm: PmEntry(2, "PA120_DIGITAL", "A1PA120 DIGITAL")
           for pm in range(17, 32) if pm not in (23,)},
    }

    # PM → style_id convenience mapping (used by cli.py, debug_report.py).
    PM_TO_STYLE: dict[int, int] = {pm: e.style_id for pm, e in _REGISTRY.items()}

    @classmethod
    def resolve(cls, pm: int, sub_type: int = 0) -> Optional[PmEntry]:
        """Resolve PM + SUB to a PmEntry, checking overrides first."""
        return cls._OVERRIDES.get((pm, sub_type)) or cls._REGISTRY.get(pm)

    @classmethod
    def get_button_image(cls, pm: int, sub: int = 0) -> Optional[str]:
        """Resolve LED device button image from PM byte."""
        entry = cls.resolve(pm, sub)
        return entry.button_image if entry else None

    @classmethod
    def get_model_name(cls, pm: int, sub_type: int = 0) -> str:
        """Get human-readable model name for a PM + SUB byte combo."""
        entry = cls.resolve(pm, sub_type)
        return entry.model_name if entry else f"Unknown (pm={pm})"

    @classmethod
    def get_style(cls, pm: int, sub_type: int = 0) -> LedDeviceStyle:
        """Get LED device style from firmware PM byte."""
        entry = cls.resolve(pm, sub_type)
        return LED_STYLES[entry.style_id if entry else 1]

    @classmethod
    def get_preview_image(cls, pm: int, sub_type: int = 0) -> str:
        """Get device preview image name, PM-specific or style default."""
        entry = cls.resolve(pm, sub_type)
        if entry and entry.preview_image:
            return entry.preview_image
        style = cls.get_style(pm, sub_type)
        return style.preview_image


# Preset colors from FormLED.cs ucColor1_ChangeColor handlers
PRESET_COLORS: List[Tuple[int, int, int]] = [
    (255, 0, 42),     # C1: Red-pink
    (255, 110, 0),    # C2: Orange
    (255, 255, 0),    # C3: Yellow
    (0, 255, 0),      # C4: Green
    (0, 255, 255),    # C5: Cyan
    (0, 91, 255),     # C6: Blue
    (214, 0, 255),    # C7: Purple
    (255, 255, 255),  # C8: White
]


# =============================================================================
# LED Index Remapping Tables (from FormLED.cs SendHidVal)
# =============================================================================

# Style 2: PA120_DIGITAL (84 LEDs, 4 zones)
_REMAP_STYLE_2: tuple[int, ...] = (
    3, 2, 14, 9, 10, 15, 13, 12, 11,
    21, 16, 17, 22, 20, 19, 18,
    28, 23, 24, 29, 27, 26, 25,
    36, 31, 32, 37, 35, 34, 33,
    43, 38, 39, 44, 42, 41, 40,
    8, 8,
    75, 76, 77, 79, 74, 73, 78,
    68, 69, 70, 72, 67, 66, 71,
    82, 83, 6, 7,
    61, 62, 63, 65, 60, 59, 64,
    54, 55, 56, 58, 53, 52, 57,
    47, 48, 49, 51, 46, 45, 50,
    4, 5, 6, 7, 81, 80,
)

# Style 3: AK120_DIGITAL (64 LEDs, 2 zones)
_REMAP_STYLE_3: tuple[int, ...] = (
    1, 25, 26, 27, 29, 24, 23, 28,
    17, 2, 16, 21, 22, 18, 19, 20,
    10, 9, 14, 15, 11, 12, 13,
    36, 31, 32, 37, 35, 34, 33,
    43, 38, 39, 44, 42, 41, 40,
    50, 45, 46, 51, 49, 48, 47,
    6, 7, 8,
    61, 62, 63, 65, 60, 59, 64,
    54, 4, 55, 56, 58, 53, 52, 57,
    67, 68,
)

# Style 4: LC1 (31 LEDs, 1 zone) — also base for HR10 (style 13)
_REMAP_STYLE_4: tuple[int, ...] = (
    2, 1, 33, 34, 35, 37, 32, 31, 6,
    36, 25, 26, 27, 29, 24, 23, 28,
    18, 19, 20, 22, 17, 16, 21,
    11, 12, 13, 15, 10, 9, 14,
)

# Style 5: LF8 (93 LEDs, 2 zones) — Phantom Spirit 120 Digital Snow / PM=49
# C# SendHidVal reorders array8 (logical) → array9 (wire) for 92 LEDs;
# LEDC13 (idx 92) is unused by C# but included for correct packet length.
_REMAP_STYLE_5: tuple[int, ...] = (
    6, 86, 87, 88, 90, 85, 84, 89,       # BFB, seg12 (C D E G B A F)
    79, 80, 81, 83, 78, 77, 82,           # seg11 (C D E G B A F)
    91, 5,                                 # LEDB13, MHz
    72, 73, 74, 76, 71, 70, 75,           # seg10 (C D E G B A F)
    65, 66, 67, 69, 64, 63, 68,           # seg9
    58, 59, 60, 62, 57, 56, 61,           # seg8
    51, 52, 53, 55, 50, 49, 54,           # seg7
    11, 10, 9, 13, 12, 7, 0, 8,           # seg1 (E D C G F A) + Cpu1 + B
    18, 17, 16, 20, 19, 14, 1, 15,        # seg2 (E D C G F A) + Gpu1 + B
    25, 24, 23, 27, 26, 21, 22,           # seg3 (E D C G F A B)
    3, 2,                                  # HSD, SSD
    32, 31, 30, 34, 33, 28, 29,           # seg4
    39, 38, 37, 41, 40, 35, 36,           # seg5
    46, 45, 44, 48, 47, 42, 43,           # seg6
    4, 92,                                 # WATT, LEDC13 (unused/padding)
)

# Style 6: LF12 (141 wire positions, 124 logical LEDs)
# Decoration LEDs (ZhuangShi) are DUPLICATED on the wire — each physical pair
# gets the same logical LED color.  This is hardware design, not a bug.
_REMAP_STYLE_6: tuple[int, ...] = (
    # decoration ring top (ZS27-31 forward, then ZS30-27 mirrored)
    119, 120, 121, 122, 123,
    122, 121, 120, 119,
    # BFB (duplicated)
    6, 6,
    # seg12 (C D E G B A F)
    86, 87, 88, 90, 85, 84, 89,
    # seg11 (C D E G B A F)
    79, 80, 81, 83, 78, 77, 82,
    # LEDC13, LEDB13, MHz
    92, 91, 5,
    # seg10 (C D E G B A F)
    72, 73, 74, 76, 71, 70, 75,
    # seg9
    65, 66, 67, 69, 64, 63, 68,
    # seg8
    58, 59, 60, 62, 57, 56, 61,
    # seg7
    51, 52, 53, 55, 50, 49, 54,
    # decoration LEDs ZS13-ZS26 (straight sequence)
    105, 106, 107, 108, 109, 110, 111, 112, 113, 114, 115, 116, 117, 118,
    # WATT
    4,
    # seg6 (C D E G B A F)
    44, 45, 46, 48, 43, 42, 47,
    # seg5
    37, 38, 39, 41, 36, 35, 40,
    # seg4
    30, 31, 32, 34, 29, 28, 33,
    # SSD, HSD
    2, 3,
    # seg3 (C D E G B A) + Gpu1 + F
    23, 24, 25, 27, 22, 21, 1, 26,
    # seg2 (C D E G B A F)
    16, 17, 18, 20, 15, 14, 19,
    # seg1 (C D E G B A F)
    9, 10, 11, 13, 8, 7, 12,
    # Cpu1
    0,
    # decoration LEDs ZS1-ZS12 (each duplicated to 2 wire positions)
    93, 93, 94, 94, 95, 95, 96, 96, 97, 97, 98, 98,
    99, 99, 100, 100, 101, 101, 102, 102, 103, 103, 104, 104,
)

# Style 7: LF10 (146 wire positions, 116 logical LEDs, 13-segment digits A-M)
# Many entries are duplicated on the wire (physical LED pairs).
_REMAP_STYLE_7: tuple[int, ...] = (
    # decoration ring (ZS32..27 descending, then ZS27..32 ascending = mirrored)
    115, 114, 113, 112, 111, 110,
    110, 111, 112, 113, 114, 115,
    # decoration ZS20..1 descending
    103, 102, 101, 100, 99, 98, 97, 96, 95, 94, 93, 92, 91, 90, 89, 88, 87, 86, 85, 84,
    # decoration ZS21..26
    104, 105, 106, 107, 108, 109,
    # Cpu1 (duplicated)
    0, 0,
    # digit 1: L1 A1 B1(dup) C1 D1 E1 M1(dup) K1 J1 I1 H1(dup) G1 F1
    17, 6, 7, 7, 8, 9, 10, 18, 18, 16, 15, 14, 13, 13, 12, 11,
    # digit 2: J2 I2 H2(dup) G2 F2 E2 M2(dup) K2 L2 A2 B2(dup) C2 D2
    28, 27, 26, 26, 25, 24, 23, 31, 31, 29, 30, 19, 20, 20, 21, 22,
    # digit 3: L3 A3 B3(dup) C3 D3 E3 M3(dup) K3 J3 I3 H3(dup) G3 F3
    43, 32, 33, 33, 34, 35, 36, 44, 44, 42, 41, 40, 39, 39, 38, 37,
    # HSD(dup) SSD(dup) Gpu1(dup)
    2, 2, 1, 1, 3, 3,
    # digit 4: L4 A4 B4(dup) C4 D4 E4 M4(dup) K4 J4 I4 H4(dup) G4 F4
    56, 45, 46, 46, 47, 48, 49, 57, 57, 55, 54, 53, 52, 52, 51, 50,
    # digit 5: J5 I5 H5(dup) G5 F5 E5 M5(dup) K5 L5 A5 B5(dup) C5 D5
    67, 66, 65, 65, 64, 63, 62, 70, 70, 68, 69, 58, 59, 59, 60, 61,
    # digit 6: L6 A6 B6(dup) C6 D6 E6 M6(dup) K6 J6 I6 H6(dup) G6 F6
    82, 71, 72, 72, 73, 74, 75, 83, 83, 81, 80, 79, 78, 78, 77, 76,
    # HSD1(dup) SSD1(dup)
    5, 5, 4, 4,
)

# Style 9: LC2 clock (63 wire positions, 61 logical LEDs)
# Riqi (date indicator) is triplicated on the wire.
_REMAP_STYLE_9: tuple[int, ...] = (
    # decoration (ZS7..1 descending)
    60, 59, 58, 57, 56, 55, 54,
    # colon LEDs
    53, 52,
    # seg5 (F A B G E D C)
    36, 31, 32, 37, 35, 34, 33,
    # Riqi (date indicator, triplicated)
    2, 2, 2,
    # seg6 (F A B G E D C)
    43, 38, 39, 44, 42, 41, 40,
    # seg7 (F A B G E D C)
    50, 45, 46, 51, 49, 48, 47,
    # seg4 (C D E G B A F)
    26, 27, 28, 30, 25, 24, 29,
    # seg3 (C D E G B A F)
    19, 20, 21, 23, 18, 17, 22,
    # Shijian1, Shijian2 (time indicators)
    0, 1,
    # seg2 (C D E G B A F)
    12, 13, 14, 16, 11, 10, 15,
    # seg1 (C D E G B A F)
    5, 6, 7, 9, 4, 3, 8,
)

# Style 10: LF11 (38 wire positions, 38 logical LEDs)
_REMAP_STYLE_10: tuple[int, ...] = (
    # GNo (=MHz), MTNo (=BFB)
    2, 1,
    # seg5 (C D E G B A) + SSD + F
    33, 34, 35, 37, 32, 31, 0, 36,
    # seg4 (C D E G B A F)
    26, 27, 28, 30, 25, 24, 29,
    # seg3 (C D E G B A F)
    19, 20, 21, 23, 18, 17, 22,
    # seg2 (C D E G B A F)
    12, 13, 14, 16, 11, 10, 15,
    # seg1 (C D E G B A F)
    5, 6, 7, 9, 4, 3, 8,
)

# Style → remap table.  Styles not listed use identity mapping (no remap).
# NOTE: Styles 8 (CZ1) and 11 (LF15) use dual-source color arrays
# (ledVal8[] / ledValLF15[]) that cannot be expressed as simple index remaps.
# Style 12 (LF13) uses identity mapping from ledValLF13[].
LED_REMAP_TABLES: dict[int, tuple[int, ...]] = {
    2: _REMAP_STYLE_2,   # PA120_DIGITAL (84 LEDs)
    3: _REMAP_STYLE_3,   # AK120_DIGITAL (64 LEDs)
    4: _REMAP_STYLE_4,   # LC1 (31 LEDs)
    5: _REMAP_STYLE_5,   # LF8 / Phantom Spirit 120 Digital Snow (93 LEDs)
    6: _REMAP_STYLE_6,   # LF12 (141 LEDs, decoration duplicated)
    7: _REMAP_STYLE_7,   # LF10 (146 LEDs, 13-segment, duplicated)
    9: _REMAP_STYLE_9,   # LC2 clock (63 LEDs, Riqi triplicated)
    10: _REMAP_STYLE_10,  # LF11 (38 LEDs)
    13: _REMAP_STYLE_4,  # HR10 shares LC1 layout
}


# Default-off LED indices per style (from C# isOnN arrays in UCScreenLED.cs).
# Styles not listed here default to all-on.
LED_DEFAULT_OFF: dict[int, frozenset[int]] = {
    1: frozenset({4, 5, 7, 8}),            # HR10 preview: only index 6 on of 6-8
    2: frozenset({5, 8}),                   # PA120
    3: frozenset({3, 5}),                   # AK120
    4: frozenset({1, 2, 25, 26, 30}),       # LC1
    5: frozenset({1, 3}),                   # LF8
    6: frozenset({1, 3}),                   # LF12
    7: frozenset({2, 5}),                   # LF10
    8: frozenset({1, 2, 3}),                # CZ1
    10: frozenset({1, 2, 32, 33, 37}),      # LF11
    11: frozenset({1, 3}),                  # LF15
    13: frozenset({1, 2, 25, 26, 30}),      # HR10 shares LC1 layout
}


def remap_led_colors(
    colors: List[Tuple[int, int, int]],
    style_id: int,
) -> List[Tuple[int, int, int]]:
    """Remap LED colors from logical to physical wire order.

    Each LED device style has a hardware-specific mapping from logical LED
    indices (used by the GUI) to physical wire positions (sent to device).
    """
    table = LED_REMAP_TABLES.get(style_id)
    if table is None:
        return colors
    black = (0, 0, 0)
    return [colors[idx] if idx < len(colors) else black for idx in table]


# =============================================================================
# DC File Format DTOs (config1.dc overlay configuration)
# =============================================================================

@dataclass
class FontConfig:
    """Font configuration from .dc file."""
    name: str
    size: float
    style: int      # 0=Regular, 1=Bold, 2=Italic
    unit: int       # GraphicsUnit
    charset: int
    color_argb: tuple  # (alpha, red, green, blue)


@dataclass
class ElementConfig:
    """Element position and font config."""
    x: int
    y: int
    font: Optional[FontConfig] = None
    enabled: bool = True


@dataclass
class DisplayElement:
    """
    Display element from UCXiTongXianShiSub (time, date, weekday, hardware info, custom text).

    myMode values:
        0 = Hardware info (CPU/GPU metrics)
        1 = Time
        2 = Weekday (SUN, MON, TUE, etc.)
        3 = Date
        4 = Custom text

    myModeSub values (format variants):
        For mode 1 (Time):
            0 = HH:mm (24-hour)
            1 = hh:mm AM/PM (12-hour)
            2 = HH:mm (same as 0)
        For mode 3 (Date):
            0 = yyyy/MM/dd
            1 = yyyy/MM/dd (same as 0)
            2 = dd/MM/yyyy
            3 = MM/dd
            4 = dd/MM
    """
    mode: int           # Display type (0=hardware, 1=time, 2=weekday, 3=date, 4=custom)
    mode_sub: int       # Format variant
    x: int              # X position
    y: int              # Y position
    main_count: int = 0     # For hardware info - sensor category
    sub_count: int = 0      # For hardware info - specific sensor
    font_name: str = "Microsoft YaHei"
    font_size: float = 24.0
    font_style: int = 0  # 0=Regular, 1=Bold, 2=Italic
    font_unit: int = 3   # GraphicsUnit.Point
    font_charset: int = 134  # GB2312 (Windows default: new Font("微软雅黑", 36f, 0, 3, 134))
    color_argb: tuple = (255, 255, 255, 255)  # ARGB
    text: str = ""      # Custom text content

    @property
    def mode_name(self) -> str:
        """Get human-readable mode name."""
        try:
            return OverlayMode(self.mode).name.lower()
        except ValueError:
            return f'unknown_{self.mode}'

    @property
    def color_hex(self) -> str:
        """Get color as hex string."""
        _, r, g, b = self.color_argb
        return f"#{r:02x}{g:02x}{b:02x}"


# =============================================================================
# Overlay element types — UI/grid-level representation.
# DisplayElement is the binary DC format; OverlayElementConfig is the
# grid editor's typed representation (replaces raw dicts in _configs).
# =============================================================================

class OverlayMode(IntEnum):
    """Display element mode — matches Windows myMode values 0..4."""
    HARDWARE = 0
    TIME = 1
    WEEKDAY = 2
    DATE = 3
    CUSTOM = 4


@dataclass
class OverlayElementConfig:
    """Overlay grid element config — UI-level representation.

    Replaces the untyped dict from _default_element_config().
    Used by OverlayGridPanel._configs and OverlayElementWidget.config.
    """
    mode: OverlayMode = OverlayMode.TIME
    mode_sub: int = 0
    x: int = 100
    y: int = 100
    main_count: int = 0
    sub_count: int = 1
    color: str = '#FFFFFF'
    font_name: str = 'Microsoft YaHei'
    font_size: int = 36
    font_style: int = 0
    text: str = ''


# =============================================================================
# HardwareMetrics DTO — typed container for all system sensor readings.
# Replaces Dict[str, float] with magic string keys. Consumers use attribute
# access (metrics.cpu_temp) instead of dict lookups (metrics['cpu_temp']).
# Pyright catches typos at lint time. Fields default to 0.0.
# =============================================================================

@dataclass
class HardwareMetrics:
    """Typed DTO for all system sensor readings. Updated once/second by polling."""
    # CPU
    cpu_temp: float = 0.0
    cpu_percent: float = 0.0
    cpu_freq: float = 0.0
    cpu_power: float = 0.0
    # GPU
    gpu_temp: float = 0.0
    gpu_usage: float = 0.0
    gpu_clock: float = 0.0
    gpu_power: float = 0.0
    # Memory
    mem_temp: float = 0.0
    mem_percent: float = 0.0
    mem_clock: float = 0.0
    mem_available: float = 0.0
    # Disk
    disk_temp: float = 0.0
    disk_activity: float = 0.0
    disk_read: float = 0.0
    disk_write: float = 0.0
    # Network
    net_up: float = 0.0
    net_down: float = 0.0
    net_total_up: float = 0.0
    net_total_down: float = 0.0
    # Fan
    fan_cpu: float = 0.0
    fan_gpu: float = 0.0
    fan_ssd: float = 0.0
    fan_sys2: float = 0.0
    # Date/Time
    date_year: float = 0.0
    date_month: float = 0.0
    date_day: float = 0.0
    time_hour: float = 0.0
    time_minute: float = 0.0
    time_second: float = 0.0
    day_of_week: float = 0.0
    date: float = 0.0
    time: float = 0.0
    weekday: float = 0.0


# Hardware sensor ↔ metric name mapping (single source of truth).
# Maps DC file (main_count, sub_count) → HardwareMetrics attribute name.
# Used by dc_parser, dc_writer, dc_config, uc_sensor_picker.
HARDWARE_METRICS: Dict[Tuple[int, int], str] = {
    # CPU (main_count=0)
    (0, 1): 'cpu_temp',
    (0, 2): 'cpu_percent',
    (0, 3): 'cpu_freq',
    (0, 4): 'cpu_power',
    # GPU (main_count=1)
    (1, 1): 'gpu_temp',
    (1, 2): 'gpu_usage',
    (1, 3): 'gpu_clock',
    (1, 4): 'gpu_power',
    # MEM (main_count=2)
    (2, 1): 'mem_percent',
    (2, 2): 'mem_clock',
    (2, 3): 'mem_available',
    (2, 4): 'mem_temp',
    # HDD (main_count=3)
    (3, 1): 'disk_read',
    (3, 2): 'disk_write',
    (3, 3): 'disk_activity',
    (3, 4): 'disk_temp',
    # NET (main_count=4)
    (4, 1): 'net_down',
    (4, 2): 'net_up',
    (4, 3): 'net_total_down',
    (4, 4): 'net_total_up',
    # FAN (main_count=5)
    (5, 1): 'fan_cpu',
    (5, 2): 'fan_gpu',
    (5, 3): 'fan_ssd',
    (5, 4): 'fan_sys2',
}

METRIC_TO_IDS: Dict[str, Tuple[int, int]] = {v: k for k, v in HARDWARE_METRICS.items()}


# =============================================================================
# Theme Config DTOs (dc_writer save/export format)
# =============================================================================

@dataclass
class ThemeConfig:
    """Complete theme configuration for saving."""
    # Display elements (UCXiTongXianShiSubArray)
    elements: List[DisplayElement] = field(default_factory=list)

    # System info global enable
    system_info_enabled: bool = True

    # Display options
    background_display: bool = True    # myBjxs
    transparent_display: bool = False  # myTpxs
    rotation: int = 0                  # directionB (0/90/180/270)
    ui_mode: int = 0                   # myUIMode
    display_mode: int = 0              # myMode

    # Overlay settings
    overlay_enabled: bool = True       # myYcbk
    overlay_x: int = 0                 # JpX
    overlay_y: int = 0                 # JpY
    overlay_w: int = 320               # JpW
    overlay_h: int = 320               # JpH

    # Mask settings
    mask_enabled: bool = False         # myMbxs
    mask_x: int = 0                    # XvalMB
    mask_y: int = 0                    # YvalMB


@dataclass
class CarouselConfig:
    """Carousel/slideshow configuration."""
    current_theme: int = 0             # myTheme - index of current theme
    enabled: bool = False              # isLunbo
    interval_seconds: int = 3          # myLunBoTimer (minimum 3)
    count: int = 0                     # lunBoCount
    theme_indices: List[int] = field(default_factory=lambda: [-1, -1, -1, -1, -1, -1])
    lcd_rotation: int = 1              # myLddVal (1-3): split mode style, NOT rotation


# =============================================================================
# Sensor DTOs
# =============================================================================

@dataclass
class SensorInfo:
    """Describes a single hardware sensor."""
    id: str             # Unique ID: "hwmon:coretemp:temp1"
    name: str           # Human-readable: "CPU Package"
    category: str       # "temperature", "fan", "clock", "usage", "power", "voltage", "other"
    unit: str           # "°C", "RPM", "MHz", "%", "W", "V", "MB/s", "KB/s", "MB"
    source: str         # "hwmon", "nvidia", "psutil", "rapl", "computed"


# =============================================================================
# Domain Constants (FBL/resolution mapping, display formats)
# =============================================================================

# Time formats matching Windows TRCC (UCXiTongXianShiSub.cs)
TIME_FORMATS: Dict[int, str] = {
    0: "%H:%M",       # 24-hour (14:58)
    1: "%-I:%M %p",   # 12-hour with AM/PM, no leading zero (2:58 PM)
    2: "%H:%M",       # 24-hour (same as mode 0 in Windows)
}

# Date formats matching Windows TRCC
DATE_FORMATS: Dict[int, str] = {
    0: "%Y/%m/%d",    # 2026/01/30
    1: "%Y/%m/%d",    # 2026/01/30 (same as mode 0 in Windows)
    2: "%d/%m/%Y",    # 30/01/2026
    3: "%m/%d",       # 01/30
    4: "%d/%m",       # 30/01
}

# Weekday names matching Windows TRCC (English)
# Python weekday(): Monday=0, Sunday=6
WEEKDAYS = ["MON", "TUE", "WED", "THU", "FRI", "SAT", "SUN"]

# Chinese weekday names (for Language == 1)
WEEKDAYS_CN = ["星期一", "星期二", "星期三", "星期四", "星期五", "星期六", "星期日"]

# System locale → Windows asset suffix (from FormLED.cs / UCAbout.cs)
# C# uses arbitrary single-char suffixes: 'e'=Russian, 'r'=Japanese, 'x'=Spanish
LOCALE_TO_LANG: dict[str, str] = {
    'zh_CN': '',     # Chinese Simplified = default (no suffix)
    'zh_TW': 'tc',   # Traditional Chinese
    'en': 'en',      # English
    'de': 'd',       # German
    'es': 'x',       # Spanish
    'fr': 'f',       # French
    'pt': 'p',       # Portuguese
    'ru': 'e',       # Russian
    'ja': 'r',       # Japanese
}

# FBL → Resolution mapping (from FormCZTV.cs lines 811-821)
# FBL (Frame Buffer Layout) byte determines LCD resolution.
FBL_TO_RESOLUTION: dict[int, tuple[int, int]] = {
    36:  (240, 240),
    37:  (240, 240),
    50:  (320, 240),
    51:  (320, 240),
    54:  (360, 360),
    64:  (640, 480),
    72:  (480, 480),
    100: (320, 320),
    101: (320, 320),
    102: (320, 320),
    114: (1600, 720),
    128: (1280, 480),
    192: (1920, 462),
    224: (854, 480),
}

# Reverse lookup: resolution → PM/FBL (first match wins)
RESOLUTION_TO_PM: dict[tuple[int, int], int] = {
    res: fbl for fbl, res in FBL_TO_RESOLUTION.items()
    if fbl not in (37, 101, 102, 224)
}

# PM byte → FBL byte for Type 2 devices where PM ≠ FBL.
# (FormCZTV.cs lines 682-821)
# For all other PM values, PM=FBL (same convention as SCSI poll bytes).
_PM_TO_FBL_OVERRIDES: dict[int, int] = {
    5:   50,    # 240x320
    7:   64,    # 640x480
    9:   224,   # 854x480
    10:  224,   # 960x540 (special: actual res depends on PM)
    11:  224,   # 854x480
    12:  224,   # 800x480 (special)
    32:  100,   # 320x320
    64:  114,   # 1600x720
    65:  192,   # 1920x462
}


# FBL 224 is shared by 3 resolutions — PM byte disambiguates
_FBL_224_BY_PM: dict[int, tuple[int, int]] = {
    10: (960, 540),
    12: (800, 480),
}

# PM+SUB compound keys where sub byte changes the FBL mapping
_PM_SUB_TO_FBL: dict[tuple[int, int], int] = {
    (1, 48): 114,   # 1600x720
    (1, 49): 192,   # 1920x462
}


def fbl_to_resolution(fbl: int, pm: int = 0) -> tuple[int, int]:
    """Map FBL byte to (width, height).

    Used by all protocols: SCSI (poll byte[0] = FBL directly),
    HID (PM → pm_to_fbl → FBL), and Bulk (PM → pm_to_fbl → FBL).

    For FBL 224, the PM byte disambiguates the actual resolution.
    Returns (320, 320) as default if FBL is unknown.
    """
    if fbl == 224:
        return _FBL_224_BY_PM.get(pm, (854, 480))
    return FBL_TO_RESOLUTION.get(fbl, (320, 320))


def pm_to_fbl(pm: int, sub: int = 0) -> int:
    """Map PM byte to FBL byte.

    Default: PM=FBL (same convention as SCSI poll bytes).
    Only overrides for the few PM values where PM ≠ FBL.
    Compound key (PM, SUB) checked first for sub-dependent mappings.
    """
    if (pm, sub) in _PM_SUB_TO_FBL:
        return _PM_SUB_TO_FBL[(pm, sub)]
    return _PM_TO_FBL_OVERRIDES.get(pm, pm)


# Split mode overlay (灵动岛 / Dynamic Island) for 1600x720 widescreen devices.
# C# UCScreenImage.cs: buttonLDD cycles myLddVal 1→2→3→1, overlay selected by
# (style, directionB). Key: (myLddVal, rotation_degrees) → asset filename.
SPLIT_OVERLAY_MAP: dict[tuple[int, int], str] = {
    # Style A (myLddVal=1)
    (1, 0):   'P灵动岛.png',
    (1, 90):  'P灵动岛90.png',
    (1, 180): 'P灵动岛180.png',
    (1, 270): 'P灵动岛270.png',
    # Style B (myLddVal=2, default)
    (2, 0):   'P灵动岛a.png',
    (2, 90):  'P灵动岛a90.png',
    (2, 180): 'P灵动岛a180.png',
    (2, 270): 'P灵动岛a270.png',
    # Style C (myLddVal=3)
    (3, 0):   'P灵动岛b.png',
    (3, 90):  'P灵动岛b90.png',
    (3, 180): 'P灵动岛b180.png',
    (3, 270): 'P灵动岛b270.png',
}

# Widescreen resolutions that support split mode (灵动岛).
# C#: myDeviceMode==2 && (pm==64 || (pm==1 && pmSub==48))
SPLIT_MODE_RESOLUTIONS: set[tuple[int, int]] = {(1600, 720)}


# =============================================================================
# Device Button Image Map (from UCDevice.cs ADDUserButton)
# =============================================================================

# Unified device → button image map.
# Outer key: HID PM byte (0-255) or SCSI VID (>255).
# Inner key: HID SUB byte or SCSI PID.  None = default when sub/pid not matched.
DEVICE_BUTTON_IMAGE: dict[int, dict[Optional[int], str]] = {
    # -- HID Vision/RGB devices (case 257, PM + SUB) --
    1:   {0: 'A1GRAND VISION', 1: 'A1GRAND VISION',
          48: 'A1LM22', 49: 'A1LF14', None: 'A1GRAND VISION'},
    3:   {None: 'A1CORE VISION'},
    4:   {1: 'A1HYPER VISION', 2: 'A1RP130 VISION', 3: 'A1LM16SE'},
    5:   {None: 'A1Mjolnir VISION'},
    6:   {1: 'FROZEN_WARFRAME_Ultra', 2: 'A1FROZEN VISION V2'},
    7:   {1: 'A1Stream Vision', 2: 'A1Mjolnir VISION PRO'},
    9:   {None: 'A1LC2JD'},
    10:  {5: 'A1LF16', 6: 'A1LF18', None: 'A1LC3'},
    11:  {None: 'A1LF19'},
    12:  {None: 'A1LF167'},
    # -- HID LCD devices (case 2 + case 257 merged, PM + SUB) --
    32:  {0: 'A1ELITE VISION', 1: 'A1FROZEN WARFRAME PRO',
          None: 'A1ELITE VISION'},
    36:  {None: 'A1AS120 VISION'},
    50:  {None: 'A1FROZEN WARFRAME'},
    51:  {None: 'A1FROZEN WARFRAME'},
    52:  {None: 'A1BA120 VISION'},
    53:  {None: 'A1BA120 VISION'},
    54:  {None: 'A1LC5'},
    58:  {0: 'A1FROZEN WARFRAME SE', None: 'A1LM26'},
    64:  {0: 'A1FROZEN WARFRAME PRO', 1: 'A1LM22', 2: 'A1LM27'},
    65:  {0: 'A1ELITE VISION', 1: 'A1LF14'},
    100: {0: 'A1FROZEN WARFRAME PRO', 1: 'A1LM22',
          None: 'A1FROZEN WARFRAME PRO'},
    101: {0: 'A1ELITE VISION', 1: 'A1LF14', None: 'A1ELITE VISION'},
    128: {None: 'A1LM24'},
    # -- SCSI devices (VID → {PID: image}) --
    0x87CD: {0x70DB: 'A1CZTV', None: 'A1CZTV'},
    0x87AD: {0x70DB: 'A1GRAND VISION', None: 'A1GRAND VISION'},
    0x0402: {0x3922: 'A1FROZEN WARFRAME', None: 'A1FROZEN WARFRAME'},
    0x0416: {0x5406: 'A1CZTV', None: 'A1CZTV'},
}

# Backward-compat alias
PM_TO_BUTTON_IMAGE = DEVICE_BUTTON_IMAGE


def get_button_image(key: int, sub: int = 0) -> Optional[str]:
    """Resolve device button image from PM+SUB (HID) or VID+PID (SCSI)."""
    sub_map = DEVICE_BUTTON_IMAGE.get(key)
    if sub_map is None:
        return None
    if sub in sub_map:
        return sub_map[sub]
    return sub_map.get(None)


# =============================================================================
# Protocol / Device Type Display Names
# =============================================================================

PROTOCOL_NAMES: dict[str, str] = {
    "scsi": "SCSI (sg_raw)",
    "hid": "HID (USB bulk)",
    "led": "LED (HID 64-byte)",
    "bulk": "USB Bulk (USBLCDNew)",
}

DEVICE_TYPE_NAMES: dict[int, str] = {
    1: "SCSI RGB565",
    2: "HID Type 2 (H)",
    3: "HID Type 3 (ALi)",
    4: "Raw USB Bulk LCD",
}

LED_DEVICE_TYPE_NAME: str = "RGB LED Controller"


# =============================================================================
# Sensor Dashboard Category Display Mappings
# =============================================================================

# Category ID → background image name
CATEGORY_IMAGES: dict[int, str] = {
    0: 'A自定义.png',
    1: 'Acpu.png',
    2: 'Agpu.png',
    3: 'Adram.png',
    4: 'Ahdd.png',
    5: 'Anet.png',
    6: 'Afan.png',
}

# Category ID → value text color
CATEGORY_COLORS: dict[int, str] = {
    0: '#9375FF',     # Custom: Purple
    1: '#32C5FF',     # CPU: Cyan
    2: '#44D7B6',     # GPU: Teal
    3: '#6DD401',     # Memory: Lime
    4: '#F7B501',     # HDD: Orange
    5: '#FA6401',     # Network: Red-orange
    6: '#E02020',     # Fan: Red
}

