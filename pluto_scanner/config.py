"""Application defaults and band presets."""
from __future__ import annotations

from dataclasses import dataclass

APP_NAME = "Pluto Scanner"
ORG_NAME = "PlutoScanner"

DEFAULT_CENTER_FREQ = 433.92e6
DEFAULT_SAMPLE_RATE = 1.024e6
DEFAULT_FFT_SIZE = 2048
DEFAULT_GAIN_DB = 40.0
DEFAULT_BANDWIDTH_HZ = 1.0e6

# Stock ADALM-PLUTO (AD9363) tuning range.  Some Pluto+ clones are modified
# to 70 MHz - 6 GHz; the UI only warns, it never blocks tuning.
PLUTO_MIN_FREQ = 325e6
PLUTO_MAX_FREQ = 3.8e9

DETECTOR_THRESHOLD_DB = 8.0
DETECTOR_EXIT_DB = 4.0
CALIBRATION_FRAMES = 16
BASELINE_FRAMES = 96
BASELINE_UPDATE_EVERY = 8
MIN_DETECTION_BINS = 2
MAX_MISSES = 6

WATERFALL_HISTORY = 160
UI_FPS = 20.0
DETECTION_MIN_HITS = 2

NEW_CONTACT_SECONDS = 60.0


@dataclass(frozen=True)
class BandPreset:
    name: str
    frequency: float
    description: str


BANDS: list[BandPreset] = [
    BandPreset("433.92 ISM", 433.92e6, "Key fobs, sensors, LPD"),
    BandPreset("868 ISM", 868.0e6, "EU ISM"),
    BandPreset("915 ISM", 915.0e6, "US ISM"),
    BandPreset("1090 ADS-B", 1090.0e6, "Aircraft transponders"),
    BandPreset("1575.42 GPS L1", 1575.42e6, "GPS / GNSS"),
    BandPreset("2400 ISM", 2400.0e6, "Wi-Fi / Bluetooth"),
    BandPreset("2450 ISM", 2450.0e6, "Microwave ovens / Wi-Fi"),
    BandPreset("3400 5G", 3400.0e6, "5G / CBRS"),
    BandPreset("3600 5G", 3600.0e6, "5G / CBRS"),
]


def format_freq(hz: float) -> str:
    hz = float(hz)
    if abs(hz) >= 1e9:
        return f"{hz / 1e9:.6f} GHz"
    if abs(hz) >= 1e6:
        return f"{hz / 1e6:.4f} MHz"
    if abs(hz) >= 1e3:
        return f"{hz / 1e3:.2f} kHz"
    return f"{hz:.0f} Hz"


def format_bw(hz: float) -> str:
    hz = abs(float(hz))
    if hz >= 1e6:
        return f"{hz / 1e6:.2f} MHz"
    if hz >= 1e3:
        return f"{hz / 1e3:.1f} kHz"
    return f"{hz:.0f} Hz"


def in_stock_pluto_range(hz: float) -> bool:
    return PLUTO_MIN_FREQ <= hz <= PLUTO_MAX_FREQ
