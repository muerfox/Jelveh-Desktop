#!/usr/bin/env bash
# Build the Linux app and pack it as dist/linux/Jelveh-<version>-<arch>.AppImage
set -euo pipefail
cd "$(dirname "$0")/.."

python3 -m pip install -i https://mirror-pypi.runflare.com/simple -r requirements.txt -r requirements-build.txt
python3 -m PyInstaller packaging/Jelveh-linux.spec --noconfirm --clean \
  --distpath dist/linux --workpath build/linux

ARCH="$(uname -m)"
VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' jelveh/__init__.py)"
ROOT="$(pwd)"
APPDIR="${ROOT}/dist/linux/Jelveh.AppDir"
OUTPUT="${ROOT}/dist/linux/Jelveh-${VERSION}-${ARCH}.AppImage"
TOOL="${ROOT}/build/linux/appimagetool-${ARCH}.AppImage"

rm -rf "$APPDIR"
mkdir -p "$APPDIR/usr/bin" "${ROOT}/build/linux"
cp -a "${ROOT}/dist/linux/Jelveh/." "$APPDIR/usr/bin/"
cp packaging/jelveh.desktop "$APPDIR/jelveh.desktop"
cp assets/icon.png "$APPDIR/jelveh.png"
cp assets/icon.png "$APPDIR/.DirIcon"
cat > "$APPDIR/AppRun" << 'EOF'
#!/bin/sh
HERE="$(dirname "$(readlink -f "$0")")"
exec "$HERE/usr/bin/Jelveh" "$@"
EOF
chmod +x "$APPDIR/AppRun" "$APPDIR/usr/bin/Jelveh"

if [[ ! -x "$TOOL" ]]; then
  curl -fsSL -o "$TOOL" \
    "https://github.com/AppImage/appimagetool/releases/download/continuous/appimagetool-${ARCH}.AppImage"
  chmod +x "$TOOL"
fi

ARCH="$ARCH" APPIMAGE_EXTRACT_AND_RUN=1 "$TOOL" "$APPDIR" "$OUTPUT"
chmod +x "$OUTPUT"
echo "Linux build: $OUTPUT"
