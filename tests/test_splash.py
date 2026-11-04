# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the boot splash widget (offscreen)."""
from __future__ import annotations

import os
from types import SimpleNamespace

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication  # noqa: E402

from pluto_scanner.__main__ import _splash_disabled  # noqa: E402
from pluto_scanner.ui.splash import BIRD_ART, RAMP, SplashScreen, _trim  # noqa: E402


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_bird_art_is_a_rectangular_grid():
    assert BIRD_ART
    width = len(BIRD_ART[0])
    assert all(len(row) == width for row in BIRD_ART)
    assert all(ch in "0123456789" for row in BIRD_ART for ch in row)
    trimmed = _trim(BIRD_ART)
    assert trimmed and trimmed[0].strip("0") and trimmed[-1].strip("0")


def test_splash_renders_shimmering_text():
    _app()
    splash = SplashScreen()
    text = splash._bird_text()
    lines = text.split("\n")
    assert len(lines) == len(_trim(BIRD_ART))
    # Only characters from the density ramp (or spaces) are used.
    assert all(ch in RAMP + " " for line in lines for ch in line)
    assert any(ch not in " " for line in lines for ch in line)

    # The animation must actually change characters between frames.
    splash._frame += 7
    assert splash._bird_text() != text


def test_progress_is_monotonic_and_clamped():
    _app()
    splash = SplashScreen()
    splash.set_progress(0.5, "ТЕСТ")
    assert abs(splash._progress - 0.5) < 1e-9
    splash.set_progress(0.2, "ТЕСТ")
    assert abs(splash._progress - 0.5) < 1e-9  # never goes backwards
    splash.set_progress(2.0, "ТЕСТ")
    assert splash._progress == 1.0


def test_splash_disabled_for_screenshots_and_flag():
    plain = SimpleNamespace(
        no_splash=False, screenshot=None, screenshot_after_scan=None,
        screenshot_after_drone=None, screenshot_after_record=None,
    )
    assert not _splash_disabled(plain)
    assert _splash_disabled(
        SimpleNamespace(**{**vars(plain), "no_splash": True})
    )
    assert _splash_disabled(
        SimpleNamespace(**{**vars(plain), "screenshot": "out.png"})
    )
