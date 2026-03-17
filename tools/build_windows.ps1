# TRCC Windows Development Build Script
#
# Prerequisites (one-time setup):
#   1. Install Python 3.12 from python.org (check "Add to PATH")
#   2. python -m pip install pyinstaller
#   3. python -m pip install ".[nvidia,windows]"
#   4. python -m pip install libusb-package tzdata
#
# Usage:
#   cd <repo-root>
#   powershell -ExecutionPolicy Bypass -File .\tools\build_windows.ps1
#
# Output: dist\trcc\ — run directly, no installer needed.
#   .\dist\trcc\trcc.exe detect
#   .\dist\trcc\trcc.exe report
#   .\dist\trcc\trcc-gui.exe

# Don't use "Stop" — it treats native command stderr as fatal errors
# (PyInstaller, taskkill, etc. write info to stderr). Use exit code checks instead.

# Build log — everything goes to console AND build.log
$logFile = "build.log"
function Log($msg) {
  $ts = Get-Date -Format "yyyy-MM-dd HH:mm:ss"
  $line = "[$ts] $msg"
  Write-Host $line
  Add-Content -Path $logFile -Value $line
}

# Clear previous log
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

# Log build environment
Log "=== TRCC Windows Build ==="
Log "Python: $(python --version 2>&1)"
Log "PyInstaller: $(python -m PyInstaller --version 2>&1)"
Log "PySide6: $(python -c 'import PySide6; print(PySide6.__version__)' 2>&1)"
Log "Platform: $([System.Environment]::OSVersion)"
Log "Working dir: $(Get-Location)"
Log ""

# Build CLI (with console)
Log "--- Building CLI ---"
cmd /c "python -m PyInstaller --name trcc --onedir --console --uac-admin --icon src/trcc/assets/icons/app.ico --add-data src/trcc/assets;trcc/assets --hidden-import PySide6.QtSvg --hidden-import pynvml --hidden-import wmi --collect-submodules trcc --noconfirm src/trcc/__main__.py 2>&1" | Tee-Object -Append -FilePath $logFile

if ($LASTEXITCODE -ne 0) {
  Log "ERROR: CLI build failed (exit code $LASTEXITCODE)"
  exit 1
}
Log "CLI build OK"

# Build GUI (windowed, no console)
Log ""
Log "--- Building GUI ---"
cmd /c "python -m PyInstaller --name trcc-gui --onedir --windowed --uac-admin --icon src/trcc/assets/icons/app.ico --add-data src/trcc/assets;trcc/assets --hidden-import PySide6.QtSvg --hidden-import pynvml --hidden-import wmi --collect-submodules trcc --noconfirm src/trcc/__main__.py 2>&1" | Tee-Object -Append -FilePath $logFile

if ($LASTEXITCODE -ne 0) {
  Log "ERROR: GUI build failed (exit code $LASTEXITCODE)"
  exit 1
}
Log "GUI build OK"

# Merge GUI exe into CLI dist folder
Log ""
Log "--- Merging ---"
Copy-Item dist/trcc-gui/trcc-gui.exe dist/trcc/ -Force
Log "Copied trcc-gui.exe to dist/trcc/"

# Bundle libusb (pyusb needs it, PyInstaller misses it)
try {
  $libusb = python -c "import libusb_package; print(libusb_package.get_library_path())"
  if ($libusb -and (Test-Path $libusb)) {
    Copy-Item $libusb dist/trcc/ -Force
    Log "Bundled libusb: $libusb"
  }
} catch {
  Log "WARNING: libusb-package not installed, pyusb may not work"
}

# Verify
Log ""
Log "=== Build Verification ==="
$missing = @()
$exes = @("dist/trcc/trcc.exe", "dist/trcc/trcc-gui.exe")
foreach ($exe in $exes) {
  if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Log "  OK: $exe ($size MB)"
  } else {
    Log "  MISSING: $exe"
    $missing += $exe
  }
}

# Check libusb
$libusb_dll = Get-ChildItem "dist/trcc/libusb*" -ErrorAction SilentlyContinue
if ($libusb_dll) {
  Log "  OK: $($libusb_dll.Name) ($([math]::Round($libusb_dll.Length/1KB, 0)) KB)"
} else {
  Log "  MISSING: libusb-1.0.dll"
  $missing += "libusb-1.0.dll"
}

# Total size
$total = (Get-ChildItem "dist/trcc" -Recurse | Measure-Object -Property Length -Sum).Sum / 1MB
$count = (Get-ChildItem "dist/trcc" -Recurse | Measure-Object).Count
Log "  Total: $count files, $([math]::Round($total, 1)) MB"

Log ""
if ($missing.Count -gt 0) {
  Log "FAILED - Missing: $($missing -join ', ')"
  exit 1
}

# Version
$ver = python -c "from trcc.__version__ import __version__; print(__version__)" 2>&1
Log "Version: $ver"
Log ""
Log "=== Build Complete ==="
Log ""
Log "Test with:"
Log "  .\dist\trcc\trcc.exe detect"
Log "  .\dist\trcc\trcc.exe report"
Log "  .\dist\trcc\trcc-gui.exe"
Log ""
Log "Build log saved to: build.log"
