"""Software VFO + real demodulation.

The local oscillator is never moved by the VFO.  The selected channel is
mixed down in software, low-pass filtered, decimated, demodulated and finally
sent to the audio sink.  That is why tuning the VFO does not invalidate the
background and why wobble is smooth.
"""
from __future__ import annotations

import numpy as np
from scipy import signal

from ..model import VFOConfig


class Demodulator:
    def __init__(self) -> None:
        self._t = 0.0
        self._audio_t = 0.0
        self._design_key: tuple | None = None
        self._ddc_sos: np.ndarray | None = None
        self._ddc_zi: np.ndarray | None = None
        self._audio_sos: np.ndarray | None = None
        self._audio_zi: np.ndarray | None = None
        self._ddc_decim = 1
        self._audio_decim = 1
        self._rate = 1.0
        self._audio_rate = 1.0
        self._bw = 10e3

    def reset(self) -> None:
        self._t = 0.0
        self._audio_t = 0.0
        self._design_key = None
        self._ddc_sos = None
        self._ddc_zi = None
        self._audio_sos = None
        self._audio_zi = None

    def _design(self, mode: str, bw_hz: float, fs: float) -> None:
        mode = mode.upper()
        bw = float(np.clip(bw_hz, 300.0, 0.9 * fs))
        # Keep enough bandwidth and enough output rate to avoid aliasing.
        target = max(4.0 * bw, 64_000.0)
        ddc_decim = max(1, int(fs // target))
        rate = fs / ddc_decim

        if mode in ("SSB", "CW"):
            cutoff = bw
        else:
            cutoff = bw / 2.0
        cutoff = float(np.clip(cutoff, 100.0, 0.45 * rate))

        self._ddc_sos = signal.butter(
            4, cutoff / (fs / 2.0), btype="low", output="sos"
        )
        self._ddc_zi = np.zeros((self._ddc_sos.shape[0], 2), dtype=np.complex128)
        self._ddc_decim = ddc_decim
        self._rate = rate

        audio_cut = {
            "AM": 4500.0,
            "FM": 15000.0,
            "SSB": 3400.0,
            "CW": 1400.0,
        }.get(mode, 4500.0)
        audio_cut = float(np.clip(audio_cut, 200.0, 0.45 * rate))
        self._audio_sos = signal.butter(
            4, audio_cut / (rate / 2.0), btype="low", output="sos"
        )
        self._audio_zi = np.zeros((self._audio_sos.shape[0], 2), dtype=np.float64)

        audio_decim = max(1, int(round(rate / 64_000.0)))
        # Do not decimate below roughly 32 kHz: some sound cards dislike it and
        # SSB/CW benefit from the extra margin.
        while audio_decim > 1 and rate / audio_decim < 32_000.0:
            audio_decim -= 1
        self._audio_decim = audio_decim
        self._audio_rate = rate / audio_decim
        self._bw = bw
        self._design_key = (mode, round(bw, 3), round(fs, 3))

    @staticmethod
    def _normalize(audio: np.ndarray, target: float = 0.8,
                   max_gain: float = 25.0) -> np.ndarray:
        if audio.size == 0:
            return audio
        peak = float(np.percentile(np.abs(audio), 99.0))
        if not np.isfinite(peak) or peak <= 1e-12:
            return audio
        gain = min(max_gain, target / peak)
        return audio * gain

    def process(self, iq: np.ndarray, fs: float, center_freq: float,
                cfg: VFOConfig) -> tuple[np.ndarray, float, float]:
        iq = np.asarray(iq, dtype=np.complex128).ravel()
        if iq.size < 8:
            return np.empty(0, dtype=np.float32), self._audio_rate, -120.0
        mode = (cfg.mode or "AM").upper()
        bw = float(cfg.bandwidth_hz)
        key = (mode, round(bw, 3), round(float(fs), 3))
        if key != self._design_key:
            self._design(mode, bw, fs)

        n = iq.size
        t = self._t + np.arange(n, dtype=np.float64) / fs
        self._t += n / fs

        # Software mixing of the VFO channel to 0 Hz.
        mixed = iq * np.exp(-2j * np.pi * float(cfg.offset_hz) * t)
        filtered, self._ddc_zi = signal.sosfilt(
            self._ddc_sos, mixed, zi=self._ddc_zi
        )
        baseband = filtered[:: self._ddc_decim]
        rate = self._rate
        if baseband.size < 4:
            return np.empty(0, dtype=np.float32), self._audio_rate, -120.0

        level_db = float(20.0 * np.log10(np.sqrt(np.mean(np.abs(baseband) ** 2)) + 1e-12))
        empty = np.zeros(max(1, baseband.size // self._audio_decim),
                         dtype=np.float32)
        if not cfg.active or level_db < float(cfg.squelch_db):
            return empty, self._audio_rate, level_db

        if mode == "AM":
            audio = np.abs(baseband)
            audio = audio - np.mean(audio)
        elif mode == "FM":
            disc = np.angle(baseband[1:] * np.conj(baseband[:-1]))
            audio = disc * (rate / (2.0 * np.pi))
            audio = audio / max(1000.0, bw / 2.0)
        elif mode == "SSB":
            audio = np.real(baseband)
            audio = audio - np.mean(audio)
        elif mode == "CW":
            t_audio = self._audio_t + np.arange(baseband.size, dtype=np.float64) / rate
            self._audio_t += baseband.size / rate
            audio = np.real(baseband * np.exp(2j * np.pi * 700.0 * t_audio))
            audio = audio - np.mean(audio)
        else:
            audio = np.abs(baseband)
            audio = audio - np.mean(audio)

        audio = np.asarray(audio, dtype=np.float64)
        if audio.size:
            audio, self._audio_zi = signal.sosfilt(
                self._audio_sos, audio, zi=self._audio_zi
            )
        if self._audio_decim > 1:
            audio = audio[:: self._audio_decim]

        if mode in ("AM", "SSB", "CW"):
            audio = self._normalize(audio, target=0.8, max_gain=30.0)
        else:
            audio = np.clip(audio * 1.8, -1.2, 1.2)
        audio = np.clip(audio * float(cfg.volume), -1.0, 1.0)
        return audio.astype(np.float32, copy=False), self._audio_rate, level_db
