# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""First-contact check for a real HackRF One.

Run this before opening the GUI when the board arrives::

    python -m tools.check_hackrf
    python -m tools.check_hackrf --seconds 2 --freq 2437e6 --rate 20.48e6
    python -m tools.check_hackrf --out Z:\\hackrf_2437cf32

It reports the serial, the effective sample rate, ADC clipping, DC offset,
the spectrum peak, and the behaviour features at 20 MHz (duty, bursts, hops,
channels).  Receive only.
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import QCoreApplication, QTimer

from sdr_scanner.devices.hackrf import HackRFWorker, clamp_rate, probe_hackrf
from sdr_scanner.ml.behavior import analyze
from sdr_scanner.model import DeviceConfig


def _parse_hz(value: str) -> float:
    text = str(value).strip().lower().replace(" ", "")
    multiplier = 1.0
    if text.endswith("ghz"):
        text, multiplier = text[:-3], 1e9
    elif text.endswith("mhz"):
        text, multiplier = text[:-3], 1e6
    elif text.endswith("khz"):
        text, multiplier = text[:-3], 1e3
    return float(text) * multiplier


def _spectrum(iq: np.ndarray, rate: float, center: float, frame: int = 8192):
    if iq.size < frame:
        return 0.0, 0.0, 0.0, 0.0
    window = np.hanning(frame).astype(np.float32)
    block = iq[-frame:]
    spec = np.abs(np.fft.fftshift(np.fft.fft(block * window)))
    db = 20.0 * np.log10(spec + 1e-20)
    freqs = np.fft.fftshift(np.fft.fftfreq(frame, 1.0 / rate)) + center
    peak = int(np.argmax(db))
    floor = float(np.percentile(db, 20))
    return float(freqs[peak]), float(db[peak]), floor, float(np.median(db))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seconds", type=float, default=2.0)
    parser.add_argument("--freq", type=_parse_hz, default=2437e6)
    parser.add_argument("--rate", type=_parse_hz, default=20.48e6)
    parser.add_argument("--bandwidth", type=_parse_hz, default=20e6)
    parser.add_argument("--gain", type=float, default=32.0)
    parser.add_argument("--serial", default="")
    parser.add_argument("--out", default="", help="save cf32 IQ here")
    args = parser.parse_args(argv)

    info = probe_hackrf()
    print("library:", info.get("library") or "—")
    if not info.get("ok"):
        print("ОШИБКА:", info.get("error"))
        print("Установите драйвер WinUSB и libhackrf — docs/HACKRF.md.")
        return 2
    serials = list(info.get("serials") or [])
    print("устройства:", ", ".join(serials) or "нет")
    if not serials:
        print("HackRF не найден. Проверьте кабель, питание и драйвер.")
        return 2
    serial = args.serial or serials[0]
    if serial not in serials:
        print(f"Серийный номер {serial} не найден.")
        return 2

    rate = clamp_rate(args.rate)
    if abs(rate - float(args.rate)) > 1.0:
        print(f"скорость ограничена устройством: {rate / 1e6:.2f} МС/с")

    app = QCoreApplication([])
    config = DeviceConfig(
        device_id="hackrf-check",
        name="HackRF check",
        kind="hackrf",
        uri=serial,
        center_freq=float(args.freq),
        sample_rate=rate,
        bandwidth=float(args.bandwidth),
        gain=float(args.gain),
        fft_size=4096,
        seed=1,
    )
    worker = HackRFWorker(config)
    blocks: list[np.ndarray] = []
    state = {"started": 0.0, "error": "", "done": False}

    worker.iq_ready.connect(lambda block: blocks.append(
        np.asarray(block.samples, dtype=np.complex64)
    ))
    worker.info_ready.connect(
        lambda _did, actual: print("параметры:", json.dumps(actual, ensure_ascii=False))
    )
    worker.status_changed.connect(
        lambda _did, status: print("статус:", status, flush=True)
    )

    def on_error(_did: str, message: str) -> None:
        state["error"] = message
        print("ошибка:", message)

    worker.error.connect(on_error)

    def tick() -> None:
        if state["done"]:
            return
        if state["error"]:
            state["done"] = True
            worker.stop()
            app.quit()
            return
        elapsed = time.monotonic() - state["started"]
        if elapsed >= float(args.seconds):
            state["done"] = True
            worker.stop()
            app.quit()

    worker.start()
    state["started"] = time.monotonic()
    timer = QTimer()
    timer.setInterval(50)
    timer.timeout.connect(tick)
    timer.start()
    app.exec()

    if not blocks:
        print("Нет IQ. Причина:", state["error"] or "устройство не ответило")
        return 1

    iq = np.concatenate(blocks)
    duration = float(iq.size) / float(rate)
    expected = float(args.seconds)
    print()
    print(f"блоков: {len(blocks)}")
    print(f"отсчётов: {iq.size}")
    print(f"длительность: {duration:.2f} с из {expected:.2f} с "
          f"({100.0 * duration / max(expected, 1e-9):.0f}%)")
    print(f"реальная скорость: {iq.size / max(expected, 1e-9) / 1e6:.2f} МС/с")
    peak = float(max(np.max(np.abs(iq.real)), np.max(np.abs(iq.imag))))
    clipped = float(np.mean(
        np.maximum(np.abs(iq.real), np.abs(iq.imag)) >= 0.99
    )) * 100.0
    dc = complex(float(np.mean(iq.real)), float(np.mean(iq.imag)))
    print(f"макс. |I| или |Q|: {peak:.3f} (полная шкала 1.0)")
    print(f"перегрузка: {clipped:.2f}% отсчётов")
    print(f"DC: {abs(dc):.4f}")
    if clipped > 1.0:
        print("  ВНИМАНИЕ: перегрузка — уменьшите усиление.")
    if duration < 0.85 * expected:
        print("  ВНИМАНИЕ: поток медленнее запрошенного — проверьте USB/драйвер.")
    if abs(dc) > 0.05:
        print("  ВНИМАНИЕ: заметный DC — это нормальный spur HackRF в центре.")

    peak_hz, peak_db, floor_db, median_db = _spectrum(
        iq, float(rate), float(args.freq)
    )
    print(f"пик: {peak_hz / 1e6:.3f} МГц, {peak_db:.1f} дБ, "
          f"шум {floor_db:.1f} дБ (медиана {median_db:.1f})")

    behavior = analyze(iq, float(rate), max_seconds=min(4.0, duration))
    print("поведение:", json.dumps(behavior.to_dict(), ensure_ascii=False))
    if float(rate) >= 15e6:
        print("перескоки и каналы здесь измеримы: полоса "
              f"{float(rate) / 1e6:.1f} МГц")
    else:
        print("полоса меньше 15 МГц: перескоки и каналы недостоверны")

    if args.out:
        out = Path(args.out)
        out.parent.mkdir(parents=True, exist_ok=True)
        iq.astype(np.complex64).tofile(out)
        meta = out.with_suffix(".json")
        meta.write_text(json.dumps({
            "center_freq": float(args.freq),
            "sample_rate": float(args.rate),
            "gain_db": float(args.gain),
            "samples": int(iq.size),
            "serial": serial,
        }, ensure_ascii=False, indent=2), encoding="utf-8")
        print("IQ сохранён:", out)
    return 0


if __name__ == "__main__":
    sys.exit(main())
