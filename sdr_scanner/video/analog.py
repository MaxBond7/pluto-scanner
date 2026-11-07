# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Analog PAL/NTSC video decoder.

The app already detects the 15.625 kHz line rate.  This module goes one step
further: it FM-demodulates the IQ, locks onto the line rhythm, samples the
active part of every line and builds a monochrome picture.

Three assembly modes are used, depending on how much of the vertical sync
the capture contains:

* two complete half-frames -> a full interlaced frame (480 lines NTSC,
  576 lines PAL/SECAM);
* one complete half-frame -> that field, line-doubled to the full height,
  which is exactly what a CRT shows before the next field arrives;
* no vertical sync -> the lines are stacked into a partial picture, which is
  what short dataset blocks and live buffers give.

The line grid is fitted over *all* detected sync pulses instead of anchoring
every line on its own pulse.  Sync detection jitters by a few samples, and
using that jitter as the line start smears the picture horizontally.  The fit
also absorbs the constant clock offset between the transmitter camera and the
SDR, which otherwise drifts the picture by half a line per field.

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
    video_bw: float = 4.4e6
    #: Lines between the vertical sync and the first visible line.
    top_blank: float = 20.5

    @property
    def line_s(self) -> float:
        return 1.0 / self.line_hz

    @property
    def rows_per_field(self) -> int:
        return self.active_lines // 2


PAL = VideoStandard("PAL", 15625.0, 625, 576, 768, 25.0, 5.5e6, 22.5)
NTSC = VideoStandard("NTSC", 15734.264, 525, 480, 640, 29.97, 4.2e6, 20.5)
# Russian SECAM D/K uses the same 625/50 geometry as PAL; colour is not
# decoded yet, but the monochrome picture and line timing are identical.
SECAM = VideoStandard("SECAM", 15625.0, 625, 576, 768, 25.0, 5.5e6, 22.5)
STANDARDS = {"PAL": PAL, "NTSC": NTSC, "SECAM": SECAM}

#: Window inside a line that carries picture (fractions of the line period).
_ACTIVE_START = 0.13
_ACTIVE_STOP = 0.94


@dataclass(frozen=True)
class DecodedFrame:
    image: np.ndarray              # uint8, rows x pixels
    line_hz: float
    lines: int
    locked: bool
    standard: str
    frame_locked: bool = False
    quality: float = 0.0          # line-to-line correlation, 0..1


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
        # Instantaneous frequency as the phase of x[n] * conj(x[n-1]).
        # This is the same as diff(unwrap(angle(x))) for signals that stay
        # inside one Nyquist zone, and it is much faster.
        product = x[1:] * np.conj(x[:-1])
        video = np.angle(product).astype(np.float64)
        if video.size:
            video = np.append(video, video[-1])
    video -= float(np.mean(video))
    if invert:
        video = -video
    return video


def band_limit(signal: np.ndarray, rate: float, cutoff: float) -> np.ndarray:
    """Low-pass the demodulated video to its real bandwidth.

    An FM discriminator turns the whole noise band into baseband noise.
    Cutting the signal at the video bandwidth of the standard (4.2 MHz NTSC,
    5.5 MHz PAL/SECAM) removes most of the snow without touching the picture.
    """
    if signal.size < 64 or rate <= 0:
        return signal
    cutoff = float(min(cutoff, 0.45 * rate))
    if cutoff <= 0:
        return signal
    # A windowed sinc only needs a few lobes: the kernel is zero at
    # rate / (2 * cutoff) samples.  A short kernel keeps live video cheap.
    taps = int(min(63, max(9, 2.5 * rate / cutoff))) | 1
    offset = np.arange(taps) - (taps - 1) / 2.0
    kernel = np.sinc(2.0 * cutoff / rate * offset) * np.hamming(taps)
    total = float(kernel.sum())
    if abs(total) < 1e-12:
        return signal
    return np.convolve(signal, kernel / total, mode="same")


def _rhythm(diff_samples: float, rate: float) -> float:
    """1.0 when a pulse spacing is a plausible TV line period."""
    if diff_samples <= 0:
        return 0.0
    for target in (1.0 / 15625.0, 1.0 / 15734.264):
        samples = target * rate
        if abs(diff_samples - samples) < 0.2 * samples:
            return 1.0
    return 0.0


def _moving_average(signal: np.ndarray, width: int) -> np.ndarray:
    """Box filter in O(n), edges padded with the first/last sample."""
    width = max(1, int(width))
    if width == 1 or signal.size < 2:
        return signal
    half = width // 2
    pad = np.concatenate((
        np.full(half, signal[0]),
        signal,
        np.full(width - half - 1, signal[-1]),
    ))
    cumulative = np.cumsum(np.concatenate(([0.0], pad)))
    return (cumulative[width:] - cumulative[:-width]) / float(width)


def _sync_runs(video: np.ndarray, rate: float) -> tuple[np.ndarray, np.ndarray]:
    """Return sync-pulse positions and vertical-sync starts, in samples.

    A line sync is a short low pulse (~4.7 us); the vertical interval is a run
    of wide low pulses (~27 us).  Both polarities are tried because the FM
    discriminator can invert the video.  The pulse position is taken at the
    bottom of the pulse: the leading edge moves with the noise level, the
    bottom does not.
    """
    width = max(3, int(round(2.0e-6 * rate)))
    narrow_width = 12e-6 * rate

    best: tuple[float, np.ndarray, np.ndarray] | None = None
    for signal in (video, -video):
        smooth = _moving_average(signal, width)
        # Percentiles of the full buffer would sort 2.4M samples twice; a
        # regular subsample is enough for a level estimate.
        step = max(1, smooth.size // 150_000)
        sample = smooth[::step]
        mid = float(np.median(sample))
        low = float(np.percentile(sample, 1.0))
        if mid <= low:
            continue
        below = smooth < mid - 0.65 * (mid - low)
        edges = np.diff(np.r_[0, below.view(np.int8), 0])
        starts = np.flatnonzero(edges == 1)
        ends = np.flatnonzero(edges == -1)
        if starts.size == 0 or ends.size == 0:
            continue
        positions = []
        broad_positions = []
        for start, stop in zip(starts, ends):
            segment = smooth[start:stop]
            bottom = float(segment.min())
            # Width at the bottom of the pulse: 4.7 us for a line sync,
            # 27 us for a vertical-sync pulse.  This does not depend on
            # where the blanking level sits.
            level = bottom + 0.25 * (mid - bottom)
            dark = segment < level
            middle = int(np.argmin(segment))
            left = middle
            while left > 0 and dark[left - 1]:
                left -= 1
            right = middle
            while right + 1 < dark.size and dark[right + 1]:
                right += 1
            centre = float(start) + (left + right) / 2.0
            if right - left + 1 >= narrow_width:
                broad_positions.append(centre)
            positions.append(centre)
        positions = np.asarray(positions, dtype=np.float64)
        broad = np.asarray(broad_positions, dtype=np.float64)
        if broad.size:
            # Vertical-sync pulses sit half a line off the picture grid;
            # keep them out of the line-rate fit.
            line_positions = positions[~np.isin(positions, broad)]
        else:
            line_positions = positions
        score = _rhythm(
            float(np.median(np.diff(line_positions)))
            if line_positions.size > 2 else 0.0,
            rate,
        )
        if best is None or score > best[0]:
            best = (score, line_positions, broad)
        if score >= 1.0:
            # A steady line rhythm: the other polarity cannot be better.
            break
    if best is None:
        return np.empty(0, np.float64), np.empty(0, np.float64)
    return best[1], best[2]


def _fit_line_grid(
    positions: np.ndarray, guess_samples: float,
) -> tuple[float, float, float]:
    """Line period, phase and confidence from detected sync pulses.

    The period is searched by phase concentration: for the true period all
    pulse positions collapse onto one phase, so their phasors add up.  This
    ignores the occasional false pulse instead of fitting to it.  The final
    least-squares pass then trims half-line blunders.
    """
    if positions.size < 8:
        first = float(positions[0]) if positions.size else 0.0
        return guess_samples, first, 0.0
    # The concentration peak is sharp enough with a few hundred pulses;
    # using every pulse of a 2 s capture only costs time.
    sample = positions
    if positions.size > 400:
        step = positions.size // 400
        sample = positions[::step]
    best_period, best_conc = guess_samples, -1.0
    for period in np.linspace(guess_samples * 0.97, guess_samples * 1.03, 241):
        angle = 2.0 * np.pi * (sample % period) / period
        conc = float(abs(np.mean(np.exp(1j * angle))))
        if conc > best_conc:
            best_period, best_conc = float(period), conc
    # Second pass: the concentration peak is narrow, so refine it locally.
    for period in np.linspace(best_period - 0.5, best_period + 0.5, 201):
        angle = 2.0 * np.pi * (sample % period) / period
        conc = float(abs(np.mean(np.exp(1j * angle))))
        if conc > best_conc:
            best_period, best_conc = float(period), conc
    slope = best_period
    index = np.round((positions - positions[0]) / slope)
    keep = np.r_[True, np.diff(index) > 0]
    index, values = index[keep], positions[keep]
    intercept = float(values[0])
    for _ in range(3):
        if index.size < 4:
            break
        slope, intercept = np.polyfit(index, values, 1)
        residual = values - (slope * index + intercept)
        centre = float(np.median(residual))
        mask = np.abs(residual - centre) < 0.15 * slope
        if mask.sum() < 4 or mask.all():
            break
        index, values = index[mask], values[mask]
    return float(slope), float(intercept), best_conc


def _vertical_syncs(broad: np.ndarray, slope: float) -> list[float]:
    """Group wide pulses into vertical-sync bursts (six, half a line apart)."""
    if broad.size == 0:
        return []
    groups: list[list[float]] = [[float(broad[0])]]
    for position in broad[1:]:
        if position - groups[-1][-1] < 2.0 * slope:
            groups[-1].append(float(position))
        else:
            groups.append([float(position)])
    starts = []
    for group in groups:
        if len(group) < 4:
            continue
        spacing = float(np.median(np.diff(group))) if len(group) > 1 else 0.0
        if spacing and abs(spacing - 0.5 * slope) > 0.2 * slope:
            continue
        starts.append(group[0])
    return starts


def _match_standard(line_hz: float, requested: VideoStandard) -> VideoStandard:
    """Keep the requested standard unless the measured rate says otherwise."""
    tolerance = 0.003 * requested.line_hz
    if abs(line_hz - requested.line_hz) <= tolerance:
        return requested
    nearest = min(STANDARDS.values(),
                  key=lambda item: abs(item.line_hz - line_hz))
    if abs(nearest.line_hz - line_hz) <= tolerance:
        return nearest
    return requested


def _line_rows(
    video: np.ndarray, positions: np.ndarray, slope: float, width: int,
) -> np.ndarray:
    rows = []
    for position in positions:
        start = max(0, int(round(position + _ACTIVE_START * slope)))
        stop = min(video.size, int(round(position + _ACTIVE_STOP * slope)))
        if stop - start < 2:
            continue
        segment = video[start:stop]
        rows.append(np.interp(
            np.linspace(0.0, segment.size - 1.0, width, endpoint=False),
            np.arange(segment.size, dtype=np.float64),
            segment,
        ))
    return np.asarray(rows, dtype=np.float64)


def _complete_fields(
    video: np.ndarray,
    standard: VideoStandard,
    slope: float,
    intercept: float,
    vsync: list[float],
    width: int,
) -> list[np.ndarray]:
    rows = standard.rows_per_field
    field_lines = standard.lines / 2.0
    fields: list[np.ndarray] = []
    for index in range(len(vsync) - 1):
        start, stop = vsync[index], vsync[index + 1]
        if not (0.92 * field_lines * slope <= stop - start
                <= 1.08 * field_lines * slope):
            continue
        first = int(np.ceil((start + standard.top_blank * slope - intercept)
                            / slope))
        positions = intercept + (first + np.arange(rows)) * slope
        if positions[-1] + _ACTIVE_STOP * slope > stop:
            continue
        field = _line_rows(video, positions, slope, width)
        if field.shape[0] == rows:
            fields.append(field)
    return fields


def _assemble(
    video: np.ndarray,
    standard: VideoStandard,
    slope: float,
    intercept: float,
    vsync: list[float],
    width: int,
) -> tuple[np.ndarray, np.ndarray, bool] | None:
    """Build (picture, rows_for_quality, is_full_frame) from the fields."""
    fields = _complete_fields(
        video, standard, slope, intercept, vsync, width,
    )
    if len(fields) >= 2:
        first, second = fields[0], fields[1]
        frame = np.zeros((2 * standard.rows_per_field, width), dtype=np.float64)
        frame[0::2] = first
        frame[1::2] = second
        alt = np.zeros_like(frame)
        alt[1::2] = first
        alt[0::2] = second
        if _correlation(alt) > _correlation(frame):
            frame = alt
        return frame, frame, True
    if fields:
        # One field is half the picture, line-doubled the way a CRT shows it.
        field = fields[0]
        picture = np.repeat(field, 2, axis=0)
        return picture, field, False
    return None


def _correlation(image: np.ndarray) -> float:
    if image.shape[0] < 2:
        return 0.0
    top = image[:-1] - image[:-1].mean(axis=1, keepdims=True)
    bottom = image[1:] - image[1:].mean(axis=1, keepdims=True)
    denom = np.sqrt((top ** 2).sum(axis=1) * (bottom ** 2).sum(axis=1))
    valid = denom > 1e-9
    if not bool(valid.any()):
        return 0.0
    return float(((top * bottom).sum(axis=1)[valid] / denom[valid]).mean())


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
    """Decode one frame (or a partial field) from a block of IQ."""
    video = demodulate(iq, mode=mode, invert=invert)
    if video.size == 0:
        return None
    # Sync detection runs on the widest video band; the picture itself is
    # then filtered to the bandwidth of the standard that was matched.
    widest = max(item.video_bw for item in STANDARDS.values())
    probe = band_limit(video, sample_rate, widest)
    narrow, broad = _sync_runs(probe, sample_rate)
    if narrow.size < min_lines:
        return None
    slope, intercept, confidence = _fit_line_grid(
        narrow, sample_rate / standard.line_hz,
    )
    if slope <= 0:
        return None
    measured = sample_rate / slope
    standard = _match_standard(measured, standard)
    if standard.video_bw < widest:
        video = band_limit(video, sample_rate, standard.video_bw)
    else:
        video = probe

    width = int(pixels or standard.pixels)
    vsync = _vertical_syncs(broad, slope)

    assembled = _assemble(video, standard, slope, intercept, vsync, width)
    frame_locked = bool(assembled and assembled[2])
    if assembled is not None:
        image, quality_rows = assembled[0], assembled[1]
    else:
        # No vertical sync: stack the lines that we do have.
        count = max(0, int((video.size - intercept) // slope))
        positions = intercept + np.arange(count) * slope
        if positions.size < min_lines:
            return None
        if vsync:
            blank = np.zeros(positions.size, dtype=bool)
            for start in vsync:
                blank |= ((positions > start)
                          & (positions < start + standard.top_blank * slope))
            positions = positions[~blank]
        if positions.size < min_lines:
            return None
        image = _line_rows(video, positions, slope, width)
        if image.shape[0] < min_lines:
            return None
        image = image[-standard.lines:]
        quality_rows = image

    # Remove line-to-line DC steps, then stretch the visible range.
    image = image - np.median(image, axis=1, keepdims=True)
    low = float(np.percentile(image, 2.0))
    high = float(np.percentile(image, 98.0))
    if high <= low:
        return None
    image = np.clip((image - low) / (high - low), 0.0, 1.0)
    if invert:
        image = 1.0 - image
    quality = _correlation(quality_rows)
    image = (image * 255.0).astype(np.uint8)
    locked = bool(
        abs(measured - standard.line_hz) / standard.line_hz < 0.03
        and confidence > 0.35
    )
    return DecodedFrame(
        image=image,
        line_hz=measured,
        lines=image.shape[0],
        locked=locked,
        standard=standard.name,
        frame_locked=frame_locked,
        quality=quality,
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
    "SECAM",
    "VideoDecoder",
    "VideoStandard",
    "band_limit",
    "decode_frame",
    "demodulate",
]
