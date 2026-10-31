"""Binary ``drone`` / ``background`` detector.

The six-class model answers *what kind* of activity was seen.  This module
answers the more important question first: *is this a drone link at all?*

It is deliberately small: a logistic regression over the same 12 features the
heuristic classifier already measures.  That keeps the installer tiny, makes
the score auditable, and lets the model be trained from recordings on a
laptop.

The score is **not** a probability of a particular drone model and not a
guarantee: it is a calibrated "looks like a drone link" value.  The decision
layer below turns it into three bands so the UI never shows a bare number.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..drone.features import OVERLOAD, QUIET, DroneObservation
from .binary_features import BINARY_FEATURE_NAMES, from_observation

BACKGROUND = "background"
DRONE = "drone"
UNKNOWN = "unknown"

DEFAULT_CANDIDATE_THRESHOLD = 0.60
DEFAULT_ALARM_THRESHOLD = 0.90
MIN_SNR_DB = 6.0

VERDICT_RU = {
    DRONE: "дрон",
    "candidate": "кандидат",
    BACKGROUND: "не дрон",
    UNKNOWN: "не определено",
}


def sigmoid(values: np.ndarray) -> np.ndarray:
    values = np.clip(np.asarray(values, dtype=np.float64), -60.0, 60.0)
    return 1.0 / (1.0 + np.exp(-values))


@dataclass
class BinaryResult:
    score: float
    verdict: str
    source: str = ""
    threshold_alarm: float = DEFAULT_ALARM_THRESHOLD
    threshold_candidate: float = DEFAULT_CANDIDATE_THRESHOLD

    @property
    def is_drone(self) -> bool:
        return self.verdict == DRONE

    def to_dict(self) -> dict[str, Any]:
        return {
            "score": round(float(self.score), 3),
            "verdict": self.verdict,
            "verdict_ru": VERDICT_RU.get(self.verdict, self.verdict),
            "source": self.source,
            "threshold_alarm": round(float(self.threshold_alarm), 3),
            "threshold_candidate": round(float(self.threshold_candidate), 3),
        }


class BinaryModel:
    """Logistic regression with standardised inputs and JSON persistence."""

    kind = "drone-binary"

    def __init__(
        self,
        *,
        mean: np.ndarray,
        std: np.ndarray,
        coef: np.ndarray,
        intercept: float,
        features: list[str] | None = None,
        metadata: dict[str, Any] | None = None,
        threshold_alarm: float = DEFAULT_ALARM_THRESHOLD,
        threshold_candidate: float = DEFAULT_CANDIDATE_THRESHOLD,
    ) -> None:
        self.mean = np.asarray(mean, dtype=np.float64)
        self.std = np.asarray(std, dtype=np.float64)
        self.coef = np.asarray(coef, dtype=np.float64)
        self.intercept = float(intercept)
        self.features = list(features or BINARY_FEATURE_NAMES)
        self.metadata = dict(metadata or {})
        self.threshold_alarm = float(threshold_alarm)
        self.threshold_candidate = float(threshold_candidate)

    # ------------------------------------------------------------- properties
    @property
    def source(self) -> str:
        return str(self.metadata.get("source", "unknown"))

    @property
    def auc(self) -> float:
        return float(self.metadata.get("roc_auc", 0.0))

    # -------------------------------------------------------------- inference
    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        if X.shape[1] != self.mean.size:
            raise ValueError("feature count mismatch")
        norm = (X - self.mean) / np.where(self.std == 0.0, 1.0, self.std)
        return sigmoid(norm @ self.coef + self.intercept)

    def verdict(self, score: float) -> str:
        if score >= self.threshold_alarm:
            return DRONE
        if score >= self.threshold_candidate:
            return "candidate"
        return BACKGROUND

    def predict_observation(self, obs: DroneObservation) -> BinaryResult:
        if obs.class_key in (QUIET, OVERLOAD) or obs.snr_db < MIN_SNR_DB:
            # Nothing to judge.  Saying "background 3%" here would look like
            # a confident negative, which it is not.
            return BinaryResult(
                0.0, UNKNOWN, self.source,
                self.threshold_alarm, self.threshold_candidate,
            )
        score = float(self.predict_proba(from_observation(obs))[0])
        return BinaryResult(
            score, self.verdict(score), self.source,
            self.threshold_alarm, self.threshold_candidate,
        )

    # ------------------------------------------------------------ persistence
    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "kind": self.kind,
            "features": self.features,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "coef": self.coef.tolist(),
            "intercept": self.intercept,
            "threshold_alarm": self.threshold_alarm,
            "threshold_candidate": self.threshold_candidate,
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "BinaryModel":
        if data.get("kind") != cls.kind:
            raise ValueError("not a drone binary model")
        model = cls(
            mean=np.asarray(data["mean"], dtype=np.float64),
            std=np.asarray(data["std"], dtype=np.float64),
            coef=np.asarray(data["coef"], dtype=np.float64),
            intercept=float(data["intercept"]),
            features=[str(v) for v in data.get("features", BINARY_FEATURE_NAMES)],
            metadata=data.get("metadata") or {},
            threshold_alarm=float(
                data.get("threshold_alarm", DEFAULT_ALARM_THRESHOLD)
            ),
            threshold_candidate=float(
                data.get("threshold_candidate", DEFAULT_CANDIDATE_THRESHOLD)
            ),
        )
        if model.coef.shape != model.mean.shape:
            raise ValueError("feature/coef shape mismatch")
        return model

    def save(self, path: str | Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "BinaryModel | None":
        try:
            path = Path(path)
            if not path.exists():
                return None
            return cls.from_dict(json.loads(path.read_text(encoding="utf-8")))
        except Exception:
            return None


# --------------------------------------------------------------------- metrics
def roc_auc(labels: Iterable[int], scores: Iterable[float]) -> float:
    """Rank-based ROC-AUC with tie handling (Mann-Whitney U)."""
    y = np.asarray(list(labels), dtype=np.float64)
    s = np.asarray(list(scores), dtype=np.float64)
    if y.size == 0 or y.min() == y.max():
        return 0.0
    order = np.argsort(s, kind="mergesort")
    ranks = np.empty_like(s)
    sorted_scores = s[order]
    i = 0
    while i < sorted_scores.size:
        j = i
        while j + 1 < sorted_scores.size and sorted_scores[j + 1] == sorted_scores[i]:
            j += 1
        ranks[order[i:j + 1]] = (i + j) / 2.0 + 1.0
        i = j + 1
    positives = int(y.sum())
    negatives = int(y.size - positives)
    if positives == 0 or negatives == 0:
        return 0.0
    return float(
        (ranks[y == 1].sum() - positives * (positives + 1) / 2.0)
        / (positives * negatives)
    )


def roc_curve(labels: Iterable[int], scores: Iterable[float]):
    y = np.asarray(list(labels), dtype=np.int8)
    s = np.asarray(list(scores), dtype=np.float64)
    thresholds = np.unique(np.round(s, 6))[::-1]
    positives = max(1, int((y == 1).sum()))
    negatives = max(1, int((y == 0).sum()))
    tpr: list[float] = []
    fpr: list[float] = []
    for threshold in thresholds:
        guess = s >= threshold
        tpr.append(float((guess & (y == 1)).sum() / positives))
        fpr.append(float((guess & (y == 0)).sum() / negatives))
    return np.asarray(fpr), np.asarray(tpr), thresholds


def tpr_at_fpr(
    labels: Iterable[int], scores: Iterable[float], target_fpr: float = 0.01
) -> float:
    fpr, tpr, _ = roc_curve(labels, scores)
    ok = fpr <= float(target_fpr)
    return float(tpr[ok].max()) if ok.any() else 0.0


def evaluate_binary(
    labels: Iterable[int],
    scores: Iterable[float],
    *,
    threshold: float = DEFAULT_ALARM_THRESHOLD,
    target_fpr: float = 0.01,
) -> dict[str, Any]:
    y = np.asarray(list(labels), dtype=np.int8)
    s = np.asarray(list(scores), dtype=np.float64)
    guess = s >= float(threshold)
    tp = int((guess & (y == 1)).sum())
    fp = int((guess & (y == 0)).sum())
    tn = int((~guess & (y == 0)).sum())
    fn = int((~guess & (y == 1)).sum())
    precision = tp / max(1, tp + fp)
    recall = tp / max(1, tp + fn)
    return {
        "n": int(y.size),
        "positives": int((y == 1).sum()),
        "negatives": int((y == 0).sum()),
        "roc_auc": round(roc_auc(y, s), 4),
        "tpr_at_1pct_fpr": round(tpr_at_fpr(y, s, target_fpr), 4),
        "threshold": round(float(threshold), 3),
        "precision": round(precision, 4),
        "recall": round(recall, 4),
        "false_alarm_rate": round(fp / max(1, fp + tn), 4),
        "tp": tp, "fp": fp, "tn": tn, "fn": fn,
    }


def calibration_table(
    labels: Iterable[int],
    scores: Iterable[float],
    *,
    bins: int = 5,
) -> list[dict[str, float]]:
    """Reliability table: does ``score=0.9`` really mean nine out of ten?"""
    y = np.asarray(list(labels), dtype=np.int8)
    s = np.asarray(list(scores), dtype=np.float64)
    edges = np.linspace(0.0, 1.0, bins + 1)
    table: list[dict[str, float]] = []
    for low, high in zip(edges[:-1], edges[1:]):
        mask = (s >= low) & (s < high if high < 1.0 else s <= high)
        if not mask.any():
            continue
        table.append({
            "bin": round(float((low + high) / 2.0), 2),
            "count": int(mask.sum()),
            "mean_score": round(float(s[mask].mean()), 3),
            "observed": round(float(y[mask].mean()), 3),
        })
    return table


def fit_binary(
    X: np.ndarray,
    y: list[int],
    *,
    epochs: int = 800,
    learning_rate: float = 0.08,
    l2: float = 3.0e-3,
    seed: int = 1,
) -> BinaryModel:
    """Fit the logistic model with Adam on the log-loss."""
    X = np.asarray(X, dtype=np.float64)
    target = np.asarray(y, dtype=np.float64)
    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std < 1e-9, 1.0, std)
    Xs = (X - mean) / std

    rng = np.random.default_rng(seed)
    coef = rng.normal(0.0, 0.01, Xs.shape[1])
    intercept = 0.0
    m_w = np.zeros_like(coef)
    v_w = np.zeros_like(coef)
    m_b = 0.0
    v_b = 0.0
    beta1, beta2, eps = 0.9, 0.999, 1.0e-8
    n = max(1, Xs.shape[0])

    # Class weights keep a 3:1 positive/negative mix from dominating the fit.
    positives = max(1.0, float(target.sum()))
    negatives = max(1.0, float(target.size - target.sum()))
    weight_pos = target.size / (2.0 * positives)
    weight_neg = target.size / (2.0 * negatives)
    weights = np.where(target > 0.5, weight_pos, weight_neg)

    for step in range(1, max(1, epochs) + 1):
        logits = Xs @ coef + intercept
        probs = sigmoid(logits)
        diff = (probs - target) * weights / n
        grad_w = Xs.T @ diff + l2 * coef
        grad_b = float(diff.sum())
        m_w = beta1 * m_w + (1.0 - beta1) * grad_w
        v_w = beta2 * v_w + (1.0 - beta2) * (grad_w ** 2)
        m_b = beta1 * m_b + (1.0 - beta1) * grad_b
        v_b = beta2 * v_b + (1.0 - beta2) * (grad_b ** 2)
        m_w_hat = m_w / (1.0 - beta1 ** step)
        v_w_hat = v_w / (1.0 - beta2 ** step)
        m_b_hat = m_b / (1.0 - beta1 ** step)
        v_b_hat = v_b / (1.0 - beta2 ** step)
        coef -= learning_rate * m_w_hat / (np.sqrt(v_w_hat) + eps)
        intercept -= learning_rate * m_b_hat / (np.sqrt(v_b_hat) + eps)

    return BinaryModel(
        mean=mean, std=std, coef=coef, intercept=intercept,
    )


def _stratified_group_split(
    labels: list[int],
    groups: list[str],
    *,
    test_fraction: float = 0.25,
    seed: int = 1,
) -> tuple[np.ndarray, np.ndarray]:
    """Split so that no group (recording/session) appears on both sides."""
    rng = np.random.default_rng(seed)
    by_class: dict[int, list[str]] = {}
    for label, group in zip(labels, groups):
        bucket = by_class.setdefault(int(label), [])
        if group not in bucket:
            bucket.append(group)
    test_groups: set[str] = set()
    for name in sorted(by_class):
        names = list(by_class[name])
        rng.shuffle(names)
        take = int(round(len(names) * test_fraction))
        if len(names) >= 2:
            take = max(1, take)
        test_groups.update(names[:take])
    train = [i for i, group in enumerate(groups) if group not in test_groups]
    test = [i for i, group in enumerate(groups) if group in test_groups]
    return np.asarray(train), np.asarray(test)
