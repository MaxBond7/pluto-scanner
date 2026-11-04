# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Generate the GitHub banner in the monochrome ``mono`` style."""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "assets"))

import brand_mono as bm  # noqa: E402

OUT = ROOT / "assets" / "github_banner.png"
W, H = 1600, 480


def app_version() -> str:
    import re

    text = (ROOT / "pyproject.toml").read_text(encoding="utf-8")
    match = re.search(r'(?m)^version\s*=\s*"([^"]+)"', text)
    return match.group(1) if match else "0.0.0"


def main() -> None:
    image = bm.canvas(W, H)
    d = bm.ImageDraw.Draw(image)

    bm.frame(d, W, H)
    bm.ruler(d, 40, 36, W - 40, step=24, tall=10)

    # Left block: wordmark and specification lines.
    left = 64
    bm.label(d, (left, 64), "CONSOLE // 001", 14)
    bm.label(d, (left + 250, 64), "PASSIVE RX ONLY", 14)

    width = bm.glitch_title(d, (left, 96), "SDR", 86)
    bm.glitch_title(d, (left, 186), "SCANNER", 86)
    bm.divider(d, left, 292, left + width)

    bm.label(
        d, (left, 310),
        "SDR SPECTRUM  ·  FULL-RANGE SCANNER  ·  DRONE-BAND MONITOR",
        22, color=bm.WHITE,
    )
    bm.label(
        d, (left, 348),
        "PLUTO+ / HACKRF ONE / IQ FILES   ·   WINDOWS   ·   RECEIVE ONLY",
        17,
    )
    bm.label(
        d, (left, 376),
        "VFO · AM/FM/SSB/CW · IQ EVIDENCE · SIGNATURES · WHITE LIST",
        15,
    )
    bm.label(d, (left, 416), "github.com/MaxBond7/sdr-scanner", 15)
    bm.label(d, (W - 190, 416), f"REV {app_version()}", 15)

    # Right block: spectrum trace in a technical box.
    box = (980, 96, W - 64, 250)
    d.rectangle(box, outline=bm.FAINT, width=1)
    for index in range(1, 4):
        y = box[1] + (box[3] - box[1]) * index // 4
        d.line([(box[0], y), (box[2], y)], fill=(28, 28, 28, 255), width=1)
    bm.spectrum(d, (box[0] + 6, box[1] + 6, box[2] - 6, box[3] - 6))
    bm.label(d, (box[0] + 8, box[1] - 22), "SPECTRUM / dBFS", 12)
    bm.label(d, (box[2] - 96, box[1] - 22), "2.4 GHz", 12)

    d.rectangle([980, 286, W - 64, 340], outline=bm.FAINT, width=1)
    bm.barcode(d, (992, 296, W - 76, 330), seed=19)
    bm.label(d, (980, 348), "BINARY DRONE / NOT-DRONE   ·   MONO THEMES", 14)

    bm.dots(d, (980, 380, W - 64, 420), step=8)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, quality=95)
    print("written", OUT)


if __name__ == "__main__":
    main()
