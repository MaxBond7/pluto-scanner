# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Decode one frame from the FPV Analogue Video IQ Dataset.

    python -m tools.decode_fpv_frame `
      --iq Z:\\datasets\\FPV_Analog\\chunk10\\sweep_20260422_153008\\iq.bin `
      --meta Z:\\datasets\\FPV_Analog\\chunk10\\sweep_20260422_153008\\metadata.csv `
      --freq 1240e6 --standard PAL --out fpv_frame.png
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

from PIL import Image

from sdr_scanner.video.analog import NTSC, PAL, decode_frame
from tools.analyze_fpv_sweep import load_blocks


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--iq", required=True)
    parser.add_argument("--meta", required=True)
    parser.add_argument("--freq", type=float, default=1240e6)
    parser.add_argument("--rate", type=float, default=20e6)
    parser.add_argument("--standard", choices=("PAL", "NTSC"), default="PAL")
    parser.add_argument("--out", default="fpv_frame.png")
    args = parser.parse_args(argv)
    iq, center = load_blocks(Path(args.iq), Path(args.meta), args.freq)
    standard = PAL if args.standard == "PAL" else NTSC
    frame = decode_frame(iq, args.rate, standard)
    if frame is None:
        print("кадр не собран: нет устойчивой строки")
        return 1
    Image.fromarray(frame.image, "L").save(args.out)
    print(
        f"{center / 1e6:.1f} МГц · {frame.standard} · "
        f"{frame.line_hz:.1f} Гц · {frame.lines} строк · {args.out}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
