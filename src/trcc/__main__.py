#!/usr/bin/env python3
"""Allow running as: python -m trcc

Sets up crash logging BEFORE any imports — ensures every OS gets
a log file at ~/.trcc/trcc.log even if the app crashes on startup.
"""

import logging
import logging.handlers
import os
import sys
from pathlib import Path

# Early logging — catches import failures, DI errors, platform issues.
# Must run before any trcc imports. All 4 OS's get a log file.
_log_dir = Path.home() / '.trcc'
_log_dir.mkdir(parents=True, exist_ok=True)
_log_path = _log_dir / 'trcc.log'

logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s [%(levelname)s] %(name)s.%(funcName)s: %(message)s',
    datefmt='%Y-%m-%d %H:%M:%S',
    handlers=[
        logging.handlers.RotatingFileHandler(
            _log_path, maxBytes=1_000_000, backupCount=3),
    ],
)
log = logging.getLogger('trcc.main')
log.info("Starting TRCC — platform=%s, executable=%s", sys.platform, sys.executable)

# macOS ``TRCC.app`` (PyInstaller): see ``trcc.core.macos_app_bundle_launch``.

# Windows: ensure libusb-1.0.dll is findable by pyusb (ctypes).
# PyInstaller bundles the DLL next to the exe, but Python 3.8+ on Windows
# doesn't search the exe's directory for ctypes DLLs unless explicitly told.
# Without this, pyusb raises ``NoBackendError: No backend available``.
if sys.platform == 'win32':
    _app_dir = Path(sys.executable).parent
    try:
        os.add_dll_directory(str(_app_dir))
        log.debug("Added DLL search directory: %s", _app_dir)
    except (OSError, AttributeError):
        pass  # add_dll_directory requires Python 3.8+ and a valid dir

try:
    # Auto-launch GUI when invoked as trcc-gui.exe (windowed PyInstaller build)
    if os.path.basename(sys.executable).lower().startswith('trcc-gui'):
        from trcc.cli import gui
        sys.exit(gui() or 0)
    else:
        from trcc.cli import main
        from trcc.core.macos_app_bundle_launch import (
            ONBOARDING_MARKER,
            subcommand_for_bundle_double_click,
        )

        _auto = subcommand_for_bundle_double_click(
            sys.argv,
            platform=sys.platform,
            frozen=getattr(sys, 'frozen', False),
            executable=sys.executable,
        )
        if _auto:
            sys.argv.append(_auto)
        _touch_macos_onboarding = _auto == 'setup-gui'

        _exit_code = main()
        if _touch_macos_onboarding:
            try:
                ONBOARDING_MARKER.touch()
            except OSError as _e:
                log.warning('Could not write macOS .app onboarding marker: %s', _e)
        sys.exit(_exit_code if isinstance(_exit_code, int) else 0)
except Exception:
    log.critical("Fatal startup error", exc_info=True)
    raise
