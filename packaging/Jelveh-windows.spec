# -*- mode: python ; coding: utf-8 -*-
"""Windows onefile build. Run on Windows via scripts/build_windows.ps1. Output is a single Jelveh.exe."""

import os

block_cipher = None
# A relative script is resolved next to this spec, which turns "run.py" into packaging/run.py.
ROOT = os.path.abspath(os.path.join(SPECPATH, os.pardir))
ENTRY = os.path.abspath(os.path.join(ROOT, "run.py"))
if not os.path.isfile(ENTRY):
    raise SystemExit("ERROR: script '%s' not found" % ENTRY)
binaries = []
datas = [
    (os.path.join(ROOT, "assets", "fonts"), os.path.join("assets", "fonts")),
    (os.path.join(ROOT, "assets", "icon.png"), "assets"),
]

try:
    import PySide6

    lib_dir = os.path.join(os.path.dirname(PySide6.__file__), "Qt", "lib")
    # Official Windows wheels ship FFmpeg as avcodec-*.dll next to the Qt libraries.
    prefixes = ("avcodec", "avformat", "avutil", "swresample", "swscale")
    if os.path.isdir(lib_dir):
        for name in os.listdir(lib_dir):
            lower = name.lower()
            if lower.startswith(prefixes) and lower.endswith(".dll"):
                binaries.append((os.path.join(lib_dir, name), os.path.join("PySide6", "Qt", "lib")))
except Exception:
    pass

a = Analysis(
    [ENTRY],
    pathex=[ROOT],
    binaries=binaries,
    datas=datas,
    hiddenimports=[
        "PySide6.QtMultimedia",
        "PySide6.QtMultimediaWidgets",
        "PySide6.QtNetwork",
    ],
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        "PySide6.Qt3DCore",
        "PySide6.QtWebEngineCore",
        "PySide6.QtWebEngineWidgets",
        "PySide6.QtQml",
        "PySide6.QtQuick",
        "PySide6.QtPdf",
    ],
    cipher=block_cipher,
    noarchive=False,
)
pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,
    a.zipfiles,
    a.datas,
    name="Jelveh",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon=os.path.join(ROOT, "assets", "icon.ico"),
)
