# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Download the Tampere drone RF recordings from Zenodo.

Record: "Radio-Frequency Control and Video Signal Recordings of Drones",
DOI 10.5281/zenodo.4264467, CC BY 4.0.  25 files, 8.56 GB, no login.

Each ``.bin`` is interleaved 16-bit little-endian I/Q, about one second:
120 MS/s for the 2.4 GHz recordings and 200 MS/s for the 5.8 GHz ones.

Examples::

    python -m tools.download_tampere --dest Z:\\datasets\\Tampere
    python -m tools.download_tampere --dest Z:\\datasets\\Tampere --only 2G
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
import urllib.request
from concurrent.futures import ThreadPoolExecutor, as_completed
from pathlib import Path

API = "https://zenodo.org/api/records/4264467"
CHUNK = 4 * 1024 * 1024
REPORT_BYTES = 100 * 1024 * 1024


def record_files() -> list[dict]:
    with urllib.request.urlopen(API, timeout=60) as response:
        record = json.loads(response.read().decode("utf-8"))
    files = []
    for item in record.get("files", []):
        links = item.get("links") or {}
        files.append({
            "key": item.get("key") or item.get("filename"),
            "size": int(item.get("size") or 0),
            "url": links.get("self") or links.get("content") or "",
        })
    return [item for item in files if item["key"].endswith(".bin")]


def priority(item: dict) -> tuple[int, str]:
    """Helpers first is handled elsewhere; 2.4 GHz before 5.8 GHz."""
    return (0 if "_2G" in item["key"] else 1, item["key"])


def download(item: dict, dest: Path) -> bool:
    target = dest / item["key"]
    if target.exists() and target.stat().st_size == item["size"]:
        print(f"  уже есть: {item['key']}", flush=True)
        return True
    part = target.with_suffix(target.suffix + ".part")
    have = part.stat().st_size if part.exists() else 0
    if have > item["size"]:
        part.unlink()
        have = 0
    request = urllib.request.Request(item["url"])
    if have:
        request.add_header("Range", f"bytes={have}-")
    started = time.perf_counter()
    next_report = REPORT_BYTES
    with urllib.request.urlopen(request, timeout=120) as response:
        mode = "ab" if have and response.status == 206 else "wb"
        if mode == "wb":
            have = 0
        with part.open(mode) as handle:
            while True:
                chunk = response.read(CHUNK)
                if not chunk:
                    break
                handle.write(chunk)
                have += len(chunk)
                if have >= next_report:
                    next_report = have + REPORT_BYTES
                    elapsed = max(0.1, time.perf_counter() - started)
                    print(
                        f"    {item['key']}: {have / 1e6:.0f} / "
                        f"{item['size'] / 1e6:.0f} МБ "
                        f"({have / 1e6 / elapsed:.1f} МБ/с)",
                        flush=True,
                    )
    if part.stat().st_size != item["size"]:
        print(f"  размер не совпал: {item['key']}", flush=True)
        return False
    shutil.move(part, target)
    print(f"  готово: {item['key']}", flush=True)
    return True


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", default=r"Z:\datasets\Tampere")
    parser.add_argument(
        "--only", default="", choices=("", "2G", "5G"),
        help="download only 2.4 GHz or only 5.8 GHz recordings",
    )
    parser.add_argument(
        "--jobs", type=int, default=6,
        help="parallel downloads (Zenodo throttles a single connection)",
    )
    args = parser.parse_args(argv)

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    files = record_files()
    if args.only:
        files = [item for item in files if f"_{args.only}" in item["key"]]
    files.sort(key=priority)
    total = sum(item["size"] for item in files)
    print(f"файлов: {len(files)}, всего {total / 1e9:.2f} ГБ", flush=True)

    failed = 0
    jobs = max(1, min(int(args.jobs), len(files)))
    print(f"потоков: {jobs}", flush=True)
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {
            pool.submit(download, item, dest): item for item in files
        }
        for future in as_completed(futures):
            item = futures[future]
            try:
                if not future.result():
                    failed += 1
            except Exception as exc:
                failed += 1
                print(f"  ошибка {item['key']}: {exc}", flush=True)
    print(f"готово, ошибок: {failed}", flush=True)
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
