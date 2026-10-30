"""Persistence for contacts the operator marked as known/background."""
from __future__ import annotations

import json
import logging
from dataclasses import asdict, dataclass
from pathlib import Path

from .model import Contact
from .paths import DATA_DIR

log = logging.getLogger(__name__)


@dataclass
class KnownContact:
    freq_hz: float
    bw_hz: float
    type: str
    name: str = ""
    device_id: str = ""
    marked_at: float = 0.0


class ContactStore:
    """A small JSON-backed whitelist.

    Matching is intentionally frequency/bandwidth based rather than
    device-id based: the same absolute frequency is normally the same
    transmitter even if it is heard on another Pluto.
    """

    def __init__(self, path: str | Path | None = None) -> None:
        if path is None:
            path = DATA_DIR / "known_contacts.json"
        self.path = Path(path)
        self.entries: list[KnownContact] = []
        self.load()

    def load(self) -> None:
        self.entries = []
        try:
            if not self.path.exists():
                return
            raw = json.loads(self.path.read_text(encoding="utf-8"))
            for item in raw.get("contacts", []):
                self.entries.append(KnownContact(**item))
        except Exception as exc:  # corrupted file must not stop the app
            log.warning("Cannot load %s: %s", self.path, exc)

    def save(self) -> None:
        try:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            data = {"version": 1, "contacts": [asdict(e) for e in self.entries]}
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception as exc:
            log.warning("Cannot save %s: %s", self.path, exc)

    @staticmethod
    def _tolerance(freq_hz: float, bw_hz: float, other_bw_hz: float) -> float:
        return min(50e3, max(3e3, 0.65 * max(bw_hz, other_bw_hz)))

    def is_known(self, freq_hz: float, bw_hz: float) -> bool:
        for e in self.entries:
            tol = self._tolerance(freq_hz, bw_hz, e.bw_hz)
            if abs(freq_hz - e.freq_hz) <= tol:
                return True
        return False

    def mark_known(self, contact: Contact, name: str = "") -> KnownContact:
        existing = self._find(contact.freq_hz, contact.bw_hz)
        if existing is not None:
            return existing
        entry = KnownContact(
            freq_hz=float(contact.freq_hz),
            bw_hz=float(contact.bw_hz),
            type=contact.type.value,
            name=name,
            device_id=contact.device_id,
        )
        self.entries.append(entry)
        self.save()
        return entry

    def forget(self, contact: Contact) -> bool:
        existing = self._find(contact.freq_hz, contact.bw_hz)
        if existing is None:
            return False
        self.entries.remove(existing)
        self.save()
        return True

    def _find(self, freq_hz: float, bw_hz: float) -> KnownContact | None:
        for e in self.entries:
            tol = self._tolerance(freq_hz, bw_hz, e.bw_hz)
            if abs(freq_hz - e.freq_hz) <= tol:
                return e
        return None
