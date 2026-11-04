# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Peak detection for a single scan step.

The live detector in :mod:`pluto_scanner.dsp.detector` is designed for a
*stationary* LO: it learns a background over many frames.  A sweep retunes the
LO for every step, so that calibration never completes.  The scanner therefore
uses a self-contained detector: the noise floor of the current step is the
median of its PSD, and peaks are regions above that floor.

The function is intentionally free of Qt so it can be tested and reused by the
CLI.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from ..model import Detection
from ..dsp.arrayops import close_gaps, median_filter_1d, runs
from ..dsp.classifier import SignalClassifier


@dataclass
class PeakResult:
    peaks: list[Detection]
    noise_floor_db: float
    threshold_db: float


def find_peaks(
    freqs: np.ndarray,
    psd: np.ndarray,
    threshold_db: float = 8.0,
    min_bins: int = 2,
    max_gap_bins: int = 2,
    smooth_bins: int = 3,
    center_hz: float | None = None,
    notch_hz: float = 15e3,
    classifier: SignalClassifier | None = None,
) -> PeakResult:
    """Detect signals in one PSD frame relative to its own noise floor.

    ``center_hz``/``notch_hz`` suppress the LO leakage (DC spur) which would
    otherwise look like a real carrier at the centre of *every* step.  The
    notch is only applied to the detection copy, the returned peak levels use
    the original PSD.
    """
    freqs = np.asarray(freqs, dtype=np.float64)
    psd = np.asarray(psd, dtype=np.float64)
    if freqs.size < 3 or psd.size != freqs.size:
        return PeakResult([], float("nan"), float(threshold_db))

    work = psd.copy()
    if center_hz is not None and notch_hz > 0:
        notch = np.abs(freqs - float(center_hz)) <= float(notch_hz)
        outside = ~notch
        if notch.any() and outside.any():
            work[notch] = float(np.median(work[outside]))

    noise_floor = float(np.median(work))
    if not np.isfinite(noise_floor):
        return PeakResult([], noise_floor, float(threshold_db))

    smooth = median_filter_1d(work, max(1, int(smooth_bins)))
    diff = smooth - noise_floor
    enter = diff >= float(threshold_db)
    exit_ = diff >= max(1.5, float(threshold_db) * 0.45)
    if not enter.any():
        return PeakResult([], noise_floor, float(threshold_db))

    low_work = close_gaps(exit_, max_gap_bins) if max_gap_bins > 0 else exit_
    bin_hz = float(abs(freqs[1] - freqs[0]))
    if classifier is None:
        classifier = SignalClassifier()

    peaks: list[Detection] = []
    for run_start, run_end in runs(low_work):
        if run_end - run_start + 1 < max(1, int(min_bins)):
            continue
        if not enter[run_start:run_end + 1].any():
            continue
        # Drop border bins added by binary closing that are not really above
        # the exit threshold.
        valid = np.flatnonzero(
            exit_[run_start:run_end + 1] | enter[run_start:run_end + 1]
        )
        if valid.size == 0:
            continue
        start = run_start + int(valid[0])
        end = run_start + int(valid[-1])
        if end - start + 1 < max(1, int(min_bins)):
            continue
        region_diff = diff[start:end + 1]
        peak_local = int(np.argmax(region_diff))
        peak_idx = start + peak_local
        peak_snr = float(region_diff[peak_local])
        if peak_snr < float(threshold_db):
            continue
        weights = np.clip(
            np.power(10.0, region_diff / 10.0) - 1.0, 0.0, None
        )
        if weights.sum() > 0:
            rf = freqs[start:end + 1]
            peak_freq = float(np.sum(rf * weights) / np.sum(weights))
        else:
            peak_freq = float(freqs[peak_idx])
        bw = max(bin_hz, float(end - start + 1) * bin_hz)
        positive = region_diff[region_diff > 0]
        mean_snr = float(np.mean(positive)) if positive.size else peak_snr
        detection = Detection(
            freq_hz=peak_freq,
            bw_hz=bw,
            peak_db=float(psd[peak_idx]),
            snr_db=peak_snr,
            mean_snr_db=mean_snr,
            bin_start=start,
            bin_end=end,
            bin_hz=bin_hz,
            region_db=work[start:end + 1].copy(),
            baseline_db=np.full(
                end - start + 1, noise_floor, dtype=np.float64
            ),
        )
        try:
            classifier.apply(detection)
        except Exception:
            # Classification must never abort a scan.
            pass
        peaks.append(detection)

    peaks.sort(key=lambda item: item.freq_hz)
    return PeakResult(peaks, noise_floor, float(threshold_db))


def decimate_mean(values: np.ndarray, target: int) -> np.ndarray:
    """Average neighbouring bins down to at most ``target`` points.

    Keeps per-step JSON small while preserving narrow peaks reasonably well
    (the full-resolution peak list is stored separately).

    The segmented mean is done with ``np.add.reduceat``: one C call instead of
    a Python loop over hundreds of slices.  This function runs for every
    spectrum snapshot and every scan step, so the loop version was visible in
    profiles.
    """
    values = np.asarray(values, dtype=np.float64)
    target = max(1, int(target))
    if values.size <= target:
        return values.copy()
    edges = np.linspace(0, values.size, target + 1).astype(np.int64)
    edges[-1] = values.size
    starts = edges[:-1]
    counts = np.diff(edges)
    sums = np.add.reduceat(values, starts)
    return sums / np.maximum(counts, 1)
