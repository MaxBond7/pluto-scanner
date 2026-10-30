"""Tests for the local known-signal signature library."""
from __future__ import annotations

from types import SimpleNamespace

from pluto_scanner.signatures import (
    SignatureStore,
    SignalSignature,
    match_event,
)


def _event(freq, bw, duty, cls):
    return SimpleNamespace(
        freq_hz=freq, bw_hz=bw, max_duty=duty, class_key=cls
    )


def test_store_is_seeded_and_searchable(tmp_path):
    store = SignatureStore(tmp_path / "signatures.db")
    assert store.count() >= 15
    assert store.search("Wi-Fi")
    assert store.get("builtin-wifi-24") is not None
    assert store.get("builtin-drone-24").source_class == "drone_control"


def test_store_export_import_roundtrip(tmp_path):
    store = SignatureStore(tmp_path / "a.db")
    custom = SignalSignature(
        id="user-test", name="Тестовый маяк", category="Тест",
        source_class="telemetry", start_hz=433e6, end_hz=434e6,
        bw_hz=50e3, modulation="FSK", duty=0.1, burst_ms=5,
        references=["https://example.invalid"], license="test",
        confidence=0.6,
    )
    store.upsert(custom)
    exported = store.export_file(tmp_path / "export.json")
    assert exported.exists()
    other = SignatureStore(tmp_path / "b.db")
    imported = other.import_file(exported)
    assert imported >= 1
    assert other.get("user-test") is not None


def test_fhss_matches_rc_or_bluetooth(tmp_path):
    store = SignatureStore(tmp_path / "signatures.db")
    matches = match_event(
        _event(2469e6, 2.8e6, 0.5, "FHSS"),
        store.all(),
    )
    assert matches
    assert matches[0].signature.source_class in {
        "rc", "bluetooth", "drone_control", "zigbee"
    }
    assert matches[0].score > 0.5
    assert "диапазон" in matches[0].reasons


def test_wifi_matches_wifi_catalog(tmp_path):
    store = SignatureStore(tmp_path / "signatures.db")
    matches = match_event(
        _event(2441e6, 20e6, 0.7, "WIFI"),
        store.all(),
    )
    assert matches
    assert matches[0].signature.source_class == "wifi"


def test_analog_video_matches_fpv_catalog(tmp_path):
    store = SignatureStore(tmp_path / "signatures.db")
    matches = match_event(
        _event(5800e6, 8e6, 1.0, "VIDEO_ANALOG"),
        store.all(),
    )
    assert matches
    assert matches[0].signature.source_class in {"drone_video", "analog_video"}


def test_frequency_mismatch_is_penalized(tmp_path):
    store = SignatureStore(tmp_path / "signatures.db")
    matches = match_event(
        _event(433.92e6, 250e3, 0.1, "TELEMETRY"),
        store.all(),
    )
    assert matches
    assert all(abs(m.signature.start_hz - 433.92e6) < 20e6
               or m.signature.start_hz < 600e6 for m in matches)
