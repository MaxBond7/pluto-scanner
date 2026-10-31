"""Features for the binary drone / background model.

The six-class model reuses the heuristic's measurements (occupied bandwidth,
burst count, ...).  Those measurements assume a flat noise floor: they compare
every bin with one global percentile.  A real receiver does not have a flat
floor — the analog filter and the FIR roll-off shape it by tens of dB — and
the DroneRF recordings show this very clearly.  Feeding shaped spectra to the
heuristic produces "narrow 15 kHz activity" for a 9 MHz video link.

This module therefore computes its own features from the *same* spectrum
snapshot the UI already draws:

* subtract a robust straight-line baseline (a drone link is a wide plateau on
  top of a smooth floor, so a straight line cannot swallow it);
* describe how much of the band is lifted, how flat the lift is, and how it
  behaves in time.

Everything is relative: no absolute dBFS, no absolute bandwidth in MHz, no
sample-rate-dependent numbers.  That is what lets a model trained on 20 MS/s
recordings work at 1 MS/s and 61 MS/s.
"""
from __future__ import annotations

import math

import numpy as np

from ..drone.features import DroneObservation

BINARY_FEATURE_NAMES = [
    "peak_db",
    "p90_db",
    "p50_db",
    "occ_6db",
    "occ_12db",
    "occ_20db",
    "span_6db",
    "flatness",
    "entropy",
    "log_regions",
    "largest_share",
    "edge_rise_db",
    "duty",
    "envelope_cv",
    "envelope_span_db",
    "log_burst_rate",
    "log_median_burst_ms",
    "envelope_autocorr",
]

_BASELINE_DEGREE = 1
_BASELINE_ITERATIONS = 4


def robust_baseline(psd_db: np.ndarray, degree: int = _BASELINE_DEGREE) -> np.ndarray:
    """Fit a smooth floor to a dB spectrum, ignoring the bins above it.

    A polynomial is fitted, the bins clearly above the fit are dropped, and the
    fit is repeated.  A straight line keeps wide plateaus (drone video) intact,
    while still following the slow tilt of a real front end.
    """
    psd = np.asarray(psd_db, dtype=np.float64)
    if psd.size < 8:
        return np.zeros_like(psd)
    x = np.arange(psd.size, dtype=np.float64)
    fit = np.polyval(np.polyfit(x, psd, degree), x)
    for _ in range(_BASELINE_ITERATIONS):
        residual = psd - fit
        keep = residual < (float(np.median(residual)) + 2.0)
        if int(keep.sum()) < max(16, psd.size // 8):
            break
        fit = np.polyval(np.polyfit(x[keep], psd[keep], degree), x)
    return fit


def _regions(above: np.ndarray, gap: int = 1) -> list[tuple[int, int]]:
    """Contiguous runs of ``True``, tolerating small gaps."""
    regions: list[tuple[int, int]] = []
    start: int | None = None
    gap_run = 0
    for index, value in enumerate(above):
        if value:
            if start is None:
                start = index
            gap_run = 0
        elif start is not None:
            gap_run += 1
            if gap_run > gap:
                regions.append((start, index - gap_run))
                start = None
                gap_run = 0
    if start is not None:
        regions.append((start, above.size - 1))
    return regions


def _entropy(power: np.ndarray) -> float:
    total = float(power.sum())
    if total <= 0.0:
        return 0.0
    p = power / total
    return float(-np.sum(p * np.log(p + 1e-12)) / math.log(max(2, power.size)))


def _autocorr_peak(envelope: np.ndarray, max_lag: int = 100) -> float:
    if envelope.size < 8:
        return 0.0
    centered = envelope - float(envelope.mean())
    denom = float(np.dot(centered, centered))
    if denom <= 1e-30:
        return 0.0
    limit = min(max_lag, envelope.size // 2)
    if limit < 2:
        return 0.0
    best = 0.0
    for lag in range(2, limit + 1):
        value = float(np.dot(centered[:-lag], centered[lag:]) / denom)
        if value > best:
            best = value
    return float(np.clip(best, 0.0, 1.0))


def _envelope_features(
    envelope_db: list[float] | np.ndarray,
    duration_s: float,
) -> dict[str, float]:
    env = np.asarray(envelope_db, dtype=np.float64)
    if env.size < 8:
        return {
            "duty": 0.0,
            "envelope_cv": 0.0,
            "envelope_span_db": 0.0,
            "log_burst_rate": 0.0,
            "log_median_burst_ms": 0.0,
            "envelope_autocorr": 0.0,
        }
    low = float(np.percentile(env, 10.0))
    high = float(np.percentile(env, 95.0))
    span = max(0.0, high - low)
    if span < 3.0:
        active = np.ones(env.size, dtype=bool)
    else:
        active = env > (low + 6.0)
    power = np.power(10.0, env / 10.0)
    mean = float(power.mean())
    cv = float(power.std() / mean) if mean > 0 else 0.0

    regions = _regions(active)
    count = len(regions)
    step_ms = 1000.0 * float(duration_s) / max(1, env.size)
    lengths_ms = [(end - start + 1) * step_ms for start, end in regions]
    median_ms = float(np.median(lengths_ms)) if lengths_ms else 0.0
    rate = count / max(1e-6, float(duration_s)) if duration_s > 0 else 0.0
    return {
        "duty": float(np.mean(active)),
        "envelope_cv": float(cv),
        "envelope_span_db": float(np.clip(span, 0.0, 90.0)),
        "log_burst_rate": float(math.log10(1.0 + rate)),
        "log_median_burst_ms": float(math.log10(1.0 + median_ms)),
        "envelope_autocorr": _autocorr_peak(power),
    }


def extract(
    spectrum_db: list[float] | np.ndarray,
    envelope_db: list[float] | np.ndarray,
    *,
    duration_s: float = 0.02,
) -> np.ndarray:
    """Build the binary feature vector from a spectrum and an envelope."""
    psd = np.asarray(spectrum_db, dtype=np.float64)
    if psd.size < 16:
        return np.zeros(len(BINARY_FEATURE_NAMES), dtype=np.float64)
    baseline = robust_baseline(psd)
    residual = psd - baseline
    power = np.power(10.0, residual / 10.0)

    peak = float(np.max(residual))
    p90 = float(np.percentile(residual, 90.0))
    p50 = float(np.percentile(residual, 50.0))
    occ6 = float(np.mean(residual > 6.0))
    occ12 = float(np.mean(residual > 12.0))
    occ20 = float(np.mean(residual > 20.0))

    above = residual > 6.0
    indices = np.flatnonzero(above)
    span = (
        float((indices[-1] - indices[0] + 1) / psd.size)
        if indices.size else 0.0
    )
    arithmetic = float(power.mean())
    geometric = float(np.exp(np.mean(np.log(power + 1e-12))))
    flatness = geometric / arithmetic if arithmetic > 0 else 0.0

    regions = _regions(above)
    total_power = float(power.sum())
    largest = 0.0
    if regions and total_power > 0:
        shares = [
            float(power[start:end + 1].sum()) / total_power
            for start, end in regions
        ]
        largest = max(shares)

    edge = max(2, psd.size // 10)
    edge_rise = 0.5 * (
        float(residual[:edge].mean()) + float(residual[-edge:].mean())
    ) - float(residual[edge:-edge].mean() if psd.size > 2 * edge else p50)

    envelope = _envelope_features(envelope_db, duration_s)
    payload = np.array([
        peak,
        p90,
        p50,
        occ6,
        occ12,
        occ20,
        span,
        float(np.clip(flatness, 0.0, 1.0)),
        _entropy(power),
        float(math.log10(1.0 + len(regions))),
        float(np.clip(largest, 0.0, 1.0)),
        edge_rise,
        envelope["duty"],
        float(np.clip(envelope["envelope_cv"], 0.0, 20.0)),
        envelope["envelope_span_db"],
        envelope["log_burst_rate"],
        envelope["log_median_burst_ms"],
        envelope["envelope_autocorr"],
    ], dtype=np.float64)
    return np.nan_to_num(payload, nan=0.0, posinf=0.0, neginf=0.0)


def from_observation(obs: DroneObservation) -> np.ndarray:
    duration = float(obs.extra.get("duration_s", 0.02) or 0.02)
    return extract(
        obs.spectrum_db,
        obs.envelope_db,
        duration_s=duration,
    )


def matrix(observations: list[DroneObservation]) -> np.ndarray:
    if not observations:
        return np.empty((0, len(BINARY_FEATURE_NAMES)), dtype=np.float64)
    return np.vstack([from_observation(obs) for obs in observations])
