# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Keep only the newest backup folders and delete the older ones.

The project rule is simple: on the backup disk there are three recent
versions, everything older goes.  This script does that by parsing the
``vX.Y.Z`` part of the folder name, so a folder without a version (for
example the personal manual) is never touched.

Examples::

    # See what would be deleted
    python -m tools.prune_backups --dry-run

    # Keep the three newest versions
    python -m tools.prune_backups

    # A different disk or a different depth
    python -m tools.prune_backups --root E:\\Backups --keep 5
"""
from __future__ import annotations

import argparse
import os
import re
import shutil
import stat
import sys
from pathlib import Path

DEFAULT_ROOT = r"Z:\SDRScanner_Backups"
VERSION_RE = re.compile(r"_v(\d+)\.(\d+)\.(\d+)(?:_|$)")


def _force_remove(function, path, _error) -> None:
    """Retry a failed delete after clearing the read-only flag."""
    try:
        os.chmod(path, stat.S_IWRITE)
        function(path)
    except Exception as exc:
        print(f"  не удалось удалить {path}: {exc}")


def remove_tree(path: Path) -> bool:
    """Delete a folder, coping with read-only files left by Git."""
    try:
        shutil.rmtree(path, onerror=_force_remove)
    except Exception as exc:
        print(f"  ошибка при удалении {path.name}: {exc}")
        return False
    return not path.exists()


def version_key(name: str) -> tuple[int, int, int] | None:
    """Return ``(major, minor, patch)`` from ``..._v0.20.2_name``."""
    match = VERSION_RE.search(name)
    if match is None:
        return None
    return tuple(int(part) for part in match.groups())


def folder_size(path: Path) -> int:
    total = 0
    for item in path.rglob("*"):
        try:
            if item.is_file():
                total += item.stat().st_size
        except OSError:
            continue
    return total


def plan(root: Path, keep: int) -> tuple[list[Path], list[Path]]:
    """Split version folders into (keep, remove), newest first."""
    entries: list[tuple[tuple[int, int, int], float, Path]] = []
    for item in root.iterdir():
        if not item.is_dir():
            continue
        key = version_key(item.name)
        if key is None:
            continue
        try:
            stamp = item.stat().st_mtime
        except OSError:
            stamp = 0.0
        entries.append((key, stamp, item))
    entries.sort(key=lambda entry: (entry[0], entry[1]), reverse=True)
    keep_count = max(0, int(keep))
    kept = [entry[2] for entry in entries[:keep_count]]
    removed = [entry[2] for entry in entries[keep_count:]]
    return kept, removed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", default=DEFAULT_ROOT,
                        help=f"backup folder (default {DEFAULT_ROOT})")
    parser.add_argument("--keep", type=int, default=3,
                        help="how many newest versions to keep (default 3)")
    parser.add_argument("--dry-run", action="store_true",
                        help="only print what would be deleted")
    args = parser.parse_args(argv)

    root = Path(args.root)
    if not root.exists():
        print(f"нет папки {root}")
        return 2
    kept, doomed = plan(root, args.keep)
    removed = 0
    failed = 0
    for path in doomed:
        size_gb = folder_size(path) / (1024 ** 3)
        if args.dry_run:
            print(f"[dry] удалить {path.name} ({size_gb:.2f} ГБ)")
            continue
        if remove_tree(path):
            removed += 1
            print(f"удалено {path.name} ({size_gb:.2f} ГБ)")
        else:
            failed += 1
    print(f"оставлено {len(kept)} из {len(kept) + len(doomed)}")
    for path in kept:
        print(f"  {path.name}")
    if failed:
        print(f"не удалось удалить папок: {failed}")
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
