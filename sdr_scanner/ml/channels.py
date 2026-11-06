# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Channel map for frequency-hopping signals.

A 20 MHz capture can hold dozens of channels.  This module turns the
per-frame peak frequency into a channel map: how long the transmitter stayed
on each channel, how often it hopped and how the dwell times are distributed.
It is deliberately separate from :mod:`behavior`, which measures duty and
burst rhythm on the same IQ but does not care where the energy sits.

The map is only meaningful on a wide capture.  At Pluto's 6.144 MS/s it is
computed for diagnostics, but the UI must say that hops and channel counts are
not trustworthy there.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from .behavior import (
    ACTIVE_FACTOR,
    BLOCK_FRAMES,
    DEFAULT_FRAME_S,
    _peaks,
)

DEFAULT_BIN_HZ = 1.0e6
MIN_CHANNEL_SHARE = 0.005
DWELL_EDGES_MS = (0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0)


@dataclass(frozen=True)
class ChannelInfo:
    center_hz: float
    share: float
    dwell_ms: float
    hits: int


@dataclass(frozen=True)
class ChannelMap:
    channels: tuple[ChannelInfo, ...]
    active_share: float
    hop_rate_hz: float
    hop_period_ms: float
    hop_period_cv: float
    dwell_ms: float
    dwells_ms: tuple[float, ...]
    hop_intervals_ms: tuple[float, ...]
    frames: int
    duration_s: float
    wide_share: float = 0.0

    def to_dict(self) -> dict:
        return {
            "channels": [
                {
                    "center_hz": round(item.center_hz, 1),
                    "share": round(item.share, 3),
                    "dwell_ms": round(item.dwell_ms, 3),
                    "hits": item.hits,
                }
                for item in self.channels
            ],
            "active_share": round(self.active_share, 3),
            "hop_rate_hz": round(self.hop_rate_hz, 1),
            "hop_period_ms": round(self.hop_period_ms, 3),
            "hop_period_cv": round(self.hop_period_cv, 3),
            "dwell_ms": round(self.dwell_ms, 3),
            "dwells_ms": [round(value, 3) for value in self.dwells_ms],
            "hop_intervals_ms": [
                round(value, 3) for value in self.hop_intervals_ms
            ],
            "frames": self.frames,
            "duration_s": round(self.duration_s, 3),
            "wide_share": round(self.wide_share, 3),
        }

    def top(self, count: int = 3) -> tuple[ChannelInfo, ...]:
        return tuple(sorted(
            self.channels, key=lambda item: item.share, reverse=True,
        )[:count])


def _empty(
    frames: int = 0, duration: float = 0.0, wide_share: float = 0.0,
) -> ChannelMap:
    return ChannelMap(
        channels=(), active_share=0.0, hop_rate_hz=0.0, hop_period_ms=0.0,
        hop_period_cv=0.0, dwell_ms=0.0, dwells_ms=(), hop_intervals_ms=(),
        frames=frames, duration_s=duration, wide_share=wide_share,
    )


def _histogram(values: tuple[float, ...]) -> list[tuple[str, int]]:
    edges = DWELL_EDGES_MS
    counts = [0] * (len(edges) + 1)
    for value in values:
        index = len(edges)
        for i, edge in enumerate(edges):
            if value <= edge:
                index = i
                break
        counts[index] += 1
    labels = [
        f"≤{edges[0]:g} мс",
        *[f"{edges[i]:g}–{edges[i + 1]:g} мс" for i in range(len(edges) - 1)],
        f">{edges[-1]:g} мс",
    ]
    return list(zip(labels, counts))


def analyze_channels(
    iq: np.ndarray,
    sample_rate: float,
    *,
    center_hz: float = 0.0,
    frame_s: float = DEFAULT_FRAME_S,
    max_seconds: float = 2.0,
    bin_hz: float = DEFAULT_BIN_HZ,
    min_share: float = MIN_CHANNEL_SHARE,
    max_width_hz: float = 15.0e6,
) -> ChannelMap:
    """Build a channel/dwell map from per-frame peak frequencies."""
    x = np.asarray(iq)
    frame = max(64, int(round(float(sample_rate) * float(frame_s))))
    limit = int(float(max_seconds) * float(sample_rate))
    if limit and x.size > limit:
        x = x[:limit]
    if x.size < frame * 16:
        return _empty()

    frames = x.size // frame
    power = np.empty(frames, dtype=np.float64)
    for start in range(0, frames, BLOCK_FRAMES):
        block = x[start * frame:(start + BLOCK_FRAMES) * frame]
        block = block.reshape(-1, frame)
        block = block - block.mean(axis=1, keepdims=True)
        power[start:start + block.shape[0]] = (np.abs(block) ** 2).mean(axis=1)

    quiet = float(np.percentile(power, 10.0))
    loud = float(np.percentile(power, 90.0))
    if loud <= quiet * ACTIVE_FACTOR:
        active = np.ones(frames, dtype=bool)
    else:
        active = power > max(1e-20, quiet * ACTIVE_FACTOR)
    active_share = float(active.mean())
    if not bool(active.any()):
        return _empty(frames, frames * frame / float(sample_rate))

    window = np.hanning(frame).astype(np.float32)
    freqs = np.fft.fftshift(
        np.fft.fftfreq(frame, 1.0 / float(sample_rate))
    ).astype(np.float64)
    peaks = np.empty(frames, dtype=np.float64)
    widths = np.empty(frames, dtype=np.float64)
    resolution = float(sample_rate) / frame
    for start in range(0, frames, BLOCK_FRAMES):
        block = x[start * frame:(start + BLOCK_FRAMES) * frame]
        block = block.reshape(-1, frame)
        block_peaks, spectrum = _peaks(block, freqs, window)
        count = block.shape[0]
        peaks[start:start + count] = block_peaks
        row_max = spectrum.max(axis=1, keepdims=True)
        mask = spectrum >= row_max * 0.5
        first = np.argmax(mask, axis=1)
        last = spectrum.shape[1] - 1 - np.argmax(mask[:, ::-1], axis=1)
        widths[start:start + count] = (last - first) * resolution
    peaks = peaks + float(center_hz)

    # A Wi-Fi or video link is wide: its peak wanders across subcarriers and
    # would fake dozens of channels.  Keep the channel map for narrow bursts,
    # where a frequency-hopping transmitter really sits on one carrier.
    narrow = active & (widths <= float(max_width_hz))
    wide_share = 1.0 - float(narrow.sum()) / max(1, int(active.sum()))
    if int(narrow.sum()) < max(8, int(0.05 * int(active.sum()))):
        return _empty(
            frames, frames * frame / float(sample_rate), wide_share,
        )

    # Round to channel bins and keep the busy ones.
    bins = np.round(peaks[narrow] / float(bin_hz)) * float(bin_hz)
    if bins.size == 0:
        return _empty(frames, frames * frame / float(sample_rate))
    values, counts = np.unique(bins, return_counts=True)
    keep = counts >= max(2, int(min_share * bins.size))
    values, counts = values[keep], counts[keep]
    if values.size == 0:
        return _empty(frames, frames * frame / float(sample_rate))
    kept = set(float(value) for value in values)

    # Group consecutive active frames on the same channel into runs.  An
    # inactive gap always starts a new run, even on the same channel.
    runs: list[list[float | int]] = []
    run_channel = None
    run_start = 0
    last_index = -2
    for index in np.flatnonzero(narrow):
        channel = float(np.round(peaks[index] / bin_hz) * bin_hz)
        if channel not in kept:
            channel = float(values[np.argmin(np.abs(values - channel))])
        if (run_channel is None or channel != run_channel
                or int(index) != last_index + 1):
            if run_channel is not None:
                runs.append([run_channel, run_start, last_index])
            run_channel = channel
            run_start = int(index)
        last_index = int(index)
    if run_channel is not None:
        runs.append([run_channel, run_start, last_index])

    if not runs:
        return _empty(frames, frames * frame / float(sample_rate))

    frame_ms = 1000.0 * frame / float(sample_rate)
    dwells = tuple((int(end) - int(start) + 1) * frame_ms for _, start, end in runs)
    starts = tuple(int(start) * frame / float(sample_rate) * 1000.0
                   for _, start, _ in runs)
    hop_intervals = []
    hops = 0
    for index in range(1, len(runs)):
        if float(runs[index][0]) != float(runs[index - 1][0]):
            hops += 1
            hop_intervals.append(starts[index] - starts[index - 1])
    duration_s = frames * frame / float(sample_rate)
    hop_rate = hops / max(duration_s, 1e-9)
    if hop_intervals:
        hop_period = float(np.median(hop_intervals))
        mean = float(np.mean(hop_intervals))
        cv = float(np.std(hop_intervals) / mean) if mean > 0 else 0.0
    else:
        hop_period = 0.0
        cv = 0.0

    total_active = max(1, int(narrow.sum()))
    dwell_by_channel: dict[float, list[float]] = {}
    for channel, start, end in runs:
        length = int(end) - int(start) + 1
        dwell_by_channel.setdefault(float(channel), []).append(
            length * frame_ms
        )
    channels = []
    for channel in np.sort(values):
        key = float(channel)
        lengths = dwell_by_channel.get(key, [])
        hits = len(lengths)
        share = sum(lengths) / max(1e-9, total_active * frame_ms)
        if hits == 0:
            continue
        channels.append(ChannelInfo(
            center_hz=key,
            share=float(share),
            dwell_ms=float(np.median(lengths)),
            hits=hits,
        ))
    channels.sort(key=lambda item: item.center_hz)
    return ChannelMap(
        channels=tuple(channels),
        active_share=active_share,
        hop_rate_hz=float(hop_rate),
        hop_period_ms=float(hop_period),
        hop_period_cv=float(cv),
        dwell_ms=float(np.median(dwells)),
        dwells_ms=dwells,
        hop_intervals_ms=tuple(hop_intervals),
        frames=frames,
        duration_s=float(duration_s),
        wide_share=float(wide_share),
    )


def dwell_histogram(channel_map: ChannelMap) -> list[tuple[str, int]]:
    return _histogram(channel_map.dwells_ms)


def fingerprint(channel_map: ChannelMap, behavior=None) -> str:
    """A cautious comparison with the profiles measured from Tampere.

    The Tampere DJI links used 41-74 channels, 700-1830 hops/s and duty
    0.78-0.89.  Wi-Fi drones and access points had far fewer channels or
    much longer dwells.  These are coarse guards, not a classifier.
    """
    if not channel_map.channels:
        if channel_map.wide_share >= 0.5:
            return ("широкополосный сигнал — похоже на Wi-Fi или цифровое "
                    "видео; карта каналов для него не применима")
        return "карта каналов недоступна"
    if channel_map.wide_share >= 0.35:
        return ("широкополосный сигнал — похоже на Wi-Fi или цифровое видео; "
                "карта каналов неполная")
    count = len(channel_map.channels)
    hops = channel_map.hop_rate_hz
    dwell = channel_map.dwell_ms
    duty = float(behavior.duty) if behavior is not None else channel_map.active_share
    if count >= 20 and hops >= 500 and dwell <= 4.0 and duty >= 0.60:
        return ("профиль ближе к широкополосному FHSS-видеолинку "
                "(DJI-подобный по датасету Tampere)")
    if count <= 8 and hops < 200:
        return "профиль ближе к узкому постоянному каналу или аналоговому видео"
    if hops >= 300 or dwell <= 5.0:
        return ("профиль ближе к Wi-Fi/точке доступа или пульту: "
                "много коротких посылок, но мало каналов")
    return "профиль неоднозначный: данных для уверенного сравнения мало"


__all__ = [
    "ChannelInfo",
    "ChannelMap",
    "analyze_channels",
    "dwell_histogram",
    "fingerprint",
]
