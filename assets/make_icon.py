"""Generate the Pluto Scanner icon (ICO + PNG) in the monochrome style.

Black square, white spectrum bars, no colour, sharp geometry — the same
language as the ``mono`` theme and the boot splash.  Drawn directly at each
size so 16×16 stays crisp instead of becoming grey mush.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent
SIZES = (16, 24, 32, 48, 64, 128, 256)
MASTER = 1024

BLACK = (0, 0, 0, 255)
WHITE = (242, 242, 242, 255)


def make(size: int = MASTER) -> Image.Image:
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(image)

    radius = max(1, round(size * 0.10))
    d.rounded_rectangle([0, 0, size - 1, size - 1], radius=radius, fill=BLACK)

    # Bars: integer layout so every size keeps a 1 px gap instead of merging.
    # At 16 px four bars are too thin, so the smallest size uses three.
    heights = (
        (0.34, 0.86, 0.52) if size <= 20
        else (0.30, 0.58, 0.86, 0.46)
    )
    base_y = round(size * 0.80)
    start_px = round(size * 0.12)
    end_px = round(size * 0.90)
    total = max(4, end_px - start_px)
    gap = max(1, round(size * 0.04))
    bar_w = max(2, (total - gap * (len(heights) - 1)) // len(heights))
    last_right = start_px
    for index, height in enumerate(heights):
        left = start_px + index * (bar_w + gap)
        right = left + bar_w - 1
        top = round(base_y - height * size * 0.62)
        d.rectangle([left, top, right, base_y - 1], fill=WHITE)
        last_right = right

    # Baseline spans the whole bar group.
    line_h = max(1, round(size * 0.035))
    d.rectangle(
        [start_px, base_y, last_right, base_y + line_h - 1],
        fill=WHITE,
    )

    return image


def save_ico(path: Path, frames: list[Image.Image]) -> None:
    """Write a multi-size ICO with a PNG-compressed image per size.

    Pillow resizes one bitmap for every entry; drawing each size separately
    keeps 16×16 crisp, so the container is assembled by hand.
    """
    import io
    import struct

    payloads = []
    for frame in frames:
        buffer = io.BytesIO()
        frame.save(buffer, format="PNG")
        payloads.append(buffer.getvalue())

    header = struct.pack("<HHH", 0, 1, len(frames))
    offset = len(header) + 16 * len(frames)
    entries = b""
    for frame, payload in zip(frames, payloads):
        size = frame.width
        entries += struct.pack(
            "<BBBBHHII",
            0 if size >= 256 else size,
            0 if size >= 256 else size,
            0, 0, 1, 32, len(payload), offset,
        )
        offset += len(payload)
    path.write_bytes(header + entries + b"".join(payloads))


def main() -> None:
    master = make(MASTER)
    master.save(ROOT / "pluto_scanner.png")

    frames = [make(size) for size in SIZES]
    save_ico(ROOT / "pluto_scanner.ico", frames)
    print("icon written to", ROOT, "sizes", SIZES)


if __name__ == "__main__":
    main()
