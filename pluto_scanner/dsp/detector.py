"""Background estimation and signal detection.

The detector compares each spectrum with a median background.  During the
initial calibration the background is collected for a short period; after
that it is updated *only* while no signal is detected, so a persistent new
carrier cannot quietly become "background" after a few seconds.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

import numpy as np
from scipy import ndimage

from ..model import Detection


@dataclass
class DetectionResult:
    detections: list[Detection] = field(default_factory=list)
    baseline: np.ndarray | None = None
    calibrated: bool = False
    calibration_progress: float = 0.0


def _label_regions(low: np.ndarray, high: np.ndarray, max_gap: int) -> list[tuple[int, int]]:
    """Label low-threshold regions, bridging small gaps.

    A region must contain at least one bin above the high (enter) threshold.
    This hysteresis prevents a noisy shoulder from becoming a detection.
    """
    if not low.any() or not high.any():
        return []
    low_work = low.copy()
    if max_gap > 0:
        low_work = ndimage.binary_closing(
            low_work, structure=np.ones(max_gap + 1, dtype=bool)
        )
    labels, count = ndimage.label(low_work)
    regions: list[tuple[int, int]] = []
    for label in range(1, count + 1):
        idx = np.flatnonzero(labels == label)
        if idx.size == 0:
            continue
        inside_high = high[idx]
        if not inside_high.any():
            continue
        # Keep only the meaningful part, dropping closed-border noise.
        valid = idx[low[idx] | high[idx]]
        if valid.size == 0:
            continue
        regions.append((int(valid[0]), int(valid[-1])))
    # Merge regions which only just touch after labeling.
    merged: list[tuple[int, int]] = []
    for start, end in regions:
        if merged and start <= merged[-1][1] + max_gap + 1:
            merged[-1] = (merged[-1][0], max(merged[-1][1], end))
        else:
            merged.append((start, end))
    return merged


class Detector:
    def __init__(
        self,
        threshold_db: float = 8.0,
        exit_db: float = 4.0,
        min_bins: int = 2,
        max_gap_bins: int = 2,
        calibration_frames: int = 24,
        baseline_frames: int = 96,
        baseline_update_every: int = 8,
        smoothing_bins: int = 3,
    ) -> None:
        self.threshold_db = float(threshold_db)
        self.exit_db = float(exit_db)
        self.min_bins = max(1, int(min_bins))
        self.max_gap_bins = max(0, int(max_gap_bins))
        self.calibration_frames = max(1, int(calibration_frames))
        self.baseline_frames = max(8, int(baseline_frames))
        self.baseline_update_every = max(1, int(baseline_update_every))
        self.smoothing_bins = max(1, int(smoothing_bins))
        self.reset()

    def reset(self) -> None:
        self.baseline: np.ndarray | None = None
        self._calibration: list[np.ndarray] = []
        self._ring: deque[np.ndarray] = deque(maxlen=self.baseline_frames)
        self._frames_since_update = 0
        self.frame_count = 0

    @property
    def calibrated(self) -> bool:
        return self.baseline is not None

    def process(self, freqs: np.ndarray, psd: np.ndarray) -> DetectionResult:
        freqs = np.asarray(freqs, dtype=np.float64)
        psd = np.asarray(psd, dtype=np.float64)
        self.frame_count += 1

        if self.baseline is None:
            self._calibration.append(psd.copy())
            progress = len(self._calibration) / float(self.calibration_frames)
            if len(self._calibration) < self.calibration_frames:
                return DetectionResult([], None, False, min(1.0, progress))
            self.baseline = np.median(np.stack(self._calibration, axis=0), axis=0)
            self._calibration.clear()
            self._ring.clear()
            self._frames_since_update = 0
            return DetectionResult([], self.baseline, True, 1.0)

        assert self.baseline is not None
        diff = psd - self.baseline
        if self.smoothing_bins > 1:
            smooth = ndimage.median_filter(
                diff, size=self.smoothing_bins, mode="nearest"
            )
        else:
            smooth = diff

        detections = self._detect(freqs, psd, self.baseline, smooth)

        # Learn the background only while the band is quiet.  This is the key
        # difference from a simple running average: a new contact stays a
        # contact while it is present.
        if not detections:
            self._ring.append(psd.copy())
            self._frames_since_update += 1
            if (len(self._ring) >= 8
                    and self._frames_since_update >= self.baseline_update_every):
                self.baseline = np.median(np.stack(self._ring, axis=0), axis=0)
                self._frames_since_update = 0
        return DetectionResult(detections, self.baseline, True, 1.0)

    def _detect(self, freqs: np.ndarray, psd: np.ndarray,
                baseline: np.ndarray, diff: np.ndarray) -> list[Detection]:
        high = diff >= self.threshold_db
        low = diff >= self.exit_db
        regions = _label_regions(low, high, self.max_gap_bins)
        if not regions:
            return []
        bin_hz = float(abs(freqs[1] - freqs[0])) if freqs.size > 1 else 1.0
        out: list[Detection] = []
        for start, end in regions:
            if end - start + 1 < self.min_bins:
                continue
            region_diff = diff[start:end + 1]
            peak_local = int(np.argmax(region_diff))
            peak_idx = start + peak_local
            peak_snr = float(region_diff[peak_local])
            if peak_snr < self.threshold_db:
                continue
            region_psd = psd[start:end + 1].copy()
            region_base = baseline[start:end + 1].copy()
            # Power-weighted centre over the part of the region above the
            # background.  This is much less jittery than using peak bin.
            weights = np.clip(np.power(10.0, region_diff / 10.0) - 1.0, 0.0, None)
            if weights.sum() > 0:
                rf = freqs[start:end + 1]
                center = float(np.sum(rf * weights) / np.sum(weights))
            else:
                center = float(freqs[peak_idx])
            bw = max(bin_hz, float(end - start + 1) * bin_hz)
            positive = region_diff[region_diff > 0]
            mean_snr = float(np.mean(positive)) if positive.size else peak_snr
            out.append(
                Detection(
                    freq_hz=center,
                    bw_hz=bw,
                    peak_db=float(psd[peak_idx]),
                    snr_db=peak_snr,
                    mean_snr_db=mean_snr,
                    bin_start=int(start),
                    bin_end=int(end),
                    bin_hz=bin_hz,
                    region_db=region_psd,
                    baseline_db=region_base,
                )
            )
        return out
