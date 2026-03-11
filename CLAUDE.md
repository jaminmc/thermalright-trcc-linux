# TRCC Linux — Claude Code Project Instructions

## Architecture — Hexagonal (Ports & Adapters)

### Layer Map
- **Models** (`core/models.py`): Pure dataclasses, enums, domain constants — zero logic, zero I/O, zero framework deps
- **Services** (`services/`): Core hexagon — all business logic, pure Python. `ImageService` is a thin facade delegating to the active `Renderer` (QtRenderer by default). `OverlayService` uses injected Renderer for compositing/text.
- **Paths** (`core/paths.py`): Application path constants and directory resolution — `DATA_DIR`, `USER_DATA_DIR`, `get_web_dir()`, `get_web_masks_dir()`. Zero project imports, safe from any module. Pure path logic only.
- **Devices** (`core/lcd_device.py`, `core/led_device.py`): Application-layer facades living in `core/` for import convenience. `LCDDevice`/`LEDDevice` use deferred imports from services and adapters at method call time (not module load). They delegate to services and return result dicts. Not domain objects — they're composition roots that wire services together per operation.
- **Builder** (`core/builder.py`): `ControllerBuilder` — fluent builder, assembles devices with DI, returns `LCDDevice`/`LEDDevice`. Composition root: imports adapters to inject into services.
- **Views** (`qt_components/`): PySide6 GUI adapter. `TRCCApp` (thin shell) + `LCDHandler`/`LEDHandler` (one per device).
- **CLI** (`cli/`): Typer CLI adapter (package: `__init__.py` + 7 submodules). Thin presentation wrappers over `LCDDevice`/`LEDDevice` — connect, call device method, print result.
- **API** (`api/`): FastAPI REST adapter (package: `__init__.py` + 7 submodules). 43 endpoints covering devices, display, LED, themes, and system metrics. Includes WebSocket live preview stream + cloud theme download. Uses `LCDDevice`/`LEDDevice` from core/. `_current_image` tracks last frame sent for preview endpoints.
- **Config** (`conf.py`): Application settings singleton — resolution, language, temp unit, device prefs. Single source of truth for all mutable app state.
- **Entry**: `cli/` → `trcc_app.py` (TRCCApp) → builder.build_lcd()/build_led()
- **Protocols**: SCSI (LCD frames), HID (handshake/resolution), LED (RGB effects + segment displays)
- **On-demand download**: Theme/Web/Mask archives fetched from GitHub at runtime via `data_repository.py`

### Design Patterns (Gang of Four + Architectural)

#### Creational — Object creation mechanisms
- **Singleton**: Ensures a class has only one instance and provides a global access point to it. Used: `conf.settings` — app-wide state (resolution, language, preferences). Widgets read from singleton, never store their own copies
- **Factory Method**: Defines an interface for creating an object, but lets subclasses decide which class to instantiate. Used: `abstract_factory.py` builds protocol-specific device adapters (CLI, GUI, or API)
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
- **Tests**: `pytest` with `PYTHONPATH=src`; 4660 tests across 57+ files in 9 directories mirroring `src/trcc/` hexagonal layers (`tests/{core,services,adapters/{device,infra,system},cli,api,qt_components}/`). Cross-cutting tests at `tests/` root. When refactoring changes mock targets, use `conftest.py` fixtures/helpers — never update 50+ individual test mock paths inline. Shared mock helpers go in conftest.
- **Linting**: `ruff check .` + `pyright` must pass before any commit (0 errors, 0 warnings)
- **Security**: Zero tolerance for CodeQL / OWASP findings — see **Security** section below
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

## Security

Zero tolerance for security issues. Fix properly within hexagonal/SOLID architecture — never suppress with shortcuts.

### Principles
- **Fix at the boundary, keep core pure** — all input validation happens in adapter layers (API, CLI). Core services and domain models trust their inputs because adapters already validated them.
- **No suppression comments** — no `# nosec`, no `# type: ignore` for security findings, no `# noqa` to silence security rules. Fix the root cause.
- **CodeQL must stay clean** — every push runs CodeQL. Zero open alerts. False positives get fixed (write better code that doesn't trigger them), not dismissed.

### Subprocess & Command Injection
- **Never interpolate user input into shell commands** — use `subprocess.run([...], shell=False)` with argument lists, never f-strings or `.format()` into shell strings
- **`pkexec` calls** — pass exact command + args as list, never construct shell strings for privilege escalation
- **System metric commands** — hardcoded command lists only, no user-controlled arguments

### API (FastAPI) — The Network Boundary
- **Validate all path parameters** — theme names, file paths, device IDs. Reject path traversal (`..`, absolute paths)
- **No stack traces in responses** — catch exceptions, return structured error responses. Never expose internal paths, file locations, or Python tracebacks to API clients
- **Structured error responses** — `{"error": "descriptive message"}` with appropriate HTTP status codes
- **Type-safe endpoints** — use Pydantic models / FastAPI path/query parameter types for automatic validation

### File System & Path Safety
- **Zip extraction** — validate every member path before extracting. Reject entries containing `..` or absolute paths (zip slip prevention)
- **Theme/mask paths** — resolve to canonical path with `.resolve()`, verify the result is under the expected data directory before reading/writing
- **Config files** — `json.load()` with try/except for `JSONDecodeError` and `KeyError`. Malformed `~/.trcc/config.json` must never crash the app — fall back to defaults
- **Temp files** — use `tempfile.mkstemp()` or `tempfile.TemporaryDirectory()`, never predictable paths in `/tmp`

### USB Device I/O
- **Bounds-check device responses** — validate handshake byte lengths before indexing. A malformed HID report must not cause `IndexError` or buffer overread
- **Timeout all USB operations** — never block indefinitely waiting for device response
- **Graceful degradation** — device returning garbage data = log warning + disconnect, never crash

### Downloads & Network
- **Pin download URLs to known GitHub repo** — `https://github.com/Lexonight1/thermalright-trcc-linux/` prefix only. Never follow redirects to arbitrary hosts
- **Validate downloaded content** — check expected file structure after extraction, don't blindly trust archive contents

### Tests
- **Use exact values** — full URLs, complete paths, specific strings. Never partial substring checks that trigger static analysis warnings (e.g., `"github.com" in url` → use full URL match)
- **No `# nosec` in tests either** — tests are code too, and CodeQL scans them

## Known Issues
- `pyusb 1.3.1` uses deprecated `_pack_` in ctypes (Python 3.14) — suppressed in pytest config until upstream fix
- `pip install .` can use cached wheel — use `pip install --force-reinstall --no-deps .` when testing
- CI runs as root — mock `subprocess.run` in non-root tests to prevent actual sudo execution
- Never set `setStyleSheet()` on ancestor widgets — it blocks `QPalette` image backgrounds on descendants
- Optional imports (`hid`, `dbus`, `gi`, `pynvml`) need `# pyright: ignore[reportMissingImports]` — they're in try/except blocks but pyright still flags them
- **Tag push triggers PyPI release** — after pushing a release, always `git tag v{version} && git push origin v{version}`. Do this automatically, don't ask.
- **Don't close GitHub issues until the reporter confirms the fix works** — reopening looks bad
- **Never use "Fixes #N" in commit messages** — GitHub auto-closes issues on push to default branch. We don't close until reporter confirms.
- **GitHub issue/PR reply footer** — every reply MUST end with a funding reminder. Check the issue reporter: if they've donated before (listed in README thanks section), thank them by name and mention their platform. For everyone else, use the generic footer: `\n\n---\nIf this project helps you, consider [buying me a beer](https://buymeacoffee.com/Lexonight1) 🍺 or [Ko-fi](https://ko-fi.com/lexonight1) ☕`
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
3. Update `doc/CHANGELOG.md` with new version entry
4. Run `ruff check .` + `pyright` — fix any issues (0 errors, 0 warnings)
5. Run `PYTHONPATH=src pytest tests/ -x -q` — all tests must pass
6. Squash or keep commits as-is, then push to `main`
7. Tag and push: `git tag v{version} && git push origin v{version}` — this triggers CI to build + publish to PyPI. Do NOT run `twine upload` manually.
8. GitHub Release: `gh release create v{version} --target main --title "v{version}"` with release notes
9. Comment on relevant GitHub issues if the release affects them

### Trigger Words
When the user says one bare word — `patch`, `minor`, or `major` — execute the full release workflow:
1. Bump version (`patch`: 8.1.10→8.1.11, `minor`: 8.1.10→8.2.0, `major`: 8.1.10→9.0.0) in **both** `src/trcc/__version__.py` AND `pyproject.toml`
2. Add version history entry in `__version__.py`
3. Update `doc/CHANGELOG.md` with new version entry
4. Update inline package specs in `release.yml` (version strings)
5. Update README native package URLs to new version
6. `ruff check .` + `pyright` — fix any issues
7. `PYTHONPATH=src pytest tests/ -x -q` — all tests must pass
8. Commit + push to `main`
9. `git tag v{version} && git push origin v{version}`
10. `gh release create v{version} --target main --title "v{version}"` with release notes

### Rules
- **Version bump = release boundary** — no bump means still in development
- **Don't push mid-development** — partial fixes confuse users who install from GitHub
- **Tag push = PyPI release** — always tag after pushing a version bump, CI publishes automatically. Never suggest manual `twine upload`
- **Batch related changes** — one version bump covers all related commits
- **Never push without explicit user instruction** (except via trigger words above)

## Project GUI Standards
- **Overlay enabled state**: `_load_theme_overlay_config()` must call `set_overlay_enabled(True)` — the grid's `_overlay_enabled` flag gates `to_overlay_config()` output
- **Format preferences**: Time/date/temp format choices persist in `config.json` via `conf.save_format_pref()` and get applied to any theme on load via `conf.apply_format_prefs()`
- **Theme loads DC for layout, user prefs for formats**: Theme's `config1.dc` defines which elements and where; user's format prefs (time_format, date_format, temp_unit) override format fields
- **Signal chain for element changes**: format button → `_on_format_changed()` → `_update_selected()` → `to_overlay_config()` → `CMD_OVERLAY_CHANGED` → `_on_overlay_changed()` → `render_overlay_and_preview()`
- **QPalette vs Stylesheet**: Never set `setStyleSheet()` on ancestor widgets — blocks `QPalette` image backgrounds on all descendants
- **First-run state**: On fresh install with no device config, `_on_device_selected()` disables overlay. Theme click re-enables it. Format prefs default to 0 (24h, yyyy/MM/dd, Celsius)
- **Delegate pattern**: Settings tab communicates via `invoke_delegate(CMD_*, data)` to main window
- **`_update_selected(**fields)`**: Single entry point for all element property changes (color, position, font, format, text)

### Completed Splits
- `uc_theme_setting.py` split into 5 files: `overlay_element.py`, `overlay_grid.py`, `color_and_add_panels.py`, `display_mode_panels.py`, + thin orchestrator `uc_theme_setting.py` (re-exports all public names)

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

## Reference Docs
- **Architecture history** (GoF refactoring, SOLID evolution, v6.0–v8.1): `doc/HISTORY_ARCHITECTURE.md`
- **Project history** (reverse engineering journey, protocols, lessons learned): `doc/HISTORY_PROJECT.md`
- **Changelog** (per-version release notes): `doc/CHANGELOG.md`
