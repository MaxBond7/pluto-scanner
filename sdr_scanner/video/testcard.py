# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Composite PAL/NTSC test card for the bench transmitter.

The picture is drawn with numpy only: the application does not depend on
Pillow, and the same generator is used by the GUI and by the command line
tools.  Levels follow a real composite signal: 0 is the sync tip, 0.30 is
blanking, 1.0 is peak white.
"""
from __future__ import annotations

import numpy as np

SYNC = 0.0
BLANK = 0.30
BLACK = 0.34

SYNC_US = 4.7
PORCH_US = 5.7
ACTIVE_US = 52.0

#: 5x7 glyphs for the caption on the card.
_FONT = {
    " ": (0, 0, 0, 0, 0, 0, 0),
    "S": (0b01111, 0b10000, 0b10000, 0b01110, 0b00001, 0b00001, 0b11110),
    "D": (0b11110, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b11110),
    "R": (0b11110, 0b10001, 0b10001, 0b11110, 0b10100, 0b10010, 0b10001),
    "C": (0b01110, 0b10001, 0b10000, 0b10000, 0b10000, 0b10001, 0b01110),
    "A": (0b01110, 0b10001, 0b10001, 0b11111, 0b10001, 0b10001, 0b10001),
    "N": (0b10001, 0b11001, 0b10101, 0b10011, 0b10001, 0b10001, 0b10001),
    "E": (0b11111, 0b10000, 0b10000, 0b11110, 0b10000, 0b10000, 0b11111),
    "P": (0b11110, 0b10001, 0b10001, 0b11110, 0b10000, 0b10000, 0b10000),
    "L": (0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b10000, 0b11111),
    "U": (0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b10001, 0b01110),
    "T": (0b11111, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100, 0b00100),
    "X": (0b10001, 0b10001, 0b01010, 0b00100, 0b01010, 0b10001, 0b10001),
}


def draw_text(canvas: np.ndarray, text: str, x: int, y: int,
              scale: int, level: float = 1.0) -> None:
    for char in text.upper():
        rows = _FONT.get(char)
        if rows is None:
            x += 6 * scale
            continue
        for row, bits in enumerate(rows):
            for column in range(5):
                if bits & (1 << (4 - column)):
                    top = y + row * scale
                    left = x + column * scale
                    canvas[top:top + scale, left:left + scale] = level
        x += 6 * scale


def test_card(width: int, height: int, second: float = 0.0) -> np.ndarray:
    """A moving test card: bars, caption, ring and a travelling marker."""
    canvas = np.full((height, width), 0.16, dtype=np.float64)
    bars = 8
    top = int(height * 0.62)
    for index in range(bars):
        level = 0.06 + 0.92 * index / (bars - 1)
        left = index * width // bars
        right = (index + 1) * width // bars
        canvas[:top, left:right] = level
    canvas[top:] = 0.13
    scale = max(2, height // 110)
    draw_text(canvas, "SDR SCANNER", max(4, width // 40),
              max(4, height // 24), scale, 1.0)
    draw_text(canvas, "PLUTO TX", max(4, width // 40),
              int(height * 0.70), scale, 0.9)
    # Ring in the lower part.
    cy = int(height * 0.82)
    cx = width // 2
    radius = max(8, height // 10)
    yy, xx = np.ogrid[:height, :width]
    ring = np.abs(np.hypot(yy - cy, xx - cx) - radius) < max(1.5, radius * 0.06)
    canvas[ring] = 0.9
    # A marker that moves with the frame counter, so motion is visible.
    span = width - max(40, width // 8)
    x = int(span * (0.5 - 0.5 * np.cos(2 * np.pi * second / 4.0)))
    size = max(24, height // 9)
    y = int(height * 0.42)
    canvas[y:y + size, x:x + size] = 1.0
    return np.clip(canvas, 0.0, 1.0)


def composite_field(standard, rate: float, rows: np.ndarray,
                    field: int) -> np.ndarray:
    """One half-frame of composite video (line sync + picture).

    The field is assembled as a (lines, line_samples) matrix and flattened,
    which is fast enough to build a field while the previous one is being
    transmitted.
    """
    line = int(round(rate / standard.line_hz))
    field_lines = standard.lines // 2
    sync = int(round(SYNC_US * 1e-6 * rate))
    porch = int(round(PORCH_US * 1e-6 * rate))
    active = int(round(ACTIVE_US * 1e-6 * rate))
    broad = int(round(2.7e-5 * rate))

    frame = np.full((field_lines, line), BLANK, dtype=np.float64)
    frame[:, :sync] = SYNC
    frame[:, sync:sync + porch] = BLANK

    height, width = rows.shape
    count = standard.rows_per_field
    top = int(round(standard.top_blank))
    source = (2 * np.arange(count) + (field % 2)) % max(1, height)
    picture = rows[source]
    if picture.shape[1] != active:
        index = np.rint(
            np.linspace(0, picture.shape[1] - 1, active)
        ).astype(np.intp)
        picture = picture[:, index]
    # Picture black must stay above blanking: a black area at the sync
    # level would be taken for a sync pulse by any receiver.
    picture = BLACK + picture * (1.0 - BLACK)
    room = min(count, field_lines - top)
    frame[top:top + room, sync + porch:sync + porch + active] = \
        picture[:room]

    video = frame.reshape(-1)
    # Vertical sync: six wide pulses, half a line apart.
    for pulse in range(6):
        start = int(pulse * 0.5 * line)
        video[start:start + broad] = SYNC
    return video


def build_frame(
    standard, rate: float, rows: np.ndarray, deviation: float,
    fields: int = 2,
) -> tuple[np.ndarray, int]:
    """Modulate one picture (a still) as *fields* half-frames."""
    pieces = [composite_field(standard, rate, rows, index % 2)
              for index in range(fields)]
    video = np.concatenate(pieces)
    angle = 2.0 * np.pi * deviation * np.cumsum(video - 0.5) / rate
    return np.exp(1j * angle).astype(np.complex64), pieces[0].size


def build(
    standard, rate: float, seconds: float, deviation: float,
    field_only: bool = False,
) -> tuple[np.ndarray, int]:
    """Composite test card, FM-modulated around 0 Hz.

    Returns the complex IQ and the length of one field in samples, so a
    caller can loop whole fields without tearing the picture.
    """
    line = int(round(rate / standard.line_hz))
    field_samples = line * (standard.lines // 2)
    height = standard.active_lines
    width = standard.pixels
    pieces = []
    if field_only:
        pieces.append(composite_field(
            standard, rate, test_card(width, height, 0.0), 0,
        ))
    else:
        frames = max(1, int(round(seconds * standard.fps)))
        for frame in range(frames):
            rows = test_card(width, height, frame / standard.fps)
            for field in range(2):
                pieces.append(composite_field(standard, rate, rows, field))
    video = np.concatenate(pieces)
    angle = 2.0 * np.pi * deviation * np.cumsum(video - 0.5) / rate
    return np.exp(1j * angle).astype(np.complex64), field_samples


__all__ = [
    "build",
    "build_frame",
    "composite_field",
    "draw_text",
    "test_card",
]
