"""Heuristic, honest top-3 signal classification.

This is deliberately rule-based.  It reports the best *hypotheses* with a
confidence, not a protocol name.  A 200 kHz flat blob is probably broadcast
FM; it is not "DVB-T2, 100%".
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np
from scipy.signal import find_peaks

from ..model import Detection, SignalType


@dataclass
class Features:
    bw_hz: float
    freq_hz: float
    flatness: float
    peak_to_mean: float
    symmetry: float        # 1.0 = symmetric spectrum
    occupancy: float       # fraction within 3 dB of peak
    n_peaks: int
    edge_sharpness: float
    snr_db: float
    duty: float = 1.0


@dataclass
class Classification:
    label: SignalType
    confidence: float
    alternatives: list[tuple[SignalType, float]] = field(default_factory=list)
    features: Features | None = None


class SignalClassifier:
    def __init__(self, temperature: float = 0.45) -> None:
        self.temperature = float(temperature)

    # ------------------------------------------------------------------ features
    @staticmethod
    def features(det: Detection, temporal: dict | None = None) -> Features:
        db = np.asarray(det.region_db, dtype=np.float64)
        base = np.asarray(det.baseline_db, dtype=np.float64)
        if db.size == 0:
            db = np.array([det.peak_db])
        if base.size != db.size:
            base = np.full_like(db, np.min(db) - 10.0)

        with np.errstate(over="ignore", invalid="ignore", divide="ignore"):
            p = np.power(10.0, db / 10.0) - np.power(10.0, base / 10.0)
        p = np.clip(p, 0.0, None)
        if not np.isfinite(p).all() or p.sum() <= 0:
            p = np.power(10.0, (db - np.max(db)) / 10.0)
        total = float(p.sum())
        if total <= 0:
            total = 1.0
        p = p / total
        mean_p = float(np.mean(p)) + 1e-15
        flatness = float(np.exp(np.mean(np.log(p + 1e-15))) / mean_p)
        flatness = float(np.clip(flatness, 0.0, 1.0))
        peak_to_mean = float(np.max(p) / mean_p)

        n = p.size
        half = max(1, n // 2)
        if n % 2:
            # Do not let the carrier bin itself bias the symmetry test:
            # compare the two sidebands around the centre bin.
            left = float(np.sum(p[:half]))
            right = float(np.sum(p[half + 1:]))
        else:
            left = float(np.sum(p[:half]))
            right = float(np.sum(p[half:]))
        symmetry = 1.0 - abs(left - right) / (left + right + 1e-15)

        peak_db = float(np.max(db))
        min_db = float(np.min(db))
        occupancy = float(np.mean(db > peak_db - 3.0))
        prominence = max(0.75, (peak_db - float(np.median(db))) * 0.15)
        try:
            peaks, _ = find_peaks(db, prominence=prominence, distance=2)
            n_peaks = int(peaks.size)
        except Exception:
            n_peaks = 0
        grad = np.abs(np.diff(db)) if db.size > 1 else np.zeros(1)
        edge = float(np.max(grad) / (peak_db - min_db + 1e-9)) if grad.size else 0.0
        duty = float(temporal.get("duty", 1.0)) if temporal else 1.0
        return Features(
            bw_hz=float(det.bw_hz),
            freq_hz=float(det.freq_hz),
            flatness=flatness,
            peak_to_mean=peak_to_mean,
            symmetry=symmetry,
            occupancy=occupancy,
            n_peaks=n_peaks,
            edge_sharpness=edge,
            snr_db=float(det.snr_db),
            duty=duty,
        )

    # ------------------------------------------------------------------- classify
    def classify(self, det: Detection,
                 temporal: dict | None = None) -> Classification:
        f = self.features(det, temporal)
        bw = f.bw_hz
        scores: dict[SignalType, float] = {t: 0.0 for t in SignalType}
        scores[SignalType.UNKNOWN] = 0.25

        # -- narrow / keyed carriers -----------------------------------------
        if bw <= 1.8e3 and f.peak_to_mean >= 1.7:
            scores[SignalType.CW] += 1.00 + 0.20 * (f.flatness < 0.5)
        elif bw <= 3.0e3 and f.peak_to_mean >= 3.0:
            scores[SignalType.CW] += 0.60
        elif bw <= 3.0e3 and f.n_peaks <= 2:
            scores[SignalType.CW] += 0.35

        # -- AM / SSB voice-sized channels -----------------------------------
        if 2.5e3 <= bw <= 20e3:
            scores[SignalType.AM] += 0.55 + 0.45 * f.symmetry
            if f.n_peaks >= 2:
                scores[SignalType.AM] += 0.20
            scores[SignalType.SSB] += 0.45 + 0.55 * (1.0 - f.symmetry)
        elif 1.0e3 <= bw <= 4.5e3:
            scores[SignalType.SSB] += 0.45 + 0.55 * (1.0 - f.symmetry)
            scores[SignalType.AM] += 0.15

        # -- wideband FM / broadcast -----------------------------------------
        if 40e3 <= bw <= 350e3:
            scores[SignalType.FM] += 0.65 + 0.55 * f.flatness + 0.25 * f.occupancy
            scores[SignalType.BROADCAST] += 0.35 + 0.40 * f.flatness
        if bw > 300e3:
            scores[SignalType.BROADCAST] += 0.60 + 0.45 * f.flatness
            scores[SignalType.NOISE] += 0.25 + 0.45 * f.flatness
            scores[SignalType.RADAR] += 0.35 + 0.30 * f.edge_sharpness

        # -- digital-looking blobs and bursts --------------------------------
        if bw <= 60e3 and (f.flatness > 0.22 or f.n_peaks >= 3):
            scores[SignalType.DIGITAL] += 0.45 + 0.25 * f.flatness
        if f.duty < 0.72:
            scores[SignalType.DIGITAL] += 0.20
            if bw > 100e3:
                scores[SignalType.RADAR] += 0.35

        # -- noise ------------------------------------------------------------
        if f.flatness > 0.55 and f.n_peaks == 0 and det.snr_db < 20.0:
            scores[SignalType.NOISE] += 0.55

        # -- coarse band priors ----------------------------------------------
        freq = f.freq_hz
        if 87.5e6 <= freq <= 108.0e6:
            scores[SignalType.FM] += 0.75
            scores[SignalType.BROADCAST] += 0.25
        elif 108.0e6 <= freq <= 137.0e6:
            scores[SignalType.AM] += 0.55
        elif 174.0e6 <= freq <= 240.0e6:
            scores[SignalType.BROADCAST] += 0.45
            scores[SignalType.DIGITAL] += 0.15
        elif 470.0e6 <= freq <= 960.0e6:
            scores[SignalType.BROADCAST] += 0.35
            scores[SignalType.DIGITAL] += 0.15
        elif 1452.0e6 <= freq <= 1492.0e6:
            scores[SignalType.BROADCAST] += 0.45
            scores[SignalType.DIGITAL] += 0.15
        elif 2400.0e6 <= freq <= 2483.5e6:
            scores[SignalType.DIGITAL] += 0.35
        elif 1087.0e6 <= freq <= 1093.0e6:
            scores[SignalType.DIGITAL] += 0.45
            scores[SignalType.RADAR] += 0.25
        elif 1575.0e6 <= freq <= 1576.0e6:
            scores[SignalType.DIGITAL] += 0.35
        elif (433.0e6 <= freq <= 435.0e6
              or 863.0e6 <= freq <= 870.0e6
              or 902.0e6 <= freq <= 928.0e6):
            scores[SignalType.DIGITAL] += 0.25

        ranked = sorted(scores.items(), key=lambda kv: kv[1], reverse=True)
        top = ranked[:3]
        best_label, best_score = top[0]
        if best_score < 0.5:
            return Classification(
                SignalType.UNKNOWN, 0.30,
                [(SignalType.UNKNOWN, 0.30)] + [(t, 0.1) for t, _ in top[:2]],
                f,
            )
        values = np.array([s for _, s in top], dtype=np.float64)
        values -= values.max()
        probs = np.exp(values / max(0.05, self.temperature))
        probs /= probs.sum()
        alternatives = [(t, float(p)) for (t, _), p in zip(top, probs)]
        return Classification(best_label, float(probs[0]), alternatives, f)

    def apply(self, det: Detection, temporal: dict | None = None) -> Detection:
        result = self.classify(det, temporal)
        det.type = result.label
        det.confidence = result.confidence
        det.alternatives = result.alternatives
        return det
