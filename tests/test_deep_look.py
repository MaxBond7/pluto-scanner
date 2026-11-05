# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the deep-look capture and its cautious verdicts."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, QTimer, Signal
from PySide6.QtWidgets import QApplication

from sdr_scanner.drone import deep_look
from sdr_scanner.drone.deep_look import DeepResult, capture, interpret, look
from sdr_scanner.drone.tracker import DroneEvent
from sdr_scanner.ml.behavior import Behavior
from sdr_scanner.ui.event_dialog import DroneEventDialog


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def _behavior(**overrides) -> Behavior:
    base = dict(
        duty=0.85, burst_rate_hz=120.0, burst_interval_cv=0.1,
        hop_rate_hz=0.0, channels=1, occupied=0.5,
        sync_khz=0.0, sync_strength=0.0, frames=4000,
    )
    base.update(overrides)
    return Behavior(**base)


def test_continuous_wide_link_is_called_drone_like():
    verdict = interpret(_behavior(), 6.144e6)
    assert "видеолинк" in verdict


def test_bursty_narrow_signal_is_not_called_drone():
    verdict = interpret(_behavior(duty=0.2, occupied=0.2), 6.144e6)
    assert "маяки" in verdict


def test_ambiguous_middle_is_reported_as_ambiguous():
    verdict = interpret(_behavior(duty=0.55, occupied=0.45), 6.144e6)
    assert "неоднозначно" in verdict


def test_hopping_is_only_claimed_on_a_wide_capture():
    narrow = interpret(
        _behavior(duty=0.9, channels=30, hop_rate_hz=900.0), 6.144e6,
    )
    wide = interpret(
        _behavior(duty=0.9, channels=30, hop_rate_hz=900.0), 20.48e6,
    )
    assert "прыгает" not in narrow
    assert "прыгает" in wide


def test_text_contains_numbers_and_verdict():
    result = DeepResult(
        True, "", 2437e6, 6.144e6, _behavior(duty=0.9), "похоже на дрон",
    )
    text = result.text()
    assert "2437.000 МГц" in text
    assert "скважность 0.90" in text
    assert "похоже на дрон" in text
    assert "15 МГц" in text


def test_text_drops_the_narrow_band_caveat_on_a_wide_capture():
    result = DeepResult(
        True, "", 2437e6, 20.48e6, _behavior(), "похоже на дрон",
    )
    assert "недостоверны" not in result.text()


def test_failed_result_explains_itself():
    result = DeepResult(False, "нет данных", 2437e6, 0.0, None, "")
    assert "не удался" in result.text()


class FakeSession(QObject):
    """Minimal stand-in for DeviceSession that streams IQ from a timer."""

    iq_ready = Signal(str, object)

    def __init__(self, rate: float = 1.0e6, block: int = 10_000) -> None:
        super().__init__()
        self.config = SimpleNamespace(
            device_id="sim-1", center_freq=2412e6, sample_rate=2.048e6,
        )
        self.requested: list[tuple[str, float]] = []
        self._rate = rate
        self._block = block
        self._timer = QTimer(self)
        self._timer.setInterval(5)
        self._timer.timeout.connect(self._emit)
        self._timer.start()

    def _emit(self) -> None:
        samples = np.ones(self._block, dtype=np.complex64)
        block = SimpleNamespace(
            device_id="sim-1",
            center_freq=self.config.center_freq,
            sample_rate=self.config.sample_rate,
            samples=samples,
        )
        self.iq_ready.emit("sim-1", block)

    def set_center_freq(self, hz: float) -> None:
        self.requested.append(("center", float(hz)))
        self.config.center_freq = float(hz)

    def set_sample_rate(self, hz: float) -> None:
        self.requested.append(("rate", float(hz)))
        self.config.sample_rate = float(hz)


def test_capture_collects_and_restores_the_previous_settings(monkeypatch):
    _app()
    monkeypatch.setattr(deep_look, "SETTLE_MS", 0)
    session = FakeSession()
    data, rate, error = capture(
        session, 2437e6, seconds=0.03, sample_rate=1.0e6, timeout_s=2.0,
    )
    assert error == ""
    assert rate == 1.0e6
    assert data.size >= 30_000
    assert session.config.center_freq == pytest.approx(2412e6)
    assert session.config.sample_rate == pytest.approx(2.048e6)


def test_look_reports_a_steady_carrier(monkeypatch):
    _app()
    monkeypatch.setattr(deep_look, "SETTLE_MS", 0)
    session = FakeSession()
    result = look(
        session, 2437e6, seconds=0.03, windows=3, sample_rate=1.0e6,
    )
    assert result.ok is True
    assert result.behavior is not None
    assert result.behavior.duty > 0.9
    assert len(result.windows) == 3
    assert "стабильно" in result.stability
    assert "почему" in result.text()


def test_save_capture_writes_a_normal_recording(tmp_path, monkeypatch):
    _app()
    monkeypatch.setattr(deep_look, "SETTLE_MS", 0)
    session = FakeSession()
    result = look(
        session, 2437e6, seconds=0.03, windows=1, sample_rate=1.0e6,
    )
    info = deep_look.save_capture(result, tmp_path, label="FHSS")
    assert info is not None
    assert Path(result.path).exists()
    assert info.samples == result.data.size
    assert info.label == "FHSS"
    assert info.meta.exists()


def _event() -> DroneEvent:
    return DroneEvent(
        event_id="e1", band_key="2.4", band_name="2.4 ГГц",
        class_key="FHSS", class_ru="FHSS", freq_hz=2437e6,
        freq_min_hz=2436e6, freq_max_hz=2438e6, bw_hz=1e6,
        first_seen=1.0, last_seen=2.0, count=4, confidence=0.9,
        drone_like=True,
    )


def test_dialog_disables_deep_look_when_a_mode_blocks_it():
    _app()
    dialog = DroneEventDialog(
        _event(), deep_look=None, deep_reason="идёт запись IQ",
    )
    assert dialog.deep_btn.isEnabled() is False
    assert "запись" in dialog.deep_btn.toolTip()
    dialog.deleteLater()


def test_dialog_shows_the_deep_look_result():
    _app()
    calls: list[tuple[float, float, int]] = []

    def fake(hz: float, seconds: float, windows: int) -> DeepResult:
        calls.append((hz, seconds, windows))
        return DeepResult(
            True, "", hz, 6.144e6, _behavior(duty=0.9), "похоже на дрон",
        )

    dialog = DroneEventDialog(_event(), deep_look=fake)
    assert dialog.deep_btn.isEnabled() is True
    dialog._run_deep_look()
    assert calls and calls[0][0] == 2437e6
    assert calls[0][1] >= 0.2 and calls[0][2] >= 1
    assert "похоже на дрон" in dialog.deep_label.text()
    assert "скважность 0.90" in dialog.deep_label.text()
    dialog.deleteLater()


def test_capture_times_out_without_iq(monkeypatch):
    _app()
    monkeypatch.setattr(deep_look, "SETTLE_MS", 0)
    session = FakeSession()
    session._timer.stop()
    data, _rate, error = capture(
        session, 2437e6, seconds=0.02, sample_rate=1.0e6, timeout_s=0.2,
    )
    assert data.size == 0
    assert "не удалось" in error
