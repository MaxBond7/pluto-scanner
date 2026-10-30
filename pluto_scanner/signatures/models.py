"""Data model for the local known-signal signature library."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any
from uuid import uuid4


@dataclass
class SignalSignature:
    id: str
    name: str
    category: str
    source_class: str
    start_hz: float
    end_hz: float
    bw_hz: float = 0.0
    modulation: str = ""
    duty: float = 0.0
    burst_ms: float = 0.0
    hop: str = "none"          # none | slow | fast
    notes: str = ""
    references: list[str] = field(default_factory=list)
    license: str = ""
    confidence: float = 0.5
    builtin: bool = False

    @property
    def width_hz(self) -> float:
        return max(0.0, self.end_hz - self.start_hz)

    @property
    def center_hz(self) -> float:
        return (self.start_hz + self.end_hz) / 2.0

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "category": self.category,
            "source_class": self.source_class,
            "start_hz": round(float(self.start_hz), 1),
            "end_hz": round(float(self.end_hz), 1),
            "bw_hz": round(float(self.bw_hz), 1),
            "modulation": self.modulation,
            "duty": round(float(self.duty), 3),
            "burst_ms": round(float(self.burst_ms), 3),
            "hop": self.hop,
            "notes": self.notes,
            "references": list(self.references),
            "license": self.license,
            "confidence": round(float(self.confidence), 3),
            "builtin": bool(self.builtin),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SignalSignature":
        refs = data.get("references") or []
        if isinstance(refs, str):
            refs = [part.strip() for part in refs.split(";") if part.strip()]
        return cls(
            id=str(data.get("id") or f"user-{uuid4().hex[:10]}"),
            name=str(data.get("name") or "Без названия"),
            category=str(data.get("category") or "Прочее"),
            source_class=str(data.get("source_class") or "unknown"),
            start_hz=float(data.get("start_hz") or 0.0),
            end_hz=float(data.get("end_hz") or data.get("start_hz") or 0.0),
            bw_hz=float(data.get("bw_hz") or 0.0),
            modulation=str(data.get("modulation") or ""),
            duty=float(data.get("duty") or 0.0),
            burst_ms=float(data.get("burst_ms") or 0.0),
            hop=str(data.get("hop") or "none"),
            notes=str(data.get("notes") or ""),
            references=[str(item) for item in refs],
            license=str(data.get("license") or ""),
            confidence=max(0.0, min(1.0, float(data.get("confidence") or 0.5))),
            builtin=bool(data.get("builtin", False)),
        )
