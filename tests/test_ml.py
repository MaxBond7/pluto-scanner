"""Tests for the offline drone ML baseline."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from pluto_scanner.ml.features import FEATURE_NAMES, feature_vector
from pluto_scanner.ml.dataset import build_real_dataset, train_from_recordings
from pluto_scanner.ml.importers import import_raw_iq, import_sigmf
from pluto_scanner.ml.model import (
    SoftmaxModel,
    evaluate,
    train_synthetic,
    train_softmax,
)
from pluto_scanner.ml.synthetic import CLASSES, generate_dataset, make_iq
from pluto_scanner.drone.features import NARROW, TELEMETRY
from pluto_scanner.recordings import (
    list_recordings,
    load_info,
    new_recording_info,
    save_info,
    set_label,
)


def _obs(**overrides):
    values = dict(
        occupied_bw_hz=250_000.0,
        snr_db=18.0,
        active_fraction=0.4,
        burst_count=5,
        burst_rate_hz=20.0,
        median_burst_ms=8.0,
        max_burst_ms=20.0,
        flatness=0.2,
        peak_to_mean_db=12.0,
        busy_fraction=0.3,
        sample_rate=2.048e6,
    )
    values.update(overrides)
    return SimpleNamespace(**values)


def test_feature_vector_is_finite_and_fixed_length():
    values = feature_vector(_obs())
    assert values.shape == (len(FEATURE_NAMES),)
    assert np.isfinite(values).all()

    empty = feature_vector(_obs(
        occupied_bw_hz=0.0, snr_db=0.0, active_fraction=0.0,
        burst_count=0, burst_rate_hz=0.0, median_burst_ms=0.0,
        max_burst_ms=0.0, flatness=0.0, peak_to_mean_db=0.0,
        busy_fraction=0.0,
    ))
    assert np.isfinite(empty).all()


def test_synthetic_dataset_has_all_classes():
    X, y, heuristic = generate_dataset(per_class=2, seed=3)
    assert X.shape[0] == len(y) == len(heuristic)
    assert X.shape[1] == len(FEATURE_NAMES)
    assert set(y) == set(CLASSES)
    assert np.isfinite(X).all()


def test_softmax_learns_separable_features_and_roundtrips(tmp_path):
    rng = np.random.default_rng(4)
    X = np.vstack([
        rng.normal(loc=(-2, -2), scale=0.2, size=(20, 2)),
        rng.normal(loc=(0, 2), scale=0.2, size=(20, 2)),
        rng.normal(loc=(2, -1), scale=0.2, size=(20, 2)),
    ])
    y = ["A"] * 20 + ["B"] * 20 + ["C"] * 20
    model = train_softmax(X, y, epochs=400, seed=2)
    assert model.predict(X).count("A") == 20
    metrics = evaluate(model, X, y)
    assert metrics["accuracy"] > 0.95

    path = model.save(tmp_path / "model.json")
    loaded = SoftmaxModel.load(path)
    assert loaded is not None
    assert loaded.classes == ["A", "B", "C"]
    assert np.allclose(
        loaded.predict_proba(X[:5]), model.predict_proba(X[:5])
    )


def test_synthetic_training_smoke(tmp_path):
    model, metrics = train_synthetic(per_class=4, epochs=80, seed=5)
    assert model.classes == CLASSES
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["n"] > 0
    assert "per_class" in metrics

    path = model.save(tmp_path / "ml_model.json")
    loaded = SoftmaxModel.load(path)
    assert loaded is not None
    assert loaded.accuracy == metrics["accuracy"]


def test_missing_or_bad_model_returns_none(tmp_path):
    assert SoftmaxModel.load(tmp_path / "missing.json") is None
    bad = tmp_path / "bad.json"
    bad.write_text("{not json", encoding="utf-8")
    assert SoftmaxModel.load(bad) is None


def test_recording_label_roundtrip(tmp_path):
    info = new_recording_info(
        tmp_path, device_id="test", device_name="test", device_kind="sim",
        sample_rate=2.048e6, center_freq=2450e6,
    )
    info.path.write_bytes(b"\x00" * 8)
    save_info(info)
    loaded = load_info(info.meta_path)
    assert loaded is not None
    set_label(loaded, NARROW)
    loaded_again = load_info(info.meta_path)
    assert loaded_again is not None
    assert loaded_again.label == NARROW


def test_real_dataset_and_training(tmp_path):
    rng = np.random.default_rng(7)
    for label in (NARROW, TELEMETRY):
        for index in range(2):
            iq = make_iq(
                label, fs=2.048e6, duration=0.45, rng=rng
            )
            info = new_recording_info(
                tmp_path,
                device_id=f"test-{label}-{index}",
                device_name=f"test-{label}-{index}",
                device_kind="sim",
                sample_rate=2.048e6,
                center_freq=2450e6,
            )
            iq.tofile(info.cf32_path)
            info.samples = int(iq.size)
            info.complete = True
            info.label = label
            save_info(info)

    assert len(list_recordings(tmp_path)) == 4
    data = build_real_dataset(tmp_path, block_s=0.2, max_blocks=2)
    assert data.blocks > 0
    assert set(data.y) == {NARROW, TELEMETRY}

    model, metrics = train_from_recordings(
        tmp_path / "model.json", tmp_path,
        include_synthetic=False, epochs=120, block_s=0.2, max_blocks=2,
    )
    assert set(model.classes) == {NARROW, TELEMETRY}
    assert 0.0 <= metrics["accuracy"] <= 1.0
    assert metrics["real_recordings"] == 4
    assert metrics["source"] == "real"
    assert (tmp_path / "model.json").exists()


def test_import_sigmf(tmp_path):
    fs = 1.024e6
    iq = (np.ones(4096, dtype=np.complex64)
          * (0.1 + 0.05j)).astype(np.complex64)
    stem = tmp_path / "sample"
    stem.with_suffix(".sigmf-data").write_bytes(iq.tobytes())
    meta = {
        "global": {
            "core:datatype": "cf32_le",
            "core:sample_rate": fs,
            "core:version": "1.0.0",
        },
        "captures": [{"core:sample_start": 0,
                      "core:frequency": 2450e6}],
        "annotations": [{"core:sample_start": 0,
                         "core:sample_count": iq.size,
                         "core:label": "WIFI"}],
    }
    stem.with_suffix(".sigmf-meta").write_text(
        __import__("json").dumps(meta), encoding="utf-8"
    )
    out = tmp_path / "out"
    result = import_sigmf(stem.with_suffix(".sigmf-meta"), out)
    assert result.info.label == "WIFI"
    assert result.info.sample_rate == fs
    assert result.info.samples == iq.size
    assert result.info.path.exists()


def test_import_raw_float32_iq(tmp_path):
    iq = (np.ones(2048, dtype=np.complex64)
          * (0.2 - 0.1j)).astype(np.complex64)
    src = tmp_path / "sample.dat"
    src.write_bytes(iq.view(np.float32).tobytes())
    out = tmp_path / "out"
    result = import_raw_iq(
        src, out, sample_rate=2.048e6, center_freq=2437.5e6,
        label="NARROW", max_seconds=1.0,
    )
    assert result.info.label == "NARROW"
    assert result.info.samples == iq.size
    assert result.info.center_freq == 2437.5e6
