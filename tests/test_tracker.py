from __future__ import annotations

import time

import numpy as np

from pluto_scanner.dsp.tracker import ContactTracker
from pluto_scanner.model import Detection, SignalType
from pluto_scanner.store import ContactStore


def _det(freq=433.92e6 + 100e3, bw=1500.0, snr=30.0,
         typ=SignalType.CW, confidence=0.8):
    return Detection(
        freq_hz=freq,
        bw_hz=bw,
        peak_db=-50.0,
        snr_db=snr,
        mean_snr_db=snr - 2,
        bin_start=1,
        bin_end=3,
        bin_hz=500.0,
        region_db=np.array([-100.0, -50.0, -100.0]),
        baseline_db=np.full(3, -100.0),
        type=typ,
        confidence=confidence,
        alternatives=[(typ, confidence)],
    )


def test_stable_id_and_tentative_track(tmp_path):
    store = ContactStore(tmp_path / "known.json")
    tracker = ContactTracker("dev", store, min_hits=2, max_misses=2)
    assert tracker.update([_det()], 1000.0, 500.0) == []
    contacts = tracker.update([_det(freq=433.92e6 + 100e3)], 1000.1, 500.0)
    assert len(contacts) == 1
    c = contacts[0]
    assert c.hits == 2
    assert c.contact_id.startswith("dev-")
    first_id = c.contact_id
    contacts = tracker.update([_det(freq=433.92e6 + 100.2e3)], 1000.2, 500.0)
    assert contacts[0].contact_id == first_id
    assert contacts[0].hits == 3


def test_miss_grace_and_removal(tmp_path):
    store = ContactStore(tmp_path / "known.json")
    tracker = ContactTracker("dev", store, min_hits=1, max_misses=2)
    tracker.update([_det()], 2000.0, 500.0)
    c1 = tracker.update([], 2000.1, 500.0)
    assert len(c1) == 1 and not c1[0].active
    c2 = tracker.update([], 2000.2, 500.0)
    assert len(c2) == 1 and not c2[0].active
    c3 = tracker.update([], 2000.3, 500.0)
    assert c3 == []


def test_known_contact_persists(tmp_path):
    store_path = tmp_path / "known.json"
    store = ContactStore(store_path)
    tracker = ContactTracker("dev", store, min_hits=1, max_misses=3)
    contact = tracker.update([_det()], 3000.0, 500.0)[0]
    assert not contact.known
    marked = tracker.mark_known(contact.contact_id)
    assert marked is not None and marked.known
    assert store.is_known(contact.freq_hz, contact.bw_hz)
    reloaded = ContactStore(store_path)
    assert reloaded.is_known(contact.freq_hz + 1000, contact.bw_hz)
    tracker.forget(contact.contact_id)
    assert not store.is_known(contact.freq_hz, contact.bw_hz)


def test_tracker_uses_nearest_match(tmp_path):
    tracker = ContactTracker("dev", ContactStore(tmp_path / "k.json"),
                             min_hits=1, max_misses=2)
    a = tracker.update([_det(freq=433.92e6 - 100e3)], 4000.0, 500.0)[0]
    contacts = tracker.update([_det(freq=433.92e6 + 100e3)], 4000.1, 500.0)
    b = next(c for c in contacts if c.freq_hz > 433.92e6)
    assert a.contact_id != b.contact_id
    # A small frequency drift should keep the same identity.
    a2 = tracker.update([_det(freq=433.92e6 - 100e3 + 1000)],
                        4000.2, 500.0)
    assert len(a2) == 2
    ids = {c.freq_hz: c.contact_id for c in a2}
    nearest = min(ids, key=lambda f: abs(f - (433.92e6 - 100e3 + 1000)))
    assert ids[nearest] == a.contact_id
