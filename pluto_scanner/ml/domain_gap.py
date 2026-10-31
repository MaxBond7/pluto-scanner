"""Build a human-readable domain-gap report.

Example:
    python -m pluto_scanner.ml.domain_gap --per-class 20
"""
from __future__ import annotations

import argparse
from pathlib import Path

from ..paths import DATA_DIR, RECORDINGS_DIR
from .domain import build_report


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(
        prog="python -m pluto_scanner.ml.domain_gap",
        description="Compare synthetic, augmented and real domains",
    )
    p.add_argument("--model", default="", help="model JSON (default: user/default)")
    p.add_argument("--recordings", default=str(RECORDINGS_DIR))
    p.add_argument("--out", default=str(DATA_DIR / "domain_gap"))
    p.add_argument("--per-class", type=int, default=20)
    p.add_argument("--block-seconds", type=float, default=0.5)
    p.add_argument("--max-blocks", type=int, default=10)
    args = p.parse_args(argv)

    try:
        report, path = build_report(
            model_path=args.model or None,
            recordings_dir=args.recordings,
            out_dir=args.out,
            per_class=max(2, args.per_class),
            block_s=max(0.1, args.block_seconds),
            max_blocks=max(1, args.max_blocks),
        )
    except Exception as exc:
        print(f"Ошибка: {exc}")
        return 1

    print(f"Отчёт: {path}")
    for name, item in report["domains"].items():
        acc = item["accuracy"]
        print(
            f"{name:20s} n={item['n']:3d} "
            f"accuracy={'—' if acc is None else f'{acc * 100:.1f}%'} "
            f"coverage={item['coverage'] * 100:.0f}%"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
