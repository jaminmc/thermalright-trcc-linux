#!/usr/bin/env bash
# TRCC Linux — Bootstrap installer
# Download and run:  curl -sSL <url> | bash
# Or:                wget -qO- <url> | bash
# Or:                bash setup.sh

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

echo "TRCC Linux Setup"
echo "================"
echo

# Check python3
if ! command -v python3 &>/dev/null; then
    echo "ERROR: python3 not found. Install Python 3.10+ first."
    exit 1
fi

# Check pip
if ! python3 -m pip --version &>/dev/null; then
    echo "ERROR: pip not found. Install python3-pip first."
    exit 1
fi

# Determine install source — local repo or PyPI
if [[ -f "$SCRIPT_DIR/pyproject.toml" ]]; then
    install_src="$SCRIPT_DIR"
    echo "Installing from local source: $install_src"
else
    install_src="trcc-linux"
    echo "Installing from PyPI..."
fi

# Install or upgrade trcc-linux
if python3 -c "import trcc" &>/dev/null; then
    ver=$(python3 -c "from importlib.metadata import version; print(version('trcc-linux'))")
    echo "trcc-linux $ver is already installed."
    read -rp "Reinstall/upgrade? [Y/n]: " ans
    if [[ "${ans,,}" != "n" ]]; then
        python3 -m pip install --force-reinstall --no-deps "$install_src"
    fi
else
    echo "Installing trcc-linux..."
    python3 -m pip install "$install_src"
fi

# Launch setup wizard — GUI if display available, CLI otherwise
echo
if [[ -n "${DISPLAY:-}" || -n "${WAYLAND_DISPLAY:-}" ]]; then
    echo "Launching setup wizard (GUI)..."
    exec trcc setup-gui
else
    echo "No display detected — running CLI setup..."
    exec trcc setup
fi
