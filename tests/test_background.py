"""Tests for the learned background map (persistent signals vs new ones)."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from pluto_scanner.drone.background import (
    BACKGROUND_BINS,
    BackgroundMap,
    active_bins,
)


def _observation(spec: np.ndarray, *, device: str = "dev", band: str = "2.4"):
    return SimpleNamespace(
        device_id=device,
        band_key=band,
        sample_rate=20.48e6,
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
        model.observe(wifi)
    fraction = model.observe(wifi)
    assert fraction > 0.9
    assert model.is_background(fraction)


def test_new_signal_stays_new(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(120):
        model.observe(wifi)
    # A narrow burst in a quiet part of the band must not be called background.
    fresh = _observation(_spectrum({(0.70, 0.75): 18.0}))
    fraction = model.observe(fresh)
    assert fraction < 0.2
    assert not model.is_background(fraction)


def test_map_freezes_after_learning(tmp_path):
    model = BackgroundMap(tmp_path / "map.json", learn_frames=60)
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(80):
        model.observe(wifi)
    post = _observation(_spectrum({(0.70, 0.75): 18.0}))
    for _ in range(20):
        model.observe(post)
    profile = next(iter(model.profiles.values()))
    assert profile.frames == 60
    assert max(profile.occupancy) > 0.9


def test_map_is_not_trusted_before_min_frames(tmp_path):
    model = BackgroundMap(tmp_path / "map.json")
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(10):
        assert model.observe(wifi) == 0.0


def test_map_roundtrip(tmp_path):
    path = tmp_path / "map.json"
    model = BackgroundMap(path)
    wifi = _observation(_spectrum({(0.30, 0.45): 20.0}))
    for _ in range(60):
        model.observe(wifi)
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
        model.observe(wifi)
    other_band = _observation(_spectrum({(0.30, 0.45): 20.0}), band="5.8")
    assert model.observe(other_band) == 0.0
    assert len(model.profiles) == 2

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
