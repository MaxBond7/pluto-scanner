"""Drawing helpers for the black-and-white ``mono`` brand assets.

Everything here is deliberately plain: 1 px white lines, a faint grid, a
ruler, a barcode and a noisy spectrum trace.  No colour, no gradients.
"""
from __future__ import annotations

import math
import random
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

WHITE = (255, 255, 255, 255)
DIM = (170, 170, 170, 255)
FAINT = (90, 90, 90, 255)
GRID = (18, 18, 18, 255)
BLACK = (0, 0, 0, 255)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / name,
        Path("/usr/share/fonts/truetype/liberation") / name,
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def mono(size: int, *, bold: bool = False) -> ImageFont.FreeTypeFont:
    names = ("consolab.ttf", "courbd.ttf") if bold else ("consola.ttf", "cour.ttf")
    for name in names:
        try:
            return font(name, size)
        except Exception:
            continue
    return font("DejaVuSansMono.ttf", size)


def canvas(width: int, height: int) -> Image.Image:
    image = Image.new("RGBA", (width, height), BLACK)
    draw = ImageDraw.Draw(image)
    for x in range(0, width, 40):
        draw.line([(x, 0), (x, height)], fill=GRID, width=1)
    for y in range(0, height, 40):
        draw.line([(0, y), (width, y)], fill=GRID, width=1)
    return image


def frame(draw: ImageDraw.ImageDraw, width: int, height: int, margin: int = 16,
          arm: int = 26) -> None:
    """Thin border with heavier corner brackets, like a plotter frame."""
    draw.rectangle(
        [margin, margin, width - margin, height - margin],
        outline=FAINT, width=1,
    )
    for x, y, dx, dy in (
        (margin, margin, 1, 1),
        (width - margin, margin, -1, 1),
        (margin, height - margin, 1, -1),
        (width - margin, height - margin, -1, -1),
    ):
        draw.line([(x, y), (x + dx * arm, y)], fill=WHITE, width=2)
        draw.line([(x, y), (x, y + dy * arm)], fill=WHITE, width=2)


def ruler(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int,
          *, step: int = 20, tall: int = 9) -> None:
    draw.line([(x0, y), (x1, y)], fill=FAINT, width=1)
    index = 0
    x = x0
    while x <= x1:
        length = tall if index % 5 == 0 else max(3, tall // 2)
        draw.line([(x, y), (x, y + length)], fill=FAINT, width=1)
        x += step
        index += 1


def barcode(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
            *, seed: int = 7) -> None:
    x0, y0, x1, y1 = box
    rng = random.Random(seed)
    x = x0
    while x < x1 - 2:
        width = rng.choice((1, 1, 2, 3, 4))
        gap = rng.choice((1, 2, 3, 5))
        if x + width > x1:
            break
        draw.rectangle([x, y0, x + width, y1], fill=WHITE)
        x += width + gap


def spectrum(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
             *, seed: int = 3, points: int = 220) -> None:
    """A noisy trace with a few peaks, like the app's own spectrum."""
    x0, y0, x1, y1 = box
    rng = random.Random(seed)
    peaks = [(rng.uniform(0.1, 0.9), rng.uniform(0.5, 1.0), rng.uniform(0.01, 0.035))
             for _ in range(5)]
    coords: list[tuple[int, int]] = []
    for index in range(points):
        t = index / (points - 1)
        value = 0.06 + rng.uniform(0.0, 0.035)
        for centre, height, width in peaks:
            value += height * math.exp(-((t - centre) ** 2) / (2 * width ** 2))
        value = min(1.0, value)
        coords.append((int(x0 + t * (x1 - x0)), int(y1 - value * (y1 - y0))))
    draw.line(coords, fill=WHITE, width=2)


def dots(draw: ImageDraw.ImageDraw, box: tuple[int, int, int, int],
         *, step: int = 9, seed: int = 11) -> None:
    """Halftone field used as a quiet decorative block."""
    x0, y0, x1, y1 = box
    rng = random.Random(seed)
    for y in range(y0, y1, step):
        for x in range(x0, x1, step):
            if rng.random() < 0.55:
                draw.point((x, y), fill=DIM)


def label(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
          size: int = 15, *, color=FAINT, bold: bool = False) -> None:
    draw.text(xy, text, font=mono(size, bold=bold), fill=color)


def glitch_title(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
                 size: int) -> int:
    """White monospace title with two faint offset copies behind it."""
    title_font = mono(size, bold=True)
    draw.text((xy[0] - 3, xy[1] + 2), text, font=title_font, fill=(60, 60, 60, 255))
    draw.text((xy[0] + 3, xy[1] - 1), text, font=title_font, fill=(110, 110, 110, 255))
    draw.text(xy, text, font=title_font, fill=WHITE)
    return int(draw.textlength(text, font=title_font))


def divider(draw: ImageDraw.ImageDraw, x0: int, y: int, x1: int) -> None:
    draw.line([(x0, y), (x1, y)], fill=WHITE, width=1)
    for x in range(x0, x1, 8):
        draw.line([(x, y + 3), (x + 4, y + 3)], fill=(50, 50, 50, 255), width=1)
