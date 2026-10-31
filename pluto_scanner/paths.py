"""Filesystem locations used by the application.

Source checkouts and portable builds keep mutable state next to the
application.  An installed build (no ``portable.flag``) uses
``%LOCALAPPDATA%\\PlutoScanner`` so Program Files stays read-only.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path


def _app_root() -> Path:
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent.parent


def resolve_data_home(
    *,
    frozen: bool,
    app_root: Path,
    env: dict[str, str] | None = None,
    portable: bool = False,
) -> Path:
    """Pick a writable data directory.

    Priority:
    1. ``PLUTO_SCANNER_DATA_DIR`` for tests and advanced users;
    2. source checkout -> project root;
    3. portable build / existing next-to-exe data -> application root;
    4. installed build -> ``%LOCALAPPDATA%\\PlutoScanner``.
    """
    values = os.environ if env is None else env
    override = values.get("PLUTO_SCANNER_DATA_DIR")
    if override:
        return Path(override).expanduser()
    if not frozen:
        return app_root
    if portable or (app_root / "user_data").exists():
        return app_root
    base = values.get("LOCALAPPDATA") or values.get("APPDATA")
    if base:
        return Path(base) / "PlutoScanner"
    return app_root


APP_ROOT = _app_root()
ASSETS_DIR = (
    Path(getattr(sys, "_MEIPASS", APP_ROOT)) / "assets"
    if getattr(sys, "frozen", False)
    else APP_ROOT / "assets"
)
DATA_HOME = resolve_data_home(
    frozen=bool(getattr(sys, "frozen", False)),
    app_root=APP_ROOT,
    portable=(APP_ROOT / "portable.flag").exists(),
)
DATA_DIR = DATA_HOME / "user_data"
RECORDINGS_DIR = DATA_HOME / "iq_recordings"
ICON_PATH = ASSETS_DIR / "pluto_scanner.ico"
DEFAULT_ML_MODEL = ASSETS_DIR / "ml_model_default.json"


def ensure_data_home() -> Path:
    """Create the data home if possible; callers fall back to APP_ROOT."""
    try:
        DATA_HOME.mkdir(parents=True, exist_ok=True)
    except OSError:
        pass
    return DATA_HOME
