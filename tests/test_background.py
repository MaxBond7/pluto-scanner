# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the learned background map (persistent signals vs new ones)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from pluto_scanner.drone.background import (
    BACKGROUND_BINS,
    BackgroundMap,
    active_bins,
)


def _observation(
    spec: np.ndarray, *, device: str = "dev", band: str = "2.4",
    center: float = 2437e6,
):
    return SimpleNamespace(
        device_id=device,
        band_key=band,
        sample_rate=20.48e6,
        center_hz=center,
        spectrum_db=spec.tolist(),
        extra={"gain_db": 40.0},
    )


def _spectrum(points: dict[tuple[float, float], float], size: int = 256):
    """Flat floor with raised spans given as (start, stop) fractions."""
    spec = np.full(size, -80.0)
    for (start, stop), lift in points.items():
        spec[int(start * size):int(stop * size)] = -80.0 + lift
    return spec


def test_active_bins_marks_the_raised_part():
    spec = _spectrum({(0.30, 0.45): 20.0})
    mask = active_bins(spec)
    assert mask is not None and len(mask) == BACKGROUND_BINS
    assert any(mask)
    assert not all(mask)


def test_active_bins_rejects_short_input():
    assert active_bins([-80.0] * 8) is None


def test_persistent_signal_becomes_background(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(120):
        model.learn(wifi)
    fraction = model.observe(wifi)
    assert fraction > 0.9
    assert model.is_background(fraction)


def test_new_signal_stays_new(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(120):
        model.learn(wifi)
    # A narrow burst in a quiet part of the band must not be called background.
    fresh = _observation(_spectrum({(0.70, 0.75): 18.0}))
    fraction = model.observe(fresh)
    assert fraction < 0.2
    assert not model.is_background(fraction)


def test_map_freezes_after_learning(tmp_path):
    model = BackgroundMap(tmp_path / "map.json", learn_frames=60)
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(80):
        model.learn(wifi)
    post = _observation(_spectrum({(0.70, 0.75): 18.0}))
    for _ in range(20):
        model.learn(post)
    profile = next(iter(model.profiles.values()))
    assert profile.frames == 60
    assert max(profile.occupancy) > 0.9


def test_map_is_not_trusted_before_min_frames(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(10):
        model.learn(wifi)
    assert model.observe(wifi) == 0.0


def test_map_roundtrip(tmp_path):
    path = tmp_path / "map.json"
    model = BackgroundMap(path)
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(60):
        model.learn(wifi)
    model.save()
    again = BackgroundMap(path)
    assert len(again.profiles) == 1
    first = next(iter(model.profiles.values()))
    second = next(iter(again.profiles.values()))
    assert second.frames == first.frames
    assert len(second.occupancy) == BACKGROUND_BINS


def test_map_is_per_band(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}), band="2.4")
    for _ in range(60):
        model.learn(wifi)
    other_band = _observation(_spectrum({(0.30, 0.45): 20.0}), band="5.8")
    assert model.observe(other_band) == 0.0
    assert len(model.profiles) == 1

def test_tracker_keeps_the_strongest_background_share():
    from pluto_scanner.drone.tracker import DroneTracker

    def obs(background: float):
        return SimpleNamespace(
            class_key="NARROW", band_key="2.4", band_name="2.4 ГГц",
            class_ru="узкий", peak_freq_hz=2437e6, timestamp=1.0,
            snr_db=12.0, spectrum_freqs_hz=[], spectrum_db=[],
            envelope_db=[], envelope_ms=[], active_fraction=0.5,
            max_burst_ms=2.0, occupied_bw_hz=200e3, confidence=0.8,
            drone_like=True, device_id="dev",
            extra={"background": background},
        )

    tracker = DroneTracker()
    event, _ = tracker.update(obs(0.2))
    assert event is not None
    tracker.update(obs(0.9))
    tracker.update(obs(0.4))
    assert event.background == 0.9

def test_monitor_query_never_teaches_the_map(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(200):
        assert model.observe(wifi) == 0.0
    assert not model.profiles

def test_narrow_carrier_still_marks_its_bin():
    spec = np.full(256, -80.0)
    spec[100] = -60.0
    mask = active_bins(spec)
    assert mask is not None
    assert any(mask)
    assert sum(mask) <= 2

def test_reset_key_forgets_one_band(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(40):
        model.learn(wifi)
    assert model.reset_key(
        device_id="dev", band_key="2.4", gain_db=40.0, sample_rate=20.48e6,
        center_hz=2437e6,
    )
    assert not model.profiles
    assert model.observe(wifi) == 0.0

def test_map_is_independent_of_the_sample_rate(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(60):
        model.learn(wifi)
    other_rate = _observation(_spectrum({(0.30, 0.45): 20.0}))
    other_rate.sample_rate = 6.144e6
    assert model.observe(other_rate) > 0.9


def test_band_report_counts_busy_bins(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(60):
        model.learn(wifi)
    report = model.band_report()
    assert report["2.4"]["active"] >= 1
    assert report["2.4"]["frames"] == 60

def test_chunks_of_one_band_do_not_mix(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    first = _observation(_spectrum({(0.30, 0.45): 20.0}), center=2410e6)
    second = _observation(_spectrum({(0.30, 0.45): 20.0}), center=2450e6)
    for _ in range(40):
        model.learn(first)
        model.learn(second)
    assert model.observe(first) > 0.9
    assert model.observe(second) > 0.9
    # A chunk that was never learned has no profile at all.
    middle = _observation(_spectrum({(0.30, 0.45): 20.0}), center=2430e6)
    assert model.observe(middle) == 0.0


def test_sparse_beacon_still_counts_as_known(tmp_path):
    """A beaconing AP is active in ~15% of blocks but is always there."""
    model = BackgroundMap(tmp_path / "map.json")
    busy = _spectrum({(0.30, 0.45): 20.0})
    quiet = _spectrum({})
    for index in range(60):
        model.learn(_observation(busy if index % 7 == 0 else quiet))
    fraction = model.observe(_observation(busy))
    assert fraction > 0.9
