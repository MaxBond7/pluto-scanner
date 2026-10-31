"""Build an ML dataset from labeled IQ recordings and train on it."""
from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from ..drone.bands import DroneBand
from ..drone.features import CLASS_RU, analyze_iq
from ..recordings import RecordingInfo, list_recordings
from .features import feature_vector
from .model import SoftmaxModel, evaluate, train_softmax
from .synthetic import CLASSES, generate_dataset


@dataclass
class RealDataset:
    X: np.ndarray
    y: list[str]
    groups: list[str]
    label_counts: dict[str, int]
    recordings: int
    blocks: int
    skipped: int


def _recording_band(info: RecordingInfo) -> tuple[DroneBand, float]:
    """Full recorded band; no DC notch, because the signal may be at centre."""
    fs = max(1000.0, float(info.sample_rate))
    analysis_center = float(info.center_freq)
    band = DroneBand(
        "rec", "recording",
        analysis_center - 0.45 * fs,
        analysis_center + 0.45 * fs,
        alarm=True,
    )
    return band, analysis_center


def _blocks(info: RecordingInfo, block_s: float, max_blocks: int):
    fs = max(1000.0, float(info.sample_rate))
    block = max(256, int(fs * max(0.05, float(block_s))))
    try:
        data = np.memmap(info.path, dtype=np.complex64, mode="r")
    except Exception:
        return
    total = int(data.size)
    if total < 256:
        del data
        return
    if total <= block:
        starts = [0]
    else:
        count = min(max_blocks, max(1, total // block))
        step = max(block, (total - block) // max(1, count - 1))
        starts = [min(total - block, i * step) for i in range(count)]
    for start in starts:
        yield np.array(data[start:start + block], dtype=np.complex64, copy=True)
    del data


def build_real_dataset(
    recordings_dir: str | Path,
    *,
    block_s: float = 0.2,
    max_blocks: int = 20,
    progress: Callable[[int, int, str], None] | None = None,
) -> RealDataset:
    infos = [
        info for info in list_recordings(recordings_dir)
        if info.label in CLASSES and info.exists
    ]
    if not infos:
        raise ValueError(
            "Нет размеченных записей. Откройте «Запись IQ», выберите "
            "запись и поставьте метку класса."
        )
    rows: list[np.ndarray] = []
    labels: list[str] = []
    groups: list[str] = []
    counts: dict[str, int] = {}
    skipped = 0

    for index, info in enumerate(infos, start=1):
        band, center = _recording_band(info)
        for iq in _blocks(info, block_s, max_blocks):
            obs = analyze_iq(
                iq, info.sample_rate, center, band,
                device_id=info.recording_id,
                threshold_db=6.0, nfft=4096, notch_hz=0.0,
            )
            if obs is None or obs.snr_db < 4.0 or obs.class_key in (
                "QUIET", "OVERLOAD"
            ):
                skipped += 1
                continue
            rows.append(feature_vector(obs))
            labels.append(info.label)
            groups.append(info.recording_id)
            counts[info.label] = counts.get(info.label, 0) + 1
        if progress is not None:
            progress(index, len(infos), info.recording_id)

    if not rows:
        raise ValueError(
            "В размеченных записях не найдено активных блоков. "
            "Проверьте уровень сигнала и метки."
        )
    return RealDataset(
        X=np.vstack(rows),
        y=labels,
        groups=groups,
        label_counts=counts,
        recordings=len(infos),
        blocks=len(rows),
        skipped=skipped,
    )


def group_split(
    groups: list[str],
    labels: list[str],
    *,
    test_fraction: float = 0.25,
    seed: int = 1,
) -> tuple[np.ndarray, np.ndarray, bool]:
    """Split by recording id, never by individual block."""
    rng = np.random.default_rng(seed)
    by_class: dict[str, list[str]] = {}
    for group, label in zip(groups, labels):
        by_class.setdefault(label, [])
        if group not in by_class[label]:
            by_class[label].append(group)
    train_groups: set[str] = set()
    test_groups: set[str] = set()
    holdout = False
    for label, names in by_class.items():
        names = list(names)
        rng.shuffle(names)
        n_test = max(1, int(round(len(names) * test_fraction))) if len(names) >= 2 else 0
        test_groups.update(names[:n_test])
        train_groups.update(names[n_test:])
        if n_test:
            holdout = True
    train_idx = [i for i, group in enumerate(groups) if group in train_groups]
    test_idx = [i for i, group in enumerate(groups) if group in test_groups]
    return np.array(train_idx), np.array(test_idx), holdout


def train_from_recordings(
    path: str | Path,
    recordings_dir: str | Path,
    *,
    include_synthetic: bool = True,
    synthetic_per_class: int = 40,
    block_s: float = 0.2,
    max_blocks: int = 20,
    epochs: int = 600,
    seed: int = 1,
    progress: Callable[[int, int, str], None] | None = None,
) -> tuple[SoftmaxModel, dict]:
    real = build_real_dataset(
        recordings_dir, block_s=block_s, max_blocks=max_blocks,
        progress=progress,
    )
    X = real.X
    y = list(real.y)
    groups = list(real.groups)
    synthetic_blocks = 0

    if include_synthetic:
        syn_X, syn_y, _ = generate_dataset(
            per_class=max(4, int(synthetic_per_class)), seed=seed + 100
        )
        X = np.vstack([X, syn_X])
        synthetic_blocks = len(syn_y)
        for index, label in enumerate(syn_y):
            y.append(label)
            groups.append(f"synthetic-{index}")

    classes = [name for name in CLASSES if name in set(y)]
    if len(classes) < 2:
        raise ValueError("Для обучения нужно минимум два разных класса.")

    train_idx, test_idx, holdout = group_split(
        groups, y, seed=seed
    )
    if len(train_idx) == 0:
        raise ValueError("После разделения не осталось обучающих блоков.")
    if len(test_idx) == 0:
        train_idx = np.arange(len(y))
        test_idx = np.arange(len(y))

    holdout_model = train_softmax(
        X[train_idx], [y[i] for i in train_idx],
        classes=classes, epochs=epochs, seed=seed,
    )
    metrics = evaluate(
        holdout_model, X[test_idx], [y[i] for i in test_idx]
    )
    metrics.update({
        "source": "mixed" if include_synthetic else "real",
        "holdout": bool(holdout),
        "total_blocks": len(y),
        "real_recordings": real.recordings,
        "real_blocks": real.blocks,
        "synthetic_blocks": synthetic_blocks,
        "skipped_blocks": real.skipped,
        "label_counts": dict(real.label_counts),
        "trained_at": time.time(),
    })

    final = train_softmax(
        X, y, classes=classes, epochs=epochs, seed=seed + 1
    )
    final.metadata = dict(metrics)
    path = Path(path)
    final.save(path)
    return final, metrics


def dataset_summary(recordings_dir: str | Path) -> dict:
    """Quick labeled/unlabeled stats for the UI without training."""
    infos = list_recordings(recordings_dir)
    labeled = [info for info in infos if info.label in CLASSES]
    counts: dict[str, int] = {}
    for info in labeled:
        counts[info.label] = counts.get(info.label, 0) + 1
    return {
        "recordings": len(infos),
        "labeled": len(labeled),
        "counts": counts,
        "classes": [CLASS_RU.get(key, key) for key in CLASSES],
    }
