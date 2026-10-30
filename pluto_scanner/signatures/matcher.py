"""Match measured drone-band features against the local signature library."""
from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Any, Iterable

from .models import SignalSignature

# Which catalog source classes make sense for each measured class.
CLASS_SOURCES: dict[str, set[str]] = {
    "FHSS": {"rc", "bluetooth", "zigbee", "drone_control", "telemetry"},
    "TELEMETRY": {"telemetry", "rc", "drone_control", "bluetooth"},
    "VIDEO_ANALOG": {"drone_video", "analog_video", "broadcast"},
    "VIDEO_DIGITAL": {"drone_video", "wifi", "broadcast"},
    "WIFI": {"wifi"},
    "NARROW": {"unknown", "telemetry", "rc"},
    "UNKNOWN": {"unknown", "telemetry", "rc", "drone_control", "drone_video"},
}


@dataclass
class SignatureMatch:
    signature: SignalSignature
    score: float
    reasons: list[str]

    def to_dict(self) -> dict[str, Any]:
        return {
            "signature": self.signature.to_dict(),
            "score": round(float(self.score), 3),
            "reasons": list(self.reasons),
        }


def _features(event) -> tuple[float, float, float, str]:
    freq = float(getattr(event, "freq_hz", None)
                 or getattr(event, "peak_freq_hz", 0.0) or 0.0)
    bw = float(getattr(event, "bw_hz", None)
               or getattr(event, "occupied_bw_hz", 0.0) or 0.0)
    duty = float(getattr(event, "max_duty", None)
                 or getattr(event, "active_fraction", 0.0) or 0.0)
    class_key = str(getattr(event, "class_key", "UNKNOWN") or "UNKNOWN")
    return freq, bw, duty, class_key


def _frequency_score(freq: float, sig: SignalSignature) -> float:
    if freq <= 0:
        return 0.0
    if sig.start_hz <= freq <= sig.end_hz:
        return 1.0
    gap = min(abs(freq - sig.start_hz), abs(freq - sig.end_hz))
    scale = max(100e3, sig.width_hz * 0.5)
    return max(0.0, 1.0 - gap / scale)


def _bw_score(bw: float, sig: SignalSignature) -> float:
    if bw <= 0 or sig.bw_hz <= 0:
        return 0.35
    ratio = min(bw, sig.bw_hz) / max(bw, sig.bw_hz)
    return math.sqrt(max(0.0, min(1.0, ratio)))


def _duty_score(duty: float, sig: SignalSignature) -> float:
    return max(0.0, 1.0 - abs(float(duty) - float(sig.duty)))


def _class_score(class_key: str, sig: SignalSignature) -> float:
    allowed = CLASS_SOURCES.get(class_key)
    if not allowed:
        return 0.30
    return 1.0 if sig.source_class in allowed else 0.20


def match_event(
    event,
    signatures: Iterable[SignalSignature],
    *,
    limit: int = 3,
) -> list[SignatureMatch]:
    """Return the best catalog entries for one event/observation."""
    freq, bw, duty, class_key = _features(event)
    results: list[SignatureMatch] = []
    for sig in signatures:
        f_score = _frequency_score(freq, sig)
        bw_score = _bw_score(bw, sig)
        d_score = _duty_score(duty, sig)
        c_score = _class_score(class_key, sig)
        score = (
            0.45 * f_score
            + 0.25 * bw_score
            + 0.15 * d_score
            + 0.15 * c_score
        )
        # A frequency mismatch must dominate all other similarities.
        if f_score < 0.20:
            score *= 0.25
        score *= 0.70 + 0.30 * max(0.0, min(1.0, sig.confidence))
        reasons: list[str] = []
        if f_score >= 0.80:
            reasons.append("диапазон")
        if bw_score >= 0.50:
            reasons.append("ширина")
        if d_score >= 0.70:
            reasons.append("скважность")
        if c_score >= 0.80:
            reasons.append("класс")
        if class_key == "FHSS" and sig.hop == "fast":
            reasons.append("прыжки")
        if score >= 0.25:
            results.append(SignatureMatch(sig, score, reasons))
    results.sort(key=lambda item: item.score, reverse=True)
    return results[:max(1, int(limit))]
