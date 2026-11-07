# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Bench transmitter: analogue TV test card from an ADALM-PLUTO.

This is a **bench tool**, not part of the passive receiver.  It builds a
composite PAL/NTSC signal with the same test card as the application and
either writes it to a ``.cf32`` file (safe, default) or streams it to a
Pluto::

    # Check the generator and the decoder without transmitting anything:
    python -m tools.pluto_tx_video --out test_card.cf32

    # Transmit to antennas on the desk (or through 30-40 dB of attenuation):
    python -m tools.pluto_tx_video --tx --freq 1241e6 --gain -10

A direct cable from the Pluto into the HackRF without an attenuator will
overload and can damage the receiver input.  Keep the TX gain low and tune
the Pluto 1 MHz away from the receiver centre: a carrier exactly on the
HackRF DC spike is swallowed by the LO leakage.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np

from sdr_scanner.devices.pluto_tx import PlutoTransmitter
from sdr_scanner.video.analog import STANDARDS
from sdr_scanner.video.testcard import build


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--standard", choices=tuple(STANDARDS), default="PAL")
    parser.add_argument("--freq", type=float, default=1241e6)
    parser.add_argument("--rate", type=float, default=20e6)
    parser.add_argument("--deviation", type=float, default=3.5e6)
    parser.add_argument("--seconds", type=float, default=None,
                        help="длина цикла; по умолчанию 0.12 с для файла "
                             "и одно поле (20 мс) для передачи")
    parser.add_argument("--out", help="записать cf32 вместо передачи")
    parser.add_argument("--tx", action="store_true", help="передавать с Pluto")
    parser.add_argument("--gain", type=float, default=-10.0,
                        help="tx_hardwaregain, дБ (0 — максимум)")
    parser.add_argument("--amplitude", type=float, default=0.5,
                        help="амплитуда IQ, 0..1 от полной шкалы")
    parser.add_argument("--duration", type=float, default=20.0,
                        help="сколько секунд передавать, потом выключить")
    args = parser.parse_args(argv)

    if not args.out and not args.tx:
        parser.error("укажите --out файл.cf32 или --tx")

    standard = STANDARDS[args.standard]
    field_only = bool(args.tx and args.seconds is None)
    seconds = args.seconds
    if seconds is None:
        seconds = 0.02 if field_only else 0.12
    iq, field_samples = build(
        standard, args.rate, seconds, args.deviation, field_only,
    )
    print(
        f"{standard.name}: {iq.size} отсчётов, поле {field_samples} "
        f"({field_samples / args.rate * 1000:.1f} мс), "
        f"девиация ±{args.deviation / 1e6:.1f} МГц"
    )
    if args.out:
        Path(args.out).write_bytes(iq.tobytes())
        print(
            f"записано {args.out} · {iq.size / args.rate:.3f} с · "
            f"{args.rate / 1e6:.2f} МС/с · {args.freq / 1e6:.3f} МГц"
        )
        return 0

    whole = (iq.size // field_samples) * field_samples
    transmitter = PlutoTransmitter()
    try:
        uri = transmitter.start(
            iq[:whole], args.rate, args.freq, args.gain, args.amplitude,
        )
    except Exception as exc:
        print(f"не удалось запустить передачу: {exc}")
        return 1
    print(
        f"Pluto {uri}: {args.freq / 1e6:.3f} МГц · "
        f"{args.rate / 1e6:.2f} МС/с · усиление {args.gain:+.1f} дБ · "
        f"{whole} отсчётов в цикле. Остановлю через {args.duration:.0f} с."
    )
    try:
        deadline = time.monotonic() + args.duration
        while time.monotonic() < deadline:
            time.sleep(0.5)
    except KeyboardInterrupt:
        pass
    finally:
        transmitter.stop()
        print("передача остановлена.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
