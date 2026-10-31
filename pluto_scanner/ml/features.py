"""Fixed-length feature vectors for the drone ML classifier."""
from __future__ import annotations

import math

import numpy as np

from ..drone.features import DroneObservation

FEATURE_NAMES = [
    "log10_bw_hz",
    "log10_snr_db",
    "active_fraction",
    "log10_bursts",
    "log10_burst_rate",
    "log10_median_burst_ms",
    "log10_max_burst_ms",
    "flatness",
    "peak_to_mean_db",
    "busy_fraction",
    "bw_fraction",
    "burst_shape",
]


def _log10(value: float, floor: float = 1.0) -> float:
    return math.log10(max(float(value), max(1e-6, floor)))


def feature_vector(obs: DroneObservation) -> np.ndarray:
    """Convert one observation into the vector expected by the model."""
    max_burst = max(float(obs.max_burst_ms), 1e-6)
    burst_shape = float(obs.median_burst_ms) / max_burst
    payload = np.array([
        _log10(obs.occupied_bw_hz),
        _log10(obs.snr_db, 0.1),
        float(np.clip(obs.active_fraction, 0.0, 1.0)),
        _log10(obs.burst_count, 0.0),
        _log10(obs.burst_rate_hz, 0.0),
        _log10(obs.median_burst_ms, 0.0),
        _log10(obs.max_burst_ms, 0.0),
        float(np.clip(obs.flatness, 0.0, 1.0)),
        float(np.clip(obs.peak_to_mean_db / 30.0, -2.0, 2.0)),
        float(np.clip(obs.busy_fraction, 0.0, 1.0)),
        float(np.clip(obs.occupied_bw_hz / max(1.0, obs.sample_rate), 0.0, 1.0)),
        float(np.clip(burst_shape, 0.0, 1.0)),
    ], dtype=np.float64)
    return np.nan_to_num(payload, nan=0.0, posinf=0.0, neginf=0.0)


def matrix(observations: list[DroneObservation]) -> np.ndarray:
    if not observations:
        return np.empty((0, len(FEATURE_NAMES)), dtype=np.float64)
    return np.vstack([feature_vector(obs) for obs in observations])
