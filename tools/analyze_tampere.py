# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Measure behaviour of the Tampere drone recordings.

For every ``.bin``: duty cycle, burst rate, frequency-hop rate, number of
channels and the analog-video line-rate peak.  The recordings are interleaved
16-bit I/Q at 120 MS/s (2.4 GHz) or 200 MS/s (5.8 GHz), about one second each.

Examples::

    python -m tools.analyze_tampere --root Z:\\datasets\\Tampere
    python -m tools.analyze_tampere --root Z:\\datasets\\Tampere --seconds 0.5
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from pluto_scanner.ml.behavior import analyze

HEADER = (
    f"{'file':38s} {'fs':>4s} {'duty':>5s} {'burst/s':>8s} "
    f"{'hop/s':>7s} {'ch':>3s} {'occ':>5s} {'sync/kHz':>9s} {'x':>5s}"
)


def read_iq(path: Path, sample_rate: float, seconds: float) -> np.ndarray:
    """Read the first ``seconds`` of interleaved int16 I/Q."""
    count = int(sample_rate * seconds) * 2
    raw = np.memmap(path, dtype="<i2", mode="r")
    data = np.asarray(raw[:min(raw.size, count)], dtype=np.float32)
    del raw
    data = data[:(data.size // 2) * 2]
    return (data[0::2] + 1j * data[1::2]).astype(np.complex64)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=r"Z:\datasets\Tampere")
    parser.add_argument("--seconds", type=float, default=1.0)
    parser.add_argument("--only", default="", choices=("", "2G", "5G"))
    args = parser.parse_args(argv)

    root = Path(args.root)
    files = sorted(root.glob("*.bin"))
    if args.only:
        files = [path for path in files if f"_{args.only}" in path.name]
    if not files:
        print(f"в {root} нет .bin")
        return 2

    print(HEADER)
    for path in files:
        sample_rate = 200e6 if "_5G" in path.name else 120e6
        try:
            iq = read_iq(path, sample_rate, args.seconds)
        except Exception as exc:
            print(f"{path.name:38s} ошибка чтения: {exc}")
            continue
        result = analyze(iq, sample_rate, max_seconds=args.seconds)
        print(
            f"{path.name:38s} {sample_rate / 1e6:4.0f} "
            f"{result.duty:5.2f} {result.burst_rate_hz:8.0f} "
            f"{result.hop_rate_hz:7.0f} {result.channels:3d} "
            f"{result.occupied:5.2f} {result.sync_khz:9.1f} "
            f"{result.sync_strength:5.1f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
