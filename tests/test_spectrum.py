"""Unit tests for the DSP core.  Run with ``python -m pytest``."""
from __future__ import annotations

import math

import numpy as np
import pytest

from pluto_scanner.dsp.spectrum import SpectrumAnalyzer


def _tone_iq(fs: float, n: int, offset_hz: float, amp: float = 1.0) -> np.ndarray:
    t = np.arange(n, dtype=np.float64) / fs
    return amp * np.exp(2j * np.pi * offset_hz * t)


def test_full_scale_complex_tone_is_zero_dbfs():
    fs = 1.024e6
    nfft = 2048
    analyzer = SpectrumAnalyzer(nfft=nfft)
    iq = _tone_iq(fs, nfft * 8, 100e3, 1.0)
    freqs, psd = analyzer.compute(iq, fs, 433.92e6)
    idx = int(np.argmin(np.abs(freqs - (433.92e6 + 100e3))))
    assert abs(float(psd[idx])) < 0.5
    assert freqs.size == nfft
    bin_hz = fs / nfft
    assert abs(float(freqs[0]) - (433.92e6 - fs / 2)) <= bin_hz
    assert abs(float(freqs[-1]) - (433.92e6 + fs / 2)) <= bin_hz


def test_short_block_is_zero_padded():
    analyzer = SpectrumAnalyzer(nfft=1024)
    freqs, psd = analyzer.compute(_tone_iq(1.024e6, 100, 0.0), 1.024e6, 100e6)
    assert freqs.size == 1024
    assert np.all(np.isfinite(psd))
