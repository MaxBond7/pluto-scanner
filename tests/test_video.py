# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic PAL/NTSC tests for the analog video decoder."""
from __future__ import annotations

import time
from types import SimpleNamespace

import numpy as np
import pytest
from PySide6.QtCore import QObject, Signal
from PySide6.QtWidgets import QApplication

from sdr_scanner.video.analog import (
    NTSC,
    PAL,
    VideoDecoder,
    decode_frame,
    demodulate,
)


def _video_wave(standard, rate: float, lines: int) -> np.ndarray:
    line = int(round(rate / standard.line_hz))
    video = np.zeros(lines * line, dtype=np.float64)
    for index in range(lines):
        base = index * line
        sync = int(0.073 * line)
        porch = int(0.09 * line)
        active = int(0.78 * line)
        video[base:base + sync] = 0.0
        video[base + sync:base + sync + porch] = 0.12
        x = np.linspace(0.0, 1.0, active)
        pattern = 0.2 + 0.65 * (
            0.5 + 0.5 * np.sin(2 * np.pi * (x * 6 + index / 40.0))
        )
        video[base + sync + porch:base + sync + porch + active] = pattern
    return video


def _fm_iq(video: np.ndarray, rate: float) -> np.ndarray:
    t = np.arange(video.size) / rate
    phase = 2 * np.pi * (
        1.0e6 * t + 2.0e6 * np.cumsum(video) / rate
    )
    return np.exp(1j * phase).astype(np.complex64)


@pytest.mark.parametrize("standard,pixels", ((PAL, 768), (NTSC, 640)))
def test_decodes_a_monochrome_frame(standard, pixels):
    rate = 10e6
    video = _video_wave(standard, rate, 300)
    iq = _fm_iq(video, rate)
    frame = decode_frame(iq, rate, standard)
    assert frame is not None
    assert frame.image.shape[1] == pixels
    assert frame.image.shape[0] >= 90
    assert abs(frame.line_hz - standard.line_hz) < 300
    assert frame.locked is True
    assert frame.image.std() > 10


def test_decoder_emits_a_frame_from_blocks():
    rate = 10e6
    video = _video_wave(PAL, rate, 2000)
    iq = _fm_iq(video, rate)
    decoder = VideoDecoder(PAL, frame_seconds=0.12, max_seconds=0.3)
    frame = None
    for start in range(0, iq.size, 200_000):
        frame = decoder.feed(iq[start:start + 200_000], rate) or frame
        if frame is not None:
            break
    assert frame is not None
    assert decoder.frames >= 1


class FakeSession(QObject):
    iq_ready = Signal(str, object)

    def __init__(self) -> None:
        super().__init__()
        self.config = SimpleNamespace(
            device_id="fake", center_freq=1240e6, sample_rate=20e6,
            bandwidth=20e6, kind="hackrf",
        )
        self.audio_enabled = False
        self.worker = SimpleNamespace(isRunning=lambda: True)
        self.calls: list[tuple[str, float]] = []

    def set_monitor_mode(self, enabled):
        self.calls.append(("monitor", float(enabled)))

    def set_audio_enabled(self, enabled):
        self.audio_enabled = bool(enabled)

    def set_sample_rate(self, rate):
        self.calls.append(("rate", float(rate)))

    def set_bandwidth(self, bw):
        self.calls.append(("bw", float(bw)))

    def set_center_freq(self, hz):
        self.calls.append(("center", float(hz)))

    def set_buffer_size(self, samples):
        pass


def test_video_window_builds_a_frame_from_a_fake_session():
    from sdr_scanner.ui.video_window import VideoPanel

    app = QApplication.instance() or QApplication([])
    rate = 20e6
    video = _video_wave(PAL, rate, 2200)
    iq = _fm_iq(video, rate)
    session = FakeSession()
    window = VideoPanel(session)
    window._start()
    block_size = 200_000
    for start in range(0, iq.size, block_size):
        block = SimpleNamespace(
            device_id="fake",
            samples=iq[start:start + block_size],
            sample_rate=rate,
            center_freq=1240e6,
        )
        window._on_iq("fake", block)
        if window._last_image is not None:
            break
    deadline = time.monotonic() + 8.0
    while window._last_image is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.03)
    assert window._last_image is not None
    assert window._last_frame is not None
    window._stop()
    assert ("monitor", 0.0) in session.calls
    window.deleteLater()
    app.processEvents()


def test_demodulate_supports_am():
    rate = 2e6
    t = np.arange(int(rate * 0.01)) / rate
    envelope = 0.5 + 0.4 * np.sin(2 * np.pi * 1000 * t)
    iq = (envelope * np.exp(2j * np.pi * 200e3 * t)).astype(np.complex64)
    video = demodulate(iq, mode="am")
    assert video.size == iq.size
    assert video.std() > 0.05
