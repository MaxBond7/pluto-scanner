"""Train the offline drone ML baseline.

Example:
    python -m pluto_scanner.ml.train --per-class 60 --out user_data/ml_model.json
"""
from __future__ import annotations

import argparse
import time
from pathlib import Path

from ..drone.features import CLASS_RU
from ..paths import DATA_DIR
from .model import train_and_save


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pluto_scanner.ml.train",
        description="Train the offline drone-band softmax classifier on synthetic IQ",
    )
    p.add_argument("--per-class", type=int, default=60,
                   help="synthetic blocks per class (default 60)")
    p.add_argument("--epochs", type=int, default=600,
                   help="training epochs (default 600)")
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--out", type=str,
                   default=str(DATA_DIR / "ml_model.json"),
                   help="model JSON path")
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    started = time.time()
    last = {"label": ""}

    def progress(done: int, total: int, label: str) -> None:
        if label != last["label"] or done == total:
            last["label"] = label
            print(
                f"[{done:3d}/{total}] {CLASS_RU.get(label, label)}",
                flush=True,
            )

    print("Генерация синтетического датасета...", flush=True)
    model, metrics = train_and_save(
        args.out,
        per_class=max(4, args.per_class),
        epochs=max(20, args.epochs),
        seed=args.seed,
        progress=progress,
    )
    elapsed = time.time() - started
    print("")
    print(f"Модель: {Path(args.out).resolve()}")
    print(f"Точность на отложенной выборке: {metrics['accuracy'] * 100:.1f}%")
    print(f"Согласие с эвристикой: "
          f"{metrics['heuristic_agreement'] * 100:.1f}%")
    print(f"Время: {elapsed:.1f} с")
    print("")
    print("Класс                         precision  recall  support")
    for name in model.classes:
        row = metrics["per_class"][name]
        ru = CLASS_RU.get(name, name)
        print(f"{ru[:28]:28s} {row['precision']:9.2f} {row['recall']:7.2f} "
              f"{int(row['support']):7d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
