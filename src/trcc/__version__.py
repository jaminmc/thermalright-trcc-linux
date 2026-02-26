"""TRCC Linux version information."""

__version__ = "6.1.7"
__version_info__ = tuple(int(x) for x in __version__.split("."))

# Version history:
# 6.1.7 - Fix Bulk PM=32 (Frozen Warframe Pro) distorted colors: encoding path
#         assumed all Bulk devices use JPEG, but PM=32 uses RGB565 (cmd=3). Added
#         use_jpeg flag to DeviceInfo, propagated from BulkDevice after handshake.
#         Fix custom theme black background after reboot: ThemeService.save()
#         stored null background reference when no source theme existed — on
#         restore, background was never loaded. Now always references saved 00.png.
#         Fix HiDPI GUI scaling: disable Qt6 auto high-DPI scaling
#         (QT_ENABLE_HIGHDPI_SCALING=0) — our pixel-positioned image-based GUI
#         was doubled on HiDPI displays, showing only a quarter of the window.
#         Addresses #43, #42. 2408 tests.
# 6.1.6 - Add RAPL power sensor permissions: trcc setup-udev now writes a
#         tmpfiles.d rule and chmods /sys/class/powercap/intel-rapl:*/energy_uj
#         to 0444, enabling non-root CPU package power readings on kernels 5.10+
#         (Platypus mitigation restricted powercap sysfs to root). trcc doctor
#         checks RAPL readability. trcc setup shows RAPL status and offers to
#         fix permissions even when udev rules are already installed. trcc report
#         includes RAPL domain status. 2399 tests.
# 6.1.5 - Fix portrait cloud directory switching: non-square displays (1280x480,
#         1600x720, 1920x462, 640x480, etc.) now load cloud backgrounds and
#         masks from portrait-oriented directories (e.g., 4801280/ instead of
#         1280480/) when rotation is set to 90° or 270°. Matches C#
#         GetWebBackgroundImageDirectory / GetFileListMBDir behavior. Local
#         themes stay landscape (same as Windows TRCC). Addresses #1. 2399 tests.
# 6.1.4 - Re-release of v6.1.3 (PyPI rejects reuse of version+filename).
# 6.1.3 - Fix LED GUI settings not syncing on startup: load_config() restored
#         LED state from config.json correctly (effects worked), but panel
#         controls (mode buttons, color wheel, brightness slider, on/off)
#         showed defaults after panel.initialize() reset them. Added
#         _sync_ui_from_state() to push loaded state into UI controls after
#         initialization. Handles both zone devices (zone 0 state) and
#         single-zone devices (global state). Fix --last-one theme restore:
#         auto-fallback (first available theme when saved path missing) was
#         persisting to config, overwriting the user's saved theme preference.
#         Now fallback loads for display only (persist=False). Addresses #15.
#         2394 tests.
# 6.1.2 - Fix AK120 (style 3) and LC1 (style 4) LED wire remap tables: same
#         root cause as v6.1.1 — remap tables built using constructor default
#         UCScreenLED indices instead of style-specific ReSetUCScreenLED3/4()
#         overrides. Style 3: all 64 entries wrong (indices up to 68, beyond
#         valid range 0-63). Style 4: 29 of 31 entries wrong (indices up to 37,
#         beyond valid range 0-30). Tightened remap range test to catch this
#         class of bug automatically. 2394 tests.
# 6.1.1 - Fix PA120 (style 2) LED wire remap table: was built using default
#         UCScreenLED class indices (Cpu1=2, Cpu2=3, SSD=6, HSD=7, BFB=8,
#         digits start at 9) instead of PA120-specific ReSetUCScreenLED2()
#         indices (Cpu1=0, Cpu2=1, SSD=4, HSD=5, BFB=6, digits start at 10).
#         Every indicator and first 3 digit segments mapped to wrong wire
#         positions — cut-off numbers and missing % signs on physical display.
#         Addresses #15. 2393 tests.
# 6.1.0 - REST API full CLI parity: refactor api.py → api/ package (7 modules),
#         28 new endpoints. Display (8): color, brightness, rotation, split,
#         reset, mask upload, overlay, status. LED (14): color, mode, brightness,
#         off, sensor source, zone color/mode/brightness/toggle, sync, segment
#         toggle, clock format, temp unit, status. Themes (3): load, save,
#         import. System (3): metrics, metrics by category, diagnostic report.
#         Reuses DisplayDispatcher + LEDDispatcher (single authority pattern).
#         Device select auto-initializes the right dispatcher. 409 Conflict
#         for unselected device. 67 API tests (44 new). 2393 tests.
# 6.0.6 - Fix triple/overlapping images on Frozen Warframe SE (PM=58, FBL=58):
#         FBL 58 was missing from FBL_TO_RESOLUTION table, defaulting to
#         320x320 instead of 320x240. Wrong resolution cascaded into: no
#         pre-rotation (square displays skip it), big-endian byte order
#         (320x320 triggers it for HID), and 33% too much pixel data sent.
#         Added FBL 58 → (320, 240). Also added FBL 53 → (320, 240) with
#         big-endian byte order (HID Type 3 SPIMode=2) — completes FBL
#         table to full C# parity. Addresses #24. 2349 tests.
# 6.0.5 - Fix LED circulate not rotating zones: zone_sync_zones was never
#         initialized in configure_for_style() — stayed empty [], so zone
#         toggles during circulate silently failed and _next_sync_zone found
#         nothing to rotate. Fix color/mode not applied during circulate:
#         C# uses global rgbR1/myLedMode for non-2/7 styles (zones only drive
#         segment data rotation, not LED color), but tick() was reading
#         per-zone color. Fix color/mode routing to always set global state
#         (C# always sets rgbR1/G1/B1 + per-zone). 2349 tests.
# 6.0.4 - Fix LED circulate (zone carousel): zone buttons now toggle zones
#         in/out when circulate is active (C# radio-select sets clicked zone,
#         user adds more by clicking buttons). Interval input fires on every
#         keystroke (textChanged, not editingFinished), default 2 seconds
#         matching C#. Accurate seconds-to-ticks formula (round(s*1000/150ms)).
#         Zone uncheck guard (can't disable last zone). Fix Select All not
#         propagating mode changes to all zones (PA120/LF10). Fix
#         zone_sync_interval default (36→13 ticks = 2 seconds). 2349 tests.
# 6.0.3 - Fix LF13 (style 12) LED preview: DLF13 overlay had opaque black
#         center covering the LED color fill — made center transparent so
#         colors show through. Fix LF13 mode numbering: D0rgblf13 rainbow
#         image was shown for Temp Linked (mode 4) instead of Rainbow (mode 3)
#         due to C# 1-based vs our 0-based mode indexing. Fix PA120 segment
#         display indices: off-by-one from C# (indicators at 2-8 instead of
#         0-9, digits starting at 9 instead of 10). GPU indicators SSD1/HSD1/
#         BFB1 were aliased to CPU indices — now have own positions. Zone
#         coverage 81→84/84. LED test harness: real LEDService for segment
#         rendering, zone-aware signal wiring matching LEDHandler. 2349 tests.
# 6.0.2 - Fix video background not persisting after reboot: ThemeService.save()
#         stored video path pointing to temp dir (/tmp/trcc_work_*/Theme.zt),
#         now copies video into theme directory as Theme.zt so it survives
#         reboots. CLI graceful errors: catch typos and usage errors (missing
#         args, bad types, unknown commands) with clean one-liner + "Did you
#         mean?" suggestions instead of Python tracebacks. 2349 tests.
# 6.0.1 - Fix SCSI 320x240 chunk size (0x10000→0xE100 matching C# USBLCD.exe
#         Mode 1/2). Fixes garbled display on FBL 50 devices (Frozen Warframe
#         240, #17). Terminal preview: --preview/-p flag on all LCD and LED CLI
#         commands renders ANSI true-color art in terminal for headless/SSH
#         users (ImageService.to_ansi, LEDService.zones_to_ansi). CLI dispatcher
#         refactor: LEDDispatcher + DisplayDispatcher classes (single authority,
#         return result dicts, never print). Shared _parse_hex utility, _MODE_MAP
#         class constant, @_cli_handler consistency. Color wheel mirror fix
#         (flip canvas horizontally to match C# gradient). 2349 tests.
# 6.0.0 - GoF refactoring: 5-phase OOP overhaul. Phase 1: Flyweight+Strategy
#         collapse led_segment.py 1109→687 (-38%). Phase 3: eliminate 5 thin
#         controller wrappers (ThemeController, DeviceController, VideoController,
#         OverlayController, LEDController) — LCDDeviceController + LEDDeviceController
#         Facades absorb all methods. Phase 4: UsbProtocol base class (Template Method).
#         Phase 5: data-driven LED config serialization (Memento). Law of Demeter
#         enforced: GUI→Facade→Services, no reaching through sub-objects. Delete 3
#         protocol doc files (moved to memory). 2306 tests.
# 5.3.3 - Fix polkit setup: _sudo_reexec includes site-packages in PYTHONPATH,
#         realpath resolves UsrMerge symlinks, JS rules file for cross-DE support,
#         SELinux restorecon, pkexec uses absolute binary paths. 2291 tests.
# 1.0.0 - Initial release: GUI, local themes, cloud themes, video playback
# 1.1.0 - Settings tab fixes: overlay element cards, mask visibility, font picker,
#         12-hour time format without leading zero
# 1.1.1 - Test suite (298 tests), bug fixes found via testing
# 1.1.2 - Fix LCD send (init handshake was skipped), dynamic frame chunks for
#         multi-resolution, local themes sort defaults first, Qt6 install docs
# 1.1.3 - Cross-distro compatibility (centralized paths.py), Theme.png preview
#         includes overlays/mask, install guide covers 25+ distros, dynamic SCSI
#         scan, os.system→subprocess.run
# 1.2.0 - Autostart on login, reference theme save (config.json), resume command,
#         ruff linting, protocol reverse engineering docs, 1836 tests
# 1.2.1 - Fix RGB565 byte order for non-320x320 SCSI devices, fix GUI crash on
#         HID handshake failure, add verbose debug logging (trcc -vv gui)
# 1.2.2 - Fix local themes not loading from pip install (Custom_ dirs blocked
#         on-demand download), bump for PyPI
# 1.2.3 - Refactor: print→logging across 12 modules, thread-safe device send,
#         extract _setup_theme_dirs helper, pyusb deprecation warning filter
# 1.2.4 - Fix pip upgrade wiping themes: extract to ~/.trcc/data/ not site-packages,
#         fix install-desktop for pip installs (generate .desktop inline)
# 1.2.5 - One-time data setup: download themes/previews/masks once per resolution,
#         track in config, custom themes saved to ~/.trcc/data/ (survives upgrades)
# 1.2.6 - Fix stale config marker (verify data on disk), add debug logging for
#         theme setup, tab switches, directory verification
# 1.2.7 - Strip all theme data from wheel (download on first run only), fix
#         _has_actual_themes to require PNGs (ignore leftover .dc files)
# 1.2.8 - KISS refactor: consolidate 5 duplicate settings handlers into
#         _update_selected(), remove dead code (set_format_options, LED stubs)
# 1.2.9 - Fix HID handshake protocol (retry, timeout, endpoint auto-detect,
#         relaxed validation), OOP refactor (DcConfig, conf.py, dataclasses)
# 1.2.10 - Fix first-launch preview bug (paths not re-resolved after download)
# 1.2.11 - Fix LCD send pipeline: overlay/mask/crop/video changes now update LCD,
#          extracted _load_and_play_video() DRY helper, send_current_image applies overlay
# 1.2.12 - Fix overlay not rendering on fresh install: render_overlay_and_preview()
#          now bypasses model.enabled check, auto-enable overlay on element edit
# 1.2.13 - Fix format buttons not updating preview on fresh install: set overlay_enabled
#          on theme load, persist format prefs (time/date/temp) across theme changes
# 1.2.14 - Add GrandVision 360 AIO support (VID 87AD:70DB), fix sysfs VID readback
# 1.2.15 - Auto-detect stale udev quirks: trcc detect warns and prompts
#          sudo trcc setup-udev + reboot when USB storage quirk is missing
# 1.2.16 - Fix udev permissions on SELinux/immutable distros (Bazzite, Silverblue):
#          use MODE="0666" instead of TAG+="uaccess" which fails with SELinux enforcing
# 1.2.17 - SCSI device identification via poll resolution byte (PM mapping from
#          USBLCD.exe protocol), KVM LED backend, sensor-driven LED fix (cpu_percent/
#          gpu_usage metric keys), unified DEVICE_BUTTON_IMAGE dict for all protocols,
#          LED button image resolver, sensor source CPU/GPU toggle in LED control UI
# 1.2.18 - Fix GrandVision 360 AIO (87AD:70DB) causing GUI hang: device is vendor-
#          specific USB (class 255), not HID — removed from LED device list to stop
#          timeout loop on startup
# 1.2.19 - Raw USB bulk protocol for GrandVision/Mjolnir Vision (87AD:70DB):
#          BulkDevice handler (handshake + RGB565 frame send via pyusb),
#          BulkProtocol in device factory, bulk udev rules, CLI detect/probe
# 1.2.20 - Fix GUI not performing handshake for HID/Bulk devices: resolution
#          stayed (0,0) so themes never loaded. Now runs handshake async on
#          device selection. OOP refactor: DeviceEntry dataclass, PmEntry
#          NamedTuple, _LedProbeCache class, _resolve_pm() DRY helper
# 2.0.0  - Major refactor: rename modules to consistent device_* / driver_*
#          naming, extract constants.py, add debug_report.py diagnostic tool,
#          HR10 LED backend (device_led_hr10.py), gif_animator→media_player rename
# 2.0.1  - Fix PM=36 (240x240) wrong resolution: unify FBL/PM tables into
#          constants.py (single source of truth), PM=FBL default instead of
#          hardcoded 320x320. Fix PyQt6 version in trcc report. CI: add ffmpeg,
#          auto-publish to PyPI on tag push. Delete dead shim files.
# 3.0.0  - Hexagonal architecture: services layer (7 services), CLI Typer,
#          REST API adapter, FontResolver extraction, pure media decoders,
#          overlay_renderer merged into services/overlay, dead code removed
#          (theme_io, constants, device_base). Module renames: paths→data_repository,
#          sensor_enumerator→system_sensors, sysinfo_config→system_config,
#          cloud_downloader→theme_cloud, driver_lcd→device_lcd. 2081 tests.
# 3.0.1  - Full CLI parity: 36 Typer commands expose all service methods.
#          New: theme-save, theme-export, theme-import, led-sensor, mask --clear,
#          brightness, rotation, screencast, overlay, theme-list, theme-load,
#          led-color, led-mode, led-brightness, led-off, video. 2148 tests.
# 3.0.2  - Fix bulk protocol (87AD:70DB GrandVision): correct frame header
#          format (magic, cmd, dimensions, mode), robust kernel driver detach
#          before set_configuration(), chunked 16 KiB writes, interface claim.
#          Fix legacy autostart cleanup (glob desktop files). 2156 tests.
# 3.0.3  - Fix background display mode: continuous LCD sending via metrics
#          timer (C# myBjxs/isToTimer parity), toggle OFF renders black+overlays,
#          theme click resets all mode toggles. Security hardening (timing-safe
#          auth, PIL bomb cap, zip-slip, TOCTOU). Tooltips on all user-facing
#          buttons. Distro name in debug report. Help→troubleshooting guide.
# 3.0.4  - Fix bulk frame encoding: JPEG (cmd=2) instead of raw RGB565 for
#          all USBLCDNew devices (87AD:70DB), matching C# ImageToJpg protocol.
#          PM=32 remains RGB565 (cmd=3). Add PM=5 to bulk resolution table
#          (Mjolnir Vision → 240×320). 2166 tests.
# 3.0.5  - Fix LED mode button images: asset filename typo caused buttons
#          to show plain text instead of icons. 2167 tests.
# 3.0.6  - Single-instance guard: prevent duplicate systray entries on launch.
#          Font size spinbox in overlay color picker (independent of font dialog).
#          2167 tests.
# 3.0.7  - Unified segment display renderer for all 11 LED device styles.
#          OOP class hierarchy (SegmentDisplay ABC + 10 subclasses) with
#          data/logic separation. Covers AX120, PA120, AK120, LC1, LF8,
#          LF12, LF10, CZ1, LC2, LF11, LF15. LEDService generalized for
#          all digit-display styles (not just AX120). 2291 tests.
# 3.0.8  - Fix LED segment display: °C/°F toggle now propagates to segment
#          renderer, CPU/GPU sensor source selector now filters phase cycling
#          (show only CPU or GPU instead of always both). OOP refactor: move
#          loose functions into classes across 5 files (conf.py, device_scsi.py,
#          device_led_hr10.py, device_factory.py, device_hid.py). 2290 tests.
# 3.0.9  - Fix PA120 LED remap table (misplaced SSD/HSD/C11/B11 block shifted
#          zones 4+ by 4 wire positions). Fix HID Type 2 frame send: chunk at
#          512 bytes matching C# UCDevice.cs, skip redundant SetConfiguration
#          to prevent USB bus reset on Linux. 2290 tests.
# 3.0.10 - Rewrite UCScreenLED: exact CS paint order (dark fill → decorations
#          → LED rectangles → overlay mask), 12 ledPosition arrays with exact
#          Rectangle(x,y,w,h) coordinates, 460×460 widget. Unified device
#          sidebar buttons: remove DeviceButton class, all buttons use
#          create_image_button with setChecked() toggle. 2288 tests.
# 4.0.0  - Hexagonal adapters/ restructure: move 24 flat files into
#          adapters/device/ (10 files), adapters/system/ (3 files),
#          adapters/infra/ (11 files). Domain data consolidation: all static
#          mappings centralized in core/models.py (LED styles, button images,
#          protocol names, category data). Assets centralization: eliminate
#          19 duplicate .png calls via Assets class. Language state unified:
#          settings.lang singleton replaces 5 widget self._lang copies.
#          Clean hexagonal boundary: core/ + services/ (pure Python) →
#          adapters/ (device/system/infra I/O). 2290 tests.
# 4.1.0  - Setup wizard: CLI (trcc setup) interactive step-by-step + GUI
#          (trcc setup-gui) PySide6 wizard with check panel, Install buttons,
#          terminal output streaming. Bootstrap script (setup.sh) auto-detects
#          GUI/CLI. Expanded distro support (Solus, Clear Linux, SteamOS, Artix,
#          PostmarketOS). PM provides fallback for unmapped deps. Uninstall
#          --yes flag for non-interactive use. 2290 tests.
# 4.1.1  - Fix pyright error in setup wizard GUI (QLayoutItem.widget() optional
#          narrowing). Update all docs for v4.1.0: adapters/ layout, setup wizard
#          commands, current test count (2290), file references. 2290 tests.
# 4.2.0  - SELinux support: new `trcc setup-selinux` command installs USB policy
#          module (trcc_usb.te) for Bazzite/Silverblue/Fedora SELinux systems.
#          SELinux step in setup wizard (CLI + GUI). Fix bulk EBUSY on SELinux:
#          detect silent detach_kernel_driver() blocking, skip set_configuration()
#          if device already configured, clear error message. Distro-specific
#          install hints for checkmodule/semodule_package. Fix CI workflows
#          triggering on stable branch. 2300 tests.
# 4.2.1  - Fix bulk claim_interface EBUSY: retry with device reset on stale
#          USB claims (crashed process, suspend/resume, device re-enumeration).
#          Fix SELinux detection: detach_kernel_driver error path now correctly
#          sets selinux_blocked flag for actionable error messages. 2303 tests.
# 4.2.2  - Fix gallery/masks empty for non-320x320 resolutions: 29 of 33
#          web/zt archives had wrapping directory causing double nesting on
#          extraction. Repacked all archives to uniform flat structure. Added
#          _unwrap_nested_dir() safety net in extraction pipeline. 2308 tests.
# 4.2.3  - Fix LED style 5 (LF8 / Phantom Spirit 120 Digital Snow) display
#          corruption: add wire remap table for PM=49 (93 LEDs). C# SendHidVal
#          reorders LEDs from logical to hardware wire positions — our code was
#          missing this remap, sending colors to wrong physical LEDs. 2308 tests.
# 4.2.4  - Fix device resolution discovery: remove hardcoded 320x320 default.
#          All protocols (SCSI, HID, Bulk) now start at (0,0) and discover
#          resolution via handshake. Fixes HID devices like Assassin Spirit
#          120 Vision ARGB (PM=36, 240x240) getting wrong-sized frames.
#          CLI commands also handshake before sending. 2308 tests.
# 4.2.5  - Fix LED style mismatch for PM=49 (LF10 product, LF8 layout):
#          resolve_style_id() name lookup matched style 7 (116 LEDs) instead
#          of style 5 (93 LEDs). Now stores style_id from probe directly on
#          DeviceInfo — no reverse name lookup. 2308 tests.
# 4.2.6  - Refactor: inline trivial callbacks, DeviceInfo.from_dict() factory,
#          LEDHandler/ScreencastHandler mediators, data-driven dispatch
#          (pm_to_fbl, fbl_to_resolution), extract _render_and_send/_scan_lsscsi
#          helpers, remove duplicate overlay.configure(), dead code cleanup.
#          SCSI handshake fix (was returning None since v4.2.4). 2311 tests.
# 4.2.7  - Fix frame transfer: send entire buffer in single USB transfer
#          instead of chunking (HID Type 2 + Bulk), matching Windows USBLCDNEW.
#          Expand debug report raw handshake output from 16 to 64 bytes.
#          2311 tests.
# 4.2.8  - Fix LED segment display: LF8/LF12 MHz now uses 4 digits (0-9999)
#          matching C# SetMyNumeral, fixing 999 MHz cap. Correct usage digit
#          indices (were overlapping MHz ones position via remap table).
#          Fix LED device handshake warning on boot: route LED devices
#          directly to LED panel in auto-select, skipping LCD handshake.
#          2311 tests.
# 5.0.0  - Complete Windows C# feature parity: full gap audit (35 items
#          resolved). HIGH: fix wire remap tables for LED styles 1-12,
#          PA120 GPU digit shift, LC2 date/colon, LF11 disk metrics,
#          LC1 MHz 4-digit. MEDIUM: zone carousel, LED test mode, DDR
#          multiplier, disk selector, per-zone on/off, split mode (Dynamic
#          Island), preview drag, slideshow carousel. LOW: video fit-mode
#          during playback (width/height letterbox), expanded DRAM info
#          (15 dmidecode fields), disk SMART health, SPI byte order fix.
#          VideoDecoder fit-mode via ffprobe + proportional scaling.
#          2315 tests.
# 5.0.1  - Fix SELinux detection without root: semodule -l requires root
#          and always reported [!!] in setup-gui for non-root users.
#          Fall back to sesearch --allow which queries the loaded kernel
#          policy without elevated privileges. 2316 tests.
# 5.0.2  - Fix LED auto-detection: probe PM byte during device enumeration
#          so all 0416:8001 devices get correct style (was falling back to
#          AX120_DIGITAL for all). Config version tracking: auto-clear stale
#          device state and LED probe cache on upgrade. LED timer optimization:
#          30ms→150ms matching C# 10-tick counter, remove redundant 30ms USB
#          cooldown sleep, skip USB sends when colors unchanged (static mode).
#          Sensor poll interval 0.9s→2.0s. 2319 tests.
# 5.0.3  - Fix LED wire remap skipped: LEDService.initialize() never called
#          protocol.handshake(), so style info was never cached and wire remap
#          was silently skipped — colors sent to wrong physical LED positions.
#          Affects all LED devices (#19 Phantom Spirit EVO, #15 PA120).
#          Fix SCSI byte order: remove 240x320 from big-endian set (C# FBL 50
#          uses little-endian, not SPIMode=2). Add SCSI handshake to trcc report
#          (FBL byte + resolution) for resolution diagnostics (#17). 2352 tests.
# 5.0.4  - Fix HID Type 2 frame header: was sending all-zero 16-byte prefix,
#          device firmware expects DA DB DC DD magic + command type (0x02) +
#          mode flags matching C# FormCZTV.ImageTo565() mode 3. Without the
#          magic, firmware rejects frames — causing USB disconnect (#16) or
#          stuck-on-logo (#28). 2353 tests.
# 5.0.5  - Fix FBL 50 resolution: was (240, 320) portrait, should be
#          (320, 240) landscape — C# default directionB=0 creates Bitmap(320,240).
#          Fixes black bars on Mjolnir Vision 360 (#22). Renderer ABC refactor:
#          Strategy pattern for overlay compositing (PilRenderer adapter).
#          Overlay caching: text+mask layer cached, re-rendered only on input
#          change (~1/sec). Fix RGBA transparency bug in overlay layer.
#          Cloud theme fix: QTimer bound method wrapper, slideshow timer guards.
#          2395 tests.
# 5.0.6  - Video hot path optimization: early return in _apply_adjustments when
#          no adjustments needed (brightness=100, rotation=0, no split), remove
#          unnecessary RGBA round-trip in overlay compositing. Commit Renderer
#          ABC + PilRenderer (were untracked — fresh clone would crash). Delete
#          dead files (qt_video.py, test_renderer.py). 2359 tests.
# 5.0.7  - Fix PA120 (style 2) LED segment display: wire remap table had
#          SSD/HSD/C11/B11 indicators at end instead of position 23 (shifted
#          all LEDs after digit 3 by 4 wire positions). PA120Display logical
#          indices didn't match C# (indicators at 0-9 instead of 2-8, digit 1
#          at index 10 instead of 9) — remap read C# indices but mask wrote to
#          wrong positions. Combined effect: scrambled digits + indicators on
#          physical display. Fixes #15 "not displaying correlated data". 2359
#          tests.
# 5.0.8  - Fix HID Type 2 color distortion and rotation: RGB565 byte order
#          was big-endian for all HID devices, but C# uses little-endian for
#          HID Type 2 (myDeviceSPIMode != 2 unless SCSI mode 1 + FBL 51).
#          Also add non-square display pre-rotation: C# ImageTo565 rotates
#          non-square images 90° CW before encoding (LCD panel is physically
#          portrait-mounted). Both fixes match C# FormCZTV.ImageTo565()
#          exactly. Addresses #28 color/rotation reports. 2372 tests.
# 5.0.9  - Match C# FormLED exactly: wire all image assets (D3 preset colors,
#          D4 zone buttons, D3旋钮 color wheel, Alogout power button, P点选框
#          checkboxes for °C/°F and LC2 clock), exact pixel positions from C#
#          InitializeComponent. Fix GPU rotation for LED segment display (#19).
#          Fix LF13 background (D0rgblf13→D0LF13 for localization). Fix sensor
#          gauge visibility (show for LC2/LF13 matching C#). Rewrite memory/disk
#          info panels to C# UCLEDMemoryInfo/UCLEDHarddiskInfo layout (transparent
#          bg, golden text, exact label positions). Remove Linux-only Source:
#          CPU/GPU toggle. HR10 renders as standard LED panel. 2372 tests.
# 5.0.10 - Fix LED static/load-linked mode timeout: remove skip-if-unchanged
#          optimization — C# always sends every tick (keepalive). Fix font
#          style (bold/italic) not applied to LCD: wire font_style through
#          signal chain from QFontDialog to OverlayElementConfig. Fix bulk
#          device rotation regression: C# ImageToJpg does no pre-rotation,
#          only ImageTo565 rotates non-square displays. 2372 tests.
# 5.0.11 - Fix overlay not restoring on autostart/reboot: _apply_device_config()
#          was disabling overlay when no saved device config existed, undoing the
#          overlay that _load_theme_overlay_config() just loaded from the DC file.
#          Affects fresh installs, config resets, and USB device index changes.
#          2372 tests.
# 5.1.0  - Remove HR10 NVMe heatsink support: Linux-only device (not in Windows
#          C# reference), broken preview rendering, shared VID:PID with all LED
#          devices. Removes led_hr10.py, uc_seven_segment.py, style 13, HR10
#          CLI commands, and all related tests. LED styles now 1-12. -1762 lines.
#          2286 tests.
# 5.1.1  - OOP/KISS refactor phase 1: dc_writer class→module functions,
#          cli.py split to cli/ package (6 submodules), controller __getattr__
#          delegation (LEDController 26→6 methods, OverlayController 19→5),
#          extract LEDEffectEngine from LEDService (Strategy pattern), move
#          HW info to adapters/system/hardware.py, shared test conftest.py.
#          Net -3100 lines. 2286 tests.
# 5.1.2  - Fix SCSI SG_IO ioctl (was silently broken — ctypes bytearray bug
#          caused every write to fork sg_raw subprocess). Pre-allocate ctypes
#          buffers per chunk size. Cache shutil.which('sg_raw'). Cache
#          psutil.cpu_freq (10s TTL). Slow sensor poll 2s→4s. CPU usage
#          drops ~21%→15% (animated theme), ~7% (static). 2286 tests.
# 5.2.0  - HID Type 2 JPEG encoding for large-resolution devices: 1280x480
#          (Trofeo Vision), 1600x720, 1920x462, 854x480, 960x540, 800x480,
#          360x360 (FanLCD). C# uses ImageToJpg() (mode 2) instead of
#          ImageTo565() (mode 3) for these FBLs — header byte[6]=0x00 with
#          actual width/height instead of hardcoded 240x320. Auto-detects
#          JPEG by FF D8 magic bytes. Addresses #34/#35. 2286 tests.
# 5.2.1  - Fix LED zone_count for 3 styles: AX120 Digital (1→4), LC1 (1→3),
#          LF11 (1→4) matching C# FormLED button visibility. Enables zone
#          carousel (circulate) feature for these devices — zone buttons and
#          interval input were already wired but hidden by wrong count. 2286 tests.
# 5.2.2  - Scale HID frame timeout for large-resolution devices (1280x480+):
#          100ms→dynamic based on packet size, prevents truncated transfers.
#          Verify all bytes sent (total == len vs total > 0). Add --test-frame
#          to trcc hid-debug: sends solid red frame + reports encoding, header,
#          packet size, transfer result. Add SCSI raw poll bytes to trcc report
#          (was missing vs HID/LED/Bulk). Addresses #36. 2286 tests.
# 5.2.3  - Fix fbl_code not propagated from handshake: CLI _get_service()
#          and GUI _start_handshake() copied resolution but dropped FBL code,
#          so JPEG-mode HID devices (FBLs 54, 114, 128, 192, 224) fell through
#          to RGB565 with hardcoded 240x320 header — firmware silently ignored
#          frames. Now both paths extract fbl from handshake result. Reported
#          by @Zeltergiest in #35. 2288 tests.
# 5.3.0  - Full end-to-end data flow audit: fix API always using RGB565
#          (now delegates to send_pil for JPEG/RGB565 routing, pre-rotation,
#          byte order), fix SCSI FBL 50 byte order (320x240 little-endian,
#          not big-endian — only FBL 51 triggers SPIMode=2), propagate FBL
#          to all byte_order_for() callers (device.py, display.py, lcd.py).
#          API also propagates fbl_code from handshake. 2291 tests.
# 5.3.1  - Fix LED segment mask_size: AK120 69→64 (C# LedCountVal3=64),
#          LC1 38→31 (C# LedCountVal4=31) — extra mask entries were harmless
#          but semantically wrong. Fix LED styles 9/12 zone_count: 1→0
#          matching C# (LC2 and LF13 are zone-less). Fresh GAPS.md rewrite
#          from 4-agent cross-reference audit of all doc/audit files vs code.
#          2291 tests.
# 5.3.2  - DRY refactor: extract shared helpers from duplicate code patterns.
#          factory.py: _guarded_send() (4 send methods), _ensure_transport() +
#          _close_transport() (HID/LED), _build_usb_protocol_info() (3 get_info).
#          services: ImageService.open_and_resize(), _copy_flat_files() helper,
#          black image → ImageService.solid_color(). bulk.py: _find_vendor_interface().
#          7 patterns deduped across 5 files, net -22 lines. 2291 tests.
