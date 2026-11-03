"""Generate the GitHub social preview image in the monochrome ``mono`` style."""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "assets"))

import brand_mono as bm  # noqa: E402

OUT = ROOT / "assets" / "github_social_preview.png"
W, H = 1280, 640


def main() -> None:
    image = bm.canvas(W, H)
    d = bm.ImageDraw.Draw(image)

    bm.frame(d, W, H, margin=20)
    bm.ruler(d, 44, 48, W - 44, step=24, tall=10)

    left = 56
    bm.label(d, (left, 72), "CONSOLE // 001", 13)
    bm.label(d, (left + 210, 72), "PASSIVE RX ONLY", 13)

    bm.glitch_title(d, (left, 100), "PLUTO", 76)
    width = bm.glitch_title(d, (left, 178), "SCANNER", 76)
    bm.divider(d, left, 268, left + width)

    bm.label(
        d, (left, 286),
        "SDR SPECTRUM  ·  SCANNER  ·  DRONE-BAND MONITOR",
        19, color=bm.WHITE,
    )
    bm.label(
        d, (left, 318),
        "ADALM-PLUTO / PLUTO+   ·   WINDOWS   ·   325 MHz — 3.8 GHz",
        15,
    )

    # Spectrum panel.
    box = (56, 382, W - 56, 536)
    d.rectangle(box, outline=bm.FAINT, width=1)
    for index in range(1, 4):
        y = box[1] + (box[3] - box[1]) * index // 4
        d.line([(box[0], y), (box[2], y)], fill=(30, 30, 30, 255), width=1)
    bm.spectrum(d, (box[0] + 8, box[1] + 8, box[2] - 8, box[3] - 8), points=320)
    bm.label(d, (box[0] + 10, box[1] - 20), "LIVE / 433.920 MHz", 12)
    bm.label(d, (box[2] - 120, box[1] - 20), "FPS 12.5", 12)

    bm.barcode(d, (56, 556, 420, 588), seed=23)
    bm.label(d, (440, 558), "BINARY DRONE / NOT-DRONE", 14)
    bm.label(d, (440, 566), "MONO THEMES  ·  USER JSON", 14)

    bm.label(d, (W - 330, 558), "github.com/MaxBond7/pluto-scanner", 13)
    bm.label(d, (W - 130, 580), "REV 0.15.0", 13)

    bm.dots(d, (W - 360, 100, W - 70, 300), step=8, seed=5)

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, quality=95)
    print("written", OUT)


if __name__ == "__main__":
    main()
