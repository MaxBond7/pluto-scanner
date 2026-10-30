# Сборка для Windows: план

Цель: пользователь скачивает один файл, запускает — и приложение работает без
Python и без терминала.

## Вариант 1: portable one-file

```text
PlutoScanner-0.2.0.exe
```

- PyInstaller `--onefile --windowed`;
- иконка `assets/pluto_scanner.ico`;
- внутри PySide6, pyqtgraph, numpy, scipy, sounddevice;
- `pyadi-iio` и libiio — только если разрешено лицензией и стабильно
  работает в one-file;
- данные (`user_data`, `scan_logs`, `drone_logs`) создаются **рядом с .exe**,
  а не в `%APPDATA%`, чтобы portable-режим оставался переносимым;
- первый запуск может быть медленнее из-за распаковки.

## Вариант 2: one-folder + установщик

```text
PlutoScanner/
  PlutoScanner.exe
  _internal/...
```

- быстрее стартует;
- Inno Setup делает `PlutoScanner-Setup-0.2.0.exe`;
- ярлык, иконка, пункт «Удалить»;
- данные в `Documents/PlutoScanner` или рядом с установкой (выбрать при
  сборке).

## Что проверить перед релизом

- [ ] Запуск на чистой Windows 10/11 без Python.
- [ ] Симулятор, спектр, водопад, VFO, демодуляция.
- [ ] Сканер и дрон-монитор.
- [ ] Запись IQ и экспорт события.
- [ ] Библиотека сигнатур, импорт/экспорт.
- [ ] Иконка окна и ярлыка.
- [ ] Нет `.venv`, логов и личных данных внутри дистрибутива.
- [ ] Версия в `pyproject.toml`, `CHANGELOG.md` и имени файла совпадает.
- [ ] SMART-предупреждение Windows / подпись кода (если возможно).

## Артефакты GitHub Release

- `PlutoScanner-<version>-portable.exe` — простой вариант;
- `PlutoScanner-Setup-<version>.exe` — установщик;
- `SHA256SUMS.txt`;
- `release-notes.md`.

## Ограничения

- PyInstaller one-file с PySide6 и scipy может быть большим (100–250 МБ).
- Антивирусы иногда реагируют на неподписанный one-file; подпись кода
  желательна для массовой раздачи.
- `pyadi-iio`/libiio на Windows требует UCRT; проверить на чистой машине.
