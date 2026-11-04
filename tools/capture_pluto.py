# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Record IQ from a real Pluto/Pluto+ into the app's own recording format.

The GUI already records, but a headless capture is handy for building
datasets: it writes the same ``cf32`` + ``.json`` pair, so the files appear in
the app's recordings list and in ``iq_recordings/`` exactly as if they were
made by hand.

Examples::

    # 5 seconds at the 2.4 GHz band centre, 20 MHz wide, 40 dB
    python -m tools.capture_pluto --center 2437e6 --seconds 5 --label WIFI

    # Several channels in one go
    python -m tools.capture_pluto --center 2412e6,2437e6,2462e6 --seconds 5

Only receive: this never transmits.  The first second of every capture is
discarded so the AGC/DC settling does not end up in the file.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from sdr_scanner.devices.pluto import (
    PLUTO_ADC_FULL_SCALE,
    _ensure_pylibiio_windows,
    scan_pluto_uris,
)
from sdr_scanner.paths import RECORDINGS_DIR
from sdr_scanner.recordings import (
    format_size,
    new_recording_info,
    save_info,
)

BLOCK_S = 0.02          # one monitor block (20 ms)
WARMUP_S = 1.0


def open_pluto(uri: str):
    _ensure_pylibiio_windows()
    import adi  # type: ignore

    if not uri:
        found = scan_pluto_uris()
        uri = next((u for u in found if u.startswith("usb:")), "")
    sdr = adi.Pluto(uri=uri) if uri else adi.Pluto()
    return sdr, uri


def configure(sdr, center: float, rate: float, gain: float, bandwidth: float) -> None:
    sdr.sample_rate = int(rate)
    sdr.rx_lo = int(center)
    sdr.rx_rf_bandwidth = int(bandwidth or rate)
    sdr.rx_buffer_size = max(4096, int(rate * BLOCK_S))
    for name in ("gain_control_mode_chan0", "gain_control_mode_chan"):
        try:
            setattr(sdr, name, "manual")
        except Exception:
            pass
    for name in ("rx_hardwaregain_chan0", "rx_hardwaregain_chan"):
        try:
            setattr(sdr, name, int(round(gain)))
        except Exception:
            continue


def capture(
    sdr,
    out_dir: Path,
    *,
    center: float,
    rate: float,
    seconds: float,
    gain: float,
    bandwidth: float,
    label: str,
    notes: str,
) -> Path:
    configure(sdr, center, rate, gain, bandwidth)
    info = new_recording_info(
        out_dir,
        device_id="pluto-1",
        device_name="Pluto+",
        device_kind="pluto",
        sample_rate=rate,
        center_freq=center,
        gain_db=gain,
        bandwidth_hz=bandwidth or rate,
    )
    info.label = label
    info.notes = notes
    save_info(info)

    wanted = int(round(rate * seconds))
    written = 0
    warmup = int(round(rate * WARMUP_S))
    dropped = 0
    started = time.perf_counter()
    with Path(info.cf32_path).open("wb") as handle:
        while written < wanted:
            block = np.asarray(sdr.rx(), dtype=np.complex64).ravel()
            if block.size == 0:
                time.sleep(0.005)
                continue
            block = block / PLUTO_ADC_FULL_SCALE
            if dropped < warmup:
                skip = min(warmup - dropped, block.size)
                dropped += skip
                block = block[skip:]
                if block.size == 0:
                    continue
            block = block[: wanted - written]
            handle.write(block.astype(np.complex64).tobytes())
            written += block.size
            elapsed = time.perf_counter() - started
            percent = 100.0 * written / max(1, wanted)
            print(
                f"\r  {info.recording_id}: {percent:5.1f}% "
                f"{format_size(written * 8)} / {format_size(wanted * 8)} "
                f"({elapsed:4.1f} с)",
                end="", flush=True,
            )
    print()
    info.samples = written
    info.complete = True
    save_info(info)
    return Path(info.cf32_path)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--uri", default="", help="libiio URI, e.g. usb:1.6.5")
    parser.add_argument("--center", default="2437e6",
                        help="centre frequency in Hz, or a comma list")
    parser.add_argument("--rate", type=float, default=20.48e6)
    parser.add_argument("--bandwidth", type=float, default=0.0)
    parser.add_argument("--gain", type=float, default=40.0)
    parser.add_argument("--seconds", type=float, default=5.0)
    parser.add_argument("--label", default="")
    parser.add_argument("--notes", default="")
    parser.add_argument("--out", default=str(RECORDINGS_DIR))
    args = parser.parse_args(argv)

    centers = [float(part) for part in str(args.center).split(",") if part.strip()]
    out_dir = Path(args.out)

    sdr, uri = open_pluto(args.uri)
    print(f"Pluto: {uri or 'default'}")
    print(f"fs {args.rate/1e6:.2f} МГц, усиление {args.gain:.0f} дБ, "
          f"по {args.seconds:g} с, папка {out_dir}")
    try:
        for center in centers:
            print(f"--- {center/1e6:.3f} МГц")
            capture(
                sdr, out_dir,
                center=center, rate=args.rate, seconds=args.seconds,
                gain=args.gain, bandwidth=args.bandwidth,
                label=args.label, notes=args.notes,
            )
    except KeyboardInterrupt:
        print("\nпрервано пользователем")
        return 130
    finally:
        try:
            sdr.rx_destroy_buffer()
        except Exception:
            pass
    return 0


if __name__ == "__main__":
    sys.exit(main())
