"""Tests for writing/loading scan JSON bundles."""
from __future__ import annotations

import json

import numpy as np

from pluto_scanner.scanner.recorder import (
    ScanRecorder,
    find_latest_background,
    load_bundle,
)


def _step(recorder: ScanRecorder, index: int, center: float,
          tone_hz: float | None = None):
    fs = 1.024e6
    freqs = np.linspace(center - fs / 2, center + fs / 2, 512)
    psd = np.full(512, -100.0)
    if tone_hz is not None:
        psd[np.abs(freqs - tone_hz) < 2e3] = -70.0
    return recorder.add_step(
        index=index,
        center_hz=center,
        freqs=freqs,
        psd=psd,
        noise_floor_db=-100.0,
        peaks=[],
        status="ok",
        dwell_frames=2,
    )


def test_recorder_writes_steps_and_bundle(tmp_path):
    recorder = ScanRecorder(
        tmp_path / "scan_x",
        scan_id="x",
        range_start_hz=433e6,
        range_end_hz=435e6,
        step_hz=1e6,
        sample_rate=1.024e6,
        fft_size=2048,
        threshold_db=8.0,
        dwell_frames=2,
    )
    first = _step(recorder, 0, 433.5e6, 433.6e6)
    _step(recorder, 1, 434.5e6)
    assert (tmp_path / "scan_x" / "step_00000.json").exists()
    assert first["spectrum"]["bins"] == 512
    assert len(first["spectrum"]["psd_db"]) == 512

    bundle, path = recorder.finalize()
    assert path.name == "background.json"
    loaded = load_bundle(path)
    assert loaded["scan_version"] == 2
    assert loaded["steps_total"] == 2
    assert loaded["steps_completed"] == 2
    assert loaded["range_start_hz"] == 433e6
    assert loaded["spectrum"]["bins"] == 8192
    assert len(loaded["spectrum"]["max_hold_db"]) == 8192
    assert all(np.isfinite(loaded["spectrum"]["max_hold_db"]))
    assert loaded["complete"] is True
    assert json.loads(path.read_text(encoding="utf-8"))["scan_id"] == "x"


def test_missed_step_is_recorded_without_fake_spectrum(tmp_path):
    recorder = ScanRecorder(
        tmp_path / "scan_y",
        scan_id="y",
        range_start_hz=433e6,
        range_end_hz=434e6,
        step_hz=1e6,
        sample_rate=1.024e6,
        fft_size=2048,
        threshold_db=8.0,
        dwell_frames=2,
    )
    missed = recorder.add_missed(index=0, center_hz=433.5e6)
    assert missed["status"] == "missed"
    bundle, _ = recorder.finalize(stopped=True)
    assert bundle["steps_missed"] == 1
    assert bundle["complete"] is False
    assert bundle["stopped"] is True


def test_find_latest_background_returns_newest(tmp_path):
    for name in ("scan_a", "scan_b"):
        folder = tmp_path / name
        folder.mkdir()
        (folder / "background.json").write_text("{}", encoding="utf-8")
    import os
    import time

    old = tmp_path / "scan_a" / "background.json"
    new = tmp_path / "scan_b" / "background.json"
    os.utime(old, (time.time() - 100, time.time() - 100))
    os.utime(new, (time.time(), time.time()))
    assert find_latest_background(tmp_path) == new
