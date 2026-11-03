"""Correctness cross-checks and loose performance budgets.

The budgets are intentionally generous (3-5x the measured value on a normal
desktop) so a slow CI machine does not fail the build, while a real regression
— a Python loop per bin, a block-sized copy, a per-frame allocation — is caught.
"""
from __future__ import annotations

import statistics
import time

import numpy as np

from pluto_scanner.dsp.detector import Detector
from pluto_scanner.dsp.spectrum import SpectrumAnalyzer
from pluto_scanner.drone.bands import DroneBand
from pluto_scanner.drone.features import analyze_iq
from pluto_scanner.scanner.peaks import decimate_mean


def _median_ms(func, repeat: int = 7) -> float:
    func()
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        func()
        samples.append((time.perf_counter() - start) * 1000.0)
    return statistics.median(samples)


def _loop_decimate(values: np.ndarray, target: int) -> np.ndarray:
    edges = np.linspace(0, values.size, target + 1).astype(int)
    out = np.empty(target, dtype=np.float64)
    for i in range(target):
        lo, hi = edges[i], max(edges[i] + 1, edges[i + 1])
        out[i] = float(np.mean(values[lo:hi]))
    return out


def test_decimate_mean_matches_the_reference_loop():
    rng = np.random.default_rng(3)
    for size, target in ((4096, 256), (8192, 1024), (1027, 64), (300, 256)):
        values = rng.normal(-100.0, 5.0, size)
        expected = _loop_decimate(values, target)
        got = decimate_mean(values, target)
        assert got.shape == expected.shape
        assert np.allclose(got, expected, atol=1e-9)


def test_decimate_mean_is_fast():
    values = np.linspace(-120.0, -40.0, 8192)
    assert _median_ms(lambda: decimate_mean(values, 1024)) < 3.0


def test_spectrum_matches_a_reference_fft():
    rng = np.random.default_rng(1)
    fs, nfft = 1.024e6, 2048
    iq = (
        rng.normal(0, 0.01, 40960) + 1j * rng.normal(0, 0.01, 40960)
    ).astype(np.complex64)
    analyzer = SpectrumAnalyzer(nfft=nfft, max_segments=8)
    freqs, psd = analyzer.compute(iq, fs, 433.92e6)

    win = analyzer._win
    nseg = iq.size // nfft
    segs = iq[: nseg * nfft].reshape(nseg, nfft)
    idx = np.linspace(nseg - 8, nseg - 1, 8).astype(int)
    segs = segs[idx].astype(np.complex128) * win[None, :]
    spec = np.fft.fftshift(np.fft.fft(segs, axis=1), axes=1)
    reference = 10.0 * np.log10(
        np.mean(np.abs(spec) ** 2, axis=0) / analyzer._scale + 1e-20
    )
    assert psd.shape == reference.shape
    assert np.allclose(psd, reference, atol=1e-3)
    assert freqs.size == nfft
    assert abs(freqs[nfft // 2] - 433.92e6) < 1.0


def test_spectrum_stays_within_budget():
    rng = np.random.default_rng(2)
    iq = (
        rng.normal(0, 0.003, 409_600) + 1j * rng.normal(0, 0.003, 409_600)
    ).astype(np.complex64)
    analyzer = SpectrumAnalyzer(nfft=4096)
    assert _median_ms(
        lambda: analyzer.compute(iq, 20.48e6, 2437e6)
    ) < 12.0


def test_drone_analyze_iq_stays_within_budget():
    rng = np.random.default_rng(4)
    n = 409_600
    t = np.arange(n) / 20.48e6
    iq = (
        rng.normal(0, 0.003, n) + 1j * rng.normal(0, 0.003, n)
    ).astype(np.complex64)
    iq += (0.02 * np.exp(2j * np.pi * 0.55e6 * t)).astype(np.complex64)
    band = DroneBand("2.4", "2.4", 2400e6, 2483.5e6)
    obs = analyze_iq(iq, 20.48e6, 2437e6, band)
    assert obs is not None
    assert _median_ms(lambda: analyze_iq(iq, 20.48e6, 2437e6, band)) < 20.0


def test_detector_process_is_fast():
    rng = np.random.default_rng(5)
    n = 4096
    freqs = np.linspace(433.0e6, 434.0e6, n)
    psd = np.full(n, -100.0) + rng.normal(0, 0.5, n)
    detector = Detector()
    for _ in range(30):
        detector.process(freqs, psd)
    assert _median_ms(lambda: detector.process(freqs, psd)) < 8.0

def test_startup_does_not_import_scipy():
    """SciPy must stay out of the startup path: it costs ~0.5 s."""
    import subprocess
    import sys

    code = (
        "import sys, pluto_scanner.__main__; "
        "print(int('scipy.signal' in sys.modules), "
        "int('scipy.ndimage' in sys.modules))"
    )
    result = subprocess.run(
        [sys.executable, "-c", code],
        capture_output=True, text=True, timeout=120,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "0 0", result.stdout


def test_arrayops_match_scipy():
    from scipy import ndimage

    from pluto_scanner.dsp.arrayops import close_gaps, median_filter_1d, runs

    rng = np.random.default_rng(7)
    values = rng.normal(0.0, 1.0, 97)
    assert np.allclose(
        median_filter_1d(values, 3),
        ndimage.median_filter(values, size=3, mode="nearest"),
    )

    mask = np.array([0, 1, 1, 0, 0, 1, 1, 1, 0, 1, 0, 0, 0], dtype=bool)
    assert runs(mask) == [(1, 2), (5, 7), (9, 9)]
    assert not close_gaps(mask, 1)[3:5].any()
    filled = close_gaps(mask, 2)
    assert filled[3:5].all()
    assert not filled[10:].any()
