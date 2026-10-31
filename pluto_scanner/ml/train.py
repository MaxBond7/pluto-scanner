"""Train the offline drone ML model.

Examples:
    python -m pluto_scanner.ml.train --per-class 60
    python -m pluto_scanner.ml.train --real-dir iq_recordings --no-synthetic
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from ..drone.features import CLASS_RU
from ..paths import DATA_DIR, RECORDINGS_DIR
from .dataset import train_from_recordings
from .model import train_and_save


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pluto_scanner.ml.train",
        description="Train the offline drone classifier on synthetic and/or labeled IQ",
    )
    p.add_argument("--per-class", type=int, default=60,
                   help="synthetic blocks per class (default 60)")
    p.add_argument("--epochs", type=int, default=600,
                   help="training epochs (default 600)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", type=str,
                   default=str(DATA_DIR / "ml_model.json"),
                   help="model JSON path")
    p.add_argument("--real-dir", type=str, default="",
                   help="folder with labeled .cf32 recordings")
    p.add_argument("--no-synthetic", action="store_true",
                   help="use only real labeled recordings")
    p.add_argument("--blocks", type=int, default=20,
                   help="max IQ blocks per recording (default 20)")
    p.add_argument("--block-seconds", type=float, default=0.2,
                   help="block length in seconds (default 0.2)")
    return p


def _print_metrics(model, metrics: dict, elapsed: float) -> None:
    print("")
    print(f"Модель: {metrics.get('model_path', '')}")
    print(f"Источник: {metrics['source']}")
    if not metrics.get("holdout", True):
        print("ВНИМАНИЕ: мало записей для отложенной выборки; "
              "точность ниже — на обучающих данных.")
    print(f"Точность: {metrics['accuracy'] * 100:.1f}%")
    if metrics.get("heuristic_agreement") is not None:
        print(f"Согласие с эвристикой: "
              f"{metrics['heuristic_agreement'] * 100:.1f}%")
    if metrics.get("real_blocks") is not None:
        print(f"Реальных блоков: {metrics['real_blocks']} "
              f"из {metrics['real_recordings']} записей")
        print(f"Синтетических блоков: {metrics.get('synthetic_blocks', 0)}")
        counts = metrics.get("label_counts") or {}
        if counts:
            print("Метки:", ", ".join(
                f"{CLASS_RU.get(k, k)}={v}" for k, v in counts.items()
            ))
    print(f"Время: {elapsed:.1f} с")
    print("")
    print("Класс                         precision  recall  support")
    for name in model.classes:
        row = metrics.get("per_class", {}).get(name, {})
        ru = CLASS_RU.get(name, name)
        print(f"{ru[:28]:28s} {float(row.get('precision', 0)):9.2f} "
              f"{float(row.get('recall', 0)):7.2f} "
              f"{int(row.get('support', 0)):7d}")


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.time()
    last = {"label": ""}

    def progress(done: int, total: int, label: str) -> None:
        if label != last["label"] or done == total:
            last["label"] = label
            print(f"[{done:3d}/{total}] {label}", flush=True)

    if args.real_dir:
        real_dir = args.real_dir or str(RECORDINGS_DIR)
        print(f"Размеченные записи: {real_dir}", flush=True)
        try:
            model, metrics = train_from_recordings(
                args.out,
                real_dir,
                include_synthetic=not args.no_synthetic,
                synthetic_per_class=max(4, args.per_class),
                block_s=max(0.05, args.block_seconds),
                max_blocks=max(1, args.blocks),
                epochs=max(20, args.epochs),
                seed=args.seed,
                progress=progress,
            )
        except Exception as exc:
            print(f"Ошибка обучения: {exc}", flush=True)
            return 1
    else:
        print("Генерация синтетического датасета...", flush=True)
        model, metrics = train_and_save(
            args.out,
            per_class=max(4, args.per_class),
            epochs=max(20, args.epochs),
            seed=args.seed,
            progress=lambda done, total, label: progress(
                done, total, CLASS_RU.get(label, label)
            ),
        )
        metrics.setdefault("source", "synthetic")
        metrics.setdefault("heuristic_agreement", metrics.get(
            "heuristic_agreement", 0.0
        ))

    metrics["model_path"] = str(Path(args.out).resolve())
    _print_metrics(model, metrics, time.time() - started)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
