# TRCC Linux — Lexicon

Shared terminology so everyone uses the same names.

## Devices & Protocols
| Term | Meaning |
|------|---------|
| **SCSI** | USB mass-storage protocol used to send LCD frames (RGB565) |
| **HID** | USB Human Interface Device protocol — handshake, resolution detection |
| **LED** | RGB LED control protocol via HID (effects, colors, zones) |
| **Bulk** | Raw USB vendor-specific bulk transfer protocol (GrandVision/Mjolnir Vision) |
| **LY** | USB bulk protocol for LY-type LCDs (0416:5408/5409), chunked 512-byte frames |
| **PM** | Product Model byte from HID handshake — identifies device variant |
| **FBL** | Firmware Byte Layout — maps PM to screen resolution |
| **PID** | USB Product ID (e.g., `0x5302`, `0x8001`) |
| **VID** | USB Vendor ID — Thermalright is `0x0416` |

## Theme System
| Term | Meaning |
|------|---------|
| **Local theme** | User-saved theme on disk (tab 1) — directory with `00.png`, `config1.dc` |
| **Cloud theme** | Downloadable MP4 video from czhorde.cc servers (tab 2) |
| **Mask** | Overlay layout template downloaded from cloud (tab 3) — `zt{resolution}/` |
| **config1.dc** | Binary overlay config file — text positions, fonts, sensor bindings |
| **Reference theme** | Read-only theme in `Custom_*/` dirs shipped with archives |
| **.tr file** | Theme export/import archive format |

## GUI Components
| Term | Meaning |
|------|---------|
| **UCPreview** | Main preview panel (500x500) showing current LCD frame |
| **UCThemeLocal** | Local themes browser (tab 1) |
| **UCThemeWeb** | Cloud themes browser (tab 2) |
| **UCThemeMask** | Cloud masks browser (tab 3) |
| **UCThemeSetting** | Overlay editor / display mode panels |
| **UCDevice** | Device sidebar with detection and selection |
| **UCLedControl** | LED RGB control panel (all LED styles 1-13, inc. HR10) |
| **UCScreenLED** | LED segment visualization (colored circles) |
| **UCSevenSegment** | 7-segment display preview (HR10) |
| **Carousel** | Auto-rotating theme slideshow |
| **Screencast** | Live screen capture sent to LCD |

## Data Flow
| Term | Meaning |
|------|---------|
| **On-demand download** | Archives fetched from GitHub raw at runtime when not found locally |
| **Theme archive** | `Theme{W}{H}.7z` — bundled theme images per resolution |
| **Web archive** | `{W}{H}.7z` — cloud theme preview PNGs |
| **Mask archive** | `zt{W}{H}.7z` — cloud mask overlay templates |
| **RGB565** | 16-bit pixel format (5R/6G/5B) sent to LCD via SCSI |

## Settings Tab
| Term | Meaning |
|------|---------|
| **`_update_selected(**fields)`** | Single handler for all overlay config changes — updates selected element and propagates |
| **`require_mode`** | Optional guard in `_update_selected` — only applies update if element's `mode` matches |
| **`mode_sub`** | Sub-format selector within a mode (e.g., 0=24H, 1=12H for time) |

## Directories
| Term | Meaning |
|------|---------|
| **DATA_DIR** | Package data dir (`src/trcc/data/` or site-packages equivalent) |
| **USER_DATA_DIR** | User writable data (`~/.trcc/data/`) — primary data location, survives pip upgrades |
| **Config dir** | Application config (`~/.trcc/`) — `config.json`, `trcc.log`, TLS certs, LED probe cache |

## Versioning
| Term | Meaning |
|------|---------|
| **Major** | First digit (`X.0.0`) — breaking changes, major architectural shifts |
| **Minor** | Second digit (`0.X.0`) — new features, device support, significant enhancements |
| **Patch** | Third digit (`0.0.X`) — bug fixes, small corrections, no new features |

## Adapters (Hexagonal Architecture)
| Term | Meaning |
|------|---------|
| **adapters/device/** | USB device protocol handlers (SCSI, HID, LED, Bulk) |
| **adapters/system/** | System integration (sensors, dashboard config) |
| **adapters/infra/** | Infrastructure I/O (data repo, fonts, media, themes, doctor) |
| **services/** | Core hexagon — pure Python business logic, no framework deps. Strict DI — RuntimeError if deps not injected. |
| **install/** | Standalone setup wizard (works without trcc installed) |
| **Composition root** | Code that imports adapters and injects them into services. Only `builder.py`, `lcd_device.py:_build_services()`, CLI functions, and `api/__init__.py` may import adapters. |
| **Strict DI** | Service constructors raise `RuntimeError` if required adapter dependencies are missing. No lazy fallback imports. |
