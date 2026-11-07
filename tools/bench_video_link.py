# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Bench link check: Pluto transmits the test card, HackRF receives it.

One process owns both radios, so the Pluto context stays alive while the
HackRF records and the transmitter is muted before the program exits.  This
avoids the Pluto+ dropping off USB between separate TX and RX runs.

    python -m tools.bench_video_link
    python -m tools.bench_video_link --freq 2400e6 --tx-gain -5 --rx-gain 16

The Pluto is tuned 1 MHz above the HackRF centre: an analogue video carrier
sitting exactly on the HackRF's DC spike is swallowed by the LO leakage.
"""
from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

import numpy as np
from PIL import Image
from PySide6.QtCore import QCoreApplication

from sdr_scanner.devices.hackrf import HackRFWorker, probe_hackrf
from sdr_scanner.devices.pluto import _ensure_pylibiio_windows, scan_pluto_uris
from sdr_scanner.model import DeviceConfig
from sdr_scanner.video.analog import STANDARDS, decode_frame
from sdr_scanner.video.testcard import build


def _open_pluto(uri: str | None):
    _ensure_pylibiio_windows()
    import adi  # type: ignore

    found = [item for item in scan_pluto_uris() if item.startswith("usb:")]
    if not found:
        raise SystemExit("Pluto не найден по USB — переподключите плату.")
    return adi.Pluto(uri=uri or found[0]), found[0]


def _capture(freq: float, gain: float, seconds: float) -> np.ndarray:
    info = probe_hackrf()
    if not info.get("ok"):
        raise SystemExit(f"HackRF не найден: {info.get('error')}")
    serial = info["serials"][0]
    rate = 20e6
    app = QCoreApplication.instance() or QCoreApplication([])
    config = DeviceConfig(
        device_id="bench", name="Bench", kind="hackrf", uri=serial,
        center_freq=freq, sample_rate=rate, bandwidth=rate, gain=gain,
        fft_size=4096, seed=1,
    )
    worker = HackRFWorker(config)
    blocks: list[np.ndarray] = []
    worker.iq_ready.connect(
        lambda block: blocks.append(
            np.asarray(block.samples, dtype=np.complex64)
        )
    )
    worker.start()
    started = time.monotonic()
    while time.monotonic() - started < seconds:
        app.processEvents()
        time.sleep(0.01)
    worker.stop()
    app.processEvents()
    if not blocks:
        raise SystemExit("HackRF не отдал отсчёты.")
    return np.concatenate(blocks)[: int(rate * seconds)], rate


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--freq", type=float, default=1240e6,
                        help="центр приёма HackRF")
    parser.add_argument("--offset", type=float, default=1e6,
                        help="насколько Pluto выше центра приёма")
    parser.add_argument("--standard", choices=tuple(STANDARDS), default="PAL")
    parser.add_argument("--deviation", type=float, default=3.5e6)
    parser.add_argument("--seconds", type=float, default=1.0)
    parser.add_argument("--tx-gain", type=float, default=0.0)
    parser.add_argument("--rx-gain", type=float, default=8.0)
    parser.add_argument("--uri", default=None)
    parser.add_argument("--out", default="bench_frame.png")
    args = parser.parse_args(argv)

    standard = STANDARDS[args.standard]
    iq, field_samples = build(
        standard, 20e6, 0.02, args.deviation, field_only=True,
    )
    whole = (iq.size // field_samples) * field_samples
    data = (iq[:whole] * 0.5 * 2 ** 14).astype(np.complex64)

    sdr, uri = _open_pluto(args.uri)
    sdr.sample_rate = int(20e6)
    sdr.tx_rf_bandwidth = int(20e6)
    sdr.tx_lo = int(args.freq + args.offset)
    sdr.tx_hardwaregain_chan0 = float(args.tx_gain)
    sdr.tx_cyclic_buffer = True
    sdr.tx(data)
    print(
        f"Pluto {uri}: {args.freq/1e6:.3f} МГц + {args.offset/1e6:.2f} МГц, "
        f"усиление {args.tx_gain:+.1f} дБ, {standard.name}",
        flush=True,
    )
    try:
        time.sleep(0.4)
        print("принимаю HackRF…", flush=True)
        iq_rx, rate = _capture(args.freq, args.rx_gain, args.seconds)
    finally:
        # Mute first: a Pluto+ can keep the last cyclic buffer playing after
        # the host process is gone.
        try:
            sdr.tx_hardwaregain_chan0 = -89.75
        except Exception:
            pass
        try:
            sdr.tx_destroy_buffer()
        except Exception:
            pass
        try:
            del sdr
        except Exception:
            pass

    rms = float(np.sqrt(np.mean(np.abs(iq_rx) ** 2)))
    peak = float(np.abs(iq_rx).max())
    clip = float(np.mean(np.abs(iq_rx) >= 0.999) * 100.0)
    print(f"принято {iq_rx.size / rate * 1000:.0f} мс, rms {rms:.4f}, "
          f"peak {peak:.3f}, клип {clip:.2f}%")

    n = 1 << 15
    if iq_rx.size >= n:
        spec = np.zeros(n)
        for start in range(0, iq_rx.size - n, n):
            spec += np.abs(np.fft.fftshift(
                np.fft.fft(iq_rx[start:start + n] * np.hanning(n))
            )) ** 2
        spec = 10 * np.log10(spec / spec.max() + 1e-12)
        freqs = np.fft.fftshift(np.fft.fftfreq(n, 1 / rate))
        index = int(np.argmax(spec))
        print(f"спектр: пик {freqs[index]/1e6:+.2f} МГц, "
              f"медиана {np.median(spec):.1f} дБ")

    saved = 0
    for candidate in (standard, *[s for s in STANDARDS.values()
                                  if s.name != standard.name]):
        frame = decode_frame(iq_rx, rate, candidate)
        if frame is None:
            print(f"{candidate.name}: кадр не собран")
            continue
        path = Path(args.out)
        Image.fromarray(frame.image, "L").save(path)
        print(
            f"{candidate.name} -> {frame.standard} {frame.lines} строк, "
            f"{frame.line_hz:.1f} Гц, кадр={frame.frame_locked}, "
            f"качество={frame.quality:.2f} -> {path}"
        )
        saved += 1
        if saved == 1:
            break
    return 0 if saved else 1


if __name__ == "__main__":
    sys.exit(main())
