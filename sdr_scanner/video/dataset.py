# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Reader for sweep folders of the FPV Analogue Video IQ Dataset.

A sweep folder contains ``iq.bin`` (interleaved complex64) and
``metadata.csv`` with ``timestamp, center_freq, offset_bytes, num_samples``
per recorded block.  The recorder pads every block with zeros: the second
half of each block is not signal.  Blocks are otherwise contiguous in time,
so trimming the padding and joining them gives one continuous capture.

The same reader is used by the video tab and by the command line tools.
"""
from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

METADATA_NAME = "metadata.csv"


def metadata_for(iq_path: str | Path) -> Path | None:
    """Return the sweep metadata next to *iq_path*, if this is a dataset."""
    iq_path = Path(iq_path)
    if iq_path.name.lower() != "iq.bin":
        return None
    meta = iq_path.with_name(METADATA_NAME)
    if not meta.is_file():
        return None
    try:
        with meta.open(encoding="utf-8", newline="") as handle:
            header = handle.readline()
    except OSError:
        return None
    return meta if "center_freq" in header else None


def frequencies(meta_path: str | Path) -> list[float]:
    """All centre frequencies of a sweep, ascending and without duplicates."""
    values: set[float] = set()
    with Path(meta_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                values.add(float(row["center_freq"]))
            except (KeyError, TypeError, ValueError):
                continue
    return sorted(values)


def load_blocks(
    iq_path: str | Path, meta_path: str | Path, freq: float,
) -> tuple[np.ndarray, float]:
    """Read the blocks of the sweep closest to *freq*.

    Returns the IQ samples with the recorder padding removed and the centre
    frequency that was actually used.
    """
    rows: list[dict[str, float | int]] = []
    with Path(meta_path).open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            try:
                rows.append({
                    "center": float(row["center_freq"]),
                    "offset": int(row["offset_bytes"]),
                    "count": int(row["num_samples"]),
                })
            except (KeyError, TypeError, ValueError):
                continue
    if not rows:
        return np.empty(0, dtype=np.complex64), float(freq)

    centres = {item["center"] for item in rows}
    nearest = min(centres, key=lambda value: abs(value - float(freq)))
    selected = [item for item in rows if item["center"] == nearest]

    data = np.memmap(Path(iq_path), dtype=np.complex64, mode="r")
    try:
        pieces = []
        for item in selected:
            start = int(item["offset"]) // 8
            block = np.array(
                data[start:start + int(item["count"])],
                dtype=np.complex64, copy=True,
            )
            real = np.flatnonzero(np.abs(block) > 0)
            pieces.append(block[: int(real[-1]) + 1] if real.size else block[:0])
    finally:
        del data
    if not pieces:
        return np.empty(0, dtype=np.complex64), nearest
    return np.concatenate(pieces), nearest


__all__ = ["frequencies", "load_blocks", "metadata_for"]
