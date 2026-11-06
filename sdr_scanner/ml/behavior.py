# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Behavioural features measured over a long IQ block (0.5–2 s).

Spectral shape tells *what* a signal looks like; behaviour tells *how it
lives*.  A frequency-hopping remote link jumps between dozens of channels
hundreds of times per second, a Wi-Fi access point stays on one channel, and
an analog FPV camera keeps a steady carrier with a 15.625 kHz line rate.
Those are much harder to fake than a plateau in a 20 ms spectrum.

Everything here is relative and works at any sample rate, although hop rate
and channel count are only meaningful when the block is wide enough to hold
several channels (roughly 20 MHz or more).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

DEFAULT_FRAME_S = 0.00025      # 0.25 ms
HOP_THRESHOLD_HZ = 2.0e6       # a jump this large is a different channel
ACTIVE_FACTOR = 4.0            # 6 dB above the quiet tenth percentile
BLOCK_FRAMES = 2000            # limit peak memory while FFT-ing


@dataclass(frozen=True)
class Behavior:
    duty: float
    burst_rate_hz: float
    burst_interval_cv: float
    hop_rate_hz: float
    channels: int
    occupied: float
    sync_khz: float
    sync_strength: float
    frames: int
    snr_db: float = 99.0
    fm_sync_khz: float = 0.0
    fm_sync_strength: float = 0.0

    def to_dict(self) -> dict[str, float | int]:
        return {
            "duty": round(self.duty, 3),
            "burst_rate_hz": round(self.burst_rate_hz, 1),
            "burst_interval_cv": round(self.burst_interval_cv, 3),
            "hop_rate_hz": round(self.hop_rate_hz, 1),
            "channels": int(self.channels),
            "occupied": round(self.occupied, 3),
            "sync_khz": round(self.sync_khz, 2),
            "sync_strength": round(self.sync_strength, 2),
            "frames": int(self.frames),
            "snr_db": round(self.snr_db, 2),
            "fm_sync_khz": round(self.fm_sync_khz, 2),
            "fm_sync_strength": round(self.fm_sync_strength, 2),
        }


def _frame_series(
    iq: np.ndarray, frame: int,
) -> tuple[np.ndarray, int]:
    frames = iq.size // frame
    return iq[: frames * frame].reshape(frames, frame), frames


def _peaks(
    block: np.ndarray, freqs: np.ndarray, window: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    # HackRF has a strong DC spur at the tuned centre.  Remove each frame's
    # mean before the FFT so the spur does not look like a permanent carrier.
    centred = block.astype(np.complex64)
    centred = centred - centred.mean(axis=1, keepdims=True)
    spectrum = np.fft.fftshift(
        np.abs(np.fft.fft(centred * window, axis=1)),
        axes=1,
    )
    return freqs[np.argmax(spectrum, axis=1)], spectrum


def analyze(
    iq: np.ndarray,
    sample_rate: float,
    *,
    frame_s: float = DEFAULT_FRAME_S,
    max_seconds: float = 2.0,
) -> Behavior:
    """Measure duty, burst rhythm, hopping and analog line sync."""
    x = np.asarray(iq)
    frame = max(64, int(round(float(sample_rate) * float(frame_s))))
    limit = int(float(max_seconds) * float(sample_rate))
    if limit and x.size > limit:
        x = x[:limit]
    if x.size < frame * 16:
        return Behavior(0.0, 0.0, 0.0, 0.0, 0, 0.0, 0.0, 0.0, 0)

    frames = x.size // frame
    x = x[:frames * frame]
    power = np.empty(frames, dtype=np.float64)
    for start in range(0, frames, BLOCK_FRAMES):
        block = x[start * frame:(start + BLOCK_FRAMES) * frame]
        block = block.reshape(-1, frame)
        block = block - block.mean(axis=1, keepdims=True)
        power[start:start + block.shape[0]] = (
            np.abs(block) ** 2
        ).mean(axis=1)

    quiet = float(np.percentile(power, 10.0))
    loud = float(np.percentile(power, 90.0))
    if loud <= quiet * ACTIVE_FACTOR:
        # A steady carrier has no quiet frames to compare against.
        active = np.ones(frames, dtype=bool)
    else:
        active = power > max(1e-20, quiet * ACTIVE_FACTOR)
    duty = float(active.mean())
    seconds = frames * frame / float(sample_rate)

    rising = np.flatnonzero(active[1:] & ~active[:-1]) + 1
    burst_rate = float(rising.size) / max(1e-9, seconds)
    if rising.size >= 3:
        intervals = np.diff(rising) * frame / float(sample_rate)
        mean = float(intervals.mean())
        cv = float(intervals.std() / mean) if mean > 0 else 0.0
    else:
        cv = 0.0

    window = np.hanning(frame).astype(np.float32)
    freqs = np.fft.fftshift(
        np.fft.fftfreq(frame, 1.0 / float(sample_rate))
    ).astype(np.float64)
    peaks = np.empty(frames, dtype=np.float64)
    psd = np.zeros(frame, dtype=np.float64)
    for start in range(0, frames, BLOCK_FRAMES):
        block = x[start * frame:(start + BLOCK_FRAMES) * frame]
        block = block.reshape(-1, frame)
        block_peaks, spectrum = _peaks(block, freqs, window)
        peaks[start:start + block.shape[0]] = block_peaks
        psd += (spectrum ** 2).mean(axis=0)
    psd /= max(1, (frames + BLOCK_FRAMES - 1) // BLOCK_FRAMES)
    psd_db = 10.0 * np.log10(psd + 1e-20)
    floor_db = float(np.percentile(psd_db, 20.0))
    occupied = float(np.mean(psd_db > floor_db + 6.0))
    snr_db = float(psd_db.max() - floor_db)
    peak_bin = int(np.argmax(psd_db))
    centre_spur = abs(float(freqs[peak_bin])) < 150e3
    if snr_db < 7.0 or (
        centre_spur and occupied < 0.005 and duty > 0.95
    ):
        # Only noise or the residual LO spur at the tuned centre: a steady
        # tone or a real link always lifts a wider part of the spectrum.
        # Without this guard a quiet channel looked like 100% duty because
        # its frame power was flat.
        return Behavior(
            duty=0.0, burst_rate_hz=0.0, burst_interval_cv=0.0,
            hop_rate_hz=0.0, channels=0, occupied=0.0,
            sync_khz=0.0, sync_strength=0.0, frames=frames, snr_db=snr_db,
        )

    active_peaks = peaks[active]
    if active_peaks.size >= 4:
        hop_rate = float(
            np.mean(np.abs(np.diff(active_peaks)) > HOP_THRESHOLD_HZ)
        ) * (float(sample_rate) / frame)
        channels = int(np.unique(
            np.round(active_peaks / 1e6).astype(np.int64)
        ).size)
    else:
        hop_rate = 0.0
        channels = 0

    # Analog video keeps a line-rate line in the envelope.  It must be
    # sampled much finer than the frame used for hopping: one PAL line is
    # 64 µs, so the envelope is reduced to ~200 kHz first.
    step = max(1, int(round(float(sample_rate) / 200e3)))
    count = x.size // step
    envelope = np.abs(x[:count * step]).reshape(count, step).mean(axis=1)
    envelope = envelope.astype(np.float64)
    envelope -= envelope.mean()
    env_spec = np.abs(np.fft.rfft(envelope * np.hanning(envelope.size)))
    env_freqs = np.fft.rfftfreq(envelope.size, step / float(sample_rate))
    band = (env_freqs >= 5e3) & (env_freqs <= 30e3)
    if band.any():
        local = env_spec[band]
        index = int(np.argmax(local))
        sync_khz = float(env_freqs[band][index]) / 1e3
        sync_strength = float(local[index] / (np.median(local) + 1e-12))
    else:
        sync_khz = 0.0
        sync_strength = 0.0

    # Analog FPV video is usually frequency-modulated, so the envelope stays
    # flat.  Discriminate the IQ and look for the same line rate in the
    # instantaneous frequency.  A 8M-sample cap keeps the phase unwrap
    # bounded on 120 MS/s dataset files.
    fm_sync_khz = 0.0
    fm_sync_strength = 0.0
    sync_len = min(x.size, int(float(sample_rate) * 0.5), 8_000_000)
    if sync_len > frame * 16:
        y = x[:sync_len]
        phase = np.unwrap(np.angle(y))
        fm = np.diff(phase).astype(np.float64)
        fm *= float(sample_rate) / (2.0 * np.pi)
        step_fm = max(1, int(round(float(sample_rate) / 200e3)))
        count_fm = fm.size // step_fm
        if count_fm >= 64:
            series = fm[:count_fm * step_fm].reshape(count_fm, step_fm).mean(axis=1)
            series = series - series.mean()
            fm_spec = np.abs(np.fft.rfft(series * np.hanning(series.size)))
            fm_freqs = np.fft.rfftfreq(count_fm, step_fm / float(sample_rate))
            fm_band = (fm_freqs >= 5e3) & (fm_freqs <= 30e3)
            if fm_band.any():
                local = fm_spec[fm_band]
                index = int(np.argmax(local))
                fm_sync_khz = float(fm_freqs[fm_band][index]) / 1e3
                fm_sync_strength = float(
                    local[index] / (np.median(local) + 1e-12)
                )

    return Behavior(
        duty=duty,
        burst_rate_hz=burst_rate,
        burst_interval_cv=cv,
        hop_rate_hz=hop_rate,
        channels=channels,
        occupied=occupied,
        sync_khz=sync_khz,
        sync_strength=sync_strength,
        frames=frames,
        snr_db=snr_db,
        fm_sync_khz=fm_sync_khz,
        fm_sync_strength=fm_sync_strength,
    )


__all__ = ["Behavior", "analyze"]
