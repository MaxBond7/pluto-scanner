# Презентация Pluto Scanner

## Главный файл

- **`Pluto_Scanner.pptx`** — готовая презентация для PowerPoint / LibreOffice / Google Slides.
- **`Pluto_Scanner.pdf`** — PDF-версия для быстрого просмотра и печати.
- `PRESENTATION.html` — интерактивная версия для браузера (стрелки/пробел).
- `PRESENTATION.md` — текстовый каркас для редактирования.

## Что внутри

PPTX/PDF — полная версия на 20 слайдов. HTML/Markdown — сокращённая версия на 17 слайдов (без отдельных слайдов про IQ-карточку и библиотеку сигнатур).

20 слайдов:

1. Титул
2. Задача
3. Обзор приложения
4. Базовые возможности
5. Эволюция проекта
6. Реальный сканер
7. Геометрия свипа
8. Сравнение фонов
9. Дрон-монитор
10. Конвейер обработки
11. IQ-фрагмент и карточка события
12. Библиотека сигнатур
13. Классы и тревоги
14. Полосы мониторинга
15. Один SDR против двух
16. Архитектура
17. Качество и тесты
18. Ограничения
19. Roadmap
20. Итог

## Иллюстрации

- `ui_scanner.png` — интерфейс сканера диапазона;
- `ui_drone.png` — интерфейс дрон-монитора;
- `event_card.png` — карточка события с IQ-записью;
- `diagram_signatures.png` — матчер и библиотека сигнатур;
- `hero_bg.png` — титульный фон;
- `diagram_evolution.png` — timeline проекта;
- `diagram_architecture.png` — архитектура;
- `diagram_scanner.png` — геометрия свипа;
- `diagram_compare.png` — сравнение фонов;
- `diagram_drone.png` — конвейер дрон-монитора;
- `diagram_bands.png` — полосы;
- `diagram_two_sdr.png` — один/два SDR;
- `diagram_quality.png` — тесты и проверки;
- `diagram_limits.png` — что можно и нельзя измерить;
- `diagram_roadmap.png` — план развития.

## Как пересобрать

Нужны `python-pptx` и `Pillow`:

```powershell
cd NEW
.\.venv\Scripts\python.exe presentation\make_diagrams.py
.\.venv\Scripts\python.exe presentation\make_pptx.py
```

`make_diagrams.py` рисует все схемы, `make_pptx.py` собирает `.pptx` с тёмной темой, заметками докладчика и изображениями.
