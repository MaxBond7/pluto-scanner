"""Export a single drone event as a self-contained evidence bundle."""
from __future__ import annotations

import csv
import json
import shutil
import time
from pathlib import Path

from .tracker import DroneEvent


def event_summary_text(event: DroneEvent) -> str:
    return (
        f"Событие: {event.event_id}\n"
        f"Полоса: {event.band_name} ({event.band_key})\n"
        f"Класс: {event.class_ru} ({event.class_key})\n"
        f"Частота: {event.freq_hz / 1e6:.4f} МГц\n"
        f"Ширина: {event.bw_hz / 1e6:.3f} МГц\n"
        f"SNR: {event.max_snr_db:.1f} дБ\n"
        f"Скважность: {event.max_duty * 100:.0f}%\n"
        f"Хиты: {event.count}\n"
        f"Уверенность: {event.confidence * 100:.0f}%\n"
        f"Устройства: {', '.join(event.device_ids) or '—'}\n"
        f"IQ-запись: {event.clip_path or 'нет'}\n"
    )


def export_event_bundle(
    event: DroneEvent,
    out_dir: str | Path,
    *,
    matches: list[dict] | None = None,
) -> Path:
    """Write event.json, spectrum.csv, envelope.csv and the IQ clip."""
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime(event.last_seen))
    root = Path(out_dir) / f"event_{event.event_id}_{stamp}"
    root.mkdir(parents=True, exist_ok=True)

    (root / "event.json").write_text(
        json.dumps(event.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )

    with (root / "spectrum.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["freq_mhz", "power_dbfs"])
        for freq, level in zip(event.spectrum_freqs_hz, event.spectrum_db):
            writer.writerow([f"{freq / 1e6:.6f}", f"{level:.3f}"])

    with (root / "envelope.csv").open("w", newline="", encoding="utf-8") as fh:
        writer = csv.writer(fh)
        writer.writerow(["time_ms", "power_dbfs"])
        for ms, level in zip(event.envelope_ms, event.envelope_db):
            writer.writerow([f"{ms:.3f}", f"{level:.3f}"])

    if matches:
        (root / "matches.json").write_text(
            json.dumps(matches, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    clip_copied = False
    if event.clip_path:
        source = Path(event.clip_path)
        if source.exists():
            destination = root / "clip.cf32"
            shutil.copy2(source, destination)
            meta = source.with_suffix(".json")
            if meta.exists():
                shutil.copy2(meta, root / "clip.json")
            clip_copied = True

    readme = (
        "# Pluto Scanner — событие\n\n"
        f"{event_summary_text(event)}\n"
        f"IQ-файл скопирован: {'да' if clip_copied else 'нет'}\n\n"
        "## Файлы\n\n"
        "- `event.json` — все поля события, спектр и огибающая;\n"
        "- `spectrum.csv` — спектр события;\n"
        "- `envelope.csv` — временная огибающая;\n"
        "- `matches.json` — гипотезы из библиотеки сигнатур;\n"
        "- `clip.cf32` — IQ, little-endian complex64 (если была запись).\n\n"
        "## Ограничения\n\n"
        "Класс и уверенность — гипотеза по форме спектра, не декодирование\n"
        "протокола и не подтверждение модели. Для проверки нужен известный\n"
        "передатчик или Remote ID.\n"
    )
    (root / "README.md").write_text(readme, encoding="utf-8")
    return root.resolve()
