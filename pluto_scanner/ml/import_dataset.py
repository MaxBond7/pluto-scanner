"""Import a public IQ dataset into the local recording format.

Examples:
    python -m pluto_scanner.ml.import_dataset --format sigmf `
        --src dataset.sigmf-meta --label WIFI

    python -m pluto_scanner.ml.import_dataset --format dat `
        --src AIR_00_00.dat --sample-rate 60e6 --center 2437.5e6 `
        --max-seconds 2 --label VIDEO_DIGITAL
"""
from __future__ import annotations

import argparse
import sys

from ..paths import RECORDINGS_DIR
from .importers import KNOWN_LABELS, import_raw_iq, import_sigmf


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="python -m pluto_scanner.ml.import_dataset",
        description="Import SigMF or raw float32 IQ into iq_recordings",
    )
    p.add_argument("--format", choices=("sigmf", "dat"), required=True)
    p.add_argument("--src", required=True, help="source file or SigMF folder")
    p.add_argument("--out", default=str(RECORDINGS_DIR))
    p.add_argument("--label", default="", choices=KNOWN_LABELS + ("",),
                   help="morphology label for training")
    p.add_argument("--sample-rate", type=float, default=0.0,
                   help="required for --format dat")
    p.add_argument("--center", type=float, default=0.0,
                   help="centre frequency in Hz (optional for SigMF)")
    p.add_argument("--start-seconds", type=float, default=0.0)
    p.add_argument("--max-seconds", type=float, default=10.0)
    return p


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        if args.format == "sigmf":
            result = import_sigmf(
                args.src, args.out,
                label=args.label or None,
                start_seconds=args.start_seconds,
                max_seconds=args.max_seconds,
            )
        else:
            if args.sample_rate <= 0:
                print("Для --format dat нужен --sample-rate", file=sys.stderr)
                return 2
            result = import_raw_iq(
                args.src, args.out,
                sample_rate=args.sample_rate,
                center_freq=args.center,
                label=args.label or None,
                start_seconds=args.start_seconds,
                max_seconds=args.max_seconds,
            )
    except Exception as exc:
        print(f"Ошибка импорта: {exc}", file=sys.stderr)
        return 1
    print(f"Импортировано: {result.info.cf32_path}")
    print(f"Метка: {result.info.label or 'без метки'}")
    print(f"Отсчётов: {result.info.samples}")
    print(f"Частота: {result.info.center_freq / 1e6:.3f} МГц, "
          f"полоса: {result.info.sample_rate / 1e6:.3f} МГц")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
