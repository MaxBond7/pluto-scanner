"""Tests for background comparison."""
from __future__ import annotations

import numpy as np

from pluto_scanner.scanner.compare import (
    background_compatible,
    compare_bundles,
    compare_spectrum,
    dedupe_peaks,
)


def _device(kind: str = "pluto", gain: float = 40.0):
    return {
        "name": kind,
        "kind": kind,
        "uri": "usb:1.6.5",
        "gain_db": gain,
        "bandwidth_hz": 1.024e6,
    }


def _peak(freq: float, level: float = -70.0, bw: float = 5e3):
    return {
        "freq_hz": freq,
        "peak_db": level,
        "bw_hz": bw,
        "snr_db": abs(level) - 100,
        "type": "FM",
        "type_ru": "FM",
        "confidence": 0.8,
    }


def _bundle(peaks, start=433e6, end=436e6, bins=512, values=None, sid="x"):
    spectrum = {
        "bins": bins,
        "freq_start_hz": start,
        "freq_end_hz": end,
        "max_hold_db": (
            list(values) if values is not None else [-100.0] * bins
        ),
    }
    return {
        "scan_version": 2,
        "scan_id": sid,
        "created": 1.0,
        "range_start_hz": start,
        "range_end_hz": end,
        "steps_completed": 1,
        "complete": True,
        "peaks": peaks,
        "spectrum": spectrum,
    }


def test_new_and_stronger_contact_against_background():
    background = _bundle(
        [_peak(433.92e6, -70.0), _peak(434.50e6, -80.0)], sid="old"
    )
    current = _bundle(
        [
            _peak(433.92e6, -61.0),   # +9 dB -> stronger
            _peak(434.10e6, -75.0),   # not present -> new
            _peak(434.50e6, -80.0),   # unchanged
        ],
        sid="new",
    )
    report = compare_bundles(background, current, margin_db=6.0)
    counts = report["counts"]
    assert counts["new"] == 1
    assert counts["stronger"] == 1
    assert counts["matched"] == 2
    assert report["new_contacts"][0]["freq_hz"] == 434.10e6
    assert report["new_contacts"][0]["reason"] == "new"
    assert report["stronger_contacts"][0]["freq_hz"] == 433.92e6
    assert report["stronger_contacts"][0]["delta_db"] >= 6.0


def test_background_peak_within_tolerance_is_matched():
    background = _bundle([_peak(433.92e6, -70.0)])
    current = _bundle([_peak(433.94e6, -69.0)])
    report = compare_bundles(background, current, tolerance_hz=50e3)
    assert report["counts"]["new"] == 0
    assert report["counts"]["matched"] == 1


def test_dedupe_merges_overlapping_steps_and_keeps_strongest():
    peaks = [
        _peak(433.920e6, -75.0),
        _peak(433.925e6, -70.0),
        _peak(434.500e6, -80.0),
    ]
    merged = dedupe_peaks(peaks, tolerance_hz=20e3)
    assert len(merged) == 2
    assert merged[0]["peak_db"] == -70.0
    assert merged[0]["seen_steps"] == 2


def test_spectrum_rise_finds_new_wideband_patch():
    bins = 512
    background_values = np.full(bins, -100.0)
    current_values = background_values.copy()
    current_values[200:240] = -85.0
    background = _bundle([], values=background_values)
    current = _bundle([], values=current_values)
    rises = compare_spectrum(background, current, margin_db=6.0)
    assert rises
    assert -86.0 < rises[0]["level_db"] < -84.0
    assert rises[0]["delta_db"] > 10.0


def test_non_overlapping_ranges_have_no_rises():
    background = _bundle([], start=100e6, end=200e6)
    current = _bundle([], start=433e6, end=436e6)
    assert compare_spectrum(background, current) == []


def test_different_device_kind_disables_auto_comparison():
    background = _bundle([_peak(433.92e6)])
    current = _bundle([_peak(433.92e6)])
    background["device"] = _device("sim", 40.0)
    current["device"] = _device("pluto", 40.0)
    ok, warnings = background_compatible(background, current)
    assert ok is False
    assert warnings


def test_gain_change_disables_auto_comparison():
    background = _bundle([_peak(433.92e6)])
    current = _bundle([_peak(433.92e6)])
    background["device"] = _device("pluto", 40.0)
    current["device"] = _device("pluto", 55.0)
    ok, warnings = background_compatible(background, current)
    assert ok is False
    assert any("Усиление" in warning for warning in warnings)


def test_same_device_is_compatible():
    background = _bundle([_peak(433.92e6)])
    current = _bundle([_peak(433.92e6)])
    background["device"] = _device("pluto", 40.0)
    current["device"] = _device("pluto", 41.0)
    ok, warnings = background_compatible(background, current)
    assert ok is True
    assert warnings == []


def test_empty_stopped_background_is_not_auto_compared():
    background = _bundle([])
    current = _bundle([])
    background["device"] = _device("pluto", 40.0)
    current["device"] = _device("pluto", 40.0)
    background["steps_completed"] = 0
    background["complete"] = False
    ok, warnings = background_compatible(background, current)
    assert ok is False
    assert any("нет завершённых шагов" in warning for warning in warnings)


def test_partial_background_is_compared_with_warning():
    background = _bundle([_peak(433.92e6)])
    current = _bundle([_peak(433.92e6)])
    background["device"] = _device("pluto", 40.0)
    current["device"] = _device("pluto", 40.0)
    background["steps_completed"] = 2
    background["complete"] = False
    ok, warnings = background_compatible(background, current)
    assert ok is True
    assert any("неполный" in warning for warning in warnings)


def test_peaks_outside_background_range_are_not_new():
    background = _bundle([_peak(433.92e6)], start=433e6, end=436e6)
    current = _bundle(
        [_peak(433.92e6), _peak(437.0e6)],
        start=430e6,
        end=440e6,
    )
    report = compare_bundles(background, current)
    assert report["counts"]["new"] == 0
    assert report["counts"]["outside_background"] == 1
    assert "Вне сохранённого фона" in report["summary_ru"]
    assert any("покрывает" in warning for warning in report["warnings"])


def test_legacy_background_is_not_compatible():
    background = _bundle([_peak(433.92e6)])
    current = _bundle([_peak(433.92e6)])
    background["scan_version"] = 1
    background["device"] = _device("pluto", 40.0)
    current["device"] = _device("pluto", 40.0)
    ok, warnings = background_compatible(background, current)
    assert ok is False
    assert any("старой версией" in warning for warning in warnings)
