"""Generate the GitHub social banner."""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "assets" / "github_banner.png"
W, H = 1600, 500
CYAN = (34, 211, 238, 255)
PINK = (244, 114, 182, 255)
TEXT = (226, 232, 240, 255)
MUTED = (148, 163, 184, 255)
DARK = (7, 11, 22, 255)


def font(name: str, size: int) -> ImageFont.FreeTypeFont:
    candidates = [
        Path(r"C:\Windows\Fonts") / name,
        Path("/usr/share/fonts/truetype/dejavu") / name,
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def main() -> None:
    background = Image.open(ROOT / "presentation" / "hero_bg.png").convert("RGBA")
    background = background.resize((W, int(background.height * W / background.width)))
    top = max(0, (background.height - H) // 2)
    banner = background.crop((0, top, W, top + H)).convert("RGBA")

    # Darken the left side so the text always has contrast.
    shade = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(W):
        alpha = int(210 * max(0.0, 1.0 - x / (W * 0.72)))
        sd.line([(x, 0), (x, H)], fill=(4, 8, 18, alpha))
    banner = Image.alpha_composite(banner, shade)
    d = ImageDraw.Draw(banner)

    # Accent lines.
    d.rectangle([0, 0, W, 4], fill=CYAN)
    d.rectangle([0, H - 4, W, H], fill=PINK)

    logo = Image.open(ROOT / "assets" / "pluto_scanner.png").convert("RGBA")
    logo.thumbnail((150, 150), Image.Resampling.LANCZOS)
    banner.alpha_composite(logo, (78, 78))

    d.text((250, 72), "PLUTO SCANNER", font=font("segoeuib.ttf", 66), fill=TEXT)
    d.text(
        (254, 152),
        "SDR spectrum  ·  full-range scanner  ·  drone-band monitor",
        font=font("segoeui.ttf", 25),
        fill=CYAN,
    )
    d.text(
        (254, 194),
        "ADALM-PLUTO / Pluto+   •   Windows desktop   •   passive RX only",
        font=font("segoeui.ttf", 21),
        fill=MUTED,
    )

    chips = [
        ("325 MHz – 3.8 GHz", CYAN),
        ("IQ evidence", PINK),
        ("84 tests", (74, 222, 128, 255)),
    ]
    x = 254
    for label, color in chips:
        f = font("segoeuib.ttf", 18)
        width = int(d.textlength(label, font=f)) + 34
        d.rounded_rectangle(
            [x, 258, x + width, 306], radius=24,
            fill=(11, 18, 34, 235), outline=color, width=2,
        )
        d.text((x + 17, 270), label, font=f, fill=color)
        x += width + 12

    d.text(
        (254, 350),
        "Software VFO  ·  AM/FM/SSB/CW  ·  IQ recording  ·  signatures  ·  white list",
        font=font("segoeui.ttf", 20),
        fill=TEXT,
    )
    d.text(
        (254, 392),
        "github.com/MaxBond7/pluto-scanner",
        font=font("segoeui.ttf", 19),
        fill=(100, 116, 139, 255),
    )

    OUT.parent.mkdir(parents=True, exist_ok=True)
    banner.convert("RGB").save(OUT, quality=95)
    print("written", OUT)


if __name__ == "__main__":
    main()
