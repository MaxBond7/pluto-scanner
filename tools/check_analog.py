# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Check an IQ file for an analog FPV video line rate.

Examples::

    python -m tools.check_analog --file capture.cf32 --rate 20e6
    python -m tools.check_analog --file dji.bin --rate 120e6 --format int16

It reports the envelope and FM-demodulated line peaks, duty, occupied
bandwidth and the cautious verdict used by the event card.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from sdr_scanner.drone.deep_look import interpret, reasons
from sdr_scanner.ml.behavior import analyze


def load(path: Path, rate: float, seconds: float, fmt: str) -> np.ndarray:
    count = int(rate * seconds)
    if fmt == "cf32":
        data = np.fromfile(path, dtype=np.complex64, count=count)
        return data.astype(np.complex64)
    dtype = "<i2" if fmt == "int16" else "i1"
    raw = np.fromfile(path, dtype=dtype, count=count * 2)
    raw = raw[:(raw.size // 2) * 2]
    if fmt == "int16":
        raw = raw.astype(np.float32) / 2048.0
    else:
        raw = raw.astype(np.float32) / 128.0
    return (raw[0::2] + 1j * raw[1::2]).astype(np.complex64)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--file", required=True)
    parser.add_argument("--rate", type=float, default=20e6)
    parser.add_argument("--seconds", type=float, default=0.5)
    parser.add_argument(
        "--format", choices=("cf32", "int16", "int8"), default="cf32",
    )
    args = parser.parse_args(argv)
    path = Path(args.file)
    if not path.exists():
        print("нет файла:", path)
        return 2
    iq = load(path, float(args.rate), float(args.seconds), args.format)
    if iq.size == 0:
        print("пустой файл")
        return 2
    behavior = analyze(iq, float(args.rate), max_seconds=args.seconds)
    print("behavior:", json.dumps(behavior.to_dict(), ensure_ascii=False))
    print("verdict:", interpret(behavior, float(args.rate)))
    print("reasons:", " · ".join(reasons(behavior, float(args.rate))))
    if behavior.fm_sync_strength > 0:
        print(
            f"FM line: {behavior.fm_sync_khz:.3f} кГц "
            f"×{behavior.fm_sync_strength:.1f}"
        )
    if behavior.sync_strength > 0:
        print(
            f"envelope line: {behavior.sync_khz:.3f} кГц "
            f"×{behavior.sync_strength:.1f}"
        )
    return 0


if __name__ == "__main__":
    sys.exit(main())
