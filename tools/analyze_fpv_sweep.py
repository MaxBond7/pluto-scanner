# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Analyze one frequency from the FPV Analogue Video IQ Dataset.

The dataset stores a sweep: ``metadata.csv`` lists ``center_freq``,
``offset_bytes`` and ``num_samples`` for every 65536-sample block, and
``iq.bin`` is interleaved complex64.  This tool reads only the blocks around
one centre frequency and runs the same analog-video detector as the app::

    python -m tools.analyze_fpv_sweep `
      --iq Z:\\datasets\\FPV_Analog\\chunk10\\sweep_20260422_153008\\iq.bin `
      --meta Z:\\datasets\\FPV_Analog\\chunk10\\sweep_20260422_153008\\metadata.csv `
      --freq 1240e6
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

import numpy as np

from sdr_scanner.drone.deep_look import _analog_line, interpret, reasons
from sdr_scanner.ml.behavior import analyze


def load_blocks(iq_path: Path, meta_path: Path, freq: float) -> tuple[np.ndarray, float]:
    rows = []
    with meta_path.open(newline="", encoding="utf-8") as handle:
        for row in csv.DictReader(handle):
            rows.append({
                "center": float(row["center_freq"]),
                "offset": int(row["offset_bytes"]),
                "count": int(row["num_samples"]),
            })
    if not rows:
        return np.empty(0, dtype=np.complex64), freq
    nearest = min({item["center"] for item in rows}, key=lambda value: abs(value - freq))
    selected = [item for item in rows if item["center"] == nearest]
    data = np.memmap(iq_path, dtype=np.complex64, mode="r")
    try:
        pieces = []
        for item in selected:
            block = np.array(
                data[item["offset"] // 8:
                     item["offset"] // 8 + item["count"]],
                dtype=np.complex64, copy=True,
            )
            # Recorder padding: the second half of every dataset block is
            # zeros, not signal.  Keep only the real samples so blocks sit
            # next to each other in time.
            real = np.flatnonzero(np.abs(block) > 0)
            pieces.append(block[: int(real[-1]) + 1] if real.size else block[:0])
    finally:
        del data
    return np.concatenate(pieces) if pieces else np.empty(0, dtype=np.complex64), nearest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iq", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--freq", type=float, default=1240e6)
    parser.add_argument("--rate", type=float, default=20e6)
    parser.add_argument("--seconds", type=float, default=0.1)
    args = parser.parse_args(argv)

    iq, center = load_blocks(Path(args.iq), Path(args.meta), args.freq)
    if iq.size == 0:
        print("нет блоков для", args.freq)
        return 2
    behavior = analyze(iq, args.rate, max_seconds=args.seconds)
    line = _analog_line(behavior)
    print(
        f"центр: {center / 1e6:.1f} МГц · {iq.size} отсчётов · "
        f"{iq.size / args.rate * 1000:.1f} мс"
    )
    print(
        f"duty={behavior.duty:.2f} occupied={behavior.occupied:.2f} "
        f"SNR={behavior.snr_db:.1f} дБ"
    )
    print(
        f"огибающая: {behavior.sync_khz:.3f} кГц ×{behavior.sync_strength:.1f} · "
        f"FM: {behavior.fm_sync_khz:.3f} кГц ×{behavior.fm_sync_strength:.1f}"
    )
    if line is not None:
        print("line:", line)
    print("verdict:", interpret(behavior, args.rate))
    print("reasons:", " · ".join(reasons(behavior, args.rate)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
