"""Generate the diagrams used by the Pluto Scanner presentation.

Everything is drawn locally with Pillow so the deck has no external image
dependencies and can be rebuilt with one command.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image, ImageDraw, ImageFilter, ImageFont

ROOT = Path(__file__).resolve().parent
W, H = 1600, 900
BG = (7, 11, 22)
PANEL = (13, 20, 38)
PANEL2 = (17, 27, 48)
LINE = (34, 48, 74)
TEXT = (219, 231, 245)
MUTED = (143, 166, 192)
CYAN = (34, 211, 238)
PINK = (244, 114, 182)
AMBER = (245, 158, 11)
GREEN = (74, 222, 128)
RED = (248, 113, 113)
VIOLET = (167, 139, 250)

SEGOE = "C:/Windows/Fonts/segoeui.ttf"
SEGOE_B = "C:/Windows/Fonts/segoeuib.ttf"
CONSOLA = "C:/Windows/Fonts/consola.ttf"


def font(size: int, bold: bool = False, mono: bool = False) -> ImageFont.FreeTypeFont:
    path = CONSOLA if mono else (SEGOE_B if bold else SEGOE)
    return ImageFont.truetype(path, size)


def make_bg(w: int = W, h: int = H, grid: bool = True) -> Image.Image:
    im = Image.new("RGB", (w, h), BG)
    draw = ImageDraw.Draw(im)
    # subtle vertical gradient
    for y in range(h):
        t = y / max(1, h - 1)
        r = int(7 + 5 * t)
        g = int(11 + 8 * t)
        b = int(22 + 14 * t)
        draw.line([(0, y), (w, y)], fill=(r, g, b))
    if grid:
        for x in range(0, w, 80):
            draw.line([(x, 0), (x, h)], fill=(14, 22, 38), width=1)
        for y in range(0, h, 80):
            draw.line([(0, y), (w, y)], fill=(14, 22, 38), width=1)
        for x in range(0, w, 320):
            draw.line([(x, 0), (x, h)], fill=(20, 31, 51), width=1)
        for y in range(0, h, 320):
            draw.line([(0, y), (w, y)], fill=(20, 31, 51), width=1)

    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse([-260, -260, 620, 620], fill=(34, 211, 238, 34))
    gd.ellipse([w - 560, h - 500, w + 180, h + 180], fill=(244, 114, 182, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(110))
    im = Image.alpha_composite(im.convert("RGBA"), glow).convert("RGB")
    return im


def top_accent(im: Image.Image) -> None:
    draw = ImageDraw.Draw(im)
    w = im.width
    for x in range(w):
        t = x / max(1, w - 1)
        c = (
            int(CYAN[0] * (1 - t) + PINK[0] * t),
            int(CYAN[1] * (1 - t) + PINK[1] * t),
            int(CYAN[2] * (1 - t) + PINK[2] * t),
        )
        draw.line([(x, 0), (x, 3)], fill=c)


def header(im: Image.Image, kicker: str, title: str) -> None:
    d = ImageDraw.Draw(im)
    d.text((80, 58), kicker.upper(), font=font(18, True), fill=CYAN)
    d.text((80, 88), title, font=font(48, True), fill=TEXT)
    d.line([(80, 158), (im.width - 80, 158)], fill=(34, 211, 238), width=1)


def wrap(draw: ImageDraw.ImageDraw, text: str, f: ImageFont.FreeTypeFont,
         max_w: int) -> list[str]:
    words = text.split()
    lines: list[str] = []
    current = ""
    for word in words:
        trial = word if not current else current + " " + word
        if draw.textlength(trial, font=f) <= max_w:
            current = trial
        else:
            if current:
                lines.append(current)
            current = word
    if current:
        lines.append(current)
    return lines


def para(draw: ImageDraw.ImageDraw, xy: tuple[int, int], width: int,
         text: str, f: ImageFont.FreeTypeFont, fill=TEXT,
         gap: int = 8) -> int:
    x, y = xy
    line_h = int(f.size * 1.35)
    for line in wrap(draw, text, f, width):
        draw.text((x, y), line, font=f, fill=fill)
        y += line_h
    return y + gap


def box(draw: ImageDraw.ImageDraw, xy: tuple[int, int, int, int],
        fill=PANEL, outline=LINE, radius: int = 18, width: int = 2) -> None:
    draw.rounded_rectangle(xy, radius=radius, fill=fill, outline=outline,
                           width=width)


def arrow(draw: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int,
          color=CYAN, width: int = 3) -> None:
    draw.line([(x1, y1), (x2, y2)], fill=color, width=width)
    import math
    ang = math.atan2(y2 - y1, x2 - x1)
    size = 13
    left = (x2 - size * math.cos(ang - 0.5), y2 - size * math.sin(ang - 0.5))
    right = (x2 - size * math.cos(ang + 0.5), y2 - size * math.sin(ang + 0.5))
    draw.polygon([(x2, y2), left, right], fill=color)


def chip(draw: ImageDraw.ImageDraw, xy: tuple[int, int], text: str,
         color=CYAN, size: int = 17) -> int:
    f = font(size, True)
    tw = int(draw.textlength(text, font=f))
    x, y = xy
    draw.rounded_rectangle([x, y, x + tw + 26, y + 34], radius=17,
                           fill=(int(color[0] * .12), int(color[1] * .12),
                                 int(color[2] * .12)),
                           outline=color, width=2)
    draw.text((x + 13, y + 7), text, font=f, fill=color)
    return x + tw + 38


def save(im: Image.Image, name: str) -> None:
    top_accent(im)
    im.save(ROOT / name, quality=95)


# --------------------------------------------------------------------- hero
def hero() -> None:
    w, h = 1920, 1080
    im = make_bg(w, h)
    d = ImageDraw.Draw(im)

    # darken the left half for the title
    shade = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    for x in range(w // 2 + 240):
        a = int(185 * max(0.0, 1.0 - x / (w * 0.56)))
        sd.line([(x, 0), (x, h)], fill=(4, 7, 15, a))
    im = Image.alpha_composite(im.convert("RGBA"), shade).convert("RGB")
    d = ImageDraw.Draw(im)

    # waterfall-ish vertical strips on the right
    import random
    rnd = random.Random(7)
    for i in range(150):
        x = int(w * 0.52 + i * (w * 0.47) / 150)
        height = rnd.randint(30, 230)
        color = (34, 211, 238) if i % 5 else (244, 114, 182)
        alpha_im = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        ad = ImageDraw.Draw(alpha_im)
        ad.rectangle([x, h - 250 - height, x + 4, h - 250], fill=(*color, 38))
        im = Image.alpha_composite(im.convert("RGBA"), alpha_im).convert("RGB")
    d = ImageDraw.Draw(im)

    # spectrum curve
    import math
    pts = []
    for i in range(420):
        x = w * 0.48 + i * (w * 0.50) / 420
        t = i / 420
        y = h * 0.61
        y -= 85 * math.exp(-((t - .13) / .035) ** 2)
        y -= 140 * math.exp(-((t - .31) / .018) ** 2)
        y -= 55 * math.exp(-((t - .45) / .06) ** 2)
        y -= 170 * math.exp(-((t - .62) / .015) ** 2)
        y -= 70 * math.exp(-((t - .78) / .05) ** 2)
        y -= 90 * math.exp(-((t - .90) / .02) ** 2)
        y += 8 * math.sin(i * .33) + rnd.uniform(-5, 5)
        pts.append((x, y))
    d.line(pts, fill=CYAN, width=4)
    # glow line
    glow = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.line(pts, fill=(34, 211, 238, 95), width=12)
    glow = glow.filter(ImageFilter.GaussianBlur(8))
    im = Image.alpha_composite(im.convert("RGBA"), glow).convert("RGB")
    save(im, "hero_bg.png")


# ---------------------------------------------------------------- evolution
def evolution() -> None:
    im = make_bg()
    header(im, "Как развивалось", "От архива на React до рабочего SDR-инструмента")
    d = ImageDraw.Draw(im)
    items = [
        ("01", "OLD/", "Старый React/TypeScript-проект. Архив, не изменялся.", MUTED),
        ("02", "Python MVP", "Симулятор IQ → спектр → детектор → контакты → VFO → демодуляция.", CYAN),
        ("03", "Реальный Pluto", "pyadi-iio, USB, 12-битные отсчёты, стабильность, исправление ошибок.", AMBER),
        ("04", "Реальный сканер", "325 МГц – 3.8 ГГц, живой график, JSON-фон, автосравнение.", VIOLET),
        ("05", "Дрон-монитор", "Быстрый обзор полос, временные признаки, классы, тревоги, два SDR.", PINK),
        ("06", "Стабилизация", "57 тестов, реальные Pluto+, USB-ограничения, строгие тревоги.", GREEN),
    ]
    x_line = 180
    top, bottom = 210, 790
    d.line([(x_line, top), (x_line, bottom)], fill=(34, 211, 238), width=2)
    ys = [top + i * (bottom - top) / (len(items) - 1) for i in range(len(items))]
    for (num, name, desc, color), y in zip(items, ys):
        d.ellipse([x_line - 25, y - 25, x_line + 25, y + 25],
                  fill=PANEL2, outline=color, width=3)
        d.text((x_line, y), num, font=font(17, True), fill=color, anchor="mm")
        d.text((x_line + 52, y - 30), name, font=font(28, True), fill=color)
        para(d, (x_line + 52, y + 8), 1180, desc, font(19), MUTED, gap=0)
    save(im, "diagram_evolution.png")


# --------------------------------------------------------------- architecture
def architecture() -> None:
    im = make_bg()
    header(im, "Архитектура", "Один поток на устройство, общий GUI")
    d = ImageDraw.Draw(im)

    def label_box(x, y, w, h, title, sub, color=CYAN):
        box(d, (x, y, x + w, y + h), PANEL, color, 16, 2)
        d.text((x + 18, y + 13), title, font=font(21, True), fill=color)
        d.multiline_text((x + 18, y + 48), sub, font=font(14), fill=MUTED,
                         spacing=4)

    label_box(80, 200, 190, 105, "IQ", "Pluto / sim\n20.48 MS/s", AMBER)
    label_box(340, 185, 270, 135, "DeviceSession",
              "спектр · детектор\nтрекер · VFO · demod", CYAN)
    label_box(690, 185, 290, 135, "DSP / UI",
              "SpectrumFrame\ncontacts · audio", VIOLET)
    label_box(1060, 185, 460, 135, "GUI",
              "Контакты · Сканер\nДрон-монитор", GREEN)

    arrow(d, 270, 252, 338, 252, CYAN)
    arrow(d, 610, 252, 688, 252, CYAN)
    arrow(d, 980, 252, 1058, 252, CYAN)

    label_box(340, 390, 270, 105, "VFO / demod", "цифровой перенос\nAM/FM/SSB/CW", PINK)
    arrow(d, 475, 322, 475, 388, PINK)

    label_box(80, 590, 420, 190, "Сканер диапазона",
              "ScanController → peaks\nrecorder → compare\n325 МГц – 3.8 ГГц", VIOLET)
    label_box(560, 590, 430, 190, "Дрон-монитор",
              "DroneWatchController\nfeatures → tracker\nrecorder + manager", PINK)
    label_box(1050, 590, 470, 190, "Хранилище",
              "scan_logs/ · drone_logs/\nbackground.json · summary.json\nevents.jsonl", GREEN)
    arrow(d, 500, 642, 558, 642, VIOLET)
    arrow(d, 990, 642, 1048, 642, GREEN)
    save(im, "diagram_architecture.png")


# ------------------------------------------------------------------- scanner
def scanner() -> None:
    im = make_bg()
    header(im, "Геометрия свипа", "Захваченные полосы покрывают диапазон без дыр")
    d = ImageDraw.Draw(im)
    # formula card
    box(d, (80, 190, 710, 305), PANEL, LINE, 14, 2)
    d.text((105, 208), "Центры LO", font=font(20, True), fill=CYAN)
    d.text((105, 245), "first = start + sample_rate / 2", font=font(20, True, mono=True), fill=TEXT)
    d.text((105, 277), "last  = end   - sample_rate / 2", font=font(20, True, mono=True), fill=TEXT)

    # axis
    ax0, ax1, ay = 150, 1440, 690
    d.line([(ax0, ay), (ax1, ay)], fill=MUTED, width=3)
    for frac, label in ((0, "325 МГц"), (.24, "1 ГГц"), (.48, "2 ГГц"),
                        (.72, "3 ГГц"), (1, "3.8 ГГц")):
        x = int(ax0 + frac * (ax1 - ax0))
        d.line([(x, ay - 10), (x, ay + 10)], fill=MUTED, width=2)
        d.text((x, ay + 20), label, font=font(16), fill=MUTED, anchor="ma")

    # illustrative chunks
    colors = [CYAN, (56, 189, 248), VIOLET, PINK, AMBER, GREEN, CYAN, VIOLET]
    n = 8
    for i in range(n):
        cx = ax0 + 62 + int(i * (ax1 - ax0 - 124) / (n - 1))
        cw = 190
        x0, x1 = cx - cw // 2, cx + cw // 2
        y0 = 505 + (i % 2) * 40
        color = colors[i % len(colors)]
        box(d, (x0, y0, x1, y0 + 70), (10, 18, 34), color, 10, 2)
        d.text((cx, y0 + 20), f"LO {i + 1}", font=font(17, True), fill=color, anchor="ma")
        d.text((cx, y0 + 45), "полоса захвата", font=font(13), fill=MUTED, anchor="ma")
        d.line([(cx, y0 + 72), (cx, ay - 6)], fill=color + (90,) if len(color) == 3 else color,
               width=1)

    # start/end brackets
    d.line([(ax0, 805), (ax0, 830)], fill=CYAN, width=2)
    d.line([(ax1, 805), (ax1, 830)], fill=CYAN, width=2)
    d.line([(ax0, 818), (ax1, 818)], fill=CYAN, width=1)
    d.text(((ax0 + ax1) // 2, 842), "захват покрывает весь заданный диапазон",
           font=font(17), fill=CYAN, anchor="ma")
    d.text((80, 350), "Схема, не в масштабе. Реальный шаг — 0.8 полосы захвата.",
           font=font(16), fill=MUTED)
    save(im, "diagram_scanner.png")


# --------------------------------------------------------------------- drone
def drone() -> None:
    im = make_bg()
    header(im, "Дрон-монитор", "От IQ до подтверждённой тревоги")
    d = ImageDraw.Draw(im)

    boxes = [
        ("IQ block", "20 мс блок\n40 мс на кусок", AMBER),
        ("PSD + envelope", "спектр +\nогибающая", CYAN),
        ("Features", "BW · duty\nbursts · SNR", VIOLET),
        ("Classifier", "FHSS · TELEMETRY\nVIDEO · WIFI · NARROW", PINK),
        ("Tracker", "слияние событий\nхиты · время", GREEN),
        ("Alarm / log", "3 hits + 70%\nJSON + баннер", RED),
    ]
    x0 = 70
    y0 = 210
    bw, bh, gap = 225, 145, 25
    for i, (title, sub, color) in enumerate(boxes):
        x = x0 + i * (bw + gap)
        box(d, (x, y0, x + bw, y0 + bh), PANEL, color, 16, 2)
        d.text((x + 16, y0 + 14), title, font=font(20, True), fill=color)
        d.multiline_text((x + 16, y0 + 54), sub, font=font(14), fill=MUTED,
                         spacing=5)
        if i:
            arrow(d, x - gap, y0 + bh // 2, x - 4, y0 + bh // 2, color)

    # classes row
    d.text((70, 405), "классы", font=font(17, True), fill=MUTED)
    x = 70
    for text, color in (("FHSS", RED), ("TELEMETRY", AMBER),
                        ("VIDEO", PINK), ("WIFI", MUTED), ("NARROW", CYAN)):
        x = chip(d, (x, 438), text, color, 16)
    d.text((70, 492), "WIFI и NARROW не поднимают тревогу — только кандидаты",
           font=font(16), fill=MUTED)

    # confirmation box under the right side
    box(d, (930, 560, 1490, 680), PANEL, RED, 14, 2)
    d.text((954, 576), "Подтверждение тревоги", font=font(20, True), fill=RED)
    d.text((954, 612), "3 попадания + уверенность 70%", font=font(19, True),
           fill=TEXT)
    d.text((954, 644), "иначе — только кандидат в таблице", font=font(15),
           fill=MUTED)
    arrow(d, 1370, 560, 1370, 365, RED)

    d.text((70, 750), "Кандидат → оранжевый · подтверждённая тревога → красный + звук",
           font=font(16), fill=MUTED)
    save(im, "diagram_drone.png")


# --------------------------------------------------------------------- bands
def bands() -> None:
    im = make_bg()
    header(im, "Полосы", "Что именно слушает дрон-монитор")
    d = ImageDraw.Draw(im)

    max_ghz = 6.2
    ax0, ax1 = 420, 1470
    top, row_h = 225, 87
    rows = [
        ("433 МГц", "пульты, телеметрия, LPD", .433, .020, AMBER),
        ("868 МГц", "EU ISM, телеметрия", .863, .007, AMBER),
        ("915 МГц", "US ISM, пульты", .902, .026, AMBER),
        ("1.2–1.3 ГГц", "аналоговое и цифровое видео", 1.08, .24, VIOLET),
        ("2.4 ГГц", "управление, видео, Wi-Fi", 2.40, .0835, CYAN),
        ("5.8 ГГц", "FPV-видео, часть управления", 5.725, .15, PINK),
    ]

    def xpos(ghz: float) -> int:
        return int(ax0 + ghz / max_ghz * (ax1 - ax0))

    # stock range shading
    sx0, sx1 = xpos(.325), xpos(3.8)
    d.rectangle([sx0, top - 20, sx1, top + row_h * len(rows) - 12],
                fill=(10, 19, 31))
    d.line([(sx0, top - 20), (sx0, top + row_h * len(rows) - 12)],
           fill=(74, 222, 128, 90), width=1)
    d.line([(sx1, top - 20), (sx1, top + row_h * len(rows) - 12)],
           fill=(74, 222, 128, 90), width=1)

    for i, (name, desc, start, width, color) in enumerate(rows):
        y = top + i * row_h
        d.text((80, y + 3), name, font=font(21, True), fill=color)
        d.text((80, y + 33), desc, font=font(14), fill=MUTED)
        x0, x1 = xpos(start), xpos(start + width)
        w = max(16, x1 - x0)
        box(d, (x0, y + 10, x0 + w, y + 48), (11, 19, 34), color, 8, 2)
        if w > 100:
            d.text((x0 + 10, y + 20), f"{start:g}–{start + width:g} ГГц",
                   font=font(14, True), fill=color)
        else:
            d.text((x0 + w + 12, y + 18), f"{start * 1000:.0f} МГц",
                   font=font(14), fill=color)

    # axis
    ay = top + row_h * len(rows) + 2
    d.line([(ax0, ay), (ax1, ay)], fill=MUTED, width=2)
    for ghz in (0.325, 0.9, 1.2, 2.4, 3.8, 5.8):
        x = xpos(ghz)
        d.line([(x, ay - 8), (x, ay + 8)], fill=MUTED, width=2)
        label = f"{ghz:g}"
        d.text((x, ay + 16), label, font=font(14), fill=MUTED, anchor="ma")
    d.text(((ax0 + ax1) // 2, ay + 44), "ГГц", font=font(14), fill=MUTED, anchor="ma")

    # stock bracket
    by = ay + 78
    d.line([(sx0, by), (sx1, by)], fill=GREEN, width=2)
    d.line([(sx0, by - 7), (sx0, by + 7)], fill=GREEN, width=2)
    d.line([(sx1, by - 7), (sx1, by + 7)], fill=GREEN, width=2)
    d.text(((sx0 + sx1) // 2, by + 12), "stock Pluto: 325 МГц – 3.8 ГГц",
           font=font(15), fill=GREEN, anchor="ma")

    # 5.8 note
    d.text((xpos(5.725), ay + 44), "5.8 — Pluto+ / расширенный диапазон",
           font=font(14), fill=PINK, anchor="ma")
    save(im, "diagram_bands.png")


# ------------------------------------------------------------------ two SDR
def two_sdr() -> None:
    im = make_bg()
    header(im, "Два Pluto+", "Скорость против покрытия")
    d = ImageDraw.Draw(im)

    # left panel
    box(d, (60, 190, 760, 790), PANEL, LINE, 18, 2)
    d.text((88, 208), "Одна USB-шина", font=font(26, True), fill=CYAN)
    d.text((88, 246), "общий контроллер / 480 Мбит/с", font=font(16), fill=MUTED)
    for i, (x, name) in enumerate(((130, "Pluto 1"), (450, "Pluto 2"))):
        box(d, (x, 310, x + 180, 405), (10, 18, 34), CYAN, 12, 2)
        d.text((x + 90, 338), name, font=font(19, True), fill=CYAN, anchor="ma")
        d.text((x + 90, 366), "10.24 MS/s", font=font(15), fill=TEXT, anchor="ma")
        arrow(d, x + 90, 407, x + 90, 492, CYAN)
    box(d, (150, 495, 610, 570), (10, 18, 34), MUTED, 10, 2)
    d.text((380, 516), "USB 2.0 / общая шина", font=font(19, True), fill=TEXT, anchor="ma")
    d.text((380, 543), "2 × 10.24 ≈ 20.48 суммарно", font=font(15), fill=GREEN, anchor="ma")
    d.text((88, 620), "стабильно: 10.24", font=font(21, True), fill=GREEN)
    d.text((88, 655), "риск: 20.48 на каждом", font=font(21, True), fill=RED)
    para(d, (88, 692), 620, "10 с работают, 30 с — одно устройство отваливается с Broken pipe.", font(16), MUTED)

    # right panel
    box(d, (840, 190, 1540, 790), PANEL, LINE, 18, 2)
    d.text((868, 208), "Ethernet / разные контроллеры", font=font(24, True), fill=PINK)
    d.text((868, 246), "у каждого своя полоса", font=font(16), fill=MUTED)
    for i, (x, name) in enumerate(((900, "Pluto 1"), (1200, "Pluto 2"))):
        box(d, (x, 310, x + 180, 405), (10, 18, 34), PINK, 12, 2)
        d.text((x + 90, 338), name, font=font(19, True), fill=PINK, anchor="ma")
        d.text((x + 90, 366), "20.48 MS/s", font=font(15), fill=TEXT, anchor="ma")
        arrow(d, x + 90, 407, x + 90, 492, PINK)
    box(d, (930, 495, 1450, 570), (10, 18, 34), GREEN, 10, 2)
    d.text((1190, 516), "2 × 20.48 ≈ 40.96 суммарно", font=font(18, True), fill=GREEN, anchor="ma")
    d.text((1190, 543), "реальный прирост скорости", font=font(15), fill=MUTED, anchor="ma")
    d.text((868, 620), "цель: 2 × 20.48", font=font(21, True), fill=GREEN)
    para(d, (868, 660), 620, "Gigabit Ethernet на Pluto+ — предпочтительный вариант для двух приёмников.", font(16), MUTED)
    save(im, "diagram_two_sdr.png")


# ------------------------------------------------------------------- compare
def compare() -> None:
    im = make_bg()
    header(im, "Сравнение фонов", "Как не превратить Wi-Fi в «новый контакт»")
    d = ImageDraw.Draw(im)

    def b(x, y, w, h, title, sub, color):
        box(d, (x, y, x + w, y + h), PANEL, color, 14, 2)
        d.text((x + 16, y + 12), title, font=font(19, True), fill=color)
        d.multiline_text((x + 16, y + 44), sub, font=font(14), fill=MUTED,
                         spacing=4)

    b(70, 190, 350, 120, "background.json",
      "старый фон: пики + max-hold\n+ диапазон + устройство", CYAN)
    b(70, 350, 350, 120, "новый скан",
      "свежие пики + max-hold\n+ диапазон + устройство", PINK)
    b(490, 250, 330, 145, "проверка совместимости",
      "тип устройства · усиление\nформат · пересечение", AMBER)
    b(900, 175, 430, 120, "peak matching",
      "новый пик без пары → новый контакт", GREEN)
    b(900, 330, 430, 120, "spectrum rise",
      "подъём max-hold → широкополосное изменение", VIOLET)
    b(900, 560, 430, 130, "compare.json",
      "new · stronger · rises\nwarnings · summary", GREEN)

    arrow(d, 420, 250, 488, 300, CYAN)
    arrow(d, 420, 410, 488, 360, PINK)
    arrow(d, 820, 300, 898, 235, GREEN)
    arrow(d, 820, 350, 898, 390, VIOLET)

    # right-side bus from both tests into compare.json
    bus_x = 1390
    d.line([(1332, 235), (bus_x, 235)], fill=GREEN, width=3)
    d.line([(1332, 390), (bus_x, 390)], fill=VIOLET, width=3)
    d.line([(bus_x, 235), (bus_x, 625)], fill=GREEN, width=3)
    d.line([(bus_x, 625), (1332, 625)], fill=GREEN, width=3)
    d.polygon([(1332, 625), (1346, 617), (1346, 633)], fill=GREEN)

    d.text((70, 530), "Фон вне пересечения диапазонов", font=font(17, True), fill=MUTED)
    d.text((70, 562), "не считается новым контактом", font=font(17, True), fill=RED)
    d.text((70, 612), "Фон с другим устройством/усилением", font=font(17, True), fill=MUTED)
    d.text((70, 644), "автосравнение пропускается", font=font(17, True), fill=RED)
    save(im, "diagram_compare.png")


# --------------------------------------------------------------- signatures
def signatures() -> None:
    im = make_bg()
    header(im, "Библиотека сигнатур", "От признаков к гипотезе, а не к гаданию")
    d = ImageDraw.Draw(im)

    box(d, (60, 190, 470, 720), PANEL, CYAN, 18, 2)
    d.text((88, 210), "Событие", font=font(26, True), fill=CYAN)
    d.text((88, 248), "что измерили", font=font(15), fill=MUTED)
    items = [
        "частота и диапазон",
        "занятая ширина",
        "скважность",
        "длительность посылок",
        "класс: FHSS / TELEMETRY / VIDEO",
        "hop-профиль",
    ]
    y = 310
    for item in items:
        d.ellipse([88, y + 7, 100, y + 19], fill=CYAN)
        d.text((118, y), item, font=font(17), fill=TEXT)
        y += 58

    box(d, (535, 190, 1035, 720), PANEL, PINK, 18, 2)
    d.text((563, 210), "Матчер", font=font(26, True), fill=PINK)
    d.text((563, 248), "взвешенное совпадение", font=font(15), fill=MUTED)
    weights = [
        ("диапазон", "45%"), ("ширина", "25%"),
        ("скважность", "15%"), ("класс", "15%"),
    ]
    y = 315
    for name, weight in weights:
        d.text((563, y), name, font=font(18, True), fill=TEXT)
        d.text((930, y), weight, font=font(18, True), fill=PINK, anchor="ra")
        d.line([(563, y + 32), (990, y + 32)], fill=(60, 40, 65), width=2)
        y += 62
    d.text((563, 585), "top-3 гипотезы", font=font(18, True), fill=GREEN)
    d.text((563, 620), "score + причины + ссылка", font=font(15), fill=MUTED)

    box(d, (1100, 190, 1540, 720), PANEL, VIOLET, 18, 2)
    d.text((1128, 210), "SQLite", font=font(26, True), fill=VIOLET)
    d.text((1128, 248), "локальная база", font=font(15), fill=MUTED)
    entries = [
        "Wi-Fi 2.4 / 5", "Bluetooth / BLE", "Zigbee",
        "RC / FHSS", "LoRa / SiK", "FPV видео",
        "OcuSync family", "ADS-B / AIS / GPS",
    ]
    y = 310
    for item in entries:
        d.text((1128, y), "•", font=font(18, True), fill=VIOLET)
        d.text((1152, y), item, font=font(17), fill=TEXT)
        y += 45
    d.text((1128, 680), "импорт/экспорт JSON/CSV", font=font(14), fill=MUTED)

    arrow(d, 472, 455, 533, 455, CYAN)
    arrow(d, 1098, 455, 1037, 455, VIOLET)

    box(d, (60, 755, 1540, 855), PANEL2, GREEN, 14, 2)
    d.text((84, 772), "Пример:", font=font(17, True), fill=GREEN)
    d.text((170, 772),
           "Zigbee 86%  ·  RC-пульт 86%  ·  BLE 85%",
           font=font(18, True), fill=TEXT)
    d.text((84, 812),
           "Это гипотезы по форме сигнала. Модель дрона — только через "
           "протокол, Remote ID или размеченный датасет.",
           font=font(14), fill=MUTED)
    save(im, "diagram_signatures.png")


# ------------------------------------------------------------------- quality
def quality() -> None:
    im = make_bg()
    header(im, "Качество", "69 тестов и живые Pluto+")
    d = ImageDraw.Draw(im)

    metrics = [
        ("69", "автотестов", "DSP · сканер · дрон · сигнатуры · белый список", CYAN),
        ("2", "реальных Pluto+", "IQ · спектр · 2.4/5.8 ГГц", PINK),
        ("10.24", "MS/s стабильно", "два USB-устройства", GREEN),
        ("5.8", "ГГц проверено", "LO + IQ на Pluto+", AMBER),
    ]
    for i, (num, label, sub, color) in enumerate(metrics):
        x = 70 + i * 375
        box(d, (x, 190, x + 340, 355), PANEL, color, 16, 2)
        d.text((x + 26, 208), num, font=font(52, True), fill=color)
        d.text((x + 26, 275), label, font=font(19, True), fill=TEXT)
        d.text((x + 26, 309), sub, font=font(14), fill=MUTED)

    box(d, (70, 400, 760, 790), PANEL, LINE, 16, 2)
    d.text((96, 420), "Проверено", font=font(24, True), fill=CYAN)
    checks = [
        "Симулятор: полный тракт и события",
        "Реальный Pluto+: IQ, спектр, свип",
        "2.4/5.8 ГГц, один и два SDR",
        "JSON-фон и сравнение",
        "IQ-фрагменты и карточка события",
        "Белый список и профили фона",
        "Ярлык Windows без терминала",
    ]
    y = 475
    for item in checks:
        d.line([(98, y + 11), (104, y + 17), (115, y + 3)],
               fill=GREEN, width=3)
        d.text((126, y), item, font=font(17), fill=TEXT)
        y += 46

    box(d, (810, 400, 1530, 790), PANEL, LINE, 16, 2)
    d.text((836, 420), "Что исправляли", font=font(24, True), fill=PINK)
    fixed = [
        "Демо-сканер → реальный свип",
        "NaN на графике, ResizeMode",
        "Устаревшие кадры при перестройке LO",
        "Аудио во время сканирования",
        "Ложные контакты и ложные тревоги",
        "USB Broken pipe → понятная ошибка",
    ]
    y = 475
    for item in fixed:
        d.text((838, y), "•", font=font(18, True), fill=PINK)
        d.text((864, y), item, font=font(17), fill=TEXT)
        y += 48
    save(im, "diagram_quality.png")


# -------------------------------------------------------------------- limits
def limits() -> None:
    im = make_bg()
    header(im, "Ограничения", "Что можно и чего нельзя одним Pluto")
    d = ImageDraw.Draw(im)

    box(d, (70, 190, 760, 780), PANEL, GREEN, 18, 2)
    d.text((100, 212), "Можно измерить", font=font(28, True), fill=GREEN)
    can = [
        "частоту и занятую ширину",
        "уровень и SNR относительно шума",
        "временную структуру: импульсы, скважность",
        "форму спектра и грубую модуляцию",
        "сам факт излучения в полосе",
        "сравнить с сохранённым фоном",
    ]
    y = 285
    for item in can:
        d.line([(100, y + 11), (106, y + 17), (117, y + 3)],
               fill=GREEN, width=3)
        d.text((132, y), item, font=font(18), fill=TEXT)
        y += 66

    box(d, (840, 190, 1530, 780), PANEL, RED, 18, 2)
    d.text((870, 212), "Нельзя без доп. железа", font=font(26, True), fill=RED)
    cannot = [
        "модель дрона и протокол",
        "направление (пеленг)",
        "дальность до цели",
        "Remote ID",
        "декодирование видео и команд",
        "абсолютную мощность в dBm",
    ]
    y = 285
    for item in cannot:
        d.line([(870, y + 8), (892, y + 30)], fill=RED, width=3)
        d.line([(892, y + 8), (870, y + 30)], fill=RED, width=3)
        d.text((916, y), item, font=font(18), fill=TEXT)
        y += 66

    d.text((70, 825), "Пассивный приём: только сигнал, не радар и не декодер.",
           font=font(17), fill=AMBER)
    d.text((840, 825), "dBFS — относительный уровень, не dBm.",
           font=font(17), fill=AMBER)
    save(im, "diagram_limits.png")


# ------------------------------------------------------------------- roadmap
def roadmap() -> None:
    im = make_bg()
    header(im, "Roadmap", "Что имеет смысл делать следующим")
    d = ImageDraw.Draw(im)

    def column(x, title, color, items):
        box(d, (x, 190, x + 660, 800), PANEL, LINE, 18, 2)
        d.text((x + 30, 210), title, font=font(27, True), fill=color)
        y = 270
        for i, item in enumerate(items):
            d.ellipse([x + 32, y + 4, x + 46, y + 18], fill=color)
            para(d, (x + 62, y), 550, item, font(18), TEXT, gap=6)
            y += 78

    column(70, "Ближайшее", CYAN, [
        "Ethernet для двух Pluto+ → 2 × 20.48 MS/s",
        "Тестовый передатчик / второй Pluto+ как TX",
        "Подбор порогов на известном сигнале",
        "Подавление Wi-Fi/Bluetooth",
        "Запись IQ-фрагментов события",
        "Экспорт отчёта для оператора",
    ])
    column(870, "Дальше", PINK, [
        "Remote ID через Wi-Fi/BLE-адаптер",
        "Пеленг на когерентной паре",
        "ML-классификатор по размеченным записям",
        "Карта и журнал с GPS",
        "Упаковка в установщик",
    ])
    arrow(d, 700, 495, 865, 495, PINK)
    save(im, "diagram_roadmap.png")


if __name__ == "__main__":
    hero()
    evolution()
    architecture()
    scanner()
    drone()
    bands()
    two_sdr()
    compare()
    signatures()
    quality()
    limits()
    roadmap()
    print("diagrams written to", ROOT)
