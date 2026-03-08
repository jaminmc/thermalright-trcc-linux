# TRCC Linux

[![GitHub Release](https://img.shields.io/github/v/release/Lexonight1/thermalright-trcc-linux?color=green&logo=github)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/trcc-linux)](https://pypi.org/project/trcc-linux/)
[![GitHub Downloads](https://img.shields.io/github/downloads/Lexonight1/thermalright-trcc-linux/total?color=blue&logo=github&label=downloads)](https://github.com/Lexonight1/thermalright-trcc-linux/releases)
[![PyPI Downloads](https://img.shields.io/pypi/dm/trcc-linux?label=PyPI%20downloads&color=blue)](https://pypi.org/project/trcc-linux/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)](https://github.com/Lexonight1/thermalright-trcc-linux)

[![CI](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml/badge.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-4034_passed-brightgreen.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-69%25-brightgreen.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml)
[![Python](https://img.shields.io/badge/python-3.9%2B-blue.svg)](https://python.org)
[![Code Style](https://img.shields.io/badge/code_style-ruff-D7FF64?logo=ruff&logoColor=black)](https://docs.astral.sh/ruff/)
[![Type Check](https://img.shields.io/badge/type_check-pyright-blue?logo=python&logoColor=white)](https://microsoft.github.io/pyright/)

[![Stars](https://img.shields.io/github/stars/Lexonight1/thermalright-trcc-linux?style=flat&logo=github)](https://github.com/Lexonight1/thermalright-trcc-linux/stargazers)
[![Forks](https://img.shields.io/github/forks/Lexonight1/thermalright-trcc-linux?style=flat&color=blue&logo=github)](https://github.com/Lexonight1/thermalright-trcc-linux/network/members)
[![Issues](https://img.shields.io/github/issues/Lexonight1/thermalright-trcc-linux?color=orange&logo=github)](https://github.com/Lexonight1/thermalright-trcc-linux/issues)
[![Last Commit](https://img.shields.io/github/last-commit/Lexonight1/thermalright-trcc-linux?color=purple&logo=git&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/commits/main)
[![Code Size](https://img.shields.io/github/languages/code-size/Lexonight1/thermalright-trcc-linux?color=lightgrey&logo=github)](https://github.com/Lexonight1/thermalright-trcc-linux)

**Packages:**

[![Fedora](https://img.shields.io/badge/Fedora-RPM-51A2DA?logo=fedora&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)
[![openSUSE](https://img.shields.io/badge/openSUSE-RPM-73BA25?logo=opensuse&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)

[![Ubuntu](https://img.shields.io/badge/Ubuntu-DEB-E95420?logo=ubuntu&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)
[![Debian](https://img.shields.io/badge/Debian-DEB-A81D33?logo=debian&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)

[![Arch](https://img.shields.io/badge/Arch-pkg.tar.zst-1793D1?logo=archlinux&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)
[![CachyOS](https://img.shields.io/badge/CachyOS-pkg.tar.zst-6B8E23?logo=archlinux&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)
[![Manjaro](https://img.shields.io/badge/Manjaro-pkg.tar.zst-35BF5C?logo=manjaro&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)

[![NixOS](https://img.shields.io/badge/NixOS-flake-5277C3?logo=nixos&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/blob/main/flake.nix)
[![Gentoo](https://img.shields.io/badge/Gentoo-ebuild-54487A?logo=gentoo&logoColor=white)](https://github.com/Lexonight1/thermalright-trcc-linux/tree/main/packaging/gentoo)

[![Buy Me a Beer](https://img.shields.io/badge/Buy_Me_a_Beer-🍺-FF5F5F?style=flat)](https://buymeacoffee.com/Lexonight1)

> Huge thanks to **[@javisaman](https://github.com/javisaman)**, **[@Xentrino](https://github.com/Xentrino)**, **[@loosethoughts19-hash](https://github.com/loosethoughts19-hash)**, **[@Mr-Renegade](https://github.com/Mr-Renegade)**, and **[@Reborn627](https://github.com/Reborn627)** for the beers — you guys are legends.

Native Linux port of the Thermalright LCD Control Center (Windows TRCC 2.1.2). Control and customize the LCD displays and LED segment displays on Thermalright CPU coolers, AIO pump heads, and fan hubs — entirely from Linux.

> **This project wouldn't exist without our testers.** I only own one device. Every supported device in this list works because someone plugged it in, ran `trcc report`, and told me what broke. 29 testers helped us go from "SCSI only" to full C# feature parity with 6 USB protocols, 16 FBL resolutions, and 12 LED styles. Open source at its best — see [Contributors](#contributors) below.

> Unofficial community project, not affiliated with Thermalright. Built with [Claude](https://claude.ai) (AI) for protocol reverse engineering and code generation, guided by human architecture decisions and logical assessment.

### Have an untested device?

Run `trcc report` and [paste the output in an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues/new) — takes 30 seconds. See the **[full list of devices that need testers](doc/TESTERS_WANTED.md)**.

![TRCC Linux GUI](doc/screenshots/screenshot.png)

## Features

| Category | What you get |
|----------|-------------|
| **GUI** | Full PySide6 desktop app — theme browser, video player, overlay editor, LED control panel |
| **CLI** | 50 commands — `trcc gui`, `trcc send`, `trcc video`, `trcc led-color`, `trcc screencast`, and more |
| **REST API** | 43 endpoints — control everything remotely, build integrations, automate your setup |
| **Themes** | Local, cloud, and masks — carousel mode, export/import as `.tr` files, 5 starters + 120 masks per resolution |
| **Media** | Video/GIF playback, video trimmer, image cropper, screen cast (X11 + Wayland) |
| **Overlay Editor** | Text, sensors, date/time overlays — font picker, dynamic scaling, color picker |
| **Hardware Sensors** | 77+ sensors — CPU/GPU temp, fan speed, power, usage — customizable dashboard |
| **LED Control** | 12 LED styles, zone carousel, breathing/rainbow/static/wave modes, per-zone color |
| **Display** | 16 resolutions (240x240 to 1920x462), 0/90/180/270 rotation, 3 brightness levels |
| **Multi-device** | Per-device config, auto-detect, multi-device with device selection |
| **Security** | udev rules, polkit policy, SELinux support, no root required after setup |

**Under the hood**: 106 source files, ~38K lines of Python, 4021 tests across 56 test files in 9 directories. Hexagonal architecture with strict dependency injection — GUI, CLI, and API all talk to the same core services. 6 USB protocols reverse-engineered from the Windows C# app.

## Supported Devices

Run `lsusb` to find your USB ID (`xxxx:xxxx` after `ID`), then match it below.

**SCSI devices** — fully supported:
| USB ID | Devices |
|--------|---------|
| `87CD:70DB` | FROZEN HORIZON PRO, FROZEN MAGIC PRO, FROZEN VISION V2, CORE VISION, ELITE VISION, AK120, AX120, PA120 DIGITAL, Wonder Vision |
| `0416:5406` | LC1, LC2, LC3, LC5 (AIO pump heads) |
| `0402:3922` | FROZEN WARFRAME, FROZEN WARFRAME 360, FROZEN WARFRAME SE, ELITE VISION 360 |

**Bulk USB devices** — raw USB protocol:
| USB ID | Devices |
|--------|---------|
| `87AD:70DB` | GrandVision 360 AIO, Mjolnir Vision 360, Wonder Vision Pro 360, Frozen Warframe Pro |

**LY USB devices** — chunked bulk protocol:
| USB ID | Devices |
|--------|---------|
| `0416:5408` | Trofeo Vision 9.16 LCD |
| `0416:5409` | (LY1 variant) |

**HID LCD devices** — auto-detected:
| USB ID | Devices |
|--------|---------|
| `0416:5302` | Trofeo Vision LCD, Assassin Spirit 120 Vision ARGB, AS120 VISION, BA120 VISION, FROZEN WARFRAME, FROZEN WARFRAME 360, FROZEN WARFRAME SE, FROZEN WARFRAME PRO, ELITE VISION, LC5 |
| `0418:5303` | TARAN ARMS |
| `0418:5304` | TARAN ARMS |

**HID LED devices** — RGB LED control:
| USB ID | Devices |
|--------|---------|
| `0416:8001` | AX120 DIGITAL, PA120 DIGITAL, Peerless Assassin 120 DIGITAL ARGB White, Assassin X 120R Digital ARGB, Phantom Spirit 120 Digital EVO, HR10 2280 PRO Digital, and others (model auto-detected via handshake) |

> See the [full device list with protocol details](doc/SUPPORTED_DEVICES.md) and the [Device Testing Guide](doc/DEVICE_TESTING.md) if you have an untested device.

## Install

### Native packages (recommended)

Pre-built packages are available for every major distro. No pip, no venv, no PEP 668 headaches — just download and install like any other app. Every release is built automatically from source using [GitHub Actions](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/release.yml) — the build logs are public so anyone can verify what went in.

**Step 1:** Go to the [latest release](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest) and download the package for your distro.

> Not sure which distro you're running? Open a terminal and type `cat /etc/os-release` — the `ID` line tells you.

**Step 2:** Open a terminal in your Downloads folder and install:

**Fedora / openSUSE / Nobara:**
```bash
cd ~/Downloads
sudo dnf install ./trcc-linux-*.noarch.rpm
```

**Ubuntu / Debian / Mint / Pop!_OS / Zorin:**
```bash
cd ~/Downloads
sudo dpkg -i trcc-linux_*_all.deb
sudo apt-get install -f    # pulls in any missing dependencies
```

**Arch / CachyOS / Manjaro / EndeavourOS / Garuda:**
```bash
cd ~/Downloads
sudo pacman -U trcc-linux-*-any.pkg.tar.zst
```

**NixOS** — add to your `flake.nix` inputs:
```nix
{
  inputs.trcc-linux.url = "github:Lexonight1/thermalright-trcc-linux";

  # In your system configuration:
  programs.trcc-linux.enable = true;
}
```
Then run `sudo nixos-rebuild switch`.

**Step 3:** Unplug and replug the USB cable, or reboot (this reloads the device permissions).

**Step 4:** Launch the app:
```bash
trcc gui
```

That's it! If your device isn't detected, run `trcc detect --all` to see what's connected, or `trcc report` and [open an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues/new) with the output.

### Verify your download

Every release includes a `SHA256SUMS.txt` file. Download it from the same release page, then:

```bash
cd ~/Downloads
sha256sum -c SHA256SUMS.txt --ignore-missing
```

If you see `OK` next to your package — it's clean. Source code is GPL-3.0, fully auditable — no binaries, no obfuscation, no telemetry.

### PyPI

```bash
pipx install trcc-linux
trcc setup        # interactive wizard — deps, udev, desktop entry
```

Then **unplug and replug the USB cable** and run `trcc gui`.

> `pipx` not installed? `sudo apt install pipx` (Debian/Ubuntu), `sudo dnf install pipx` (Fedora), `sudo pacman -S python-pipx` (Arch). See the **[Install Guide](doc/INSTALL_GUIDE.md)** for your distro.

### One-line bootstrap

```bash
bash <(curl -sSL https://raw.githubusercontent.com/Lexonight1/thermalright-trcc-linux/main/setup.sh)
```

Downloads and installs trcc-linux, then launches the setup wizard.

### Automatic (git clone)

```bash
git clone https://github.com/Lexonight1/thermalright-trcc-linux.git
cd thermalright-trcc-linux
sudo ./install.sh
```

Detects your distro, installs system packages, Python deps, udev rules, and desktop shortcut.

### Supported distros

Fedora, Nobara, Ubuntu, Debian, Mint, Pop!_OS, Zorin, elementary OS, Arch, Manjaro, EndeavourOS, CachyOS, Garuda, openSUSE, Void, Gentoo, Alpine, NixOS, Bazzite, Aurora, Bluefin, SteamOS (Steam Deck).

> **`trcc: command not found`?** Open a new terminal — pip installs to `~/.local/bin` which needs a new shell session to appear on PATH.

> See the **[Install Guide](doc/INSTALL_GUIDE.md)** for distro-specific instructions and troubleshooting.

## Usage

### GUI

```bash
trcc gui
```

Full desktop app with theme browser, video player, overlay editor, LED control panel, and hardware sensor dashboard.

### CLI

```bash
trcc detect               # Show connected devices
trcc send image.png       # Send image to LCD
trcc color "#ff0000"      # Fill LCD with solid color
trcc video clip.mp4       # Play video on LCD
trcc screencast           # Live screen capture to LCD
trcc brightness 2         # Set brightness (1=25%, 2=50%, 3=100%)
trcc rotation 90          # Rotate display (0/90/180/270)
trcc theme-list           # List available themes
trcc theme-load NAME      # Load a theme by name
trcc overlay              # Render and send overlay
trcc led-color "#00ff00"  # Set LED color
trcc led-mode breathing   # Set LED effect mode
trcc report               # Generate diagnostic report
trcc doctor               # Check system dependencies
trcc setup                # Interactive setup wizard
trcc uninstall            # Remove TRCC completely
```

50 commands total — see the **[CLI Reference](doc/CLI_REFERENCE.md)** for the full list.

### REST API

Start the API server and control your devices remotely:

```bash
trcc serve                    # Start on http://localhost:9876
trcc serve --port 8080        # Custom port
trcc serve --tls              # HTTPS with auto-generated self-signed cert
trcc serve --host 0.0.0.0     # Listen on all interfaces (LAN access)
```

43 endpoints covering devices, display, LED, themes, and system metrics. Use `trcc api` to list all endpoints.

```bash
# Examples with curl
curl http://localhost:9876/devices              # List devices
curl -X POST http://localhost:9876/display/send \
  -F "file=@wallpaper.png"                     # Send image
curl -X POST http://localhost:9876/led/color \
  -H "Content-Type: application/json" \
  -d '{"color": "#ff0000"}'                    # Set LED color
```

## Documentation

| Document | Description |
|----------|-------------|
| [Install Guide](doc/INSTALL_GUIDE.md) | Installation for all major distros |
| [CLI Reference](doc/CLI_REFERENCE.md) | All CLI commands with options and examples |
| [Troubleshooting](doc/TROUBLESHOOTING.md) | Common issues and fixes |
| [New to Linux](doc/NEW_TO_LINUX.md) | Guide for Linux beginners |
| [Changelog](doc/CHANGELOG.md) | Version history |
| [Supported Devices](doc/SUPPORTED_DEVICES.md) | Full device list with USB IDs and protocols |
| [Testers Wanted](doc/TESTERS_WANTED.md) | Devices that need hardware validation |
| [Device Testing Guide](doc/DEVICE_TESTING.md) | How to test and report device compatibility |
| [Architecture](doc/ARCHITECTURE.md) | Project layout and design |
| [Technical Reference](doc/TECHNICAL_REFERENCE.md) | SCSI protocol and file formats |

### Protocol documentation (reverse-engineered from Windows TRCC)

| Document | Description |
|----------|-------------|
| [USBLCD Protocol](doc/audit/USBLCD_PROTOCOL.md) | SCSI frame transfer protocol |
| [USBLCDNEW Protocol](doc/audit/USBLCDNEW_PROTOCOL.md) | USB bulk/LY frame transfer protocol |
| [USBLED Protocol](doc/audit/USBLED_PROTOCOL.md) | HID LED segment display protocol |

## Architecture

```
src/trcc/
├── core/           # Models, enums, domain constants — zero I/O
├── services/       # Business logic — pure Python, no framework deps
├── adapters/       # USB device protocols (SCSI, HID, Bulk, LY, LED)
├── qt_components/  # PySide6 GUI (themes, video, overlay, LED, sensors)
├── cli/            # Typer CLI — 50 commands across 8 modules
├── api/            # FastAPI REST API — 43 endpoints across 7 modules
├── conf.py         # Settings singleton
└── assets/         # GUI images, desktop entry, polkit policy, systemd service
```

**Hexagonal architecture** — GUI, CLI, and API are interchangeable adapters over the same core services. Adding a new interface (Android app, Home Assistant plugin) means writing a new adapter, not touching business logic.

**6 USB protocols** reverse-engineered from the Windows C# app:

| Protocol | Transport | Devices |
|----------|-----------|---------|
| SCSI | SG_IO ioctl | Frozen Warframe, Elite Vision, AK/AX120, PA120, LC1-5 |
| HID Type 2 | pyusb interrupt | Trofeo Vision, Assassin Spirit, AS/BA120, Frozen Warframe SE/PRO |
| HID Type 3 | pyusb interrupt | TARAN ARMS |
| Bulk | pyusb bulk | GrandVision 360, Mjolnir Vision 360, Wonder Vision Pro 360, Frozen Warframe Pro |
| LY | pyusb bulk (chunked) | Trofeo Vision 9.16 LCD |
| LED | pyusb HID | All LED segment display devices (12 styles) |

## Contributors

A big thanks to everyone who has contributed invaluable reports to this project:

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
- **[loosethoughts19-hash](https://github.com/loosethoughts19-hash)** — Frozen Warframe Pro bulk protocol testing
- **[Mr-Renegade](https://github.com/Mr-Renegade)** — Peerless Vision LY protocol testing & portrait rotation feedback
- **[Reborn627](https://github.com/Reborn627)** — GrandVision 360 AIO HiDPI scaling & CachyOS testing
- **[tensaiteki](https://github.com/tensaiteki)** — Elite Vision 360 SCSI detection on CachyOS (sg module bug)
- **[wrightbyname](https://github.com/wrightbyname)** — CLI compatibility testing & bug report
- **[Scifiguygaming](https://github.com/Scifiguygaming)** — Frozen Warframe HID testing on CachyOS
- **[mog199](https://github.com/mog199)** — HID Type 2 permission error bug report
- **[ravensvoice](https://github.com/ravensvoice)** — Trofeo Vision portrait cloud theme feature request
- **[rhuggins573-crypto](https://github.com/rhuggins573-crypto)** — Assassin X 120R Digital ARGB LED bug report on Bazzite
- **[knappstar](https://github.com/knappstar)** — Scrambled display bug report & SCSI permission troubleshooting

## Stargazers

Thanks to everyone who took a moment to star this project — it means the world.

**[alessa-lara](https://github.com/alessa-lara)** · **[ArcaneCoder404](https://github.com/ArcaneCoder404)** · **[betolink](https://github.com/betolink)** · **[BrunoLeguizamon05](https://github.com/BrunoLeguizamon05)** · **[cancos1](https://github.com/cancos1)** · **[codeflitting](https://github.com/codeflitting)** · **[dabombUSA](https://github.com/dabombUSA)** · **[damachine](https://github.com/damachine)** · **[emaspa](https://github.com/emaspa)** · **[honjow](https://github.com/honjow)** · **[jezzaw007](https://github.com/jezzaw007)** · **[jhlasnik](https://github.com/jhlasnik)** · **[jmo808](https://github.com/jmo808)** · **[ligmaSec](https://github.com/ligmaSec)** · **[mgaruccio](https://github.com/mgaruccio)** · **[michael-spinelli](https://github.com/michael-spinelli)** · **[nathanielhernandez](https://github.com/nathanielhernandez)** · **[oddajpierscien](https://github.com/oddajpierscien)** · **[Pikarz](https://github.com/Pikarz)** · **[Rehaell](https://github.com/Rehaell)** · **[rslater](https://github.com/rslater)** · **[Smokemic](https://github.com/Smokemic)** · **[spiritofjon](https://github.com/spiritofjon)** · **[Vydon](https://github.com/Vydon)** · **[Xentrino](https://github.com/Xentrino)** · **[Ziusz](https://github.com/Ziusz)**

## Faulkers

Thanks for carrying the torch — these folks forked the repo to build on it.

**[dabombUSA](https://github.com/dabombUSA)** · **[jezzaw007](https://github.com/jezzaw007)** · **[taillis](https://github.com/taillis)**

## Donations

If this project saved you from keeping a Windows partition around, consider **[buying me a cold one](https://buymeacoffee.com/Lexonight1)**.

## License

GPL-3.0
