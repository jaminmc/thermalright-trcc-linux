# Changelog

## v8.1.0

### Architecture
- **Strict Dependency Injection**: All service constructors now raise `RuntimeError` if required adapter dependencies are not provided. No lazy fallback imports in services — hexagonal purity enforced.
- **Composition roots fully wired**: `builder.py`, `cli/` functions, `api/__init__.py`, and `lcd_device.py:_build_services()` explicitly inject all adapter deps (detector, factory, decoders, DC config, data repository).
- **Services never import adapters**: Only one accepted exception — `SystemService._get_instance()` acts as a mini composition root for the convenience singleton.
- **LCDDevice stores DC deps**: `dc_config_cls` and `load_config_json_fn` injected at construction, used by `render_overlay_from_dc()` and `load_mask_standalone()` without adapter imports.
- **CLI call sites fixed**: `_display.py`, `_led.py`, `_theme.py` all inject concrete adapter deps instead of bare service construction.
- **API call sites fixed**: `api/__init__.py` and `api/themes.py` inject DC deps into OverlayService and ThemeService.
- **LEDDevice wiring**: `led_device.py:initialize()` passes `get_protocol` to LEDService.
- **conftest fixtures**: Shared DI-wired service fixtures in `tests/services/conftest.py`.
- 4021 tests across 56 files in 9 directories

### Bug Fixes
- **Fixed**: Cloud theme thumbnail blank after download — `_on_download_complete()` now calls `_set_movies_running(True)` when panel is visible (QMovie lifecycle fix).

## v8.0.1

### Bug Fixes
- **Fixed**: Theme save missing mask, double overlay, stale state — `load_mask_standalone()` now wires `_mask_source_dir` on DisplayService
- **Fixed**: Saved config.json had `mask: null` — theme reload lost overlay
- **Fixed**: Save was passing overlay-composited image as `00.png` (double overlay on reload)

### Architecture
- **Hexagonal purity (v8.0.0)**: Dependencies point inward only (adapters → services → core). No fallback imports in services. Composition roots wire concrete adapters.
- **Capability classes inlined**: ThemeOps, VideoOps, OverlayOps, FrameOps, DisplaySettings dissolved into LCDDevice directly
- **DeviceProfile table**: Replaces scattered encoding logic with single data-driven lookup
- **CPU optimization**: 34% → 9% idle CPU — eliminated double sensor polling, invisible widget updates, bulk video pre-encoding
- **Test restructuring (v8.0.2)**: 53 test files reorganized into hexagonal directories (`tests/{core,services,adapters/{device,infra,system},cli,api,qt_components}/`). Merged duplicates, dissolved `hid_testing/`, deleted 22 mock-wiring tests.
- 4022 tests across 53 files in 9 directories

## v7.1.1

### Bug Fixes
- **Fixed**: PermissionError on system-wide installs (#51) — `_find_data_dir()`, `get_web_dir()`, `get_web_masks_dir()` fell back to read-only package path (`/usr/lib/python3.x/.../trcc/data/`). Now falls back to `~/.trcc/data/` (user-writable)
- **Fixed**: CodeQL stack-trace-exposure alert (CWE-209) — restructured preview endpoint exception handling

## v7.1.0

### Bug Fixes
- **Fixed**: Scrambled display on bulk USB devices (#54) — `BulkDevice.handshake()` and `LyDevice.handshake()` returned `model_id=PM` instead of `model_id=FBL`. PM=32 mapped to JPEG encoding instead of RGB565, sending JPEG bytes with cmd=3 header
- **Fixed**: Theme not restoring on boot — `_restore_theme()` fallback used `persist=False`, so `--last-one` autostart never saved. Now uses `persist = not saved`
- **Fixed**: Duplicate concurrent handshakes from device poll timer — added `_handshake_pending` guard
- **Fixed**: Per-frame DEBUG log spam (~30/sec) rotated out useful INFO messages within seconds of video playback. Removed hot-path debug logging from display, device, image services, and factory
- **Added**: All C# v2.1.2 bulk PM values to `_BULK_KNOWN_PMS`

## v7.0.10

### Bug Fixes & Cloud Parity
- **Fixed**: Bulk protocol RGB565 encoding — compute `use_jpeg` from protocol+FBL, not mutable field
- **Fixed**: Stack trace exposure in API preview endpoint (CWE-209) — wrapped `_encode_frame` in try/except
- **Fixed**: Missing dependencies in all distro packages (RPM, DEB, Arch inline specs in `release.yml`)
- **Added**: Full C# v2.1.2 cloud theme resolution parity — all 32 resolutions in `theme_cloud.py` RESOLUTION_URLS (landscape, portrait, u/l split variants)
- **Added**: `tools/check_pkg_deps.py` — queries Arch/Fedora/Debian repos to verify PyPI dep availability per distro
- 4157 tests across 56 files

## v7.0.6

### SOLID Device ABCs — Replace Controller Layer
- **Added**: `Device` ABC in `core/ports.py` — 4 methods (connect, connected, device_info, cleanup)
- **Added**: `LCDDevice` in `core/lcd_device.py` — composed capabilities (ThemeOps, VideoOps, OverlayOps, FrameOps, DisplaySettings), each delegates to services
- **Added**: `LEDDevice` in `core/led_device.py` — direct methods (set_color, set_mode, tick, zone/segment ops), delegates to LEDService
- **Added**: `ControllerBuilder` in `core/builder.py` — fluent builder, returns concrete `LCDDevice`/`LEDDevice` types
- **Added**: `TRCCApp` in `qt_components/trcc_app.py` — thin QMainWindow shell (C# Form1 equivalent)
- **Added**: `LCDHandler` in `qt_components/lcd_handler.py` — one per LCD device (C# FormCZTV equivalent)
- **Deleted**: `core/controllers.py` (LCDDeviceController + LEDDeviceController), backward compat aliases (DisplayDispatcher, LEDDispatcher), 197 dead tests
- **Slimmed**: CLI `_display.py` and `_led.py` — thin print wrappers using `_connect_or_fail()` → call device method → print result
- 4157 tests across 56 files

## v7.0.5

### QtRenderer — Eliminate PIL from Hot Path
- **Added**: Expanded `Renderer` ABC in `core/ports.py` — apply_brightness, apply_rotation, encode_rgb565, encode_jpeg, open_image, surface_size
- **Added**: `QtRenderer` in `adapters/render/qt.py` — full QImage/QPainter implementation for compositing, text, rotation, brightness, RGB565/JPEG encoding, font resolution. Zero PIL in hot path
- **Added**: Same new methods in `PilRenderer` (`adapters/render/pil.py`) as fallback
- **Refactored**: `ImageService` is now a thin facade — all methods delegate to `_renderer` via `set_renderer()` / `_r()`. Defaults to QtRenderer
- **Fixed**: Font pixel sizing — `QFont.setPixelSize(size)` instead of `QFont(family, size)` which interprets as points
- **Added**: Test infrastructure — `conftest.py` helpers `make_test_surface()`, `surface_size()`, `get_pixel()`
- 4157 tests across 56 files

## v7.0.4

### API DRY Refactoring
- **Refactored**: Extracted `require_connected()` into `api/models.py` — eliminated 4 duplicated dispatcher guard patterns across `display.py`, `led.py`, `themes.py`
- **Removed**: Unused `HTTPException` import from `led.py`
- 4646 tests across 54 files

## v7.0.3

### Explicit Click Dependency
- **Fixed**: `ModuleNotFoundError: No module named 'click'` on CachyOS — we import `click.exceptions` directly but only declared `typer` (transitive dep). Some install methods don't resolve transitive deps
- **Added**: `click` as explicit dependency in `pyproject.toml` and all 5 distro packaging files (Arch, RPM, DEB, Gentoo)
- Addresses #50
- 4646 tests across 54 files

## v7.0.2

### SOLID Device Architecture
- **ISP**: Split `DeviceProtocol` god interface into `LCDMixin` (send_image, send_pil) + `LEDMixin` (send_led_data) — LCD callers no longer see LED methods and vice versa
- **LSP**: Removed `LedProtocol.send_image()` returning False and `DeviceProtocol.send_led_data()` default — no more lying interfaces
- **DIP**: Injected protocol factory into `DeviceService` via `get_protocol` param + `_get_proto()` method — no more hardcoded imports
- **SRP**: Moved `detect_lcd_resolution()` from `DeviceService` to `ScsiDevice.detect_resolution()` — SCSI-specific code in SCSI adapter
- **OCP**: Added `@DeviceProtocolFactory.register()` decorator for self-registering protocols — new protocols don't edit the factory class
- 4646 tests across 54 files

## v7.0.1

### GoF File Renames
- **Renamed**: 13 files in `adapters/device/` to `{pattern}_{name}.py` format:
  - `factory.py` → `abstract_factory.py`
  - `frame.py` → `template_method_device.py`
  - `hid.py` → `template_method_hid.py`
  - `scsi.py` → `adapter_scsi.py`
  - `bulk.py` → `adapter_bulk.py` (+ `_template_method_bulk.py` base)
  - `ly.py` → `adapter_ly.py`
  - `led.py` → `adapter_led.py`
  - `led_kvm.py` → `adapter_led_kvm.py`
  - `lcd.py` → `facade_lcd.py`
  - `detector.py` → `registry_detector.py`
  - `led_segment.py` → `strategy_segment.py`
  - `hr10.py` → `adapter_hr10.py`
- 4646 tests across 54 files

## v7.0.0

### Major Architecture Overhaul
- GoF file renames (v7.0.1) + SOLID refactoring (v7.0.2) — complete device protocol architecture cleanup
- Every adapter file named by its primary design pattern
- Protocol interfaces properly segregated (ISP), no lying defaults (LSP), factory self-registers (OCP)
- 4646 tests across 54 files

## v6.6.3

### Metrics Mediator + CPU Optimization
- **Added**: `MetricsMediator` — single timer for all sensor polling, replaces per-widget timers
- **Added**: Persistent USB send worker thread (reused across frames, idle timeout 30s)
- **Added**: Preview throttle (4 FPS) to reduce PIL→QPixmap conversions
- **Fixed**: LCD blink bug — identity check was skipping sends when overlay cache hit
- **Added**: `on_frame_sent` callback on `DeviceService` for frame capture (API preview)
- 4496 tests across 54 files

## v6.6.1

### LCD Preview Stream + API Video Control
- **Added**: WebSocket `/display/preview/stream` — steady-fps JPEG stream of LCD frame
- **Added**: Direct IPC frame read from GUI daemon (no poll thread)
- **Added**: Video playback background thread for standalone API mode
- **Added**: Overlay metrics loop for standalone themes
- **Added**: API spec doc + Flutter remote guide
- 4494 tests across 54 files

## v6.5.2

### Video Background Save Fix
- **Fixed**: Custom theme save renamed all video files to `Theme.zt` regardless of format — MP4 files got wrong decoder on reload, causing black screen
- **Fixed**: Save now preserves original video extension (`.mp4` stays `.mp4`, `.zt` stays `.zt`)
- **Added**: Fallback decoder for `.zt` files that fail magic check (handles old broken saves)
- Addresses #42
- 4440 tests across 54 files

## v6.5.1

### CodeQL Fix
- **Fixed**: CodeQL false positive — URL substring check in test replaced with `urlparse().hostname`
- 4440 tests across 54 files

## v6.5.0

### IPC Daemon — GUI-as-Server
- **Added**: Unix domain socket IPC — when GUI is running, it owns USB device exclusively. CLI commands auto-route through socket instead of fighting over device
- **Added**: `IPCServer`, `IPCClient`, `IPCDisplayProxy`, `IPCLEDProxy` in new `src/trcc/ipc.py`
- **Added**: Method whitelist routing with `_DISPLAY_METHODS` and `_LED_METHODS` for security
- **Added**: QSocketNotifier integration for non-blocking socket I/O in Qt event loop
- **Changed**: Info module (sensor metrics bar) decoupled from overlay toggle
- **Added**: `show_info_module` config setting (default: false) in `~/.config/trcc/config.json`
- Addresses #48
- 4440 tests across 54 files

## v6.4.1

### Info Module Decoupling
- **Changed**: Sensor metrics bar visibility no longer tied to overlay enable/disable
- **Added**: `show_info_module` config toggle (default: off)
- 4440 tests across 54 files

## v6.4.0

### Test Suite Expansion
- **Added**: 1995 new tests (2445 → 4440), 18% coverage increase (58% → 76%), 15 new test files (39 → 54)
- **Added**: Session-scoped `qapp` fixture for headless Qt testing
- **Added**: `@pytest.fixture` patterns with `autouse=True` for module-wide mocking
- 4440 tests across 54 files

## v6.3.7

### Codebase Minimization
- **Refactored**: Trimmed 694 lines of shipped source — collapsed glue code, generic dispatch helpers
- 4440 tests across 54 files

## v6.3.6

### CLI-Centric Simplification
- **Refactored**: Generic dispatch helpers collapse CLI glue code
- 2523 tests across 39 files

## v6.3.5

### DRY Refactoring
- **Refactored**: USB Device Factory, shared API helpers, LED dispatcher cleanup
- 2523 tests across 39 files

## v6.3.4

### Bug Fixes
- **Fixed**: Minor fixes and improvements
- 2523 tests across 39 files

## v6.3.3

### Single-Instance Window Raise
- **Improved**: Second `trcc gui` launch raises existing window instead of silently exiting — uses lock file + signal
- 2523 tests across 39 files

## v6.3.2

### Device Button Image & Product Name Resolution
- **Improved**: PM-based device button image selection after handshake (C# `SetButtonImage` parity)
- **Improved**: Product name resolution from PM byte — sidebar button shows correct product name instead of generic VID:PID label
- 2523 tests across 39 files

## v6.3.1

### Device Naming Fix
- **Fixed**: Device naming for `0402:3922` — now shows "Frozen Warframe / Elite Vision" instead of hardcoded "FROZEN WARFRAME". Both products share the same USB ID. Vendor corrected from "ALi Corp" to "Thermalright".
- Addresses #46
- 2523 tests across 39 files

## v6.3.0

### SOLID Refactoring
- **Refactored**: Data-driven protocol configuration — protocol parameters (chunk sizes, headers, encoding modes) stored as data instead of scattered across code branches
- **Refactored**: Dependency inversion across adapters — constructor injection, ABC ports at boundaries
- **Refactored**: SRP splits across oversized modules
- 2523 tests across 39 files

## v6.2.5

### SCSI Detection Fix (CachyOS/Arch)
- **Fixed**: SCSI detection on distros without `sg` kernel module — CachyOS, Arch, and others don't autoload `sg`, so `/dev/sg*` doesn't exist even when the device is connected
- **Added**: Block device fallback — detector now tries `/dev/sd*` with USBLCD vendor check when `/dev/sg*` is unavailable (`SG_IO` ioctl works on both)
- **Added**: `trcc setup-udev` writes `/etc/modules-load.d/trcc-sg.conf` to autoload `sg` on boot + loads it immediately
- **Refactored**: `_resolve_usblcd_vid_pid()` extracted to DRY the vendor/product check
- Addresses #46
- 2517 tests across 39 files

## v6.2.4

### DRY Refactoring
- **Refactored**: `parse_hex_color()` → `core/models.py` — was duplicated in CLI, API display, and API LED modules
- **Refactored**: `dispatch_result()` → `api/models.py` — was duplicated in API display and API LED modules
- **Refactored**: `ImageService.encode_for_device()` → `services/image.py` — Strategy pattern, was duplicated in device service and display service
- 16 files changed, -50 net lines of duplicated logic, +28 tests with fixtures
- 2509 tests across 39 files

## v6.2.3

### HiDPI Scaling & Theme Restore Fix
- **Fixed**: HiDPI scaling override — force-set `QT_ENABLE_HIGHDPI_SCALING=0` to prevent GUI layout corruption on HiDPI displays (CachyOS, KDE Plasma)
- **Fixed**: Stale background path on custom theme restore — saved themes with deleted backgrounds showed black instead of falling back gracefully
- Addresses #42
- 2481 tests across 39 files

## v6.2.2

### LY Protocol Integration & PM/FBL Overrides
- **Fixed**: LY protocol integration gaps — GUI poll, JPEG encoding, udev rules, display path, and debug report all missed `ly` protocol type. 7 code paths that branched on protocol string now include LY.
- **Added**: PM→FBL overrides (PM 13-17, 50, 66, 68, 69) + FBL 192/224 disambiguation from C# v2.1.2
- **Refactored**: `discover_resolution()` extracted for unified PM→FBL→resolution pipeline
- Addresses #45
- 2481 tests across 39 files

## v6.2.1

### `trcc api` CLI Command
- **New**: `trcc api` command — lists all 41 REST API endpoints with method, path, and description
- 2445 tests across 39 files

## v6.2.0

### REST API Static File Serving
- **New**: Serve theme/web/mask images via REST API `StaticFiles` — resolution-aware mounts on device select
- **New**: `GET /themes/web` and `GET /themes/masks` endpoints
- **New**: `ThemeResponse` includes `preview_url`, `WebThemeResponse` and `MaskResponse` models
- 2445 tests across 39 files

## v6.1.10

### FastAPI Base Dependencies
- **Changed**: Moved `fastapi` + `uvicorn` from optional `[api]` extra to base dependencies — REST API is always available, no separate install needed
- Prepares for Android companion app integration
- 2439 tests across 39 files

## v6.1.9

### TLS Support for REST API
- **New**: `--tls` flag auto-generates self-signed certificate for HTTPS
- **New**: `--cert` / `--key` flags for custom TLS certificates
- **New**: Plaintext token warning when running without TLS
- 2439 tests across 39 files

## v6.1.8

### LY Protocol Support
- **New**: LY protocol handler for `0416:5408` (Peerless Vision) and `0416:5409` (variant) — chunked 512-byte bulk transfer with 16-byte header + 496 data bytes
- **New**: `LyDevice` class with handshake, PM extraction, and JPEG frame encoding from TRCC v2.1.2 `USBLCDNEW.dll`
- **New**: Two PID variants with different PM formulas (LY: `64+resp[20]`, LY1: `50+resp[36]`)
- Addresses #45
- 2439 tests across 39 files

## v6.1.7

### Bulk Encoding, HiDPI & Theme Background Fix
- **Fixed**: Bulk PM=32 distorted colors — `use_jpeg` DTO field wasn't propagated, raw RGB565 sent when device expected JPEG
- **Fixed**: HiDPI GUI scaling — set `QT_ENABLE_HIGHDPI_SCALING=0` environment variable before Qt init
- **Fixed**: Black background on saved custom themes — `background_path` was null when theme had no explicit background
- 2408 tests across 39 files

## v6.1.6

### RAPL Power Sensor Permissions
- **Added**: RAPL power sensor permission check and fix in `trcc setup` pipeline — Intel CPU power sensors (`/sys/class/powercap/intel-rapl/`) need read permission for non-root users
- 2399 tests across 39 files

## v6.1.5

### Portrait Cloud Directory Fix
- **Fixed**: Non-square displays (e.g. 1280x480 Trofeo Vision) mounted vertically were loading cloud backgrounds/masks from the landscape directory instead of portrait directory
- **Added**: `Settings.resolve_cloud_dirs(rotation)` — swaps width/height for web_dir and masks_dir when rotation is 90/270 on non-square displays
- Addresses #1
- 2399 tests across 39 files

## v6.1.4

### LED GUI Settings & Theme Restore Fix
- **Fixed**: LED GUI settings not syncing on startup — `load_config()` correctly restored LED state from `config.json` (effects worked), but `panel.initialize()` reset all controls to defaults. Added `_sync_ui_from_state()` to push loaded state into UI controls after initialization.
- **Fixed**: `--last-one` theme restore overwriting saved preference — auto-fallback (first available theme when saved path missing) was persisting to config via `_select_theme_from_path()`, silently overwriting the user's saved theme. Now fallback loads for display only (`persist=False`).
- Note: v6.1.3 was the original release; v6.1.4 is a re-release because PyPI rejects reuse of version+filename after a tag was moved.
- Addresses #15
- 2394 tests across 34 files

## v6.1.2

### AK120 & LC1 LED Wire Remap Fix
- **Fixed**: AK120 (style 3) LED wire remap — all 64 entries wrong, indices up to 68 (beyond valid range 0-63). Same root cause as v6.1.1: remap tables built using constructor default `UCScreenLED` indices instead of style-specific `ReSetUCScreenLED3()` overrides.
- **Fixed**: LC1 (style 4) LED wire remap — 29 of 31 entries wrong, indices up to 37 (beyond valid range 0-30). Same root cause, `ReSetUCScreenLED4()` overrides not applied.
- **Improved**: Tightened remap range guard test (`test_all_remap_indices_in_range`) — checks `idx < style.led_count` to catch this class of bug automatically.
- 2394 tests across 34 files

## v6.1.1

### PA120 LED Wire Remap Fix
- **Fixed**: PA120 (style 2) LED wire remap — was built using default `UCScreenLED` class indices (Cpu1=2, Cpu2=3, SSD=6, HSD=7, BFB=8, digits start at 9) instead of PA120-specific `ReSetUCScreenLED2()` indices (Cpu1=0, Cpu2=1, SSD=4, HSD=5, BFB=6, digits start at 10). Every indicator and first 3 digit segments mapped to wrong wire positions — cut-off numbers and missing % signs on physical display.
- Addresses #15
- 2393 tests across 34 files

## v6.1.0

### REST API Full CLI Parity
- **New**: Refactored `api.py` → `api/` package (7 modules): `__init__`, `models`, `devices`, `display`, `led`, `themes`, `system`
- **New**: 28 new endpoints (35 total): display (8), LED (14), themes (4), system (3), devices (6)
- **New**: 16 Pydantic request/response models for type-safe API contracts
- **Architecture**: Reuses `DisplayDispatcher` + `LEDDispatcher` from CLI — zero duplicated business logic. Device select auto-initializes the right dispatcher. 409 Conflict if no device selected when calling display/LED endpoints.
- 67 API tests (44 new), 2393 tests across 34 files

## v6.0.6

### FBL Resolution Table Completion
- **Fixed**: Triple/overlapping images on Frozen Warframe SE (PM=58, FBL=58) — FBL 58 was missing from `FBL_TO_RESOLUTION` table, defaulting to 320x320 instead of 320x240. Wrong resolution cascaded into: no pre-rotation (square displays skip it), big-endian byte order (320x320 triggers it for HID), and 33% too much pixel data sent. Addresses #24.
- **Added**: FBL 53 → (320, 240) with big-endian byte order (HID Type 3 SPIMode=2) — completes FBL table to full C# parity (16 entries)
- 2349 tests across 34 files

## v6.0.5

### LED Circulate Rotation & Color Fix
- **Fixed**: LED circulate not rotating zones — `zone_sync_zones` was never initialized in `configure_for_style()`, stayed empty, so zone toggles during circulate silently failed
- **Fixed**: Color/mode not applied during circulate — C# uses global `rgbR1`/`myLedMode` for non-2/7 styles (zones only drive segment data rotation, not LED color), but `tick()` was reading per-zone color
- **Fixed**: Color/mode routing to always set global state (C# always sets `rgbR1`/`G1`/`B1` + per-zone)
- 2349 tests across 34 files

## v6.0.4

### LED Circulate Zone Buttons
- **Fixed**: Zone buttons now toggle zones in/out when circulate is active (C# radio-select sets clicked zone, user adds more by clicking buttons)
- **Fixed**: Interval input fires on every keystroke (`textChanged`, not `editingFinished`), default 2 seconds matching C#
- **Fixed**: Accurate seconds-to-ticks formula (`round(s*1000/150ms)`)
- **Fixed**: Zone uncheck guard (can't disable last zone)
- **Fixed**: Select All not propagating mode changes to all zones (PA120/LF10)
- **Fixed**: `zone_sync_interval` default (36→13 ticks = 2 seconds)
- 2349 tests across 34 files

## v6.0.3

### LF13 & PA120 Segment Fixes
- **Fixed**: LF13 (style 12) LED preview — DLF13 overlay had opaque black center covering the LED color fill, made center transparent so colors show through
- **Fixed**: LF13 mode numbering — rainbow image shown for Temp Linked (mode 4) instead of Rainbow (mode 3) due to C# 1-based vs our 0-based mode indexing
- **Fixed**: PA120 segment display indices — off-by-one from C# (indicators at 2-8 instead of 0-9, digits starting at 9 instead of 10). GPU indicators SSD1/HSD1/BFB1 were aliased to CPU indices — now have own positions. Zone coverage 81→84/84.
- **Improved**: LED test harness — real LEDService for segment rendering, zone-aware signal wiring matching LEDHandler
- 2349 tests across 34 files

## v6.0.2

### Video Persistence & CLI Error Handling
- **Fixed**: Video background not persisting after reboot — `ThemeService.save()` stored video path pointing to temp dir (`/tmp/trcc_work_*/Theme.zt`), now copies video into theme directory as `Theme.zt` so it survives reboots. Addresses #34.
- **Improved**: CLI graceful errors — catch typos and usage errors (missing args, bad types, unknown commands) with clean one-liner + "Did you mean?" suggestions instead of Python tracebacks
- 2349 tests across 34 files

## v6.0.1

### CLI Dispatchers & Metrics Observer
- **New**: `LEDDispatcher` + `DisplayDispatcher` classes — single authority for programmatic LED/LCD operations. Return result dicts (never print). CLI functions are thin presentation wrappers. GUI and API can import dispatchers directly.
- **New**: `--preview` / `-p` flag on all LCD and LED CLI commands — renders ANSI true-color art in terminal for headless/SSH users (`ImageService.to_ansi()`, `LEDService.zones_to_ansi()`)
- **New**: `UCLedControl.update_metrics()` — Observer pattern. Panel subscribes to metrics and dispatches to style-specific update methods internally. `qt_app_mvc._poll_sensors()` reduced from 15-line if/elif chain to 2 lines.
- **New**: LED visual test harness (`tests/test_led_panel_visual.py`) — standalone Qt app for testing all 12 LED device styles with live metrics, device buttons, index overlay, and full signal wiring
- **Fixed**: Color wheel mirror (flip canvas horizontally to match C# gradient)
- **Fixed**: SCSI 320x240 chunk size (`0x10000` → `0xE100` matching C# USBLCD.exe Mode 1/2)
- **Refactored**: CLI shared utilities — `_parse_hex()`, `_MODE_MAP` class constant, `@_cli_handler` decorator consistency
- 2349 tests across 34 files

## v6.0.0

### GoF Refactoring — 5-Phase OOP Overhaul
- **Phase 1**: Segment display collapse — `led_segment.py` 1109→687 lines (-38%). Properties→class attrs, 4 encode methods→unified `_encode_digits()` + `_encode_7seg()`, LF12 delegates to LF8. Flyweight + Strategy patterns.
- **Phase 2**: HID subclasses — SKIPPED (logic genuinely differs between Type2/Type3, ~20 line savings not worth it)
- **Phase 3**: Controller layer elimination — `controllers.py` 699→608 lines (-91). Deleted 5 thin wrapper controllers (ThemeController, DeviceController, VideoController, OverlayController, LEDController). LCDDeviceController = Facade over 4 services (~35 methods). LEDDeviceController absorbed LEDController. ~50 GUI call sites rewritten, 7 test files updated. Law of Demeter enforced: GUI→Facade→Services only. Facade pattern.
- **Phase 4**: UsbProtocol base — `factory.py` 874→846 lines (-28). Extracted shared transport lifecycle (open/close/ensure) from HidProtocol + LedProtocol into `UsbProtocol` base class. Template Method pattern.
- **Phase 5**: LED config serialization — `services/led.py` save/load driven by `_PERSIST_FIELDS` dict + `_ALIASES` dict. Single source of truth for which fields persist. Memento pattern.
- **Total**: 24 files changed, -1203 net lines
- 2306 tests across 34 files

## v5.3.3

### Polkit & Sudo Fix
- **Fixed**: `_sudo_reexec` now includes user site-packages in PYTHONPATH (sudo strips `~/.local/lib/`)
- **Fixed**: `os.path.realpath()` for binary paths in polkit (UsrMerge symlink canonicalization)
- **Fixed**: JavaScript `.rules` file for cross-DE polkit support (XFCE `allow_active=yes` doesn't work)
- **Fixed**: `restorecon` after file writes for SELinux context reset
- **Fixed**: `pkexec` uses absolute binary paths
- 2291 tests across 34 files

## v5.3.2

### DRY Refactor
- Extract shared helpers from 7 duplicate patterns across 5 files
- -67 net lines
- 2291 tests across 34 files

## v5.3.1

### LED Mask & Zone Fix
- **Fixed**: LED mask_size (AK120 64, LC1 31) — was wrong for some device models
- **Fixed**: LED zone_count for styles 9/12 → 0 (no zone cycling)
- 2291 tests across 34 files

## v5.3.0

### Full Data Flow Audit
- **Fixed**: API encoding path for REST adapter
- **Fixed**: SCSI FBL 50 byte order correction
- **Fixed**: FBL code propagation from handshake through entire pipeline
- 2291 tests across 34 files

## v5.2.3

### FBL Propagation Fix
- **Fixed**: `fbl_code` not propagated from handshake to device info — resolution was falling back to default
- 2288 tests across 34 files

## v5.2.2

### HID Diagnostics
- HID frame timeout scaling for large-resolution devices
- `--test-frame` flag for `hid-debug` — sends a solid color test frame
- SCSI raw bytes in `trcc report` for protocol debugging
- 2286 tests across 34 files

## v5.1.1

### OOP/KISS Refactor
- `cli.py` → `cli/` package (6 submodules)
- DcWriter class → module functions
- Controller `__getattr__` delegation (LEDController 26→6 methods, OverlayController 19→5)
- LEDEffectEngine Strategy extraction
- Hardware info → `adapters/system/hardware.py`
- Net -69 lines
- 2286 tests across 34 files

## v5.1.0

### Remove HR10 NVMe Support
- Removed HR10 NVMe temperature daemon — Linux-only feature, not in C# reference, broken preview
- -1762 lines removed
- LED styles 1-12 (13 removed)
- 2286 tests across 34 files

## v5.0.10

### LED & Bulk Fixes
- **Fixed**: LED static/load-linked timeout (remove skip-unchanged keepalive)
- **Fixed**: Font style bold/italic passthrough from QFontDialog
- **Fixed**: Bulk rotation regression (skip pre-rotation for JPEG)
- 2372 tests across 35 files

## v5.0.9

### LED GUI Overhaul
- Match C# FormLED exactly — memory/disk panels at C# positions with golden text
- Fix LF13 background_base localization
- Fix sensor gauge visibility (only hide for styles 4/10)
- Remove Linux-only CPU/GPU source toggle
- HR10 renders as standard LED panel
- GPU LED phase rotation fix
- 2372 tests across 35 files

## v5.0.8

### HID Type 2 Color & Rotation Fix
- **Fixed**: RGB565 byte order wrong for HID Type 2 devices at 320x240 — was sending big-endian, device expects little-endian. C# only uses big-endian for `is320x320` (FBL 100-102), not for HID at other resolutions
- **Fixed**: Non-square displays (320x240, etc.) missing 90° CW pre-rotation — LCD panels are physically portrait-mounted, C# `ImageTo565` rotates before encoding. Added `apply_device_rotation()` to both `DisplayService` and `DeviceService` send paths
- Affects: Frozen Warframe 360 HID Type 2 (`0416:5302`), Assassin Spirit 120 Vision ARGB (#28, #16)
- 2359 tests across 35 files

## v5.0.7

### PA120 LED Segment Display Fix
- **Fixed**: PA120 wire remap table had SSD/HSD/C11/B11 displaced to end, shifting zones 4+ by 4 positions
- **Fixed**: PA120Display indices didn't match C# (indicators 0-9 vs 2-8, digit 1 at 10 vs 9)
- 2359 tests across 35 files

## v5.0.6

### Video Hot Path Optimization
- Commit Renderer ABC + PilRenderer for display pipeline
- Delete dead files, clean up unused code
- 2359 tests across 35 files

## v5.0.5

### FBL 50 Resolution & Overlay Caching Fix
- **Fixed**: FBL 50 resolution was 240x320 (wrong) — corrected to 320x240
- **Fixed**: Overlay caching not invalidating on element changes
- **Fixed**: Cloud theme download path resolution
- 2395 tests across 35 files

## v5.0.4

### HID Type 2 Frame Header Fix
- **Fixed**: HID Type 2 frame header was sending all-zero 16-byte prefix — device firmware expects `DA DB DC DD` magic + command type (`0x02`) + mode flags matching C# `FormCZTV.ImageTo565()` mode 3. Without the magic, firmware rejects frames causing USB disconnect (#16) or stuck-on-logo (#28)
- Affects all HID Type 2 LCD devices (`0416:5302`): Assassin Spirit, Frozen Warframe, etc.
- 2353 tests across 35 files

## v5.0.3

### LED Wire Remap & SCSI Byte Order Fix
- **Fixed**: LED wire remap skipped — `LEDService.initialize()` never called `protocol.handshake()`, so style info was never cached and wire remap was silently skipped. Affects all LED devices (#19 Phantom Spirit EVO, #15 PA120)
- **Fixed**: SCSI byte order — removed 240x320 from big-endian set (C# FBL 50 uses little-endian, not SPIMode=2)
- **Added**: SCSI handshake section in `trcc report` (FBL byte + resolution) for resolution diagnostics (#17)
- 2352 tests across 35 files

## v5.0.0 — v5.0.2

### Complete Windows C# Feature Parity
- v5.0.0: Full gap audit — 35 items resolved (wire remap, zone carousel, LED test mode, DDR multiplier, split mode, video fit-mode, DRAM/SMART info, SPI byte order)
- v5.0.1: Fix SELinux detection without root (sesearch fallback)
- v5.0.2: Fix LED auto-detection (probe PM during enumeration), config version tracking, LED timer optimization
- 2319 tests across 35 files

## v4.2.0

### SELinux Support
- **New**: `trcc setup-selinux` command — installs SELinux policy module (`trcc_usb`) that allows USB device access on SELinux-enforcing systems (Bazzite, Silverblue, Fedora Atomic)
- **New**: SELinux check integrated into setup wizard (CLI `trcc setup` + GUI `trcc setup-gui`)
- **New**: Distro-specific install hints for `checkmodule`/`semodule_package` across all package managers
- **Fixed**: Bulk devices (87AD:70DB) failing with EBUSY on SELinux — detect silent `detach_kernel_driver()` blocking, skip `set_configuration()` if device already configured, clear error message pointing to `trcc setup-selinux`
- **Fixed**: CI workflows now trigger on `stable` branch (was `main/master`)
- Confirmed working: Wonder Vision Pro 360 on Bazzite (SELinux enforcing) — PM=64 → 1600x720
- 2300 tests across 35 files

## v4.1.0

### Setup Wizard
- **New**: `trcc setup` — interactive CLI wizard that checks deps, GPU, udev, desktop entry and offers to install anything missing
- **New**: `trcc setup-gui` — PySide6 GUI wizard with check panel, Install buttons, and embedded terminal output streaming
- **New**: `setup.sh` bootstrap script — one-liner to install trcc-linux and launch the setup wizard (auto-detects GUI/CLI)
- **New**: `trcc uninstall --yes` flag for non-interactive use (GUI uses pkexec for graphical auth)
- Expanded distro support: Solus (eopkg), Clear Linux (swupd), SteamOS, Artix, ArcoLinux, PostmarketOS, Funtoo, Calculate
- PM native "provides" search fallback (dnf/pacman/zypper/apk/xbps) for unmapped dependencies
- Structured check functions in doctor.py (`check_system_deps`, `check_gpu`, `check_udev`, `check_desktop_entry`) for programmatic consumers
- GPU vendor detection via PCI sysfs (NVIDIA, AMD, Intel)
- libxcb-cursor check for apt-based distros (prevents PySide6 segfault on Ubuntu)
- 2290 tests across 35 files

## v4.0.0

### Hexagonal Adapters Restructure
- Moved 24 flat files into `adapters/device/` (10 files), `adapters/system/` (3 files), `adapters/infra/` (11 files)
- Domain data consolidation: all static mappings centralized in `core/models.py` (LED styles, button images, protocol names, category data)
- Assets centralization: eliminate 19 duplicate `.png` calls via `Assets` class
- Language state unified: `settings.lang` singleton replaces 5 widget `self._lang` copies
- Clean hexagonal boundary: `core/` + `services/` (pure Python) → `adapters/` (device/system/infra I/O)
- 2290 tests across 35 files

## v3.0.10

### UCScreenLED Rewrite
- Rewrite UCScreenLED: exact CS paint order (dark fill → decorations → LED rectangles → overlay mask)
- 12 ledPosition arrays with exact Rectangle(x,y,w,h) coordinates, 460×460 widget
- Unified device sidebar buttons: remove DeviceButton class, all buttons use `create_image_button` with `setChecked()` toggle
- 2288 tests across 35 files

## v3.0.9

### PA120 Remap Fix & HID Type 2 Transport Fix
- **Fixed**: PA120 LED remap table — misplaced SSD/HSD/C11/B11 block shifted zones 4+ by 4 wire positions
- **Fixed**: HID Type 2 `open()` — skip redundant `set_configuration()` if already configured, preventing USB bus reset on Linux
- Note: HID Type 2 frame send was later changed to single transfer in v4.2.7, then frame header fixed in v5.0.4
- 2290 tests across 35 files

## v3.0.8

### LED Segment Display Fix
- **Fixed**: LED segment display °C/°F toggle now propagates to segment renderer
- **Fixed**: CPU/GPU sensor source selector now filters phase cycling (show only CPU or GPU instead of always both)
- OOP refactor: moved loose functions into classes across 5 files (conf.py, device_scsi.py, device_led_hr10.py, device_factory.py, device_hid.py)
- 2290 tests across 35 files

## v3.0.7

### Unified Segment Display Renderer
- Unified segment display renderer for all 11 LED device styles
- OOP class hierarchy: `SegmentDisplay` ABC + 10 subclasses (AX120, PA120, AK120, LC1, LF8, LF12, LF10, CZ1, LC2, LF11)
- Data/logic separation with `CHAR_7SEG` and `CHAR_13SEG` encoding tables
- `LEDService` generalized for all digit-display styles (not just AX120)
- 2291 tests across 35 files

## v3.0.6

### Single-Instance Guard
- Single-instance guard: prevent duplicate systray entries on launch
- Font size spinbox in overlay color picker (independent of font dialog)
- 2167 tests across 35 files

## v3.0.5

### LED Mode Button Image Fix
- **Fixed**: LED mode button images — asset filename typo caused buttons to show plain text instead of icons (`D2灯光1{i+1}` → `D2灯光{i+1}`)
- 2167 tests across 35 files

## v3.0.4

### Bulk Frame Encoding Fix
- **Fixed**: Bulk frame encoding — JPEG (cmd=2) instead of raw RGB565 for all USBLCDNew devices (87AD:70DB), matching C# `ImageToJpg` protocol
- PM=32 remains RGB565 (cmd=3) for raw-mode devices
- Added PM=5 to bulk resolution table (Mjolnir Vision → 240×320)
- 2166 tests across 35 files

## v3.0.3

### Background Display Mode Fix
- **Fixed**: Background display mode — continuous LCD sending via metrics timer (C# `myBjxs`/`isToTimer` parity), toggle OFF renders black+overlays, theme click resets all mode toggles
- Security hardening: timing-safe auth, PIL bomb cap, zip-slip guard, TOCTOU fix
- Tooltips on all user-facing buttons
- Distro name in debug report
- Help → troubleshooting guide
- 2162 tests across 33 files

## v3.0.2

### Bulk Protocol Fix
- **Fixed**: Bulk protocol frame header (correct magic bytes, kernel driver detach, chunked writes)
- **Fixed**: Legacy autostart cleanup — glob desktop files, remove duplicates
- Auto-detect GPU vendor for sensor mapping: NVIDIA > AMD > Intel
- CI: added FastAPI test dependencies (httpx, python-multipart) to dev extras
- 2156 tests across 33 files

## v3.0.1

### Full CLI Parity
- **36 Typer commands** expose all service methods — CLI, GUI, and REST API now have full feature parity
- New theme commands: `theme-save`, `theme-export`, `theme-import`
- New LED commands: `led-color`, `led-mode`, `led-brightness`, `led-off`, `led-sensor`
- New display commands: `brightness`, `rotation`, `screencast`, `mask` (with `--clear`), `overlay`
- New media command: `video` (plays video/GIF/ZT on LCD)
- Theme commands: `theme-list` (local + cloud), `theme-load` (find by name + send)
- All commands follow detect → service → print → return 0/1 pattern
- Backward-compatible module-level aliases for all new commands
- 2148 tests across 31 files

## v3.0.0

### Hexagonal Architecture
- **Services layer** (`src/trcc/services/`) — 8 service classes shared by GUI, CLI, and REST API:
  - `DeviceService` — detect, select, send_pil, send_rgb565
  - `DisplayService` — high-level display orchestration
  - `ImageService` — solid_color, resize, brightness, rotation, byte_order
  - `LEDService` — LED RGB control via LedProtocol
  - `MediaService` — GIF/video frame extraction
  - `OverlayService` — overlay rendering
  - `SystemService` — system sensor access
  - `ThemeService` — theme loading/saving/export/import
- **CLI refactored to Typer** — OOP command classes (DeviceCommands, DisplayCommands, ThemeCommands, LEDCommands, DiagCommands, SystemCommands)
- **REST API adapter** (`api.py`) — FastAPI endpoints for headless/remote control (optional `[api]` extra)
- **Module renames**: `paths`→`data_repository`, `sensor_enumerator`→`system_sensors`, `sysinfo_config`→`system_config`, `cloud_downloader`→`theme_cloud`, `driver_lcd`→`device_lcd`
- Dead code removed: `theme_io.py`, `constants.py`, `device_base.py`
- 2081 tests across 31 files

## v2.0.1

### FBL/PM Resolution Fix
- Fixed PM=36 (240x240) wrong resolution: unified FBL/PM tables into `constants.py` (single source of truth)
- PM=FBL default instead of hardcoded 320x320
- Fixed PyQt6 version in `trcc report`
- CI: add ffmpeg, auto-publish to PyPI on tag push
- Deleted dead shim files

## v2.0.0

### Major Refactor
- **Module renaming**: Consistent `device_*` / `driver_*` naming convention across all backend modules:
  - `bulk_device` → `device_bulk`, `hid_device` → `device_hid`, `led_device` → `device_led`
  - `scsi_device` → `device_scsi`, `lcd_driver` → `driver_lcd`, `kvm_led_device` → `device_kvm_led`
  - `gif_animator` → `media_player`
- **New modules**: `constants.py` (shared constants), `debug_report.py` (diagnostic tool), `device_led_hr10.py` (HR10 LED backend)
- All imports updated across 49 source files and 29 test files
- 2105 tests passing, ruff + pyright clean

## v1.2.16

### SELinux/Immutable Distro Fix
- **Fixed**: udev rules using `TAG+="uaccess"` which fails on SELinux-enforcing distros (Bazzite, Silverblue, Fedora Atomic)
- Now uses `MODE="0666"` for all udev rules — works universally across all Linux distros

## v1.2.15

### Stale Udev Detection
- **Auto-detect stale udev rules**: `trcc detect` now warns when USB storage quirk is missing and prompts `sudo trcc setup-udev` + reboot
- Prevents confusing "no device found" errors after adding new device support

## v1.2.14

### GrandVision 360 AIO Support
- Added GrandVision 360 AIO (VID `87AD:70DB`) as a known SCSI device
- Fixed sysfs VID readback for non-standard vendor IDs
- Device layer dedup: lcd_driver delegates to scsi_device, extracted `_create_usb_transport()`, `get_frame_chunks()` single source of truth
- Fixed LED PM/SUB byte offset (`pm=resp[5], sub=resp[4]`) — was off by one due to Windows Report ID prepend

## v1.2.13

### Format Button Fix
- **Fixed**: Format buttons (time/date/temp) not updating preview on fresh install
- Set `overlay_enabled` on theme load so format changes render immediately
- Persist format preferences (time_format, date_format, temp_unit) across theme changes via `conf.save_format_pref()`

## v1.2.12

### Fresh Install Overlay Fix
- **Fixed**: Overlay/mask changes not updating preview or LCD on fresh install (no saved device config)
- Root cause: `OverlayModel.enabled` defaults to `False` and was only set `True` by `start_metrics()`. On fresh install, no saved config → overlay disabled → `render_overlay_and_preview()` returned raw background unchanged
- `render_overlay_and_preview()` now uses `force=True` to always render through the renderer, bypassing the `enabled` check (preview path should always show edits)
- `_on_overlay_changed()` auto-enables overlay and starts metrics timer when user is actively editing elements

## v1.2.11

### LCD Send Pipeline Fix
- **Overlay changes**: Editing overlay elements (color, position, font, format, text) now sends the rendered frame to the LCD immediately
- **Mask toggle/reset**: Toggling or clearing mask now sends to LCD
- **Background toggle**: Switching to static background now sends to LCD
- **Image crop**: Cropped image now sends to LCD after crop completes
- **Video first frame**: Loading a video theme now shows the first frame on LCD immediately (was blank until timer fired)
- **send_current_image**: Now applies overlay before sending (was sending raw background)
- **_render_and_send**: Fixed to send overlay-rendered image, not raw `current_image`
- **DRY**: Extracted `_load_and_play_video()` — eliminates 5 scattered video load+play patterns

## v1.2.10

### First-Launch Preview Fix
- **Fixed**: Theme previews not showing on first GUI launch after `pip install` or upgrade
- Root cause: `Settings` singleton resolved paths at import time (before data existed), and `set_resolution()` short-circuited when resolution was unchanged — paths were never refreshed after `ensure_all_data()` downloaded archives

## v1.2.9

### HID Handshake Protocol Fix
- **LED routing fixed**: `hid-debug` now routes LED devices (Type 1) through `LedProtocol` instead of `HidProtocol` — was returning None immediately for all LED devices
- **Retry logic**: 3-attempt handshake with 500ms delay between retries (matching Windows UCDevice.cs `Timer_event`)
- **Timeout increased**: Handshake uses 5000ms timeout (was 100ms) — frame I/O stays at 100ms
- **Relaxed Type 2 validation**: Removed strict `resp[16] == 0x10` check (Windows doesn't require it)
- **Relaxed LED validation**: Bad magic/cmd bytes now warn instead of reject (matching Windows `DeviceDataReceived1`)
- **PM/SUB offset fix**: Type 2 LCD now reads `pm=resp[5], sub=resp[4]` (matching Windows Report ID offset)
- **Endpoint auto-detection**: `PyUsbTransport` enumerates actual device endpoints instead of hardcoding EP 0x02
- **Error visibility**: Actual USB exceptions logged and exposed via `protocol.last_error` instead of generic "None"
- **Hex dump in diagnostics**: `hid-debug` now shows raw handshake response bytes for bug reports

### OOP Refactor
- **DcConfig**: Merged `dc_parser.py` + `dc_writer.py` into single `DcConfig` class in `dc_config.py`
- **conf.py**: Moved all config persistence from `paths.py` into dedicated `conf.py` module
- **device_base.py**: Added `DeviceHandler` ABC and `HandshakeResult` base dataclass
- **Dataclasses**: `ThemeItem`/`LocalThemeItem`/`CloudThemeItem`/`MaskItem` replace raw dicts in theme browsers
- **DownloadableThemeBrowser**: Template method base class in `base.py` for cloud/mask/web browsers
- **gif_animator.py**: Simplified with cleaner class structure, removed dead code
- **paths.py**: Facade pattern with `ensure_all_data()`, cleaner on-demand download

## v1.2.8

### KISS Refactor
- Consolidated 5 duplicate Settings tab handlers (`_on_color_changed`, `_on_position_changed`, `_on_font_changed`, `_on_format_changed`, `_on_text_changed`) into single `_update_selected(**fields)` method in `uc_theme_setting.py`
- Each handler is now a one-liner delegating to `_update_selected` with keyword args
- Removed dead `set_format_options()` method from `overlay_renderer.py` (never called)
- Removed 6 dead LED legacy stubs from `models.py` (`_tick_static`, `_tick_breathing`, `_tick_colorful`, `_tick_rainbow`, `_tick_temp_linked`, `_tick_load_linked`) — production dispatches via `_tick_single_mode` directly

## v1.2.7

### Strip Theme Data from Wheel
- Removed all theme data from the pip wheel — themes download on first run only
- `_has_actual_themes()` now requires PNG files (ignores leftover `.dc` files)

## v1.2.6

### Config Marker Verification
- Fixed stale config marker: `is_resolution_installed()` now verifies data exists on disk
- Added debug logging for theme setup, tab switches, and directory verification

## v1.2.5

### One-Time Data Setup
- Download themes/previews/masks once per resolution, tracked in `~/.trcc/config.json`
- `is_resolution_installed()` / `mark_resolution_installed()` skip re-download on subsequent launches
- Custom themes saved to `~/.trcc/data/` (survives pip upgrades)

## v1.2.4

### Fix pip Upgrade Data Loss
- Theme archives now extract to `~/.trcc/data/` instead of site-packages
- `install-desktop` generates `.desktop` file inline for pip installs (no bundled template needed)

## v1.2.3

### Logging Refactor
- Replaced `print()` with `logging` across 12 modules
- Thread-safe device send with lock
- Extracted `_setup_theme_dirs()` helper
- Suppressed `pyusb` deprecation warning (`_pack_` in ctypes)

## v1.2.2

### Fix Local Theme Loading
- Fixed local themes not loading from pip install (`Custom_*` dirs blocked on-demand download)

## v1.2.1

### Debug Logging & HID Fix
- Fixed RGB565 byte order for non-320x320 SCSI devices
- Fixed GUI crash on HID handshake failure
- Added verbose debug logging (`trcc -vv gui`)

## v1.2.0

### HR10 2280 PRO Digital Support
- 7-segment display renderer (`hr10_display.py`) — converts text + unit into 31-LED color array
- NVMe temperature daemon (`hr10-tempd` CLI command) — reads sysfs temp, breathe animation, thermal color gradient
- LED diagnostic command (`led-debug`) — handshake + test colors for LED devices
- Interactive HSV color wheel widget (`uc_color_wheel.py`) for LED hue selection
- 7-segment preview widget (`uc_seven_segment.py`) — QPainter rendering matching physical HR10 display
- Unified LED panel — all LED device styles (1-13) handled by single `UCLedControl` panel, matching Windows FormLED.cs
- HR10-specific widgets (drive metrics, display selection, circulate mode) shown conditionally in the LED panel
- LED segment visualization widget (`uc_screen_led.py`) with colored circles at segment positions
- Contributor: [Lcstyle](https://github.com/Lcstyle) (GitHub PR #9)

### Controller Naming
- Renamed `FormCZTVController` → `LCDDeviceController` (LCD orchestrator)
- Renamed `FormLEDController` → `LEDDeviceController` (LED orchestrator)
- Consistent naming convention: `{Domain}Controller` for state engines, `{Protocol}DeviceController` for orchestrators

### Autostart on Login
- Auto-enable autostart on first GUI launch (matches Windows `KaijiQidong()` behavior)
- Creates `~/.config/autostart/trcc.desktop` with `trcc --last-one` on first run
- `--last-one` launches GUI minimized to system tray and sends last-used theme
- Settings panel checkbox reflects and toggles the actual autostart state
- `trcc resume` command for headless theme send (scripting/cron)

### Reference Theme Save
- Custom saved themes use `config.json` with path references (no file copies)
- On save: writes `config.json` + `Theme.png` thumbnail to `Custom_{name}/`
- On load: resolves background/mask/overlay paths from `config.json`
- Fixes overlay-on-resume: overlay config persisted in theme JSON

### Protocol Reverse Engineering
- Complete SCSI protocol reference from USBLCD.exe (Ghidra decompilation)
- Complete USB bulk protocol reference from USBLCDNEW.exe (.NET/ILSpy)
- Documented all CDB commands, handshake sequences, frame transfer formats
- New docs: [USBLCD_PROTOCOL.md](USBLCD_PROTOCOL.md), [USBLCDNEW_PROTOCOL.md](USBLCDNEW_PROTOCOL.md)

### LCD Blink Mitigation
- SCSI init now checks poll response for `0xA1A2A3A4` boot signature (matching USBLCD.exe)
- If device is still booting, waits 3s and re-polls (up to 5 retries)
- Added 100ms post-init delay to let display controller settle before first frame

### Code Quality
- `ruff` linting enforced in CI (E/F/W/I rules) — 0 violations across 26 files
- Fixed 122 ruff violations (unsorted imports, unused vars, f-strings, lambda, class redefinition)
- Removed unused imports across 10 files
- Sorted all import blocks (isort)
- Removed redundant `requirements.txt` (`pyproject.toml` is single source of truth)
- Deduplicated magic bytes: `led_device.LED_MAGIC` now imports `TYPE2_MAGIC` from `hid_device` (was copy-pasted)
- Extracted `_select_item()` into `BaseThemeBrowser` — shared visual selection logic for local, cloud, and mask browsers
- Centralized `pil_to_pixmap()` usage in `UCImageCut` (was inline 5-line conversion)
- Added `_create_info_panel()` factory in `UCLedControl` — eliminates duplicate QFrame+label creation for mem/disk panels
- Consolidated 5 repeated stylesheet strings into module-level constants (`_STYLE_INFO_BG`, `_STYLE_INFO_NAME`, etc.)

### On-Demand Download
- All 15 LCD resolutions now have bundled `.7z` theme archives (was 4)
- New resolutions: 240x320, 360x360, 800x480, 854x480, 960x540, 1280x480, 1600x720, 1920x462, plus portrait variants
- On-demand download for themes, cloud previews, and mask archives from GitHub on first use
- 33 Web archives (cloud previews + masks) for all resolutions
- Downloaded archives stored in `~/.trcc/data/` when package dir is read-only (pip install)
- Cross-distro 7z install help shown when system `7z` is not available

### HID Device Identification
- PM→FBL→resolution mapping from Windows FormCZTV.cs (all known PM byte values)
- `pm_to_fbl()` and `fbl_to_resolution()` functions in `hid_device.py`
- `PM_TO_BUTTON_IMAGE` mapping for dynamic sidebar button updates after handshake
- New `trcc hid-debug` CLI command — hex dump diagnostic for HID bug reports

### Packaging
- Assets and data moved into `trcc` package (`src/trcc/assets/`, `src/trcc/data/`)
- `pip install .` now produces a complete wheel with all GUI images, fonts, and themes
- HID devices auto-detected — `--testing-hid` flag no longer needed

### Bug Fixes
- Fixed resume RGB565 conversion to match GUI (big-endian + masked)
- Fixed LEDMode int-to-enum conversion crash on config save
- Fixed device config persistence for autostart theme state
- Fixed json import ordering in controllers
- Fixed saved theme overlay not rendering (overlay must enable before background load)
- Fixed tab 2 mask not persisting in saved themes (mask source directory tracking)
- Fixed `install_desktop()` icon path (`src/assets/` → `src/trcc/assets/`)
- Fixed `install.sh` desktop shortcut using generic icon instead of TRCC icon
- Fixed CI workflow missing libEGL and QT_QPA_PLATFORM for PyQt6 tests

### Documentation
- Added [Supported Devices](SUPPORTED_DEVICES.md) page with all USB IDs
- Added [Development Status](DEVELOPMENT_STATUS.md) tracking page
- Expanded [Technical Reference](TECHNICAL_REFERENCE.md) with full SCSI command table
- Removed `--testing-hid` references from all docs (HID is auto-detected)

### Testing
- 2029 tests across 27 test files (up from 1777)
- 96% coverage on non-Qt backend

## v1.1.3

### LED RGB Control (`hid-protocol-testing` branch)
- RGB LED control panel (FormLED equivalent) for HID LED devices (e.g. AX120 DIGITAL)
- 7 LED effect modes: Static, Breathing, Rainbow, Cycle, Wave, Flash, Music
- Per-segment and global on/off toggles, brightness slider, color picker
- `LedProtocol` in device_factory.py routes LED devices separately from LCD HID
- `FormLEDController` with tick-based animation loop (30ms, matching Windows timer1)
- `led_device.py`: LED styles, packet builder, HID sender, effect engine
- `uc_led_control.py`: PyQt6 LED control panel with segment grid and mode buttons
- Device routing: sidebar auto-routes HID LED devices to LED view instead of LCD form
- 376 new LED tests (245 led_device + 131 led_controller)

### Save Custom Theme Fixes
- Fixed font size DPI corruption on save — sizes no longer inflate each save cycle (36pt → 48pt → 64pt)
- Fixed font charset lost on save — preserves GB2312 charset (134) instead of defaulting to 0
- Fixed font style default — Regular (0) instead of Bold (1), matching Windows `new Font()` defaults
- Lossless DC config round-trip: original parsed DC data preserved in `OverlayModel._dc_data` and merged on save instead of reconstructing from scratch
- Cloud video themes now copy MP4 to working dir for inclusion in saved custom themes
- `ThemeInfo.from_directory()` now detects `.mp4` files in theme directories (not just Theme.zt)
- Saved custom themes with MP4 backgrounds properly reload as video on reopen

### Cross-Distro Compatibility
- Centralized all platform-specific helpers in `paths.py` (single source of truth)
- `require_sg_raw()` with install instructions for 8+ distro families (Fedora, Debian, Arch, openSUSE, Void, Alpine, Gentoo, NixOS)
- Dynamic SCSI device scan via `/sys/class/scsi_generic/` (replaces hardcoded `range(16)`)
- `FONT_SEARCH_DIRS` covering 20+ font directories across all major Linux distros
- Replaced `os.system()` with `subprocess.run()` in cli.py for security/correctness
- Install guide expanded to cover 25+ Linux distributions

### CI / Testing
- Added `hid-protocol-testing` branch to GitHub Actions test workflow (Python 3.10, 3.11, 3.12)
- 563 HID/LED tests (114 device protocol + 73 factory/routing + 245 LED device + 131 LED controller) — total 1777 tests across all branches
- Fixed Python 3.12 `mock.patch` failure for optional `pynvml` import
- Added `ruff` to dev dependencies for CI lint step

### Documentation
- Added HID device PIDs (`0416:5302`, `0418:5303`, `0418:5304`) to supported devices
- Split README device tables into SCSI (stable) and HID (testing) sections with USB IDs
- Added `lsusb` example to help users identify their device
- Created [Device Testing Guide](DEVICE_TESTING.md) with install, switch, and reporting instructions
- Added CI badge to README
- Added [CLI Reference](CLI_REFERENCE.md) with all commands, options, and troubleshooting
- Updated Documentation table on all branches

### Autostart on Login
- Auto-enable autostart on first GUI launch (matches Windows `KaijiQidong()` behavior)
- Creates `~/.config/autostart/trcc.desktop` with `trcc --last-one` on first run
- Checkbox in Settings panel reflects and toggles the actual autostart state
- Subsequent launches refresh the `.desktop` file if the install path changed
- 15 new autostart tests covering first-launch, toggle, path refresh, and edge cases

### Bug Fixes
- Theme.png preview now includes rendered overlays and masks (was showing raw background only)
- `dc_writer.py` only writes fallback Theme.png if one doesn't already exist (controller writes the better rendered version)
- Fixed cli.py `--version` flag (was stuck at 1.1.0)

## v1.1.2

### Bug Fixes
- Fixed LCD send: init handshake (poll + init) was being skipped on first frame send
- Dynamic frame chunk calculation for all resolutions (was hardcoded to 320x320)
- Local themes grid now sorts default themes (Theme1-5) first
- Added Qt6 installation docs for additional distros

### Test Suite (1209 tests, 96% coverage)
- Expanded from 880 → 1209 tests across 6 coverage sprints
- All 18 non-Qt backend modules now 92-100% covered (combined 96%)
- Added 3 Qt component test files (test_qt_constants, test_qt_base, test_qt_widgets)

## v1.1.1

### Test Suite (298 tests)
- Added test_dc_writer (18 tests): binary write, roundtrip, overlay_config_to_theme, carousel, .tr export/import
- Added test_paths (25 tests): config persistence, per-device config, path helpers, resolution/temp unit
- Added test_sysinfo_config (18 tests): config load/save, defaults, auto_map
- Added test_device_implementations (25 tests): RGB565 conversion, resolution, commands, registry
- Added test_scsi_device (18 tests): CRC32, header building, frame chunking
- Added test_models (30 tests): ThemeInfo, ThemeModel, DeviceModel, VideoState, OverlayModel
- Added test_theme_io (14 tests): C# string encoding, .tr export/import roundtrip
- Removed 7 dead test files (1490 lines) importing non-existent modules
- Fixed 3 RGBA→RGB assertion mismatches in overlay renderer tests
- Existing tests: test_dc_parser (133), test_device_detector (17), test_overlay_renderer (25)

### Bug Fixes
- Fixed `dc_writer.py`: `overlay_config_to_theme()` and `import_theme()` called `DisplayElement()` without required positional args — runtime crash
- Fixed `theme_io.py`: `export_theme()` missing `bg_len` write when no background image — caused import to read past EOF

## v1.1.0

- Per-device configuration — each LCD remembers its theme, brightness, rotation, overlay, and carousel
- Carousel mode — auto-rotate through up to 6 themes on a timer
- Theme export/import — save/load themes as `.tr` files
- Video trimmer — trim videos and export as `Theme.zt` frame packages
- Image cropper — crop and resize images for any LCD resolution
- Fullscreen color picker — eyedropper tool for picking screen colors
- Dynamic font and coordinate scaling across resolutions
- Font picker dialog for overlay elements
- Mask toggle to hide/show instead of destroying mask data
- Mask reset/clear functionality
- Screen cast with PipeWire/Portal support for Wayland
- Sensor customization dashboard with reassignable sensor slots
- Overlay element cards matching Windows UCXiTongXianShiSub exactly
- Font name and style preservation when loading themes
- Fixed disabled overlay elements being re-enabled on property changes
- Fixed 12-hour time format (2:58 PM instead of 02:58 PM)
- Video resume when toggling video display back on

## v1.0.0

- Initial release
- Full GUI port of Windows TRCC 2.0.3
- Local and cloud theme support
- Video/GIF playback with FFmpeg
- Theme editor with overlay elements
- System info dashboard with 77+ sensors
- Screen cast functionality
- Multi-device and multi-resolution support
