# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the drone monitor panel controls."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication

from sdr_scanner.ui.drone_panel import DronePanel


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

def _event(background: float):
    from sdr_scanner.drone.tracker import DroneEvent

    return DroneEvent(
        event_id="e1", band_key="2.4", band_name="2.4 ГГц",
        class_key="FHSS", class_ru="FHSS", freq_hz=2437e6,
        freq_min_hz=2436e6, freq_max_hz=2438e6, bw_hz=1e6,
        first_seen=1.0, last_seen=2.0, count=4, confidence=0.9,
        drone_like=True, background=background,
        binary={"score": 0.99, "verdict": "drone"},
    )


def test_background_event_does_not_pop_the_banner():
    _app()
    panel = DronePanel()
    panel.add_event(_event(0.9), True)
    assert panel.alarm.text() == ""

    panel.add_event(_event(0.1), True)
    assert panel.alarm.text() != ""
    panel.deleteLater()
