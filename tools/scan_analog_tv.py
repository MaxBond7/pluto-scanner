# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Scan Russian analog TV carriers with a HackRF.

Russia uses 625-line SECAM D/K; the line rate is the same 15.625 kHz as PAL,
so the monochrome video decoder can show a SECAM picture without colour.

    python -m tools.scan_analog_tv --band uhf
    python -m tools.scan_analog_tv --band both --gain 24 --seconds 0.12

The tool only receives.  A digital DVB-T2 multiplex will look like a wide
signal without a 15.6 kHz line and is not reported as analog TV.
"""
from __future__ import annotations

import argparse
import sys
import time

import numpy as np
from PySide6.QtCore import QCoreApplication, QEventLoop, QTimer

from sdr_scanner.devices.hackrf import HackRFWorker, clamp_rate, probe_hackrf
from sdr_scanner.drone.deep_look import _analog_line
from sdr_scanner.ml.behavior import analyze

# Russian D/K video carriers.
VHF = [49.75, 59.25, 77.25, 85.25, 93.25,
       175.25, 183.25, 191.25, 199.25, 207.25, 215.25, 223.25]
UHF = [471.25 + 8.0 * index for index in range(40)]   # channels 21-60


def wait(milliseconds: int) -> None:
    loop = QEventLoop()
    QTimer.singleShot(milliseconds, loop.quit)
    loop.exec()


def channels(band: str) -> list[tuple[str, float]]:
    result: list[tuple[str, float]] = []
    for index, mhz in enumerate(VHF, start=1):
        result.append((f"VHF {index}", mhz * 1e6))
    for index, mhz in enumerate(UHF, start=21):
        result.append((f"UHF {index}", mhz * 1e6))
    if band == "vhf":
        return result[:len(VHF)]
    if band == "uhf":
        return result[len(VHF):]
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--band", choices=("vhf", "uhf", "both"), default="uhf")
    parser.add_argument("--gain", type=float, default=28.0)
    parser.add_argument("--seconds", type=float, default=0.12)
    parser.add_argument("--serial", default="")
    args = parser.parse_args(argv)

    info = probe_hackrf()
    if not info.get("ok"):
        print(info.get("error"))
        return 2
    serials = list(info.get("serials") or [])
    if not serials:
        print("HackRF не найден")
        return 2
    serial = args.serial or serials[0]
    app = QCoreApplication([])
    rate = clamp_rate(20e6)
    from sdr_scanner.model import DeviceConfig
    worker = HackRFWorker(DeviceConfig(
        device_id="tv-scan", name="TV scan", kind="hackrf", uri=serial,
        center_freq=471.25e6, sample_rate=rate, bandwidth=8e6,
        gain=float(args.gain),
    ))
    blocks: list[tuple[float, np.ndarray]] = []
    worker.iq_ready.connect(lambda block: blocks.append(
        (float(block.center_freq),
         np.asarray(block.samples, dtype=np.complex64))
    ))
    errors: list[str] = []
    worker.error.connect(lambda _did, message: errors.append(message))
    worker.start()
    wait(500)
    # Keep the full 20 MHz passband.  A narrower baseband filter raises the
    # noise floor inside its passband and makes every channel look occupied.
    worker.set_bandwidth(20.0e6)

    print(
        f"{'канал':8s} {'видео, МГц':>10s} {'SNR':>6s} {'занято':>7s} "
        f"{'строка':>10s} {'сила':>7s} вердикт"
    )
    found = 0
    for name, freq in channels(args.band):
        if errors:
            print("ошибка:", errors[-1])
            break
        blocks.clear()
        worker.set_center_freq(freq)
        wait(300)
        blocks.clear()
        wait(int(args.seconds * 1000))
        usable = [
            sample for center, sample in blocks
            if abs(center - freq) < 1.0e6
        ]
        if not usable:
            print(f"{name:8s} {freq / 1e6:10.2f}  нет данных")
            continue
        iq = np.concatenate(usable)
        behavior = analyze(iq, rate, max_seconds=args.seconds)
        line = _analog_line(behavior)
        # SECAM/PAL TV line is 15.625 kHz.  A 16 kHz switching spur is not TV.
        if line is not None and not (15.3 <= line[1] <= 15.9):
            line = None
        if line is not None and behavior.occupied < 0.10:
            line = None
        line_text = f"{line[1]:.2f}" if line else "—"
        strength = f"{line[2]:.1f}" if line else "—"
        verdict = "АНАЛОГОВОЕ ТВ?" if line else (
            "широкополосный сигнал" if behavior.occupied > 0.25
            else "нет"
        )
        print(
            f"{name:8s} {freq / 1e6:10.2f} {behavior.snr_db:6.1f} "
            f"{behavior.occupied:7.2f} {line_text:>10s} {strength:>7s} "
            f"{verdict}"
        )
        if line:
            found += 1
    worker.stop()
    print(f"кандидатов с аналоговой строкой: {found}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
