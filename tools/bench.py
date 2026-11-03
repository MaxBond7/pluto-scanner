"""Micro-benchmarks for the hot paths of Pluto Scanner.

    python tools/bench.py
    python tools/bench.py --repeat 20

Prints milliseconds per call.  No hardware and no Qt needed except for the
stylesheet benchmark, which uses the pure-Python theme builder only.
"""
from __future__ import annotations

import argparse
import statistics
import sys
import time
from pathlib import Path
from typing import Callable

import numpy as np

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from pluto_scanner.dsp.detector import Detector
from pluto_scanner.dsp.spectrum import SpectrumAnalyzer
from pluto_scanner.dsp.tracker import ContactTracker
from pluto_scanner.model import Detection, SpectrumFrame
from pluto_scanner.scanner.peaks import decimate_mean, find_peaks
from pluto_scanner.ui.themes import BUILTIN_THEMES, build_stylesheet


def measure(name: str, func: Callable[[], object], repeat: int = 10) -> float:
    func()  # warm-up
    samples = []
    for _ in range(repeat):
        start = time.perf_counter()
        func()
        samples.append((time.perf_counter() - start) * 1000.0)
    median = statistics.median(samples)
    print(f"{name:44s} {median:8.2f} ms   (min {min(samples):.2f})")
    return median


def make_iq(n: int, peaks: int = 4) -> np.ndarray:
    rng = np.random.default_rng(1)
    iq = (rng.normal(0, 0.003, n) + 1j * rng.normal(0, 0.003, n))
    t = np.arange(n) / 1.024e6
    for index in range(peaks):
        freq = (index + 1) * 0.11e6
        iq += 0.02 * np.exp(2j * np.pi * freq * t)
    return iq.astype(np.complex64)


def make_psd(n: int = 4096, count: int = 6) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(2)
    psd = np.full(n, -100.0) + rng.normal(0, 0.6, n)
    for index in range(count):
        start = 200 + index * 500
        psd[start:start + 80] += 25.0
    freqs = np.linspace(433.0e6, 434.0e6, n)
    return freqs, psd


def make_frame(device: str = "sim") -> SpectrumFrame:
    freqs, psd = make_psd()
    detections = [
        Detection(
            freq_hz=433.1e6 + index * 0.1e6,
            bw_hz=20e3,
            peak_db=-70.0,
            snr_db=18.0,
            mean_snr_db=12.0,
            bin_start=200 + index * 500,
            bin_end=280 + index * 500,
            bin_hz=244.0,
        )
        for index in range(6)
    ]
    return SpectrumFrame(
        device_id=device,
        freqs=freqs,
        psd=psd,
        baseline=psd - 20.0,
        detections=detections,
        contacts=[],
        center_freq=433.5e6,
        sample_rate=1.024e6,
        timestamp=time.time(),
        calibrated=True,
        calibration_progress=1.0,
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repeat", type=int, default=10)
    args = parser.parse_args()
    repeat = max(1, args.repeat)

    iq_1m = make_iq(204_800)          # 200 ms at 1.024 MS/s (scanner block)
    iq_20m = make_iq(409_600)         # 20 ms at 20.48 MS/s (drone block)
    analyzer_2k = SpectrumAnalyzer(nfft=2048)
    analyzer_4k = SpectrumAnalyzer(nfft=4096)
    freqs, psd = make_psd()

    print("== DSP ==")
    measure("spectrum 1.024 MS/s, 200 ms, nfft 2048",
            lambda: analyzer_2k.compute(iq_1m, 1.024e6, 433.92e6), repeat)
    measure("spectrum 20.48 MS/s, 20 ms, nfft 4096",
            lambda: analyzer_4k.compute(iq_20m, 20.48e6, 2437e6), repeat)

    detector = Detector()
    for _ in range(30):
        detector.process(freqs, psd)
    measure("detector.process, 4096 bins",
            lambda: detector.process(freqs, psd), repeat)

    measure("find_peaks, 8192 bins",
            lambda: find_peaks(freqs, psd, center_hz=433.5e6), repeat)
    measure("decimate_mean 4096 -> 256",
            lambda: decimate_mean(psd, 256), repeat)
    measure("decimate_mean 8192 -> 1024",
            lambda: decimate_mean(np.tile(psd, 2), 1024), repeat)

    tracker = ContactTracker("sim")
    detections = make_frame().detections
    measure("contact tracker.update, 6 detections",
            lambda: tracker.update(detections, time.time(), 244.0), repeat)

    from pluto_scanner.drone.features import analyze_iq
    from pluto_scanner.drone.bands import DroneBand

    band = DroneBand("2.4", "2.4", 2400e6, 2483.5e6)
    measure("drone analyze_iq, 20 ms at 20.48 MS/s",
            lambda: analyze_iq(iq_20m, 20.48e6, 2437e6, band), repeat)

    print("== UI ==")
    measure("theme stylesheet build",
            lambda: build_stylesheet(BUILTIN_THEMES["mono"]), repeat)
    from pluto_scanner.ui.themes import qss
    sample = "color:#f87171; font-size:11px; padding:0 8px; border:1px solid #2b3d5f;"
    measure("qss() on a short stylesheet", lambda: qss(sample), repeat)

    print("== IO ==")
    from pluto_scanner.ui.waterfall_view import WaterfallView  # noqa: F401
    history, bins = 200, 8192
    buffer = np.zeros((history, bins), dtype=np.float32)
    row = np.linspace(-120, -40, bins).astype(np.float32)

    def shift() -> None:
        buffer[1:] = buffer[:-1]
        buffer[0] = row

    measure("waterfall history shift 200x8192", shift, repeat)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
