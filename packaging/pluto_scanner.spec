# -*- mode: python ; coding: utf-8 -*-
"""PyInstaller one-folder build for Pluto Scanner.

Build from the project root:
    .\\.venv\\Scripts\\pyinstaller.exe packaging\\pluto_scanner.spec --noconfirm

The result is dist/PlutoScanner/ with PlutoScanner.exe and _internal/.
"""
from __future__ import annotations

import os
from pathlib import Path

from PyInstaller.utils.hooks import collect_data_files

ROOT = Path(SPECPATH).resolve().parent  # noqa: F821 - provided by PyInstaller
SYSTEM32 = Path(os.environ.get("SystemRoot", r"C:\Windows")) / "System32"

# libiio is installed system-wide on the build machine.  Copy it and its
# direct dependencies so the portable build also works on a clean Windows.
BINARIES = []
for name in (
    "libiio.dll",
    "libiio1.dll",
    "libusb-1.0.dll",
    "libserialport.dll",
    "libzstd.dll",
    "libxml2.dll",
    "vcruntime140.dll",
    "vcruntime140_1.dll",
):
    candidate = SYSTEM32 / name
    if candidate.exists():
        BINARIES.append((str(candidate), "."))

hiddenimports = [
    "adi",
    "iio",
    "sounddevice",
    "_sounddevice_data",
]
extra_datas = collect_data_files("_sounddevice_data")

a = Analysis(  # noqa: F821 - provided by PyInstaller
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT)],
    binaries=BINARIES,
    datas=[(str(ROOT / "assets"), "assets")] + extra_datas,
    hiddenimports=hiddenimports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=["tkinter", "matplotlib", "pytest"],
    noarchive=False,
    optimize=0,
)
pyz = PYZ(a.pure)  # noqa: F821

exe = EXE(  # noqa: F821
    pyz,
    a.scripts,
    [],
    exclude_binaries=True,
    name="PlutoScanner",
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=False,
    console=False,
    disable_windowed_traceback=False,
    argv_emulation=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon=str(ROOT / "assets" / "pluto_scanner.ico"),
    version=str(ROOT / "packaging" / "version_info.txt"),
)

coll = COLLECT(  # noqa: F821
    exe,
    a.binaries,
    a.datas,
    strip=False,
    upx=False,
    upx_exclude=[],
    name="PlutoScanner",
)
