"""Core ports — ABCs that define contracts for adapter implementations.

Ports live in core/ so both services/ and adapters/ can import them
without violating hexagonal dependency direction.

SOLID:
    S — Each ABC has one responsibility
    O — New device types extend Device without modifying existing code
    L — LCDDevice/LEDDevice fully substitutable as Device
    I — Device ABC: 4 methods. Renderer ABC: domain-focused groups.
        Replaces DisplayPort (47) and LEDPort (30) — ISP violations.
    D — All adapters depend on these core abstractions
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Callable, Optional, Protocol, runtime_checkable

if TYPE_CHECKING:
    from trcc.core.models import SensorInfo


@dataclass
class RawFrame:
    """Raw decoded video frame — pure bytes, no framework deps.

    Produced by media decoders (VideoDecoder, ThemeZtDecoder).
    Converted to native renderer surfaces by the render adapter.
    """
    data: bytes
    width: int
    height: int


class Renderer(ABC):
    """Port: rendering backend for the full image pipeline.

    Covers overlay compositing, image adjustments (brightness, rotation),
    device encoding (RGB565, JPEG), and file I/O.

    Concrete implementation:
        - QtRenderer (adapters/render/qt.py) — PySide6 QImage/QPainter
    """

    # ── Surface lifecycle ─────────────────────────────────────────

    @abstractmethod
    def create_surface(self, width: int, height: int,
                       color: tuple[int, ...] | None = None) -> Any:
        """Create a new rendering surface (blank transparent or solid color)."""

    @abstractmethod
    def copy_surface(self, surface: Any) -> Any:
        """Defensive copy of a surface."""

    @abstractmethod
    def convert_to_rgba(self, surface: Any) -> Any:
        """Ensure surface has alpha channel."""

    @abstractmethod
    def convert_to_rgb(self, surface: Any) -> Any:
        """Ensure surface is RGB (strip alpha)."""

    @abstractmethod
    def surface_size(self, surface: Any) -> tuple[int, int]:
        """Return (width, height) of a surface."""

    # ── Compositing ───────────────────────────────────────────────

    @abstractmethod
    def composite(self, base: Any, overlay: Any,
                  position: tuple[int, int],
                  mask: Any | None = None) -> Any:
        """Alpha-composite *overlay* onto *base* at *position*."""

    @abstractmethod
    def resize(self, surface: Any, width: int, height: int) -> Any:
        """Resize surface with high-quality resampling."""

    # ── Text ──────────────────────────────────────────────────────

    @abstractmethod
    def draw_text(self, surface: Any, x: int, y: int, text: str,
                  color: str, font: Any, anchor: str = 'mm') -> None:
        """Draw text onto surface at (x, y)."""

    @abstractmethod
    def get_font(self, size: int, bold: bool = False,
                 font_name: str | None = None) -> Any:
        """Resolve and cache a font at given size."""

    @abstractmethod
    def clear_font_cache(self) -> None:
        """Flush font cache (e.g. after resolution change)."""

    # ── Image adjustments ─────────────────────────────────────────

    @abstractmethod
    def apply_brightness(self, surface: Any, percent: int) -> Any:
        """Apply brightness adjustment (100 = unchanged, 0 = black)."""

    @abstractmethod
    def apply_rotation(self, surface: Any, degrees: int) -> Any:
        """Rotate surface by 0/90/180/270 degrees."""

    # ── Device encoding ───────────────────────────────────────────

    @abstractmethod
    def encode_rgb565(self, surface: Any, byte_order: str = '>') -> bytes:
        """Encode surface to RGB565 bytes for LCD device."""

    @abstractmethod
    def encode_jpeg(self, surface: Any, quality: int = 95,
                    max_size: int = 450_000) -> bytes:
        """Encode surface to JPEG bytes with size constraint."""

    # ── File I/O ──────────────────────────────────────────────────

    @abstractmethod
    def open_image(self, path: Any) -> Any:
        """Load image file into native surface."""

    # ── Drawing primitives ────────────────────────────────────────

    @abstractmethod
    def fill_rect(self, surface: Any, x: int, y: int,
                  w: int, h: int, color: tuple[int, ...]) -> None:
        """Fill a rectangle on the surface with solid color."""

    @abstractmethod
    def draw_rect_outline(self, surface: Any, x: int, y: int,
                          w: int, h: int, color: tuple[int, ...]) -> None:
        """Draw an unfilled rectangle outline on the surface."""

    @abstractmethod
    def get_pixels_rgb(self, surface: Any, cols: int,
                       rows: int) -> list[list[tuple[int, int, int]]]:
        """Return pixel grid scaled to cols×rows as (r, g, b) tuples.

        Used for ANSI terminal output — cold path, not hot path.
        """

    # ── Legacy boundary ───────────────────────────────────────────

    @abstractmethod
    def from_raw_rgb24(self, frame: "RawFrame") -> Any:
        """Convert RawFrame (RGB24 bytes) → native surface."""


# =========================================================================
# Device ABC — minimal contract for all Thermalright devices (ISP)
# =========================================================================


class Device(ABC):
    """Base device contract — sidebar, CLI, API all depend on this.

    Minimal interface (ISP): only what ALL devices share.
    Brightness is device-type-specific (LCD backlight vs LED strip),
    so it lives on LCDDevice/LEDDevice, not here.

    Concrete implementations:
        - LCDDevice (core/lcd_device.py) — LCD display devices
        - LEDDevice (core/led_device.py) — LED segment display devices
    """

    @abstractmethod
    def connect(self, detected: Any = None) -> dict:
        """Connect to device. Handshakes via protocol, fills DeviceInfo from models.

        Returns: {"success": bool, "message": str, ...}
        """

    @property
    @abstractmethod
    def connected(self) -> bool:
        """Whether device is connected and ready."""

    @property
    @abstractmethod
    def device_info(self) -> Any:
        """DeviceInfo — models hold all device state."""

    @abstractmethod
    def cleanup(self) -> None:
        """Release resources on shutdown."""


# =========================================================================
# Infrastructure port types — injected into services via DI
# =========================================================================

# Type alias for device detection callable.
# Concrete: DeviceDetector.detect
DetectDevicesFn = Callable[[], list[Any]]

# Type alias for LED model probe callable.
# Concrete: probe_led_model
ProbeLedModelFn = Callable[..., Any]


@runtime_checkable
class DeviceProtocol(Protocol):
    """Port: protocol for communicating with a USB device."""

    def handshake(self) -> Any: ...
    def send_image(self, image_data: bytes, width: int, height: int) -> bool: ...


# Type alias for protocol factory callable.
# Concrete: DeviceProtocolFactory.get_protocol
GetProtocolFn = Callable[[Any], DeviceProtocol]

# Type alias for protocol info query callable.
# Concrete: DeviceProtocolFactory.get_protocol_info
GetProtocolInfoFn = Callable[[Any], Any]

# Type alias for data archive extraction callable.
# Concrete: DataManager.ensure_all
EnsureDataFn = Callable[[int, int], None]

# Type alias for DC config file parser factory.
# Concrete: DcConfig (class itself, called as DcConfig(path))
DcConfigFactory = Callable[..., Any]

# Type alias for config.json loader.
# Concrete: dc_parser.load_config_json
LoadConfigJsonFn = Callable[[str], Any]

# Type alias for instance detection callable.
# Concrete: core.instance.find_active
# Returns InstanceKind | None — who currently owns the device.
FindActiveFn = Callable[[], Any]

# Type alias for proxy factory callable.
# Concrete: ipc.create_lcd_proxy / ipc.create_led_proxy
# Takes InstanceKind, returns a proxy object (IPCDisplayProxy, APIDisplayProxy, etc.)
ProxyFactoryFn = Callable[[Any], Any]

# Type alias for theme export callable.
# Concrete: dc_writer.export_theme
ExportThemeFn = Callable[[str, str], None]

# Type alias for theme import callable.
# Concrete: dc_writer.import_theme
ImportThemeFn = Callable[[str, str], None]

# Type alias for privileged command builder.
# Concrete: hardware._privileged_cmd
PrivilegedCmdFn = Callable[[str, list[str]], list[str]]

# Type aliases for platform hardware info callables.
# Concrete: adapters/system/{linux,windows,macos,bsd}/hardware.py
GetMemoryInfoFn = Callable[[], list[dict[str, str]]]
GetDiskInfoFn = Callable[[], list[dict[str, str]]]


@dataclass
class DoctorPlatformConfig:
    """Platform-specific constants for the doctor health check.

    Each OS adapter returns one of these from get_doctor_config().
    doctor.py reads the fields and stays OS-blind.
    """
    distro_name: str
    pkg_manager: Optional[str]
    check_libusb: bool
    extra_binaries: list[tuple[str, bool, str]]   # (name, required, note)
    run_gpu_check: bool
    run_udev_check: bool
    run_selinux_check: bool
    run_rapl_check: bool
    run_polkit_check: bool
    run_winusb_check: bool
    enable_ansi: bool


@dataclass
class ReportPlatformConfig:
    """Platform-specific constants for the diagnostic report.

    Each OS adapter returns one of these from get_report_config().
    debug_report.py reads the fields and stays OS-blind.
    """
    distro_name: str
    collect_lsusb: bool
    collect_udev: bool
    collect_selinux: bool
    collect_rapl: bool
    collect_device_permissions: bool
    get_process_lines_fn: Callable[[], list[str]]


# =========================================================================
# Sensor Enumerator ABC — contract for platform sensor adapters
# =========================================================================


class SensorEnumerator(ABC):
    """Port: hardware sensor discovery and reading.

    Each platform adapter (Linux, Windows, macOS, BSD) implements this ABC
    to provide sensor data via native sources (hwmon, LHM, IOKit, sysctl).

    Concrete implementations:
        - SensorEnumerator (adapters/system/sensors.py) — Linux
        - WindowsSensorEnumerator (adapters/system/windows/sensors.py)
        - MacOSSensorEnumerator (adapters/system/macos/sensors.py)
        - BSDSensorEnumerator (adapters/system/bsd/sensors.py)
    """

    @abstractmethod
    def discover(self) -> list[SensorInfo]:
        """Scan hardware for available sensors. Call once at startup."""

    @abstractmethod
    def get_sensors(self) -> list[SensorInfo]:
        """Return previously discovered sensors."""

    @abstractmethod
    def get_by_category(self, category: str) -> list[SensorInfo]:
        """Filter sensors by category."""

    @abstractmethod
    def read_all(self) -> dict[str, float]:
        """Return current sensor readings (non-blocking, from cache)."""

    @abstractmethod
    def read_one(self, sensor_id: str) -> Optional[float]:
        """Read a single sensor by ID."""

    @abstractmethod
    def start_polling(self, interval: float = 2.0) -> None:
        """Start background polling thread."""

    @abstractmethod
    def stop_polling(self) -> None:
        """Stop background polling thread."""

    @abstractmethod
    def set_poll_interval(self, seconds: float) -> None:
        """Set background poll interval (user's data refresh setting)."""

    @abstractmethod
    def map_defaults(self) -> dict[str, str]:
        """Map legacy metric keys to sensor IDs for overlay rendering.

        Returns dict like {'cpu_temp': 'hwmon:coretemp:temp1', ...}.
        """


# =========================================================================
# Platform Setup ABC — contract for platform-specific setup wizards
# =========================================================================


class PlatformSetup(ABC):
    """Port: platform-specific setup wizard.

    Each platform adapter (Linux, Windows, macOS, BSD) implements this ABC
    to provide its own dependency checks and install steps.

    Concrete implementations:
        - LinuxSetup (adapters/system/setup.py)
        - WindowsSetup (adapters/system/windows/setup.py)
        - MacOSSetup (adapters/system/macos/setup.py)
        - BSDSetup (adapters/system/bsd/setup.py)
    """

    @abstractmethod
    def get_distro_name(self) -> str:
        """Human-readable OS/distro name for the setup header."""

    @abstractmethod
    def get_pkg_manager(self) -> Optional[str]:
        """Detect the native package manager (dnf, winget, brew, pkg, etc.)."""

    @abstractmethod
    def check_deps(self) -> list[Any]:
        """Check all system dependencies. Returns list of DepResult."""

    @abstractmethod
    def run(self, auto_yes: bool = False) -> int:
        """Run the full interactive setup wizard. Returns exit code."""

    @abstractmethod
    def archive_tool_install_help(self) -> str:
        """Platform-specific instructions for installing 7z/p7zip."""

    @abstractmethod
    def config_dir(self) -> str:
        """User config directory (e.g. ~/.trcc/)."""

    @abstractmethod
    def data_dir(self) -> str:
        """User data directory (e.g. ~/.trcc/data/)."""

    @abstractmethod
    def user_content_dir(self) -> str:
        """User-created content directory (e.g. ~/.trcc-user/)."""

    @abstractmethod
    def theme_dir(self, width: int, height: int) -> str:
        """Local theme directory for a resolution."""

    @abstractmethod
    def web_dir(self, width: int, height: int) -> str:
        """Cloud theme web directory for a resolution."""

    @abstractmethod
    def web_masks_dir(self, width: int, height: int) -> str:
        """Cloud masks directory for a resolution."""

    @abstractmethod
    def user_masks_dir(self, width: int, height: int) -> str:
        """User-created masks directory for a resolution."""

    @abstractmethod
    def ffmpeg_install_help(self) -> str:
        """Platform-specific instructions for installing ffmpeg."""

    @abstractmethod
    def resolve_assets_dir(self, pkg_assets_dir: Any) -> Any:
        """Resolve the GUI assets directory for this platform.

        Linux: use package dir directly.
        Others: copy to ~/.trcc/assets/gui/ to avoid sandboxed paths.
        Returns the resolved Path.
        """

    @abstractmethod
    def minimize_on_close(self) -> bool:
        """Return True if the window should minimize to taskbar on close.

        Windows: True — clicking the taskbar X minimizes, second close exits.
        All other platforms: False — close hides to tray.
        """

    @abstractmethod
    def no_devices_hint(self) -> Optional[str]:
        """Platform-specific hint printed when no devices are detected.

        Returns a message string, or None if no extra hint is needed.
        """

    @abstractmethod
    def check_device_permissions(self, devices: list[Any]) -> list[str]:
        """Return list of permission warning messages for detected devices.

        Linux: checks udev rules for each device.
        Other platforms: returns [].
        """

    @abstractmethod
    def get_system_files(self) -> list[str]:
        """Return list of system-level file paths installed by this platform.

        Used by uninstall to remove files that require root.
        Linux: udev rules, modprobe, polkit policy files.
        Other platforms: returns [].
        """

    @abstractmethod
    def get_doctor_config(self) -> DoctorPlatformConfig:
        """Return platform-specific constants for the doctor health check."""

    @abstractmethod
    def get_report_config(self) -> ReportPlatformConfig:
        """Return platform-specific constants for the diagnostic report."""

    @abstractmethod
    def acquire_instance_lock(self) -> object | None:
        """Acquire an exclusive single-instance lock.

        Returns an open file handle on success, or None if another instance
        already holds the lock.
        """

    @abstractmethod
    def raise_existing_instance(self) -> None:
        """Signal the already-running instance to raise its window.

        Linux/macOS/BSD: sends SIGUSR1 to the PID stored in the lock file.
        Windows: no-op (user must switch manually — no POSIX signals).
        """


# =========================================================================
# Autostart Manager ABC — contract for platform-specific autostart mechanisms
# =========================================================================


class AutostartManager(ABC):
    """Port: platform-specific autostart mechanism.

    Each platform adapter implements the four abstract methods.
    The concrete ensure() method provides first-launch auto-enable logic
    shared across all platforms.

    Concrete implementations:
        - LinuxAutostartManager   (adapters/system/linux/autostart.py)   — XDG .desktop
        - WindowsAutostartManager (adapters/system/windows/autostart.py) — winreg Run key
        - MacOSAutostartManager   (adapters/system/macos/autostart.py)   — Launch Agent plist
        - LinuxAutostartManager   reused for BSD (XDG .desktop)
    """

    @staticmethod
    def get_exec() -> str:
        """Resolve full path to trcc binary (shared across all platforms).

        Resolution order:
        1. PyInstaller bundle — sys.executable (trcc.exe / trcc)
        2. pip/pipx install  — shutil.which('trcc')
        3. git clone fallback — PYTHONPATH=<src> python -m trcc.cli
        """
        import shutil
        import sys
        from pathlib import Path

        if getattr(sys, 'frozen', False):
            return sys.executable
        trcc_path = shutil.which('trcc')
        if trcc_path:
            return trcc_path
        src_dir = str(Path(__file__).parent.parent.parent)
        return f'env PYTHONPATH={src_dir} {sys.executable} -m trcc.cli'

    @abstractmethod
    def is_enabled(self) -> bool:
        """Return True if autostart is currently configured."""

    @abstractmethod
    def enable(self) -> None:
        """Register autostart entry for the current user."""

    @abstractmethod
    def disable(self) -> None:
        """Remove autostart entry for the current user."""

    @abstractmethod
    def refresh(self) -> None:
        """Update the autostart entry if the binary path has changed."""

    def ensure(self) -> bool:
        """Auto-enable on first launch; refresh on subsequent launches.

        On first launch: calls enable() and marks config as configured.
        On subsequent launches: calls refresh() to keep path current.
        Returns the current autostart state.
        """
        from ..conf import load_config, save_config

        config = load_config()
        if not config.get('autostart_configured'):
            self.enable()
            config['autostart_configured'] = True
            save_config(config)
            return True

        self.refresh()
        return self.is_enabled()

