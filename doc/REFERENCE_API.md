# API Reference

TRCC Linux includes a REST API for headless and remote control of LCD and LED devices. Start the server with:

```bash
trcc serve                          # localhost:9876
trcc serve --port 8080              # custom port
trcc serve --token mysecret         # require X-API-Token header
trcc serve --tls                    # HTTPS with auto-generated self-signed cert
trcc serve --host 0.0.0.0           # listen on all interfaces (use with --token)
```

Interactive docs available at `http://localhost:9876/docs` (Swagger UI) when the server is running.

When the `qrcode` package is installed (`pip install qrcode`), startup prints a terminal QR code containing `{"host","port","token","tls"}` as compact JSON — scan with TRCC Remote to connect instantly.

---

## Table of Contents

1. [Authentication](#authentication)
2. [Health](#health)
3. [Pairing](#post-pair)
4. [Devices](#devices)
5. [Display (LCD)](#display-lcd)
6. [Video Playback](#video-playback)
7. [Preview / Live Stream](#preview--live-stream)
8. [Themes](#themes)
9. [LED](#led)
10. [System Metrics](#system-metrics)
11. [i18n (Internationalization)](#i18n-internationalization)
12. [Request/Response Models](#requestresponse-models)

---

## Authentication

When started with `--token`, all endpoints except `/health` require the `X-API-Token` header:

```bash
curl -H "X-API-Token: mysecret" http://localhost:9876/devices
```

WebSocket connections use a query parameter instead:

```
ws://localhost:9876/display/preview/stream?token=mysecret
```

---

## Health

### `GET /health`

Health check. Always accessible, no auth required.

**Response:**
```json
{"status": "ok", "version": "9.0.3"}
```

---

### `POST /pair`

Pair a remote client (e.g. TRCC Remote app). Returns connection info and device status.

**Response:**
```json
{"paired": true, "version": "9.0.3"}
```

---

## Devices

### `GET /devices`

List currently known devices.

**Response:** `DeviceResponse[]`
```json
[
  {
    "id": 0,
    "name": "FROZEN VISION V2",
    "vid": 34765,
    "pid": 28891,
    "protocol": "scsi",
    "resolution": [320, 320],
    "path": "/dev/sg2"
  }
]
```

### `POST /devices/detect`

Rescan USB for LCD/LED devices. Returns updated device list.

**Response:** `DeviceResponse[]`

### `GET /devices/{device_id}`

Get details for a specific device by index.

**Response:** `DeviceResponse`

**Errors:** `404` if device index out of range.

### `POST /devices/{device_id}/select`

Select a device for control. Initializes LCD or LED dispatcher, mounts static file directories, and restores last theme if available.

If the GUI daemon is running, the API routes commands through IPC automatically.

**Response:**
```json
{"selected": "FROZEN VISION V2", "resolution": [320, 320]}
```

### `POST /devices/{device_id}/send`

Upload and send an image directly to the device LCD.

**Content-Type:** `multipart/form-data`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `image` | file | required | Image file (PNG, JPEG, etc.) |
| `rotation` | int | 0 | Rotation in degrees (0, 90, 180, 270) |
| `brightness` | int | 100 | Brightness percentage (0-100) |

**Limits:** 10 MB max upload size. PIL format validation on upload.

**Response:**
```json
{"sent": true, "resolution": [320, 320]}
```

**Errors:** `400` invalid image, `404` device not found, `413` too large, `503` can't discover resolution.

---

## Display (LCD)

All display endpoints require a device to be selected first (`POST /devices/{id}/select`). Returns `409` if no LCD device is active.

### `POST /display/color`

Send a solid color to the LCD.

**Body:**
```json
{"hex": "ff0000"}
```

### `POST /display/brightness`

Set display brightness. Persists to config.

**Body:**
```json
{"level": 3}
```

| Level | Brightness |
|-------|-----------|
| 1 | 25% |
| 2 | 50% |
| 3 | 100% |

### `POST /display/rotation`

Set display rotation. Persists to config.

**Body:**
```json
{"degrees": 90}
```

Values: `0`, `90`, `180`, `270`.

### `POST /display/split`

Set split mode (Dynamic Island). Persists to config.

**Body:**
```json
{"mode": 0}
```

Values: `0` (off), `1`-`3` (Dynamic Island variants).

### `POST /display/test`

Run a color cycle test on the connected LCD. Cycles through 7 colors (red, green, blue, yellow, magenta, cyan, white) with 1-second pauses. Stops any running video/overlay first.

**Response:**
```json
{"success": true, "message": "Test complete — cycled 7 colors on 320x320"}
```

### `POST /display/reset`

Reset device by sending a solid red frame. Useful for clearing stuck display state.

### `POST /display/mask`

Upload and apply a mask overlay (PNG with transparency).

**Content-Type:** `multipart/form-data`

| Parameter | Type | Description |
|-----------|------|-------------|
| `image` | file | PNG mask image (max 10 MB) |

### `POST /display/overlay`

Render an overlay from a DC config file path.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `dc_path` | string | required | Path to config1.dc file |
| `send` | bool | true | Send rendered frame to device |

### `GET /display/status`

Get current display state.

**Response:**
```json
{
  "connected": true,
  "resolution": [320, 320],
  "device_path": "/dev/sg2"
}
```

---

## Video Playback

Video playback runs in a background thread, pumping decoded frames to the LCD and updating the preview stream.

### `POST /display/video/stop`

Stop background video playback.

### `POST /display/video/pause`

Toggle pause on video playback. Returns `409` if no video is playing.

**Response:**
```json
{"success": true, "paused": true}
```

### `GET /display/video/status`

Get current video playback state.

**Response:**
```json
{
  "playing": true,
  "paused": false,
  "progress": 0.45,
  "current_time": "0:13",
  "total_time": "0:30",
  "fps": 30.0,
  "source": "/path/to/video.mp4",
  "loop": true
}
```

---

## Preview / Live Stream

### `GET /display/preview`

Return the current LCD frame as a PNG image. Useful for single-shot screenshots.

**Response:** `image/png` binary

**Errors:** `503` if no image available.

### `WS /display/preview/stream`

WebSocket live JPEG stream of the LCD. Frames are sent as binary messages at a configurable framerate.

When the GUI daemon is running, frames come via IPC. In standalone mode, frames come from the `on_frame_sent` capture.

**Auth:** `?token=` query parameter (if token auth is configured).

**Client control messages (JSON text frames):**

| Message | Default | Range | Description |
|---------|---------|-------|-------------|
| `{"fps": N}` | 10 | 1-30 | Target framerate |
| `{"quality": N}` | 85 | 10-100 | JPEG quality |
| `{"pause": bool}` | false | — | Pause/resume stream |

**Example (JavaScript):**
```javascript
const ws = new WebSocket('ws://localhost:9876/display/preview/stream');
ws.binaryType = 'arraybuffer';
ws.onmessage = (e) => {
  const blob = new Blob([e.data], {type: 'image/jpeg'});
  document.getElementById('preview').src = URL.createObjectURL(blob);
};
// Adjust quality
ws.send(JSON.stringify({quality: 70, fps: 15}));
```

---

## Themes

### `POST /themes/init`

Initialize the theme system for a given resolution. Downloads theme/mask/web archives if not cached locally.

**Body:**
```json
{"resolution": "320x320"}
```

**Response:**
```json
{"initialized": true, "resolution": "320x320"}
```

### `GET /themes`

List available local themes for a given resolution.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `resolution` | string | "320x320" | Resolution filter (e.g. "480x480") |

**Response:** `ThemeResponse[]`
```json
[
  {
    "name": "CyberPunk",
    "category": "Tech",
    "is_animated": false,
    "has_config": true,
    "preview_url": "/static/themes/CyberPunk/Theme.png"
  }
]
```

### `POST /themes/load`

Load a theme by name and send to device. Handles static images, animated themes (video/Theme.zt), and overlay configs (config1.dc) automatically.

**Body:**
```json
{"name": "CyberPunk", "resolution": "320x320"}
```

`resolution` is optional — defaults to the connected device's resolution.

### `POST /themes/save`

Save current device display as a named theme.

**Body:**
```json
{"name": "MyTheme"}
```

### `POST /themes/import`

Import a `.tr` theme archive. Max 50 MB.

**Content-Type:** `multipart/form-data`

| Parameter | Type | Description |
|-----------|------|-------------|
| `file` | file | `.tr` theme archive |

### `POST /themes/export`

Export a theme as a downloadable `.tr` archive.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `theme_name` | string | required | Theme name (exact or partial match) |
| `resolution` | string | "320x320" | Resolution filter |

**Response:** Binary `.tr` file download (`application/octet-stream`).

**Errors:** `400` invalid name, `404` theme not found.

### `GET /themes/web`

List available cloud theme previews for a given resolution.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `resolution` | string | "320x320" | Resolution filter |

**Response:** `WebThemeResponse[]`
```json
[
  {
    "id": "a001",
    "category": "a",
    "preview_url": "/static/web/a001.png",
    "has_video": true,
    "download_url": "/themes/web/a001/download"
  }
]
```

### `POST /themes/web/{theme_id}/download`

Download a cloud theme to local cache. Optionally starts video playback on the device.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `resolution` | string | device res | Target resolution |
| `send` | bool | false | Start playback after download |

**Response:**
```json
{
  "id": "a001",
  "cached_path": "/home/user/.trcc/data/web/320320/a001.mp4",
  "resolution": "320x320",
  "already_cached": false
}
```

### `GET /themes/masks`

List available mask overlays for a given resolution.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `resolution` | string | "320x320" | Resolution filter |

**Response:** `MaskResponse[]`
```json
[
  {"name": "mask01", "preview_url": "/static/masks/mask01/Theme.png"}
]
```

---

## LED

All LED endpoints require an LED device to be selected first. Returns `409` if no LED device is active.

### Global Operations

#### `POST /led/color`

Set LED static color.

**Body:**
```json
{"hex": "00ff88"}
```

#### `POST /led/mode`

Set LED effect mode.

**Body:**
```json
{"mode": "breathing"}
```

Values: `static`, `breathing`, `colorful`, `rainbow` (device-dependent).

#### `POST /led/brightness`

Set LED brightness (0-100).

**Body:**
```json
{"level": 80}
```

#### `POST /led/off`

Turn all LEDs off.

#### `POST /led/sensor`

Set CPU/GPU sensor source for temperature/load-linked modes.

**Body:**
```json
{"source": "cpu"}
```

### Zone Operations

#### `POST /led/zones/{zone}/color`

Set color for a specific LED zone.

**Body:** `{"hex": "ff0000"}`

#### `POST /led/zones/{zone}/mode`

Set effect mode for a specific zone.

**Body:** `{"mode": "breathing"}`

#### `POST /led/zones/{zone}/brightness`

Set brightness for a specific zone (0-100).

**Body:** `{"level": 50}`

#### `POST /led/zones/{zone}/toggle`

Toggle a specific LED zone on/off.

**Body:** `{"on": true}`

#### `POST /led/sync`

Enable/disable zone sync (circulate mode).

**Body:**
```json
{"enabled": true, "interval": 500}
```

`interval` is optional (milliseconds between zone rotations).

### Segment Operations

#### `POST /led/segments/{index}/toggle`

Toggle a specific LED segment on/off.

**Body:** `{"on": true}`

#### `POST /led/clock`

Set segment display clock format.

**Body:** `{"is_24h": true}`

#### `POST /led/temp-unit`

Set segment display temperature unit.

**Body:** `{"unit": "C"}`

Values: `C` (Celsius), `F` (Fahrenheit).

### Test

#### `POST /led/test`

Run LED preview with real system metrics. No device needed — useful for testing without hardware.

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `mode` | string | "static" | LED mode: static, breathing, colorful, rainbow |
| `segments` | int | 64 | Number of LED segments to simulate |

**Response:**
```json
{
  "success": true,
  "mode": "static",
  "segments": 10,
  "colors": [
    {"r": 255, "g": 0, "b": 0},
    {"r": 255, "g": 0, "b": 0}
  ]
}
```

### Status

#### `GET /led/status`

Get current LED state.

**Response:**
```json
{"connected": true, "status": "..."}
```

---

## System Metrics

### `GET /system/metrics`

All system metrics as JSON — CPU, GPU, memory, disk, network, fans.

**Response:** Flat dict with prefixed keys:
```json
{
  "cpu_temp": 52,
  "cpu_usage": 12,
  "cpu_freq": 4200,
  "gpu_temp": 45,
  "gpu_usage": 8,
  "mem_used": 8192,
  "mem_total": 32768,
  "disk_read": 15,
  "disk_write": 3,
  "net_up": 120,
  "net_down": 450,
  "fan_speed": 850
}
```

### `GET /system/metrics/{category}`

Filtered metrics by category.

| Category | Aliases | Prefix |
|----------|---------|--------|
| `cpu` | — | `cpu_` |
| `gpu` | — | `gpu_` |
| `mem` | `memory` | `mem_` |
| `disk` | — | `disk_` |
| `net` | `network` | `net_` |
| `fan` | — | `fan_` |

### `GET /system/report`

Generate diagnostic report (same as `trcc report` CLI command).

**Response:**
```json
{"report": "TRCC Linux v9.0.3\n..."}
```

### `GET /system/perf`

Run software performance benchmarks (rendering, encoding, compositing).

**Response:**
```json
{
  "benchmarks": [
    {"name": "encode_rgb565_320x320", "mean_ms": 0.8, "iterations": 100}
  ]
}
```

### `GET /system/perf/device`

Run hardware USB I/O benchmarks. Requires a connected LCD device. Pauses any running GUI daemon for exclusive access.

**Response:**
```json
{
  "benchmarks": [
    {"name": "send_frame_320x320", "mean_ms": 42.1, "iterations": 50}
  ]
}
```

---

## i18n (Internationalization)

### `GET /i18n/languages`

List all available languages with ISO codes and native names.

**Response:**
```json
[
  {"code": "en", "name": "English"},
  {"code": "de", "name": "Deutsch"},
  {"code": "ja", "name": "日本語"}
]
```

### `GET /i18n/language`

Get the current application language.

**Response:**
```json
{"code": "en", "name": "English"}
```

### `PUT /i18n/language/{code}`

Set the application language by ISO 639-1 code. Persists to config.

**Response:**
```json
{"code": "de", "name": "Deutsch"}
```

**Errors:** `400` if language code is not supported.

---

## Request/Response Models

All request bodies are JSON. All responses are JSON unless noted (preview endpoints return binary).

### Common Error Responses

| Status | Meaning |
|--------|---------|
| 400 | Invalid request (bad hex color, unknown category, corrupt image) |
| 401 | Invalid or missing API token |
| 404 | Device or theme not found |
| 409 | No device selected — call `POST /devices/{id}/select` first |
| 413 | Upload exceeds size limit |
| 500 | Device send failed |
| 503 | Device resolution unknown, or no frame available for preview |

### Static File Mounts

After device selection, theme and cloud directories are mounted as static files:

| Mount | Directory | Content |
|-------|-----------|---------|
| `/static/themes/` | Local theme packs | Theme images, videos, configs |
| `/static/web/` | Cloud theme previews | PNG previews, MP4 videos |
| `/static/masks/` | Cloud mask overlays | Mask PNGs, overlay configs |

These mounts are resolution-specific and update when a different device is selected.

---

## Daemon Mode vs Standalone

The API detects whether the GUI daemon is running:

- **Daemon mode:** Commands route through IPC (Unix socket) to the GUI. Preview stream fetches frames from the daemon. Both GUI and API control the same device simultaneously.
- **Standalone mode:** API manages the device directly. No GUI required. Preview stream uses the `on_frame_sent` callback to capture outgoing frames.

The mode is selected automatically — no configuration needed.

---

## Examples

### Send an image via curl

```bash
curl -X POST http://localhost:9876/devices/detect
curl -X POST http://localhost:9876/devices/0/select
curl -X POST -F "image=@photo.png" http://localhost:9876/devices/0/send
```

### Load a theme

```bash
curl -X POST http://localhost:9876/themes/load \
  -H "Content-Type: application/json" \
  -d '{"name": "CyberPunk"}'
```

### Set LED color

```bash
curl -X POST http://localhost:9876/led/color \
  -H "Content-Type: application/json" \
  -d '{"hex": "ff6600"}'
```

### Monitor system metrics

```bash
# All metrics
curl http://localhost:9876/system/metrics

# CPU only
curl http://localhost:9876/system/metrics/cpu

# Watch metrics (updates every 2s)
watch -n 2 'curl -s http://localhost:9876/system/metrics/cpu | python3 -m json.tool'
```

### Live preview in browser

```html
<img id="preview" />
<script>
  const ws = new WebSocket('ws://localhost:9876/display/preview/stream');
  ws.binaryType = 'arraybuffer';
  ws.onmessage = (e) => {
    const blob = new Blob([e.data], {type: 'image/jpeg'});
    document.getElementById('preview').src = URL.createObjectURL(blob);
  };
</script>
```
