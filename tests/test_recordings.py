"""Tests for long IQ recording, metadata and chunked playback reads."""
from __future__ import annotations

import json
import time

import numpy as np

from pluto_scanner.model import IQBlock
from pluto_scanner.recordings import (
    IqRecorder,
    delete_recording,
    estimated_bytes,
    iter_iq_chunks,
    list_recordings,
    load_info,
    new_recording_info,
)


def _info(tmp_path, fs=1.0e6):
    return new_recording_info(
        tmp_path,
        device_id="sim-1",
        device_name="Симулятор 1",
        device_kind="sim",
        sample_rate=fs,
        center_freq=433.92e6,
        gain_db=40.0,
        bandwidth_hz=fs,
    )


def test_recorder_writes_cf32_and_complete_metadata(tmp_path):
    info = _info(tmp_path)
    recorder = IqRecorder(tmp_path)
    recorder.start(info, expected_seconds=3.0)
    block = np.arange(4096, dtype=np.complex64) * (1.0 + 0.5j)
    start = time.time()
    for _ in range(4):
        recorder.write(IQBlock(
            device_id="sim-1",
            samples=block,
            sample_rate=1.0e6,
            center_freq=433.92e6,
            timestamp=start,
        ))
    written = recorder.stop()

    assert written is not None
    assert written.complete
    assert written.samples == 4 * 4096
    assert abs(written.duration_s - 0.016384) < 1e-6
    assert written.path.stat().st_size == written.samples * 8
    data = np.fromfile(written.path, dtype=np.complex64)
    assert data.size == written.samples
    assert np.allclose(data[:64], block[:64])


def test_recorder_ignores_other_devices(tmp_path):
    info = _info(tmp_path)
    recorder = IqRecorder(tmp_path)
    recorder.start(info)
    recorder.write(IQBlock(
        device_id="pluto-9",
        samples=np.ones(1024, dtype=np.complex64),
        sample_rate=1.0e6,
        center_freq=433.92e6,
        timestamp=time.time(),
    ))
    written = recorder.stop()
    assert written is not None
    assert written.samples == 0
    assert not written.complete


def test_list_and_load_sidecar_from_cf32_path(tmp_path):
    info = _info(tmp_path)
    recorder = IqRecorder(tmp_path)
    recorder.start(info)
    recorder.write(IQBlock(
        device_id="sim-1",
        samples=np.ones(2048, dtype=np.complex64),
        sample_rate=1.0e6,
        center_freq=433.92e6,
        timestamp=time.time(),
    ))
    written = recorder.stop()

    loaded = load_info(written.path)
    assert loaded is not None
    assert loaded.recording_id == info.recording_id
    assert loaded.center_freq == 433.92e6
    assert loaded.samples == 2048

    items = list_recordings(tmp_path)
    assert len(items) == 1
    assert items[0].recording_id == info.recording_id


def test_chunked_reader_does_not_load_everything(tmp_path):
    info = _info(tmp_path)
    recorder = IqRecorder(tmp_path)
    recorder.start(info)
    block = np.arange(10000, dtype=np.complex64)
    recorder.write(IQBlock(
        device_id="sim-1",
        samples=block,
        sample_rate=1.0e6,
        center_freq=433.92e6,
        timestamp=time.time(),
    ))
    written = recorder.stop()
    assert written is not None

    chunks = list(iter_iq_chunks(written.path, chunk_samples=3000))
    assert [len(chunk) for chunk in chunks] == [3000, 3000, 3000, 1000]
    joined = np.concatenate(chunks)
    assert np.array_equal(joined, block)


def test_load_recovers_duration_from_file_after_crash(tmp_path):
    info = _info(tmp_path)
    np.ones(5000, dtype=np.complex64).tofile(info.cf32_path)
    data = info.to_dict()
    data["samples"] = 0
    data["complete"] = False
    info.meta.write_text(json.dumps(data), encoding="utf-8")

    loaded = load_info(info.meta_path)
    assert loaded is not None
    assert loaded.samples == 5000
    assert not loaded.complete
    assert abs(loaded.duration_s - 0.005) < 1e-9


def test_delete_removes_both_files(tmp_path):
    info = _info(tmp_path)
    recorder = IqRecorder(tmp_path)
    recorder.start(info)
    written = recorder.stop()
    assert written is not None
    assert written.path.exists()
    assert written.meta.exists()

    delete_recording(written)
    assert not written.path.exists()
    assert not written.meta.exists()
    assert list_recordings(tmp_path) == []


def test_estimated_size_uses_cf32():
    assert estimated_bytes(1.0e6, 2.0) == 16_000_000
    assert estimated_bytes(2.5e6, 0.0) == 0
