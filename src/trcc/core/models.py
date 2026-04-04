"""
TRCC Models - Pure data classes with no GUI dependencies.

These models can be used by any GUI framework (Tkinter, PyQt6, etc.)
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum, IntEnum, auto
from pathlib import Path
from typing import Any, Dict, List, NamedTuple, Optional, Tuple

# =============================================================================
# Temperature conversion — single source of truth
# =============================================================================


def celsius_to_fahrenheit(celsius: float) -> float:
    """Convert Celsius to Fahrenheit. C#: value * 9 / 5 + 32."""
    return celsius * 9 / 5 + 32


def parse_hex_color(hex_color: str) -> Optional[Tuple[int, int, int]]:
    """Parse '#RRGGBB' or 'RRGGBB' → (r, g, b), or None on invalid input."""
    hex_color = hex_color.lstrip('#')
    if len(hex_color) != 6:
        return None
    try:
        return (int(hex_color[0:2], 16),
                int(hex_color[2:4], 16),
                int(hex_color[4:6], 16))
    except ValueError:
        return None


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
    """Item in the masks browser (UCThemeMask)."""
    path: Optional[str] = None
    preview: Optional[str] = None
    is_custom: bool = False  # User-uploaded mask (enables delete in context menu)


@dataclass
class MaskInfo:
    """Mask overlay info returned by ThemeService.discover_masks().

    Pure domain object — adapters (GUI, API) convert to their own types.
    """
    name: str
    path: Optional[Path] = None
    preview_path: Optional[Path] = None
    is_custom: bool = False  # User-created vs cloud-downloaded


# =============================================================================
# Theme Model
# =============================================================================

@dataclass
class ThemeData:
    """Bundle returned after loading a theme — everything needed to display it."""
    background: Any = None               # native surface (QImage)
    animation_path: Optional[Path] = None  # video/zt path
    is_animated: bool = False
    mask: Any = None                     # native surface (QImage)
    mask_position: Optional[Tuple[int, int]] = None
    mask_source_dir: Optional[Path] = None


class ThemeDir:
    """Standard theme directory layout — pure domain value object.

    Path-construction properties only. Zero I/O, zero logic.
    Filesystem operations (resolve_theme_dir, has_themes) live in core/paths.py.

    Usage::

        td = ThemeDir(some_path)
        td.bg          # Path to 00.png
        td.mask        # Path to 01.png
        td.dc          # Path to config1.dc
    """

    __slots__ = ('path',)

    def __init__(self, path: str | os.PathLike):
        self.path = Path(path)

    @property
    def bg(self) -> Path:
        """Background image (00.png)."""
        return self.path / '00.png'

    @property
    def mask(self) -> Path:
        """Mask overlay image (01.png)."""
        return self.path / '01.png'

    @property
    def preview(self) -> Path:
        """Thumbnail preview (Theme.png)."""
        return self.path / 'Theme.png'

    @property
    def dc(self) -> Path:
        """Binary overlay config (config1.dc)."""
        return self.path / 'config1.dc'

    @property
    def json(self) -> Path:
        """JSON config for custom themes (config.json)."""
        return self.path / 'config.json'

    @property
    def zt(self) -> Path:
        """Theme.zt animation file."""
        return self.path / 'Theme.zt'

    def __truediv__(self, other: str) -> Path:
        """Allow ThemeDir / 'subpath' to return a Path."""
        return self.path / other

    def __str__(self) -> str:
        return str(self.path)


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
class DeviceEntry:
    """Registry entry describing a known USB device's capabilities."""
    vendor: str
    product: str
    implementation: str
    model: str = "CZTV"
    button_image: str = "A1CZTV"
    protocol: str = "scsi"
    device_type: int = 1  # 1=SCSI, 2=HID Type 2, 3=HID Type 3, 4=Raw USB Bulk
    fbl: int = 100         # FBL code (resolution identifier) — used by Windows SCSI poll fallback


@dataclass
class DetectedDevice:
    """Detected USB/SCSI device."""
    vid: int  # Vendor ID
    pid: int  # Product ID
    vendor_name: str
    product_name: str
    usb_path: str  # e.g., "2-1.4"
    scsi_device: Optional[str] = None  # e.g., "/dev/sg0"
    implementation: str = "generic"  # Device-specific implementation
    model: str = "CZTV"  # Device model for button image lookup
    button_image: str = "A1CZTV"  # Button image prefix (without .png)
    protocol: str = "scsi"  # "scsi" or "hid"
    device_type: int = 1  # 1=SCSI, 2=HID Type 2, 3=HID Type 3, 4=Bulk, 5=LY

    @property
    def path(self) -> str:
        """Device path for protocol factories (SCSI → /dev/sgN, else USB path)."""
        return self.scsi_device or self.usb_path


# =========================================================================
# Device registries — single source of truth for all known USB devices
# =========================================================================

SCSI_DEVICES: dict[tuple[int, int], DeviceEntry] = {
    (0x87CD, 0x70DB): DeviceEntry(
        vendor="Thermalright", product="LCD Display",
        implementation="thermalright_lcd_v1",
    ),
    (0x0416, 0x5406): DeviceEntry(
        vendor="Winbond", product="LCD Display",
        implementation="ali_corp_lcd_v1",
    ),
    # Shared by multiple products (Frozen Warframe SE/PRO/Ultra, Elite Vision 360,
    # AS120, BA120, etc). Real product resolved after handshake via PM→DEVICE_BUTTON_IMAGE.
    (0x0402, 0x3922): DeviceEntry(
        vendor="Thermalright", product="LCD Display",
        model="FROZEN_WARFRAME", button_image="A1CZTV",
        implementation="ali_corp_lcd_v1",
    ),
}

HID_LCD_DEVICES: dict[tuple[int, int], DeviceEntry] = {
    (0x0416, 0x5302): DeviceEntry(
        vendor="Winbond", product="USBDISPLAY",
        implementation="hid_type2", protocol="hid", device_type=2,
    ),
    (0x0418, 0x5303): DeviceEntry(
        vendor="ALi Corp", product="LCD Display",
        implementation="hid_type3", protocol="hid", device_type=3,
    ),
    (0x0418, 0x5304): DeviceEntry(
        vendor="ALi Corp", product="LCD Display",
        implementation="hid_type3", protocol="hid", device_type=3,
    ),
}

LED_DEVICES: dict[tuple[int, int], DeviceEntry] = {
    (0x0416, 0x8001): DeviceEntry(
        vendor="Winbond", product="LED Controller",
        model="LED_DIGITAL", implementation="hid_led",
        protocol="led", device_type=1,
    ),
}

BULK_DEVICES: dict[tuple[int, int], DeviceEntry] = {
    # NOTE: 87AD:70DB is raw USB bulk (USBLCDNew protocol), not SCSI.
    (0x87AD, 0x70DB): DeviceEntry(
        vendor="ChiZhu Tech", product="GrandVision 360 AIO",
        model="GRAND_VISION", button_image="A1GRAND VISION",
        implementation="bulk_usblcdnew",
        protocol="bulk", device_type=4,
    ),
}

LY_DEVICES: dict[tuple[int, int], DeviceEntry] = {
    (0x0416, 0x5408): DeviceEntry(
        vendor="Winbond", product="Trofeo Vision 9.16 LCD",
        implementation="ly_bulk", protocol="ly", device_type=5,
    ),
    (0x0416, 0x5409): DeviceEntry(
        vendor="Winbond", product="Trofeo Vision 9.16 LCD",
        implementation="ly_bulk", protocol="ly", device_type=5,
    ),
}

ALL_DEVICES: dict[tuple[int, int], DeviceEntry] = {
    **SCSI_DEVICES, **HID_LCD_DEVICES, **LED_DEVICES, **BULK_DEVICES, **LY_DEVICES,
}


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
    button_image: str = "A1CZTV"    # Sidebar image prefix (resolved from detection or handshake PM+SUB)
    sub_byte: int = 0               # Raw SUB from handshake (for encode rotation lookup)
    led_style_id: Optional[int] = None  # LED style from probe (avoids name-based lookup)
    led_style_sub: int = 0              # LED style sub-variant (C# nowLedStyleSub)

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
            led_style_sub=d.get('led_style_sub', 0),
        )

    @property
    def resolution_str(self) -> str:
        """Get resolution as string (e.g., '320x320')."""
        return f"{self.resolution[0]}x{self.resolution[1]}"

    @property
    def profile(self) -> 'DeviceProfile':
        """Device profile derived from FBL code."""
        return get_profile(self.fbl_code) if self.fbl_code is not None else _DEFAULT_PROFILE

    @property
    def use_jpeg(self) -> bool:
        """Whether this device uses JPEG encoding.

        Bulk/LY: JPEG unless FBL is RGB565-only (e.g. FBL 100).
        HID: JPEG if profile says so. SCSI: always RGB565.
        """
        if self.protocol in ('bulk', 'ly'):
            return self.fbl_code not in BULK_RGB565_FBLS
        return self.profile.jpeg if self.protocol == 'hid' else False

    @property
    def encoding_params(self) -> tuple:
        """Encoding params for ImageService.encode_for_device().

        Returns (protocol, resolution, fbl, use_jpeg).
        """
        res = self.resolution
        fbl = self.fbl_code
        if res == (0, 0):
            res = self.profile.resolution
        return (self.protocol, res, fbl, self.use_jpeg)


@dataclass
class HandshakeResult:
    """Common output from any device handshake.

    Every protocol (SCSI, HID, LED, Bulk) produces at least these fields.
    Protocol-specific subclasses (HidHandshakeInfo, LedHandshakeInfo) add extras.
    """

    resolution: Optional[Tuple[int, int]] = None
    model_id: int = 0
    serial: str = ""
    pm_byte: int = 0   # Raw PM from handshake (for button image lookup)
    sub_byte: int = 0   # Raw SUB from handshake (for button image lookup)
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
        """Get frame interval in milliseconds (capped at 16 FPS).

        Windows C# uses a fixed 62ms timer (≈16 FPS) for all animated
        themes regardless of source FPS.  Higher rates waste CPU on a
        small LCD where the difference is imperceptible.
        """
        if self.fps <= 0:
            return 62
        return max(62, int(1000 / self.fps))


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
    ring_count: int = 0             # decoration ring LEDs (e.g. LF25 = 77)
    memory_ratio: int = 2           # DDR multiplier (1, 2, or 4) — C# default: 2

    # LF11 (style 10) disk selector (C# hardDiskCount, 0-based)
    disk_index: int = 0

    # Segment carousel interval (ticks per phase, ~30ms per tick → 100 = ~3s)
    carousel_interval: int = 100

    # Zone sync (C# isLunBo) — one checkbox, behavior depends on style:
    #   Styles 2/7: "Select all" — sync all zones to same mode/color/brightness
    #   Other styles: "Circulate" — timer-rotate through enabled zones
    selected_zone: int = 0               # Currently selected zone (UI)
    zone_sync: bool = False              # isLunBo: checkbox state
    zone_sync_zones: List[bool] = field(default_factory=list)  # LunBo1-4
    zone_sync_current: int = 0           # nowLunbo: current active zone
    zone_sync_ticks: int = 0             # ValCount: tick counter
    zone_sync_interval: int = 13         # round(2s * 1000 / 150ms tick)

    # LC2 clock settings (style 9)
    is_timer_24h: bool = True
    is_week_sunday: bool = False

    def __post_init__(self):
        if not self.segment_on:
            self.segment_on = [True] * self.segment_count
        if not self.zones and self.zone_count > 1:
            self.zones = [LEDZoneState() for _ in range(self.zone_count)]
        if not self.zone_sync_zones and self.zone_count > 1:
            self.zone_sync_zones = [True] + [False] * (self.zone_count - 1)


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
    1: LedDeviceStyle(1, 30, 10, 4, "AX120_DIGITAL", "DAX120_DIGITAL", "D0数码屏"),
    2: LedDeviceStyle(2, 84, 18, 4, "PA120_DIGITAL", "DPA120_DIGITAL", "D0数码屏4区域"),
    3: LedDeviceStyle(3, 64, 10, 2, "AK120_DIGITAL", "DAK120_DIGITAL", "D0数码屏"),
    4: LedDeviceStyle(4, 31, 14, 3, "LC1", "DLC1", "D0LC1"),
    5: LedDeviceStyle(5, 93, 23, 2, "LF8", "DLF8", "D0LF8"),
    6: LedDeviceStyle(6, 124, 72, 2, "LF12", "DLF12", "D0LF12"),
    7: LedDeviceStyle(7, 116, 12, 3, "LF10", "DLF10", "D0LF10"),
    8: LedDeviceStyle(8, 18, 13, 4, "CZ1", "DCZ1", "D0CZ1"),
    9: LedDeviceStyle(9, 61, 31, 0, "LC2", "DLC2", "D0LC2"),
    10: LedDeviceStyle(10, 38, 17, 4, "LF11", "DLF11", "D0LF11"),
    11: LedDeviceStyle(11, 93, 72, 2, "LF15", "DLF15", "D0LF15"),
    12: LedDeviceStyle(12, 62, 62, 0, "LF13", "DLF13", "D0LF13"),
}

# Style IDs that support "select all zones" — sync every zone to same
# mode/color/brightness in one operation (PA120=2, LF10=7).
LED_SELECT_ALL_STYLES: frozenset[int] = frozenset({2, 7})


def resolve_led_style_id(model_name: str) -> int:
    """Resolve LED style_id from device model name. Returns 1 (AX120) if unknown."""
    for style_id, style in LED_STYLES.items():
        if style.model_name == model_name:
            return style_id
    return 1


@dataclass
class LedHandshakeInfo(HandshakeResult):
    """LED-specific handshake info (extends HandshakeResult)."""
    pm: int = 0
    sub_type: int = 0
    style: Optional[LedDeviceStyle] = None
    model_name: str = ""
    style_sub: int = 0  # C# nowLedStyleSub — wire remap variant


# =============================================================================
# PM Registry — PM byte → (style, model, button image)
# =============================================================================

class PmEntry(NamedTuple):
    """PM registry entry mapping a firmware PM byte to device metadata."""
    style_id: int
    model_name: str
    button_image: str
    preview_image: str = ""  # PM-specific preview; empty = use style default
    style_sub: int = 0       # C# nowLedStyleSub — variant within same style


class PmRegistry:
    """Encapsulates all PM-to-device metadata lookups.

    Maps firmware PM bytes (from HID handshake) to device style, model name,
    and button image.  Handles sub-type overrides and PA120 variant range
    (PMs 17-31).
    """

    # (pm, sub_type) → PmEntry override for devices that share a PM byte.
    _OVERRIDES: dict[tuple[int, int], PmEntry] = {}

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
        129: PmEntry(10, "LF11", "A1LF11", style_sub=1),
        144: PmEntry(11, "LF15", "A1LF15"),
        160: PmEntry(12, "LF13", "A1LF13"),
        176: PmEntry(5, "LF25", "A1LF25", style_sub=1),
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
# Wire order from C# FormLED.cs SendHidVal (line 4391).
# IMPORTANT: PA120 uses ReSetUCScreenLED2() indices (Cpu1=0, Cpu2=1, ...,
# BFB1=9, digits start at 10), NOT the UCScreenLED class defaults (Cpu1=2).
# Cpu2,Cpu1, digit1(FABGEDC), digit2, digit3,
# SSD,HSD,LEDC11,LEDB11,  digit4, digit5,
# BFB,BFB1,  digit10(CDEGBAF), digit9,
# LEDB12,LEDC12,SSD1,HSD1,  digit8, digit7, digit6,
# Gpu1,Gpu2
_REMAP_STYLE_2: tuple[int, ...] = (
    1, 0, 15, 10, 11, 16, 14, 13, 12,
    22, 17, 18, 23, 21, 20, 19,
    29, 24, 25, 30, 28, 27, 26,
    4, 5, 81, 80,
    36, 31, 32, 37, 35, 34, 33,
    43, 38, 39, 44, 42, 41, 40,
    6, 9,
    75, 76, 77, 79, 74, 73, 78,
    68, 69, 70, 72, 67, 66, 71,
    82, 83, 7, 8,
    61, 62, 63, 65, 60, 59, 64,
    54, 55, 56, 58, 53, 52, 57,
    47, 48, 49, 51, 46, 45, 50,
    2, 3,
)

# Style 3: AK120_DIGITAL (64 LEDs, 2 zones)
# ReSetUCScreenLED3(): Cpu1=0, WATT=1, SSD=2, HSD=3, BFB=4, Gpu1=5,
# LEDA1=6..LEDG1=12, LEDA2=13..LEDG2=19, ..., LEDB9=62, LEDC9=63
_REMAP_STYLE_3: tuple[int, ...] = (
    1, 22, 23, 24, 26, 21, 20, 25,
    14, 0, 13, 18, 19, 15, 16, 17,
    7, 6, 11, 12, 8, 9, 10,
    32, 27, 28, 33, 31, 30, 29,
    39, 34, 35, 40, 38, 37, 36,
    46, 41, 42, 47, 45, 44, 43,
    2, 3, 4,
    57, 58, 59, 61, 56, 55, 60,
    50, 5, 51, 52, 54, 49, 48, 53,
    62, 63,
)

# Style 4: LC1 (31 LEDs, 1 zone)
# ReSetUCScreenLED4(): SSD=0, MTNo=1, GNo=2,
# LEDA1=3..LEDG1=9, LEDA2=10..LEDG2=16, LEDA3=17..LEDG3=23, LEDA4=24..LEDG4=30
_REMAP_STYLE_4: tuple[int, ...] = (
    2, 1, 26, 27, 28, 30, 25, 24, 0,
    29, 19, 20, 21, 23, 18, 17, 22,
    12, 13, 14, 16, 11, 10, 15,
    5, 6, 7, 9, 4, 3, 8,
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

# Style 5 sub=1: LF25 (170 wire positions — 93 segment + 77 decoration ring)
# Segments use same indices as LF8 but REVERSED wire order.
# Decoration ring (ledVal5_1) mapped to logical indices 93-169.
# Decoration ring wire order: ledVal5_1[3,2,1,0,76,75,...,5,4].
_REMAP_STYLE_5_SUB1: tuple[int, ...] = (
    # --- Segment LEDs (93, reversed vs LF8) ---
    4,                                          # WATT
    43, 42, 47, 48, 44, 45, 46,                # seg6 (B A F G C D E)
    36, 35, 40, 41, 37, 38, 39,                # seg5
    29, 28, 33, 34, 30, 31, 32,                # seg4
    3, 2,                                       # HSD, SSD
    22, 21, 26, 27, 23, 24, 25,                # seg3
    15, 1, 14, 19, 20, 16, 17, 18,             # seg2 (B Gpu1 A F G C D E)
    8, 0, 7, 12, 13, 9, 10, 11,               # seg1 (B Cpu1 A F G C D E)
    54, 49, 50, 55, 53, 52, 51,                # seg7 (F A B G E D C)
    61, 56, 57, 62, 60, 59, 58,                # seg8
    68, 63, 64, 69, 67, 66, 65,                # seg9
    75, 70, 71, 76, 74, 73, 72,                # seg10
    5, 92, 91,                                  # MHz, LEDC13, LEDB13
    82, 77, 78, 83, 81, 80, 79,                # seg11
    89, 84, 85, 90, 88, 87, 86,                # seg12
    6,                                          # BFB
    # --- Decoration ring (77 LEDs, logical 93-169) ---
    # ledVal5_1[3,2,1,0] then [76,75,...,5,4]
    96, 95, 94, 93,
    169, 168, 167, 166, 165, 164, 163, 162, 161, 160,
    159, 158, 157, 156, 155, 154, 153, 152, 151, 150,
    149, 148, 147, 146, 145, 144, 143, 142, 141, 140,
    139, 138, 137, 136, 135, 134, 133, 132, 131, 130,
    129, 128, 127, 126, 125, 124, 123, 122, 121, 120,
    119, 118, 117, 116, 115, 114, 113, 112, 111, 110,
    109, 108, 107, 106, 105, 104, 103, 102, 101, 100,
    99, 98, 97,
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
}

# Sub-variant remap overrides: (style_id, style_sub) → remap table.
# Used when nowLedStyleSub != 0 (e.g. LF25 = style 5, sub 1).
LED_REMAP_SUB_TABLES: dict[tuple[int, int], tuple[int, ...]] = {
    (5, 1): _REMAP_STYLE_5_SUB1,  # LF25 (170 wire positions)
}


# Default-off LED indices per style (from C# isOnN arrays in UCScreenLED.cs).
# Styles not listed here default to all-on.
LED_DEFAULT_OFF: dict[int, frozenset[int]] = {
    1: frozenset({4, 5, 7, 8}),            # AX120: only index 6 on of 6-8
    2: frozenset({7}),                       # PA120: HSD(°F) off by default (°C mode)
    3: frozenset({3, 5}),                   # AK120
    4: frozenset({1, 2, 25, 26, 30}),       # LC1
    5: frozenset({1, 3}),                   # LF8
    6: frozenset({1, 3}),                   # LF12
    7: frozenset({2, 5}),                   # LF10
    8: frozenset({1, 2, 3}),                # CZ1
    10: frozenset({1, 2, 32, 33, 37}),      # LF11
    11: frozenset({1, 3}),                  # LF15
}


def remap_led_colors(
    colors: List[Tuple[int, int, int]],
    style_id: int,
    style_sub: int = 0,
) -> List[Tuple[int, int, int]]:
    """Remap LED colors from logical to physical wire order.

    Each LED device style has a hardware-specific mapping from logical LED
    indices (used by the GUI) to physical wire positions (sent to device).
    Sub-variant overrides (e.g. LF25 = style 5, sub 1) use a separate table.
    """
    table = LED_REMAP_SUB_TABLES.get((style_id, style_sub))
    if table is None:
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

    _TEMP_FIELDS = ('cpu_temp', 'gpu_temp', 'mem_temp', 'disk_temp')

    @staticmethod
    def with_temp_unit(metrics: 'HardwareMetrics', temp_unit: int) -> 'HardwareMetrics':
        """Apply temperature unit conversion in-place (0=Celsius, 1=Fahrenheit).

        Called once by MetricsMediator before dispatch — all downstream
        consumers receive pre-converted temps.
        """
        if temp_unit != 1:
            return metrics
        for attr in HardwareMetrics._TEMP_FIELDS:
            setattr(metrics, attr, celsius_to_fahrenheit(getattr(metrics, attr)))
        return metrics


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
# Overlay config builders (CLI/API metric spec → OverlayService config dict)
# =============================================================================

# Valid metric keys for overlay elements (hardware sensors + time/date/weekday).
VALID_OVERLAY_KEYS: frozenset[str] = frozenset(
    set(HARDWARE_METRICS.values()) | {'time', 'date', 'weekday'}
)


def parse_metric_spec(
    spec: str,
    index: int,
    default_color: str = 'ffffff',
    default_size: int = 14,
    default_font: str = 'Microsoft YaHei',
    default_style: str = 'regular',
) -> tuple[str, dict]:
    """Parse a metric spec string into an overlay config element.

    Format: ``key:x,y[:color[:size[:font[:style]]]]``

    Examples:
        ``"gpu_temp:10,20"``                      → uses all defaults
        ``"cpu_percent:10,50:ff0000"``             → red, default size
        ``"time:150,10:ffffff:24"``                → white, 24px
        ``"gpu_temp:10,20:ff0000:18:Arial:bold"``  → red, 18px, Arial bold
        ``"cpu_temp:10,50::16:Courier"``            → default color, 16px, Courier

    Returns:
        (element_key, config_dict) for ``OverlayService.set_config()``.

    Raises:
        ValueError: if spec is malformed or metric key is invalid.
    """
    parts = spec.split(':')
    if len(parts) < 2:
        raise ValueError(
            f"Invalid metric spec '{spec}' — expected 'key:x,y' "
            f"(e.g. 'gpu_temp:10,20')")

    metric_key = parts[0]
    if metric_key not in VALID_OVERLAY_KEYS:
        raise ValueError(
            f"Unknown metric key '{metric_key}'. "
            f"Valid keys: {', '.join(sorted(VALID_OVERLAY_KEYS))}")

    try:
        coords = parts[1].split(',')
        x, y = int(coords[0]), int(coords[1])
    except (ValueError, IndexError) as e:
        raise ValueError(
            f"Invalid coordinates in '{spec}' — expected 'key:x,y' "
            f"(e.g. 'gpu_temp:10,20')") from e

    color = default_color
    size = default_size
    font_name = default_font
    style = default_style
    if len(parts) >= 3 and parts[2]:
        color = parts[2]
    if len(parts) >= 4 and parts[3]:
        try:
            size = int(parts[3])
        except ValueError as e:
            raise ValueError(
                f"Invalid size in '{spec}' — expected integer") from e
    if len(parts) >= 5 and parts[4]:
        font_name = parts[4]
    if len(parts) >= 6 and parts[5]:
        style = parts[5]

    element_key = f"cli_elem_{index}"
    config: dict = {
        'x': x,
        'y': y,
        'color': f"#{color.lstrip('#')}",
        'font': {
            'size': size,
            'style': style,
            'name': font_name,
        },
        'enabled': True,
        'metric': metric_key,
    }

    # Add format fields for time/date/temp metrics
    if metric_key == 'time':
        config['time_format'] = 0
    elif metric_key == 'date':
        config['date_format'] = 0
    elif metric_key.endswith('_temp'):
        config['temp_unit'] = 0

    return element_key, config


def build_overlay_config(
    metrics: list[str],
    *,
    default_color: str = 'ffffff',
    default_font_size: int = 14,
    default_font: str = 'Microsoft YaHei',
    default_style: str = 'regular',
    temp_unit: int = 0,
    time_format: int = 0,
    date_format: int = 0,
) -> dict:
    """Build an overlay config dict from CLI metric spec strings.

    Args:
        metrics: List of spec strings (``"key:x,y[:color[:size]]"``).
        default_color: Global hex color for elements without per-metric override.
        default_font_size: Global font size (px).
        default_font: Global font family name.
        default_style: Global font style (``'regular'`` or ``'bold'``).
        temp_unit: Temperature unit (0=Celsius, 1=Fahrenheit).
        time_format: Time format (0=24h HH:MM, 1=12h hh:MM).
        date_format: Date format (0=yyyy/MM/dd, 1=same, 2=dd/MM/yyyy, etc.).

    Returns:
        Dict suitable for ``OverlayService.set_config()``.

    Raises:
        ValueError: if any metric spec is invalid.
    """
    config: dict = {}
    for i, spec in enumerate(metrics):
        key, elem = parse_metric_spec(
            spec, i, default_color, default_font_size,
            default_font, default_style)
        # Apply global format overrides
        if 'time_format' in elem:
            elem['time_format'] = time_format
        if 'date_format' in elem:
            elem['date_format'] = date_format
        if 'temp_unit' in elem:
            elem['temp_unit'] = temp_unit
        config[key] = elem
    return config


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

# LCD brightness button steps (percent values cycled by the GUI button)
BRIGHTNESS_STEPS: tuple[int, ...] = (25, 50, 100)
DEFAULT_BRIGHTNESS_LEVEL = 100

# JPEG encoding — max payload bytes (HID Type 2 transfer buffer is 691,200 bytes,
# leaving ~672 KB for payload; 650 KB gives safe margin at full quality 95)
JPEG_MAX_BYTES = 650_000


# Time formats matching Windows TRCC (UCXiTongXianShiSub.cs)
TIME_FORMATS: Dict[int, str] = {
    0: "%H:%M",       # 24-hour (14:58)
    1: "%I:%M",       # 12-hour with leading zero (02:58) — stripped in _format_metric
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

# Legacy C# suffix → ISO 639-1 code migration map
# Used by conf.py to migrate old config.json "lang" values
LEGACY_TO_ISO: dict[str, str] = {
    '': 'zh',
    'tc': 'zh_TW',
    'd': 'de',
    'e': 'ru',
    'f': 'fr',
    'p': 'pt',
    'r': 'ja',
    'x': 'es',
    'h': 'ko',
    # These were already ISO — included for completeness
    'en': 'en',
}

# ISO 639-1 code → legacy C# asset suffix (for asset filename lookup)
# Only needed for the 10 original languages whose assets use C# suffixes
ISO_TO_LEGACY: dict[str, str] = {v: k for k, v in LEGACY_TO_ISO.items()}

# System locale prefix → ISO 639-1 language code
LOCALE_TO_LANG: dict[str, str] = {
    'zh_CN': 'zh',
    'zh_TW': 'zh_TW',
    'en': 'en',
    'de': 'de',
    'es': 'es',
    'fr': 'fr',
    'pt': 'pt',
    'ru': 'ru',
    'ja': 'ja',
    'ko': 'ko',
}

# =============================================================================
# Device Profile — single source of truth for all FBL-derived properties.
# Replaces FBL_TO_RESOLUTION, JPEG_MODE_FBLS, BULK_RGB565_FBLS,
# byte_order_for(), _SQUARE_NO_ROTATE.
# =============================================================================


@dataclass(frozen=True)
class DeviceProfile:
    """Everything needed to talk to a device, derived from its FBL code.

    One lookup replaces 5 scattered constants/functions.
    """
    width: int
    height: int
    jpeg: bool = False           # JPEG encoding (vs RGB565)
    big_endian: bool = False     # RGB565 byte order (> vs <)
    rotate: bool = False         # Pre-rotate 90° CW for non-square portrait panels
    # Device encode rotation (C# RotateImg in ImageToJpg).
    # Formula: angle = (base + direction * sign) % 360
    # sign = -1 if encode_invert else +1. sub_byte overrides base.
    encode_base: int = 0
    encode_invert: bool = True   # True = (base - dir), most devices
    encode_sub_bases: tuple[tuple[int, int], ...] = ()  # ((sub, base), ...)

    @property
    def resolution(self) -> tuple[int, int]:
        return (self.width, self.height)

    @property
    def byte_order(self) -> str:
        return '>' if self.big_endian else '<'


# fmt: off
FBL_PROFILES: dict[int, DeviceProfile] = {
    #          W      H     jpeg    BE      rotate  enc_base  enc_inv  enc_sub
    36:  DeviceProfile(240,  240),
    37:  DeviceProfile(240,  240),
    50:  DeviceProfile(320,  240,  rotate=True),
    51:  DeviceProfile(320,  240,  rotate=True),                     # HID Type 2 → SPIMode=1
    53:  DeviceProfile(320,  240,  rotate=True),                     # HID Type 2 → SPIMode=1
    54:  DeviceProfile(360,  360,  jpeg=True),
    58:  DeviceProfile(320,  240,  rotate=True),
    64:  DeviceProfile(640,  480,  rotate=True),
    72:  DeviceProfile(480,  480),
    100: DeviceProfile(320,  320,  big_endian=True),
    101: DeviceProfile(320,  320,  big_endian=True),
    102: DeviceProfile(320,  320,  big_endian=True),
    114: DeviceProfile(1600, 720,  jpeg=True, rotate=True,
                       encode_base=180, encode_sub_bases=((3, 0),)),
    128: DeviceProfile(1280, 480,  jpeg=True, rotate=True,
                       encode_sub_bases=((2, 90),)),
    129: DeviceProfile(480,  480),                              # alias for 72
    192: DeviceProfile(1920, 462,  jpeg=True, rotate=True,
                       encode_base=180, encode_sub_bases=((2, 0), (3, 0), (4, 0))),
    224: DeviceProfile(854,  480,  jpeg=True, rotate=True,
                       encode_invert=False, encode_sub_bases=((2, 180),)),
}
# fmt: on

_DEFAULT_PROFILE = DeviceProfile(320, 320, big_endian=True)


def get_encode_rotation(profile: DeviceProfile, sub_byte: int,
                        direction: int) -> int:
    """Compute device encode rotation angle (C# RotateImg in ImageToJpg).

    Every C# angle table follows: angle = (base + direction * sign) % 360.
    sign is per-resolution (-1 if encode_invert, +1 otherwise).
    sub_byte overrides base for specific device variants.
    """
    base = profile.encode_base
    for sub, sub_base in profile.encode_sub_bases:
        if sub_byte == sub:
            base = sub_base
            break
    sign = -1 if profile.encode_invert else 1
    return (base + direction * sign) % 360


def get_profile(fbl: int, pm: int = 0) -> DeviceProfile:
    """Get device profile for an FBL code.

    For FBL 224/192, PM disambiguates the resolution (same encoding props).
    """
    profile = FBL_PROFILES.get(fbl, _DEFAULT_PROFILE)
    if fbl == 224:
        w, h = _FBL_224_BY_PM.get(pm, (854, 480))
        return DeviceProfile(w, h, jpeg=profile.jpeg,
                             big_endian=profile.big_endian, rotate=profile.rotate,
                             encode_base=profile.encode_base,
                             encode_invert=profile.encode_invert,
                             encode_sub_bases=profile.encode_sub_bases)
    if fbl == 192:
        w, h = _FBL_192_BY_PM.get(pm, (1920, 462))
        return DeviceProfile(w, h, jpeg=profile.jpeg,
                             big_endian=profile.big_endian, rotate=profile.rotate,
                             encode_base=profile.encode_base,
                             encode_invert=profile.encode_invert,
                             encode_sub_bases=profile.encode_sub_bases)
    return profile


# --- Backward compatibility aliases (remove after migration) ---

FBL_TO_RESOLUTION: dict[int, tuple[int, int]] = {
    fbl: p.resolution for fbl, p in FBL_PROFILES.items()
}

JPEG_MODE_FBLS: frozenset[int] = frozenset(
    fbl for fbl, p in FBL_PROFILES.items() if p.jpeg
)

BULK_RGB565_FBLS: frozenset[int] = frozenset(
    fbl for fbl, p in FBL_PROFILES.items() if not p.jpeg and p.big_endian
)

# Reverse lookup: resolution → PM/FBL (first match wins)
RESOLUTION_TO_PM: dict[tuple[int, int], int] = {
    p.resolution: fbl for fbl, p in FBL_PROFILES.items()
    if fbl not in (37, 101, 102, 224)
}

# PM byte → FBL byte for Type 2 devices where PM ≠ FBL.
# (FormCZTV.cs lines 682-821)
# For all other PM values, PM=FBL (same convention as SCSI poll bytes).
_PM_TO_FBL_OVERRIDES: dict[int, int] = {
    5:   50,    # 320x240
    7:   64,    # 640x480
    9:   224,   # 854x480
    10:  224,   # 960x540 (disambiguated in _FBL_224_BY_PM)
    11:  224,   # 854x480
    12:  224,   # 800x480 (disambiguated in _FBL_224_BY_PM)
    13:  224,   # 960x320 (disambiguated in _FBL_224_BY_PM)
    14:  64,    # 640x480
    15:  224,   # 640x172 (disambiguated in _FBL_224_BY_PM)
    16:  224,   # 960x540 (disambiguated in _FBL_224_BY_PM)
    17:  224,   # 960x320 (disambiguated in _FBL_224_BY_PM)
    32:  100,   # 320x320
    50:  50,    # 320x240 (SPI mode 2)
    63:  114,   # 1600x720
    64:  114,   # 1600x720
    65:  192,   # 1920x462
    66:  192,   # 1920x462
    68:  192,   # 1280x480 (disambiguated in _FBL_192_BY_PM)
    69:  192,   # 1920x440 (disambiguated in _FBL_192_BY_PM)
}


# FBL 224 is shared by 5 resolutions — PM byte disambiguates
_FBL_224_BY_PM: dict[int, tuple[int, int]] = {
    10: (960, 540),
    12: (800, 480),
    13: (960, 320),
    15: (640, 172),
    16: (960, 540),
    17: (960, 320),
}

# FBL 192 is shared by 3 resolutions — PM byte disambiguates
_FBL_192_BY_PM: dict[int, tuple[int, int]] = {
    68: (1280, 480),
    69: (1920, 440),
}

# PM+SUB compound keys where sub byte changes the FBL mapping
_PM_SUB_TO_FBL: dict[tuple[int, int], int] = {
    (1, 48): 114,   # 1600x720
    (1, 49): 192,   # 1920x462
}


def fbl_to_resolution(fbl: int, pm: int = 0) -> tuple[int, int]:
    """Map FBL byte to (width, height). Delegates to get_profile()."""
    return get_profile(fbl, pm).resolution


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
# Panel Asset Dims — scaled dimensions for crop/video panel backgrounds
# =============================================================================
# C# buttonSelectBackgroundImage() maps each device resolution to scaled dims
# that fit the fixed-size panel. Assets: P0裁减{pw}{ph}, P0图片裁减{pw}{ph}.
# Both landscape and portrait entries included.
PANEL_ASSET_DIMS: dict[tuple[int, int], tuple[int, int]] = {
    # Square
    (240, 240): (240, 240),
    (320, 320): (320, 320),
    (360, 360): (360, 360),
    (480, 480): (480, 480),
    # Rectangular — native size
    (320, 240): (320, 240),   (240, 320): (240, 320),
    # Rectangular — ÷2
    (640, 480): (320, 240),   (480, 640): (240, 320),
    (800, 480): (400, 240),   (480, 800): (240, 400),
    (854, 480): (427, 240),   (480, 854): (240, 427),
    (960, 540): (480, 270),   (540, 960): (270, 480),
    (960, 320): (480, 160),   (320, 960): (160, 480),
    (640, 172): (320, 86),    (172, 640): (86, 320),
    # Widescreen — ÷2.67
    (1280, 480): (480, 180),  (480, 1280): (180, 480),
    # Widescreen — ÷4
    (1600, 720): (400, 180),  (720, 1600): (180, 400),
    (1920, 462): (480, 116),  (462, 1920): (116, 480),
    (1920, 440): (480, 110),  (440, 1920): (110, 480),
}


def panel_asset_dims(w: int, h: int) -> tuple[int, int]:
    """Look up scaled panel dims for a device resolution.

    Falls back to (320, 240) landscape or (240, 320) portrait,
    matching the C# else branch in buttonSelectBackgroundImage().
    """
    dims = PANEL_ASSET_DIMS.get((w, h))
    if dims:
        return dims
    return (240, 320) if h > w else (320, 240)


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
    4:   {1: 'A1HYPER VISION', 2: 'A1RP130 VISION', 3: 'A1LM16SE',
          4: 'A1LF10V', 5: 'A1LM19SE'},
    5:   {None: 'A1Mjolnir VISION'},
    6:   {1: 'FROZEN_WARFRAME_Ultra', 2: 'A1FROZEN VISION V2'},
    7:   {1: 'A1Stream Vision', 2: 'A1Mjolnir VISION PRO'},
    9:   {0: 'A1LC2JD', 1: 'A1LC2JD', 2: 'A1LC2JD', 3: 'A1LC2JD',
          4: 'A1LC2JD', None: 'A1LF19'},
    10:  {5: 'A1LF16', 6: 'A1LF18', 7: 'A1LD6', None: 'A1LC3'},
    11:  {6: 'A1LD8', None: 'A1LF19'},
    12:  {None: 'A1LF167'},
    13:  {None: 'A1PC1'},
    14:  {1: 'A1Stream Vision', 2: 'A1Mjolnir VISION PRO'},
    15:  {2: 'A1LC8', None: 'A1LC7'},
    16:  {None: 'A1CZ2'},
    17:  {1: 'A1PC1', 2: 'A1LC9', 5: 'A1PC1', None: 'A1PC1'},
    # -- HID LCD devices (case 2 + case 257 merged, PM + SUB) --
    32:  {0: 'A1ELITE VISION', 1: 'A1FROZEN WARFRAME PRO',
          None: 'A1ELITE VISION'},
    36:  {None: 'A1AS120 VISION'},
    49:  {None: 'A1FROZEN WARFRAME'},
    50:  {None: 'A1FROZEN WARFRAME'},
    51:  {None: 'A1FROZEN WARFRAME'},
    52:  {None: 'A1BA120 VISION'},
    53:  {1: 'A1LF21', 2: 'A1LF22', None: 'A1LF20'},
    54:  {None: 'A1LC5'},
    58:  {0: 'A1FROZEN WARFRAME SE', None: 'A1LM26'},
    63:  {0: 'A1FROZEN WARFRAME PRO', 1: 'A1LM22', 2: 'A1LM27',
          3: 'A1LM30'},
    64:  {0: 'A1FROZEN WARFRAME PRO', 1: 'A1LM22', 2: 'A1LM27',
          3: 'A1LM30'},
    65:  {0: 'A1ELITE VISION', 1: 'A1LF14', 2: 'A1LF14', 3: 'A1LD7',
          4: 'A1LD10', 5: 'A1LD7'},
    66:  {0: 'A1ELITE VISION', 1: 'A1LF14', 2: 'A1LF14',
          3: 'A1LD7', 4: 'A1LD7'},
    68:  {None: 'A1LM24'},
    69:  {2: 'A1LD9'},
    100: {0: 'A1FROZEN WARFRAME PRO', 1: 'A1LM22',
          None: 'A1FROZEN WARFRAME PRO'},
    101: {0: 'A1ELITE VISION', 1: 'A1LF14', None: 'A1ELITE VISION'},
    128: {None: 'A1LM24'},
    129: {None: 'A1GRAND VISION'},
}



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
    "ly": "USB Bulk LY (Trofeo Vision)",
}

DEVICE_TYPE_NAMES: dict[int, str] = {
    1: "SCSI RGB565",
    2: "HID Type 2 (H)",
    3: "HID Type 3 (ALi)",
    4: "Raw USB Bulk LCD",
    5: "USB Bulk LY (Trofeo Vision)",
}

LED_DEVICE_TYPE_NAME: str = "RGB LED Controller"


# =============================================================================
# Protocol Traits — data-driven per-protocol behavioral properties
# =============================================================================


@dataclass(frozen=True)
class ProtocolTraits:
    """Per-protocol behavioral data — eliminates scattered string checks.

    Single source of truth for protocol-specific properties.  Consumed by
    udev rule generation, factory backend selection, image encoding, and
    device type classification.
    """
    udev_subsystems: Tuple[str, ...]     # subsystems for udev rules
    backend_key: str                     # 'sg_raw' or 'pyusb'
    fallback_backend: Optional[str]      # 'hidapi' for HID/LED, None for others
    requires_reboot: bool                # SCSI needs reboot after udev quirk
    supports_jpeg: bool                  # bulk/ly use JPEG encoding
    is_led: bool                         # LED protocol (not LCD)


PROTOCOL_TRAITS: Dict[str, ProtocolTraits] = {
    'scsi': ProtocolTraits(
        udev_subsystems=('scsi_generic',), backend_key='sg_raw',
        fallback_backend=None, requires_reboot=True,
        supports_jpeg=False, is_led=False),
    'hid': ProtocolTraits(
        udev_subsystems=('hidraw', 'usb'), backend_key='pyusb',
        fallback_backend='hidapi', requires_reboot=False,
        supports_jpeg=False, is_led=False),
    'bulk': ProtocolTraits(
        udev_subsystems=('usb',), backend_key='pyusb',
        fallback_backend=None, requires_reboot=False,
        supports_jpeg=True, is_led=False),
    'ly': ProtocolTraits(
        udev_subsystems=('usb',), backend_key='pyusb',
        fallback_backend=None, requires_reboot=False,
        supports_jpeg=True, is_led=False),
    'led': ProtocolTraits(
        udev_subsystems=('hidraw', 'usb'), backend_key='pyusb',
        fallback_backend='hidapi', requires_reboot=False,
        supports_jpeg=False, is_led=True),
}


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

# Overlay element hardware category ID → display name (0=CPU, 1=GPU, …)
CATEGORY_NAMES: dict[int, str] = {
    0: 'CPU',
    1: 'GPU',
    2: 'MEM',
    3: 'HDD',
    4: 'NET',
    5: 'FAN',
}

# Overlay element hardware sub-metric labels per category
# {category_id: {sub_count: label}}
SUB_METRICS: dict[int, dict[int, str]] = {
    0: {1: 'Temp', 2: 'Usage', 3: 'Freq',     4: 'Power'},
    1: {1: 'Temp', 2: 'Usage', 3: 'Clock',    4: 'Power'},
    2: {1: 'Used%', 2: 'Clock', 3: 'Used',    4: 'Free'},
    3: {1: 'Read', 2: 'Write', 3: 'Activity', 4: 'Temp'},
    4: {1: 'Down', 2: 'Up',    3: 'Total',    4: 'Ping'},
    5: {1: 'RPM',  2: 'PWM%',  3: 'Temp',     4: 'Speed'},
}


# Activity sidebar sensor definitions: category → [(key_suffix, label, unit, metric_key)]
SENSORS: dict[str, list[tuple[str, str, str, str]]] = {
    'cpu':     [('temp',       'TEMP',      '°C',   'cpu_temp'),
                ('usage',      'Usage',     '%',    'cpu_percent'),
                ('clock',      'Clock',     'MHz',  'cpu_freq'),
                ('power',      'Power',     'W',    'cpu_power')],
    'gpu':     [('temp',       'TEMP',      '°C',   'gpu_temp'),
                ('usage',      'Usage',     '%',    'gpu_usage'),
                ('clock',      'Clock',     'MHz',  'gpu_clock'),
                ('power',      'Power',     'W',    'gpu_power')],
    'memory':  [('temp',       'TEMP',      '°C',   'mem_temp'),
                ('usage',      'Usage',     '%',    'mem_percent'),
                ('clock',      'Clock',     'MHz',  'mem_clock'),
                ('available',  'Available', 'MB',   'mem_available')],
    'hdd':     [('temp',       'TEMP',      '°C',   'disk_temp'),
                ('activity',   'Activity',  '%',    'disk_activity'),
                ('read',       'Read',      'MB/s', 'disk_read'),
                ('write',      'Write',     'MB/s', 'disk_write')],
    'network': [('upload',     'UP rate',   'KB/s', 'net_up'),
                ('download',   'DL rate',   'KB/s', 'net_down'),
                ('total_up',   'Total UP',  'MB',   'net_total_up'),
                ('total_dl',   'Total DL',  'MB',   'net_total_down')],
    'fan':     [('cpu_fan',    'CPUFAN',    'RPM',  'fan_cpu'),
                ('gpu_fan',    'GPUFAN',    'RPM',  'fan_gpu'),
                ('ssd_fan',    'SSDFAN',    'RPM',  'fan_ssd'),
                ('fan2',       'FAN2',      'RPM',  'fan_sys2')],
}

# Maps 'category_keysuffix' → overlay (main_count, sub_count)
SENSOR_TO_OVERLAY: dict[str, tuple[int, int]] = {
    'cpu_temp': (0, 1),     'cpu_usage': (0, 2),     'cpu_clock': (0, 3),     'cpu_power': (0, 4),
    'gpu_temp': (1, 1),     'gpu_usage': (1, 2),     'gpu_clock': (1, 3),     'gpu_power': (1, 4),
    'memory_temp': (2, 1),  'memory_usage': (2, 2),  'memory_clock': (2, 3),  'memory_available': (2, 4),
    'hdd_temp': (3, 1),     'hdd_activity': (3, 2),  'hdd_read': (3, 3),      'hdd_write': (3, 4),
    'network_upload': (4, 1), 'network_download': (4, 2), 'network_total_up': (4, 3), 'network_total_dl': (4, 4),
    'fan_cpu_fan': (5, 1),  'fan_gpu_fan': (5, 2),   'fan_ssd_fan': (5, 3),   'fan_fan2': (5, 4),
}


# =============================================================================
# Sensor Dashboard Panel Configuration — pure domain dataclasses
# =============================================================================

@dataclass
class SensorBinding:
    """Maps a single dashboard panel row to a sensor."""
    label: str        # Row label displayed on panel ("TEMP", "Usage", etc.)
    sensor_id: str    # SensorEnumerator ID ("hwmon:coretemp:temp1")
    unit: str         # Display unit suffix ("°C", "%", "MHz", etc.)


@dataclass
class PanelConfig:
    """Configuration for a single sensor dashboard panel."""
    category_id: int                          # 0=Custom,1=CPU,2=GPU,3=Memory,4=HDD,5=Network,6=Fan
    name: str                                  # Panel display name
    sensors: list[SensorBinding] = field(default_factory=list)


# =============================================================================
# Metric formatting — single source of truth (matches Windows TRCC)
# =============================================================================


def format_metric(metric: str, value: float, time_format: int = 0,
                  date_format: int = 0, temp_unit: int = 0) -> str:
    """Format a metric value for display (matches Windows TRCC)."""
    if metric == 'date':
        now = datetime.now()
        fmt = DATE_FORMATS.get(date_format, DATE_FORMATS[0])
        return now.strftime(fmt)
    elif metric == 'time':
        now = datetime.now()
        fmt = TIME_FORMATS.get(time_format, TIME_FORMATS[0])
        result = now.strftime(fmt)
        # Strip leading zero for 12-hour format (cross-platform — avoids
        # Unix %-I vs Windows %#I platform-specific strftime flags)
        if time_format == 1:
            result = result.lstrip('0')
        return result
    elif metric == 'weekday':
        now = datetime.now()
        return WEEKDAYS[now.weekday()]
    elif metric == 'day_of_week':
        return WEEKDAYS[int(value)]
    elif metric.startswith('time_') or metric.startswith('date_'):
        return f"{int(value):02d}"
    elif 'temp' in metric:
        suffix = "°F" if temp_unit == 1 else "°C"
        return f"{value:.0f}{suffix}"
    elif 'percent' in metric or 'usage' in metric or 'activity' in metric:
        return f"{value:.0f}%"
    elif 'freq' in metric or 'clock' in metric:
        if value >= 1000:
            return f"{value/1000:.1f}GHz"
        return f"{value:.0f}MHz"
    elif metric in ('disk_read', 'disk_write'):
        return f"{value:.1f}MB/s"
    elif metric in ('net_up', 'net_down'):
        if value >= 1024:
            return f"{value/1024:.1f}MB/s"
        return f"{value:.0f}KB/s"
    elif metric in ('net_total_up', 'net_total_down'):
        if value >= 1024:
            return f"{value/1024:.1f}GB"
        return f"{value:.0f}MB"
    elif metric.startswith('fan_'):
        return f"{value:.0f}RPM"
    elif metric == 'mem_available':
        if value >= 1024:
            return f"{value/1024:.1f}GB"
        return f"{value:.0f}MB"
    return f"{value:.1f}"


# =============================================================================
# API Server DTOs
# =============================================================================

# =============================================================================
# Cloud / Mask URL maps (single source of truth — adapters import from here)
# =============================================================================

# Cloud theme download URL keys (resolution string → server path suffix).
# Source: C# v2.1.2 GifWebDir* constants.
CLOUD_THEME_URL_KEYS: dict[str, str] = {
    "240x240": "bj240240",
    "240x320": "bj240320",
    "320x240": "bj320240",
    "320x320": "bj320320",
    "360x360": "bj360360",
    "480x480": "bj480480",
    "640x172": "bj640172",
    "640x480": "bj640480",
    "800x480": "bj800480",
    "854x480": "bj854480",
    "960x320": "bj960320",
    "960x540": "bj960540",
    "1280x480": "bj1280480",
    "1600x720": "bj1600720",
    "1600x720u": "bj1600720u",
    "1600x720l": "bj1600720l",
    "1920x440": "bj1920440",
    "1920x462": "bj1920462",
    # Portrait variants
    "172x640": "bj172640",
    "320x960": "bj320960",
    "440x1920": "bj4401920",
    "462x1920": "bj4621920",
    "480x640": "bj480640",
    "480x800": "bj480800",
    "480x854": "bj480854",
    "480x1280": "bj4801280",
    "540x960": "bj540960",
    "720x1600": "bj7201600",
    "720x1600u": "bj7201600u",
    "720x1600l": "bj7201600l",
}

# Cloud mask server URLs by resolution string.
# Source: C# UCMask server endpoints.
CLOUD_MASK_URLS: dict[str, str] = {
    "240x240":   "http://www.czhorde.cc/tr/zt240240/",
    "240x320":   "http://www.czhorde.cc/tr/zt240320/",
    "320x240":   "http://www.czhorde.cc/tr/zt320240/",
    "320x320":   "http://www.czhorde.cc/tr/zt320320/",
    "360x360":   "http://www.czhorde.cc/tr/zt360360/",
    "480x480":   "http://www.czhorde.cc/tr/zt480480/",
    "480x640":   "http://www.czhorde.cc/tr/zt480640/",
    "480x800":   "http://www.czhorde.cc/tr/zt480800/",
    "480x854":   "http://www.czhorde.cc/tr/zt480854/",
    "480x1280":  "http://www.czhorde.cc/tr/zt4801280/",
    "540x960":   "http://www.czhorde.cc/tr/zt540960/",
    "640x480":   "http://www.czhorde.cc/tr/zt640480/",
    "720x1600":  "http://www.czhorde.cc/tr/zt7201600/",
    "800x480":   "http://www.czhorde.cc/tr/zt800480/",
    "854x480":   "http://www.czhorde.cc/tr/zt854480/",
    "960x540":   "http://www.czhorde.cc/tr/zt960540/",
    "1280x480":  "http://www.czhorde.cc/tr/zt1280480/",
    "1600x720":  "http://www.czhorde.cc/tr/zt1600720/",
    "1920x462":  "http://www.czhorde.cc/tr/zt1920462/",
    "462x1920":  "http://www.czhorde.cc/tr/zt4621920/",
    # Billboard/side-strip devices (cloud-only, no bundled archives)
    "640x172":   "http://www.czhorde.cc/tr/zt640172/",
    "172x640":   "http://www.czhorde.cc/tr/zt172640/",
    "960x320":   "http://www.czhorde.cc/tr/zt960320/",
    "320x960":   "http://www.czhorde.cc/tr/zt320960/",
    "1920x440":  "http://www.czhorde.cc/tr/zt1920440/",
    "440x1920":  "http://www.czhorde.cc/tr/zt4401920/",
}

# Cloud theme server base URL templates (resolution suffix appended at runtime).
CLOUD_SERVERS: dict[str, str] = {
    'international': 'http://www.czhorde.cc/tr/bj{resolution}/',
    'china': 'http://www.czhorde.com/tr/bj{resolution}/',
}


# =============================================================================
# API Server DTOs
# =============================================================================

@dataclass(frozen=True)
class ServerInfo:
    """Connection details for a running TRCC API server."""
    host: str
    port: int
    token: str
    tls: bool

    def to_json(self) -> str:
        """Compact JSON payload for QR codes / remote apps."""
        import json
        return json.dumps({
            "host": self.host,
            "port": self.port,
            "token": self.token,
            "tls": self.tls,
        }, separators=(",", ":"))

