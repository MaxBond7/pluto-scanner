from __future__ import annotations

import numpy as np

from pluto_scanner.dsp.classifier import SignalClassifier
from pluto_scanner.model import Detection, SignalType


def _detection(db, bw_hz, center=433.92e6):
    db = np.asarray(db, dtype=np.float64)
    base = np.full_like(db, -100.0)
    return Detection(
        freq_hz=center,
        bw_hz=float(bw_hz),
        peak_db=float(db.max()),
        snr_db=float(db.max() + 100.0),
        mean_snr_db=float(np.mean(db[db > -100.0]) + 100.0),
        bin_start=0,
        bin_end=db.size - 1,
        bin_hz=500.0,
        region_db=db,
        baseline_db=base,
        type=SignalType.UNKNOWN,
    )


def test_classifies_cw_carrier():
    det = _detection([-100.0, -40.0, -100.0], 1500.0)
    result = SignalClassifier().classify(det)
    assert result.label == SignalType.CW
    assert result.confidence > 0.5
    assert len(result.alternatives) == 3
    assert abs(sum(p for _, p in result.alternatives) - 1.0) < 1e-6


def test_classifies_am_with_sidebands():
    db = np.full(21, -100.0)
    db[10] = -55.0
    db[6] = db[14] = -71.0
    db[3] = db[17] = -83.0
    result = SignalClassifier().classify(_detection(db, 10_500.0))
    assert result.label == SignalType.AM
    assert result.alternatives[0][0] == SignalType.AM


def test_classifies_flat_wide_fm():
    db = np.full(401, -64.0)
    result = SignalClassifier().classify(_detection(db, 200_000.0))
    assert result.label == SignalType.FM
    assert result.confidence > 0.5


def test_classifies_asymmetric_ssb():
    db = np.array([-100.0, -100.0, -100.0, -100.0, -70.0,
                   -60.0, -55.0, -65.0, -100.0])
    result = SignalClassifier().classify(_detection(db, 4_500.0))
    assert result.label == SignalType.SSB
    assert result.alternatives[0][0] == SignalType.SSB


def test_apply_updates_detection():
    det = _detection([-100.0, -40.0, -100.0], 1500.0)
    SignalClassifier().apply(det)
    assert det.type == SignalType.CW
    assert det.confidence > 0.0
    assert det.alternatives
