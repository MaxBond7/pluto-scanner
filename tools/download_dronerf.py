"""Download the DroneRF dataset from Mendeley Data.

DroneRF (Al-Sa'd et al., 2019) is published under CC BY 4.0 through the
Mendeley Data open API, so no login is needed.  The 23 RAR archives are
4.03 GB and unpack to about 40 GB.

Usage::

    python -m tools.download_dronerf --out Z:\\datasets\\DroneRF

The files are skipped when a complete copy already exists, so the command can
be re-run after an interrupted download.
"""
from __future__ import annotations

import argparse
import json
import urllib.request
from pathlib import Path

API = "https://data.mendeley.com/api/datasets/f4c2b4n755/files"
USER_AGENT = "pluto-scanner-dronerf-downloader"


def list_files() -> list[dict]:
    request = urllib.request.Request(API, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(request, timeout=60) as response:
        return json.load(response)


def download(target: Path, *, progress=None) -> int:
    files = list_files()
    total = sum(int(item["content_details"]["size"]) for item in files)
    done = 0
    print(f"files={len(files)} total={total / 1e9:.2f} GB", flush=True)
    for index, item in enumerate(files, start=1):
        name = str(item["filename"])
        size = int(item["content_details"]["size"])
        url = str(item["content_details"]["download_url"])
        destination = target / name
        if destination.exists() and destination.stat().st_size == size:
            done += size
            print(f"[{index}/{len(files)}] skip {name}", flush=True)
            continue
        part = destination.with_suffix(destination.suffix + ".part")
        print(
            f"[{index}/{len(files)}] {name} {size / 1e6:.0f} MB", flush=True
        )
        request = urllib.request.Request(
            url, headers={"User-Agent": USER_AGENT}
        )
        with urllib.request.urlopen(request, timeout=120) as source, \
                part.open("wb") as sink:
            while True:
                chunk = source.read(1024 * 1024)
                if not chunk:
                    break
                sink.write(chunk)
                done += len(chunk)
                if progress is not None:
                    progress(done, total, name)
        part.replace(destination)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--out", default="Z:\\datasets\\DroneRF",
        help="destination folder for the .rar archives",
    )
    args = parser.parse_args(argv)
    target = Path(args.out)
    target.mkdir(parents=True, exist_ok=True)
    download(target)
    print("done", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
