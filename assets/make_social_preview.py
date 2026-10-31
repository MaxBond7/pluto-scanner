"""Generate a 1280x640 GitHub social preview image."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "github_social_preview.png"
W, H = 1280, 640
CYAN = (34, 211, 238, 255)
PINK = (244, 114, 182, 255)
TEXT = (226, 232, 240, 255)
MUTED = (148, 163, 184, 255)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    path = Path(r"C:\Windows\Fonts") / name
    if path.exists():
        return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def main() -> None:
    bg = Image.open(ROOT / "presentation" / "hero_bg.png").convert("RGBA")
    scale = max(W / bg.width, H / bg.height)
    bg = bg.resize((int(bg.width * scale) + 1, int(bg.height * scale) + 1))
    left = (bg.width - W) // 2
    top = (bg.height - H) // 2
    image = bg.crop((left, top, left + W, top + H)).convert("RGBA")

    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        alpha = int(220 * max(0.0, 1.0 - x / (W * 0.78)))
        sd.line([(x, 0), (x, H)], fill=(4, 8, 18, alpha))
    image = Image.alpha_composite(image, shade)
    d = ImageDraw.Draw(image)

    d.rectangle([0, 0, W, 5], fill=CYAN)
    d.rectangle([0, H - 5, W, H], fill=PINK)

    logo = Image.open(ROOT / "assets" / "pluto_scanner.png").convert("RGBA")
    logo.thumbnail((190, 190), Image.Resampling.LANCZOS)
    image.alpha_composite(logo, (70, 80))

    d.text((300, 82), "PLUTO SCANNER", font=font("segoeuib.ttf", 72), fill=TEXT)
    d.text(
        (304, 174),
        "SDR spectrum  ·  scanner  ·  drone-band monitor",
        font=font("segoeui.ttf", 26),
        fill=CYAN,
    )
    d.text(
        (304, 218),
        "ADALM-PLUTO / Pluto+   •   Windows   •   passive RX",
        font=font("segoeui.ttf", 22),
        fill=MUTED,
    )

    chips = [("325 MHz – 3.8 GHz", CYAN), ("IQ evidence", PINK),
             ("84 tests", (74, 222, 128, 255))]
    x = 304
    for label, color in chips:
        f = font("segoeuib.ttf", 18)
        width = int(d.textlength(label, font=f)) + 34
        d.rounded_rectangle(
            [x, 282, x + width, 330], radius=24,
            fill=(11, 18, 34, 235), outline=color, width=2,
        )
        d.text((x + 17, 294), label, font=f, fill=color)
        x += width + 12

    d.text(
        (304, 382),
        "VFO  ·  AM/FM/SSB/CW  ·  band scanner  ·  IQ evidence",
        font=font("segoeui.ttf", 21),
        fill=TEXT,
    )
    d.text(
        (304, 424),
        "github.com/MaxBond7/pluto-scanner",
        font=font("segoeui.ttf", 20),
        fill=(100, 116, 139, 255),
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    image.convert("RGB").save(OUT, quality=95)
    print("written", OUT)


if __name__ == "__main__":
    main()
