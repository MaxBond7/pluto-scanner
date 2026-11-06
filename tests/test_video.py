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
    SECAM,
    VideoDecoder,
    _assemble,
    _fit_line_grid,
    _match_standard,
    _vertical_syncs,
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


@pytest.mark.parametrize(
    "standard,pixels", ((PAL, 768), (NTSC, 640), (SECAM, 768)),
)
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
    assert frame.quality > 0.45


@pytest.mark.parametrize("standard", (PAL, NTSC))
def test_weaves_two_fields_into_a_full_frame(standard):
    """The line grid and the field weaving accept a synthetic capture."""
    rate = 10e6
    slope = rate / standard.line_hz
    rows = standard.rows_per_field
    active = int(0.8 * slope)
    per_field = int(round(slope * standard.lines / 2))
    video = np.zeros(per_field * 3, dtype=np.float64)
    field_rows = []
    for field in range(3):
        base = field * per_field
        values = np.empty(rows)
        for row in range(rows):
            head = base + int((standard.top_blank + row) * slope)
            values[row] = 0.1 + 0.8 * row / max(1, rows - 1)
            video[head:head + active] = values[row]
        field_rows.append(values)
    vsync = [0.0, float(per_field), 2.0 * per_field]
    assembled = _assemble(video, standard, slope, 0.0, vsync, standard.pixels)
    assert assembled is not None
    image, quality_rows, full = assembled
    assert full is True
    assert image.shape == (standard.active_lines, standard.pixels)
    # Even rows come from the first field, odd rows from the second.
    assert np.allclose(image[0, 0], field_rows[0][0], atol=0.02)
    assert np.allclose(image[1, 0], field_rows[1][0], atol=0.02)
    assert np.allclose(image[-2, 0], field_rows[0][-1], atol=0.02)
    assert quality_rows is image


def test_a_single_field_is_doubled():
    standard = NTSC
    rate = 10e6
    slope = rate / standard.line_hz
    rows = standard.rows_per_field
    per_field = int(round(slope * standard.lines / 2))
    video = np.zeros(per_field * 2, dtype=np.float64)
    for row in range(rows):
        head = int((standard.top_blank + row) * slope)
        video[head:head + 40] = 0.1 + 0.8 * row / max(1, rows - 1)
    assembled = _assemble(
        video, standard, slope, 0.0, [0.0, float(per_field)], standard.pixels,
    )
    assert assembled is not None
    image, quality_rows, full = assembled
    assert full is False
    assert image.shape == (standard.active_lines, standard.pixels)
    assert np.allclose(image[0], image[1])
    assert quality_rows.shape[0] == rows


def test_line_grid_finds_the_period_from_sync_pulses():
    rng = np.random.default_rng(7)
    slope = 635.56
    index = np.arange(900)
    positions = 1000.0 + index * slope + rng.normal(0.0, 3.0, index.size)
    fitted, intercept, confidence = _fit_line_grid(positions, 635.0)
    assert abs(fitted - slope) < 0.05
    assert abs(intercept - 1000.0) < 10.0
    assert confidence > 0.9


def test_line_rate_selects_the_matching_standard():
    assert _match_standard(15734.8, PAL).name == "NTSC"
    assert _match_standard(15625.2, NTSC).name == "PAL"
    assert _match_standard(15625.0, SECAM).name == "SECAM"


def test_vertical_sync_pulses_are_grouped():
    slope = 635.0
    first = 500.0
    pulses = [first + step * 0.5 * slope for step in range(6)]
    pulses += [value + 400000.0 for value in pulses]
    groups = _vertical_syncs(np.asarray(pulses), slope)
    assert len(groups) == 2
    assert abs(groups[0] - first) < 1e-6
    assert abs(groups[1] - (first + 400000.0)) < 1e-6


def test_am_negative_modulation_decodes():
    rate = 10e6
    video = _video_wave(SECAM, rate, 300)
    t = np.arange(video.size) / rate
    # Negative AM modulation: sync tips are the strongest carrier.
    iq = ((0.15 + 0.8 * video)
          * np.exp(2j * np.pi * 1e6 * t)).astype(np.complex64)
    frame = decode_frame(iq, rate, SECAM, mode="am")
    assert frame is not None
    assert frame.image.shape[0] >= 90
    assert frame.image.std() > 5


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
            bandwidth=20e6, kind="hackrf", uri="",
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


def test_video_tab_decodes_an_iq_file(tmp_path):
    from sdr_scanner.ui.video_window import VideoPanel

    app = QApplication.instance() or QApplication([])
    rate = 10e6
    iq = _fm_iq(_video_wave(PAL, rate, 2200), rate)
    path = tmp_path / "recording.cf32"
    iq.tofile(path)
    session = FakeSession()
    session.config.kind = "iqfile"
    session.config.uri = str(path)
    session.config.sample_rate = rate
    window = VideoPanel(session)
    window._start()
    deadline = time.monotonic() + 8.0
    while window._last_image is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.03)
    assert window._last_image is not None
    assert window._last_frame is not None
    window._stop()
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
