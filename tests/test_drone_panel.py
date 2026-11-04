# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the drone monitor panel controls."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from pluto_scanner.ui.drone_panel import DronePanel


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_default_rate_is_safe_for_usb():
    _app()
    panel = DronePanel()
    assert panel.sample_rate() == 6.144e6
    assert panel.rate_warning.text() == ""
    panel.deleteLater()


def test_high_rate_shows_the_usb_warning():
    _app()
    panel = DronePanel()
    index = panel.rate_combo.findData(20.48e6)
    assert index >= 0
    panel.rate_combo.setCurrentIndex(index)
    assert "USB 2.0" in panel.rate_warning.text()
    safe = panel.rate_combo.findData(4.096e6)
    panel.rate_combo.setCurrentIndex(safe)
    assert panel.rate_warning.text() == ""
    panel.deleteLater()
