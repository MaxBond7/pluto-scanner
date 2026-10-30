"""Tests for per-step peak detection used by the band scanner."""
from __future__ import annotations

import numpy as np

from pluto_scanner.scanner.peaks import decimate_mean, find_peaks


def _spectrum(fs: float = 1.024e6, bins: int = 2048,
              rng: np.random.Generator | None = None):
    rng = rng or np.random.default_rng(7)
    freqs = np.linspace(-fs / 2.0, fs / 2.0, bins)
    psd = -100.0 + rng.normal(0.0, 0.35, bins)
    return freqs, psd


def test_finds_narrow_tone_and_no_dc_spur():
    freqs, psd = _spectrum()
    tone = 150e3
    psd[np.abs(freqs - tone) < 2e3] += 30.0
    psd[np.abs(freqs) < 2e3] += 45.0  # LO leakage must be notched out

    result = find_peaks(
        freqs, psd, threshold_db=8.0, center_hz=0.0, notch_hz=15e3
    )

    assert result.noise_floor_db < -95.0
    assert len(result.peaks) == 1
    peak = result.peaks[0]
    assert abs(peak.freq_hz - tone) < 4e3
    assert peak.snr_db > 20.0
    assert peak.bw_hz >= 2 * peak.bin_hz


def test_flat_noise_has_no_peaks():
    freqs, psd = _spectrum()
    result = find_peaks(freqs, psd, threshold_db=10.0)
    assert result.peaks == []


def test_wideband_peak_spans_many_bins():
    freqs, psd = _spectrum()
    psd[np.abs(freqs - 200e3) < 40e3] += 18.0
    result = find_peaks(freqs, psd, threshold_db=8.0)
    assert len(result.peaks) == 1
    assert result.peaks[0].bw_hz > 50e3


def test_decimate_mean_keeps_size_and_level():
    values = np.linspace(-100.0, -60.0, 4096)
    small = decimate_mean(values, 512)
    assert small.size == 512
    assert abs(float(small.mean()) - float(values.mean())) < 0.01
    assert decimate_mean(np.array([1.0, 2.0]), 8).size == 2
