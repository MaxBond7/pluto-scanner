"""Synthetic IQ generator for the drone ML baseline.

The generator creates the six classes the monitor can actually measure:
FHSS, telemetry, analog video, digital video, Wi-Fi-like wideband bursts and
narrow continuous carriers.  It is intentionally simple and reproducible; it
is a training baseline, not a claim about real drone protocols.
"""
from __future__ import annotations

from collections.abc import Callable

import numpy as np

from ..drone.bands import DroneBand
from ..drone.features import (
    FHSS,
    NARROW,
    TELEMETRY,
    VIDEO_ANALOG,
    VIDEO_DIGITAL,
    WIFI,
    analyze_iq,
)
from .features import feature_vector

CLASSES = [FHSS, TELEMETRY, VIDEO_ANALOG, VIDEO_DIGITAL, WIFI, NARROW]

# sample rate, block duration
SPECS: dict[str, tuple[float, float]] = {
    FHSS: (2.048e6, 0.20),
    TELEMETRY: (2.048e6, 0.20),
    NARROW: (2.048e6, 0.20),
    VIDEO_ANALOG: (10.24e6, 0.05),
    VIDEO_DIGITAL: (10.24e6, 0.05),
    WIFI: (10.24e6, 0.05),
}

_BAND = DroneBand(
    "2.4", "2.4 ГГц", 2400.0e6, 2483.5e6,
    "synthetic training band", alarm=True,
)


def _noise(n: int, rng: np.random.Generator, sigma: float) -> np.ndarray:
    return sigma * (
        rng.normal(size=n).astype(np.float64)
        + 1j * rng.normal(size=n).astype(np.float64)
    )


def _band_noise(
    n: int, fs: float, bw_hz: float, shape: str, rng: np.random.Generator
) -> np.ndarray:
    raw = (
        rng.normal(size=n).astype(np.float64)
        + 1j * rng.normal(size=n).astype(np.float64)
    )
    spec = np.fft.fft(raw)
    freqs = np.fft.fftfreq(n, d=1.0 / fs)
    if shape == "gauss":
        mask = np.exp(-0.5 * (freqs / max(1.0, bw_hz / 2.2)) ** 2)
    else:
        mask = (np.abs(freqs) <= max(1.0, bw_hz / 2.0)).astype(np.float64)
    wave = np.fft.ifft(spec * mask)
    rms = float(np.sqrt(np.mean(np.abs(wave) ** 2)))
    return wave / max(rms, 1e-12)


def _gate(
    t: np.ndarray, burst_ms: float, duty: float, rng: np.random.Generator
) -> np.ndarray:
    duty = float(np.clip(duty, 0.02, 1.0))
    if duty >= 0.99:
        return np.ones_like(t)
    burst_s = max(1e-4, burst_ms / 1000.0)
    period = burst_s / duty
    phase = rng.uniform(0.0, period)
    return (np.mod(t + phase, period) < burst_s).astype(np.float64)


def _phase_tone(freq: np.ndarray, fs: float, phase0: float) -> np.ndarray:
    return np.exp(1j * (2.0 * np.pi * np.cumsum(freq) / fs + phase0))


def make_iq(
    label: str,
    *,
    fs: float,
    duration: float,
    rng: np.random.Generator,
) -> np.ndarray:
    n = max(4096, int(fs * duration))
    t = np.arange(n, dtype=np.float64) / fs
    limit = 0.42 * fs
    phase0 = rng.uniform(0.0, 2.0 * np.pi)
    wave: np.ndarray

    if label == NARROW:
        offset = rng.uniform(-limit, limit)
        depth = rng.uniform(0.0, 0.25)
        wave = np.exp(
            1j * (2.0 * np.pi * offset * t + phase0)
        ) * (1.0 - depth + depth * np.sin(2.0 * np.pi * 3.0 * t))
    elif label == TELEMETRY:
        symbol_rate = rng.uniform(4e3, 80e3)
        sps = max(1, int(fs / symbol_rate))
        bits = rng.integers(0, 2, int(np.ceil(n / sps)) + 1)
        deviation = rng.uniform(5e3, 60e3)
        freq = np.repeat(bits * 2.0 - 1.0, sps)[:n] * deviation
        wave = _phase_tone(freq, fs, phase0)
        wave *= _gate(t, rng.uniform(8.0, 80.0), rng.uniform(0.05, 0.45), rng)
    elif label == FHSS:
        hop_ms = rng.uniform(0.5, 3.0)
        hop_len = max(1, int(fs * hop_ms / 1000.0))
        hops = int(np.ceil(n / hop_len))
        offsets = rng.uniform(-limit, limit, hops)
        freq = np.repeat(offsets, hop_len)[:n]
        wave = _phase_tone(freq, fs, phase0)
        wave *= _gate(
            t, hop_ms * rng.uniform(0.5, 1.0), rng.uniform(0.3, 0.95), rng
        )
    elif label == VIDEO_ANALOG:
        bw = rng.uniform(2.0e6, 5.5e6)
        wave = _band_noise(n, fs, bw, "gauss", rng)
    elif label == VIDEO_DIGITAL:
        bw = rng.uniform(3.0e6, 7.0e6)
        wave = _band_noise(n, fs, bw, "rect", rng)
    elif label == WIFI:
        bw = rng.uniform(6.0e6, 9.5e6)
        wave = _band_noise(n, fs, bw, "rect", rng)
        wave *= _gate(t, rng.uniform(1.5, 12.0), rng.uniform(0.2, 0.95), rng)
    else:
        raise ValueError(f"unknown synthetic label: {label}")

    amp = rng.uniform(0.06, 0.16)
    sigma = rng.uniform(0.008, 0.030)
    return (amp * wave + _noise(n, rng, sigma)).astype(np.complex64)


def generate_dataset(
    per_class: int = 60,
    *,
    seed: int = 1,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[np.ndarray, list[str], list[str]]:
    """Return (feature matrix, labels, heuristic labels)."""
    per_class = max(1, int(per_class))
    rng = np.random.default_rng(seed)
    rows: list[np.ndarray] = []
    labels: list[str] = []
    heuristics: list[str] = []
    total = per_class * len(CLASSES)

    for label in CLASSES:
        fs, duration = SPECS[label]
        for _ in range(per_class):
            iq = make_iq(label, fs=fs, duration=duration, rng=rng)
            obs = analyze_iq(
                iq, fs, _BAND.center_hz, _BAND,
                device_id="synthetic", threshold_db=6.0, nfft=4096,
            )
            if obs is None or obs.snr_db < 5.0:
                iq = (iq * 3.0).astype(np.complex64)
                obs = analyze_iq(
                    iq, fs, _BAND.center_hz, _BAND,
                    device_id="synthetic", threshold_db=6.0, nfft=4096,
                )
            if obs is None:
                continue
            rows.append(feature_vector(obs))
            labels.append(label)
            heuristics.append(obs.class_key)
            if progress is not None:
                progress(len(rows), total, label)

    return np.vstack(rows), labels, heuristics
