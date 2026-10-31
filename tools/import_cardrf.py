"""Import the Cardinal RF (CardRF) dataset into the app's recording format.

CardRF ships one ``.mat`` file per recording (5,000,000 complex samples) and
is published under CC BY 4.0 by the University of Louisville.  Download it
from the IEEE DataPort page (the OneDrive link needs a free Microsoft
account); this tool does not download anything.

The label is taken from the folder or file name:

===============  ==================================================
``wifi``/``wlan``  ``WIFI``    (negative for the binary drone model)
``bluetooth``/``bt`` ``NARROW``  (negative: narrowband non-drone link)
``uav``/``drone``/``rc``/``controller``/``telemetry``  ``TELEMETRY``
                                                            (positive)
===============  ==================================================

Examples::

    # See what is inside before importing anything
    python -m tools.import_cardrf --root D:\\CardRF --inspect

    # Import 40 files of each class
    python -m tools.import_cardrf --root D:\\CardRF --limit 40

    # Import everything (about 65 GB of .mat becomes ~4 GB of .cf32)
    python -m tools.import_cardrf --root D:\\CardRF --limit 0
"""
from __future__ import annotations

import argparse
from pathlib import Path

from pluto_scanner.ml.importers import import_mat
from pluto_scanner.paths import RECORDINGS_DIR

LABEL_RULES: tuple[tuple[tuple[str, ...], str], ...] = (
    (("wifi", "wi-fi", "wlan", "802.11"), "WIFI"),
    (("bluetooth", "btle", "ble"), "NARROW"),
    (("uav", "drone", "controller", "telemetry", "remote", "rc_"), "TELEMETRY"),
)


def infer_label(path: Path) -> str:
    text = str(path).lower().replace("\\", "/")
    for needles, label in LABEL_RULES:
        if any(needle in text for needle in needles):
            return label
    return ""


def find_files(root: Path) -> list[Path]:
    return sorted(
        path for path in root.rglob("*")
        if path.is_file() and path.suffix.lower() == ".mat"
    )


def inspect(root: Path, limit: int) -> int:
    from scipy.io import whosmat

    files = find_files(root)
    print(f"найдено .mat: {len(files)}")
    counts: dict[str, int] = {}
    for path in files:
        label = infer_label(path) or "?"
        counts[label] = counts.get(label, 0) + 1
    print("по меткам:", counts)
    for path in files[:max(1, limit)]:
        try:
            variables = whosmat(path)
        except Exception as exc:  # pragma: no cover - depends on user files
            print(f"  {path.name}: не читается ({exc})")
            continue
        described = ", ".join(
            f"{name}{shape}" for name, shape, _kind in variables
        )
        print(f"  {path.name} -> {infer_label(path) or '?'}: {described}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", required=True, help="folder with CardRF .mat")
    parser.add_argument("--out", default=str(RECORDINGS_DIR))
    parser.add_argument("--sample-rate", type=float, default=20e6)
    parser.add_argument("--center", type=float, default=0.0)
    parser.add_argument("--max-seconds", type=float, default=0.25)
    parser.add_argument("--limit", type=int, default=40,
                        help="files per label; 0 means all")
    parser.add_argument("--inspect", action="store_true",
                        help="only list files and their variables")
    parser.add_argument("--dry-run", action="store_true",
                        help="show what would be imported")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"нет папки {root}")
        return 2
    if args.inspect:
        return inspect(root, max(10, args.limit))

    files = find_files(root)
    if not files:
        print("не найдено ни одного .mat")
        return 2

    per_label: dict[str, int] = {}
    imported = 0
    for path in files:
        label = infer_label(path)
        if not label:
            continue
        already = per_label.get(label, 0)
        if args.limit and already >= args.limit:
            continue
        if args.dry_run:
            print(f"  [dry] {label:10s} {path.name}")
        else:
            try:
                result = import_mat(
                    path, args.out,
                    sample_rate=args.sample_rate,
                    center_freq=args.center,
                    label=label,
                    max_seconds=args.max_seconds,
                )
            except Exception as exc:
                print(f"  ошибка {path.name}: {exc}")
                continue
            print(f"  {label:10s} {result.info.recording_id} "
                  f"{result.info.samples} отсчётов")
        per_label[label] = already + 1
        imported += 1
    print(f"\nвсего: {imported}, по меткам: {per_label}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
