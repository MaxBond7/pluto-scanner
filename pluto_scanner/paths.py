"""Filesystem locations used by the application.

In a source checkout all mutable state lives next to the application (inside
NEW/) instead of in the user profile.  In a frozen PyInstaller build the data
directory is placed next to ``PlutoScanner.exe``, while bundled assets are
read from PyInstaller's ``_internal`` directory.
"""
from __future__ import annotations

import sys
from pathlib import Path

if getattr(sys, "frozen", False):
    APP_ROOT = Path(sys.executable).resolve().parent
    ASSETS_DIR = Path(getattr(sys, "_MEIPASS", APP_ROOT)) / "assets"
else:
    APP_ROOT = Path(__file__).resolve().parent.parent
    ASSETS_DIR = APP_ROOT / "assets"

DATA_DIR = APP_ROOT / "user_data"
ICON_PATH = ASSETS_DIR / "pluto_scanner.ico"
