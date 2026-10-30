"""Windowed spectrum estimation in dBFS.

The simulator and the Pluto both deliver complex baseband.  A full-scale
complex tone is calibrated to 0 dBFS, which is good enough for relative
detection work and is clearly documented in the UI.  It is *not* dBm.
"""
from __future__ import annotations

import numpy as np
from scipy import signal


class SpectrumAnalyzer:
    def __init__(self, nfft: int = 2048, window: str = "hann",
                 max_segments: int = 32) -> None:
        self.nfft = max(256, int(nfft))
        self.window_name = window
        self.max_segments = max(1, int(max_segments))
        self._win = signal.get_window(window, self.nfft, fftbins=True).astype(np.float64)
        self._scale = float(np.sum(self._win)) ** 2

    def compute(self, iq: np.ndarray, sample_rate: float,
                center_freq: float) -> tuple[np.ndarray, np.ndarray]:
        iq = np.asarray(iq, dtype=np.complex128).ravel()
        nfft = self.nfft
        nseg = iq.size // nfft
        if nseg < 1:
            segs = np.zeros((1, nfft), dtype=np.complex128)
            segs[0, : iq.size] = iq
            nseg = 1
        else:
            segs = iq[: nseg * nfft].reshape(nseg, nfft)
        if nseg > self.max_segments:
            # Use the most recent segments, but spread them over the block.
            idx = np.linspace(nseg - self.max_segments, nseg - 1,
                              self.max_segments).astype(int)
            segs = segs[idx]
            nseg = self.max_segments

        spec = np.fft.fftshift(
            np.fft.fft(segs * self._win[None, :], axis=1), axes=1
        )
        power = np.mean(np.abs(spec) ** 2, axis=0) / self._scale
        psd = 10.0 * np.log10(power + 1e-20)
        freqs = np.fft.fftshift(
            np.fft.fftfreq(nfft, d=1.0 / float(sample_rate))
        ) + float(center_freq)
        return freqs, psd.astype(np.float32)

    def bin_hz(self, sample_rate: float) -> float:
        return float(sample_rate) / self.nfft
