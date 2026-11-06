# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Analog PAL/NTSC video decoder.

The app already detects the 15.625 kHz line rate.  This module goes one step
further: it FM-demodulates the IQ, finds line sync pulses, samples the active
part of every line and stacks the lines into a monochrome frame.

It is deliberately monochrome.  Colour subcarriers and PAL/NTSC colour
decoding are a later step; luminance is enough to see whether a link carries
a picture and to identify the source.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class VideoStandard:
    name: str
    line_hz: float
    lines: int
    active_lines: int
    pixels: int
    fps: float

    @property
    def line_s(self) -> float:
        return 1.0 / self.line_hz


PAL = VideoStandard("PAL", 15625.0, 625, 576, 768, 25.0)
NTSC = VideoStandard("NTSC", 15734.264, 525, 480, 640, 29.97)
STANDARDS = {"PAL": PAL, "NTSC": NTSC}


@dataclass(frozen=True)
class DecodedFrame:
    image: np.ndarray              # uint8, rows x pixels
    line_hz: float
    lines: int
    locked: bool
    standard: str
    frame_locked: bool = False


def _normalise(signal: np.ndarray) -> np.ndarray:
    signal = np.asarray(signal, dtype=np.float64)
    if signal.size == 0:
        return signal
    low = float(np.percentile(signal, 2.0))
    high = float(np.percentile(signal, 98.0))
    if high <= low:
        return np.zeros_like(signal)
    return np.clip((signal - low) / (high - low), 0.0, 1.0)


def demodulate(iq: np.ndarray, mode: str = "fm", invert: bool = False) -> np.ndarray:
    """Return a real video-like signal from complex IQ."""
    x = np.asarray(iq, dtype=np.complex64)
    if x.size < 64:
        return np.empty(0, dtype=np.float64)
    if mode.lower() == "am":
        video = np.abs(x).astype(np.float64)
    else:
        phase = np.unwrap(np.angle(x))
        video = np.diff(phase).astype(np.float64)
        if video.size:
            video = np.append(video, video[-1])
    video -= float(np.mean(video))
    if invert:
        video = -video
    return video


def _sync_positions(
    video: np.ndarray, rate: float, standard: VideoStandard,
) -> tuple[np.ndarray, float]:
    """Find line-sync leading edges and estimate the line period.

    The FM discriminator can invert the video, so both polarities are tried
    and the one with a regular line rhythm wins.  Looking only at the signal
    tails is ambiguous: active video can have deeper excursions than sync.
    """
    if video.size < int(rate * standard.line_s * 8):
        return np.empty(0, dtype=np.int64), standard.line_hz

    min_gap = max(4, int(rate * standard.line_s * 0.5))

    def candidate(signal: np.ndarray):
        median = float(np.median(signal))
        low = float(np.percentile(signal, 1.0))
        threshold = median - 0.65 * (median - low)
        below = signal < threshold
        starts = np.flatnonzero(below[1:] & ~below[:-1]) + 1
        positions: list[int] = []
        for start in starts:
            stop = min(signal.size - 1, start + max(2, int(rate * 2.5e-6)))
            index = int(start + np.argmin(signal[start:stop + 1]))
            if not positions or index - positions[-1] >= min_gap:
                positions.append(index)
        positions_arr = np.asarray(positions, dtype=np.int64)
        if positions_arr.size < 4:
            return positions_arr, standard.line_hz, 0.0
        diffs = np.diff(positions_arr) / float(rate)
        valid = diffs[(diffs > 0.8 * standard.line_s)
                      & (diffs < 1.2 * standard.line_s)]
        score = float(valid.size) / max(1, diffs.size)
        period = float(np.median(valid)) if valid.size >= 3 else standard.line_s
        return positions_arr, 1.0 / max(period, 1e-9), score

    normal = candidate(video)
    inverted = candidate(-video)
    if inverted[2] > normal[2] + 0.05:
        return inverted[0], inverted[1]
    if normal[2] > inverted[2] + 0.05:
        return normal[0], normal[1]
    # Similar rhythm: prefer the polarity with fewer false edges.
    if inverted[0].size < normal[0].size:
        return inverted[0], inverted[1]
    return normal[0], normal[1]


def decode_frame(
    iq: np.ndarray,
    sample_rate: float,
    standard: VideoStandard = PAL,
    *,
    mode: str = "fm",
    invert: bool = False,
    pixels: int | None = None,
    min_lines: int = 90,
) -> DecodedFrame | None:
    """Decode one (possibly partial) frame from a block of IQ."""
    video = demodulate(iq, mode=mode, invert=invert)
    if video.size == 0:
        return None
    positions, line_hz = _sync_positions(video, sample_rate, standard)
    if positions.size < min_lines:
        return None
    period = 1.0 / max(line_hz, 1e-9)
    # Keep sync pulses that actually fit the estimated rhythm.
    intervals = np.diff(positions) / float(sample_rate)
    keep = [int(positions[0])]
    for index in range(1, positions.size):
        if 0.8 * period <= intervals[index - 1] <= 1.2 * period:
            keep.append(int(positions[index]))
    positions = np.asarray(keep, dtype=np.int64)
    if positions.size < min_lines:
        return None

    # Fill short gaps on the line grid.  On a weak/noisy VTX the sync
    # detector misses individual lines; without this the frame has holes and
    # the picture rolls.
    period_samples = period * float(sample_rate)
    grid: list[float] = []
    for first, second in zip(positions[:-1], positions[1:]):
        steps = int(round((second - first) / period_samples))
        if 1 <= steps <= 6:
            grid.extend(first + index * period_samples
                        for index in range(steps))
        else:
            grid.append(float(first))
    grid.append(float(positions[-1]))
    positions = np.rint(grid).astype(np.int64)

    # Vertical sync / blanking appears as a gap in the line rhythm.  Split
    # there and keep the longest uninterrupted field/frame; this stops the
    # decoder from stacking the end of one frame onto the start of the next.
    runs: list[list[int]] = []
    current: list[int] = [int(positions[0])]
    gap_limit = 1.6 * period_samples
    for position in positions[1:]:
        if float(position - current[-1]) > gap_limit:
            runs.append(current)
            current = [int(position)]
        else:
            current.append(int(position))
    runs.append(current)
    best = max(runs, key=len)
    # Keep the split only when it really is a field/frame.  A short fragment
    # is more useful stacked with its neighbours than shown as a thin strip.
    if len(best) >= max(min_lines, int(standard.lines * 0.5)):
        positions = np.asarray(best, dtype=np.int64)
    frame_locked = len(best) >= int(standard.lines * 0.8)

    width = int(pixels or standard.pixels)
    # PAL/NTSC active video starts after sync + back porch (~17% of a line)
    # and lasts about 78% of the line.
    start_offset = 0.17 * period
    active = 0.78 * period
    lines: list[np.ndarray] = []
    for position in positions:
        start = (position / float(sample_rate)) + start_offset
        stop = start + active
        start_index = max(0, int(start * sample_rate))
        stop_index = min(video.size, int(stop * sample_rate))
        if stop_index - start_index < 2:
            continue
        segment = video[start_index:stop_index]
        # Interpolate inside the line only.  Using the full 2.4M-sample
        # capture as the interpolation axis for every line was the reason a
        # 20 MS/s frame took 15 seconds and froze the UI.
        lines.append(np.interp(
            np.linspace(0.0, segment.size - 1.0, width, endpoint=False),
            np.arange(segment.size, dtype=np.float64),
            segment,
        ))
    if len(lines) < min_lines:
        return None

    image = np.asarray(lines[-standard.lines:], dtype=np.float64)
    # Remove line-to-line DC steps, then stretch the visible range.
    image -= np.median(image, axis=1, keepdims=True)
    low = float(np.percentile(image, 2.0))
    high = float(np.percentile(image, 98.0))
    if high <= low:
        return None
    image = np.clip((image - low) / (high - low), 0.0, 1.0)
    if invert:
        image = 1.0 - image
    image = (image * 255.0).astype(np.uint8)
    locked = bool(
        abs(line_hz - standard.line_hz) / standard.line_hz < 0.03
    )
    return DecodedFrame(
        image=image,
        line_hz=line_hz,
        lines=image.shape[0],
        locked=locked,
        standard=standard.name,
        frame_locked=bool(frame_locked),
    )


class VideoDecoder:
    """Accumulate IQ and emit monochrome frames."""

    def __init__(
        self,
        standard: VideoStandard = PAL,
        *,
        mode: str = "fm",
        invert: bool = False,
        frame_seconds: float = 0.12,
        max_seconds: float = 0.30,
    ) -> None:
        self.standard = standard
        self.mode = mode
        self.invert = invert
        self.frame_seconds = max(0.04, float(frame_seconds))
        self.max_seconds = max(self.frame_seconds, float(max_seconds))
        self._chunks: list[np.ndarray] = []
        self._size = 0
        self._rate = 0.0
        self.frames = 0
        self.last: DecodedFrame | None = None

    def reset(self) -> None:
        self._chunks = []
        self._size = 0

    def feed(self, iq: np.ndarray, sample_rate: float) -> DecodedFrame | None:
        if sample_rate <= 0 or iq.size == 0:
            return None
        self._rate = float(sample_rate)
        self._chunks.append(np.asarray(iq, dtype=np.complex64))
        self._size += iq.size
        if self._size < self.frame_seconds * self._rate:
            return None
        data = np.concatenate(self._chunks)
        frame = decode_frame(
            data, self._rate, self.standard,
            mode=self.mode, invert=self.invert,
        )
        if frame is not None:
            self.frames += 1
            self.last = frame
            # Keep a short overlap so the next frame does not start blind.
            keep = int(0.03 * self._rate)
            data = data[-keep:] if keep else data[:0]
            self._chunks = [data] if data.size else []
            self._size = int(data.size)
        else:
            limit = int(self.max_seconds * self._rate)
            if self._size > limit:
                data = data[-limit:]
                self._chunks = [data]
                self._size = int(data.size)
        return frame


__all__ = [
    "DecodedFrame",
    "NTSC",
    "PAL",
    "STANDARDS",
    "VideoDecoder",
    "VideoStandard",
    "decode_frame",
    "demodulate",
]
