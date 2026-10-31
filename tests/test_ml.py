"""Tests for the offline drone ML baseline."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from pluto_scanner.ml.features import FEATURE_NAMES, feature_vector
from pluto_scanner.ml.model import (
    SoftmaxModel,
    evaluate,
    train_synthetic,
    train_softmax,
)
from pluto_scanner.ml.synthetic import CLASSES, generate_dataset


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
