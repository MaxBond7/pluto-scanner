"""Build the PowerPoint version of the Pluto Scanner presentation."""
from __future__ import annotations

from pathlib import Path

from pptx import Presentation
from pptx.dml.color import RGBColor
from pptx.enum.shapes import MSO_SHAPE
from pptx.enum.text import MSO_ANCHOR, PP_ALIGN
from pptx.util import Inches, Pt

ROOT = Path(__file__).resolve().parent
OUT = ROOT / "Pluto_Scanner.pptx"

# ------------------------------------------------------------------ palette
BG = RGBColor(0x07, 0x0B, 0x16)
PANEL = RGBColor(0x0D, 0x14, 0x26)
PANEL2 = RGBColor(0x11, 0x1B, 0x30)
LINE = RGBColor(0x22, 0x30, 0x4A)
TEXT = RGBColor(0xDB, 0xE7, 0xF5)
MUTED = RGBColor(0x8F, 0xA6, 0xC0)
CYAN = RGBColor(0x22, 0xD3, 0xEE)
PINK = RGBColor(0xF4, 0x72, 0xB6)
AMBER = RGBColor(0xF5, 0x9E, 0x0B)
GREEN = RGBColor(0x4A, 0xDE, 0x80)
RED = RGBColor(0xF8, 0x71, 0x71)
VIOLET = RGBColor(0xA7, 0x8B, 0xFA)
WHITE = RGBColor(0xFF, 0xFF, 0xFF)

FONT = "Segoe UI"
MONO = "Consolas"


# ------------------------------------------------------------------ helpers
def bg(slide) -> None:
    shape = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(7.5)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = BG
    shape.line.fill.background()
    # top accent
    line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, 0, 0, Inches(13.333), Inches(0.035)
    )
    line.fill.solid()
    line.fill.fore_color.rgb = CYAN
    line.line.fill.background()


def header(slide, kicker: str, title: str, color=CYAN) -> None:
    t = slide.shapes.add_textbox(
        Inches(0.55), Inches(0.28), Inches(11.9), Inches(0.28)
    )
    p = t.text_frame.paragraphs[0]
    p.text = kicker.upper()
    p.font.size = Pt(10)
    p.font.bold = True
    p.font.name = FONT
    p.font.color.rgb = color

    t = slide.shapes.add_textbox(
        Inches(0.55), Inches(0.50), Inches(12.2), Inches(0.65)
    )
    p = t.text_frame.paragraphs[0]
    p.text = title
    p.font.size = Pt(27)
    p.font.bold = True
    p.font.name = FONT
    p.font.color.rgb = TEXT

    line = slide.shapes.add_shape(
        MSO_SHAPE.RECTANGLE, Inches(0.55), Inches(1.22),
        Inches(12.2), Inches(0.012)
    )
    line.fill.solid()
    line.fill.fore_color.rgb = color
    line.line.fill.background()


def footer(slide, number: int) -> None:
    t = slide.shapes.add_textbox(
        Inches(0.55), Inches(7.16), Inches(7.5), Inches(0.2)
    )
    p = t.text_frame.paragraphs[0]
    p.text = "PLUTO SCANNER  ·  КУРСОВОЙ ПРОЕКТ"
    p.font.size = Pt(8)
    p.font.name = FONT
    p.font.color.rgb = RGBColor(0x64, 0x74, 0x8B)

    t = slide.shapes.add_textbox(
        Inches(12.0), Inches(7.12), Inches(0.8), Inches(0.24)
    )
    p = t.text_frame.paragraphs[0]
    p.text = f"{number:02d}"
    p.alignment = PP_ALIGN.RIGHT
    p.font.size = Pt(9)
    p.font.name = FONT
    p.font.color.rgb = MUTED


def text(slide, x, y, w, h, value: str, size=16, color=TEXT,
         bold=False, font_name=FONT, align=PP_ALIGN.LEFT,
         anchor=MSO_ANCHOR.TOP) -> None:
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.vertical_anchor = anchor
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    lines = str(value).split("\n")
    for i, line in enumerate(lines):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = line
        p.alignment = align
        p.font.size = Pt(size)
        p.font.bold = bold
        p.font.name = font_name
        p.font.color.rgb = color
        p.space_after = Pt(0)


def bullets(slide, x, y, w, h, items, size=15, color=TEXT,
            bullet_color=CYAN, gap=5) -> None:
    box = slide.shapes.add_textbox(Inches(x), Inches(y), Inches(w), Inches(h))
    tf = box.text_frame
    tf.word_wrap = True
    tf.margin_left = 0
    tf.margin_right = 0
    tf.margin_top = 0
    tf.margin_bottom = 0
    for i, item in enumerate(items):
        p = tf.paragraphs[0] if i == 0 else tf.add_paragraph()
        p.text = f"•  {item}"
        p.font.size = Pt(size)
        p.font.name = FONT
        p.font.color.rgb = color
        p.space_after = Pt(gap)
        p.level = 0
    # Colour the bullet glyphs is not exposed per-run; the body stays neutral.


def card(slide, x, y, w, h, title: str, body: str,
         color=CYAN, title_size=16, body_size=12) -> None:
    shape = slide.shapes.add_shape(
        MSO_SHAPE.ROUNDED_RECTANGLE, Inches(x), Inches(y),
        Inches(w), Inches(h)
    )
    shape.fill.solid()
    shape.fill.fore_color.rgb = PANEL
    shape.line.color.rgb = color
    shape.line.width = Pt(1)
    # rounded corners
    try:
        shape.adjustments[0] = 0.08
    except Exception:
        pass

    text(slide, x + 0.16, y + 0.12, w - 0.32, 0.3,
         title, size=title_size, color=color, bold=True)
    text(slide, x + 0.16, y + 0.48, w - 0.32, h - 0.58,
         body, size=body_size, color=MUTED)


def picture_fill(slide, path: str, x, y, w, h) -> None:
    from PIL import Image
    with Image.open(ROOT / path) as img:
        iw, ih = img.size
    target = w / h
    source = iw / ih
    if source > target:
        # crop left/right by using height and centered
        ph = h
        pw = h * source
    else:
        pw = w
        ph = w / source
    shape = slide.shapes.add_picture(
        str(ROOT / path), Inches(x + (w - pw) / 2), Inches(y + (h - ph) / 2),
        width=Inches(pw), height=Inches(ph)
    )
    shape.line.color.rgb = RGBColor(0x22, 0x30, 0x4A)
    shape.line.width = Pt(0.75)


def full_image(slide, path: str) -> None:
    slide.shapes.add_picture(
        str(ROOT / path), 0, 0,
        width=Inches(13.333), height=Inches(7.5)
    )


def caption(slide, x, y, w, value: str) -> None:
    text(slide, x, y, w, 0.2, value, size=8.5, color=MUTED)


def table(slide, x, y, w, h, rows: list[list[str]],
          col_widths: list[float], header_color=CYAN) -> None:
    shape = slide.shapes.add_table(
        len(rows), len(rows[0]), Inches(x), Inches(y),
        Inches(w), Inches(h)
    )
    tbl = shape.table
    for i, cw in enumerate(col_widths):
        tbl.columns[i].width = Inches(cw)
    for r, row in enumerate(rows):
        for c, value in enumerate(row):
            cell = tbl.cell(r, c)
            cell.margin_left = Inches(0.08)
            cell.margin_right = Inches(0.06)
            cell.margin_top = Inches(0.03)
            cell.margin_bottom = Inches(0.03)
            cell.vertical_anchor = MSO_ANCHOR.MIDDLE
            cell.fill.solid()
            cell.fill.fore_color.rgb = PANEL if r else PANEL2
            p = cell.text_frame.paragraphs[0]
            p.text = value
            p.font.size = Pt(10 if r else 9)
            p.font.name = FONT
            p.font.bold = r == 0
            p.font.color.rgb = header_color if r == 0 else TEXT
    # remove default banding look by alternating manually
    for r in range(1, len(rows)):
        for c in range(len(rows[0])):
            tbl.cell(r, c).fill.fore_color.rgb = (
                PANEL if r % 2 else RGBColor(0x0A, 0x12, 0x23)
            )


def notes(slide, value: str) -> None:
    slide.notes_slide.notes_text_frame.text = value


# --------------------------------------------------------------------- deck
def build() -> Path:
    prs = Presentation()
    prs.slide_width = Inches(13.333)
    prs.slide_height = Inches(7.5)
    blank = prs.slide_layouts[6]
    num = 0

    def new_slide(kicker=None, title=None, color=CYAN):
        nonlocal num
        num += 1
        s = prs.slides.add_slide(blank)
        bg(s)
        if kicker is not None and title is not None:
            header(s, kicker, title, color)
        footer(s, num)
        return s

    # 1. title -------------------------------------------------------------
    s = new_slide()
    full_image(s, "hero_bg.png")
    text(s, 0.85, 1.55, 6.4, 0.3,
         "SDR  ·  ПАССИВНЫЙ МОНИТОРИНГ  ·  WINDOWS",
         size=10, color=CYAN, bold=True)
    text(s, 0.85, 2.0, 6.6, 1.0, "Pluto Scanner", size=52, color=CYAN, bold=True)
    text(s, 0.85, 3.05, 6.35, 1.2,
         "От спектроанализатора до монитора эфира: реальный Pluto+, "
         "поиск новых контактов, свип 325 МГц – 3.8 ГГц и дрон-монитор "
         "433 МГц – 5.8 ГГц.",
         size=17, color=TEXT)
    text(s, 0.85, 5.55, 6.4, 0.3,
         "PYTHON  ·  PYSIDE6  ·  PYQTGRAPH  ·  ADALM-PLUTO / PLUTO+",
         size=9, color=MUTED)
    notes(s, "Титульный слайд. Pluto Scanner — desktop-приложение для "
             "исследования эфира на ADALM-PLUTO/Pluto+ и симуляторе.")

    # 2. problem -----------------------------------------------------------
    s = new_slide("Зачем это всё", "Есть SDR. Нет удобного рабочего места")
    card(s, 0.55, 1.55, 5.85, 4.65, "Что было нужно",
         "•  Спектр и водопад в реальном времени\n"
         "•  Прослушивание без перестройки LO\n"
         "•  Понимание, что было фоном, а что появилось\n"
         "•  Сохранение результатов в понятный JSON\n"
         "•  Запуск под Windows ярлыком, без терминала\n"
         "•  Пассивный мониторинг полос дроновых линков",
         CYAN, 18, 14)
    card(s, 6.85, 1.55, 5.9, 4.65, "Что приняли сразу",
         "Pluto — это приёмник, не радар и не декодер протоколов.\n\n"
         "Он показывает радиосигнал, но не может сам по себе назвать "
         "модель дрона, направление и дальность.\n\n"
         "Поэтому приложение показывает измерения и гипотезы, а не "
         "«магический вердикт».",
         PINK, 18, 14)
    text(s, 0.55, 6.45, 12.2, 0.35,
         "Цель: инструмент, который честно показывает то, что реально можно "
         "измерить одним или двумя SDR.",
         size=13, color=GREEN)
    notes(s, "Проблема: SDR есть, рабочего места нет. Важно сразу обозначить "
             "границы: Pluto не радар и не декодер.")

    # 3. overview with screenshot -----------------------------------------
    s = new_slide("Что это сейчас", "Pluto Scanner сегодня", PINK)
    bullets(s, 0.55, 1.55, 5.1, 3.8, [
        "Python + PySide6 + pyqtgraph",
        "Windows, ярлык без консоли",
        "ADALM-PLUTO / Pluto+ и симулятор",
        "Один или два SDR",
        "Три вкладки: Контакты, Сканер диапазона, Дрон-монитор",
        "JSON, IQ-фрагменты и карточка события",
    ], size=13.5)
    picture_fill(s, "ui_scanner.png", 5.95, 1.45, 6.85, 4.55)
    caption(s, 5.95, 6.12, 6.85,
            "Интерфейс: спектр, водопад, VFO и вкладки рабочих режимов")
    notes(s, "Обзор текущего состояния: один desktop-инструмент, три режима, "
             "ярлык и JSON-логи.")

    # 4. base functions ----------------------------------------------------
    s = new_slide("Базовые возможности", "Приём и анализ")
    card(s, 0.55, 1.5, 5.95, 2.15, "Отображение",
         "•  Спектр в dBFS и водопад\n"
         "•  Адаптивная шумовая дорожка\n"
         "•  Метки детекций и VFO", CYAN, 17, 13)
    card(s, 6.75, 1.5, 6.0, 2.15, "VFO и звук",
         "•  Программный перенос по частоте\n"
         "•  Wobble — качание VFO\n"
         "•  AM / FM / SSB / CW, шумоподавитель", PINK, 17, 13)
    card(s, 0.55, 3.95, 5.95, 2.55, "Контакты",
         "•  Стабильные ID\n"
         "•  Хиты и пропуски\n"
         "•  «Новый» / «известный»\n"
         "•  Мягкое удаление после пропадания\n"
         "•  Сохранение известных частот", GREEN, 17, 13)
    card(s, 6.75, 3.95, 6.0, 2.55, "Почему VFO в цифре",
         "LO не перестраивается при движении VFO и качании.\n\n"
         "Это позволяет слушать сигнал и не рвать захват.\n\n"
         "Небольшая, но важная деталь для живого эфира.",
         VIOLET, 17, 13)
    notes(s, "Базовые функции: спектр, водопад, VFO, демодуляция, контакты.")

    # 5. evolution ---------------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_evolution.png")
    notes(s, "Эволюция: старый React/TS-архив → Python MVP → реальный Pluto → "
             "сканер → дрон-монитор → стабилизация.")

    # 6. scanner -----------------------------------------------------------
    s = new_slide("Реальный свип", "325 МГц – 3.8 ГГц за один проход", VIOLET)
    bullets(s, 0.55, 1.55, 5.05, 4.1, [
        "Шаг ~819 кГц при 1.024 MS/s",
        "Около 4240 шагов, 12–18 минут",
        "Живой график: текущий шаг + max-hold",
        "Прогресс, ETA, пропущенные шаги",
        "Сохранение фона и автосравнение",
    ], size=13.5)
    picture_fill(s, "ui_scanner.png", 5.9, 1.45, 6.9, 4.6)
    caption(s, 5.9, 6.15, 6.9,
            "Скриншот: свип 433–436 МГц на симуляторе, 5 шагов, 35 пиков")
    notes(s, "Сканер: полный паспортный диапазон Pluto, живой график и JSON.")

    # 7. scanner geometry --------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_scanner.png")
    notes(s, "Геометрия свипа: первый/последний центр, перекрытие, покрытие "
             "без дыр.")

    # 8. compare -----------------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_compare.png")
    notes(s, "Сравнение фонов: пики, max-hold, проверка совместимости и "
             "защита от ложных новых контактов.")

    # 9. drone -------------------------------------------------------------
    s = new_slide("Дрон-монитор", "Быстрый обзор вместо полного свипа", PINK)
    bullets(s, 0.55, 1.55, 5.0, 4.0, [
        "Полосы: 433 / 868 / 915 МГц",
        "1.2–1.3 / 2.4 / 5.8 ГГц",
        "Широкие куски: 10.24 / 20.48 / 30.72 MS/s",
        "Живой спектр текущего куска",
        "Таблица событий и журнал JSON",
        "Тревога только после подтверждения",
    ], size=13.2)
    picture_fill(s, "ui_drone.png", 5.9, 1.45, 6.9, 4.6)
    caption(s, 5.9, 6.15, 6.9,
            "Скриншот: активный дрон-монитор на симуляторе, 2.4 ГГц")
    notes(s, "Дрон-монитор: не полный свип, а частые возвраты в интересные "
             "полосы; измеряем временную структуру.")

    # 10. drone pipeline --------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_drone.png")
    notes(s, "Конвейер: IQ → PSD+огибающая → признаки → класс → трекер → "
             "подтверждённая тревога.")

    # 11. evidence card ----------------------------------------------------
    s = new_slide("Доказательства", "IQ-фрагмент и карточка события", GREEN)
    bullets(s, 0.55, 1.55, 4.8, 4.3, [
        "Двойной клик по событию открывает карточку",
        "Спектр и временная огибающая",
        "Хиты, SNR, ширина, скважность",
        "IQ-фрагмент ~20 мс в clips/*.cf32",
        "Экспорт: event.json, spectrum.csv, envelope.csv, clip.cf32",
    ], size=13.0, bullet_color=GREEN)
    picture_fill(s, "event_card.png", 5.55, 1.45, 7.2, 4.9)
    notes(s, "Доказательная база: IQ-фрагмент, спектр, огибающая и экспорт "
             "в отдельную папку. Это следующий шаг после детектора.")

    # 12. signature library ------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_signatures.png")
    notes(s, "Библиотека сигнатур: признаки события сопоставляются с локальной "
             "SQLite-базой; top-3 гипотезы со ссылками и причинами. Модель "
             "дрона — только через протокол, Remote ID или датасет.")

    # 13. classes ---------------------------------------------------------
    s = new_slide("Классы и тревоги", "Классы — это гипотезы, а не приговор", AMBER)
    rows = [
        ["Класс", "Признаки", "Тревога"],
        ["FHSS", "короткие узкие посылки, скважность, прыжки", "да"],
        ["TELEMETRY", "редкие узкие посылки", "да"],
        ["VIDEO_ANALOG", "непрерывный канал 3–10 МГц", "да"],
        ["VIDEO_DIGITAL", "широкий канал 8–30 МГц", "да"],
        ["WIFI", "15–30 МГц, «плоский» спектр", "нет"],
        ["NARROW", "узкий непрерывный носитель", "нет"],
        ["UNKNOWN", "прочая активность", "нет"],
    ]
    table(s, 0.55, 1.5, 12.2, 3.35, rows, [2.2, 7.4, 2.6])
    card(s, 0.55, 5.1, 5.95, 1.45, "Строгий режим",
         "Кандидат — оранжевый. Тревога — красный, только после 3 попаданий "
         "и 70% уверенности. В таблице есть столбец «Хиты».",
         GREEN, 15, 11.5)
    card(s, 6.75, 5.1, 6.0, 1.45, "Честно",
         "2.4 ГГц полон Wi-Fi, Bluetooth, Zigbee и камер. Большинство "
         "одиночных тревог — ложные. Для проверки нужен известный передатчик.",
         RED, 15, 11.5)
    notes(s, "Классы и строгий режим тревог: кандидат и подтверждённая "
             "тревога — разные вещи.")

    # 12. bands ------------------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_bands.png")
    notes(s, "Полосы мониторинга: 433/868/915, 1.2–1.3, 2.4 и 5.8 ГГц. "
             "5.8 зависит от конкретного Pluto+.")

    # 13. two SDR ----------------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_two_sdr.png")
    notes(s, "Два Pluto+: 10.24 стабильно, 20.48 на обоих — риск; для "
             "реального 2× нужен Ethernet или разные контроллеры.")

    # 14. architecture -----------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_architecture.png")
    notes(s, "Архитектура: один QThread на устройство, DSP/GUI в главном "
             "потоке, отдельные модули сканера и дрон-монитора.")

    # 15. quality ----------------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_quality.png")
    notes(s, "Качество: 64 теста, симулятор, реальные Pluto+, исправленные "
             "баги и живые измерения.")

    # 16. limitations ------------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_limits.png")
    notes(s, "Ограничения: что реально измеряет пассивный приёмник, а что "
             "требует другого железа — пеленг, дальность, Remote ID, "
             "декодирование.")

    # 17. roadmap ---------------------------------------------------------
    s = new_slide()
    full_image(s, "diagram_roadmap.png")
    notes(s, "Roadmap: Ethernet, тестовый передатчик, Remote ID, пеленг, ML "
             "и упаковка.")

    # 18. conclusion -------------------------------------------------------
    s = new_slide()
    full_image(s, "hero_bg.png")
    text(s, 0.85, 1.55, 6.2, 0.3, "К ЧЕМУ ПРИШЛИ",
         size=10, color=CYAN, bold=True)
    text(s, 0.85, 1.95, 6.5, 1.0, "Рабочий инструмент,\nа не демо",
         size=38, color=TEXT, bold=True)
    text(s, 0.85, 3.55, 6.2, 1.7,
         "Pluto Scanner закрывает путь: увидеть → измерить → сохранить → "
         "сравнить. Отдельный быстрый режим смотрит дроновые полосы и "
         "честно показывает кандидатов.",
         size=15, color=TEXT)
    text(s, 0.85, 5.5, 6.2, 0.5,
         "Один SDR — глаза в эфир. Два SDR — параллельные полосы и больше "
         "шансов не пропустить событие.",
         size=12, color=PINK)
    notes(s, "Итог: рабочий инструмент, который честно показывает измерения "
             "и ограничения, и имеет понятный путь развития.")

    prs.core_properties.title = "Pluto Scanner — презентация"
    prs.core_properties.author = "Pluto Scanner"
    prs.core_properties.subject = "SDR, ADALM-PLUTO, сканер диапазона, дрон-монитор"
    prs.save(OUT)
    return OUT


if __name__ == "__main__":
    path = build()
    print("PPTX written to", path)
