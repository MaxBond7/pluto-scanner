"""Persistent white list for known drone-band signals.

A white-list entry suppresses *alarms* for a signal family that the operator
has explicitly accepted (Wi-Fi, a router, a camera, a known beacon).  It does
not hide the event from the table: the operator can still review it later.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import uuid4

from ..paths import DATA_DIR
from .tracker import DroneEvent


@dataclass
class WhitelistEntry:
    id: str
    name: str
    band_key: str
    class_key: str
    freq_min_hz: float
    freq_max_hz: float
    bw_hz: float
    device_ids: list[str] = field(default_factory=list)
    created: float = 0.0
    last_seen: float = 0.0
    hits: int = 0
    source: str = "user"

    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "band_key": self.band_key,
            "class_key": self.class_key,
            "freq_min_hz": round(float(self.freq_min_hz), 1),
            "freq_max_hz": round(float(self.freq_max_hz), 1),
            "bw_hz": round(float(self.bw_hz), 1),
            "device_ids": list(self.device_ids),
            "created": round(float(self.created), 3),
            "last_seen": round(float(self.last_seen), 3),
            "hits": int(self.hits),
            "source": self.source,
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "WhitelistEntry":
        return cls(
            id=str(data.get("id") or f"wl-{uuid4().hex[:10]}"),
            name=str(data.get("name") or "Известный сигнал"),
            band_key=str(data.get("band_key") or ""),
            class_key=str(data.get("class_key") or ""),
            freq_min_hz=float(data.get("freq_min_hz") or 0.0),
            freq_max_hz=float(data.get("freq_max_hz") or 0.0),
            bw_hz=float(data.get("bw_hz") or 0.0),
            device_ids=[str(x) for x in data.get("device_ids") or []],
            created=float(data.get("created") or 0.0),
            last_seen=float(data.get("last_seen") or 0.0),
            hits=int(data.get("hits") or 0),
            source=str(data.get("source") or "user"),
        )


class DroneWhitelist:
    """JSON-backed list of accepted signal families."""

    def __init__(self, path: str | Path | None = None) -> None:
        self.path = Path(path) if path is not None else DATA_DIR / "drone_whitelist.json"
        self.entries: list[WhitelistEntry] = []
        self.load()

    # ------------------------------------------------------------------ storage
    def load(self) -> None:
        self.entries = []
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("entries", []):
                self.entries.append(WhitelistEntry.from_dict(item))
        except Exception:
            self.entries = []

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "version": 1,
            "entries": [entry.to_dict() for entry in self.entries],
        }
        self.path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )

    # ------------------------------------------------------------------- query
    @property
    def count(self) -> int:
        return len(self.entries)

    def all(self) -> list[WhitelistEntry]:
        return list(self.entries)

    def match(self, event: DroneEvent) -> WhitelistEntry | None:
        frequency = float(event.freq_hz)
        for entry in self.entries:
            if entry.band_key and entry.band_key != event.band_key:
                continue
            if entry.class_key and entry.class_key != event.class_key:
                continue
            tolerance = max(1.0e6, 3.0 * max(entry.bw_hz, event.bw_hz))
            if (entry.freq_min_hz - tolerance
                    <= frequency
                    <= entry.freq_max_hz + tolerance):
                return entry
        return None

    # ------------------------------------------------------------------- write
    def add_event(
        self,
        event: DroneEvent,
        *,
        name: str = "",
        source: str = "user",
    ) -> WhitelistEntry:
        now = time.time()
        existing = self.match(event)
        if existing is not None:
            existing.freq_min_hz = min(existing.freq_min_hz, event.freq_min_hz)
            existing.freq_max_hz = max(existing.freq_max_hz, event.freq_max_hz)
            existing.last_seen = max(existing.last_seen, now)
            existing.hits += 1
            if source == "user" and name:
                existing.name = name
            if event.device_ids:
                for device_id in event.device_ids:
                    if device_id not in existing.device_ids:
                        existing.device_ids.append(device_id)
            self.save()
            return existing

        entry = WhitelistEntry(
            id=f"wl-{uuid4().hex[:10]}",
            name=name or f"{event.class_ru} · {event.freq_hz / 1e6:.3f} МГц",
            band_key=event.band_key,
            class_key=event.class_key,
            freq_min_hz=float(event.freq_min_hz),
            freq_max_hz=float(event.freq_max_hz),
            bw_hz=float(event.bw_hz),
            device_ids=list(event.device_ids),
            created=now,
            last_seen=now,
            hits=1,
            source=source,
        )
        self.entries.append(entry)
        self.save()
        return entry

    def remove(self, entry_id: str) -> bool:
        before = len(self.entries)
        self.entries = [entry for entry in self.entries if entry.id != entry_id]
        if len(self.entries) == before:
            return False
        self.save()
        return True

    def clear(self) -> None:
        self.entries.clear()
        self.save()
