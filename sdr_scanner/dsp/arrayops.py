# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Small 1-D array helpers that replace ``scipy.ndimage`` at startup.

Importing ``scipy.ndimage`` costs about 235 ms and ``scipy.signal`` about
528 ms.  The application only used them for three things on **one-dimensional**
arrays: a 3-point median filter, binary closing with a small box, and run
labelling.  All three are a few lines of NumPy, so the startup import graph no
longer needs SciPy at all (audio filters load it lazily, see ``dsp.demod``).
"""
from __future__ import annotations

import numpy as np


def median_filter_1d(values: np.ndarray, size: int = 3) -> np.ndarray:
    """Median filter with edge padding, for small odd window sizes."""
    data = np.asarray(values, dtype=np.float64)
    size = max(1, int(size))
    if size <= 1 or data.size == 0:
        return data.copy()
    if size % 2 == 0:
        size += 1
    if data.size < size:
        return data.copy()
    pad = size // 2
    padded = np.pad(data, pad, mode="edge")
    if size == 3:
        # Median of three without sorting: max(min(a,b), min(max(a,b), c)).
        left = padded[:-2]
        middle = padded[1:-1]
        right = padded[2:]
        return np.maximum(
            np.minimum(left, middle),
            np.minimum(np.maximum(left, middle), right),
        )
    windows = np.lib.stride_tricks.sliding_window_view(padded, size)
    return np.median(windows, axis=-1)


def close_gaps(mask: np.ndarray, gap: int = 1) -> np.ndarray:
    """Bridge ``False`` gaps of at most ``gap`` samples between two runs.

    This is what the callers used ``scipy.ndimage.binary_closing`` for, but
    without its edge erosion: only the gaps are filled, the run ends stay.
    """
    data = np.asarray(mask, dtype=bool)
    gap = max(0, int(gap))
    if gap <= 0 or data.size < 3:
        return data.copy()
    regions = runs(data)
    if len(regions) < 2:
        return data.copy()
    out = data.copy()
    for (_, left_end), (right_start, _) in zip(regions, regions[1:]):
        if 0 < right_start - left_end - 1 <= gap:
            out[left_end + 1:right_start] = True
    return out


def runs(mask: np.ndarray) -> list[tuple[int, int]]:
    """Contiguous ``True`` runs as inclusive ``(start, end)`` pairs."""
    data = np.asarray(mask, dtype=bool)
    if data.size == 0 or not data.any():
        return []
    edges = np.diff(data.astype(np.int8))
    starts = list(np.flatnonzero(edges == 1) + 1)
    ends = list(np.flatnonzero(edges == -1))
    if data[0]:
        starts.insert(0, 0)
    if data[-1]:
        ends.append(data.size - 1)
    return list(zip(starts, ends))[: len(starts)]

def get_window(name: str, size: int, fftbins: bool = True) -> np.ndarray:
    """Common window functions without importing scipy.signal.

    ``fftbins=True`` gives the periodic (DFT-even) window, matching
    ``scipy.signal.get_window``.  Exotic names fall back to SciPy.
    """
    n = max(1, int(size))
    name = str(name or "hann").lower()
    if n == 1:
        return np.ones(1, dtype=np.float64)
    k = np.arange(n, dtype=np.float64)
    denom = float(n) if fftbins else float(max(1, n - 1))
    if name in ("hann", "hanning"):
        return 0.5 - 0.5 * np.cos(2.0 * np.pi * k / denom)
    if name == "hamming":
        return 0.54 - 0.46 * np.cos(2.0 * np.pi * k / denom)
    if name == "blackman":
        return (0.42 - 0.5 * np.cos(2.0 * np.pi * k / denom)
                + 0.08 * np.cos(4.0 * np.pi * k / denom))
    if name in ("boxcar", "rect", "rectangular", "ones"):
        return np.ones(n, dtype=np.float64)
    from scipy.signal import get_window as _scipy_window

    return np.asarray(_scipy_window(name, n, fftbins=fftbins), dtype=np.float64)
