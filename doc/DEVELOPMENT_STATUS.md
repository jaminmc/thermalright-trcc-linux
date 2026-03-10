# Development Status

TRCC Linux is **feature-complete** — all 45 features from the Windows TRCC 2.1.2 have been ported, with full CLI/GUI/API parity via hexagonal architecture.

**Current version:** 8.2.3
**Branch:** `main`
**Tests:** 4112 across 57 files in 9 hexagonal directories
**PyPI:** [trcc-linux](https://pypi.org/project/trcc-linux/)

## What's Stable

All features are tested and working on the `main` branch:

- **6 protocol backends** — SCSI, HID, LED, Bulk (raw USB), LY (bulk), IPC (Unix socket)
- **Full GUI** — local/cloud/mask themes, overlays, video playback, carousel, image cropper, video trimmer
- **System info overlays** — 77+ sensors (CPU, GPU, RAM, disk, network, fans)
- **LED RGB control** — 6 effect modes (Static, Breathing, Colorful, Rainbow, Temp-linked, Load-linked), sensor-linked colors, 12 device styles
- **Per-device config** — each LCD remembers its theme, brightness, rotation, overlay, and carousel settings
- **Autostart** — launches minimized to system tray on login, sends last-used theme
- **Setup wizard** — CLI (`trcc setup`) and GUI (`trcc setup-gui`) with bootstrap script (`setup.sh`)
- **CLI** — 50 Typer commands with full service parity (theme, LED, display, overlay, screencast, video, diagnostics, setup)
- **REST API** — 43 endpoints with full CLI parity (`trcc serve`), Pydantic models, uses LCDDevice/LEDDevice from core/
- **IPC daemon** — GUI owns device exclusively; CLI auto-routes through Unix socket when GUI is running
- **Services layer** — 8 pure-Python service classes shared by GUI, CLI, and API
- **Cross-distro compatibility** — tested on Fedora, Debian/Ubuntu, Arch, openSUSE, Void, Alpine, Gentoo, NixOS, SteamOS, Bazzite
- **4112 tests** across 57 test files in hexagonal directory layout (`tests/{core,services,adapters/,cli,api,qt_components}/`)

### Supported Devices

**SCSI devices** — fully supported:
| USB ID | Devices |
|--------|---------|
| `87CD:70DB` | FROZEN HORIZON PRO, FROZEN MAGIC PRO, FROZEN VISION V2, CORE VISION, ELITE VISION, AK120, AX120, PA120 DIGITAL, Wonder Vision |
| `0416:5406` | LC1, LC2, LC3, LC5 (AIO pump heads) |
| `0402:3922` | FROZEN WARFRAME, FROZEN WARFRAME 360, FROZEN WARFRAME SE, ELITE VISION 360 |

**HID LCD devices** — auto-detected:
| USB ID | Devices |
|--------|---------|
| `0416:5302` | Trofeo Vision LCD, Assassin Spirit 120 Vision ARGB, AS120 VISION, BA120 VISION, FROZEN WARFRAME, FROZEN WARFRAME 360, FROZEN WARFRAME SE, FROZEN WARFRAME PRO, ELITE VISION, LC5 |
| `0418:5303` | TARAN ARMS |
| `0418:5304` | TARAN ARMS |

**HID LED devices** — RGB LED control:
| USB ID | Devices |
|--------|---------|
| `0416:8001` | AX120 DIGITAL, PA120 DIGITAL, Peerless Assassin 120 DIGITAL, Phantom Spirit 120 Digital EVO, Assassin X 120R Digital ARGB, HR10 2280 PRO Digital |

**Bulk USB devices** — raw USB protocol:
| USB ID | Devices |
|--------|---------|
| `87AD:70DB` | GrandVision 360 AIO, Mjolnir Vision 360, Wonder Vision Pro 360, Frozen Warframe Pro |

**LY Bulk devices** — chunked bulk protocol:
| USB ID | Devices |
|--------|---------|
| `0416:5408` | Trofeo Vision 9.16 LCD |
| `0416:5409` | (LY1 variant) |

## Roadmap

| # | Item | Status |
|---|------|--------|
| 1 | Full GUI port of Windows TRCC 2.1.2 | Done |
| 2 | Test coverage | Done (4112 tests, 57 files, hexagonal layout) |
| 3 | CI/CD (GitHub Actions) | Done |
| 4 | Type checking (pyright basic) | Done |
| 5 | Cross-distro compatibility | Done |
| 6 | Linting (ruff) | Done — 0 violations |
| 7 | PyPI publish | Done — [trcc-linux](https://pypi.org/project/trcc-linux/) |
| 8 | HID LCD support | Done — auto-detected |
| 9 | LED RGB control | Done — 6 modes, 12 styles, sensor-linked |
| 10 | Bulk USB protocol | Done — GrandVision/Mjolnir Vision |
| 11 | HR10 7-segment display | Removed (v5.1.0) — Linux-only, not in C# reference |
| 12 | On-demand download | Done — 16 resolutions + 33 web archives |
| 13 | Diagnostic report (`trcc report`) | Done |
| 14 | Hexagonal architecture (services layer) | Done — 8 services |
| 15 | CLI Typer refactor | Done — 50 commands |
| 16 | REST API adapter | Done — FastAPI (`trcc serve`) |
| 17 | Unified segment display renderer | Done — 10 styles, OOP class hierarchy |
| 18 | Hexagonal adapters/ restructure | Done — adapters/device, system, infra |
| 19 | Setup wizard (CLI + GUI) | Done — `trcc setup` + `trcc setup-gui` + `setup.sh` |
| 20 | SELinux support | Done — `trcc setup-selinux` + policy module + wizard integration |
| 21 | Windows C# feature parity audit | Done — 45/49 ported, 4 hidden/unreleased |
| 22 | GoF refactoring (5-phase OOP overhaul) | Done — -1203 lines, Facade/Flyweight/Strategy/Template Method/Memento, GoF file renames (v7.0.1), SOLID (v7.0.2) |
| 23 | REST API full CLI parity | Done — 43 endpoints, Pydantic models, uses LCDDevice/LEDDevice |
| 24 | Full wire remap audit (12 LED styles) | Done — styles 2/3/4 fixed, 9 verified correct |
| 25 | LY bulk protocol | Done — `0416:5408` / `0416:5409` |
| 26 | IPC daemon (GUI-as-server) | Done — Unix socket, CLI auto-routes through GUI |
| 27 | Native packages (RPM, DEB, Arch) | Done — CI builds on tag push |
| 28 | Version bump automation | Done — `scripts/bump_version.py` |
| 29 | Type annotation hardening (pyright strict) | Not planned — basic mode with targeted checks is sufficient |
| 30 | SOLID device architecture | Done — ISP (LCDMixin/LEDMixin), LSP, DIP, SRP, OCP (@register decorator) |
| 31 | GoF file renames | Done — 13 files renamed to `{pattern}_{name}.py` format |
| 32 | QtRenderer (eliminate PIL from hot path) | Done — QImage/QPainter for compositing, text, encoding, rotation |
| 33 | Device ABCs (replace controller layer) | Done — LCDDevice/LEDDevice with composed capabilities, ControllerBuilder |
| 34 | Cloud theme resolution parity | Done — all 32 C# v2.1.2 resolutions (landscape + portrait + u/l variants) |
| 35 | CI distro package dependencies | Done — full dep lists in RPM, DEB, Arch inline specs |
| 36 | Strict DI (hexagonal purity) | Done — all service constructors strict, composition roots wire all deps |

## Reporting Issues

If something breaks:
1. Run `trcc report` and copy the output
2. Open an issue at https://github.com/Lexonight1/thermalright-trcc-linux/issues
3. Include your distro, kernel version, and the report output

## See Also

- [SUPPORTED_DEVICES.md](SUPPORTED_DEVICES.md) — full device list with USB IDs
- [CHANGELOG.md](CHANGELOG.md) — version history
- [DEVICE_TESTING.md](DEVICE_TESTING.md) — how to help test devices
- [INSTALL_GUIDE.md](INSTALL_GUIDE.md) — installation for all distros
- [CLI_REFERENCE.md](CLI_REFERENCE.md) — all 50 commands
- [API_REFERENCE.md](API_REFERENCE.md) — all 43 REST API endpoints
- [USBLCD_PROTOCOL.md](audit/USBLCD_PROTOCOL.md) — SCSI protocol (from USBLCD.exe reverse engineering)
- [USBLCDNEW_PROTOCOL.md](audit/USBLCDNEW_PROTOCOL.md) — USB bulk protocol (from USBLCDNEW.exe reverse engineering)
- [USBLED_PROTOCOL.md](audit/USBLED_PROTOCOL.md) — HID LED protocol (from FormLED.cs reverse engineering)
