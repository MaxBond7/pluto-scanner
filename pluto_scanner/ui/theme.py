"""Compatibility shim: the theme engine now lives in :mod:`pluto_scanner.ui.themes`."""
from __future__ import annotations

from .themes import (  # noqa: F401
    BUILTIN_THEMES,
    DEFAULT_THEME,
    TOKENS,
    Theme,
    active_theme,
    apply_theme,
    available_themes,
    build_stylesheet,
    load_settings,
    load_theme_file,
    qss,
    resolve_theme,
    save_settings,
    tcol,
    theme_dir,
    theme_from_dict,
    trgba,
)

__all__ = [
    "BUILTIN_THEMES",
    "DEFAULT_THEME",
    "TOKENS",
    "Theme",
    "active_theme",
    "apply_theme",
    "available_themes",
    "build_stylesheet",
    "load_settings",
    "load_theme_file",
    "qss",
    "resolve_theme",
    "save_settings",
    "tcol",
    "theme_dir",
    "theme_from_dict",
    "trgba",
]
