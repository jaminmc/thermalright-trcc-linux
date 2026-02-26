# TRCC Linux

[![Tests](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/tests.yml/badge.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/tests.yml)
[![Coverage](https://img.shields.io/badge/coverage-96%25-brightgreen.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/tests.yml)
[![PyPI](https://img.shields.io/pypi/v/trcc-linux)](https://pypi.org/project/trcc-linux/)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://python.org)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Buy Me a Beer](https://img.shields.io/badge/Buy_Me_a_Beer-🍺-FF5F5F?style=flat)](https://buymeacoffee.com/Lexonight1)

> If this helped you, could you **[buy me a nice frosty cold one](https://buymeacoffee.com/Lexonight1)**? Huge thanks to **[@javisaman](https://github.com/javisaman)** and **[@Xentrino](https://github.com/Xentrino)** for buying me a beer — you guys are legends.

Native Linux port of the Thermalright LCD Control Center (Windows TRCC 2.0.3). Control and customize the LCD displays and LED segment displays on Thermalright CPU coolers, AIO pump heads, and fan hubs — entirely from Linux.

> **This project wouldn't exist without our testers.** I only own one device. Every supported device in this list works because someone plugged it in, ran `trcc report`, and told me what broke. 20 testers across 6 countries helped us go from "SCSI only" to full C# feature parity with 4 USB protocols, 16 FBL resolutions, and 12 LED styles. Open source at its best — see [Contributors](#contributors) below.

> Unofficial community project, not affiliated with Thermalright. Built with [Claude](https://claude.ai) (AI) for protocol reverse engineering and code generation, guided by human architecture decisions and logical assessment. If something doesn't work on your distro, please **update to the latest version first** (`pip install --upgrade trcc-linux`) — your issue may already be fixed. If it persists, [open an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues).

### Have an untested device?

Run `trcc report` and [paste the output in an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues/new) — takes 30 seconds. See the **[full list of devices that need testers](doc/TESTERS_WANTED.md)**.

![TRCC Linux GUI](doc/screenshots/screenshot.png)

## Features

- **Themes** — Local, cloud, masks, carousel mode, export/import as `.tr` files
- **Media** — Video/GIF playback, video trimmer, image cropper, screen cast (X11 + Wayland)
- **Editor** — Overlay text/sensors/date/time, font picker, dynamic scaling, color picker
- **Hardware** — 77+ sensors, customizable dashboard, multi-device with per-device config, RGB LED control
- **Display** — 15 resolutions (240x240 to 1920x462), 0/90/180/270 rotation, 3 brightness levels
- **Extras** — 5 starter themes + 120 masks per resolution, on-demand download, system tray, auto-start

## Supported Devices

Run `lsusb` to find your USB ID (`xxxx:xxxx` after `ID`), then match it below.

**SCSI devices** — fully supported:
| USB ID | Devices |
|--------|---------|
| `87CD:70DB` | FROZEN HORIZON PRO, FROZEN MAGIC PRO, FROZEN VISION V2, CORE VISION, ELITE VISION, AK120, AX120, PA120 DIGITAL, Wonder Vision |
| `0416:5406` | LC1, LC2, LC3, LC5 (AIO pump heads) |
| `0402:3922` | FROZEN WARFRAME, FROZEN WARFRAME 360, FROZEN WARFRAME SE |

**Bulk USB devices** — raw USB protocol:
| USB ID | Devices |
|--------|---------|
| `87AD:70DB` | GrandVision 360 AIO, Mjolnir Vision 360 |

**HID LCD devices** — auto-detected, needs hardware testers:
| USB ID | Devices |
|--------|---------|
| `0416:5302` | Trofeo Vision LCD, Assassin Spirit 120 Vision ARGB, AS120 VISION, BA120 VISION, FROZEN WARFRAME, FROZEN WARFRAME 360, FROZEN WARFRAME SE, FROZEN WARFRAME PRO, ELITE VISION, LC5 |
| `0418:5303` | TARAN ARMS |
| `0418:5304` | TARAN ARMS |

**HID LED devices** — RGB LED control:
| USB ID | Devices |
|--------|---------|
| `0416:8001` | AX120 DIGITAL, PA120 DIGITAL, Peerless Assassin 120 DIGITAL, Assassin X 120R Digital ARGB, Phantom Spirit 120 Digital EVO, and others (model auto-detected via handshake) |

> HID devices are auto-detected. See the [Device Testing Guide](doc/DEVICE_TESTING.md) if you have one — I need testers.

## Install

### Quick install (PyPI)

```bash
pip install trcc-linux
trcc setup        # interactive wizard — deps, udev, desktop entry
```

Then **unplug and replug the USB cable** and run `trcc gui`.

### One-line bootstrap

Download and run — installs trcc-linux, then launches the setup wizard (GUI if you have a display, CLI otherwise):

```bash
bash <(curl -sSL https://raw.githubusercontent.com/Lexonight1/thermalright-trcc-linux/main/setup.sh)
```

### Setup wizard

After installing, run the setup wizard to configure everything:

```bash
trcc setup        # interactive CLI wizard
trcc setup-gui    # GUI wizard with Install buttons
```

The wizard checks system dependencies, GPU packages, udev rules, and desktop integration — and offers to install anything missing.

### Automatic (recommended for full setup)

```bash
git clone https://github.com/Lexonight1/thermalright-trcc-linux.git
cd thermalright-trcc-linux
sudo ./install.sh
```

Detects your distro, installs system packages, Python deps, udev rules, and desktop shortcut. On PEP 668 distros (Ubuntu 24.04+, Fedora 41+) it auto-falls back to a virtual environment if `pip` refuses direct install.

After it finishes: **unplug and replug the USB cable**, then run `trcc gui`.

### Supported distros

Fedora, Nobara, Ubuntu, Debian, Mint, Pop!_OS, Zorin, elementary OS, Arch, Manjaro, EndeavourOS, CachyOS, Garuda, openSUSE, Void, Gentoo, Alpine, NixOS, Bazzite, Aurora, Bluefin, SteamOS (Steam Deck).

> **`trcc: command not found`?** Open a new terminal — pip installs to `~/.local/bin` which needs a new shell session to appear on PATH.

> See the **[Install Guide](doc/INSTALL_GUIDE.md)** for distro-specific instructions, troubleshooting, and optional deps.

## Usage

```bash
trcc gui                  # Launch GUI
trcc detect               # Show connected devices
trcc send image.png       # Send image to LCD
trcc color "#ff0000"      # Fill LCD with solid color
trcc brightness 2         # Set brightness (1=25%, 2=50%, 3=100%)
trcc rotation 90          # Rotate display (0/90/180/270)
trcc theme-list           # List available themes
trcc theme-load NAME      # Load a theme by name
trcc overlay              # Render and send overlay
trcc screencast           # Live screen capture to LCD
trcc video clip.mp4       # Play video on LCD
trcc led-color "#00ff00"  # Set LED color
trcc led-mode breathing   # Set LED effect mode
trcc serve                # Start REST API server
trcc setup                # Interactive setup wizard (CLI)
trcc setup-gui            # Setup wizard (GUI)
trcc setup-selinux        # Install SELinux USB policy (Bazzite/Silverblue)
trcc doctor               # Check system dependencies
trcc report               # Generate diagnostic report
trcc setup-udev           # Install udev rules
trcc install-desktop      # Install app menu entry and icon
trcc uninstall            # Remove TRCC completely
```

See the **[CLI Reference](doc/CLI_REFERENCE.md)** for all 39 commands, options, and troubleshooting.

## Documentation

| Document | Description |
|----------|-------------|
| [Install Guide](doc/INSTALL_GUIDE.md) | Installation for all major distros |
| [Troubleshooting](doc/TROUBLESHOOTING.md) | Common issues and fixes |
| [CLI Reference](doc/CLI_REFERENCE.md) | All commands, options, and troubleshooting |
| [Changelog](doc/CHANGELOG.md) | Version history |
| [Architecture](doc/ARCHITECTURE.md) | Project layout and design |
| [Technical Reference](doc/TECHNICAL_REFERENCE.md) | SCSI protocol and file formats |
| [USBLCD Protocol](doc/audit/USBLCD_PROTOCOL.md) | SCSI protocol reverse-engineered from USBLCD.exe |
| [USBLCDNEW Protocol](doc/audit/USBLCDNEW_PROTOCOL.md) | USB bulk protocol reverse-engineered from USBLCDNEW.exe |
| [USBLED Protocol](doc/audit/USBLED_PROTOCOL.md) | HID LED protocol reverse-engineered from FormLED.cs |
| [Testers Wanted](doc/TESTERS_WANTED.md) | Devices that need hardware validation |
| [Device Testing Guide](doc/DEVICE_TESTING.md) | Device support and troubleshooting |
| [Supported Devices](doc/SUPPORTED_DEVICES.md) | Full device list with USB IDs |

## Contributors

A big thanks to everyone who has contributed invaluable reports to this project:

- **[Zeltergiest](https://github.com/Zeltergiest)** — Trofeo Vision 360 HID Type 2 testing, detailed bug reports & enhancement suggestions
- **[Xentrino](https://github.com/Xentrino)** — Peerless Assassin 120 Digital ARGB White LED testing across 15+ versions
- **[hexskrew](https://github.com/hexskrew)** — Assassin X 120R Digital ARGB HID testing & GUI layout feedback
- **[javisaman](https://github.com/javisaman)** — Phantom Spirit 120 Digital EVO LED testing & GPU phase validation
- **[Pikarz](https://github.com/Pikarz)** — Mjolnir Vision 360 bulk protocol testing
- **[michael-spinelli](https://github.com/michael-spinelli)** — Assassin Spirit 120 Vision ARGB HID testing & font style bug report
- **[Rizzzolo](https://github.com/Rizzzolo)** — Phantom Spirit 120 Digital EVO hardware testing
- **[N8ghtz](https://github.com/N8ghtz)** — Trofeo Vision HID testing
- **[Lcstyle](https://github.com/Lcstyle)** — HR10 2280 PRO Digital testing
- **[PantherX12max](https://github.com/PantherX12max)** — Trofeo Vision LCD hardware testing
- **[shadowepaxeor-glitch](https://github.com/shadowepaxeor-glitch)** — AX120 Digital hardware testing & USB descriptor dumps
- **[bipobuilt](https://github.com/bipobuilt)** — GrandVision 360 AIO bulk protocol testing
- **[cadeon](https://github.com/cadeon)** — GrandVision 360 AIO bulk protocol testing
- **[gizbo](https://github.com/gizbo)** — FROZEN WARFRAME SCSI color bug report
- **[apj202-ops](https://github.com/apj202-ops)** — Frozen Warframe SE HID testing
- **[Edoardo-Rossi-EOS](https://github.com/Edoardo-Rossi-EOS)** — Frozen Warframe 360 HID testing
- **[edoargo1996](https://github.com/edoargo1996)** — Frozen Warframe 360 HID testing
- **[stephendesmond1-cmd](https://github.com/stephendesmond1-cmd)** — Frozen Warframe 360 HID Type 2 testing
- **[acioannina-wq](https://github.com/acioannina-wq)** — Assassin Spirit 120 Vision HID testing
- **[Civilgrain](https://github.com/Civilgrain)** — Wonder Vision Pro 360 bulk protocol testing

## License

GPL-3.0
