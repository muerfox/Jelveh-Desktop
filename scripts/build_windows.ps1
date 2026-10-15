# Build the Windows app into dist/windows/Jelveh/Jelveh.exe
# Run this on Windows. PyInstaller cannot cross-compile a Qt app from Linux.
$ErrorActionPreference = "Stop"
Set-Location (Join-Path $PSScriptRoot "..")
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller packaging/Jelveh-windows.spec --noconfirm --clean `
  --distpath dist/windows --workpath build/windows
Write-Host "Windows build: dist/windows/Jelveh/Jelveh.exe"
