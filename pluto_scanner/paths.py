"""Filesystem locations used by the application.

All mutable state lives next to the application (inside NEW/) instead of in
the user profile.  This keeps the project self-contained: moving the folder
also moves known contacts, signatures and logs.
"""
from __future__ import annotations

from pathlib import Path

APP_ROOT = Path(__file__).resolve().parent.parent
DATA_DIR = APP_ROOT / "user_data"
