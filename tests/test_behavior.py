# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Behavioural features: tests with synthetic signals only (no dataset needed)."""
from __future__ import annotations

import numpy as np

from sdr_scanner.ml.behavior import analyze

RATE = 20.0e6


def _tone(freqs: np.ndarray, rate: float = RATE) -> np.ndarray:
    t = np.arange(freqs.size) / rate
    return np.exp(2j * np.pi * freqs * t).astype(np.complex64)


def test_steady_carrier_has_no_hops():
    iq = _tone(np.full(int(RATE * 0.02), 5e6))
    result = analyze(iq, RATE, max_seconds=0.02)
    assert result.duty > 0.95
    assert result.hop_rate_hz < 50.0
    assert result.channels == 1
    assert result.burst_rate_hz < 10.0


def test_hopping_carrier_is_detected():
    segments = 20                       # 20 ms in 1 ms pieces
    piece = np.empty(0, dtype=np.complex64)
    for index in range(segments):
        freq = 5e6 if index % 2 == 0 else -5e6
        piece = np.concatenate([piece, _tone(np.full(int(RATE * 0.001), freq))])
    result = analyze(piece, RATE, max_seconds=0.02)
    assert result.duty > 0.95
    assert result.hop_rate_hz > 800.0
    assert result.channels == 2


def test_pulsed_carrier_reports_burst_rate():
    rate = RATE
    seconds = 0.2
    iq = np.zeros(int(rate * seconds), dtype=np.complex64)
    gap = int(rate * 0.01)              # 100 Hz
    for start in range(0, iq.size, gap):
        iq[start:start + int(rate * 0.002)] = _tone(
            np.full(int(rate * 0.002), 3e6), rate
        )
    result = analyze(iq, rate, max_seconds=seconds)
    assert 80.0 < result.burst_rate_hz < 130.0
    assert result.duty < 0.4


def test_analog_video_line_rate():
    rate = 4e6
    seconds = 0.5
    t = np.arange(int(rate * seconds)) / rate
    # Envelope pulsed at 15.625 kHz on a 1 MHz carrier.
    envelope = 0.5 + 0.5 * np.sign(np.sin(2 * np.pi * 15625.0 * t))
    iq = (envelope * np.exp(2j * np.pi * 1e6 * t)).astype(np.complex64)
    result = analyze(iq, rate, max_seconds=seconds)
    assert abs(result.sync_khz - 15.625) < 1.5
    assert result.sync_strength > 5.0


def test_short_block_is_safe():
    result = analyze(np.zeros(10, dtype=np.complex64), RATE)
    assert result.frames == 0
    assert result.duty == 0.0
