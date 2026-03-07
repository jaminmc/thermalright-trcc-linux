# TRCC Linux — Claude Code Project Instructions

## Architecture — Hexagonal (Ports & Adapters)

### Layer Map
- **Models** (`core/models.py`): Pure dataclasses, enums, domain constants — zero logic, zero I/O, zero framework deps
- **Services** (`services/`): Core hexagon — all business logic, pure Python. `ImageService` is a thin facade delegating to the active `Renderer` (QtRenderer by default). `OverlayService` uses injected Renderer for compositing/text.
- **Devices** (`core/lcd_device.py`, `core/led_device.py`): `LCDDevice(Device)` with direct methods (capabilities inlined) + `LEDDevice(Device)` with direct methods. Delegate to services, return result dicts. No business logic.
- **Builder** (`core/builder.py`): `ControllerBuilder` — fluent builder, assembles devices with DI, returns `LCDDevice`/`LEDDevice`.
- **Views** (`qt_components/`): PySide6 GUI adapter. `TRCCApp` (thin shell) + `LCDHandler`/`LEDHandler` (one per device).
- **CLI** (`cli/`): Typer CLI adapter (package: `__init__.py` + 6 submodules). Thin presentation wrappers over `LCDDevice`/`LEDDevice` — connect, call device method, print result.
- **API** (`api/`): FastAPI REST adapter (package: `__init__.py` + 6 submodules). 42 endpoints covering devices, display, LED, themes, and system metrics. Includes WebSocket live preview stream + cloud theme download. Uses `LCDDevice`/`LEDDevice` from core/. `_current_image` tracks last frame sent for preview endpoints.
- **Config** (`conf.py`): Application settings singleton — resolution, language, temp unit, device prefs. Single source of truth for all mutable app state.
- **Entry**: `cli/` → `trcc_app.py` (TRCCApp) → builder.build_lcd()/build_led()
- **Protocols**: SCSI (LCD frames), HID (handshake/resolution), LED (RGB effects + segment displays)
- **On-demand download**: Theme/Web/Mask archives fetched from GitHub at runtime via `data_repository.py`

### Design Patterns (Gang of Four + Architectural)

#### Creational — Object creation mechanisms
- **Singleton**: Ensures a class has only one instance and provides a global access point to it. Used: `conf.settings` — app-wide state (resolution, language, preferences). Widgets read from singleton, never store their own copies
- **Factory Method**: Defines an interface for creating an object, but lets subclasses decide which class to instantiate. Used: `factory.py` builds protocol-specific device adapters (CLI, GUI, or API)
- **Abstract Factory**: Provides an interface for creating families of related or dependent objects without specifying their concrete classes
- **Builder**: Separates the construction of a complex object from its representation, allowing the same construction process to create different representations
- **Prototype**: Specifies the kinds of objects to create using a prototypical instance, and creates new objects by copying this prototype

#### Structural — Class/object composition into larger structures
- **Adapter**: Converts the interface of a class into another interface clients expect, allowing classes with incompatible interfaces to work together. Used: Hexagonal adapters/ — CLI, GUI, API all adapt to the same core services
- **Bridge**: Decouples an abstraction from its implementation so that the two can vary independently
- **Composite**: Composes objects into tree structures to represent part-whole hierarchies, allowing clients to treat individual objects and compositions uniformly
- **Decorator**: Attaches additional responsibilities to an object dynamically, providing a flexible alternative to subclassing for extending functionality
- **Facade**: Provides a unified, simplified interface to a set of interfaces in a subsystem
- **Flyweight**: Uses sharing to support large numbers of fine-grained objects efficiently
- **Proxy**: Provides a surrogate or placeholder for another object to control access to it

#### Behavioral — Algorithms and responsibility assignment
- **Chain of Responsibility**: Avoids coupling the sender of a request to its receiver by chaining receiving objects and passing the request along the chain until an object handles it
- **Command**: Encapsulates a request as an object, thereby letting you parameterize clients with different requests, queue or log requests, and support undoable operations. Used: user actions (button click, terminal command) — easy to log, undo, queue across interfaces
- **Iterator**: Provides a way to access the elements of an aggregate object sequentially without exposing its underlying representation
- **Mediator**: Defines an object that encapsulates how a set of objects interact, promoting loose coupling by keeping objects from referring to each other explicitly
- **Memento**: Captures and externalizes an object's internal state without violating encapsulation, allowing the object to be restored to this state later
- **Observer**: Defines a one-to-many dependency between objects so that when one object changes state, all its dependents are notified and updated automatically. Used: PySide6 signals broadcast updates from core to views without coupling. `UCLedControl.update_metrics()` — panel subscribes to metrics, dispatches internally based on style_id (caller doesn't route)
- **State**: Allows an object to alter its behavior when its internal state changes, making it appear as though the object changed its class
- **Strategy**: Defines a family of algorithms, encapsulates each one, and makes them interchangeable, allowing the algorithm to vary independently from the clients that use it. Used: swap display/export behaviors without modifying core service logic
- **Template Method**: Defines the skeleton of an algorithm in an operation, deferring some steps to subclasses, allowing subclasses to redefine certain steps of an algorithm without changing its structure
- **Visitor**: Represents an operation to be performed on elements of an object structure, allowing you to define a new operation without changing the classes of the elements on which it operates
- **Interpreter**: Given a language, defines a representation for its grammar along with an interpreter that uses this representation to interpret sentences in the language

#### Architectural (project-specific)
- **Dependency Injection**: Inject dependencies at runtime, never hardcode — decouple core logic from external tools
- **Repository Pattern**: Standardized data access — service layer doesn't know if data comes from file, DB, or remote API. Used: `data_repository.py`
- **Ports & Adapters (Hexagonal)**: Define Ports (ABC contracts) that every Adapter must follow — CLI, GUI, and API interact with core logic the same way
- **Data Transfer Objects (DTOs)**: Strictly defined structures (`dataclass`) for passing data across the Hexagon boundary — prevent GUI/API from manipulating internal domain objects

### Abstract Base Classes (ABCs)
Two layers of ABCs: **transport layer** (raw device I/O) and **adapter layer** (MVC integration). Future-proofed — new Thermalright devices slot in as subclasses without touching existing code.

#### Transport Layer (`adapters/device/template_method_device.py` + `template_method_hid.py`)
```
UsbDevice (ABC) — handshake() + close()
├── FrameDevice (ABC) — + send_frame()
│   ├── ScsiDevice (adapter_scsi.py)
│   ├── BulkDevice (_template_method_bulk.py)
│   └── HidDevice (ABC, template_method_hid.py) — + build_init_packet, validate_response, parse_device_info
│       ├── HidDeviceType2
│       └── HidDeviceType3
└── LedDevice (ABC) — + send_led_data() + is_sending
    └── LedHidSender (adapter_led.py)
```

#### Adapter Layer (`adapters/device/abstract_factory.py`)
```
DeviceProtocol (ABC) — Template Method: handshake() concrete, _do_handshake() abstract
├── LCDMixin — send_image() (abstract) + send_pil() (concrete, ISP)
├── LEDMixin — send_led_data() (abstract, ISP)
│
├── ScsiProtocol  (DeviceProtocol + LCDMixin, wraps ScsiDevice)
├── HidProtocol   (UsbProtocol + LCDMixin, wraps HidDevice)
├── BulkProtocol  (DeviceProtocol + LCDMixin, wraps BulkDevice)
└── LedProtocol   (UsbProtocol + LEDMixin, wraps LedHidSender)

DeviceProtocolFactory — @register() decorator for self-registration (OCP)
```

#### Other ABCs
| ABC | File | Subclasses | Purpose |
|-----|------|------------|---------|
| `Renderer` | `core/ports.py` | QtRenderer, PilRenderer (2) | Image rendering ABC — compositing, text, encoding, rotation. QtRenderer is the primary (QImage/QPainter), PilRenderer is fallback |
| `UsbTransport` | `adapters/device/hid.py` | PyUsbTransport, HidApiTransport (2) | USB I/O abstraction — mockable for tests |
| `SegmentDisplay` | `adapters/device/led_segment.py` | AX120, PA120, AK120, LC1, LF8, LF12, LF10, CZ1, LC2, LF11 (10) | LED 7-segment mask computation per product |
| `BasePanel` | `qt_components/base.py` | UCDevice, UCAbout, UCPreview, UCThemeSetting, BaseThemeBrowser (5+3 indirect) | GUI panel lifecycle: `_setup_ui()` enforced, `apply_language()`, `get_state()`/`set_state()`, timer helpers |

**Rules**:
- **ABC = contract + shared behavior** — Python ABC serves both roles (no need for Java-style `IFoo` + `AbstractFoo` split)
- **ABC at architectural boundaries** — even with 1 implementation today, an ABC at a high-variation seam is worth it for extensibility. Thermalright will ship new devices; the ABCs are ready.
- **Don't add `typing.Protocol`** unless third-party plugins need to implement our contracts without inheriting
- **Template Method on ABC** — concrete method on base calls `@abstractmethod` on subclass (e.g. `handshake()` → `_do_handshake()`)
- **PySide6 metaclass conflict** — `QFrame` + `ABC` raises `TypeError`. Use `__init_subclass__` enforcement instead (see `BasePanel`)

### Data Ownership Rules
Every piece of data has exactly ONE owner. Violations = bugs.

| Data Kind | Owner | Examples |
|-----------|-------|---------|
| Domain constants (static mappings) | `core/models.py` | `FBL_TO_RESOLUTION`, `LOCALE_TO_LANG`, `HARDWARE_METRICS`, `TIME_FORMATS` |
| Device registries (VID/PID, protocol) | `core/models.py` | VID/PID tables, implementation names, device type enums |
| Mutable app state (user prefs) | `conf.py` → `Settings` | resolution, language, temp_unit, device config, format prefs |
| GUI asset resolution | `qt_components/assets.py` → `Assets` | file lookup, `.png` auto-append, pixmap loading, localization |
| Business logic | `services/` | image processing, overlay rendering, sensor polling |
| View state (widget-local) | Each widget | button states, selection indices, animation counters |

**Rules**:
- **Models own ALL static domain data** — if it's a lookup table, mapping, enum, or constant that multiple files reference, it goes in `core/models.py`. Never scatter domain data in device handlers, services, or views.
- **Settings owns ALL mutable app state** — widgets read `settings.lang`, `settings.resolution`, `settings.temp_unit`. No widget stores its own copy of app state (`self._lang`, `self._resolution`). When state changes, update the singleton; widgets read it on demand.
- **Assets owns ALL asset resolution** — one class handles file existence, `.png` auto-appending, pixmap loading, localization suffixes. No manual `f"{name}.png"` anywhere else.
- **Services own ALL business logic** — pure Python, no Qt, no framework deps. Services can import models but never views.
- **Views own ONLY rendering** — views read from Settings/Models, call Services, display results. No business logic, no domain data.

## Conventions
- **Logging**: Use `log = logging.getLogger(__name__)` — never `print()` for diagnostics
- **Paths**: Use `pathlib.Path` where possible; `os.path` only in `data_repository.py` (legacy, perf)
- **Thread safety**: Use Qt signals to communicate from background threads to GUI — never `QTimer.singleShot` from non-main threads
- **Tests**: `pytest` with `PYTHONPATH=src`; 4157 tests across 56 files. When refactoring changes mock targets, use `conftest.py` fixtures/helpers — never update 50+ individual test mock paths inline. Shared mock helpers go in conftest.
- **Linting**: `ruff check .` + `pyright` must pass before any commit (0 errors, 0 warnings)
- **Assets**: All GUI asset access goes through `Assets` class (`qt_components/assets.py`). Auto-appends `.png` for base names. Never manually build asset paths with `f"{name}.png"`.
- **Language**: Single source of truth is `settings.lang` (in `conf.py`). Widgets call `Assets.get_localized(name, settings.lang)` — never store `self._lang`.
- **Domain data**: Static mappings (VID/PID tables, format strings, resolution maps, sensor categories) belong in `core/models.py`. If you're defining a `dict` literal or `list` constant that maps domain concepts, it goes in models.

## OOP Best Practices

### Single Source of Truth
Every concept has ONE canonical location. Before adding a constant, mapping, or state variable, search the codebase for existing definitions. Duplicate state = bugs.

**Centralized state** — `conf.Settings` singleton:
```python
# GOOD: read from singleton
bg = Assets.get_localized('P0CZTV', settings.lang)

# BAD: widget stores its own copy
self._lang = 'en'  # ← stale copy, diverges from settings.lang
bg = Assets.get_localized('P0CZTV', self._lang)
```

**Centralized assets** — `Assets` class:
```python
# GOOD: Assets handles .png resolution
pixmap = Assets.load_pixmap('DAX120_DIGITAL')

# BAD: manual .png appending
pixmap = Assets.load_pixmap(f'{name}.png')
```

### Separation of Concerns
Each class has ONE job. When a class starts doing two things, split it.

| Class | Responsibility | Does NOT do |
|-------|---------------|-------------|
| `Assets` | File resolution, pixmap loading | Store app state, business logic |
| `Settings` | App state persistence, preferences | Asset loading, rendering |
| Models | Data structures, domain constants | I/O, business logic, rendering |
| Services | Business logic, data processing | GUI ops, state persistence |
| Views | Rendering, user interaction | Business logic, data ownership |

### Pattern: Adding New Domain Data
When you discover a new constant, mapping, or enum:
1. **Check if it exists** — search `core/models.py` first
2. **Add to models** — define it in `core/models.py` with a clear section comment
3. **Import where needed** — `from .core.models import MY_CONSTANT`
4. **Never define in device handlers** — `device_hid.py`, `device_led.py`, etc. import from models, never define their own lookup tables

### Pattern: Adding New App State
When you need a new user preference or persistent setting:
1. **Add to `Settings`** — private `_get_saved_X()` / `_save_X()` + public `set_X()` or property
2. **Persist in `config.json`** — via `load_config()` / `save_config()`
3. **Widgets read from `settings.X`** — never pass state through constructor chains
4. **Updates go through setter** — `settings.set_X(value)` persists + updates in-memory

### Pattern: Adding New Assets
When adding GUI assets:
1. **Put the file** in `src/trcc/assets/gui/`
2. **Reference by base name** — `Assets.get('MY_ASSET')` auto-resolves `.png`
3. **Add class constant** if used in multiple places — `MY_ASSET = 'filename.png'` in `Assets`
4. **Localized variants** — name them `{base}{lang}.png` (e.g., `P0CZTVen.png`), use `Assets.get_localized()`

## Known Issues
- `pyusb 1.3.1` uses deprecated `_pack_` in ctypes (Python 3.14) — suppressed in pytest config until upstream fix
- `pip install .` can use cached wheel — use `pip install --force-reinstall --no-deps .` when testing
- CI runs as root — mock `subprocess.run` in non-root tests to prevent actual sudo execution
- Never set `setStyleSheet()` on ancestor widgets — it blocks `QPalette` image backgrounds on descendants
- Optional imports (`hid`, `dbus`, `gi`, `pynvml`) need `# pyright: ignore[reportMissingImports]` — they're in try/except blocks but pyright still flags them
- **Tag push triggers PyPI release** — after pushing a release, always `git tag v{version} && git push origin v{version}`. Do this automatically, don't ask.
- **Don't close GitHub issues until the reporter confirms the fix works** — reopening looks bad
- **Never use "Fixes #N" in commit messages** — GitHub auto-closes issues on push to default branch. We don't close until reporter confirms.
- **C# asset suffixes are arbitrary** — `'e'`=Russian, `'r'`=Japanese, `'x'`=Spanish. Single source of truth: `LOCALE_TO_LANG` in `core/models.py` (re-exported via `qt_components/constants.py`)

## Deployment
- **Default branch: `main`** — all development, releases, and user-facing clones happen here
- **Never push without explicit user instruction**
- Dev repo: `~/Desktop/projects/thermalright/trcc-linux`
- Testing repo: `~/Desktop/trcc_testing/thermalright-trcc-linux/`
- PyPI: `trcc-linux` (published)

## Development Workflow

### Two modes: Development and Release

**Development** — local commits, no push, no version bump:
- Commit freely to `main` as you work (small logical commits)
- Run `ruff check .` + `pyright` before each commit
- Do NOT push, do NOT bump version — changes stay local
- Multiple commits can accumulate until the work is ready to ship

**Release** — when a set of changes is validated and ready for users:
1. Bump version in **both** `src/trcc/__version__.py` AND `pyproject.toml`
2. Add version history entry in `__version__.py`
3. Run `ruff check .` + `pyright` — fix any issues (0 errors, 0 warnings)
4. Run `PYTHONPATH=src pytest tests/ -x -q` — all tests must pass
5. Squash or keep commits as-is, then push to `main`
6. Tag and push: `git tag v{version} && git push origin v{version}` — this triggers CI to build + publish to PyPI. Do NOT run `twine upload` manually.
7. GitHub Release: `gh release create v{version} --target main --title "v{version}"` with release notes
8. Comment on relevant GitHub issues if the release affects them

### Rules
- **Version bump = release boundary** — no bump means still in development
- **Don't push mid-development** — partial fixes confuse users who install from GitHub
- **Tag push = PyPI release** — always tag after pushing a version bump, CI publishes automatically. Never suggest manual `twine upload`
- **Batch related changes** — one version bump covers all related commits
- **Never push without explicit user instruction**

## Project GUI Standards
- **Overlay enabled state**: `_load_theme_overlay_config()` must call `set_overlay_enabled(True)` — the grid's `_overlay_enabled` flag gates `to_overlay_config()` output
- **Format preferences**: Time/date/temp format choices persist in `config.json` via `conf.save_format_pref()` and get applied to any theme on load via `conf.apply_format_prefs()`
- **Theme loads DC for layout, user prefs for formats**: Theme's `config1.dc` defines which elements and where; user's format prefs (time_format, date_format, temp_unit) override format fields
- **Signal chain for element changes**: format button → `_on_format_changed()` → `_update_selected()` → `to_overlay_config()` → `CMD_OVERLAY_CHANGED` → `_on_overlay_changed()` → `render_overlay_and_preview()`
- **QPalette vs Stylesheet**: Never set `setStyleSheet()` on ancestor widgets — blocks `QPalette` image backgrounds on all descendants
- **First-run state**: On fresh install with no device config, `_on_device_selected()` disables overlay. Theme click re-enables it. Format prefs default to 0 (24h, yyyy/MM/dd, Celsius)
- **Delegate pattern**: Settings tab communicates via `invoke_delegate(CMD_*, data)` to main window
- **`_update_selected(**fields)`**: Single entry point for all element property changes (color, position, font, format, text)

## GoF Refactoring (COMPLETE — v6.0.0 through v7.0.10, 4157 tests passing)

### All Phases
- **Phase 1: Segment Display Collapse** — `led_segment.py` 1109→687 lines (-422, 38%). Properties→class attrs, 4 encode methods→unified `_encode_digits()` + `_encode_7seg()`, LF12 delegates to LF8. Flyweight + Strategy.
- **Phase 2: HID Subclasses — SKIPPED** — Template Method already well-applied, logic genuinely differs between Type2/Type3. ~20 line savings not worth it.
- **Phase 3: Controller Layer Elimination** — `controllers.py` 699→608 lines (-91). Deleted 5 thin wrapper controllers (ThemeController, DeviceController, VideoController, OverlayController, LEDController). LCDDeviceController = Facade over 4 services (~35 methods). LEDDeviceController absorbed LEDController. ~50 GUI call sites rewritten, 7 test files updated. Law of Demeter enforced: GUI→Facade→Services only.
- **Phase 4: UsbProtocol Base** — `factory.py` 874→846 lines (-28). Extracted shared transport lifecycle (open/close/ensure) from HidProtocol + LedProtocol into `UsbProtocol` base class. Template Method.
- **Phase 5: LED Config Serialization** — `services/led.py` save/load driven by `_PERSIST_FIELDS` dict + `_ALIASES` dict. Single source of truth for which fields persist. Memento pattern.
- **Total**: 24 files changed, -1203 net lines.

### v6.0.1 Extensions
- **CLI Dispatchers**: `LEDDispatcher` + `DisplayDispatcher` — Command pattern. Single authority for LED/LCD operations. Return result dicts, never print. CLI functions are thin wrappers.
- **Metrics Observer**: `UCLedControl.update_metrics()` — panel dispatches to style-specific update methods internally. `qt_app_mvc._poll_sensors()` reduced from 15 lines to 2. Observer pattern.
- **ANSI Preview**: `--preview` flag on all LCD/LED CLI commands renders true-color terminal art. `ImageService.to_ansi()` for stills, `to_ansi_cursor_home()` for video.
- **LED Visual Test Harness**: `tests/test_led_panel_visual.py` — standalone Qt app for testing all 12 LED styles with live metrics, device buttons, index overlay, and signal wiring.

### v6.1.5: Portrait Cloud Directory Switching
- **Non-square displays (e.g. 1280x480 Trofeo Vision) mounted vertically** were loading cloud backgrounds/masks from the landscape directory (`1280480/`) instead of the portrait directory (`4801280/`).
- **Root cause**: `_on_rotation_change()` set rotation but didn't re-resolve cloud/mask directories. `_apply_device_config()` similarly restored rotation without resolving portrait directories.
- **Fix**: Added `Settings.resolve_cloud_dirs(rotation)` — swaps width/height for web_dir and masks_dir when rotation is 90°/270° on non-square displays. Wired into both `_on_rotation_change()` and `_apply_device_config()`.
- **C# reference**: `GetWebBackgroundImageDirectory()` (FormCZTV.cs:3749) and `GetFileListMBDir()` (FormCZTV.cs:4255) both check `directionB` for portrait switching. Local themes (`ThemeML`) stay landscape — only cloud dirs switch.
- **No portrait local theme pack exists** — Windows doesn't ship `Theme4801280` either. Only cloud backgrounds/masks have portrait variants.
- Addresses #1. 5 new tests (2408 total).

### v6.1.3–v6.1.4: LED GUI Settings & Theme Restore Fix
- **LED GUI settings not syncing on startup**: `load_config()` correctly restored LED state, but `panel.initialize()` reset controls to defaults. Added `_sync_ui_from_state()` to push loaded state into UI after initialization.
- **`--last-one` theme restore overwriting saved preference**: Auto-fallback was persisting to config, silently overwriting the user's saved theme. Now uses `persist=False` for fallback loads.
- v6.1.4 is a re-release of v6.1.3 (PyPI rejects reuse of version+filename after tag move).

### v6.1.1–v6.1.2: Wire Remap Audit
- **Full ReSetUCScreenLED audit**: All 12 styles checked against C# `ReSetUCScreenLED*()` overrides. Styles 2 (PA120), 3 (AK120), 4 (LC1) had default constructor indices instead of style-specific overrides. 9 other styles verified correct.
- **Guard test**: `test_all_remap_indices_in_range` checks `idx < style.led_count` — catches this class of bug automatically.
- **Root cause pattern**: C# `UCScreenLED` constructor assigns Cpu1=2, SSD=6, etc. but `ReSetUCScreenLED{N}()` overrides per style. Remap tables must use the overridden indices.

### v7.0.x: GoF File Renames + SOLID Architecture
- **GoF File Renames (v7.0.1)**: 13 files in `adapters/device/` renamed to `{pattern}_{name}.py` — every adapter file named by its primary design pattern (e.g., `factory.py` → `abstract_factory.py`, `frame.py` → `template_method_device.py`)
- **SOLID Refactoring (v7.0.2)**: All 5 SOLID principles applied to device protocol architecture:
  - **ISP**: Split `DeviceProtocol` into `LCDMixin` (send_image, send_pil) + `LEDMixin` (send_led_data)
  - **LSP**: Removed `LedProtocol.send_image()` returning False, `DeviceProtocol.send_led_data()` default
  - **DIP**: Injected protocol factory into `DeviceService` via `get_protocol` param + `_get_proto()` method
  - **SRP**: Moved `detect_lcd_resolution()` from `DeviceService` to `ScsiDevice.detect_resolution()`
  - **OCP**: Added `@DeviceProtocolFactory.register()` decorator for self-registering protocols
- **Explicit Dependencies (v7.0.3)**: Added `click` as direct dependency (was transitive through `typer`). Addresses #50.
- **API DRY (v7.0.4)**: Extracted `require_connected()` into `api/models.py` — eliminated 4 duplicated dispatcher guard patterns.

### v7.0.5: QtRenderer — Eliminate PIL from Hot Path
- **Renderer ABC expanded** (`core/ports.py`): Added apply_brightness, apply_rotation, encode_rgb565, encode_jpeg, open_image, surface_size to existing Renderer ABC
- **QtRenderer** (`adapters/render/qt.py`): Full QImage/QPainter implementation — compositing, text, rotation, brightness, RGB565/JPEG encoding, font resolution. Zero PIL in hot path.
- **PilRenderer** (`adapters/render/pil.py`): Same new methods implemented with PIL (fallback only)
- **ImageService** (`services/image.py`): Now a thin facade — all methods delegate to `_renderer` via `set_renderer()` / `_r()`. Defaults to QtRenderer.
- **Font pixel sizing**: `QFont.setPixelSize(size)` — PIL callers pass pixel sizes, Qt `QFont(family, size)` interprets as points. Must use `setPixelSize()`.
- **Test infrastructure**: `conftest.py` helpers `make_test_surface()`, `surface_size()`, `get_pixel()` — all tests use native renderer surfaces
- **PIL boundary conversion**: PIL Images entering the system converted once via `renderer.from_pil()`, then flow as QImage throughout
- 4157 tests passing, ruff clean, pyright clean

### v7.0.6: SOLID Device ABCs — Replace Controller Layer
- **Device ABC** (`core/ports.py`): 4 methods (connect, connected, device_info, cleanup). Minimal contract for all devices.
- **LCDDevice** (`core/lcd_device.py`): Composed capabilities — ThemeOps, VideoOps, OverlayOps, FrameOps, DisplaySettings. Each capability delegates to services.
- **LEDDevice** (`core/led_device.py`): Direct methods — set_color, set_mode, tick, zone/segment ops. Delegates to LEDService.
- **ControllerBuilder** (`core/builder.py`): Fluent builder, returns concrete `LCDDevice`/`LEDDevice` types (not `Device` ABC).
- **TRCCApp** (`qt_components/trcc_app.py`): Thin QMainWindow shell (C# Form1 equivalent). Handlers dict, one per device.
- **LCDHandler** (`qt_components/lcd_handler.py`): One per LCD device (C# FormCZTV equivalent). Owns LCDDevice, timers, state.
- **CLI slimmed**: `_display.py` and `_led.py` are thin print wrappers — `_connect_or_fail()` → call device method → print result.
- **Deleted**: `core/controllers.py` (LCDDeviceController + LEDDeviceController), backward compat aliases (DisplayDispatcher, LEDDispatcher), 197 dead tests.
- **Test rewrites**: `test_cli_display.py`, `test_cli_led.py`, `test_qt_main_window.py`, `test_architecture.py`, `hid_testing/test_led_controller.py` — all use proper pytest fixtures.
- 4157 tests passing, ruff clean, pyright clean

### v7.0.7–v7.0.10: Bug Fixes, Cloud Parity, CI Package Deps
- **Cloud theme resolution parity**: All 32 C# v2.1.2 resolutions added to `theme_cloud.py` RESOLUTION_URLS and `tools/pack_theme_archives.py` — landscape, portrait, u/l split variants. Full match of `FormCZTV` `GifDirectoryWeb*`/`GifWebDir*` constants.
- **CI distro package dependencies fixed**: `release.yml` inline package specs (RPM, DEB, Arch `.PKGINFO`) had missing/incomplete Python deps. Root cause of #51 (typer not found on CachyOS). All three formats now declare full dependency lists matching `pyproject.toml`.
- **`tools/check_pkg_deps.py`**: NEW tool — queries Arch, Fedora, Debian repos to verify which PyPI deps have native packages vs need bundling. Found: Arch missing `python-uvicorn` (must bundle via pip), Fedora/Debian all available.
- **CodeQL fix**: Stack trace exposure in `api/display.py` preview endpoint (CWE-209). Wrapped `_encode_frame` in try/except.
- **Bulk RGB565 encoding fix**: v7.0.10 corrected bulk protocol encoding.
- 4157 tests passing, ruff clean, pyright clean

### v7.1.0–v7.1.1: Bulk FBL Bug, Theme Persist, System Install Fix
- **Bulk/LY FBL bug (#54)**: `BulkDevice.handshake()` and `LyDevice.handshake()` returned `model_id=PM` (raw handshake byte) instead of `model_id=FBL` (lookup code). GUI stored PM as `fbl_code` → `DeviceInfo.use_jpeg` computed wrong encoding. PM=32 bulk devices got JPEG encoding when they need RGB565 → scrambled display. Fixed: both now return `pm_to_fbl(pm, sub)`.
- **Theme persist on first boot**: `_restore_theme()` fallback used `persist=False`, so `--last-one` autostart never saved the theme. Fixed: `persist = not saved` — persists when no prior save existed.
- **Handshake guard**: Added `_handshake_pending` flag to prevent duplicate concurrent handshakes from device poll timer.
- **Log noise**: Removed per-frame DEBUG logs (~30/sec) from display, device, image services and factory — was rotating out useful INFO messages within seconds of video playback.
- **PermissionError on system-wide installs (#51)**: `_find_data_dir()`, `get_web_dir()`, `get_web_masks_dir()` fell back to read-only package path (`/usr/lib/python3.x/.../trcc/data/`) when no themes existed. Cloud theme `mkdir` crashed. Fixed: fallback is now `USER_DATA_DIR` (`~/.trcc/data/`), always user-writable.
- **CodeQL alert**: Restructured preview endpoint exception handling to prevent stack trace flow analysis false positive (CWE-209).
- 4157 tests passing, ruff clean, pyright clean

### v7.1.2–v7.1.4: CLI Device Selection, Software Update System
- **CLI auto-select fix**: `_get_service()` falls back to first detected device when saved device path doesn't match. Removed premature auto-select from `DeviceService.scan()` — selection is caller's responsibility.
- **Software update system** (`uc_about.py`): Version check uses GitHub releases API (not PyPI). Detects install method (pip/pipx/pacman/dnf/apt) and distro on first launch, persists to `config.json` via `Settings.get_install_info()`/`save_install_info()`. Update button toggles dark→light overlay when update available. Click triggers method-appropriate upgrade: pip/pipx run directly, package managers download from release assets + `pkexec` for sudo prompt.
- **Install info in config**: `config.json` stores `install_info.method` and `install_info.distro` — detected once, read forever. No runtime guessing after first launch.
- **GitHub release assets**: Package download URLs come from the release JSON (no hardcoded filenames). Handles Fedora version changes automatically.
- **CodeQL fix**: Restructured preview endpoint try/except to satisfy flow analysis (CWE-209).
- 4157 tests passing, ruff clean, pyright clean

### v7.1.5: Brightness Persist, Overlay Restore, Test Warnings
- **Brightness not persisting across restarts**: `_restore_brightness` called `DisplaySettings.set_brightness(percent)` which re-persisted the percent value (100) as `brightness_level`, overwriting the saved level (3). Next restart mapped 100 via `{1:25, 2:50, 3:100}.get(100, 50)` → 50% fallback. Fixed: restore now sets `DisplayService.brightness` directly, bypassing `DisplaySettings` persist side-effect. Also added `_update_ldd_icon()` after `apply_device_config()` so brightness button icon reflects restored level.
- **Stale overlay on custom theme restart (#58)**: Overlay config in `config.json` is per-device, not per-theme. Switching from official theme (with overlay) to custom theme (without) left stale overlay saved. On restart, custom theme loaded then `_restore_overlay` applied the old overlay. Fixed: `_load_theme_overlay_config` now clears and persists `enabled: False` when theme has no overlay config.
- **Test warnings eliminated**: QMouseEvent deprecated 5-arg constructor → 6-arg (added `globalPos`). Unclosed PIL `Image.open()` in `_load_mask_into` → context manager. Unclosed `HTTPError` in test mocks → explicit `.close()`. Unclosed `Image.open()` in `test_dc_writer` → context manager. pyusb `_pack_` filter fixed (`usb` → `usb.*`).
- 4157 tests passing, 0 warnings, ruff clean, pyright clean

### v8.0.0: Hexagonal Purification + CPU Optimization (-684 lines, 34%→9% CPU)
- **Hexagonal violations fixed**: `led_segment.py`, `color.py`, `paths.py` moved from `adapters/` → `core/`. Lazy-import `DataManager` in `services/display.py` (no adapter imports at module level in services).
- **Double sensor polling eliminated**: `UCInfoModule` and `UCActivitySidebar` had their own polling timers AND MetricsMediator subscriptions — double work. Removed redundant timers; MetricsMediator is now the single polling authority.
- **Preview skip when minimized**: `LCDHandler` accepts `is_visible_fn` from `TRCCApp`. Video tick and overlay render skip `set_image()` when window is minimized — no QImage scaling or QPixmap conversion for invisible widgets.
- **QMovie visibility management**: Cloud theme GIF thumbnails (`CloudThemeThumbnail._movie`) created but NOT started. `UCThemeWeb.showEvent()`/`hideEvent()` start/stop all QMovies — zero CPU when cloud panel not visible.
- **VideoFrameCache rewrite**: Replaced bulk `_build_layer4()` with lazy per-frame `_ensure_frame()` — only encodes current frame on access, caches last result. Matches C# `FormCZTV.Timer_event` approach.
- **Capability classes inlined**: `ThemeOps`, `VideoOps`, `OverlayOps`, `FrameOps`, `DisplaySettings` dissolved into `LCDDevice` directly — unnecessary indirection removed.
- **DeviceProfile table**: Replaces scattered encoding logic with a single data-driven lookup.
- **LED segment data consolidated**: `core/led_segment.py` now owns all segment display data (was in `adapters/device/led_segment.py`).
- **data_repository.py DRY**: -139 lines of duplicated archive extraction logic.
- 48 files changed, -684 net lines, 4159 tests passing, ruff clean, pyright clean

### Future Work
- Test consolidation (parametrize, merge tiny classes)
- GUI component splits (uc_theme_setting.py → 5 files)

## Style

- **OOP** — classes with clear single responsibilities. `dataclass` for data, `Enum` for categories, classmethods for factory/utility operations.
- **DRY** — extract helpers for repeated patterns, inline one-off logic. If a pattern appears 3+ times, centralize it. Two duplicates = smell; three = refactor.
- **SOLID**:
  - **SRP** — each class has one reason to change. Services own logic, views own rendering, models own data.
  - **OCP** — `@DeviceProtocolFactory.register()` decorator for self-registering protocols. New devices = new data, not modified logic.
  - **LSP** — no fake implementations (e.g. `send_image()` returning False on LED devices). If a subclass can't fulfill the contract, it shouldn't inherit it.
  - **ISP** — `LCDMixin` (send_image, send_pil) + `LEDMixin` (send_led_data) instead of one fat `DeviceProtocol`. Clients depend only on what they use.
  - **DIP** — inject dependencies at runtime (`get_protocol` param, `set_renderer()`). Core logic never imports concrete adapters.
- **Hexagonal Purity** — dependencies point inward ONLY: adapters → services → core. Services and core NEVER import from adapters. Infrastructure deps (USB, filesystem, rendering) are injected via constructor params with lazy defaults in module-level factory functions. Adapter entry points (CLI, GUI, API) are composition roots that wire concrete implementations.
- **No Fallback Imports** — services must not lazy-import adapter implementations as fallbacks. If a service needs an adapter, it must be injected. `RuntimeError` if not provided. Composition roots (`cli/__init__.py`, `trcc_app.py`, `api/__init__.py`) create and inject concrete adapters.
- **Re-export Pattern** — when moving code from adapters to core, the adapter file becomes a thin re-export stub. All existing import paths continue working.
- **Single source of truth** — every constant, mapping, and state variable has ONE canonical location. Search before defining.
- **Type hints** on all public APIs — parameters, return types, class attributes.
- **No scattered state** — mutable app state lives in `conf.Settings`, not in widget instance variables. Widgets read from the singleton.
- **No scattered data** — static domain mappings live in `core/models.py`, not in device handlers or views.
- **Import from canonical location** — `from .core.models import X`, not re-defining X locally. Re-exports are fine for convenience (e.g., `constants.py` re-exporting from models).

## Project Recap — How We Got Here

This section documents the full journey of building TRCC Linux from scratch, intended as institutional knowledge for the next project (TR-VISION HOME water-cooling LED screen control software). Everything learned here should carry forward.

### The Problem
Thermalright sells CPU coolers and AIO liquid coolers with built-in LCD displays and LED segment displays. The only software to control them (TRCC) is Windows-only, closed-source, with no Linux support. Linux users who bought these coolers had no way to use their displays.

### The Approach: Reverse Engineering Windows C#
The Windows TRCC app was decompiled (ILSpy/dnSpy → `/home/ignorant/Downloads/TRCCCAPEN/TRCC_decompiled/`). Every protocol, frame format, handshake sequence, and encoding detail was traced from the C# source. Key decompiled files:

- **FormCZTV.cs** — LCD display control (themes, video, resolution, frame encoding)
- **FormLED.cs** — LED segment display control (12 styles, zone carousel, color modes)
- **UCDevice.cs** — Device detection, HID handshake, device enumeration
- **USBLCD.exe / USBLCDNEW.exe** — SCSI and bulk USB LCD frame transfer protocols

The C# code is the ground truth. When our code doesn't match C# behavior, our code is wrong.

### Five USB Protocols Discovered
All Thermalright display devices communicate over USB, but use 5 different protocols depending on the chipset:

| Protocol | Transport | Key Discovery | Tricky Parts |
|----------|-----------|---------------|-------------|
| **SCSI** | sg (SCSI generic) | Frames sent via SG_IO ioctl, chunked writes | Chunk size varies by resolution (0xE100 for 320x240), byte order depends on FBL |
| **HID Type 2** | pyusb interrupt | DA DB DC DD magic header required | Two encoding modes: RGB565 (Mode 3) vs JPEG (Mode 2). Resolution from PM→FBL→table. Non-square displays need 90° CW pre-rotation |
| **HID Type 3** | pyusb interrupt | Fixed 204816-byte frames, ALi chipset | Different handshake and ACK pattern |
| **Bulk** | pyusb bulk | Vendor-specific USB class (not HID) | JPEG encoding only, kernel driver detach issues on SELinux |
| **LY** | pyusb bulk | Chunked 512-byte frames (16-byte header + 496 data) | Two PID variants (LY=0x5408, LY1=0x5409) with different PM formulas and chunk padding |
| **LED** | pyusb HID | 64-byte reports, wire remap tables | Each of 12 device styles has different LED count, segment layout, and wire ordering |

### Resolution Discovery Pipeline (Hardest Problem)
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

### RGB565 Encoding Gotchas
- **Byte order varies by device**: 320x320 and SPIMode=2 devices (FBL 51, 53) use big-endian. Everything else uses little-endian. Getting this wrong produces "pop art" color distortion.
- **Pre-rotation**: Non-square LCD panels are physically mounted in portrait. Software must rotate 90° CW before encoding. Square displays skip this.
- **JPEG mode**: Large-resolution devices (360x360+) use JPEG instead of RGB565. Header byte[6] = 0x00 (JPEG) vs 0x01 (RGB565), with actual width/height instead of hardcoded 240x320.
- **Frame headers matter**: Every byte in the protocol header exists for a reason. The DA DB DC DD magic was missing for months — firmware silently rejected frames.

### LED Segment Display Architecture
12 device styles (PA120, AX120, AK120, LC1, LF8, LF10, LF12, CZ1, LC2, LF11, LF13, LF15), each with unique LED counts (30-116), segment layouts, and wire remap tables. Data varies, logic is shared:

- **SegmentDisplay ABC** with 10 subclasses — each defines indices, digit positions, indicator positions, zone maps
- **LEDService** — single renderer that uses the display's data to compute masks
- **Wire remap tables** — C# `SendHidVal` reorders LEDs from logical to hardware positions. Missing remap = colors on wrong physical LEDs
- **Zone carousel (circulate)** — C# `isLunBo`: toggles zones in/out, rotates active zone on timer. Zones drive segment data source (CPU/GPU), not LED color (except styles 2/7 which have physical per-zone LEDs)

### What Worked Well
1. **Hexagonal architecture** — CLI, GUI, and API all adapt to the same core services. Adding the API took hours, not weeks. Device protocols slot in as new adapter subclasses.
2. **C# as ground truth** — every bug we fixed was traced back to "our code doesn't match C#". The decompiled source eliminated guesswork.
3. **Data-driven design** — FBL tables, wire remap tables, LED style configs, segment display layouts are all data. Logic operates on data. New devices = new data, not new logic.
4. **Test suite (4157 tests)** — catches regressions immediately. Every fix includes tests. Mock USB devices for protocol testing.
5. **`trcc report` diagnostic** — users paste one command output and we get VID:PID, PM, FBL, resolution, raw handshake bytes, permissions, SELinux status. Eliminates back-and-forth.
6. **GoF patterns applied pragmatically** — Facade (controllers), Flyweight+Strategy (segment displays), Template Method (protocol handshakes), Memento (LED config), Observer (metrics), Command (dispatchers). Each pattern solved a real problem, not applied for theory.

### What Caused the Most Bugs
1. **Missing FBL/PM mappings** — every new device type needed its entry. Default (320, 320) silently broke everything.
2. **Byte order mismatches** — big-endian vs little-endian RGB565. Two bytes per pixel, wrong order = every color wrong.
3. **Wire remap tables** — one shifted index corrupts every LED after it. Must match C# `SendHidVal` exactly.
4. **Frame headers** — missing magic bytes, wrong command codes, hardcoded dimensions where actual were needed.
5. **State not propagated** — handshake discovers resolution/FBL but the value never reaches the encoding layer. Multiple fixes for "fbl not propagated from handshake."
6. **Linux-specific USB issues** — kernel driver detach, SELinux blocking, polkit for udev rules, UsrMerge symlink differences, XFCE session not "active" in logind.

### Version Evolution (v1.0 → v6.6.1)
- **v1.x** (17 releases) — Basic GUI, SCSI protocol, theme loading, bug-fixing spree
- **v2.0** — Module rename/restructure, HR10 LED backend, PM/FBL unification
- **v3.0** — Hexagonal architecture, services layer, CLI (Typer), REST API, 2081→2166 tests
- **v4.0** — Adapters restructure, domain data consolidation, setup wizard, SELinux support
- **v5.0** — Full C# feature parity audit (35 items), video fit-mode, all LED wire remaps, JPEG encoding for large displays
- **v6.0** — GoF refactoring (-1203 lines), CLI dispatchers, metrics observer, LED test harness, circulate fix, FBL table completion
- **v7.0** — GoF file renames (13 files → `{pattern}_{name}.py`), SOLID refactoring (ISP/LSP/DIP/SRP/OCP), explicit click dependency, API DRY extraction, QtRenderer migration (eliminate PIL from hot path), SOLID Device ABCs (LCDDevice/LEDDevice replace controller layer), cloud theme resolution parity (all 32 C# resolutions), CI distro package dep fixes, 4157 tests
- **v6.6** — LCD preview stream (direct IPC frame read from GUI daemon, steady-fps WebSocket, no poll thread), overlay metrics loop for standalone themes, video playback background thread, API spec + Flutter remote guide, `on_frame_sent` callback on DeviceService, MetricsMediator, 4496 tests
- **v6.5** — IPC daemon (GUI-as-server, CLI auto-routes through Unix socket), info module decoupling, video background save fix, 4440 tests
- **v6.3–v6.4** — Codebase minimization, DRY refactoring, test suite expansion (2509→4440 tests, 39→54 files, 76% coverage)
- **v6.2** — REST API static files, `trcc api` command, LY protocol integration, HiDPI fix, DRY refactoring (3 duplications eliminated, Strategy pattern), 2509 tests
- **v6.1** — REST API full CLI parity (35 endpoints), full wire remap audit (3 styles fixed), LY protocol, TLS, portrait cloud dirs, 2439 tests

### Applying This to TR-VISION HOME
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
