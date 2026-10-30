"""Tests for drone white-list and background-profile persistence."""
from __future__ import annotations

import time

from pluto_scanner.drone.background import DroneBackgroundStore
from pluto_scanner.drone.tracker import DroneEvent
from pluto_scanner.drone.whitelist import DroneWhitelist


def _event(freq=2469.4e6, band="2.4", cls="FHSS", bw=2.8e6,
           fmin=2468e6, fmax=2472e6) -> DroneEvent:
    now = time.time()
    return DroneEvent(
        event_id="drone-test",
        band_key=band,
        band_name=band,
        class_key=cls,
        class_ru="тест",
        freq_hz=freq,
        freq_min_hz=fmin,
        freq_max_hz=fmax,
        bw_hz=bw,
        first_seen=now,
        last_seen=now,
        count=3,
        max_snr_db=20,
        max_duty=0.5,
        confidence=0.8,
        drone_like=True,
        device_ids=["pluto-1"],
    )


def test_whitelist_add_match_and_persist(tmp_path):
    store = DroneWhitelist(tmp_path / "whitelist.json")
    event = _event()
    entry = store.add_event(event, name="Мой пульт")
    assert store.count == 1
    assert entry.name == "Мой пульт"
    assert store.match(event) is not None

    reloaded = DroneWhitelist(tmp_path / "whitelist.json")
    assert reloaded.count == 1
    assert reloaded.match(event).name == "Мой пульт"


def test_whitelist_rejects_other_band_or_far_frequency(tmp_path):
    store = DroneWhitelist(tmp_path / "whitelist.json")
    store.add_event(_event())
    assert store.match(_event(band="5.8", freq=5800e6,
                              fmin=5790e6, fmax=5810e6)) is None
    assert store.match(_event(freq=2600e6,
                              fmin=2590e6, fmax=2610e6)) is None
    assert store.match(_event(cls="WIFI")) is None


def test_whitelist_remove_and_clear(tmp_path):
    store = DroneWhitelist(tmp_path / "whitelist.json")
    entry = store.add_event(_event())
    assert store.remove(entry.id)
    assert store.count == 0
    store.add_event(_event())
    store.clear()
    assert store.count == 0


def test_background_profile_is_saved_and_loaded(tmp_path):
    path = tmp_path / "background.json"
    store = DroneBackgroundStore(path)
    store.update(
        device_id="pluto-1", band_key="2.4", gain_db=40,
        sample_rate=20.48e6, noise_floor_db=-100.0,
    )
    assert store.get(
        device_id="pluto-1", band_key="2.4", gain_db=40,
        sample_rate=20.48e6,
    ) == -100.0
    reloaded = DroneBackgroundStore(path)
    assert reloaded.get(
        device_id="pluto-1", band_key="2.4", gain_db=40,
        sample_rate=20.48e6,
    ) == -100.0


def test_background_profile_is_keyed_by_gain(tmp_path):
    store = DroneBackgroundStore(tmp_path / "background.json")
    store.update(
        device_id="pluto-1", band_key="2.4", gain_db=40,
        sample_rate=20.48e6, noise_floor_db=-100.0,
    )
    assert store.get(
        device_id="pluto-1", band_key="2.4", gain_db=55,
        sample_rate=20.48e6,
    ) is None
