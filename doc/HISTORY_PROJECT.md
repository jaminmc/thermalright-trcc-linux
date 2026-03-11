# Project History — How We Got Here

This documents the full journey of building TRCC Linux from scratch, intended as institutional knowledge for the next project (TR-VISION HOME water-cooling LED screen control software). Everything learned here should carry forward.

## The Problem
Thermalright sells CPU coolers and AIO liquid coolers with built-in LCD displays and LED segment displays. The only software to control them (TRCC) is Windows-only, closed-source, with no Linux support. Linux users who bought these coolers had no way to use their displays.

## The Approach: Reverse Engineering Windows C#
The Windows TRCC app was decompiled (ILSpy/dnSpy → `/home/ignorant/Downloads/v2.1.2_decompiled/`). Every protocol, frame format, handshake sequence, and encoding detail was traced from the C# source. Key decompiled files:

- **FormCZTV.cs** — LCD display control (themes, video, resolution, frame encoding)
- **FormLED.cs** — LED segment display control (12 styles, zone carousel, color modes)
- **UCDevice.cs** — Device detection, HID handshake, device enumeration
- **USBLCD.exe / USBLCDNEW.exe** — SCSI and bulk USB LCD frame transfer protocols

The C# code is the ground truth. When our code doesn't match C# behavior, our code is wrong.

## Five USB Protocols Discovered
All Thermalright display devices communicate over USB, but use 5 different protocols depending on the chipset:

| Protocol | Transport | Key Discovery | Tricky Parts |
|----------|-----------|---------------|-------------|
| **SCSI** | sg (SCSI generic) | Frames sent via SG_IO ioctl, chunked writes | Chunk size varies by resolution (0xE100 for 320x240), byte order depends on FBL |
| **HID Type 2** | pyusb interrupt | DA DB DC DD magic header required | Two encoding modes: RGB565 (Mode 3) vs JPEG (Mode 2). Resolution from PM→FBL→table. Non-square displays need 90° CW pre-rotation |
| **HID Type 3** | pyusb interrupt | Fixed 204816-byte frames, ALi chipset | Different handshake and ACK pattern |
| **Bulk** | pyusb bulk | Vendor-specific USB class (not HID) | JPEG encoding only, kernel driver detach issues on SELinux |
| **LY** | pyusb bulk | Chunked 512-byte frames (16-byte header + 496 data) | Two PID variants (LY=0x5408, LY1=0x5409) with different PM formulas and chunk padding |
| **LED** | pyusb HID | 64-byte reports, wire remap tables | Each of 12 device styles has different LED count, segment layout, and wire ordering |

## Resolution Discovery Pipeline (Hardest Problem)
The single biggest source of bugs was resolution. Devices don't report resolution directly — you get a PM (product mode) byte from the handshake, convert it to an FBL (framebuffer layout) code, then look up the resolution. Getting any step wrong cascades into wrong image size, wrong encoding, wrong byte order, and garbled display.

```
Handshake → PM byte → pm_to_fbl() → FBL code → fbl_to_resolution() → (width, height)
                                                                     ↓
                                                        JPEG_MODE_FBLS check → encoding mode
                                                        byte_order_for() → endianness
                                                        _SQUARE_NO_ROTATE check → pre-rotation
```

**FBL table completeness is critical.** Missing FBL values default to (320, 320) which silently produces wrong encoding, wrong byte order, and no pre-rotation. This caused #24 (triple/overlapping images) — FBL 58 was missing.

Current FBL table (16 entries, full C# parity):
```
36→240x240  37→240x240  50→320x240  51→320x240(BE)  53→320x240(BE)
54→360x360  58→320x240  64→640x480  72→480x480  100→320x320(BE)
101→320x320(BE)  102→320x320(BE)  114→1600x720  128→1280x480
192→1920x462  224→854x480/960x540/800x480(PM disambiguates)
```

## RGB565 Encoding Gotchas
- **Byte order varies by device**: 320x320 and SPIMode=2 devices (FBL 51, 53) use big-endian. Everything else uses little-endian. Getting this wrong produces "pop art" color distortion.
- **Pre-rotation**: Non-square LCD panels are physically mounted in portrait. Software must rotate 90° CW before encoding. Square displays skip this.
- **JPEG mode**: Large-resolution devices (360x360+) use JPEG instead of RGB565. Header byte[6] = 0x00 (JPEG) vs 0x01 (RGB565), with actual width/height instead of hardcoded 240x320.
- **Frame headers matter**: Every byte in the protocol header exists for a reason. The DA DB DC DD magic was missing for months — firmware silently rejected frames.

## LED Segment Display Architecture
12 device styles (PA120, AX120, AK120, LC1, LF8, LF10, LF12, CZ1, LC2, LF11, LF13, LF15), each with unique LED counts (30-116), segment layouts, and wire remap tables. Data varies, logic is shared:

- **SegmentDisplay ABC** with 10 subclasses — each defines indices, digit positions, indicator positions, zone maps
- **LEDService** — single renderer that uses the display's data to compute masks
- **Wire remap tables** — C# `SendHidVal` reorders LEDs from logical to hardware positions. Missing remap = colors on wrong physical LEDs
- **Zone carousel (circulate)** — C# `isLunBo`: toggles zones in/out, rotates active zone on timer. Zones drive segment data source (CPU/GPU), not LED color (except styles 2/7 which have physical per-zone LEDs)

## What Worked Well
1. **Hexagonal architecture** — CLI, GUI, and API all adapt to the same core services. Adding the API took hours, not weeks. Device protocols slot in as new adapter subclasses.
2. **C# as ground truth** — every bug we fixed was traced back to "our code doesn't match C#". The decompiled source eliminated guesswork.
3. **Data-driven design** — FBL tables, wire remap tables, LED style configs, segment display layouts are all data. Logic operates on data. New devices = new data, not new logic.
4. **Test suite (4021 tests)** — catches regressions immediately. Every fix includes tests. Mock USB devices for protocol testing.
5. **`trcc report` diagnostic** — users paste one command output and we get VID:PID, PM, FBL, resolution, raw handshake bytes, permissions, SELinux status. Eliminates back-and-forth.
6. **GoF patterns applied pragmatically** — Facade (controllers), Flyweight+Strategy (segment displays), Template Method (protocol handshakes), Memento (LED config), Observer (metrics), Command (dispatchers). Each pattern solved a real problem, not applied for theory.

## What Caused the Most Bugs
1. **Missing FBL/PM mappings** — every new device type needed its entry. Default (320, 320) silently broke everything.
2. **Byte order mismatches** — big-endian vs little-endian RGB565. Two bytes per pixel, wrong order = every color wrong.
3. **Wire remap tables** — one shifted index corrupts every LED after it. Must match C# `SendHidVal` exactly.
4. **Frame headers** — missing magic bytes, wrong command codes, hardcoded dimensions where actual were needed.
5. **State not propagated** — handshake discovers resolution/FBL but the value never reaches the encoding layer. Multiple fixes for "fbl not propagated from handshake."
6. **Linux-specific USB issues** — kernel driver detach, SELinux blocking, polkit for udev rules, UsrMerge symlink differences, XFCE session not "active" in logind.

## Version Evolution (v1.0 → v8.0)
- **v1.x** (17 releases) — Basic GUI, SCSI protocol, theme loading, bug-fixing spree
- **v2.0** — Module rename/restructure, HR10 LED backend, PM/FBL unification
- **v3.0** — Hexagonal architecture, services layer, CLI (Typer), REST API
- **v4.0** — Adapters restructure, domain data consolidation, setup wizard, SELinux support
- **v5.0** — Full C# feature parity audit (35 items), video fit-mode, all LED wire remaps, JPEG encoding for large displays
- **v6.0** — GoF refactoring (-1203 lines), CLI dispatchers, metrics observer, LED test harness, circulate fix, FBL table completion
- **v6.1–v6.2** — REST API full CLI parity (42 endpoints), full wire remap audit (3 styles fixed), LY protocol, TLS, portrait cloud dirs, HiDPI fix
- **v6.3–v6.4** — Codebase minimization, DRY refactoring, test suite expansion
- **v6.5** — IPC daemon (GUI-as-server, CLI auto-routes through Unix socket)
- **v6.6** — LCD preview stream (WebSocket), overlay metrics loop, video playback background thread, MetricsMediator
- **v7.0** — GoF file renames, SOLID refactoring (ISP/LSP/DIP/SRP/OCP), QtRenderer (eliminate PIL from hot path), SOLID Device ABCs (LCDDevice/LEDDevice replace controller layer), cloud theme resolution parity (all 32 C# resolutions), CI distro package dep fixes
- **v8.0** — Hexagonal purification, CPU optimization (-684 lines, 48%→6% CPU), capability classes inlined, DeviceProfile table, test restructuring (hexagonal directory layout)
- **v8.1** — Strict DI (all service constructors RuntimeError without deps), composition roots fully wired, cloud thumbnail blank fix

## Applying This to TR-VISION HOME
The next project controls Thermalright water-cooling LED screens. What carries forward:

1. **Same reverse engineering workflow** — decompile C# → trace protocols → build data tables → implement adapters
2. **Same hexagonal architecture** — core services (pure Python) + adapters (USB, GUI, CLI, API)
3. **Same resolution pipeline pattern** — handshake → product mode → lookup table → encoding parameters
4. **Same RGB565/JPEG encoding** — likely identical frame formats (same vendor firmware)
5. **Same LED segment display logic** — if the water-cooling products have segment displays, the SegmentDisplay ABC + subclass pattern is proven
6. **Same `trcc report` pattern** — diagnostic command that dumps everything needed for remote debugging
7. **Same test infrastructure** — mock USB transports, parametrized device tests
8. **Same deployment** — PyPI package, `pip install`, udev rules, polkit, SELinux support
9. **Same CI** — ruff + pyright + pytest matrix + trusted PyPI publishing on tag push

**Key lesson**: build the data tables first (VID/PID, PM→FBL→resolution, wire remaps, segment layouts). The logic is generic; the data is device-specific. Get the data right and the rest follows.
