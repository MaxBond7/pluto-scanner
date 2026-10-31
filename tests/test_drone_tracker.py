"""Tests for drone event tracking and JSON logging."""
from __future__ import annotations

import json

import numpy as np

from pluto_scanner.drone.features import DroneObservation, FHSS, TELEMETRY
from pluto_scanner.drone.recorder import DroneRecorder
from pluto_scanner.drone.report import export_event_bundle
from pluto_scanner.drone.tracker import DroneTracker


def _obs(freq: float, cls: str = FHSS, ts: float = 100.0,
         snr: float = 12.0, duty: float = 0.3,
         bw: float = 200e3, device: str = "pluto-1") -> DroneObservation:
    return DroneObservation(
        timestamp=ts,
        device_id=device,
        band_key="2.4",
        band_name="2.4 ГГц",
        center_hz=2440e6,
        sample_rate=20.48e6,
        noise_floor_db=-100.0,
        peak_db=-100.0 + snr,
        peak_freq_hz=freq,
        snr_db=snr,
        occupied_bw_hz=bw,
        busy_fraction=0.2,
        active_fraction=duty,
        burst_count=4,
        median_burst_ms=1.0,
        max_burst_ms=2.0,
        burst_rate_hz=200.0,
        flatness=0.2,
        peak_to_mean_db=10.0,
        class_key=cls,
        class_ru="тест",
        confidence=0.7,
        drone_like=cls == FHSS,
        spectrum_freqs_hz=[2400e6, 2480e6],
        spectrum_db=[-100.0, -90.0],
        envelope_db=[-100.0, -85.0, -95.0],
        envelope_ms=[0.0, 0.5, 1.0],
    )


def test_fhss_hops_merge_into_one_event():
    tracker = DroneTracker(timeout_s=5.0)
    event, new = tracker.update(_obs(2410e6, ts=100.0))
    assert new is True
    assert event is not None
    assert event.count == 1
    event2, new2 = tracker.update(_obs(2470e6, ts=101.0))
    assert new2 is False
    assert event2 is event
    assert event2.count == 2
    assert event2.freq_min_hz == 2410e6
    assert event2.freq_max_hz == 2470e6
    assert event2.device_ids == ["pluto-1"]


def test_narrowband_events_are_separated_by_frequency():
    tracker = DroneTracker(merge_hz=1e6)
    tracker.update(_obs(2410e6, cls=TELEMETRY))
    tracker.update(_obs(2470e6, cls=TELEMETRY))
    assert len(tracker.events()) == 2


def test_expire_marks_event_inactive():
    tracker = DroneTracker(timeout_s=5.0)
    event, _ = tracker.update(_obs(2410e6, ts=100.0))
    changed = tracker.expire(now=110.0)
    assert event in changed
    assert event.active is False
    assert tracker.summary()["events_active"] == 0


def test_recorder_writes_summary_and_config(tmp_path):
    recorder = DroneRecorder(
        tmp_path / "drone_x",
        drone_id="x",
        sample_rate=20.48e6,
        dwell_ms=40,
        threshold_db=6,
        bands=["2.4", "5.8"],
        devices=[{"device_id": "pluto-1", "name": "Pluto 1",
                  "kind": "pluto", "uri": "usb:1.6.5"}],
    )
    tracker = DroneTracker()
    event, _ = tracker.update(_obs(2410e6))
    recorder.log_event(event, kind="new")
    path = recorder.finalize(tracker.summary(), tracker.events())
    assert path.name == "summary.json"
    summary = json.loads(path.read_text(encoding="utf-8"))
    assert summary["drone_id"] == "x"
    assert summary["sample_rate"] == 20.48e6
    assert summary["summary"]["events_total"] == 1
    assert summary["events"][0]["class_key"] == FHSS
    config = json.loads((tmp_path / "drone_x" / "config.json").read_text(
        encoding="utf-8"
    ))
    assert config["bands"] == ["2.4", "5.8"]


def test_recorder_saves_iq_clip_and_exports_bundle(tmp_path):
    recorder = DroneRecorder(
        tmp_path / "drone_y",
        drone_id="y",
        sample_rate=10.24e6,
        dwell_ms=40,
        threshold_db=8,
        bands=["2.4"],
        devices=[],
    )
    tracker = DroneTracker()
    event, _ = tracker.update(_obs(2410e6))
    assert event is not None
    samples = np.zeros(4096, dtype=np.complex64)
    clip = recorder.save_clip(
        event, samples,
        sample_rate=10.24e6, center_hz=2410e6, device_id="pluto-1",
    )
    assert clip.exists()
    assert clip.suffix == ".cf32"
    assert clip.stat().st_size == samples.size * 8
    meta = json.loads(clip.with_suffix(".json").read_text(encoding="utf-8"))
    assert meta["format"] == "cf32"
    assert meta["samples"] == 4096

    event.clip_path = str(clip)
    event.clip_samples = 4096
    event.clip_sample_rate = 10.24e6
    event.clip_center_hz = 2410e6
    bundle = export_event_bundle(event, tmp_path / "export")
    assert (bundle / "event.json").exists()
    assert (bundle / "spectrum.csv").exists()
    assert (bundle / "envelope.csv").exists()
    assert (bundle / "clip.cf32").exists()
    readme = (bundle / "README.md").read_text(encoding="utf-8")
    assert "Pluto Scanner" in readme
    data = json.loads((bundle / "event.json").read_text(encoding="utf-8"))
    assert data["clip_samples"] == 4096
    assert data["envelope_db"] == [-100.0, -85.0, -95.0]

def test_wideband_flag_is_kept_on_the_event():
    tracker = DroneTracker(timeout_s=5.0)
    obs = _obs(2410e6, ts=100.0)
    obs.extra["wideband"] = True
    event, is_new = tracker.update(obs)
    assert is_new
    assert event.wideband is True
    payload = event.to_dict(include_spectrum=False)
    assert payload["wideband"] is True
