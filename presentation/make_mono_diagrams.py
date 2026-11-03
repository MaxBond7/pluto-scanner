"""Generate the monochrome diagrams used on the GitHub page.

    python presentation/make_mono_diagrams.py

Everything is black and white, 1 px lines, monospace labels — the same
language as the application's ``mono`` theme.  Numbers come from
``docs/BINARY.md`` and ``docs/MODEL_CARD.md``; keep them in sync.
"""
from __future__ import annotations

import math
import sys
from pathlib import Path

from PIL import ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "assets"))

import brand_mono as bm  # noqa: E402

OUT = ROOT / "presentation"


def band_map() -> None:
    width, height = 1400, 470
    image = bm.canvas(width, height)
    d = ImageDraw.Draw(image)
    bm.frame(d, width, height)

    left, right = 250, width - 60
    f_min, f_max = 380.0, 6600.0

    def x_of(freq: float) -> float:
        return left + (math.log10(freq) - math.log10(f_min)) / (
            math.log10(f_max) - math.log10(f_min)
        ) * (right - left)

    bm.label(d, (56, 54), "BAND COVERAGE / MHz (log)", 16, color=bm.WHITE)

    # Pluto range band behind the rows.
    d.rectangle(
        [x_of(325), 96, x_of(3800), height - 66],
        outline=(70, 70, 70, 255), width=1,
    )
    d.line([(x_of(325), 96), (x_of(325), height - 66)], fill=(70, 70, 70, 255))
    d.line([(x_of(3800), 96), (x_of(3800), height - 66)], fill=(70, 70, 70, 255))
    bm.label(d, (int(x_of(325)) + 6, 100), "PLUTO 325 – 3800", 10, color=bm.FAINT)

    # Ruler.
    for freq in (400, 500, 700, 1000, 1500, 2000, 3000, 4000, 5000, 6000):
        x = x_of(freq)
        d.line([(x, 84), (x, 96)], fill=bm.FAINT)
        bm.label(d, (int(x) - 12, 66), str(freq), 11)

    bands = [
        ("433 МГц", 433.05, 434.79, "1.7 МГц", ""),
        ("868 МГц", 863.0, 870.0, "7 МГц", ""),
        ("915 МГц", 902.0, 928.0, "26 МГц", ""),
        ("1.2 ГГц", 1080.0, 1320.0, "240 МГц", ""),
        ("2.4 ГГц", 2400.0, 2483.5, "83 МГц", ""),
        ("5.8 ГГц", 5725.0, 5875.0, "150 МГц", "PLUTO+"),
    ]
    y = 120
    for name, start, end, width_text, note in bands:
        x0, x1 = x_of(start), x_of(end)
        bm.label(d, (56, y - 2), name, 15, color=bm.WHITE)
        if note:
            bm.label(d, (56, y + 18), note, 10)
        d.rectangle([x0, y, max(x0 + 2, x1), y + 18], fill=bm.WHITE)
        text_x = int(max(x1 + 10, x0 + 12))
        if text_x > right - 90:
            text_x = int(x0) - int(d.textlength(width_text, font=bm.mono(11))) - 14
        bm.label(d, (text_x, y + 1), width_text, 11, color=bm.DIM)
        d.line([(left, y + 30), (right, y + 30)], fill=(26, 26, 26, 255))
        y += 48

    bm.label(
        d, (56, height - 44),
        "ПАССИВНЫЙ ПРИЁМ · 61.44 MS/s МАКС. · 5.8 ГГЦ ТОЛЬКО С PLUTO+",
        11,
    )
    image.convert("RGB").save(OUT / "mono_bands.png", quality=95)
    print("written", OUT / "mono_bands.png")


def pipeline() -> None:
    width, height = 1400, 380
    image = bm.canvas(width, height)
    d = ImageDraw.Draw(image)
    bm.frame(d, width, height)
    bm.label(d, (56, 50), "SIGNAL PATH / PASSIVE RX ONLY", 16, color=bm.WHITE)

    boxes = [
        ("ADALM-PLUTO", ["IQ, 61.44 MS/s", "USB / Ethernet"]),
        ("DSP", ["FFT + огибающая", "калибровка фона"]),
        ("HEURISTIC", ["6 классов", "форма + время"]),
        ("BINARY MODEL", ["дрон / не дрон", "score + порог"]),
        ("UI + PROOF", ["таблица, тревога", "IQ-клип, JSON"]),
    ]
    top, box_h = 110, 110
    margin, gap = 56, 54
    box_w = (width - 2 * margin - gap * (len(boxes) - 1)) // len(boxes)
    for index, (title, lines) in enumerate(boxes):
        x = margin + index * (box_w + gap)
        d.rectangle([x, top, x + box_w, top + box_h], outline=bm.WHITE, width=1)
        d.rectangle([x, top, x + box_w, top + 22], fill=bm.WHITE)
        bm.label(d, (x + 8, top + 4), title, 11, color=bm.BLACK, bold=True)
        for line_index, line in enumerate(lines):
            bm.label(d, (x + 10, top + 38 + line_index * 22), line, 11, color=bm.DIM)
        if index < len(boxes) - 1:
            ax = x + box_w
            d.line([(ax + 8, top + box_h // 2), (ax + gap - 8, top + box_h // 2)],
                   fill=bm.WHITE, width=1)
            d.line([(ax + gap - 14, top + box_h // 2 - 4),
                    (ax + gap - 8, top + box_h // 2),
                    (ax + gap - 14, top + box_h // 2 + 4)], fill=bm.WHITE, width=1)

    bm.label(
        d, (56, 268),
        "МОДЕЛЬ НЕ ДЕКОДИРУЕТ ПРОТОКОЛЫ И НЕ ЗАМЕНЯЕТ REMOTE ID",
        13, color=bm.DIM,
    )
    bm.label(
        d, (56, 296),
        "ВСЁ СЧИТАЕТСЯ ЛОКАЛЬНО · ДАННЫЕ НЕ ПОКИДАЮТ МАШИНУ",
        13, color=bm.DIM,
    )
    bm.barcode(d, (width - 300, 286, width - 60, 318), seed=41)
    image.convert("RGB").save(OUT / "mono_pipeline.png", quality=95)
    print("written", OUT / "mono_pipeline.png")


def binary_model() -> None:
    width, height = 1400, 540
    image = bm.canvas(width, height)
    d = ImageDraw.Draw(image)
    bm.frame(d, width, height)

    bm.label(d, (56, 46), "BINARY MODEL / DRONE OR NOT", 16, color=bm.WHITE)

    # Score scale.
    left, right = 56, width - 56
    y = 96
    d.rectangle([left, y, right, y + 22], outline=bm.FAINT, width=1)
    cut = left + int((right - left) * 0.60)
    alarm = left + int((right - left) * 0.95)
    d.rectangle([left, y, cut, y + 22], fill=(40, 40, 40, 255))
    d.rectangle([cut, y, alarm, y + 22], fill=(80, 80, 80, 255))
    d.rectangle([alarm, y, right, y + 22], fill=bm.WHITE)
    bm.label(d, (left + 6, y + 24), "0%  BACKGROUND / не дрон", 10, color=bm.DIM)
    bm.label(d, (cut - 40, y + 24), "60%  КАНДИДАТ", 10, color=bm.DIM)
    bm.label(d, (alarm - 60, y + 24), "95%  ТРЕВОГА", 10, color=bm.WHITE)

    # Per-source bars (share of blocks above the alarm threshold).
    rows = [
        ("DroneRF AR, чистые", 0.93),
        ("DroneRF Phantom, чистые", 0.94),
        ("DroneRF AR, 7–24 дБ", 0.64),
        ("DroneRF Phantom, 7–24 дБ", 0.25),
        ("Фон DroneRF с чужим Wi-Fi", 0.063),
        ("Рация Baofeng 433", 0.0),
        ("Синтетический Wi-Fi", 0.0),
    ]
    bm.label(d, (56, 168), "ДОЛЯ БЛОКОВ ВЫШЕ ПОРОГА", 12)
    bar_left, bar_right = 420, width - 130
    y = 196
    for name, value in rows:
        bm.label(d, (56, y - 3), name, 12, color=bm.WHITE)
        d.rectangle([bar_left, y, bar_right, y + 14], outline=(50, 50, 50, 255))
        filled = int((bar_right - bar_left) * value)
        if filled > 0:
            d.rectangle([bar_left, y, bar_left + filled, y + 14], fill=bm.WHITE)
        bm.label(d, (bar_right + 12, y - 2), f"{value * 100:.0f}%", 12)
        y += 30

    bm.label(
        d, (56, height - 86),
        "ROC-AUC 0.96 ± 0.05 ПО 5 РАЗБИЕНИЯМ · ПОРОГ 95% ДАЁТ ~1% ЛОЖНЫХ",
        11, color=bm.DIM,
    )
    bm.label(
        d, (56, height - 62),
        "Wi-Fi И ВИДЕОЛИНК ДРОНА ФИЗИЧЕСКИ ПОХОЖИ — ЭТО НЕ РЕШАЕТСЯ СПЕКТРОМ",
        11, color=bm.FAINT,
    )
    image.convert("RGB").save(OUT / "mono_binary.png", quality=95)
    print("written", OUT / "mono_binary.png")


def limits() -> None:
    width, height = 1400, 430
    image = bm.canvas(width, height)
    d = ImageDraw.Draw(image)
    bm.frame(d, width, height)
    bm.label(d, (56, 50), "WHAT IT DOES / WHAT IT DOES NOT", 16, color=bm.WHITE)

    can = [
        "видеть сигнал и измерять ширину, скважность, SNR",
        "классифицировать 6 типов активности",
        "оценивать «дрон / не дрон» с порогом и калибровкой",
        "сохранять IQ-доказательство и JSON-журнал",
        "работать полностью офлайн",
    ]
    cannot = [
        "декодировать протокол и назвать модель дрона",
        "заменить Remote ID",
        "измерить дальность или направление",
        "отличить Wi-Fi-дрон от обычного Wi-Fi",
        "дать гарантию 100% на любой дрон",
    ]
    column_w = (width - 2 * 56 - 60) // 2
    for index, (title, items, mark) in enumerate(
        (("МОЖЕТ", can, "+"), ("НЕ МОЖЕТ", cannot, "−"))
    ):
        x = 56 + index * (column_w + 60)
        bm.label(d, (x, 96), title, 14, color=bm.WHITE, bold=True)
        d.line([(x, 118), (x + column_w, 118)], fill=bm.WHITE, width=1)
        y = 136
        for item in items:
            bm.label(d, (x, y), f"{mark} {item}", 12, color=bm.DIM)
            y += 40

    bm.label(
        d, (56, height - 40),
        "ЧЕСТНАЯ ЭВРИСТИКА, А НЕ СЕРТИФИЦИРОВАННОЕ СРЕДСТВО БЕЗОПАСНОСТИ",
        11, color=bm.FAINT,
    )
    image.convert("RGB").save(OUT / "mono_limits.png", quality=95)
    print("written", OUT / "mono_limits.png")


def _box(d: ImageDraw.ImageDraw, x: int, y: int, w: int, h: int,
         title: str, lines: list[str], *, note: str = "") -> None:
    d.rectangle([x, y, x + w, y + h], outline=bm.WHITE, width=1)
    d.rectangle([x, y, x + w, y + 24], fill=bm.WHITE)
    bm.label(d, (x + 10, y + 5), title, 12, color=bm.BLACK, bold=True)
    for index, line in enumerate(lines):
        bm.label(d, (x + 12, y + 40 + index * 22), line, 11, color=bm.DIM)
    if note:
        bm.label(d, (x + 12, y + h - 22), note, 10, color=bm.FAINT)


def _arrow(d: ImageDraw.ImageDraw, x1: int, y1: int, x2: int, y2: int) -> None:
    d.line([(x1, y1), (x2, y2)], fill=bm.WHITE, width=1)
    if y1 == y2:
        direction = 1 if x2 > x1 else -1
        d.line([(x2 - 8 * direction, y1 - 4), (x2, y1),
                (x2 - 8 * direction, y1 + 4)], fill=bm.WHITE, width=1)
    else:
        direction = 1 if y2 > y1 else -1
        d.line([(x1 - 4, y2 - 8 * direction), (x1, y2),
                (x1 + 4, y2 - 8 * direction)], fill=bm.WHITE, width=1)


def architecture() -> None:
    width, height = 1600, 860
    image = bm.canvas(width, height)
    d = ImageDraw.Draw(image)
    bm.frame(d, width, height)

    bm.label(d, (56, 50), "ARCHITECTURE", 15, color=bm.FAINT)
    bm.label(d, (56, 78), "ОДИН ПОТОК НА УСТРОЙСТВО", 34,
             color=bm.WHITE, bold=True)
    bm.label(d, (58, 122), "ОБЩИЙ GUI · ПАССИВНЫЙ ПРИЁМ · БЕЗ ДЕКОДИРОВАНИЯ", 12)
    bm.divider(d, 56, 150, width - 56)

    # Row 1.
    y1, h1 = 180, 120
    _box(d, 56, y1, 210, h1, "IQ", ["Pluto / sim", "20.48 MS/s"])
    _box(d, 330, y1, 280, h1, "DeviceSession",
         ["спектр · детектор", "трекер · VFO · демод"])
    _box(d, 676, y1, 280, h1, "DSP / UI",
         ["SpectrumFrame", "contacts · audio"])
    _box(d, 1022, y1, 300, h1, "GUI",
         ["Контакты · Сканер", "Дрон-монитор"])

    _arrow(d, 266, y1 + h1 // 2, 322, y1 + h1 // 2)
    _arrow(d, 610, y1 + h1 // 2, 668, y1 + h1 // 2)
    _arrow(d, 956, y1 + h1 // 2, 1014, y1 + h1 // 2)

    # VFO under DeviceSession.
    _box(d, 330, 360, 280, 96, "VFO / DEMOD",
         ["цифровой перенос", "AM/FM/SSB/CW"])
    _arrow(d, 470, y1 + h1, 470, 352)

    # Row 2: scanner and drone monitor are separate consumers.
    y2, h2 = 520, 150
    _box(d, 56, y2, 400, h2, "СКАНЕР ДИАПАЗОНА",
         ["ScanController → peaks", "recorder → compare", "325 МГц – 3.8 ГГц"])
    _box(d, 540, y2, 420, h2, "ДРОН-МОНИТОР",
         ["DroneWatchController", "features → tracker",
          "recorder + manager"])
    _box(d, 1046, y2, 340, h2, "ХРАНИЛИЩЕ",
         ["scan_logs/ · drone_logs/", "background.json · summary.json",
          "events.jsonl"])

    _arrow(d, 456, y2 + h2 // 2, 532, y2 + h2 // 2)
    _arrow(d, 960, y2 + h2 // 2, 1038, y2 + h2 // 2)

    bm.label(d, (56, height - 44),
             "ОДИН ПОТОК НА УСТРОЙСТВО · СОБЫТИЯ И IQ-КЛИПЫ ПИШУТСЯ ЛОКАЛЬНО",
             11, color=bm.DIM)
    bm.barcode(d, (width - 300, height - 52, width - 60, height - 28), seed=61)

    image.convert("RGB").save(OUT / "mono_architecture.png", quality=95)
    print("written", OUT / "mono_architecture.png")


def main() -> int:
    band_map()
    pipeline()
    binary_model()
    limits()
    architecture()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
