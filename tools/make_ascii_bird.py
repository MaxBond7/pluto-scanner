"""Generate the ASCII bird used by the splash screen.

    python tools/make_ascii_bird.py

Draws a distant seagull silhouette with Pillow, blurs it and downsamples to a
62×18 intensity grid (0 = empty, 9 = solid).  The splash renders it through a
density ramp and animates individual characters, so the result looks soft and
dithered rather than a crisp silhouette.
"""
from __future__ import annotations

import math

from PIL import Image, ImageDraw, ImageFilter

COLS, ROWS = 62, 20
SCALE = 10
W, H = COLS * SCALE, ROWS * SCALE
RAMP = " .:-=+*#%@"


def draw_bird() -> Image.Image:
    image = Image.new("L", (W, H), 0)
    d = ImageDraw.Draw(image)

    def point(x: float, y: float) -> tuple[float, float]:
        return (x * W, y * H)

    # Two arcs meeting at the body: the classic "distant seagull" shape.
    for side in (-1, 1):
        points = []
        for index in range(81):
            t = index / 80.0
            x = 0.5 + side * 0.40 * t
            y = 0.64 - 0.30 * (math.sin(math.pi * t) ** 1.15)
            points.append(point(x, y))
        d.line(points, fill=250, width=6, joint="curve")

    # Body and head.
    d.ellipse([*point(0.470, 0.56), *point(0.530, 0.76)], fill=250)
    d.ellipse([*point(0.488, 0.515), *point(0.514, 0.565)], fill=250)
    return image.filter(ImageFilter.GaussianBlur(7))


def to_grid(image: Image.Image) -> list[str]:
    small = image.resize((COLS, ROWS), Image.Resampling.BOX)
    pixels = small.load()
    rows: list[str] = []
    for row in range(ROWS):
        digits = []
        for col in range(COLS):
            value = pixels[col, row] / 255.0
            value = max(0.0, (value - 0.03) / 0.97) ** 0.9
            digits.append(str(min(9, int(round(value * 9)))))
        rows.append("".join(digits))
    return rows


def main() -> int:
    grid = to_grid(draw_bird())
    print("ASCII bird preview:")
    for row in grid:
        print("".join(RAMP[int(ch)] for ch in row))
    print()
    print("BIRD_ART = [")
    for row in grid:
        print(f'    "{row}",')
    print("]")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
