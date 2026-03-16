#!/usr/bin/env python3
"""Allow running as: python -m trcc"""

import os
import sys

# Auto-launch GUI when invoked as trcc-gui.exe (windowed PyInstaller build)
if os.path.basename(sys.executable).lower().startswith('trcc-gui'):
    from trcc.cli import gui
    sys.exit(gui() or 0)
else:
    from trcc.cli import main
    sys.exit(main())
