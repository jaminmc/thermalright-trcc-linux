# Architecture

## Hexagonal (Ports & Adapters)

The project follows hexagonal architecture. The **services layer** is the core hexagon containing all business logic (pure Python, no framework deps). Four driving adapters consume the services:

- **CLI** (`cli/` package) — Typer, 39 commands across 6 submodules. `LEDDispatcher` + `DisplayDispatcher` classes are the single authority for programmatic LED/LCD operations — return result dicts, never print. CLI functions are thin presentation wrappers. GUI and API can import dispatchers directly.
- **GUI** (`qt_components/`) — PySide6, controllers in `core/` call services
- **API** (`api.py`) — FastAPI REST adapter (optional `[api]` extra)
- **Setup GUI** (`install/gui.py`) — Standalone PySide6 setup wizard

## Project Layout

```
src/trcc/
├── cli/                         # Typer CLI adapter package (6 submodules)
├── api.py                       # FastAPI REST adapter (optional [api] extra)
├── conf.py                      # Settings singleton + persistence helpers
├── __version__.py               # Version info
├── adapters/
│   ├── device/                  # USB device protocol handlers
│   │   ├── scsi.py              # SCSI protocol (sg_raw)
│   │   ├── hid.py               # HID USB transport (PyUSB)
│   │   ├── led.py               # LED RGB protocol (effects, HID sender)
│   │   ├── led_effect.py        # LEDEffectEngine — strategy pattern for LED effects
│   │   ├── led_kvm.py           # KVM LED backend
│   │   ├── led_segment.py       # Segment display renderer (11 styles)
│   │   ├── bulk.py              # Raw USB bulk protocol
│   │   ├── lcd.py               # SCSI RGB565 frame send
│   │   ├── detector.py          # USB device scan + registries
│   │   └── factory.py           # Protocol factory (SCSI/HID/LED/Bulk routing)
│   ├── render/                  # Rendering backends (Strategy pattern)
│   │   └── pil.py               # PilRenderer — CPU-only PIL/Pillow backend
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
│   ├── __init__.py              # Re-exports all 8 service classes
│   ├── device.py                # DeviceService — detect, select, send_pil, send_rgb565
│   ├── image.py                 # ImageService — solid_color, resize, brightness, rotation
│   ├── display.py               # DisplayService — high-level display orchestration
│   ├── led.py                   # LEDService — LED RGB control via LedProtocol
│   ├── media.py                 # MediaService — GIF/video frame extraction
│   ├── overlay.py               # OverlayService — overlay rendering
│   ├── renderer.py              # Renderer ABC — Strategy port for compositing backends
│   ├── system.py                # SystemService — system sensor access and monitoring
│   └── theme.py                 # ThemeService — theme loading/saving/export/import
├── core/
│   ├── models.py                # Domain constants, dataclasses, enums, resolution pipeline
│   └── controllers.py           # LCDDeviceController (Facade), LEDDeviceController (Facade)
└── qt_components/               # PySide6 GUI adapter
    ├── qt_app_mvc.py            # Main window (1454x800)
    ├── base.py                  # BasePanel, BaseThemeBrowser, pil_to_pixmap
    ├── constants.py             # Layout coords, sizes, colors, styles
    ├── assets.py                # Asset loader with lru_cache
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
    ├── uc_seven_segment.py      # 7-segment display preview
    ├── uc_activity_sidebar.py   # Sensor element picker
    └── uc_about.py              # Settings / about panel
```

## Design Patterns

### Hexagonal / MVC

Controllers in `core/` are Facades — `LCDDeviceController` orchestrates 4 services (theme, device, overlay, media), `LEDDeviceController` wraps `LEDService`. Views subscribe via callbacks. All business logic lives in `services/`, making it possible to swap frontends (CLI, GUI, API all use the same services). Law of Demeter: GUI→Facade→Services only.

### Metrics Observer

`UCLedControl.update_metrics(metrics)` is the single entry point for hardware metrics. The panel dispatches internally based on `style_id`:

- Styles 1-3, 5-8, 11-12: `update_sensor_metrics()` (CPU/GPU temp, load, fan)
- Style 4: `update_memory_metrics()` (RAM/VRAM usage)
- Style 10: `update_lf11_disk_metrics()` (disk usage, SMART)
- Style 9: `_update_clock()` (LC2 date/time — reads own timer state, no external args)

Callers (`qt_app_mvc._poll_sensors()`, test harnesses) just pass metrics — zero routing knowledge needed. This is the Observer pattern: provider emits, subscriber dispatches.

### Per-Device Configuration

Each connected LCD is identified by `"{index}:{vid:04x}_{pid:04x}"` (e.g. `"0:87cd_70db"`). Settings are stored in `~/.config/trcc/config.json` under a `"devices"` key. Each device independently persists:

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

The `DeviceProtocolFactory` in `device_factory.py` routes devices to the correct protocol based on PID and implementation type:

- **SCSI devices** → `ScsiProtocol` (sg_raw) — LCD displays
- **HID LCD devices** → `HidProtocol` (PyUSB/HIDAPI) — LCD displays via HID
- **Bulk USB devices** → `BulkProtocol` (PyUSB) — LCD displays via raw USB bulk
- **HID LED devices** → `LedProtocol` (PyUSB/HIDAPI) — RGB LED controllers

The GUI auto-routes LED devices to `UCLedControl` (LED panel) instead of the LCD form. `LEDDeviceController` manages LED effects with a 150ms animation timer, matching Windows FormLED. The unified LED panel handles all device styles (1-12).

### CLI Dispatchers

`LEDDispatcher` and `DisplayDispatcher` in `cli/` are the programmatic API for LED and LCD operations. They return structured result dicts (`{"success": bool, "message": str, ...}`) and never print — callers decide how to present results. CLI functions are thin wrappers that print + exit. GUI and API can import dispatchers directly for the same operations without parsing CLI output.

### Shared UI Base Classes

`base.py` provides `BaseThemeBrowser` — the common superclass for local, cloud, and mask theme browsers. It handles grid layout, thumbnail creation, selection state (`_select_item()`), filter buttons, and scrolling. Subclasses override `_on_item_clicked()` for download-vs-select behavior while reusing the visual selection logic.

`UCLedControl` uses a `_create_info_panel()` factory for building labeled metric displays (memory, disk), and module-level stylesheet constants (`_STYLE_INFO_BG`, `_STYLE_INFO_NAME`, etc.) shared across all info panels and buttons.

### Theme Archives

Starter themes and mask overlays ship as `.7z` archives, extracted on first use to `~/.trcc/data/`. This keeps the git repo and package size small.
