"""Tests for the binary drone / background detector."""
from __future__ import annotations

import numpy as np

from pluto_scanner.drone.features import DroneObservation
from pluto_scanner.ml.binary import (
    BACKGROUND,
    DRONE,
    BinaryModel,
    calibration_table,
    evaluate_binary,
    fit_binary,
    roc_auc,
    tpr_at_fpr,
    _stratified_group_split,
)
from pluto_scanner.ml.binary_features import (
    BINARY_FEATURE_NAMES,
    extract,
    from_observation,
    robust_baseline,
)
from pluto_scanner.ml.dronerf import (
    DroneRFRecording,
    read_window,
    scan_recordings,
    to_baseband,
)
from pluto_scanner.paths import DEFAULT_BINARY_MODEL


def _observation(spectrum, envelope=None, *, class_key="NARROW", snr=20.0,
                 duration=0.02):
    envelope = envelope if envelope is not None else [-60.0] * 80
    return DroneObservation(
        timestamp=0.0,
        device_id="test",
        band_key="2.4",
        band_name="2.4 ГГц",
        center_hz=2440e6,
        sample_rate=20.48e6,
        noise_floor_db=-70.0,
        peak_db=-40.0,
        peak_freq_hz=2440e6,
        snr_db=snr,
        occupied_bw_hz=2e6,
        busy_fraction=0.2,
        active_fraction=0.5,
        burst_count=2,
        median_burst_ms=5.0,
        max_burst_ms=10.0,
        burst_rate_hz=20.0,
        flatness=0.2,
        peak_to_mean_db=6.0,
        class_key=class_key,
        class_ru=class_key,
        confidence=0.5,
        drone_like=class_key == "FHSS",
        spectrum_db=list(spectrum),
        envelope_db=list(envelope),
        envelope_ms=[i * 0.25 for i in range(len(envelope))],
        extra={"duration_s": duration},
    )


def _noise_spectrum(seed=1, size=256):
    rng = np.random.default_rng(seed)
    return -100.0 + rng.normal(0.0, 1.5, size)


def _wideband_spectrum(seed=1, size=256, lift=25.0):
    base = _noise_spectrum(seed, size)
    signal = np.zeros(size)
    signal[size // 4: 3 * size // 4] = lift
    return base + signal


def test_baseline_follows_tilt_but_keeps_plateau():
    ramp = np.linspace(-20.0, 0.0, 256)
    noisy = ramp + np.random.default_rng(2).normal(0.0, 0.5, 256)
    baseline = robust_baseline(noisy)
    residual = noisy - baseline
    assert abs(float(np.median(residual))) < 2.0

    plateau = noisy.copy()
    plateau[80:180] += 30.0
    residual = plateau - robust_baseline(plateau)
    assert float(np.median(residual[80:180])) > 20.0
    assert float(np.median(residual[:60])) < 5.0


def test_extract_shape_and_separation():
    noise = extract(_noise_spectrum(3), [-60.0] * 80)
    signal = extract(_wideband_spectrum(3), [-60.0] * 80)
    assert noise.shape == (len(BINARY_FEATURE_NAMES),)
    assert np.isfinite(noise).all() and np.isfinite(signal).all()
    names = BINARY_FEATURE_NAMES
    assert signal[names.index("occ_6db")] > noise[names.index("occ_6db")] + 0.2
    assert signal[names.index("p50_db")] > noise[names.index("p50_db")] + 5.0


def test_extract_handles_empty_spectrum():
    values = extract([], [])
    assert values.shape == (len(BINARY_FEATURE_NAMES),)
    assert np.isfinite(values).all()


def test_from_observation_uses_snapshot():
    obs = _observation(_wideband_spectrum(5))
    values = from_observation(obs)
    assert values.shape == (len(BINARY_FEATURE_NAMES),)
    assert np.isfinite(values).all()


def test_model_roundtrip_and_verdicts(tmp_path):
    rng = np.random.default_rng(0)
    X = np.vstack([
        rng.normal(0.0, 1.0, (60, len(BINARY_FEATURE_NAMES))),
        rng.normal(3.0, 1.0, (60, len(BINARY_FEATURE_NAMES))),
    ])
    y = [0] * 60 + [1] * 60
    model = fit_binary(X, y, epochs=400)
    negative = float(model.predict_proba(X[0])[0])
    positive = float(model.predict_proba(X[-1])[0])
    assert positive > negative

    path = model.save(tmp_path / "binary.json")
    loaded = BinaryModel.load(path)
    assert loaded is not None
    assert loaded.predict_proba(X[:5]).shape == (5,)
    assert abs(float(loaded.predict_proba(X[-1])[0]) - positive) < 1e-9


def test_unknown_verdict_when_nothing_to_judge():
    model = BinaryModel(
        mean=np.zeros(len(BINARY_FEATURE_NAMES)),
        std=np.ones(len(BINARY_FEATURE_NAMES)),
        coef=np.zeros(len(BINARY_FEATURE_NAMES)),
        intercept=0.0,
    )
    quiet = _observation(_noise_spectrum(), class_key="QUIET", snr=1.0)
    overload = _observation(_noise_spectrum(), class_key="OVERLOAD", snr=40.0)
    assert model.predict_observation(quiet).verdict == "unknown"
    assert model.predict_observation(overload).verdict == "unknown"
    normal = model.predict_observation(_observation(_noise_spectrum()))
    assert normal.verdict in (BACKGROUND, "candidate", DRONE)


def test_roc_auc_and_thresholds():
    labels = [0, 0, 0, 0, 1, 1, 1, 1]
    scores = [0.1, 0.2, 0.3, 0.4, 0.6, 0.7, 0.8, 0.9]
    assert abs(roc_auc(labels, scores) - 1.0) < 1e-9
    assert abs(tpr_at_fpr(labels, scores, 0.25) - 1.0) < 1e-9
    metrics = evaluate_binary(labels, scores, threshold=0.5)
    assert metrics["recall"] == 1.0
    assert metrics["false_alarm_rate"] == 0.0
    table = calibration_table(labels, scores, bins=2)
    assert table and all("observed" in row for row in table)


def test_group_split_keeps_recordings_apart():
    labels = [0, 1, 0, 1, 0, 1, 0, 1]
    groups = ["a", "b", "c", "d", "e", "f", "g", "h"]
    train, test = _stratified_group_split(labels, groups, test_fraction=0.5)
    train_groups = {groups[i] for i in train}
    test_groups = {groups[i] for i in test}
    assert not (train_groups & test_groups)
    assert set(labels[i] for i in train) == {0, 1}
    assert set(labels[i] for i in test) == {0, 1}


def test_to_baseband_moves_tone_to_expected_frequency():
    fs = 40e6
    n = 200_000
    t = np.arange(n) / fs
    window = 1000.0 * np.sin(2 * np.pi * 5e6 * t)
    block = to_baseband(window)
    assert block.size == n // 2
    spectrum = np.abs(np.fft.fftshift(np.fft.fft(block)))
    freqs = np.fft.fftshift(np.fft.fftfreq(block.size, d=1.0 / 20e6))
    assert abs(freqs[int(np.argmax(spectrum))] + 5e6) < 100e3


def test_read_window_from_single_line_csv(tmp_path):
    samples = np.arange(1, 20001, dtype=float) * 0.5
    path = tmp_path / "00000L_0.csv"
    path.write_text(",".join(f"{v:.6f}" for v in samples), encoding="ascii")
    values = read_window(path, 0, 2000, total_samples=samples.size)
    assert values.size == 2000
    assert np.allclose(values, samples[:2000])

    tail = read_window(path, 15000, 2000, total_samples=samples.size)
    assert 1000 <= tail.size <= 2000
    # The byte offset is an estimate (the text length per sample varies), so
    # the window may start a little later.  It must still be a contiguous run.
    start = int(round(float(tail[0]) / 0.5)) - 1
    assert abs(start - 15000) < 300
    assert np.allclose(tail, samples[start:start + tail.size])


def test_train_on_synthetic_blocks_produces_usable_model():
    from pluto_scanner.ml.dronerf import BinaryDataset
    from pluto_scanner.ml.train_binary import train

    rng = np.random.default_rng(0)
    X = np.vstack([
        rng.normal(0.0, 1.0, (40, len(BINARY_FEATURE_NAMES))),
        rng.normal(2.5, 1.0, (40, len(BINARY_FEATURE_NAMES))),
    ])
    dataset = BinaryDataset(
        X=X,
        y=[BACKGROUND] * 40 + [DRONE] * 40,
        groups=[f"g{index // 4}" for index in range(80)],
        sources=["syn-negative"] * 40 + ["syn-positive"] * 40,
        snr=np.full(80, 20.0),
        meta=[],
    )
    report = train(dataset, seed=2, epochs=300)
    model = report.model
    assert 0.5 <= model.threshold_alarm < 1.0
    assert model.metadata["total_blocks"] == 80
    assert "by_source" in model.metadata["metrics"]
    scores = model.predict_proba(dataset.X[:4])
    assert np.all((scores >= 0.0) & (scores <= 1.0))
    assert float(model.predict_proba(X[-1])[0]) > float(model.predict_proba(X[0])[0])


def test_bundled_binary_model_loads():
    model = BinaryModel.load(DEFAULT_BINARY_MODEL)
    assert model is not None
    assert len(model.features) == len(BINARY_FEATURE_NAMES)
    assert 0.5 <= model.threshold_alarm < 1.0
    assert 0.0 < model.threshold_candidate < model.threshold_alarm
    assert model.metadata.get("metrics", {}).get("roc_auc", 0.0) > 0.6


def test_scan_recordings_parses_names(tmp_path):
    (tmp_path / "RF Data_10000_L").mkdir()
    (tmp_path / "RF Data_10000_L" / "10000L_0.csv").write_text("1,2,3")
    (tmp_path / "00000H_5.csv").write_text("1,2,3")
    (tmp_path / "notes.txt").write_text("skip me")
    found = scan_recordings(tmp_path)
    keys = sorted(recording.key for recording in found)
    assert keys == ["00000H_5", "10000L_0"]
    assert all(isinstance(item, DroneRFRecording) for item in found)
    assert found[0].family == "background"
