# TRCC Windows Development Build Script
#
# Prerequisites (one-time setup):
#   1. Install Python 3.12 from python.org (check "Add to PATH")
#   2. pip install pyinstaller
#   3. pip install ".[nvidia,windows]"
#   4. pip install libusb-package
#
# Usage:
#   cd <repo-root>
#   .\tools\build_windows.ps1
#
# Output: dist\trcc\ — run directly, no installer needed.
#   .\dist\trcc\trcc.exe detect
#   .\dist\trcc\trcc.exe report
#   .\dist\trcc\trcc-gui.exe

$ErrorActionPreference = "Stop"

Write-Host "=== TRCC Windows Build ===" -ForegroundColor Cyan

# Build CLI (with console)
Write-Host "`n--- Building CLI ---" -ForegroundColor Yellow
pyinstaller `
  --name trcc `
  --onedir `
  --console `
  --icon src/trcc/assets/icons/app.ico `
  --add-data "src/trcc/assets;trcc/assets" `
  --hidden-import PySide6.QtSvg `
  --hidden-import pynvml `
  --hidden-import wmi `
  --collect-submodules trcc `
  --noconfirm `
  src/trcc/__main__.py

# Build GUI (windowed, no console)
Write-Host "`n--- Building GUI ---" -ForegroundColor Yellow
pyinstaller `
  --name trcc-gui `
  --onedir `
  --windowed `
  --icon src/trcc/assets/icons/app.ico `
  --add-data "src/trcc/assets;trcc/assets" `
  --hidden-import PySide6.QtSvg `
  --hidden-import pynvml `
  --hidden-import wmi `
  --collect-submodules trcc `
  --noconfirm `
  src/trcc/__main__.py

# Merge GUI exe into CLI dist folder
Write-Host "`n--- Merging ---" -ForegroundColor Yellow
Copy-Item dist/trcc-gui/trcc-gui.exe dist/trcc/ -Force

# Bundle libusb (pyusb needs it, PyInstaller misses it)
try {
  $libusb = python -c "import libusb_package; print(libusb_package.get_library_path())"
  if ($libusb -and (Test-Path $libusb)) {
    Copy-Item $libusb dist/trcc/ -Force
    Write-Host "Bundled libusb: $libusb"
  }
} catch {
  Write-Host "WARNING: libusb-package not installed, pyusb may not work" -ForegroundColor Red
}

# Verify
Write-Host "`n=== Build Complete ===" -ForegroundColor Green
$exes = @("dist/trcc/trcc.exe", "dist/trcc/trcc-gui.exe")
foreach ($exe in $exes) {
  if (Test-Path $exe) {
    $size = [math]::Round((Get-Item $exe).Length / 1MB, 1)
    Write-Host "  OK: $exe ($size MB)"
  } else {
    Write-Host "  MISSING: $exe" -ForegroundColor Red
  }
}

Write-Host "`nTest with:"
Write-Host "  .\dist\trcc\trcc.exe detect"
Write-Host "  .\dist\trcc\trcc.exe report"
Write-Host "  .\dist\trcc\trcc-gui.exe"
