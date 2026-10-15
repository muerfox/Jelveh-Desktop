# -*- mode: python ; coding: utf-8 -*-
"""Windows onedir build. Run on Windows via scripts/build_windows.ps1 so the result lands in dist/windows."""

import os

block_cipher = None
binaries = []
datas = [("assets/fonts", "assets/fonts"), ("assets/icon.png", "assets")]

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
    ["run.py"],
    pathex=["."],
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
    [],
    exclude_binaries=True,
    name="Jelveh",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    icon="assets/icon.ico",
)
coll = COLLECT(
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    name="Jelveh",
)
