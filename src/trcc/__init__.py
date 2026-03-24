"""
TRCC Linux - Thermalright LCD Control Center

A Linux implementation of the Thermalright LCD Control Center,
matching the Windows TRCC 2.0.3 protocol.

Features:
- LCD display control via SCSI commands
- System monitoring (CPU, GPU, RAM temperatures)
- Theme support (local, cloud, wallpapers)
- Video and GIF animation playback
- Real-time sensor overlays

Usage:
    # As a library
    from trcc import LCDDriver
    driver = LCDDriver()
    driver.send_frame(image_data)

    # Command line
    trcc-gui          # Launch GUI
    trcc-detect       # Detect LCD device
    trcc-test         # Test display with color cycle
"""

from trcc.__version__ import __version__
from trcc.adapters.device.detector import get_device_path
from trcc.adapters.infra.dc_config import DcConfig
from trcc.adapters.infra.dc_parser import dc_to_overlay_config, parse_dc_file
from trcc.adapters.infra.media_player import VideoDecoder
from trcc.core.models import format_metric
from trcc.services.system import get_all_metrics

__author__ = "TRCC Linux Contributors"


def detect_devices():
    """Detect connected TRCC LCD devices (platform-aware)."""
    from trcc.core.builder import ControllerBuilder
    return ControllerBuilder.for_current_os().build_detect_fn()()


__all__ = [
    # Version
    "__version__",
    # Detection
    "detect_devices",
    "get_device_path",
    # System info
    "get_all_metrics",
    "format_metric",
    # Theme parsing
    "DcConfig",
    "parse_dc_file",
    "dc_to_overlay_config",
    # Animation
    "VideoDecoder",
]
