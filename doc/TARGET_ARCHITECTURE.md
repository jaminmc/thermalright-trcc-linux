# Architecture Decision — CommandBus Removal (Completed v9.3.0)

## Context

The CommandBus layer (62 command dataclasses, 4 handlers, ~1,800 lines) sat between good adapters and good core logic, adding indirection without value. 80% of handler case arms were pure passthrough: `case SetBrightnessCommand(level=level): return self._lcd.set_brightness(level)`.

The hexagonal architecture was correct. The SOLID principles were correct. The CommandBus was not part of either — it was ceremony that grew between the layers. Removing it made the architecture *more* hexagonal, not less.

## Result — Hexagonal Layers

```
┌─────────────────────────────────────────────────┐
│  Adapters (thin — parse input, format output)   │
│                                                 │
│  CLI:  trcc theme-load Theme1                   │
│  API:  POST /display/theme {name: "Theme1"}     │
│  GUI:  click theme in browser panel             │
└───────────────────┬─────────────────────────────┘
                    │ direct method calls (no bus)
┌───────────────────▼─────────────────────────────┐
│  Core — Device Facades (LCDDevice, LEDDevice)   │
│                                                 │
│  ~22 operations total (methods on device)       │
│  Each takes args, returns result dict           │
│  Owns connection lifecycle + state              │
│  Type gates available operations                │
└───────────────────┬─────────────────────────────┘
                    │ injected services (DIP)
┌───────────────────▼─────────────────────────────┐
│  Services (pure business logic, no framework)   │
│                                                 │
│  DisplayService, OverlayService, LEDService     │
│  ImageService (delegates to Renderer)           │
│  SystemService (sensor polling)                 │
└───────────────────┬─────────────────────────────┘
                    │ injected transports (DIP)
┌───────────────────▼─────────────────────────────┐
│  Transport (raw device I/O)                     │
│                                                 │
│  SCSI, HID, Bulk, LED — unchanged              │
│  Platform adapters — unchanged                  │
└─────────────────────────────────────────────────┘
```

Dependencies point inward only. Adapters → Core → Services → Transport.

## SOLID (How It Applies)

- **SRP**: Adapters parse/format. Devices orchestrate. Services compute. Transport sends bytes.
- **OCP**: `@DeviceProtocolFactory.register()` for new devices. New device = new data, not modified logic.
- **LSP**: LCD and LED are separate types — no fake `send_image()` on LED devices.
- **ISP**: `LCDDevice` and `LEDDevice` expose only their own operations.
- **DIP**: Services and transports injected via constructors. Core never imports adapters.

None of this requires a CommandBus. It requires clean interfaces and dependency injection.

## The Device — Universal Entry Point

One device list, indexed. Handshake determines type. Index is the universal selector.

```
[0] Frozen Warframe Pro  (LCD, 320x320, /dev/sg2)
[1] AX120 R3             (LED, 6 zones, /dev/hidraw3)
```

### Adapter Mapping

| Operation | CLI | API | GUI |
|-----------|-----|-----|-----|
| Discover all | `trcc detect` | `GET /devices` | Auto on startup |
| Load theme | `trcc theme-load Theme1` | `POST /display/theme` | Click theme |
| Brightness | `trcc brightness 75` | `POST /display/brightness` | Slider widget |
| LED mode | `trcc led-mode rainbow` | `POST /led/mode` | Mode picker |

## Operations (Validated Against C# Source)

The Windows app has ~22 distinct operations. That's what the hardware supports.

### LCD (~12 operations)
| Operation | Args | Device method |
|-----------|------|---------------|
| `brightness` | `0-100` | `lcd.set_brightness(level)` |
| `image` | `path or url` | `lcd.send_image(path)` |
| `color` | `hex or r,g,b` | `lcd.send_color(r, g, b)` |
| `rotation` | `0, 90, 180, 270` | `lcd.set_rotation(degrees)` |
| `theme` | `name` | `lcd.load_theme(name)` |
| `overlay` | `on/off` | `lcd.set_overlay(enabled)` |
| `video` | `path` | `lcd.play_video(path)` |
| `screencast` | `region` | `lcd.start_screencast(...)` |
| `gif` | `path` | `lcd.send_gif(path)` |
| `text` | `string` | `lcd.send_text(text)` |
| `export` | `path` | `lcd.export_theme(path)` |
| `import` | `path` | `lcd.import_theme(path)` |

### LED (~6 operations)
| Operation | Args | Device method |
|-----------|------|---------------|
| `brightness` | `0-100` | `led.set_brightness(level)` |
| `color` | `hex or r,g,b` | `led.set_color(r, g, b)` |
| `mode` | `name` | `led.set_mode(mode)` |
| `speed` | `1-5` | `led.set_speed(speed)` |
| `zone` | `index color` | `led.set_zone(idx, r, g, b)` |
| `toggle` | — | `led.toggle()` |

### Shared (~4 operations)
| Operation | Args | Device method |
|-----------|------|---------------|
| `info` | — | `device.info()` |
| `disconnect` | — | `device.disconnect()` |
| `temp-unit` | `c/f` | via `settings.set_temp_unit()` |
| `language` | `code` | via `settings.set_lang()` |

## What Was Changed (v9.3.0)

### Removed (~1,800 lines)
- `core/command_bus.py` — bus + middleware infrastructure
- `core/commands/` — 62 command dataclasses (replaced by ~22 device methods that already existed)
- `core/handlers/` — 4 handlers with match statements (pure passthrough, no logic)

### Simplified (~122 dispatch sites rewired)
- CLI: `bus.dispatch(SetBrightnessCommand(level=75))` → `lcd.set_brightness(75)`
- API: `bus.dispatch(SetBrightnessCommand(level=75))` → `lcd.set_brightness(75)`
- GUI: `self._bus.dispatch(SetBrightnessCommand(level=75))` → `self._lcd.set_brightness(75)`
- LED rate limiting: moved from `RateLimitMiddleware` to timer in `led_handler.py`
- Logging: `log.debug()` at adapter boundary or in device methods (where it belongs)

### Kept (unchanged)
- `core/models.py` — domain data, single source of truth
- `core/lcd_device.py`, `core/led_device.py` — device facades (these ARE the operations)
- `services/` — business logic (display, overlay, LED, system)
- `adapters/device/` — transport layer (SCSI, HID, Bulk, LED protocols)
- `adapters/system/` — platform adapters (Linux, Windows, macOS, BSD)
- `conf.py` — settings singleton
- `gui/` widgets — rewired from `bus.dispatch()` to `device.method()`

## GUI Specifics

- `trcc gui` discovers + handshakes all devices at startup
- Device buttons appear based on what was found (or saved in config)
- Clicking a device button opens LCD panel or LED panel based on device type
- Panel widgets call device methods directly — no bus dispatch
- LED rate limiting is a local concern in `led_handler.py` (throttle slider signals with a timer)
- Multiple devices: each has its own connection, panels switch between them
