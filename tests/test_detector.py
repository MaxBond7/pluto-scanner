from __future__ import annotations

import numpy as np

from pluto_scanner.dsp.detector import Detector


def _axis(fs=1.024e6, nfft=2048, center=433.92e6):
    freqs = np.fft.fftshift(np.fft.fftfreq(nfft, 1.0 / fs)) + center
    return freqs


def _baseline(n=2048, seed=1):
    rng = np.random.default_rng(seed)
    return -100.0 + rng.normal(0, 0.7, n)


def test_calibration_and_two_detections():
    fs = 1.024e6
    freqs = _axis(fs)
    n = freqs.size
    det = Detector(threshold_db=8.0, exit_db=4.0, calibration_frames=8,
                   smoothing_bins=3)
    base = _baseline(n)
    for _ in range(8):
        result = det.process(freqs, base)
    assert result.calibrated
    assert det.baseline is not None

    psd = base.copy()
    for offset in (100e3, -250e3):
        idx = int(np.argmin(np.abs(freqs - (433.92e6 + offset))))
        psd[idx - 1: idx + 2] = -40.0
    result = det.process(freqs, psd)
    assert result.calibrated
    assert len(result.detections) == 2
    by_freq = sorted(result.detections, key=lambda d: d.freq_hz)
    assert abs(by_freq[0].freq_hz - (433.92e6 - 250e3)) < 1000
    assert abs(by_freq[1].freq_hz - (433.92e6 + 100e3)) < 1000
    assert all(d.snr_db > 40 for d in by_freq)
    assert all(d.bw_hz >= 1000 for d in by_freq)


def test_background_freezes_while_signals_are_present():
    fs = 1.024e6
    freqs = _axis(fs)
    n = freqs.size
    det = Detector(calibration_frames=4, smoothing_bins=3,
                   baseline_update_every=1)
    base = _baseline(n)
    for _ in range(4):
        det.process(freqs, base)
    baseline_before = det.baseline.copy()
    psd = base.copy()
    idx = int(np.argmin(np.abs(freqs - (433.92e6 + 50e3))))
    psd[idx - 1: idx + 2] = -35.0
    for _ in range(12):
        det.process(freqs, psd)
    assert np.max(np.abs(det.baseline - baseline_before)) < 0.01


def test_reset_requires_new_calibration():
    fs = 1.024e6
    freqs = _axis(fs)
    det = Detector(calibration_frames=3)
    for _ in range(3):
        det.process(freqs, _baseline(freqs.size))
    assert det.calibrated
    det.reset()
    assert not det.calibrated
    result = det.process(freqs, _baseline(freqs.size))
    assert not result.calibrated
    assert 0.0 <= result.calibration_progress <= 1.0
