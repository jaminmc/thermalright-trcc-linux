# TRCC Linux — Gap Analysis vs Windows C# Implementation

> Generated 2026-02-16 from audit docs cross-referenced against Python codebase.
> Sorted by severity: HIGH = wrong data to device, MEDIUM = missing user feature, LOW = cosmetic/preview

---

## HIGH — Wrong Data Sent to Hardware

### H1. Missing wire remap tables for LED styles 6-12
**Source**: FormLED audit, SendHidVal (lines 4309-7618)
**File**: `core/models.py` LED_REMAP_TABLES (line 637)
**Problem**: Only styles 2, 3, 4, 5, 13 have remap tables. Styles 1, 6, 7, 8, 9, 10, 11, 12 use identity mapping. C# has unique remap tables for each style in SendHidVal. Without remapping, RGB data goes to wrong physical LEDs.
**Affected products**: LF12 (style 6), LF10 (style 7), CZ1 (style 8), LC2 (style 9), LF11 (style 10), LF15 (style 11), LF13 (style 12)

### H2. PA120 (style 2) GPU section shifted by 1 digit
**Source**: UCScreenLED audit, default wire field values
**File**: `adapters/device/led_segment.py` PA120Display (line 356)
**Problem**: GPU_TEMP_DIGITS starts at index 52 instead of 45 (shifted by 7 = one digit position). CPU_USE_PARTIAL points to (46, 47) instead of (80, 81). Entire GPU section renders to wrong wire indices.
**Result**: GPU temp/usage lights wrong segments on PA120 hardware.

### H3. LC2 (style 9) date digit positions swapped
**Source**: UCScreenLED audit, SetMyTimer
**File**: `adapters/device/led_segment.py` LC2Display (line 833)
**Problem**: Month tens is partial B/C at indices 52-53, month ones is full digit at 31-37, day tens at 38-44, day ones at 45-51. Our code reverses month tens/ones and shifts the whole date section. For "12/25", C# sends month_tens=1(partial@52-53), month_ones=2(full@31-37), day_tens=2(@38-44), day_ones=5(@45-51). Our code sends month_tens=1(full@31-37), month_ones=2(@38-44), day_tens=2(@45-51), day_ones=5(partial@52-53).

### H4. LC2 (style 9) time colons never lit
**Source**: UCScreenLED audit, isOn9 defaults
**File**: `adapters/device/led_segment.py` LC2Display.compute_mask
**Problem**: Indices 0-2 (time colon dots + date separator) are never set to True. C# defaults isOn9[0]=isOn9[1]=isOn9[2]=true. Physical display shows no colons between HH:MM.

### H5. LF11 (style 10) shows CPU/GPU metrics instead of disk metrics
**Source**: FormLED audit GetVal + UCScreenLED audit SetMyNumeralHardDisk
**File**: `adapters/device/led_segment.py` LF11Display (line 916)
**Problem**: PHASES = (cpu_temp, cpu_percent, gpu_temp, gpu_usage). C# uses disk metrics (SSD temp, fan RPM, disk MHz). Also missing 5-digit mode for RPM/MHz values — only uses 3 digits.

### H6. LC1 (style 4) MHz mode truncated to 3 digits
**Source**: UCScreenLED audit, SetMyNumeral mode 1/2
**File**: `adapters/device/led_segment.py` LC1Display (line 527)
**Problem**: MHz phase uses `_encode_3digit` + `_encode_unit("H")` on digit 4. C# uses all 4 digit positions for a 4-digit MHz value. For 3200 MHz, C# shows "3200", ours shows "320H".

---

## MEDIUM — Missing User-Facing Features

### M1. Zone carousel (LunBo) rotation for LED devices
**Source**: FormLED audit, GetVal/isLunBo
**Problem**: C# buttonLB enables multi-zone rotation with configurable timer. Device cycles through selected zones. Our "Sync All" checkbox just applies same color to all zones — not the same feature. Multi-zone devices (styles 2, 3, 5, 6, 7, 8, 11) cannot rotate between zone data sources.

### M2. LED test mode
**Source**: FormLED audit, checkBox1 (line 1029)
**Problem**: C# sends 252-byte test packet cycling white/red/green/blue at brightness=1 every 10 ticks. No diagnostic mode exists in our code.

### M3. DDR memory multiplier for LC1 (style 4) — DONE
**Source**: FormLED audit, memoryRatio
**Fix**: Added DDR combo box (×1/×2/×4) in LC1 memory panel. Signal → service → state pipeline. Memory clock display shows effective MT/s (clock × ratio). Ratio persisted in LED config.

### M4. Hard disk index selector for LF11 (style 10)
**Source**: FormLED audit, hardDiskCount/ucComboBoxC
**Problem**: C# lets user select which disk to monitor. No disk selector in our UI. Multi-disk systems always monitor first disk.

### M5. LED sub-style handling (nowLedStyleSub) — DONE (already implemented)
**Source**: FormLED audit, nowLedStyleSub
**Analysis**: C# `nowLedStyleSub` is set per product type: 0 for LC1 (style 4), 1 for LF11 (style 10). These are separate styles with separate display classes — not a runtime toggle. Our `LEDState.sub_style` field + `LC1Display.PHASES_MEM`/`PHASES_DISK` already handle this correctly. No code changes needed.

### M6. Per-zone on/off toggle
**Source**: FormLED audit, myOnOff1-4
**Problem**: C# has per-zone on/off via ucColor2Delegate. Our GUI has single global on/off button. LEDZoneState.on field exists in model but no GUI control to set it per-zone.

### M7. Boot animation upload for SCSI devices — NOT IMPLEMENTED (liability)
**Source**: FormCZTV audit, buttonFXTB_Click/GifTo565
**Problem**: C# sends embedded boot animations (per resolution) to device. No boot animation support in our code.
**Decision**: SCSI protocol for compressed multi-frame flash upload is reverse-engineered and documented in `adapters/device/scsi.py` (`_send_boot_animation`), but intentionally NOT exposed in the UI or service layer. Writing incorrect data to device flash could brick the boot animation or the device. C# only sends known-good embedded GIFs at exact matching resolutions — we don't have those resources and won't risk user devices with arbitrary uploads.

### M8. Direct GIF-to-RGB565 multi-frame transfer — NOT IMPLEMENTED (liability)
**Source**: FormCZTV audit, GifTo565
**Problem**: C# sends all GIF frames to SCSI device in one batch with frame delay headers. Our SCSI handler only sends single frames. Animated GIFs can only play via continuous video-mode USB transfers.
**Decision**: Same flash-write protocol as M7. Low-level SCSI plumbing exists in `scsi.py` but not wired up. Animated GIF playback via host-side frame-by-frame transfer (video mode) works correctly today.

### M9. Display split mode (LDD) for widescreen — DONE
**Source**: FormCZTV audit, buttonLDD
**Fix**: Fixed misidentified buttonLDD (was brightness, actually split mode). Added `SPLIT_OVERLAY_MAP` in models.py (12 overlay variants: 3 styles × 4 rotations). DisplayService composites 灵动岛 RGBA overlays onto LCD frame after rotation. buttonLDD is dual-purpose: split mode for 1600x720, brightness for others. Split mode persisted per-device and in Theme.dc. All 12 overlay PNGs (1600×720 RGBA) loaded lazily with cache.

### M10. Drag overlay elements on LCD preview — DONE
**Source**: DCUserControls audit, UCScreenImage.SetTextPos
**Fix**: ImageLabel now tracks mouse drag (press/move/release) with OpenHand/ClosedHand cursors. UCPreview translates widget coords → LCD coords. FormCZTV wires drag signals to move the selected overlay element (delta-based, matching C# SetTextPos). WASD/arrow key nudge (1px normal, 10px Shift) on focused preview. Spinboxes update in sync.

### M11. System info page carousel (M1-M6) — DONE (already implemented)
**Source**: DCUserControls audit, UCXiTongXinXi
**Analysis**: C# UCXiTongXinXi is a **theme carousel** (轮播), not dedicated system info pages. M1-M6 are theme indices in `lunBoArray[0-5]` that auto-cycle on a timer. Each theme has its own overlay config (config1.dc) showing system metrics. Our slideshow feature in UCThemeLocal implements this: enable/disable toggle, configurable timer, up to 6 theme selections, carousel config persisted in Theme.dc. No code changes needed.

### M12. LC2 weekday bar graph — DONE (fixed during H3/H4)
**Source**: UCScreenLED audit, SetMyTimer
**File**: `adapters/device/led_segment.py` LC2Display
**Fix**: Progressive fill implemented: `mask[idx] = (i == 0) or (w > i - 1)`. First bar always on, each subsequent bar based on weekday. Tests: `test_weekday_progressive_fill`, `test_weekday_sunday_all_on`.

---

## LOW — Cosmetic / Defaults / Preview-Only

### L1. Default brightness 100 vs C# 65 — DONE (already fixed)
**File**: `core/models.py` LEDState.brightness
**Fix**: `brightness: int = 65` — already matches C# default.

### L2. Carousel/rotation interval not user-configurable — DONE (already fixed)
**File**: `services/led.py`, `core/models.py`
**Fix**: `LEDState.carousel_interval` configurable field (default 100 ticks). LED service reads `self.state.carousel_interval` for phase tick threshold.

### L3. HDD toggle is cosmetic — DONE (already fixed)
**File**: `qt_components/uc_about.py`, `qt_components/qt_app_mvc.py`, `conf.py`, `services/system.py`
**Fix**: Toggle persisted via `settings.set_hdd_enabled()` → `config.json`. `SystemService.get_all_metrics()` checks `settings.hdd_enabled` and zeroes disk_temp when disabled.

### L4. No suspend/resume handler — DONE (already fixed)
**File**: `qt_components/qt_app_mvc.py` lines 594-624
**Fix**: `_setup_sleep_monitor()` listens for `org.freedesktop.login1.Manager::PrepareForSleep` via DBus. On suspend: stops all timers + screencast. On resume: calls `DeviceProtocolFactory.close_all()` to invalidate stale USB handles, then restarts timers.

### L5. Asset name mismatch: FROZEN WARFRAME Ultra — DONE
**File**: `core/models.py` DEVICE_BUTTON_IMAGE[6][1]
**Fix**: Changed to `'FROZEN_WARFRAME_Ultra'` matching the actual asset filename (underscores).

### L6. Style 7 decoration color source — DONE (already fixed)
**File**: `qt_components/uc_screen_led.py` _paint_decorations
**Fix**: `deco_idx = {7: 104, 6: 93}.get(self._style_id, 0)` correctly maps style 7 to ZhuangShi21 (index 104).

### L7. Default isOn states not style-specific — DONE (already fixed)
**File**: `qt_components/uc_screen_led.py` set_style, `core/models.py` LED_DEFAULT_OFF
**Fix**: `LED_DEFAULT_OFF` dict maps each style to its off-by-default indices. `set_style()` uses it: `self._is_on = [i not in off for i in range(self._led_count)]`.

### L8. Style 6/7 decoration rectangle dimensions are approximations — DONE (already correct)
**File**: `qt_components/uc_screen_led.py` _DECO config
**Fix**: Verified against C# UCScreenLED.cs lines 2913-2971: all `_DECO` dimensions match exactly. Style 6 uses Dch2 (408x46), Dch3 (414x28), Dch4 (155x173). Style 7 uses Dch1 (400x221) with intentional 70px height crop for color fill. No changes needed.

### L9. DEVICE_IMAGE_MAP fallback missing newer products — DONE (already fixed)
**File**: `qt_components/uc_device.py` DEVICE_IMAGE_MAP
**Fix**: Map now includes LF16, LF18, LF19, LC2JD, LC3, Mjolnir_VISION_PRO, Stream_Vision, LM24, LM26, LM27, and other newer products.

### L10. Video fit-mode/rotation not exposed during live playback — DONE
**Source**: DCUserControls audit, UCBoFangQiKongZhi
**Fix**: Added height-fit and width-fit buttons to UCPreview video controls bar (C# buttonTPJCH/buttonTPJCW at same positions). VideoDecoder probes original dimensions via ffprobe, re-decodes with proportional scaling, and composites onto black canvas (letterbox or center-crop). Pipeline: UCPreview → controller → DisplayService → MediaService.set_fit_mode() → VideoDecoder re-decode.

### L11. Mask category filter buttons missing — DONE (already implemented)
**Source**: DCUserControls audit, UCThemeMask
**Fix**: `UCThemeMask._create_filter_buttons()` creates 7 category buttons from `Layout.WEB_CATEGORIES`. `_set_category()` filters masks by last character suffix. Fully matches C# UCThemeMask category filtering.

### L12. LED memory info (DRAM specs/timings) expanded — DONE
**Source**: DCUserControls audit, UCLEDMemoryInfo
**Fix**: Expanded `get_memory_info()` to capture 15 fields from dmidecode Type 17: manufacturer, part_number, type, speed, configured_memory_speed, size, form_factor, rank, data_width, total_width, configured_voltage, min/max_voltage, memory_technology. Identity label shows 2-line summary (mfr + part / type + size + speed + rank + voltage). CAS/tRCD/tRP timing values unavailable on Linux (DDR5 SPD hub not supported by decode-dimms).

### L13. LED hard disk info (model/health) expanded — DONE
**Source**: DCUserControls audit, UCLEDHarddiskInfo
**Fix**: Added SMART health check via `smartctl -H` to `get_disk_info()`. Disk identity label shows model, size, type (SSD/HDD), and SMART status (PASSED/FAILED). Disk selector combo updates identity label on change. Graceful fallback when smartctl unavailable or not running as root.

### L14. SPI mode byte order variant (myDeviceSPIMode=2) — DONE
**Source**: FormCZTV audit
**Fix**: Added (320, 240) to `ImageService._SCSI_BIG_ENDIAN` set alongside (320, 320) and (240, 320). FBL=51 (320x240) now correctly uses big-endian RGB565.

### L15. Resolution mismatch warning on .tr import — DONE (already fixed)
**Source**: FormCZTV audit, buttonDaoRu_Click
**Fix**: `ThemeService.import_tr()` checks `theme.resolution != lcd_size` and logs a warning when imported theme resolution doesn't match device.

### L16. Fan LCD RPM feedback (FBL=54, PM=100) — WON'T FIX
**Source**: FormCZTV audit, DeviceDataReceived
**Problem**: C# reads data[5]*30 as fan RPM from fan LCD devices. No device-to-host data receive path in our code.
**Decision**: FBL=54 (360x360 fan LCD) is a rare product. Adding device-to-host USB read path requires new protocol infrastructure. Fan RPM is a read-only diagnostic — doesn't affect display functionality.

### L17. Screen capture coordinates not persisted to DC — DONE (already fixed)
**Source**: FormCZTV audit
**Fix**: Full round-trip: ScreenCastPanel emits `screencast_params_changed(x,y,w,h)` → DcWriter writes JpX/JpY/JpW/JpH to config1.dc → dc_parser reads them back → `set_values()` restores UI entries on theme load. qt_app_mvc.py line 2063-2065 applies capture region from DC.

### L18. FBL 50 resolution swapped (240x320 → 320x240) — DONE
**Source**: FormCZTV.cs line 1797, `new Bitmap(320, 240)` when `directionB == 0`
**File**: `core/models.py` FBL_TO_RESOLUTION[50]
**Problem**: FBL 50 mapped to (240, 320) (portrait) but C# default orientation is (320, 240) (landscape). Mjolnir Vision 360 (87AD:70DB, PM=5) displayed with black bars on left/right.
**Fix**: Swapped to (320, 240). Added `"320x240": "bj320240"` to cloud theme URLs.

---

## NOT NEEDED (Windows-only, by design different, or C# stubs)

- Shared memory IPC with USBLCD.exe — we talk USB directly
- Windows registry autostart — we use XDG .desktop
- .NET 6 installer button
- HWiNFO shared memory — we use native Linux sensors
- WinForms DPI/memory management (GetDeviceCaps, EmptyWorkingSet)
- UCDongHuaLianDong, UCJianPanLianDongA/B/C — C# stubs (zero handlers)
- UCColorB/UCColorC inline pickers — replaced by QColorDialog
- UCShiJianXianShi/UCDingYiWenBen dedicated panels — covered by overlay grid
- Cloud download from czhorde.com — we use GitHub 7z archives
- FTP update check — we use PyPI
- Help opens PDF — we open GitHub docs
