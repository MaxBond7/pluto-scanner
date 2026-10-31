"""Domain-gap report: synthetic vs augmented vs real recordings."""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from ..drone.bands import DroneBand
from ..drone.features import CLASS_RU, OVERLOAD, QUIET, analyze_iq
from ..paths import DATA_DIR, DEFAULT_ML_MODEL, RECORDINGS_DIR
from ..recordings import list_recordings
from .dataset import build_real_dataset
from .features import FEATURE_NAMES, feature_vector
from .model import SoftmaxModel
from .synthetic import CLASSES, SPECS, make_iq

SYNTHETIC_SEED = 9001
_BAND = DroneBand(
    "2.4", "2.4 ГГц", 2400.0e6, 2483.5e6, alarm=True,
)


def _model(model_path: str | Path | None = None) -> SoftmaxModel:
    candidates = []
    if model_path:
        candidates.append(Path(model_path))
    candidates.extend([DATA_DIR / "ml_model.json", DEFAULT_ML_MODEL])
    for path in candidates:
        model = SoftmaxModel.load(path)
        if model is not None:
            return model
    raise FileNotFoundError("не найдена ML-модель")


def _augment(iq: np.ndarray, fs: float, rng: np.random.Generator) -> np.ndarray:
    t = np.arange(iq.size, dtype=np.float64) / max(1.0, fs)
    gain = 10.0 ** (rng.uniform(-12.0, 6.0) / 20.0)
    cfo = rng.uniform(-150e3, 150e3)
    eps = rng.uniform(-0.08, 0.08)
    phase = rng.uniform(-0.12, 0.12)
    i = iq.real.astype(np.float64)
    q = iq.imag.astype(np.float64)
    q = q * (1.0 + eps)
    mixed = (i + 1j * q) * np.exp(1j * phase)
    noise = rng.normal(0.0, 0.01, iq.size) + 1j * rng.normal(0.0, 0.01, iq.size)
    out = gain * mixed * np.exp(2j * np.pi * cfo * t) + noise
    return out.astype(np.complex64)


def synthetic_domain(
    *,
    per_class: int = 20,
    seed: int = SYNTHETIC_SEED,
    augment: bool = False,
) -> tuple[np.ndarray, list[str]]:
    rng = np.random.default_rng(seed)
    rows: list[np.ndarray] = []
    labels: list[str] = []
    for label in CLASSES:
        fs, duration = SPECS[label]
        for _ in range(max(1, per_class)):
            iq = make_iq(label, fs=fs, duration=duration, rng=rng)
            if augment:
                iq = _augment(iq, fs, rng)
            obs = analyze_iq(
                iq, fs, _BAND.center_hz, _BAND,
                device_id="domain", threshold_db=6.0, nfft=4096,
            )
            if obs is None or obs.class_key in (QUIET, OVERLOAD):
                continue
            rows.append(feature_vector(obs))
            labels.append(label)
    if not rows:
        return np.empty((0, len(FEATURE_NAMES))), []
    return np.vstack(rows), labels


def evaluate_domain(
    model: SoftmaxModel, X: np.ndarray, y: list[str]
) -> dict[str, Any]:
    if len(y) == 0:
        return {
            "n": 0, "supported": 0, "coverage": 0.0,
            "accuracy": None, "mean_confidence": None,
            "per_class": {}, "confusion": {},
        }
    pred = model.predict(X)
    probs = model.predict_proba(X)
    conf = probs.max(axis=1)
    supported = [i for i, label in enumerate(y) if label in model.classes]
    correct = [i for i in supported if pred[i] == y[i]]
    conf_map: dict[str, list[float]] = {}
    counts: dict[str, int] = {}
    hits: dict[str, int] = {}
    confusion: dict[str, dict[str, int]] = {}
    for i, label in enumerate(y):
        counts[label] = counts.get(label, 0) + 1
        confusion.setdefault(label, {})
        confusion[label][pred[i]] = confusion[label].get(pred[i], 0) + 1
        if i in supported:
            conf_map.setdefault(label, []).append(float(conf[i]))
            if pred[i] == label:
                hits[label] = hits.get(label, 0) + 1
    per_class = {}
    for label, count in counts.items():
        values = conf_map.get(label, [])
        per_class[label] = {
            "n": count,
            "correct": hits.get(label, 0),
            "mean_confidence": float(np.mean(values)) if values else None,
        }
    return {
        "n": len(y),
        "supported": len(supported),
        "coverage": len(supported) / len(y),
        "accuracy": len(correct) / len(supported) if supported else None,
        "mean_confidence": float(np.mean(conf)) if len(conf) else None,
        "per_class": per_class,
        "confusion": confusion,
    }


def feature_drift(
    X_syn: np.ndarray, y_syn: list[str],
    X_real: np.ndarray, y_real: list[str],
) -> list[dict[str, Any]]:
    common = [label for label in set(y_real) if label in set(y_syn)]
    if not common or X_real.size == 0:
        return []
    label = max(common, key=lambda item: y_real.count(item))
    syn = X_syn[np.array([value == label for value in y_syn])]
    real = X_real[np.array([value == label for value in y_real])]
    if syn.size == 0 or real.size == 0:
        return []
    mean_syn = syn.mean(axis=0)
    std_syn = syn.std(axis=0)
    std_syn = np.where(std_syn < 1e-9, 1.0, std_syn)
    mean_real = real.mean(axis=0)
    rows = []
    for index, name in enumerate(FEATURE_NAMES):
        rows.append({
            "feature": name,
            "synthetic_mean": float(mean_syn[index]),
            "real_mean": float(mean_real[index]),
            "drift_sigma": float((mean_real[index] - mean_syn[index]) / std_syn[index]),
        })
    rows.sort(key=lambda row: abs(row["drift_sigma"]), reverse=True)
    return rows


def _fmt(value: float | None, digits: int = 1) -> str:
    return "—" if value is None else f"{value * 100:.{digits}f}%"


def _markdown(report: dict[str, Any]) -> str:
    lines = [
        "# Domain-gap отчёт",
        "",
        f"Модель: `{report['model']}`",
        f"Источник модели: `{report['model_source']}`",
        f"Время: {report['created_ru']}",
        "",
        "## Домены",
        "",
        "| Домен | Примеров | Покрытие классов | Точность | Средняя уверенность |",
        "|---|---:|---:|---:|---:|",
    ]
    for name, item in report["domains"].items():
        lines.append(
            f"| {name} | {item['n']} | {_fmt(item['coverage'])} | "
            f"{_fmt(item['accuracy'])} | {_fmt(item['mean_confidence'])} |"
        )
    lines.extend(["", "## По классам", ""])
    for name, item in report["domains"].items():
        if not item["per_class"]:
            continue
        lines.append(f"### {name}")
        lines.append("")
        lines.append("| Класс | N | Верно | Средняя уверенность |")
        lines.append("|---|---:|---:|---:|")
        for key, row in item["per_class"].items():
            lines.append(
                f"| {CLASS_RU.get(key, key)} | {row['n']} | "
                f"{row['correct']} | {_fmt(row['mean_confidence'])} |"
            )
        lines.append("")
    drift = report.get("feature_drift") or []
    if drift:
        lines.extend([
            "## Дрейф признаков",
            "",
            "Самые сильные сдвиги между синтетикой и реальными записями "
            "(в единицах стандартного отклонения синтетики):",
            "",
            "| Признак | Синтетика | Реальность | Сдвиг, σ |",
            "|---|---:|---:|---:|",
        ])
        for row in drift[:8]:
            lines.append(
                f"| `{row['feature']}` | {row['synthetic_mean']:.3f} | "
                f"{row['real_mean']:.3f} | {row['drift_sigma']:+.2f} |"
            )
        lines.append("")
    lines.extend([
        "## Как читать",
        "",
        "- Высокая точность на синтетике не означает высокую точность на эфире.",
        "- Малое покрытие классов означает, что реальных примеров этого класса нет.",
        "- Большой дрейф признака показывает, где синтетика не похожа на реальность.",
        "- Если реальных классов меньше двух, это отчёт о тракте, а не о модели.",
        "",
        f"Реальных записей: {report['real_recordings']}, "
        f"блоков: {report['real_blocks']}, "
        f"пропущено (тихо/перегрузка): {report['real_skipped']}.",
        "",
    ])
    return "\n".join(lines)


def build_report(
    *,
    model_path: str | Path | None = None,
    recordings_dir: str | Path = RECORDINGS_DIR,
    out_dir: str | Path = DATA_DIR / "domain_gap",
    per_class: int = 20,
    block_s: float = 0.5,
    max_blocks: int = 10,
) -> tuple[dict[str, Any], Path]:
    model = _model(model_path)
    real = build_real_dataset(
        recordings_dir, block_s=block_s, max_blocks=max_blocks
    )
    syn_X, syn_y = synthetic_domain(per_class=per_class, augment=False)
    aug_X, aug_y = synthetic_domain(per_class=per_class, augment=True)
    domains = {
        "synthetic": evaluate_domain(model, syn_X, syn_y),
        "synthetic_augmented": evaluate_domain(model, aug_X, aug_y),
        "real": evaluate_domain(model, real.X, real.y),
    }
    drift = feature_drift(syn_X, syn_y, real.X, real.y)
    report = {
        "created": time.time(),
        "created_ru": time.strftime("%d.%m.%Y %H:%M"),
        "model": str(model_path or DATA_DIR / "ml_model.json"),
        "model_source": model.source,
        "real_recordings": real.recordings,
        "real_blocks": real.blocks,
        "real_skipped": real.skipped,
        "domains": domains,
        "feature_drift": drift,
    }
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    md = out_dir / "report.md"
    md.write_text(_markdown(report), encoding="utf-8")
    return report, md
