"""Feature extraction and heuristic classification for drone-band activity.

This module works on raw IQ blocks.  It deliberately does **not** claim to
decode a drone protocol: it measures the things a passive receiver can
actually see — occupied bandwidth, burst timing, duty cycle, spectral
flatness and SNR — and turns them into a conservative "looks like a drone
link" score.

The output is a plain dataclass so the scanner UI, JSON recorder and tests
can all use the same object.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

import numpy as np
from scipy import ndimage

from ..dsp.spectrum import SpectrumAnalyzer
from ..scanner.peaks import decimate_mean
from .bands import DroneBand

# Classification keys are stable; Russian labels live in CLASS_RU.
FHSS = "FHSS"
TELEMETRY = "TELEMETRY"
VIDEO_ANALOG = "VIDEO_ANALOG"
VIDEO_DIGITAL = "VIDEO_DIGITAL"
WIFI = "WIFI"
NARROW = "NARROW"
UNKNOWN = "UNKNOWN"
QUIET = "QUIET"

CLASS_RU = {
    FHSS: "скачкообразное управление",
    TELEMETRY: "телеметрия / пульт",
    VIDEO_ANALOG: "аналоговое видео",
    VIDEO_DIGITAL: "цифровое видео",
    WIFI: "похоже на Wi-Fi",
    NARROW: "узкополосная активность",
    UNKNOWN: "неизвестная активность",
    QUIET: "тихо",
}

DRONE_CLASSES = {FHSS, TELEMETRY, VIDEO_ANALOG, VIDEO_DIGITAL}


@dataclass
class DroneObservation:
    timestamp: float
    device_id: str
    band_key: str
    band_name: str
    center_hz: float
    sample_rate: float
    noise_floor_db: float
    peak_db: float
    peak_freq_hz: float
    snr_db: float
    occupied_bw_hz: float
    busy_fraction: float
    active_fraction: float
    burst_count: int
    median_burst_ms: float
    max_burst_ms: float
    burst_rate_hz: float
    flatness: float
    peak_to_mean_db: float
    class_key: str
    class_ru: str
    confidence: float
    drone_like: bool
    spectrum_freqs_hz: list[float] = field(default_factory=list)
    spectrum_db: list[float] = field(default_factory=list)
    envelope_db: list[float] = field(default_factory=list)
    envelope_ms: list[float] = field(default_factory=list)
    extra: dict[str, Any] = field(default_factory=dict)
    # Raw IQ is used only for the optional evidence clip.  It is deliberately
    # excluded from to_dict() and from event JSON.
    iq_samples: np.ndarray | None = field(
        default=None, repr=False, compare=False
    )

    def to_dict(self) -> dict[str, Any]:
        return {
            "timestamp": round(float(self.timestamp), 3),
            "device_id": self.device_id,
            "band_key": self.band_key,
            "band_name": self.band_name,
            "center_hz": round(float(self.center_hz), 1),
            "sample_rate": round(float(self.sample_rate), 1),
            "noise_floor_db": round(float(self.noise_floor_db), 2),
            "peak_db": round(float(self.peak_db), 2),
            "peak_freq_hz": round(float(self.peak_freq_hz), 1),
            "snr_db": round(float(self.snr_db), 2),
            "occupied_bw_hz": round(float(self.occupied_bw_hz), 1),
            "busy_fraction": round(float(self.busy_fraction), 3),
            "active_fraction": round(float(self.active_fraction), 3),
            "burst_count": int(self.burst_count),
            "median_burst_ms": round(float(self.median_burst_ms), 2),
            "max_burst_ms": round(float(self.max_burst_ms), 2),
            "burst_rate_hz": round(float(self.burst_rate_hz), 2),
            "flatness": round(float(self.flatness), 3),
            "peak_to_mean_db": round(float(self.peak_to_mean_db), 2),
            "class_key": self.class_key,
            "class_ru": self.class_ru,
            "confidence": round(float(self.confidence), 3),
            "drone_like": bool(self.drone_like),
            "spectrum_freqs_hz": [round(float(v), 1) for v in self.spectrum_freqs_hz],
            "spectrum_db": [round(float(v), 2) for v in self.spectrum_db],
            "envelope_db": [round(float(v), 2) for v in self.envelope_db],
            "envelope_ms": [round(float(v), 3) for v in self.envelope_ms],
            "extra": dict(self.extra),
        }


# --------------------------------------------------------------------- helpers
def _notch_center(freqs: np.ndarray, psd: np.ndarray,
                  center_hz: float, notch_hz: float = 15e3) -> np.ndarray:
    work = np.asarray(psd, dtype=np.float64).copy()
    if notch_hz <= 0:
        return work
    notch = np.abs(freqs - float(center_hz)) <= float(notch_hz)
    if notch.any() and (~notch).any():
        work[notch] = float(np.median(work[~notch]))
    return work


def _region(
    freqs: np.ndarray,
    psd: np.ndarray,
    noise_floor_db: float,
    threshold_db: float,
) -> tuple[int, int, float, float, float] | None:
    """Return (start, end, peak_index, peak_db, flatness) for the strongest
    contiguous region above the threshold."""
    above = psd >= noise_floor_db + float(threshold_db)
    if not above.any():
        return None
    above = ndimage.binary_closing(above, structure=np.ones(3, dtype=bool))
    labels, count = ndimage.label(above)
    if count == 0:
        return None

    best_label = 0
    best_level = -np.inf
    for label in range(1, count + 1):
        idx = np.flatnonzero(labels == label)
        if idx.size == 0:
            continue
        level = float(np.max(psd[idx]))
        if level > best_level:
            best_level = level
            best_label = label
    if best_label == 0:
        return None

    idx = np.flatnonzero(labels == best_label)
    # Remove edge bins added by closing that are not really above threshold.
    valid = idx[above[idx]]
    if valid.size == 0:
        return None
    start = int(valid[0])
    end = int(valid[-1])
    peak_local = int(np.argmax(psd[start:end + 1]))
    peak_idx = start + peak_local
    peak_db = float(psd[peak_idx])

    power = np.power(10.0, psd[start:end + 1] / 10.0)
    arithmetic = float(np.mean(power))
    geometric = float(np.exp(np.mean(np.log(power + 1e-30))))
    flatness = geometric / arithmetic if arithmetic > 0 else 0.0
    return start, end, peak_idx, peak_db, float(np.clip(flatness, 0.0, 1.0))


def _time_features(
    iq: np.ndarray,
    sample_rate: float,
    threshold_db: float,
) -> dict[str, float | int]:
    """Burst timing from the IQ envelope.

    A continuous carrier has almost no envelope dynamics; in that case it is
    treated as one long burst, which is exactly what a video link looks like.
    """
    samples = np.asarray(iq)
    if samples.size < 64:
        return {
            "active_fraction": 0.0,
            "burst_count": 0,
            "median_burst_ms": 0.0,
            "max_burst_ms": 0.0,
            "burst_rate_hz": 0.0,
            "duration_s": 0.0,
            "envelope_low_db": -200.0,
            "envelope_db": [],
            "envelope_ms": [],
        }
    win = max(16, int(sample_rate * 0.00025))  # 0.25 ms
    usable = (samples.size // win) * win
    if usable < win:
        usable = samples.size
        win = samples.size
    chunk = samples[:usable]
    power = np.abs(chunk.astype(np.complex128)) ** 2
    env = power.reshape(-1, win).mean(axis=1)
    env_db = 10.0 * np.log10(env + 1e-20)
    duration = usable / float(sample_rate)
    low = float(np.percentile(env_db, 5.0))
    high = float(np.percentile(env_db, 95.0))
    if high - low < 3.0:
        active = np.ones(env_db.size, dtype=bool)
        burst_count = 1
    else:
        active = env_db > (low + float(threshold_db))
        active = ndimage.binary_closing(active, structure=np.ones(2, dtype=bool))
        labels, burst_count = ndimage.label(active)
        burst_count = int(burst_count)

    if active.any():
        labels, count = ndimage.label(active)
        lengths = [
            int(np.count_nonzero(labels == label))
            for label in range(1, count + 1)
        ]
        durations_ms = [
            length * (duration / max(1, active.size)) * 1000.0
            for length in lengths
        ]
        median_ms = float(np.median(durations_ms)) if durations_ms else 0.0
        max_ms = float(max(durations_ms)) if durations_ms else 0.0
    else:
        median_ms = 0.0
        max_ms = 0.0
    envelope_ms = (
        np.arange(env_db.size, dtype=np.float64)
        * (win / float(sample_rate))
        * 1000.0
    )
    return {
        "active_fraction": float(np.mean(active)),
        "burst_count": int(burst_count),
        "median_burst_ms": median_ms,
        "max_burst_ms": max_ms,
        "burst_rate_hz": float(burst_count / duration) if duration > 0 else 0.0,
        "duration_s": float(duration),
        "envelope_low_db": low,
        "envelope_db": env_db.astype(float).tolist(),
        "envelope_ms": envelope_ms.tolist(),
    }


def _confidence(class_key: str, *, snr_db: float, bw_hz: float,
                duty: float, bursts: int, flatness: float) -> float:
    snr_score = max(0.0, min(1.0, (snr_db - 6.0) / 18.0))
    if class_key == FHSS:
        score = 0.35 + 0.30 * snr_score
        score += 0.15 if bursts >= 3 else 0.05
        score += 0.10 if 0.10 <= duty <= 0.75 else 0.0
        score += 0.10 if 0.20e6 <= bw_hz <= 2.5e6 else 0.0
    elif class_key == TELEMETRY:
        score = 0.30 + 0.30 * snr_score
        score += 0.15 if bursts >= 2 else 0.05
        score += 0.15 if 0.02 <= duty <= 0.45 else 0.0
        score += 0.10 if bw_hz <= 1.2e6 else 0.0
    elif class_key == VIDEO_ANALOG:
        score = 0.40 + 0.25 * snr_score
        score += 0.20 if duty >= 0.65 else 0.0
        score += 0.15 if 3.0e6 <= bw_hz <= 10.0e6 else 0.0
    elif class_key == VIDEO_DIGITAL:
        score = 0.40 + 0.25 * snr_score
        score += 0.20 if duty >= 0.55 else 0.0
        score += 0.10 if bw_hz >= 8.0e6 else 0.0
        score += 0.05 if flatness >= 0.20 else 0.0
    elif class_key == WIFI:
        score = 0.40 + 0.25 * snr_score
        score += 0.20 if bw_hz >= 15.0e6 else 0.0
        score += 0.15 if flatness >= 0.25 else 0.0
        score += 0.10 if 0.2 <= duty <= 0.95 else 0.0
    elif class_key == NARROW:
        score = 0.25 + 0.30 * snr_score
        score += 0.10 if duty >= 0.6 else 0.0
    else:
        score = 0.15 + 0.20 * snr_score
    return float(np.clip(score, 0.0, 0.99))


def _classify(
    band: DroneBand,
    *,
    bw_hz: float,
    duty: float,
    bursts: int,
    flatness: float,
    snr_db: float,
) -> tuple[str, float, bool]:
    if snr_db < 4.0:
        return QUIET, 0.0, False
    if bw_hz >= 4.0e6 and duty >= 0.35:
        if (band.key in ("2.4", "5.8") and bw_hz >= 15.0e6
                and flatness >= 0.22 and duty < 0.98):
            class_key = WIFI
        elif bw_hz >= 8.0e6 or flatness >= 0.30:
            class_key = VIDEO_DIGITAL
        else:
            class_key = VIDEO_ANALOG
    elif bursts >= 2 and bw_hz <= 3.5e6 and duty <= 0.85:
        class_key = FHSS
    elif bursts >= 1 and bw_hz <= 1.5e6 and duty <= 0.65:
        class_key = TELEMETRY
    elif bw_hz <= 2.0e6:
        class_key = NARROW
    else:
        class_key = UNKNOWN
    confidence = _confidence(
        class_key, snr_db=snr_db, bw_hz=bw_hz,
        duty=duty, bursts=bursts, flatness=flatness,
    )
    drone_like = (
        class_key in DRONE_CLASSES
        and band.alarm
        and confidence >= 0.45
    )
    return class_key, confidence, drone_like


# ---------------------------------------------------------------------- public
def analyze_iq(
    iq: np.ndarray,
    sample_rate: float,
    center_hz: float,
    band: DroneBand,
    *,
    device_id: str = "device",
    threshold_db: float = 6.0,
    analyzer: SpectrumAnalyzer | None = None,
    noise_floor_db: float | None = None,
    nfft: int = 4096,
) -> DroneObservation | None:
    """Measure one IQ block and classify what it contains.

    Returns ``None`` only when the block is empty.  A quiet block is returned
    with ``class_key == QUIET`` so the caller can use it to learn a baseline.
    """
    iq = np.asarray(iq)
    if iq.size < 256:
        return None
    sample_rate = max(1.0, float(sample_rate))
    if analyzer is None:
        analyzer = SpectrumAnalyzer(nfft=nfft)
    freqs, psd = analyzer.compute(iq, sample_rate, center_hz)
    freqs = np.asarray(freqs, dtype=np.float64)
    psd = np.asarray(psd, dtype=np.float64)
    band_mask = (freqs >= band.start_hz) & (freqs <= band.end_hz)
    if band_mask.sum() >= 32:
        freqs = freqs[band_mask]
        psd = psd[band_mask]
    if freqs.size < 8:
        return None

    # At 20 MS/s the LO/DC spur is much wider than in the 1 MS/s scanner.
    # Chunks overlap, so a real carrier sitting exactly on one LO is still
    # visible in the neighbouring chunk.
    work = _notch_center(freqs, psd, center_hz, notch_hz=300e3)
    # The 10th percentile stays on the noise side even when a broad signal
    # occupies most of a narrow chunk.  The controller supplies a long-term
    # baseline when even that is not enough (e.g. a full-band video link).
    median_floor = float(np.percentile(work, 10.0))
    floor = float(noise_floor_db) if noise_floor_db is not None else median_floor
    # Never let a stale baseline make a noisy band look completely active.
    floor = max(floor, median_floor - 12.0)
    region = _region(freqs, work, floor, threshold_db)
    time_features = _time_features(iq, sample_rate, threshold_db)

    if region is None:
        peak_idx = int(np.argmax(psd))
        peak_db = float(psd[peak_idx])
        peak_freq = float(freqs[peak_idx])
        bw = 0.0
        flatness = 0.0
        peak_to_mean = 0.0
        busy_fraction = 0.0
    else:
        start, end, peak_idx, peak_db, flatness = region
        peak_freq = float(freqs[peak_idx])
        bw = float((end - start + 1) * abs(freqs[1] - freqs[0]))
        region_db = work[start:end + 1]
        peak_to_mean = float(peak_db - np.mean(region_db))
        busy_fraction = float(np.mean(work >= floor + threshold_db))

    snr_db = float(peak_db - floor)
    if region is None:
        class_key, confidence, drone_like = QUIET, 0.0, False
        bw = 0.0
    else:
        class_key, confidence, drone_like = _classify(
            band,
            bw_hz=bw,
            duty=float(time_features["active_fraction"]),
            bursts=int(time_features["burst_count"]),
            flatness=flatness,
            snr_db=snr_db,
        )
        if class_key == QUIET:
            bw = 0.0

    # Small spectral snapshot for the event log and UI; full PSD is not needed.
    snapshot_db = decimate_mean(psd, 256)
    if snapshot_db.size:
        snapshot_freqs = np.linspace(
            float(freqs[0]), float(freqs[-1]), snapshot_db.size
        )
    else:
        snapshot_freqs = np.empty(0)

    return DroneObservation(
        timestamp=time.time(),
        device_id=str(device_id),
        band_key=band.key,
        band_name=band.name,
        center_hz=float(center_hz),
        sample_rate=sample_rate,
        noise_floor_db=float(floor),
        peak_db=float(peak_db),
        peak_freq_hz=peak_freq,
        snr_db=snr_db,
        occupied_bw_hz=bw,
        busy_fraction=busy_fraction,
        active_fraction=float(time_features["active_fraction"]),
        burst_count=int(time_features["burst_count"]),
        median_burst_ms=float(time_features["median_burst_ms"]),
        max_burst_ms=float(time_features["max_burst_ms"]),
        burst_rate_hz=float(time_features["burst_rate_hz"]),
        flatness=float(flatness),
        peak_to_mean_db=float(peak_to_mean),
        class_key=class_key,
        class_ru=CLASS_RU.get(class_key, class_key),
        confidence=float(confidence),
        drone_like=bool(drone_like),
        spectrum_freqs_hz=snapshot_freqs.astype(float).tolist(),
        spectrum_db=snapshot_db.astype(float).tolist(),
        envelope_db=list(time_features["envelope_db"]),
        envelope_ms=list(time_features["envelope_ms"]),
        extra={
            "duration_s": float(time_features["duration_s"]),
            "envelope_low_db": float(time_features["envelope_low_db"]),
            "median_floor_db": float(median_floor),
        },
        iq_samples=iq,
    )
