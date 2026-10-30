from __future__ import annotations

import time

from pluto_scanner.model import Contact, SignalType
from pluto_scanner.store import ContactStore


def _contact(freq=433.92e6 + 100e3, bw=10e3):
    now = time.time()
    return Contact(
        contact_id="dev-0001",
        device_id="dev",
        freq_hz=freq,
        bw_hz=bw,
        type=SignalType.DIGITAL,
        confidence=0.8,
        first_seen=now,
        last_seen=now,
        hits=3,
        misses=0,
        max_snr_db=25.0,
        last_snr_db=22.0,
    )


def test_mark_save_reload_and_forget(tmp_path):
    path = tmp_path / "known.json"
    store = ContactStore(path)
    contact = _contact()
    assert not store.is_known(contact.freq_hz, contact.bw_hz)
    entry = store.mark_known(contact, name="test")
    assert entry.freq_hz == contact.freq_hz
    assert store.is_known(contact.freq_hz, contact.bw_hz)
    assert store.is_known(contact.freq_hz + 1000.0, contact.bw_hz)
    assert not store.is_known(contact.freq_hz + 100_000.0, contact.bw_hz)

    reloaded = ContactStore(path)
    assert reloaded.is_known(contact.freq_hz, contact.bw_hz)
    assert reloaded.entries[0].name == "test"

    assert reloaded.forget(contact)
    assert not reloaded.is_known(contact.freq_hz, contact.bw_hz)
    assert not ContactStore(path).is_known(contact.freq_hz, contact.bw_hz)
