# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Windowed spectrum estimation in dBFS.

The simulator and the Pluto both deliver complex baseband.  A full-scale
complex tone is calibrated to 0 dBFS, which is good enough for relative
detection work and is clearly documented in the UI.  It is *not* dBm.
"""
from __future__ import annotations

import numpy as np

from .arrayops import get_window


class SpectrumAnalyzer:
    def __init__(self, nfft: int = 2048, window: str = "hann",
                 max_segments: int = 32) -> None:
        self.nfft = max(256, int(nfft))
        self.window_name = window
        self.max_segments = max(1, int(max_segments))
        self._win = get_window(window, self.nfft, fftbins=True).astype(np.float64)
        self._scale = float(np.sum(self._win)) ** 2

    def compute(self, iq: np.ndarray, sample_rate: float,
                center_freq: float) -> tuple[np.ndarray, np.ndarray]:
        iq = np.asarray(iq).ravel()
        nfft = self.nfft
        nseg = iq.size // nfft
        if nseg < 1:
            segs = np.zeros((1, nfft), dtype=np.complex128)
            segs[0, : iq.size] = iq[:nfft]
            nseg = 1
        else:
            if nseg > self.max_segments:
                # Use the most recent segments, but spread them over the block.
                idx = np.linspace(nseg - self.max_segments, nseg - 1,
                                  self.max_segments).astype(int)
            else:
                idx = np.arange(nseg)
            # Copy only the samples that are actually used.  Converting the
            # whole block to complex128 wasted megabytes per frame.
            base = idx * nfft
            offsets = np.arange(nfft)
            segs = np.asarray(iq[base[:, None] + offsets], dtype=np.complex128)
        # Window in place: segs is a fresh copy, so this avoids a second
        # block-sized allocation.
        segs *= self._win[None, :]

        spec = np.fft.fft(segs, axis=1)
        # real^2 + imag^2 instead of abs()**2: skips a square root over every
        # bin of every segment.
        power = np.mean(spec.real ** 2 + spec.imag ** 2, axis=0) / self._scale
        # Shift the 1-D result, not the 32 x nfft spectrum: the block-sized
        # copy cost more than the FFT itself.
        psd = np.fft.fftshift(10.0 * np.log10(power + 1e-20))
        freqs = np.fft.fftshift(
            np.fft.fftfreq(nfft, d=1.0 / float(sample_rate))
        ) + float(center_freq)
        return freqs, psd.astype(np.float32)

    def bin_hz(self, sample_rate: float) -> float:
        return float(sample_rate) / self.nfft
