# Intro
> "I’ll do it while you talk" - Józef Piłsudski, was the founding father of modern Poland
# TRCC Linux
> **Looking for testers!** We need **Linux**, **Windows**, **macOS**, and **BSD** testers. If you have a Thermalright LCD or LED device on any platform, grab the latest [release](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest) and [let us know how it goes](https://github.com/Lexonight1/thermalright-trcc-linux/issues) — run `trcc report` and paste the output in an issue. Every test report helps, even if nothing works yet!

> **Solo hobbyist project** — built in my spare time, one device, no corporate backing. Just a Linux user who got tired of waiting for Thermalright to support us. If something breaks, please be patient — I do this for free because I like helping people. If this project helps you, consider [buying me a beer](https://buymeacoffee.com/Lexonight1) 🍺 or [Ko-fi](https://ko-fi.com/lexonight1) ☕

> **Need help?** [Open a GitHub issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues/new) — that's the only place I see support requests. I don't monitor Reddit, forums, Discord, or Discussions. Run `trcc report` and paste the output so I can actually help you.

[![GitHub Release](https://img.shields.io/github/v/release/Lexonight1/thermalright-trcc-linux?color=green&logo=github)](https://github.com/Lexonight1/thermalright-trcc-linux/releases/latest)
[![PyPI](https://img.shields.io/pypi/v/trcc-linux)](https://pypi.org/project/trcc-linux/)
[![GitHub Downloads](https://img.shields.io/github/downloads/Lexonight1/thermalright-trcc-linux/total?color=blue&logo=github&label=downloads)](https://github.com/Lexonight1/thermalright-trcc-linux/releases)
[![PyPI Downloads](https://img.shields.io/pypi/dm/trcc-linux?label=PyPI%20downloads&color=blue)](https://pypi.org/project/trcc-linux/)
[![License](https://img.shields.io/badge/license-GPL--3.0-green.svg)](LICENSE)
[![Platform](https://img.shields.io/badge/platform-Linux-FCC624?logo=linux&logoColor=black)](https://github.com/Lexonight1/thermalright-trcc-linux)

[![CI](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml/badge.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml)
[![Tests](https://img.shields.io/badge/tests-5325_passed-brightgreen.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml)
[![Coverage](https://img.shields.io/badge/coverage-72%25-brightgreen.svg)](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/ci.yml)
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
[![Ko-fi](https://img.shields.io/badge/Ko--fi-☕-FF5E5B?style=flat&logo=kofi&logoColor=white)](https://ko-fi.com/lexonight1)

> Huge thanks to **[@Reborn627](https://github.com/Reborn627)**, **[@nihilistqueen](https://github.com/nihilistqueen)**, **[@javisaman](https://github.com/javisaman)**, **[@woebygon](https://github.com/woebygon)**, **[@knappstar](https://github.com/knappstar)**, **[@chava-byte](https://github.com/chava-byte)**, **[@loosethoughts19-hash](https://github.com/loosethoughts19-hash)**, **[@rhuggins573-crypto](https://github.com/rhuggins573-crypto)**, **[@Mr-Renegade](https://github.com/Mr-Renegade)**, **[@Xentrino](https://github.com/Xentrino)**, and **[@Smokemic](https://github.com/Smokemic)** for the beers — you guys are legends.

Native Linux port of the Thermalright LCD Control Center (Windows TRCC 2.1.2). Control and customize the LCD displays and LED segment displays on Thermalright CPU coolers, AIO pump heads, and fan hubs — entirely from Linux.

> **This project wouldn't exist without our testers.** I only own one device. Every supported device in this list works because someone plugged it in, ran `trcc report`, and told me what broke. 32 testers helped us go from "SCSI only" to full C# feature parity with 6 USB protocols, 16 FBL resolutions, and 12 LED styles. Open source at its best — see [Contributors](#contributors) below.

> Unofficial community project, not affiliated with Thermalright. Built with [Claude](https://claude.ai) (AI) for protocol reverse engineering and code generation, guided by human architecture decisions and logical assessment.

## Install

### Native packages (recommended)

Pre-built packages are available for every major distro. No pip, no venv, no PEP 668 headaches — just download and install like any other app. Every release is built automatically from source using [GitHub Actions](https://github.com/Lexonight1/thermalright-trcc-linux/actions/workflows/release.yml) — the build logs are public so anyone can verify what went in.

> For detailed step-by-step instructions, troubleshooting, and alternative install methods, see the **[Install Guide](doc/GUIDE_INSTALL.md)**.

| Distro | Install Guide |
|--------|--------------|
| Fedora / Nobara / openSUSE | [Fedora](doc/GUIDE_INSTALL.md#fedora--nobara) |
| Bazzite / Bluefin / Aurora / Universal Blue | [Immutable Fedora](doc/GUIDE_INSTALL.md#bazzite--aurora--bluefin--fedora-atomic) |
| Ubuntu 24.04+ / Debian 13+ / Mint 22+ / Pop!_OS / Zorin | [Ubuntu / Debian](doc/GUIDE_INSTALL.md#ubuntu--debian--mint--pop_os--zorin) |
| Ubuntu 22.04 / Mint 21.x / Debian 12 (older) | [Legacy DEB](doc/GUIDE_INSTALL.md#ubuntu-2204--mint-21x--debian-12-legacy-deb) |
| Arch / CachyOS / Manjaro / EndeavourOS / Garuda | [Arch](doc/GUIDE_INSTALL.md#arch--cachyos--manjaro--endeavouros--garuda) |
| NixOS | [NixOS](doc/GUIDE_INSTALL.md#nixos) |
| Gentoo | [Gentoo](doc/GUIDE_INSTALL.md#gentoo) |
| SteamOS (Steam Deck) | [SteamOS](doc/GUIDE_INSTALL.md#steamos-steam-deck) |
| Windows 10/11 | [Windows](doc/GUIDE_INSTALL.md#windows-experimental) |
| macOS 11+ | [macOS](doc/GUIDE_INSTALL.md#macos-experimental) |
| FreeBSD | [FreeBSD](doc/GUIDE_INSTALL.md#freebsd-experimental) |

Each guide has a one-liner copy-paste command and step-by-step instructions. After installing, unplug and replug the USB cable, then run `trcc gui`.

### Verify your download

Every release includes a `SHA256SUMS.txt` file. Download it from the same release page, then:

```bash
cd ~/Downloads
sha256sum -c SHA256SUMS.txt --ignore-missing
```

If you see `OK` next to your package — it's clean. Source code is GPL-3.0, fully auditable — no binaries, no obfuscation, no telemetry.

### PyPI

Best option for very old distros (Ubuntu 20.04, Debian 11) or if you prefer Python packaging. For Ubuntu 22.04 / Mint 21.x / Debian 12, the [Legacy DEB](doc/GUIDE_INSTALL.md#ubuntu-2204--mint-21x--debian-12-legacy-deb) is easier.

```bash
# Install system dependencies first
sudo apt install pipx libusb-1.0-0 sg3-utils p7zip-full libxcb-cursor0  # Debian/Ubuntu/Mint
sudo dnf install pipx libusb-1.0.0 sg3_utils p7zip                      # Fedora

# Install trcc-linux
pipx install trcc-linux
trcc setup        # interactive wizard — udev rules, desktop entry
```

Then **unplug and replug the USB cable** and run `trcc gui`.

> `pipx` not installed? `sudo apt install pipx` (Debian/Ubuntu), `sudo dnf install pipx` (Fedora), `sudo pacman -S python-pipx` (Arch). See the **[Install Guide](doc/GUIDE_INSTALL.md)** for your distro.

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

> See the **[Install Guide](doc/GUIDE_INSTALL.md)** for distro-specific instructions and troubleshooting.

### Have an untested device?

Run `trcc report` and [paste the output in an issue](https://github.com/Lexonight1/thermalright-trcc-linux/issues/new) — takes 30 seconds. See the **[full list of devices that need testers](doc/TESTERS_WANTED.md)**.

![TRCC Linux GUI](doc/screenshots/screenshot.png)

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

60 commands total — see the **[CLI Reference](doc/REFERENCE_CLI.md)** for the full list.

### REST API

Start the API server and control your devices remotely:

```bash
trcc serve                    # Start on http://localhost:9876
trcc serve --port 8080        # Custom port
trcc serve --tls              # HTTPS with auto-generated self-signed cert
trcc serve --host 0.0.0.0     # Listen on all interfaces (LAN access)
```

55 endpoints covering devices, display, LED, themes, and system metrics. Use `trcc api` to list all endpoints.

```bash
# Examples with curl
curl http://localhost:9876/devices              # List devices
curl -X POST http://localhost:9876/display/send \
  -F "file=@wallpaper.png"                     # Send image
curl -X POST http://localhost:9876/led/color \
  -H "Content-Type: application/json" \
  -d '{"color": "#ff0000"}'                    # Set LED color
```

### Tips

**Mounting your device vertically?**
Set the angle to **90°** (or 270°) in the GUI, then open **Cloud Themes** — the browser will automatically show portrait-orientation themes for your device's rotated dimensions. Download and apply one of those for a proper vertical layout. Local themes are landscape-only; portrait layouts come from the cloud theme packs.

## Documentation

| Document | Description |
|----------|-------------|
| [Install Guide](doc/GUIDE_INSTALL.md) | Installation for all major distros |
| [CLI Reference](doc/REFERENCE_CLI.md) | All CLI commands with options and examples |
| [User Guide](doc/GUIDE_USER.md) | How to use everything — GUI, themes, overlays, media, LED |
| [API Reference](doc/REFERENCE_API.md) | All 55 REST API endpoints with request/response models |
| [Troubleshooting](doc/GUIDE_TROUBLESHOOTING.md) | Common issues and fixes |
| [New to Linux](doc/GUIDE_NEW_TO_LINUX.md) | Guide for Linux beginners |
| [Changelog](doc/CHANGELOG.md) | Version history |
| [Supported Devices](doc/REFERENCE_DEVICES.md) | Full device list with USB IDs and protocols |
| [Testers Wanted](doc/TESTERS_WANTED.md) | Devices that need hardware validation |
| [Device Testing Guide](doc/GUIDE_DEVICE_TESTING.md) | How to test and report device compatibility |
| [Architecture](doc/GUIDE_ARCHITECTURE.md) | Project layout and design |
| [Technical Reference](doc/REFERENCE_TECHNICAL.md) | SCSI protocol and file formats |

### Protocol documentation (reverse-engineered from Windows TRCC)

| Document | Description |
|----------|-------------|
| [USBLCD Protocol](doc/audit/USBLCD_PROTOCOL.md) | SCSI frame transfer protocol |
| [USBLCDNEW Protocol](doc/PROTOCOL_USBLCDNEW.md) | USB bulk/LY frame transfer protocol |
| [USBLED Protocol](doc/PROTOCOL_USBLED.md) | HID LED segment display protocol |

## Features

| Category | What you get |
|----------|-------------|
| **GUI** | Full PySide6 desktop app — theme browser, video player, overlay editor, LED control panel, 38 languages |
| **CLI** | 60 commands — `trcc gui`, `trcc send`, `trcc video`, `trcc led-color`, `trcc screencast`, `trcc shell`, and more |
| **REST API** | 55 endpoints — control everything remotely, build integrations, automate your setup |
| **Themes** | Local, cloud, and masks — carousel mode, export/import as `.tr` files, custom mask upload with X/Y positioning, 5 starters + 120 masks per resolution |
| **Media** | Video/GIF playback on LCD, video trimmer, image cropper, screen cast (X11 + Wayland), mic audio visualization |
| **Overlay Editor** | Text, sensors, date/time overlays — font picker, dynamic scaling, color picker |
| **Hardware Sensors** | 77+ sensors — CPU/GPU temp, fan speed, power, usage — customizable dashboard |
| **LED Control** | 12 LED styles, zone carousel, breathing/rainbow/static/wave modes, per-zone color |
| **Display** | 16 resolutions (240x240 to 1920x462), 0/90/180/270 rotation, 3 brightness levels |
| **Multi-device** | Per-device config, auto-detect, multi-device with device selection |
| **Security** | udev rules, polkit policy, SELinux support, no root required after setup |

**Under the hood**: 147 source files, ~49K lines of Python, 5323 tests across 89 test files in 9 directories. Hexagonal architecture with strict dependency injection — GUI, CLI, and API all talk to the same core services. 6 USB protocols reverse-engineered from the Windows C# app.

### What we do better than Windows TRCC

- **38 languages** — Windows has 10 (baked into PNGs). We render text at runtime, community can add more
- **CLI + REST API** — Windows is GUI-only. We have 60 CLI commands and 55 API endpoints for automation
- **Custom mask upload** — upload your own PNG overlay, position with X/Y controls, saved to `~/.trcc-user/`
- **No admin required** — udev rules handle permissions. Windows needs "Run as Administrator"
- **Open source** — read the code, fix bugs, add features. Windows TRCC is closed-source .NET
- **Screencast on Wayland** — Windows can't do that either
- **Audio visualization** — mic spectrum analyzer on screencast. Windows doesn't have this
- **Hexagonal architecture** — GUI, CLI, and API share the same core. No feature lag between interfaces

### 38-Language GUI (i18n)

The Windows TRCC app ships 10 languages by baking translated text into separate PNG background images — 129 PNGs just for panel labels. We replaced all of that with a runtime i18n system: language-neutral background PNGs + QLabel text overlays rendered from `core/i18n.py`. Switching languages updates every label instantly — no restart, no extra files.

**Supported languages:** Simplified Chinese, Traditional Chinese, English, German, Russian, French, Portuguese, Japanese, Spanish, Korean, Italian, Dutch, Polish, Turkish, Arabic, Hindi, Thai, Vietnamese, Indonesian, Czech, Swedish, Danish, Norwegian, Finnish, Hungarian, Romanian, Ukrainian, Greek, Hebrew, Malay, Bengali, Urdu, Farsi, Tagalog, Tamil, Punjabi, Swahili, Burmese

Adding a new language is one dict entry per string in `core/i18n.py` — no PNG editing, no asset pipeline. Community translations welcome.

### Supported Devices

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

> See the [full device list with protocol details](doc/REFERENCE_DEVICES.md) and the [Device Testing Guide](doc/GUIDE_DEVICE_TESTING.md) if you have an untested device.

## Architecture

```
src/trcc/
├── core/           # Models, enums, domain constants — zero I/O
├── services/       # Business logic — pure Python, no framework deps
├── adapters/       # USB device protocols (SCSI, HID, Bulk, LY, LED)
├── gui/  # PySide6 GUI (themes, video, overlay, LED, sensors)
├── cli/            # Typer CLI — 60 commands across 8 modules
├── api/            # FastAPI REST API — 55 endpoints across 7 modules
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

**Frozen Warframe** — **[gizbo](https://github.com/gizbo)** · **[knappstar](https://github.com/knappstar)** · **[Scifiguygaming](https://github.com/Scifiguygaming)** · **[apj202-ops](https://github.com/apj202-ops)** · **[loosethoughts19-hash](https://github.com/loosethoughts19-hash)** · **[Edoardo-Rossi-EOS](https://github.com/Edoardo-Rossi-EOS)** · **[edoargo1996](https://github.com/edoargo1996)** · **[stephendesmond1-cmd](https://github.com/stephendesmond1-cmd)** · **[riodevelop](https://github.com/riodevelop)** · **[wobbegongus](https://github.com/wobbegongus)** · **[Pallemz](https://github.com/Pallemz)** · **[pawbtism](https://github.com/pawbtism)**

**Trofeo Vision** — **[N8ghtz](https://github.com/N8ghtz)** · **[PantherX12max](https://github.com/PantherX12max)** · **[ravensvoice](https://github.com/ravensvoice)** · **[beret21](https://github.com/beret21)** · **[jimmister1234-bit](https://github.com/jimmister1234-bit)** · **[Tavus1990](https://github.com/Tavus1990)**

**GrandVision 360 AIO** — **[bipobuilt](https://github.com/bipobuilt)** · **[cadeon](https://github.com/cadeon)** · **[Reborn627](https://github.com/Reborn627)** · **[TheManchineel](https://github.com/TheManchineel)**

**Assassin Spirit 120 Vision** — **[michael-spinelli](https://github.com/michael-spinelli)** · **[acioannina-wq](https://github.com/acioannina-wq)**

**Assassin X 120R Digital ARGB** — **[hexskrew](https://github.com/hexskrew)** · **[rhuggins573-crypto](https://github.com/rhuggins573-crypto)**

**Peerless Assassin 120 Digital ARGB** — **[Xentrino](https://github.com/Xentrino)** · **[Vydon](https://github.com/Vydon)**

**PA120 Digital** — **[Pewful2021](https://github.com/Pewful2021)** · **[lallemandgianni-boop](https://github.com/lallemandgianni-boop)** · **[mody446](https://github.com/mody446)**

**Phantom Spirit 120 Digital EVO** — **[javisaman](https://github.com/javisaman)** · **[Rizzzolo](https://github.com/Rizzzolo)** · **[chava-byte](https://github.com/chava-byte)**

**Wonder Vision** — **[Civilgrain](https://github.com/Civilgrain)** · **[Alb3e3](https://github.com/Alb3e3)**

**AX120 Digital** — **[shadowepaxeor-glitch](https://github.com/shadowepaxeor-glitch)**

**Elite Vision 360** — **[tensaiteki](https://github.com/tensaiteki)**

**Mjolnir Vision 360** — **[Pikarz](https://github.com/Pikarz)**

**Peerless Vision** — **[Mr-Renegade](https://github.com/Mr-Renegade)**

**Stream Vision** — **[Me-shok](https://github.com/Me-shok)**

**HR10 2280 PRO Digital** — **[Lcstyle](https://github.com/Lcstyle)**

**General** — **[wrightbyname](https://github.com/wrightbyname)** · **[mog199](https://github.com/mog199)** · **[jezzaw007](https://github.com/jezzaw007)** · **[sleeper14200](https://github.com/sleeper14200)** · **[kabi02](https://github.com/kabi02)** · **[david43](https://github.com/david43)** · **[Deltawolf](https://github.com/Deltawolf)** · **[JoshWrites](https://github.com/JoshWrites)** · **[jun3010me](https://github.com/jun3010me)** · **[Litsas](https://github.com/Litsas)** · **[MoltenMonster](https://github.com/MoltenMonster)** · **[ProfessorJoed](https://github.com/ProfessorJoed)** · **[qwerty22121998](https://github.com/qwerty22121998)** · **[unfirthman](https://github.com/unfirthman)** · **[ux370](https://github.com/ux370)** · **[vlad1](https://github.com/vlad1)**

## Stars

Thanks to everyone who took a moment to star this project.

**[akasvi](https://github.com/akasvi)** · **[alessa-lara](https://github.com/alessa-lara)** · **[ArcaneCoder404](https://github.com/ArcaneCoder404)** · **[azrael1911](https://github.com/azrael1911)** · **[betolink](https://github.com/betolink)** · **[bive242](https://github.com/bive242)** · **[BrunoLeguizamon05](https://github.com/BrunoLeguizamon05)** · **[cancos1](https://github.com/cancos1)** · **[cesarnr21](https://github.com/cesarnr21)** · **[codeflitting](https://github.com/codeflitting)** · **[dabombUSA](https://github.com/dabombUSA)** · **[damachine](https://github.com/damachine)** · **[DasFlogetier](https://github.com/DasFlogetier)** · **[david43](https://github.com/david43)** · **[eap5](https://github.com/eap5)** · **[emaspa](https://github.com/emaspa)** · **[Gdetrane](https://github.com/Gdetrane)** · **[greaseyjockey](https://github.com/greaseyjockey)** · **[gupsterg](https://github.com/gupsterg)** · **[israelsz](https://github.com/israelsz)** · **[jezzaw007](https://github.com/jezzaw007)** · **[jhlasnik](https://github.com/jhlasnik)** · **[jmo808](https://github.com/jmo808)** · **[Jorann](https://github.com/Jorann)** · **[knappstar](https://github.com/knappstar)** · **[Legendarycentaur](https://github.com/Legendarycentaur)** · **[Leonnaki](https://github.com/Leonnaki)** · **[lotte25](https://github.com/lotte25)** · **[mgaruccio](https://github.com/mgaruccio)** · **[michelle0812](https://github.com/michelle0812)** · **[mkogut](https://github.com/mkogut)** · **[nathanielhernandez](https://github.com/nathanielhernandez)** · **[oddajpierscien](https://github.com/oddajpierscien)** · **[okrzanowska](https://github.com/okrzanowska)** · **[PantherX12max](https://github.com/PantherX12max)** · **[Pewful2021](https://github.com/Pewful2021)** · **[Pikarz](https://github.com/Pikarz)** · **[qussaif10](https://github.com/qussaif10)** · **[qwerty22121998](https://github.com/qwerty22121998)** · **[Rehaell](https://github.com/Rehaell)** · **[rhuggins573-crypto](https://github.com/rhuggins573-crypto)** · **[riodevelop](https://github.com/riodevelop)** · **[rslater](https://github.com/rslater)** · **[saucymcbeef](https://github.com/saucymcbeef)** · **[shadowepaxeor-glitch](https://github.com/shadowepaxeor-glitch)** · **[ShaunnyBwoy](https://github.com/ShaunnyBwoy)** · **[Smokemic](https://github.com/Smokemic)** · **[Spebelgenenst](https://github.com/Spebelgenenst)** · **[spiritofjon](https://github.com/spiritofjon)** · **[stephenvalente](https://github.com/stephenvalente)** · **[Thymur](https://github.com/Thymur)** · **[Torotin](https://github.com/Torotin)** · **[urbnywrt](https://github.com/urbnywrt)** · **[Vydon](https://github.com/Vydon)** · **[Xentrino](https://github.com/Xentrino)** · **[YahusRevus](https://github.com/YahusRevus)** · **[Ziusz](https://github.com/Ziusz)**

## Faulkers

Thanks for carrying the torch — these folks forked the repo to build on it.

**[dabombUSA](https://github.com/dabombUSA)** · **[DasFlogetier](https://github.com/DasFlogetier)** · **[jemte](https://github.com/jemte)** · **[jezzaw007](https://github.com/jezzaw007)** · **[taillis](https://github.com/taillis)**

## Donations

If this project saved you from keeping a Windows partition around, consider **[buying me a cold one](https://buymeacoffee.com/Lexonight1)**.

## License

GPL-3.0
