# Architecture

## Hexagonal (Ports & Adapters)

The project follows hexagonal architecture. The **services layer** is the core hexagon containing all business logic (pure Python, no framework deps). Four driving adapters consume the services via **Device ABCs** (`LCDDevice` / `LEDDevice`):

- **CLI** (`cli/` package) — Typer, 50 commands across 8 submodules. Thin presentation wrappers over `LCDDevice`/`LEDDevice` — connect, call device method, print result.
- **GUI** (`qt_components/`) — PySide6, `TRCCApp` (thin shell) + `LCDHandler` (one per LCD device)
- **API** (`api/` package) — FastAPI REST adapter, 43 endpoints across 7 submodules
- **IPC** (`ipc.py`) — Unix socket daemon for GUI-as-server single-device-owner safety
- **Setup GUI** (`install/gui.py`) — Standalone PySide6 setup wizard

## Project Layout

```
src/trcc/
├── cli/                         # Typer CLI adapter package (8 submodules)
├── api/                         # FastAPI REST adapter package (7 submodules)
│   ├── __init__.py              # App factory, middleware, CORS
│   ├── devices.py               # Device endpoints (detect, select, info)
│   ├── display.py               # Display endpoints (send, color, brightness, rotation)
│   ├── led.py                   # LED endpoints (color, mode, brightness, sensor)
│   ├── themes.py                # Theme endpoints (list, load, save, export, import)
│   ├── system.py                # System endpoints (info, metrics, screencast)
│   └── models.py                # Pydantic request/response models + require_connected()
├── ipc.py                       # Unix socket IPC daemon (GUI-as-server)
├── conf.py                      # Settings singleton + persistence helpers
├── __version__.py               # Version info
├── adapters/
│   ├── device/                       # USB device protocol handlers (GoF-named)
│   │   ├── template_method_device.py # UsbDevice / FrameDevice / LedDevice ABCs
│   │   ├── template_method_hid.py    # HID USB transport (PyUSB)
│   │   ├── _template_method_bulk.py  # Bulk-like USB base class
│   │   ├── abstract_factory.py       # Protocol factory + LCDMixin/LEDMixin ABCs
│   │   ├── adapter_scsi.py           # SCSI protocol (sg_raw)
│   │   ├── adapter_bulk.py           # Raw USB bulk protocol
│   │   ├── adapter_ly.py             # LY USB bulk protocol (0416:5408/5409)
│   │   ├── adapter_led.py            # LED RGB protocol (effects, HID sender)
│   │   ├── adapter_led_kvm.py        # KVM LED backend
│   │   ├── adapter_hr10.py           # HR10 LED backend
│   │   ├── strategy_segment.py       # Segment display renderer (10 styles)
│   │   ├── facade_lcd.py             # SCSI RGB565 frame send
│   │   └── registry_detector.py      # USB device scan + registries
│   ├── render/                  # Rendering backends (Strategy pattern)
│   │   ├── qt.py                # QtRenderer — primary (QImage/QPainter)
│   │   └── pil.py               # PilRenderer — CPU-only PIL/Pillow fallback
│   ├── system/                  # System integration
│   │   ├── sensors.py           # Hardware sensor discovery + collection
│   │   ├── hardware.py          # Hardware info (CPU, GPU, RAM, disk)
│   │   ├── info.py              # Dashboard panel config
│   │   └── config.py            # Dashboard config persistence
│   └── infra/                   # Infrastructure (I/O, files, network)
│       ├── data_repository.py   # XDG paths, on-demand download
│       ├── binary_reader.py     # Binary data reader
│       ├── dc_parser.py         # Parse config1.dc overlay configs
│       ├── dc_writer.py         # Write config1.dc files
│       ├── dc_config.py         # DcConfig class
│       ├── font_resolver.py     # Cross-distro font discovery
│       ├── media_player.py      # FFmpeg video frame extraction
│       ├── theme_cloud.py       # Cloud theme HTTP fetch
│       ├── theme_downloader.py  # Theme pack download manager
│       ├── debug_report.py      # Diagnostic report tool
│       └── doctor.py            # Dependency health check + structured checks
├── install/                     # Standalone setup wizard (works without trcc installed)
│   ├── __init__.py
│   └── gui.py                   # PySide6 setup wizard GUI
├── services/                    # Core hexagon — pure Python, no framework deps
│   ├── __init__.py              # Re-exports service classes
│   ├── device.py                # DeviceService — detect, select, send_pil, send_rgb565
│   ├── image.py                 # ImageService — thin facade over Renderer
│   ├── display.py               # DisplayService — high-level display orchestration
│   ├── led.py                   # LEDService — LED RGB control via LedProtocol
│   ├── led_config.py            # LED config persistence (Memento pattern)
│   ├── led_effects.py           # LEDEffectEngine — strategy pattern for LED effects
│   ├── media.py                 # MediaService — GIF/video frame extraction
│   ├── overlay.py               # OverlayService — overlay rendering
│   ├── renderer.py              # Renderer ABC — Strategy port for compositing backends
│   ├── system.py                # SystemService — system sensor access and monitoring
│   ├── theme.py                 # ThemeService — theme orchestration
│   ├── theme_loader.py          # Theme loading logic
│   ├── theme_persistence.py     # Theme save/export/import
│   └── video_cache.py           # Video frame caching
├── core/
│   ├── models.py                # Domain constants, dataclasses, enums, resolution pipeline
│   ├── ports.py                 # Device ABC (4 methods), Renderer ABC
│   ├── lcd_device.py            # LCDDevice(Device) — direct methods, delegates to services
│   ├── led_device.py            # LEDDevice(Device) — set_color, set_mode, tick, zone/segment ops
│   ├── builder.py               # ControllerBuilder — fluent builder, full DI wiring
│   └── encoding.py              # Encoding utilities
└── qt_components/               # PySide6 GUI adapter
    ├── trcc_app.py              # TRCCApp — thin QMainWindow shell (C# Form1 equivalent)
    ├── lcd_handler.py           # LCDHandler — one per LCD device (C# FormCZTV equivalent)
    ├── base.py                  # BasePanel, BaseThemeBrowser, pil_to_pixmap
    ├── constants.py             # Layout coords, sizes, colors, styles
    ├── assets.py                # Asset loader with lru_cache
    ├── metrics_mediator.py      # MetricsMediator — sensor data routing
    ├── eyedropper.py            # Fullscreen color picker
    ├── screen_capture.py        # X11/Wayland screen grab
    ├── pipewire_capture.py      # PipeWire/Portal Wayland capture
    ├── uc_device.py             # Device sidebar
    ├── uc_preview.py            # Live preview frame
    ├── uc_theme_local.py        # Local theme browser
    ├── uc_theme_web.py          # Cloud theme browser
    ├── uc_theme_mask.py         # Mask browser
    ├── uc_theme_setting.py      # Overlay editor / display mode panels
    ├── uc_image_cut.py          # Image cropper
    ├── uc_video_cut.py          # Video trimmer
    ├── uc_system_info.py        # Sensor dashboard
    ├── uc_sensor_picker.py      # Sensor selection dialog
    ├── uc_info_module.py        # Live system info display
    ├── uc_led_control.py        # LED RGB control panel (LED styles 1-12)
    ├── uc_screen_led.py         # LED segment visualization (colored circles)
    ├── uc_color_wheel.py        # HSV color wheel for LED hue selection
    ├── uc_activity_sidebar.py   # Sensor element picker
    └── uc_about.py              # Settings / about panel
```

## Design Patterns

### Hexagonal / Device ABCs

`LCDDevice` and `LEDDevice` in `core/` are the single entry point for all adapters. `LCDDevice` has direct methods (capabilities inlined in v8.0.0) that delegate to services. `LEDDevice` has direct methods. CLI, GUI, and API all import from `core/` — never adapter→adapter. Law of Demeter: Adapter→Device→Services only.

### Strict Dependency Injection (v8.1.0)

All service constructors are strict — `RuntimeError` if required adapter dependencies are not provided. Services never import from adapters. Adapter wiring happens exclusively in **composition roots**:

- **`core/builder.py`** — `ControllerBuilder.build_lcd()` / `build_led()` — full DI for GUI path
- **`core/lcd_device.py:_build_services()`** — called from `connect()`, mirrors builder wiring for CLI/API
- **`cli/` functions** — each CLI command imports and injects concrete adapters
- **`api/__init__.py`** — module-level adapter wiring for REST API

One accepted exception: `SystemService._get_instance()` acts as a mini composition root for the convenience singleton (used by GUI widgets via `get_all_metrics()`).

### Metrics Observer

`UCLedControl.update_metrics(metrics)` is the single entry point for hardware metrics. The panel dispatches internally based on `style_id`:

- Styles 1-3, 5-8, 11-12: `update_sensor_metrics()` (CPU/GPU temp, load, fan)
- Style 4: `update_memory_metrics()` (RAM/VRAM usage)
- Style 10: `update_lf11_disk_metrics()` (disk usage, SMART)
- Style 9: `_update_clock()` (LC2 date/time — reads own timer state, no external args)

Callers (`lcd_handler._poll_sensors()`, test harnesses) just pass metrics — zero routing knowledge needed. This is the Observer pattern: provider emits, subscriber dispatches.

### Per-Device Configuration

Each connected LCD is identified by `"{index}:{vid:04x}_{pid:04x}"` (e.g. `"0:87cd_70db"`). Settings are stored in `~/.trcc/config.json` under a `"devices"` key. Each device independently persists:

- **Theme** — last selected local/cloud theme path
- **Brightness** — 3-level brightness (25%, 50%, 100%)
- **Rotation** — 0°/90°/180°/270°
- **Carousel** — enabled, interval, and theme list
- **Overlay** — element config and enabled state

### Asset System

726 GUI assets extracted from the Windows application, applied via QPalette (not stylesheets) to match the original dark theme exactly.

### Cross-Distro Compatibility

Platform-specific helpers are centralized in `adapters/infra/`:

- **`doctor.py`** — dependency health check with structured results, distro-to-PM mapping (25+ distros), PM native "provides" search fallback
- **`data_repository.py`** — XDG paths, on-demand download, theme/web archive management
- **`font_resolver.py`** — 20+ font directories covering Fedora, Debian/Ubuntu, Arch, Void, Alpine, openSUSE, NixOS, Guix, and more

### Device Protocol Routing

The `DeviceProtocolFactory` in `abstract_factory.py` routes devices to the correct protocol via self-registering `@register()` decorators (OCP):

- **SCSI devices** → `ScsiProtocol` (sg_raw) — LCD displays
- **HID LCD devices** → `HidProtocol` (PyUSB/HIDAPI) — LCD displays via HID
- **Bulk USB devices** → `BulkProtocol` (PyUSB) — LCD displays via raw USB bulk
- **LY Bulk devices** → `LyProtocol` (PyUSB) — LCD displays via chunked bulk (0416:5408/5409)
- **HID LED devices** → `LedProtocol` (PyUSB/HIDAPI) — RGB LED controllers

The GUI auto-routes LED devices to `UCLedControl` (LED panel) instead of the LCD form. `LEDDevice` manages LED effects with a 150ms animation timer, matching Windows FormLED. The unified LED panel handles all device styles (1-12).

### Rendering Pipeline

`QtRenderer` (QImage/QPainter) is the primary renderer — compositing, text, rotation, brightness, RGB565/JPEG encoding, font resolution. Zero PIL in the hot path. `PilRenderer` is a fallback. `ImageService` is a thin facade delegating to the active renderer.

### Shared UI Base Classes

`base.py` provides `BaseThemeBrowser` — the common superclass for local, cloud, and mask theme browsers. It handles grid layout, thumbnail creation, selection state (`_select_item()`), filter buttons, and scrolling. Subclasses override `_on_item_clicked()` for download-vs-select behavior while reusing the visual selection logic.

`UCLedControl` uses a `_create_info_panel()` factory for building labeled metric displays (memory, disk), and module-level stylesheet constants (`_STYLE_INFO_BG`, `_STYLE_INFO_NAME`, etc.) shared across all info panels and buttons.

### Theme Archives

Starter themes and mask overlays ship as `.7z` archives, extracted on first use to `~/.trcc/data/`. This keeps the git repo and package size small.
