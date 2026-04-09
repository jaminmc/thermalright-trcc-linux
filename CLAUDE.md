# TRCC Linux — Claude Code Project Instructions

## Architecture — Hexagonal (Ports & Adapters)

### Layer Map
- **Models** (`core/models.py`): Pure dataclasses, enums, domain constants — zero logic, zero I/O, zero framework deps
- **Services** (`services/`): Core hexagon — all business logic, pure Python. `ImageService` delegates to active `Renderer`. `OverlayService` uses injected Renderer for compositing/text.
- **Paths** (`core/paths.py`): Fallback path constants (`DATA_DIR`, `USER_DATA_DIR`). Primary resolution via `PlatformSetup` adapter injected into `Settings`. Zero project imports.
- **Devices** (`core/lcd_device.py`, `core/led_device.py`): Application-layer facades. Strict DI — `RuntimeError` if deps not injected. Zero adapter imports. Delegate to services, return result dicts.
- **Builder** (`core/builder.py`): `ControllerBuilder` — fluent builder, assembles devices with DI. Composition root: imports adapters to inject into services.
- **Views** (`gui/`): PySide6 GUI adapter. `TRCCApp` (thin shell) + `LCDHandler`/`LEDHandler` (one per device).
- **CLI** (`cli/`): Typer CLI adapter (package: `__init__.py` + 8 submodules). Thin wrappers over `LCDDevice`/`LEDDevice`.
- **API** (`api/`): FastAPI REST adapter (package: `__init__.py` + 7 submodules). 49 endpoints. WebSocket preview stream + cloud themes + export. Uses `LCDDevice`/`LEDDevice` from core/.
- **Config** (`conf.py`): `Settings(path_resolver)` receives `PlatformSetup` via constructor. `init_settings(resolver)` called by composition roots. Single source of truth for mutable app state.
- **Entry**: `cli/` → `trcc_app.py` (TRCCApp) → builder.build_lcd()/build_led()
- **Protocols**: SCSI (LCD frames), HID (handshake/resolution), LED (RGB effects + segment displays)
- **Platform** (`core/platform.py`): `WINDOWS`, `LINUX`, `MACOS`, `BSD` flags. `builder.py` routes to platform-specific adapters.
- **Platform adapters** (`adapters/{device,system}/{windows,macos,bsd}/`): Each has detector, SCSI transport, sensor enumerator, hardware info. Same interface as Linux adapters.
- **CI**: `release.yml` (Linux RPM/DEB/Arch), `windows.yml` (PyInstaller + Inno Setup), `macos.yml` (PyInstaller + create-dmg)
- **On-demand download**: Theme/Web/Mask archives fetched from GitHub at runtime via `data_repository.py`

### Design Patterns (Used in This Project)
- **Singleton**: `conf.settings` — app-wide state. Widgets read from singleton, never store copies.
- **Factory Method**: `abstract_factory.py` builds protocol-specific device adapters
- **Adapter**: Hexagonal adapters/ — CLI, GUI, API all adapt to the same core services
- **Command**: User actions (button click, terminal command) — log, undo, queue across interfaces
- **Observer**: PySide6 signals broadcast updates from core to views without coupling
- **Strategy**: Swap display/export behaviors without modifying core service logic
- **Template Method**: Concrete method on ABC calls `@abstractmethod` on subclass (e.g. `handshake()` → `_do_handshake()`)
- **Dependency Injection**: Inject dependencies at runtime, never hardcode
- **Repository Pattern**: `data_repository.py` — service layer doesn't know if data comes from file, DB, or API
- **Ports & Adapters**: ABCs as contracts; CLI, GUI, API interact with core the same way
- **DTOs**: `dataclass` for passing data across hexagonal boundaries

### Abstract Base Classes (ABCs)
Two layers: **transport** (raw device I/O) and **adapter** (MVC integration).

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
├── LCDMixin — send_image() (abstract, ISP)
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
| `Renderer` | `core/ports.py` | QtRenderer (1) | Image rendering — compositing, text, encoding, rotation. PIL eliminated. |
| `UsbTransport` | `adapters/device/hid.py` | PyUsbTransport, HidApiTransport (2) | USB I/O abstraction — mockable for tests |
| `SegmentDisplay` | `adapters/device/led_segment.py` | AX120, PA120, AK120, LC1, LF8, LF12, LF10, CZ1, LC2, LF11 (10) | LED 7-segment mask computation per product |
| `BasePanel` | `gui/base.py` | UCDevice, UCAbout, UCPreview, UCThemeSetting, BaseThemeBrowser (5+3 indirect) | GUI panel lifecycle: `_setup_ui()` enforced, `apply_language()`, `get_state()`/`set_state()` |

**Rules**:
- ABC = contract + shared behavior (no Java-style `IFoo` + `AbstractFoo` split)
- ABC at architectural boundaries even with 1 implementation — extensibility for future devices
- Don't add `typing.Protocol` unless third-party plugins need it
- PySide6 metaclass conflict: `QFrame` + `ABC` raises `TypeError` → use `__init_subclass__` (see `BasePanel`)

### Data Ownership
Every piece of data has exactly ONE owner. Violations = bugs.

| Data Kind | Owner | Examples |
|-----------|-------|---------|
| Domain constants (static mappings) | `core/models.py` | `FBL_TO_RESOLUTION`, `LOCALE_TO_LANG`, `HARDWARE_METRICS`, `TIME_FORMATS` |
| Device registries (VID/PID, protocol) | `core/models.py` | VID/PID tables, device type enums |
| Mutable app state (user prefs) | `conf.py` → `Settings` | resolution, language, temp_unit, format prefs |
| GUI asset resolution | `gui/assets.py` → `Assets` | file lookup, `.png` auto-append, pixmap loading, localization |
| Business logic | `services/` | image processing, overlay rendering, sensor polling |
| View state (widget-local) | Each widget | button states, selection indices, animation counters |

**Rules**:
- Models own ALL static domain data — lookups, mappings, enums, constants go in `core/models.py`
- Settings owns ALL mutable app state — widgets read `settings.X`, never store own copies
- Assets owns ALL asset resolution — no manual `f"{name}.png"` anywhere
- Services own ALL business logic — pure Python, no Qt, no framework deps
- Views own ONLY rendering — read from Settings/Models, call Services, display results

## Conventions

### Code Style
- **OOP** — classes with clear SRP. `dataclass` for data, `Enum` for categories.
- **Pure Python** — use the language to its fullest. Dunders (`__getitem__`, `__contains__`, `__iter__`, `__len__`) for registry classes so data describes itself. `@property` for derived attributes. `match/case` for pattern dispatch. Generators for lazy iteration. Context managers for resource lifecycle. Data should be self-describing — behavior derived from structure, not plumbing code.
- **DRY** — 3+ duplicates = centralize. Two = smell. One-off = inline.
- **Type hints** on all public APIs
- **Logging**: `log = logging.getLogger(__name__)` — never `print()`
- **Paths**: `pathlib.Path` preferred; `os.path` only in `data_repository.py`
- **Thread safety**: Qt signals for background→GUI communication — never `QTimer.singleShot` from non-main threads
- **Import from canonical location** — `from .core.models import X`, not re-defining locally

### SOLID
- **SRP** — services own logic, views own rendering, models own data
- **OCP** — `@DeviceProtocolFactory.register()` for self-registering protocols. New devices = new data, not modified logic.
- **LSP** — no fake implementations. If a subclass can't fulfill the contract, don't inherit.
- **ISP** — `LCDMixin` + `LEDMixin` instead of one fat `DeviceProtocol`
- **DIP** — inject dependencies at runtime. Core never imports concrete adapters.

### Hexagonal Purity
- Dependencies point inward ONLY: adapters → services → core
- Services and core NEVER import from adapters
- Infrastructure deps injected via constructor params
- Composition roots (CLI, GUI, API) wire concrete implementations
- No fallback imports — services must not lazy-import adapters. `RuntimeError` if not injected.
- No workarounds — find root cause, fix it. No silent degradation, no environment sniffing, no dual code paths.

### Testing
- `pytest` with `PYTHONPATH=src`; run: `PYTHONPATH=src pytest tests/ -n 8 -x -q`
- Tests mirror `src/trcc/` hexagonal layers (`tests/{core,services,adapters/{device,infra,system},cli,api,gui}/`)
- Refactoring changes mock targets → use `conftest.py` fixtures/helpers, not 50+ inline updates
- Model-parametrized tests: `FBL_PROFILES`, `LED_STYLES`, `ALL_DEVICES` are single source of truth — `@pytest.mark.parametrize` over them. Never hardcode domain values in tests.
- `ruff check .` + `pyright` must pass before any commit (0 errors, 0 warnings)

### Patterns for Adding Things

**New domain data** (constant, mapping, enum):
1. Search `core/models.py` first — may already exist
2. Add to `core/models.py` with section comment
3. `from .core.models import MY_CONSTANT` where needed

**New app state** (user preference):
1. Add to `Settings` — `_get_saved_X()` / `_save_X()` + public `set_X()`
2. Persist in `config.json` via `load_config()` / `save_config()`
3. Widgets read `settings.X` — never pass through constructor chains

**New assets**:
1. Put file in `src/trcc/assets/gui/`
2. Reference by base name — `Assets.get('MY_ASSET')` auto-resolves `.png`
3. Localized variants: `{base}{lang}.png`, use `Assets.get_localized()`

## Security

Zero tolerance for security issues. Fix within hexagonal architecture — never suppress.

### Principles
- Fix at the boundary, keep core pure — validation in adapter layers (API, CLI)
- No suppression comments — no `# nosec`, `# type: ignore` for security, `# noqa`
- CodeQL must stay clean — zero alerts, false positives get fixed not dismissed

### Rules by Area
- **Subprocess**: `subprocess.run([...], shell=False)` with arg lists. Never interpolate user input. `pkexec` = exact command list.
- **API**: Validate all path params (reject `..`, absolute paths). No stack traces in responses. Structured error responses with Pydantic.
- **File system**: Zip slip prevention (validate members before extracting). Theme/mask paths `.resolve()` + verify under expected dir. Config `json.load()` with try/except, fall back to defaults.
- **USB**: Bounds-check handshake bytes. Timeout all operations. Garbage data = log + disconnect, never crash.
- **Downloads**: Pin to `https://github.com/Lexonight1/thermalright-trcc-linux/`. Validate content after extraction.
- **Tests**: Full exact values, no partial substring checks. No `# nosec` in tests.

## Known Issues
- `pyusb 1.3.1` deprecated `_pack_` on Python 3.14 — suppressed in pytest config
- `pip install .` can use cached wheel — use `pip install --force-reinstall --no-deps .`
- CI runs as root — mock `subprocess.run` in non-root tests
- Never `setStyleSheet()` on ancestor widgets — blocks `QPalette` image backgrounds
- Optional imports (`hid`, `dbus`, `gi`, `pynvml`) need `# pyright: ignore[reportMissingImports]`
- C# asset suffixes are legacy — `Assets.get_localized()` maps ISO 639-1 → legacy suffixes via `ISO_TO_LEGACY`
- **Issue #87**: Python 3.14 typer crash in `sudo_reexec` — FIXED: dispatches via `python -c` (direct function call), bypasses typer.

## GitHub Issues
- Never use "Fixes #N" in commit messages — GitHub auto-closes on push to default branch
- Don't close issues until reporter confirms the fix works
- Every reply ends with funding footer: `\n\n---\nIf this project helps you, consider [buying me a beer](https://buymeacoffee.com/Lexonight1) 🍺 or [Ko-fi](https://ko-fi.com/lexonight1) ☕`
- Check if reporter is a donor (README thanks section) — thank by name if so
- **Package upgrade instructions must be copy-paste ready** — always provide the full `wget -c <URL>` + install command so users can paste directly into their terminal. Use the actual download URL from `gh release view --json assets`, not just "go to Releases page". Distro-specific:
  - Arch: `wget -c <url>.pkg.tar.zst && sudo pacman -U trcc-linux-*.pkg.tar.zst`
  - Fedora: `wget -c <url>.rpm && sudo dnf install ./trcc-linux-*.rpm`
  - Ubuntu/Debian (legacy): `wget -c <url>.legacy_all.deb && sudo dpkg -i trcc-linux_*.legacy_all.deb`
  - Ubuntu/Debian (standard): `wget -c <url>.deb && sudo dpkg -i trcc-linux_*.deb`

## Deployment
- Default branch: `main`
- Never push without explicit user instruction
- Dev repo: `~/Desktop/projects/thermalright/trcc-linux`
- Testing repo: `~/Desktop/trcc_testing/thermalright-trcc-linux/`
- PyPI: `trcc-linux` (published)
- Tag push triggers PyPI release — always `git tag v{version} && git push origin v{version}` after push

## Development Workflow

### Plan Before Coding
Non-trivial changes: think through full impact, state plan, wait for confirmation, THEN implement in one pass. Never jump in and patch as you go.

### Two Modes

**Development** — local commits, no push, no version bump:
- Small logical commits to `main`
- `ruff check .` + `pyright` before each commit
- Do NOT push or bump version

**Release** — validated and ready for users:
1. `ruff check .` + `pyright` — 0 errors
2. `PYTHONPATH=src pytest tests/ -n 8 -x -q` — all pass
3. Commit + push existing changes to `main`
4. Bump version in `src/trcc/__version__.py`, `pyproject.toml`, AND `flake.nix`
5. Add version history entry in `__version__.py`
6. Update `doc/CHANGELOG.md`
7. Lint + test again
8. Commit + push version bump to `main`
9. `git tag v{version} && git push origin v{version}` (triggers CI + PyPI)
10. `gh release create v{version} --target main --title "v{version}"`
11. Comment on relevant GitHub issues

### Trigger Words
Bare `patch`, `minor`, or `major` → full release workflow:
1. Lint + test uncommitted changes first
2. Commit + push existing changes to `main`
3. Bump version in `__version__.py`, `pyproject.toml`, `flake.nix`
4. Version history + changelog
5. Update `release.yml` inline package specs (download URLs use fixed-name aliases — no version in guide/README URLs)
6. Lint + test again
7. Commit + push version bump + tag + GitHub release

## GUI Standards
- **Overlay enabled**: `_load_theme_overlay_config()` must call `set_overlay_enabled(True)`
- **Format prefs**: Persist via `conf.save_format_pref()`, applied on theme load via `conf.apply_format_prefs()`
- **Theme loads**: DC for layout, user prefs for formats (time_format, date_format, temp_unit)
- **Signal chain**: format button → `_on_format_changed()` → `_update_selected()` → `to_overlay_config()` → `CMD_OVERLAY_CHANGED` → `_on_overlay_changed()` → `render_overlay_and_preview()`
- **QPalette vs Stylesheet**: Never `setStyleSheet()` on ancestors — blocks palette backgrounds
- **First-run**: No device config → overlay disabled. Theme click re-enables. Defaults: 24h, yyyy/MM/dd, Celsius.
- **First install auto-load**: `EnsureDataCommand` extracts in background → `notify_data_ready()` → `_update_theme_directories()` → auto-loads first theme if `current_image is None`
- **Delegate pattern**: Settings tab → `invoke_delegate(CMD_*, data)` → main window
- **`_update_selected(**fields)`**: Single entry point for element property changes

## Reference Docs
- Architecture history: `doc/HISTORY_ARCHITECTURE.md`
- Project history: `doc/HISTORY_PROJECT.md`
- Changelog: `doc/CHANGELOG.md`

## Execution Boundaries (Non-Negotiable)

### File Modification Rules
- Only modify files explicitly named in the request
- If a fix requires touching an unspecified file, STOP and ask first
- Do not clean up related code while inside a file
- Do not create new files without explicit instruction

### Before Every File You Touch
1. Which layer is this file in?
2. Which port interface does it implement or consume?
3. Does any import violate the layer law?

### Complexity Calibration
- Trivial: execute directly, no preamble
- Moderate: one sentence stating approach, then execute
- Complex: full plan, wait for confirmation, implement in one pass

### On Uncertainty
If the boundary is unclear — stop and ask.
A precise question is better than a confident wrong answer.

### Behavioral Rules
- **Listen and implement** — implement what the user says, don't reinterpret. Device type is a boolean from discovery, config data makes the object, handler manipulates it. Keep it simple.
- **Never post to GitHub without approval** — always show the draft first, wait for explicit "post it" / "ok" before running `gh issue comment` or `gh pr create`. The user is the maintainer — their voice, their project.
- **Be honest about fixes** — never claim a bug is fixed unless the specific code change addresses the specific problem. Refactors don't fix user bugs. Don't reply to issues with upgrade instructions when the bug isn't actually fixed.
- **Plan before patching** — don't jump to code edits on bug reports. Read all relevant code, trace the full flow, use web search to understand platform-specific behavior, enter plan mode, get confirmation, then implement in one pass. Don't assume cross-platform bugs without evidence from each platform.
