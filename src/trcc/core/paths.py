"""Application path constants — single source of truth.

Zero project imports. Safe to import from any module without circular deps.
"""
from __future__ import annotations

import os

# Navigate from core/ back to the trcc package root
_TRCC_PKG = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))

# Asset directories (inside trcc package)
ASSETS_DIR = os.path.join(_TRCC_PKG, 'assets')
RESOURCES_DIR = os.path.join(ASSETS_DIR, 'gui')

# User config directory (~/.trcc/)
USER_CONFIG_DIR = os.path.expanduser('~/.trcc')
USER_DATA_DIR = os.path.join(USER_CONFIG_DIR, 'data')
