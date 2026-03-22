# TRCC Windows Development Build Script
#
# Emulates windows.yml CI exactly - same tools, same bundle contents.
#
# Prerequisites (one-time setup):
#   1. Install Python 3.12 from python.org (check "Add to PATH")
#   2. Install 7-Zip system-wide from https://www.7-zip.org (needed to extract 7z-extra.7z)
#   3. python -m pip install pyinstaller
#   4. python -m pip install ".[nvidia,windows]"
#   5. python -m pip install libusb-package tzdata
#
# Usage:
#   cd <repo-root>
#   powershell -ExecutionPolicy Bypass -File .\tools\build_windows.ps1
#
# Output: dist\trcc\ - run directly, no installer needed.
#   .\dist\trcc\trcc.exe detect
#   .\dist\trcc\trcc.exe report
#   .\dist\trcc\trcc-gui.exe

$logFile = "build.log"
function Log($msg) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $msg"
  Write-Host $line
  Add-Content -Path $logFile -Value $line
}

if (Test-Path $logFile) { Remove-Item $logFile }

# Ensure Python Scripts dir is on PATH (pyinstaller lives there)
$scriptsDir = python -c "import sysconfig; print(sysconfig.get_path('scripts'))"
if ($scriptsDir -and (Test-Path $scriptsDir)) {
  $env:PATH += ";$scriptsDir"
}

# Kill running TRCC processes before build
Log "--- Stopping running TRCC processes ---"
taskkill /F /IM trcc-gui.exe *>$null
taskkill /F /IM trcc.exe *>$null
Start-Sleep -Seconds 1

Log "=== TRCC Windows Build ==="
Log "Python: $(python --version 2>&1)"
Log "PyInstaller: $(python -m PyInstaller --version 2>&1)"
Log "PySide6: $(python -c 'import PySide6; print(PySide6.__version__)' 2>&1)"
Log "Platform: $([System.Environment]::OSVersion)"
Log "Working dir: $(Get-Location)"
Log ""

# Download 7-Zip standalone (LGPL) for theme extraction
# Bootstrap via 7zr.exe (tiny self-contained exe from 7-zip.org, no install needed)
Log "--- Downloading 7-Zip standalone ---"
if (Test-Path "7z-standalone/7za.exe") {
  Log "7za.exe already present - skipping download"
} else {
  Invoke-WebRequest -Uri "https://www.7-zip.org/a/7zr.exe" -OutFile 7zr.exe
  Invoke-WebRequest -Uri "https://www.7-zip.org/a/7z2409-extra.7z" -OutFile 7z-extra.7z
  .\7zr.exe x 7z-extra.7z -o7z-standalone 7za.exe 7za.dll
  Remove-Item 7zr.exe -Force
  Remove-Item 7z-extra.7z -Force
  Log "7z standalone downloaded OK"
}

# Download ffmpeg essentials (LGPL) for video playback
Log "--- Downloading ffmpeg ---"
if (Test-Path "ffmpeg.exe") {
  Log "ffmpeg.exe already present - skipping download"
} else {
  Invoke-WebRequest -Uri "https://www.gyan.dev/ffmpeg/builds/ffmpeg-release-essentials.zip" -OutFile ffmpeg.zip
  Expand-Archive ffmpeg.zip -DestinationPath ffmpeg-tmp -Force
  $ffmpegExe = Get-ChildItem -Path ffmpeg-tmp -Recurse -Filter "ffmpeg.exe" | Select-Object -First 1
  Copy-Item $ffmpegExe.FullName -Destination ffmpeg.exe -Force
  Remove-Item ffmpeg.zip -Force
  Remove-Item ffmpeg-tmp -Recurse -Force
  Log "ffmpeg downloaded OK"
}

# Get libusb path
$libusbPath = python -c "import libusb_package; print(libusb_package.get_library_path())" 2>$null

# Build CLI (with console)
Log ""
Log "--- Building CLI ---"
pyinstaller `
  --name trcc `
  --onedir `
  --console `
  --uac-admin `
  --icon src/trcc/assets/icons/app.ico `
  --add-data "src/trcc/assets;trcc/assets" `
  --hidden-import PySide6.QtSvg `
  --hidden-import pynvml `
  --hidden-import wmi `
  --collect-submodules trcc `
  --noconfirm `
  src/trcc/__main__.py 2>&1 | Tee-Object -Append -FilePath $logFile

if ($LASTEXITCODE -ne 0) {
  Log "ERROR: CLI build failed (exit code $LASTEXITCODE)"
  exit 1
}
Log "CLI build OK"

# Build GUI (windowed, no console)
Log ""
Log "--- Building GUI ---"
pyinstaller `
  --name trcc-gui `
  --onedir `
  --windowed `
  --uac-admin `
  --icon src/trcc/assets/icons/app.ico `
  --add-data "src/trcc/assets;trcc/assets" `
  --hidden-import PySide6.QtSvg `
  --hidden-import pynvml `
  --hidden-import wmi `
  --collect-submodules trcc `
  --noconfirm `
  src/trcc/__main__.py 2>&1 | Tee-Object -Append -FilePath $logFile

if ($LASTEXITCODE -ne 0) {
  Log "ERROR: GUI build failed (exit code $LASTEXITCODE)"
  exit 1
}
Log "GUI build OK"

# Merge into dist/trcc/ (same as CI)
Log ""
Log "--- Merging ---"
Copy-Item dist/trcc-gui/trcc-gui.exe dist/trcc/ -Force
Log "Copied trcc-gui.exe"
Copy-Item 7z-standalone/7za.exe dist/trcc/7z.exe -Force
Log "Bundled 7z.exe"
Copy-Item ffmpeg.exe dist/trcc/ffmpeg.exe -Force
Log "Bundled ffmpeg.exe"
if ($libusbPath -and (Test-Path $libusbPath)) {
  Copy-Item $libusbPath dist/trcc/ -Force
  Log "Bundled libusb: $libusbPath"
} else {
  Log "WARNING: libusb-package not installed"
}

# Verify (same checks as CI)
Log ""
Log "=== Build Verification ==="
Write-Host "--- dist/trcc/ (top-level) ---"
Get-ChildItem "dist/trcc/*.exe" | ForEach-Object { Log "  $($_.Name) ($([math]::Round($_.Length/1MB, 1)) MB)" }
Get-ChildItem "dist/trcc/*.dll" | ForEach-Object { Log "  $($_.Name) ($([math]::Round($_.Length/1KB, 0)) KB)" }

$missing = @()
if (-not (Test-Path "dist/trcc/trcc.exe"))     { $missing += "trcc.exe" }
if (-not (Test-Path "dist/trcc/trcc-gui.exe")) { $missing += "trcc-gui.exe" }
if (-not (Test-Path "dist/trcc/7z.exe"))       { $missing += "7z.exe" }
if (-not (Test-Path "dist/trcc/ffmpeg.exe"))   { $missing += "ffmpeg.exe" }
$libusb_dll = Get-ChildItem "dist/trcc/libusb*" -ErrorAction SilentlyContinue
if (-not $libusb_dll) { $missing += "libusb-1.0.dll" }

$total = (Get-ChildItem "dist/trcc" -Recurse | Measure-Object).Count
$size  = (Get-ChildItem "dist/trcc" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
Log "Total: $total files, $([math]::Round($size, 1)) MB"

if ($missing.Count -gt 0) {
  Log "FAILED - Missing: $($missing -join ', ')"
  exit 1
}

$ver = python -c "from trcc.__version__ import __version__; print(__version__)" 2>&1
Log "PASSED - trcc.exe, trcc-gui.exe, 7z.exe, ffmpeg.exe, libusb OK"
Log "Version: $ver"
Log ""
Log "=== Build Complete ==="
Log ""
Log "Test with:"
Log "  .\dist\trcc\trcc.exe detect"
Log "  .\dist\trcc\trcc.exe report"
Log "  .\dist\trcc\trcc-gui.exe"
Log ""
Log "Build log saved to: $logFile"
