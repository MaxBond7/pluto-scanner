# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""The controller must free the receiver without losing its place."""
from __future__ import annotations

from types import SimpleNamespace

from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from sdr_scanner.drone.controller import DroneWatchController


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


class FakeSession(QObject):
    iq_ready = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(
            device_id="sim-1", name="Симулятор 1", kind="sim",
            center_freq=2412e6, sample_rate=6.144e6,
            bandwidth=4.9e6, gain=40.0, uri="",
        )
        self.audio_enabled = True
        self.centers: list[float] = []
        self.rates: list[float] = []
        self.monitor_mode = False

    def set_monitor_mode(self, enabled: bool) -> None:
        self.monitor_mode = bool(enabled)

    def set_audio_enabled(self, enabled: bool) -> None:
        self.audio_enabled = bool(enabled)

    def set_sample_rate(self, hz: float) -> None:
        self.rates.append(float(hz))
        self.config.sample_rate = float(hz)

    def set_bandwidth(self, hz: float) -> None:
        self.config.bandwidth = float(hz)

    def set_buffer_size(self, samples: int) -> None:
        pass

    def set_center_freq(self, hz: float) -> None:
        self.centers.append(float(hz))
        self.config.center_freq = float(hz)

    def set_gain(self, db: float) -> None:
        self.config.gain = float(db)

    def reset_background(self) -> None:
        pass


class FakeChunk(SimpleNamespace):
    pass


def _chunk(center: float, index: int = 0) -> FakeChunk:
    return FakeChunk(
        center_hz=center,
        band=SimpleNamespace(key="2.4", name="2.4 ГГц"),
        index=index, total=1,
    )


def test_pause_stops_the_timer_and_resume_retunes_the_same_chunk():
    _app()
    session = FakeSession()
    controller = DroneWatchController(
        session, [_chunk(2437e6)], sample_rate=6.144e6,
    )
    assert controller.start() is True
    assert controller.paused is False

    assert controller.pause() is True
    assert controller.paused is True
    assert controller._timer.isActive() is False
    assert controller.pause() is False          # already paused

    before = list(session.centers)
    controller.resume()
    assert controller.paused is False
    assert controller._timer.isActive() is True
    assert session.centers[-1] == 2437e6
    assert session.centers.count(2437e6) >= before.count(2437e6) + 1

    controller.stop()
    assert controller.running is False
    controller.deleteLater()
