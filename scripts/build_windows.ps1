# Build the Windows app into a single dist/windows/Jelveh.exe
# Run this on Windows. PyInstaller cannot cross-compile a Qt app from Linux.
$ErrorActionPreference = "Stop"
$Root = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
Set-Location $Root
$Entry = Join-Path $Root "run.py"
if (-not (Test-Path -LiteralPath $Entry)) {
    Write-Error "Entry script not found: $Entry"
}
$Spec = Join-Path $Root "packaging\Jelveh-windows.spec"
python -m pip install -r requirements.txt -r requirements-build.txt
python -m PyInstaller $Spec --noconfirm --clean `
  --distpath (Join-Path $Root "dist\windows") `
  --workpath (Join-Path $Root "build\windows")
Write-Host "Windows build: $(Join-Path $Root 'dist\windows\Jelveh.exe')"
