"""Generate the Pluto Scanner icon (ICO + PNG)."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SIZE = 256
BG = (7, 11, 22, 255)
BORDER = (34, 211, 238, 255)
CYAN = (34, 211, 238, 255)
PINK = (244, 114, 182, 255)
AMBER = (245, 158, 11, 255)
VIOLET = (167, 139, 250, 255)


def make(size: int = SIZE) -> Image.Image:
    im = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    pad = max(2, size // 24)
    radius = size // 5
    d.rounded_rectangle(
        [pad, pad, size - pad, size - pad],
        radius=radius, fill=BG, outline=BORDER, width=max(2, size // 32),
    )
    # spectrum bars
    bars = [
        (0.18, 0.40, 0.075, CYAN),
        (0.32, 0.62, 0.075, PINK),
        (0.46, 0.82, 0.080, AMBER),
        (0.60, 0.52, 0.075, VIOLET),
        (0.74, 0.70, 0.075, CYAN),
    ]
    baseline = int(size * 0.78)
    for x, h, w, color in bars:
        x0 = int(size * x)
        x1 = int(size * (x + w))
        y0 = int(size * (0.78 - h * 0.55))
        d.rounded_rectangle(
            [x0, y0, x1, baseline], radius=max(2, size // 50), fill=color
        )
    # baseline
    d.line(
        [(int(size * 0.14), baseline), (int(size * 0.86), baseline)],
        fill=BORDER, width=max(2, size // 48),
    )
    # small antenna dot
    d.ellipse(
        [int(size * 0.46), int(size * 0.14),
         int(size * 0.54), int(size * 0.22)],
        fill=PINK,
    )
    return im


def main() -> None:
    im = make(SIZE)
    im.save(ROOT / "pluto_scanner.png")
    sizes = [(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)]
    im.save(ROOT / "pluto_scanner.ico", sizes=sizes)
    print("icon written to", ROOT)


if __name__ == "__main__":
    main()
