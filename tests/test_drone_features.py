"""Tests for drone-band feature extraction and classification."""
from __future__ import annotations

import numpy as np

from pluto_scanner.dsp.spectrum import SpectrumAnalyzer
from pluto_scanner.drone.bands import DroneBand
from pluto_scanner.drone.features import (
    FHSS,
    QUIET,
    VIDEO_ANALOG,
    VIDEO_DIGITAL,
    analyze_iq,
)

FS = 2.048e6
CENTER = 433.92e6
BAND = DroneBand("433", "433 МГц", 433.05e6, 434.79e6)


def _noise(n: int, rng: np.random.Generator, level: float = 2.5e-4) -> np.ndarray:
    return level * (rng.normal(size=n) + 1j * rng.normal(size=n))


def _pulsed_tone(
    *, seconds: float = 0.03, tone_hz: float = 500e3,
    pulse_rate: float = 200.0, duty: float = 0.25,
    amplitude: float = 0.25, seed: int = 3,
) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(FS * seconds)
    t = np.arange(n) / FS
    gate = (np.mod(t * pulse_rate, 1.0) < duty).astype(float)
    iq = amplitude * gate * np.exp(2j * np.pi * tone_hz * t)
    return iq + _noise(n, rng)


def _continuous_tone(*, seconds: float = 0.02,
                     tone_hz: float = 80e3,
                     amplitude: float = 0.25,
                     seed: int = 4) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(FS * seconds)
    t = np.arange(n) / FS
    return amplitude * np.exp(2j * np.pi * tone_hz * t) + _noise(n, rng)


def _wideband_noise(*, seconds: float = 0.02, width_hz: float = 6e6,
                    amplitude: float = 0.12,
                    seed: int = 5) -> np.ndarray:
    rng = np.random.default_rng(seed)
    n = int(FS * seconds)
    raw = rng.normal(size=n) + 1j * rng.normal(size=n)
    spec = np.fft.fft(raw)
    freqs = np.fft.fftfreq(n, d=1.0 / FS)
    mask = np.abs(freqs) <= width_hz / 2.0
    filtered = np.fft.ifft(spec * mask)
    filtered /= max(1e-12, np.sqrt(np.mean(np.abs(filtered) ** 2)))
    return amplitude * filtered


def test_quiet_noise_is_quiet():
    rng = np.random.default_rng(1)
    iq = _noise(int(FS * 0.02), rng)
    obs = analyze_iq(iq, FS, CENTER, BAND, analyzer=SpectrumAnalyzer(2048))
    assert obs is not None
    assert obs.class_key == QUIET
    assert obs.drone_like is False


def test_pulsed_narrowband_is_fhss_like():
    iq = _pulsed_tone()
    obs = analyze_iq(iq, FS, CENTER, BAND, analyzer=SpectrumAnalyzer(2048))
    assert obs is not None
    assert obs.burst_count >= 3
    assert 0.05 < obs.active_fraction < 0.8
    assert obs.occupied_bw_hz < 1.0e6
    assert obs.class_key == FHSS
    assert obs.drone_like is True
    assert obs.confidence >= 0.45
    assert obs.envelope_db
    assert len(obs.envelope_db) == len(obs.envelope_ms)
    assert "iq_samples" not in obs.to_dict()


def test_lo_center_spur_is_not_a_detection():
    iq = _continuous_tone(tone_hz=0.0, amplitude=0.5)
    obs = analyze_iq(iq, FS, CENTER, BAND, analyzer=SpectrumAnalyzer(2048))
    assert obs is not None
    assert obs.class_key in (QUIET, "NARROW", "UNKNOWN")
    assert obs.drone_like is False
    assert obs.occupied_bw_hz == 0.0


def test_continuous_narrowband_is_not_a_drone_alarm():
    iq = _continuous_tone(tone_hz=600e3)
    obs = analyze_iq(iq, FS, CENTER, BAND, analyzer=SpectrumAnalyzer(2048))
    assert obs is not None
    assert obs.active_fraction > 0.9
    assert obs.class_key in ("NARROW", "UNKNOWN")
    assert obs.drone_like is False


def test_wideband_video_is_detected():
    # 10.24 MS/s gives enough room for a 6 MHz-wide signal.
    fs = 10.24e6
    rng = np.random.default_rng(6)
    n = int(fs * 0.02)
    raw = rng.normal(size=n) + 1j * rng.normal(size=n)
    spec = np.fft.fft(raw)
    freqs = np.fft.fftfreq(n, d=1.0 / fs)
    spec[np.abs(freqs) > 3e6] = 0.0
    filtered = np.fft.ifft(spec)
    filtered /= max(1e-12, np.sqrt(np.mean(np.abs(filtered) ** 2)))
    iq = 0.15 * filtered
    band = DroneBand("2.4", "2.4 ГГц", 2400e6, 2420e6)
    obs = analyze_iq(iq, fs, 2410e6, band, analyzer=SpectrumAnalyzer(4096))
    assert obs is not None
    assert obs.occupied_bw_hz >= 4e6
    assert obs.active_fraction > 0.8
    assert obs.class_key in (VIDEO_ANALOG, VIDEO_DIGITAL)
    assert obs.drone_like is True
