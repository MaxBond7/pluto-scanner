"""Train the binary drone/background model.

Data sources, in order of trust:

1. **DroneRF** (Al-Sa'd et al., 2019, CC BY 4.0) — real 2.4 GHz recordings of
   three drone families plus real background activity.  Positives are the
   windows where the drone actually transmits; silent windows inside a drone
   recording are dropped, because the folder label is per recording, not per
   window.
2. **Own recordings** — labelled IQ from ``iq_recordings``; ``NARROW`` voice
   recordings are the most important negatives.
3. **Synthetic blocks** — the project's own generator.  It adds coverage for
   433/868/915 MHz, where DroneRF has no data, and for shapes the field
   recordings do not contain.

Usage::

    python -m pluto_scanner.ml.train_binary --dronerf-root Z:\\datasets\\DroneRF_extracted

The extracted DroneRF features are cached, so retraining and cross-checks do
not read 40 GB again.
"""
from __future__ import annotations

import argparse
import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

import numpy as np

from ..drone.bands import DroneBand
from ..drone.features import (
    FHSS,
    NARROW,
    OVERLOAD,
    QUIET,
    TELEMETRY,
    VIDEO_ANALOG,
    VIDEO_DIGITAL,
    WIFI,
    analyze_iq,
)
from ..paths import DEFAULT_ML_MODEL, RECORDINGS_DIR
from .binary import (
    BACKGROUND,
    DRONE,
    BinaryModel,
    calibration_table,
    evaluate_binary,
    fit_binary,
    roc_auc,
    _stratified_group_split,
)
from .dronerf import (
    DRONERF_WINDOW,
    BinaryDataset,
    mix_noise,
    scan_recordings,
    analyze_window,
)
from .binary_features import BINARY_FEATURE_NAMES, from_observation

BINARY_SAMPLE_RATE = 20.48e6
BINARY_BLOCK_S = 0.02
DRONERF_MIN_RMS = 7.0
DEFAULT_DRONERF_CHUNKS = 6

SYNTHETIC_NEGATIVES = (WIFI, NARROW)
# Synthetic drone blocks are deliberately **not** used as positives: the
# generator makes a continuous carrier, while every real drone window in
# DroneRF is gated (duty about 0.4).  Mixing the two taught the model a
# contradiction and dropped ROC-AUC from 0.97 to 0.85, so synthetic data is
# only used for negatives it actually models well (Wi-Fi-like bursts and
# narrow carriers).
AUGMENT_SNR_DB = (24.0, 18.0, 14.0, 10.0, 7.0)


def _band(fs: float) -> DroneBand:
    return DroneBand(
        "binary", "binary", -0.45 * fs, 0.45 * fs, "training band", alarm=True,
    )


def _empty() -> BinaryDataset:
    return BinaryDataset(
        X=np.empty((0, len(BINARY_FEATURE_NAMES)), dtype=np.float64),
        y=[], groups=[], sources=[], snr=np.empty(0), meta=[],
    )


def _append(
    dataset: BinaryDataset,
    observation,
    *,
    label: int,
    group: str,
    source: str,
) -> None:
    dataset.X = np.vstack([dataset.X, from_observation(observation)[None, :]])
    dataset.y.append(DRONE if label else BACKGROUND)
    dataset.groups.append(group)
    dataset.sources.append(source)
    dataset.snr = np.append(dataset.snr, float(observation.snr_db))
    dataset.meta.append({
        "class_key": observation.class_key,
        "snr_db": round(float(observation.snr_db), 2),
        "bw_hz": round(float(observation.occupied_bw_hz), 1),
        "duty": round(float(observation.active_fraction), 3),
    })


# ------------------------------------------------------------------ DroneRF
def collect_dronerf(
    root: str | Path,
    *,
    chunks: int = DEFAULT_DRONERF_CHUNKS,
    min_rms: float = DRONERF_MIN_RMS,
    augment: bool = True,
    seed: int = 1,
    progress: Callable[[int, int, str], None] | None = None,
) -> BinaryDataset:
    """Extract feature vectors from the DroneRF recordings."""
    recordings = scan_recordings(root)
    rng = np.random.default_rng(seed)
    data = _empty()
    total = len(recordings)

    for index, recording in enumerate(recordings, start=1):
        # A recording holds both drone transmissions ("bursts") and silence.
        # The dataset label is per recording, so windows with no signal must
        # be dropped instead of being learned as "drone".
        windows: list[np.ndarray] = []
        for block in _iter_windows(recording, chunks):
            rms = float(np.sqrt(np.mean(np.abs(block) ** 2)))
            if rms < float(min_rms):
                continue
            windows.append(block)

        for block in windows:
            observation = analyze_window(block)
            if observation is None or observation.class_key in (QUIET, OVERLOAD):
                continue
            label = 0 if recording.is_background else 1
            _append(
                data, observation,
                label=label,
                group=recording.group,
                source=f"dronerf-{recording.family}",
            )
            if augment and label == 1 and float(observation.snr_db) > 12.0:
                level = float(AUGMENT_SNR_DB[
                    int(rng.integers(0, len(AUGMENT_SNR_DB)))
                ])
                noisy = analyze_window(mix_noise(block, level, rng))
                if noisy is not None and noisy.class_key not in (
                    QUIET, OVERLOAD
                ):
                    _append(
                        data, noisy,
                        label=1,
                        group=recording.group,
                        source=f"dronerf-{recording.family}-noisy",
                    )
        if progress is not None:
            progress(index, total, recording.key)
    return data


def _iter_windows(recording, chunks: int):
    from .dronerf import iter_windows

    return iter_windows(recording, chunks=chunks, window=DRONERF_WINDOW)


# --------------------------------------------------------------- recordings
def collect_recordings(
    recordings_dir: str | Path,
    *,
    block_s: float = BINARY_BLOCK_S,
    max_blocks: int = 80,
    label: int = 0,
    only_classes: tuple[str, ...] = (NARROW, WIFI, TELEMETRY),
    progress: Callable[[int, int, str], None] | None = None,
) -> BinaryDataset:
    """Use labelled local recordings as extra (mostly negative) examples."""
    from ..recordings import list_recordings

    directory = Path(recordings_dir)
    data = _empty()
    if not directory.exists():
        return data
    infos = [
        info for info in list_recordings(directory)
        if info.label in only_classes and info.exists
    ]
    for index, info in enumerate(infos, start=1):
        fs = max(1000.0, float(info.sample_rate))
        center = float(info.center_freq)
        band = DroneBand(
            "rec", "recording",
            center - 0.45 * fs, center + 0.45 * fs, alarm=True,
        )
        block = max(256, int(fs * max(0.005, float(block_s))))
        try:
            samples = np.memmap(info.path, dtype=np.complex64, mode="r")
        except Exception:
            continue
        total = int(samples.size)
        if total < block:
            del samples
            continue
        count = min(max_blocks, max(1, total // block))
        step = max(block, (total - block) // max(1, count - 1))
        starts = [min(total - block, i * step) for i in range(count)]
        for start in starts:
            iq = np.array(samples[start:start + block], dtype=np.complex64)
            observation = analyze_iq(
                iq, fs, center, band,
                device_id=info.recording_id,
                threshold_db=6.0, nfft=4096, notch_hz=300e3,
            )
            if observation is None or observation.class_key in (
                QUIET, OVERLOAD
            ):
                continue
            _append(
                data, observation,
                label=label,
                group=f"rec-{info.recording_id}",
                source=f"recording-{info.label}",
            )
        del samples
        if progress is not None:
            progress(index, len(infos), info.recording_id)
    return data


# ---------------------------------------------------------------- synthetic
def collect_synthetic(
    *,
    per_class: int = 120,
    seed: int = 7,
    progress: Callable[[int, int, str], None] | None = None,
) -> BinaryDataset:
    """Synthetic blocks at the monitor's own block size and sample rate."""
    from .synthetic import make_iq

    rng = np.random.default_rng(seed)
    band = _band(BINARY_SAMPLE_RATE)
    data = _empty()
    labels = [(name, 0) for name in SYNTHETIC_NEGATIVES]
    total = per_class * len(labels)
    done = 0
    for name, label in labels:
        for _ in range(max(1, int(per_class))):
            iq = make_iq(
                name, fs=BINARY_SAMPLE_RATE, duration=BINARY_BLOCK_S, rng=rng,
            )
            observation = analyze_iq(
                iq, BINARY_SAMPLE_RATE, 0.0, band,
                device_id="synthetic",
                threshold_db=6.0, nfft=4096, notch_hz=300e3,
            )
            if observation is None or observation.class_key in (
                QUIET, OVERLOAD
            ):
                iq = (iq * 3.0).astype(np.complex64)
                observation = analyze_iq(
                    iq, BINARY_SAMPLE_RATE, 0.0, band,
                    device_id="synthetic",
                    threshold_db=6.0, nfft=4096, notch_hz=300e3,
                )
            if observation is None or observation.class_key in (
                QUIET, OVERLOAD
            ):
                continue
            _append(
                data, observation, label=label,
                group=f"syn-{name}-{len(data.y)}",
                source=f"synthetic-{name}",
            )
            done += 1
            if progress is not None:
                progress(done, total, name)
    return data


# ------------------------------------------------------------------- merge
def merge(*datasets: BinaryDataset) -> BinaryDataset:
    parts = [d for d in datasets if len(d)]
    if not parts:
        return _empty()
    return BinaryDataset(
        X=np.vstack([d.X for d in parts]),
        y=[v for d in parts for v in d.y],
        groups=[v for d in parts for v in d.groups],
        sources=[v for d in parts for v in d.sources],
        snr=np.concatenate([d.snr for d in parts]),
        meta=[v for d in parts for v in d.meta],
    )


def save_cache(path: str | Path, dataset: BinaryDataset) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    np.savez_compressed(
        path,
        X=dataset.X,
        y=np.array([1 if v == DRONE else 0 for v in dataset.y], dtype=np.int8),
        groups=np.array(dataset.groups, dtype=object),
        sources=np.array(dataset.sources, dtype=object),
        snr=dataset.snr,
    )
    return path


def load_cache(path: str | Path) -> BinaryDataset | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = np.load(path, allow_pickle=True)
        labels = [DRONE if int(v) else BACKGROUND for v in payload["y"]]
        return BinaryDataset(
            X=np.asarray(payload["X"], dtype=np.float64),
            y=labels,
            groups=[str(v) for v in payload["groups"]],
            sources=[str(v) for v in payload["sources"]],
            snr=np.asarray(payload["snr"], dtype=np.float64),
            meta=[],
        )
    except Exception:
        return None


# ---------------------------------------------------------------- training
def _labels_as_int(dataset: BinaryDataset) -> list[int]:
    return [1 if value == DRONE else 0 for value in dataset.y]


def _source_breakdown(
    dataset: BinaryDataset,
    index: np.ndarray,
    scores: np.ndarray,
    threshold: float,
) -> dict[str, dict[str, float]]:
    """How each data source behaves on the holdout split."""
    buckets: dict[str, list[float]] = {}
    for position, i in enumerate(index):
        name = dataset.sources[int(i)]
        buckets.setdefault(name, []).append(float(scores[position]))
    result: dict[str, dict[str, float]] = {}
    for name, values in sorted(buckets.items()):
        array = np.asarray(values, dtype=np.float64)
        result[name] = {
            "n": int(array.size),
            "mean_score": round(float(array.mean()), 4),
            "median_score": round(float(np.median(array)), 4),
            "share_above_threshold": round(
                float((array >= threshold).mean()), 4
            ),
        }
    return result


def _threshold_for_fpr(
    negatives: np.ndarray, target_fpr: float = 0.01, floor: float = 0.85
) -> float:
    if negatives.size == 0:
        return 0.95
    value = float(np.quantile(negatives, 1.0 - float(target_fpr)))
    return float(min(0.995, max(floor, value)))


@dataclass
class TrainingReport:
    model: BinaryModel
    metrics: dict
    payload: dict = field(default_factory=dict)


def train(
    dataset: BinaryDataset,
    *,
    seed: int = 1,
    test_fraction: float = 0.25,
    target_fpr: float = 0.01,
    epochs: int = 800,
) -> TrainingReport:
    labels = _labels_as_int(dataset)
    if len(set(labels)) < 2:
        raise ValueError(
            "Нужны оба класса: положительные (дрон) и отрицательные (не дрон)."
        )
    train_idx, test_idx = _stratified_group_split(
        labels, dataset.groups, test_fraction=test_fraction, seed=seed,
    )
    if train_idx.size == 0 or test_idx.size == 0:
        train_idx = np.arange(len(labels))
        test_idx = np.arange(len(labels))

    holdout = fit_binary(
        dataset.X[train_idx], [labels[i] for i in train_idx],
        epochs=epochs, seed=seed,
    )
    test_scores = holdout.predict_proba(dataset.X[test_idx])
    test_labels = [labels[i] for i in test_idx]
    threshold = _threshold_for_fpr(
        test_scores[np.asarray(test_labels) == 0], target_fpr=target_fpr,
    )
    metrics = evaluate_binary(
        test_labels, test_scores, threshold=threshold, target_fpr=target_fpr,
    )
    metrics["roc_auc"] = round(roc_auc(test_labels, test_scores), 4)
    metrics["calibration"] = calibration_table(test_labels, test_scores)
    metrics["by_source"] = _source_breakdown(
        dataset, test_idx, test_scores, threshold,
    )
    metrics["holdout"] = True

    final = fit_binary(
        dataset.X, labels, epochs=epochs, seed=seed + 1,
    )
    final.threshold_alarm = threshold
    final.threshold_candidate = 0.60

    composition: dict[str, int] = {}
    for source in dataset.sources:
        composition[source] = composition.get(source, 0) + 1

    final.metadata = {
        "source": "dronerf+recordings+synthetic",
        "trained_at": time.time(),
        "seed": int(seed),
        "total_blocks": int(len(labels)),
        "positives": int(sum(labels)),
        "negatives": int(len(labels) - sum(labels)),
        "composition": dict(sorted(composition.items())),
        "metrics": metrics,
        "thresholds": {
            "alarm": round(float(threshold), 3),
            "candidate": 0.60,
            "target_fpr": float(target_fpr),
        },
        "features": "12 features from pluto_scanner.ml.features",
        "datasets": [
            "DroneRF, Al-Sa'd et al. 2019, CC BY 4.0, doi:10.17632/f4c2b4n755.1",
            "own IQ recordings (iq_recordings)",
            "project synthetic generator",
        ],
        "limitations": [
            "не определяет модель дрона",
            "не заменяет Remote ID",
            "Wi-Fi-дрон физически похож на обычный Wi-Fi",
            "калибровка проверена на ограниченном наборе записей",
        ],
    }
    return TrainingReport(final, metrics, {
        "composition": composition,
        "test_size": int(test_idx.size),
        "threshold": threshold,
    })


def cross_family_report(
    dataset: BinaryDataset, *, epochs: int = 800, seed: int = 3
) -> dict[str, dict]:
    """Train on some drone families and test on the one that was left out."""
    families = sorted({
        source.replace("dronerf-", "").split("-")[0]
        for source in dataset.sources
        if source.startswith("dronerf-")
    })
    families = [name for name in families if name not in ("background", "")]
    if len(families) < 2:
        return {}
    results: dict[str, dict] = {}
    is_drone = np.array([1 if v == DRONE else 0 for v in dataset.y])
    dronerf = np.array([source.startswith("dronerf-") for source in dataset.sources])
    for family in families:
        test_mask = dronerf & np.array([
            source.startswith(f"dronerf-{family}") for source in dataset.sources
        ])
        train_mask = ~test_mask
        if test_mask.sum() < 10 or train_mask.sum() < 10:
            continue
        if len(set(is_drone[train_mask])) < 2:
            continue
        model = fit_binary(
            dataset.X[train_mask], is_drone[train_mask].tolist(),
            epochs=epochs, seed=seed,
        )
        scores = model.predict_proba(dataset.X[test_mask])
        results[family] = {
            "n": int(test_mask.sum()),
            "recall_at_0.9": round(float((scores >= 0.9).mean()), 4),
            "mean_score": round(float(scores.mean()), 4),
            "median_score": round(float(np.median(scores)), 4),
        }
    return results


def build_markdown(metrics: dict, metadata: dict, cross: dict) -> str:
    m = metrics
    lines = [
        "# Отчёт: бинарная модель «дрон / не дрон»",
        "",
        "Отчёт генерируется командой `python -m pluto_scanner.ml.train_binary`.",
        "Данные обучения в поставку не входят; в приложении лежит только",
        "маленький JSON с весами.",
        "",
        f"- ROC-AUC на отложенной выборке: **{m.get('roc_auc')}**",
        f"- TPR при FPR 1%: **{m.get('tpr_at_1pct_fpr')}**",
        f"- Порог тревоги: {m.get('threshold')}",
        f"- Precision: {m.get('precision')}, recall: {m.get('recall')}",
        f"- Ложные тревоги: {m.get('false_alarm_rate')}",
        f"- Блоков: {m.get('n')} (дрон {m.get('positives')}, "
        f"не дрон {m.get('negatives')})",
        "",
        "## Состав данных",
        "",
    ]
    for name, count in sorted(metadata.get("composition", {}).items()):
        lines.append(f"- `{name}`: {count}")
    by_source = m.get("by_source") or {}
    if by_source:
        lines += [
            "", "## Источники на отложенной выборке", "",
            "| источник | блоков | средний score | доля выше порога |",
            "|---|---:|---:|---:|",
        ]
        for name, row in by_source.items():
            lines.append(
                f"| `{name}` | {row['n']} | {row['mean_score']} | "
                f"{row['share_above_threshold']} |"
            )
    lines += ["", "## Калибровка", "", "| бина | блоков | средний score | доля дронов |", "|---|---:|---:|---:|"]
    for row in m.get("calibration", []):
        lines.append(
            f"| {row['bin']} | {row['count']} | {row['mean_score']} | "
            f"{row['observed']} |"
        )
    if cross:
        lines += ["", "## Кросс-проверка по семействам дронов", "",
                  "| семейство | блоков | recall@0.9 | средний score |",
                  "|---|---:|---:|---:|"]
        for name, row in cross.items():
            lines.append(
                f"| {name} | {row['n']} | {row['recall_at_0.9']} | "
                f"{row['mean_score']} |"
            )
    lines += [
        "",
        "## Как это читать",
        "",
        "- «TPR при FPR 1%» — какую долю дронов поймаем, если разрешим",
        "  1% ложных тревог на блок.",
        "- `dronerf-background` — реальные записи, где дрон не летал, но была",
        "  чужая активность (Wi-Fi/помеха). Самая сложная часть: широкий",
        "  непрерывный Wi-Fi физически похож на видеолинк дрона.",
        "- `*-noisy` — те же дроны, искусственно ослабленные до SNR 7–24 дБ.",
        "- Кросс-проверка обучает модель без одного семейства и проверяет на",
        "  нём. Это ответ на вопрос «а новый дрон поймает?».",
        "",
        "## Ограничения",
        "",
        "- Wi-Fi-дрон (Bebop) неотличим от обычного Wi-Fi без декодирования.",
        "- 433/868/915 МГц подтверждены только отрицательными примерами.",
        "- Модель не определяет модель дрона и не заменяет Remote ID.",
        "",
    ]
    return "\n".join(lines)


# ---------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Train the binary drone/background model.",
    )
    parser.add_argument(
        "--dronerf-root", default="",
        help="Folder with the extracted DroneRF CSV files (optional).",
    )
    parser.add_argument(
        "--chunks", type=int, default=DEFAULT_DRONERF_CHUNKS,
        help="20 ms windows per DroneRF file.",
    )
    parser.add_argument(
        "--recordings", default=str(RECORDINGS_DIR),
        help="Folder with local labelled IQ recordings.",
    )
    parser.add_argument(
        "--synthetic", type=int, default=120,
        help="Synthetic blocks per class.",
    )
    parser.add_argument(
        "--out", default=str(DEFAULT_ML_MODEL.parent / "ml_drone_binary.json"),
    )
    parser.add_argument("--cache", default="")
    parser.add_argument("--report", default="")
    parser.add_argument("--seed", type=int, default=1)
    parser.add_argument("--cross-check", action="store_true")
    args = parser.parse_args(argv)

    started = time.perf_counter()
    dataset = None
    if args.cache:
        dataset = load_cache(args.cache)
        if dataset is not None:
            print(f"кэш DroneRF: {args.cache} ({len(dataset)} блоков)")

    if dataset is None and args.dronerf_root:
        print(f"DroneRF: {args.dronerf_root}")
        dataset = collect_dronerf(
            args.dronerf_root,
            chunks=args.chunks,
            seed=args.seed,
            progress=lambda i, n, name: print(
                f"  [{i}/{n}] {name}", flush=True
            ) if i % 20 == 0 or i == n else None,
        )
        print(f"  положительных блоков: {sum(1 for v in dataset.y if v == DRONE)}")
        if args.cache:
            save_cache(args.cache, dataset)
            print(f"  кэш сохранён: {args.cache}")

    if dataset is None:
        dataset = _empty()

    print("локальные записи...")
    recordings = collect_recordings(args.recordings)
    if len(recordings):
        print(f"  блоков: {len(recordings)}")

    print("синтетика...")
    synthetic = collect_synthetic(
        per_class=args.synthetic, seed=args.seed + 5,
    )
    print(f"  блоков: {len(synthetic)}")

    full = merge(dataset, recordings, synthetic)
    if len(full) == 0:
        print("Нет данных для обучения.")
        return 2

    report = train(full, seed=args.seed)
    cross = cross_family_report(full) if args.cross_check else {}
    if cross:
        report.model.metadata["cross_family"] = cross

    out = Path(args.out)
    report.model.save(out)
    print(f"\nмодель: {out}")
    print(f"ROC-AUC: {report.metrics['roc_auc']}")
    print(f"TPR@FPR1%: {report.metrics['tpr_at_1pct_fpr']}")
    print(f"порог тревоги: {report.metrics['threshold']}")
    print(f"precision {report.metrics['precision']}, "
          f"recall {report.metrics['recall']}")
    for name, row in cross.items():
        print(f"  {name}: recall@0.9={row['recall_at_0.9']} "
              f"средний score={row['mean_score']}")

    if args.report:
        path = Path(args.report)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            build_markdown(report.metrics, report.model.metadata, cross),
            encoding="utf-8",
        )
        print(f"отчёт: {path}")

    print(f"готово за {time.perf_counter() - started:.1f} с")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
