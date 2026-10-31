"""Small NumPy softmax classifier with JSON persistence."""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np

from ..drone.features import DroneObservation
from .features import FEATURE_NAMES, feature_vector
from .synthetic import CLASSES, generate_dataset


@dataclass
class MLResult:
    label: str
    confidence: float
    alternatives: list[tuple[str, float]]

    def to_dict(self) -> dict[str, Any]:
        return {
            "label": self.label,
            "confidence": round(float(self.confidence), 3),
            "alternatives": [
                [label, round(float(prob), 3)]
                for label, prob in self.alternatives
            ],
        }


def _softmax(logits: np.ndarray) -> np.ndarray:
    shifted = logits - np.max(logits, axis=1, keepdims=True)
    exp = np.exp(shifted)
    return exp / np.sum(exp, axis=1, keepdims=True)


class SoftmaxModel:
    def __init__(
        self,
        *,
        classes: list[str],
        mean: np.ndarray,
        std: np.ndarray,
        weights: np.ndarray,
        bias: np.ndarray,
        metadata: dict[str, Any] | None = None,
    ) -> None:
        self.classes = list(classes)
        self.mean = np.asarray(mean, dtype=np.float64)
        self.std = np.asarray(std, dtype=np.float64)
        self.weights = np.asarray(weights, dtype=np.float64)
        self.bias = np.asarray(bias, dtype=np.float64)
        self.metadata = dict(metadata or {})

    @property
    def accuracy(self) -> float:
        return float(self.metadata.get("accuracy", 0.0))

    @property
    def source(self) -> str:
        return str(self.metadata.get("source", "unknown"))

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        X = np.atleast_2d(np.asarray(X, dtype=np.float64))
        norm = (X - self.mean) / np.where(self.std == 0.0, 1.0, self.std)
        return _softmax(norm @ self.weights + self.bias)

    def predict(self, X: np.ndarray) -> list[str]:
        probs = self.predict_proba(X)
        return [self.classes[int(i)] for i in np.argmax(probs, axis=1)]

    def predict_observation(self, obs: DroneObservation) -> MLResult:
        probs = self.predict_proba(feature_vector(obs))[0]
        order = np.argsort(probs)[::-1]
        ranked = [
            (self.classes[int(i)], float(probs[int(i)]))
            for i in order[:3]
        ]
        return MLResult(ranked[0][0], ranked[0][1], ranked)

    def to_dict(self) -> dict[str, Any]:
        return {
            "version": 1,
            "kind": "drone-softmax",
            "classes": self.classes,
            "features": FEATURE_NAMES,
            "mean": self.mean.tolist(),
            "std": self.std.tolist(),
            "weights": self.weights.tolist(),
            "bias": self.bias.tolist(),
            "metadata": self.metadata,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SoftmaxModel":
        if data.get("kind") != "drone-softmax":
            raise ValueError("not a drone softmax model")
        model = cls(
            classes=[str(v) for v in data["classes"]],
            mean=np.asarray(data["mean"], dtype=np.float64),
            std=np.asarray(data["std"], dtype=np.float64),
            weights=np.asarray(data["weights"], dtype=np.float64),
            bias=np.asarray(data["bias"], dtype=np.float64),
            metadata=data.get("metadata") or {},
        )
        if model.weights.shape != (len(model.mean), len(model.classes)):
            raise ValueError("feature/class shape mismatch")
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
    def load(cls, path: str | Path) -> "SoftmaxModel | None":
        try:
            path = Path(path)
            if not path.exists():
                return None
            data = json.loads(path.read_text(encoding="utf-8"))
            return cls.from_dict(data)
        except Exception:
            return None


def train_softmax(
    X: np.ndarray,
    y: list[str] | np.ndarray,
    *,
    classes: list[str] | None = None,
    epochs: int = 600,
    learning_rate: float = 0.06,
    l2: float = 1.0e-3,
    seed: int = 1,
) -> SoftmaxModel:
    X = np.asarray(X, dtype=np.float64)
    labels = list(y)
    class_list = list(classes or sorted(set(labels)))
    index = {name: i for i, name in enumerate(class_list)}
    Y = np.zeros((len(labels), len(class_list)), dtype=np.float64)
    for row, label in enumerate(labels):
        Y[row, index[label]] = 1.0

    mean = X.mean(axis=0)
    std = X.std(axis=0)
    std = np.where(std < 1e-9, 1.0, std)
    Xs = (X - mean) / std

    n, d = Xs.shape
    c = len(class_list)
    rng = np.random.default_rng(seed)
    weights = rng.normal(0.0, 0.01, (d, c))
    bias = np.zeros(c, dtype=np.float64)
    mw = np.zeros_like(weights)
    vw = np.zeros_like(weights)
    mb = np.zeros_like(bias)
    vb = np.zeros_like(bias)
    beta1, beta2, eps = 0.9, 0.999, 1.0e-8

    for step in range(1, max(1, epochs) + 1):
        probs = _softmax(Xs @ weights + bias)
        diff = (probs - Y) / max(1, n)
        grad_w = Xs.T @ diff + l2 * weights
        grad_b = diff.sum(axis=0)
        mw = beta1 * mw + (1.0 - beta1) * grad_w
        vw = beta2 * vw + (1.0 - beta2) * (grad_w ** 2)
        mb = beta1 * mb + (1.0 - beta1) * grad_b
        vb = beta2 * vb + (1.0 - beta2) * (grad_b ** 2)
        mw_hat = mw / (1.0 - beta1 ** step)
        vw_hat = vw / (1.0 - beta2 ** step)
        mb_hat = mb / (1.0 - beta1 ** step)
        vb_hat = vb / (1.0 - beta2 ** step)
        weights -= learning_rate * mw_hat / (np.sqrt(vw_hat) + eps)
        bias -= learning_rate * mb_hat / (np.sqrt(vb_hat) + eps)

    return SoftmaxModel(
        classes=class_list, mean=mean, std=std,
        weights=weights, bias=bias,
    )


def evaluate(
    model: SoftmaxModel,
    X: np.ndarray,
    y: list[str],
) -> dict[str, Any]:
    predicted = model.predict(X)
    labels = list(y)
    accuracy = (
        sum(1 for a, b in zip(predicted, labels) if a == b) / max(1, len(labels))
    )
    confusion: dict[str, dict[str, int]] = {
        name: {other: 0 for other in model.classes}
        for name in model.classes
    }
    for truth, guess in zip(labels, predicted):
        confusion.setdefault(truth, {}).setdefault(guess, 0)
        confusion[truth][guess] += 1

    per_class: dict[str, dict[str, float]] = {}
    for name in model.classes:
        tp = sum(
            1 for truth, guess in zip(labels, predicted)
            if truth == name and guess == name
        )
        fp = sum(
            1 for truth, guess in zip(labels, predicted)
            if truth != name and guess == name
        )
        fn = sum(
            1 for truth, guess in zip(labels, predicted)
            if truth == name and guess != name
        )
        per_class[name] = {
            "precision": tp / max(1, tp + fp),
            "recall": tp / max(1, tp + fn),
            "support": float(sum(1 for truth in labels if truth == name)),
        }
    return {
        "accuracy": accuracy,
        "confusion": confusion,
        "per_class": per_class,
        "n": len(labels),
    }


def _stratified_split(
    y: list[str], *, test_fraction: float = 0.2, seed: int = 1
) -> tuple[np.ndarray, np.ndarray]:
    rng = np.random.default_rng(seed)
    train: list[int] = []
    test: list[int] = []
    for label in sorted(set(y)):
        indices = np.array([i for i, value in enumerate(y) if value == label])
        rng.shuffle(indices)
        n_test = max(1, int(round(indices.size * test_fraction)))
        test.extend(indices[:n_test].tolist())
        train.extend(indices[n_test:].tolist())
    return np.array(train), np.array(test)


def train_synthetic(
    *,
    per_class: int = 60,
    epochs: int = 600,
    seed: int = 1,
    progress=None,
) -> tuple[SoftmaxModel, dict[str, Any]]:
    X, y, heuristics = generate_dataset(
        per_class=per_class, seed=seed, progress=progress
    )
    if len(y) < len(CLASSES) * 2:
        raise ValueError("слишком мало синтетических примеров")
    train_idx, test_idx = _stratified_split(y, seed=seed)
    holdout = train_softmax(
        X[train_idx], [y[i] for i in train_idx],
        classes=CLASSES, epochs=epochs, seed=seed,
    )
    metrics = evaluate(
        holdout, X[test_idx], [y[i] for i in test_idx]
    )
    metrics["source"] = "synthetic"
    metrics["per_class_requested"] = per_class
    metrics["heuristic_agreement"] = (
        sum(1 for a, b in zip(y, heuristics) if a == b) / max(1, len(y))
    )
    metrics["trained_at"] = time.time()

    # Final model uses all data; reported metrics remain the holdout estimate.
    final = train_softmax(
        X, y, classes=CLASSES, epochs=epochs, seed=seed + 1
    )
    final.metadata = dict(metrics)
    return final, metrics


def train_and_save(
    path: str | Path,
    *,
    per_class: int = 60,
    epochs: int = 600,
    seed: int = 1,
    progress=None,
) -> tuple[SoftmaxModel, dict[str, Any]]:
    model, metrics = train_synthetic(
        per_class=per_class, epochs=epochs, seed=seed, progress=progress
    )
    model.save(path)
    return model, metrics
