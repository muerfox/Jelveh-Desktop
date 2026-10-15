#!/usr/bin/env bash
# Build the Linux app into dist/linux/Jelveh/
set -euo pipefail
cd "$(dirname "$0")/.."
python3 -m pip install -r requirements.txt -r requirements-build.txt
python3 -m PyInstaller packaging/Jelveh-linux.spec --noconfirm --clean \
  --distpath dist/linux --workpath build/linux
cp packaging/jelveh.desktop dist/linux/jelveh.desktop
echo "Linux build: dist/linux/Jelveh/Jelveh"
