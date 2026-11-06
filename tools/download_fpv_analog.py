# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Download the FPV Analogue Video IQ Dataset from Zenodo.

Record: "FPV Analogue Video IQ Dataset", DOI 10.5281/zenodo.19870020,
CC BY 4.0.  Captured with a HackRF One at 5.8 GHz, 20 MS/s; contains analog
video transmissions and ground-truth sweeps without an active transmitter.

The record is split into ten ~1-3 GB chunks.  Download only what you need::

    python -m tools.download_fpv_analog --chunks 10
    python -m tools.download_fpv_analog --chunks 8,9,10 --jobs 3
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

API = "https://zenodo.org/api/records/19870020"
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
    return files


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
    next_report = have + REPORT_BYTES
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
    parser.add_argument("--dest", default=r"Z:\datasets\FPV_Analog")
    parser.add_argument(
        "--chunks", default="10",
        help="comma-separated chunk numbers, e.g. 8,9,10 (default: 10)",
    )
    parser.add_argument("--jobs", type=int, default=1)
    args = parser.parse_args(argv)

    dest = Path(args.dest)
    dest.mkdir(parents=True, exist_ok=True)
    wanted = {
        int(item) for item in str(args.chunks).replace(" ", "").split(",")
        if item
    }
    files = record_files()
    csv = [item for item in files if item["key"].endswith(".csv")]
    chunks = [
        item for item in files
        if item["key"].startswith("chunk")
        and int(item["key"].removeprefix("chunk").removesuffix(".zip"))
        in wanted
    ]
    if not chunks:
        print(f"нет кусков {sorted(wanted)}")
        return 2
    total = sum(item["size"] for item in csv + chunks)
    print(f"файлов: {len(csv) + len(chunks)}, всего {total / 1e9:.2f} ГБ")

    failed = 0
    for item in csv:
        try:
            if not download(item, dest):
                failed += 1
        except Exception as exc:
            failed += 1
            print(f"  ошибка {item['key']}: {exc}", flush=True)

    jobs = max(1, min(int(args.jobs), len(chunks)))
    with ThreadPoolExecutor(max_workers=jobs) as pool:
        futures = {pool.submit(download, item, dest): item for item in chunks}
        for future in as_completed(futures):
            item = futures[future]
            try:
                if not future.result():
                    failed += 1
            except Exception as exc:
                failed += 1
                print(f"  ошибка {item['key']}: {exc}", flush=True)
    print(f"готово, ошибок: {failed}")
    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
