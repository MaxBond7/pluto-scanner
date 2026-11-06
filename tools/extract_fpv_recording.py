# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Extract one frequency block from the FPV dataset as a normal recording.

    python -m tools.extract_fpv_recording `
      --iq ...\\sweep_20260422_153008\\iq.bin `
      --meta ...\\sweep_20260422_153008\\metadata.csv `
      --freq 1240e6 --out Z:\\datasets\\FPV_Analog\\fpv_1240.cf32
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np

from sdr_scanner.recordings import new_recording_info, save_info
from tools.analyze_fpv_sweep import load_blocks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iq", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--freq", type=float, default=1240e6)
    parser.add_argument("--rate", type=float, default=20e6)
    parser.add_argument("--out", required=True)
    args = parser.parse_args(argv)
    iq, center = load_blocks(Path(args.iq), Path(args.meta), args.freq)
    if iq.size == 0:
        print("нет блоков")
        return 2
    out = Path(args.out)
    info = new_recording_info(
        out.parent,
        device_id="fpv-dataset",
        device_name="FPV Analogue Video IQ Dataset",
        device_kind="iqfile",
        sample_rate=args.rate,
        center_freq=center,
        bandwidth_hz=8.0e6,
    )
    # Keep the requested name, not the timestamped one.
    target = out if out.suffix.lower() == ".cf32" else out.with_suffix(".cf32")
    iq.astype(np.complex64).tofile(target)
    info.cf32_path = str(target)
    info.meta_path = str(target.with_suffix(".json"))
    info.samples = int(iq.size)
    info.complete = True
    info.notes = "FPV Analogue Video IQ Dataset, 1240 MHz VTX"
    save_info(info)
    print(
        f"{target} · {iq.size} отсчётов · {iq.size / args.rate * 1000:.1f} мс\n"
        f"{info.meta_path}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
