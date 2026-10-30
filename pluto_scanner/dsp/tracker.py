"""Stable contact tracking.

The detector sees a signal every frame.  The tracker is what turns that into
a contact with a stable ID, age, hit count and a short grace period.  New
tracks are tentative until they have been seen several times, which kills
single-frame noise spikes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING

from ..model import Contact, Detection, SignalType

if TYPE_CHECKING:
    from ..store import ContactStore


@dataclass
class _Track:
    contact_id: str
    device_id: str
    freq_hz: float
    bw_hz: float
    type: SignalType
    confidence: float
    first_seen: float
    last_seen: float
    hits: int = 1
    misses: int = 0
    max_snr_db: float = 0.0
    last_snr_db: float = 0.0
    known: bool = False
    alternatives: list[tuple[SignalType, float]] = field(default_factory=list)
    last_detection: Detection | None = None

    def to_contact(self) -> Contact:
        return Contact(
            contact_id=self.contact_id,
            device_id=self.device_id,
            freq_hz=self.freq_hz,
            bw_hz=self.bw_hz,
            type=self.type,
            confidence=self.confidence,
            first_seen=self.first_seen,
            last_seen=self.last_seen,
            hits=self.hits,
            misses=self.misses,
            max_snr_db=self.max_snr_db,
            last_snr_db=self.last_snr_db,
            known=self.known,
            active=self.misses == 0,
            alternatives=list(self.alternatives),
        )


class ContactTracker:
    def __init__(self, device_id: str, store: "ContactStore | None" = None,
                 min_hits: int = 2, max_misses: int = 6) -> None:
        self.device_id = device_id
        self.store = store
        self.min_hits = max(1, int(min_hits))
        self.max_misses = max(1, int(max_misses))
        self._tracks: dict[str, _Track] = {}
        self._counter = 0

    def reset(self) -> None:
        self._tracks.clear()

    @property
    def contact_count(self) -> int:
        return len(self._visible())

    def _visible(self) -> list[_Track]:
        return [t for t in self._tracks.values() if t.hits >= self.min_hits]

    def contact(self, contact_id: str) -> Contact | None:
        track = self._tracks.get(contact_id)
        return track.to_contact() if track else None

    def snapshot(self) -> list[Contact]:
        """Current contacts without advancing the miss counters."""
        return sorted((t.to_contact() for t in self._visible()),
                      key=lambda c: c.freq_hz)

    def update(self, detections: list[Detection], timestamp: float,
               bin_hz: float) -> list[Contact]:
        # Greedy nearest assignment.  A handful of detections per frame makes
        # this more than fast enough and much easier to reason about than a
        # full Hungarian assignment.
        pairs: list[tuple[float, int, str]] = []
        for di, det in enumerate(detections):
            for tid, tr in self._tracks.items():
                if tr.misses > self.max_misses:
                    continue
                tol = max(3.0 * bin_hz,
                          min(0.75 * max(tr.bw_hz, det.bw_hz), 50e3),
                          750.0)
                dist = abs(det.freq_hz - tr.freq_hz)
                if dist <= tol:
                    pairs.append((dist / tol, di, tid))
        pairs.sort(key=lambda p: p[0])

        used_det: set[int] = set()
        used_tracks: set[str] = set()
        for _, di, tid in pairs:
            if di in used_det or tid in used_tracks:
                continue
            det = detections[di]
            tr = self._tracks[tid]
            used_det.add(di)
            used_tracks.add(tid)
            tr.freq_hz = 0.70 * tr.freq_hz + 0.30 * det.freq_hz
            tr.bw_hz = 0.70 * tr.bw_hz + 0.30 * det.bw_hz
            tr.last_snr_db = float(det.snr_db)
            tr.max_snr_db = max(tr.max_snr_db, float(det.snr_db))
            tr.hits += 1
            tr.misses = 0
            tr.last_seen = float(timestamp)
            if det.confidence >= tr.confidence - 0.12:
                tr.type = det.type
                tr.confidence = 0.65 * tr.confidence + 0.35 * det.confidence
            tr.alternatives = list(det.alternatives)
            tr.last_detection = det

        for di, det in enumerate(detections):
            if di in used_det:
                continue
            self._counter += 1
            cid = f"{self.device_id}-{self._counter:04d}"
            known = bool(self.store.is_known(det.freq_hz, det.bw_hz)) if self.store else False
            tr = _Track(
                contact_id=cid,
                device_id=self.device_id,
                freq_hz=float(det.freq_hz),
                bw_hz=float(det.bw_hz),
                type=det.type,
                confidence=float(det.confidence),
                first_seen=float(timestamp),
                last_seen=float(timestamp),
                hits=1,
                max_snr_db=float(det.snr_db),
                last_snr_db=float(det.snr_db),
                known=known,
                alternatives=list(det.alternatives),
                last_detection=det,
            )
            self._tracks[cid] = tr
            # A track created on this frame has already been matched; do not
            # count that same frame as a miss in the ageing pass below.
            used_tracks.add(cid)

        # Age unmatched tracks.  Keep them a few frames so a one-frame fade
        # does not create a duplicate contact.
        stale: list[str] = []
        for tid, tr in self._tracks.items():
            if tid in used_tracks:
                continue
            tr.misses += 1
            if tr.misses > self.max_misses:
                stale.append(tid)
        for tid in stale:
            self._tracks.pop(tid, None)

        return sorted((t.to_contact() for t in self._visible()),
                      key=lambda c: c.freq_hz)

    def mark_known(self, contact_id: str) -> Contact | None:
        tr = self._tracks.get(contact_id)
        if tr is None:
            return None
        tr.known = True
        contact = tr.to_contact()
        if self.store is not None:
            self.store.mark_known(contact)
        return contact

    def forget(self, contact_id: str) -> Contact | None:
        tr = self._tracks.get(contact_id)
        if tr is None:
            return None
        tr.known = False
        contact = tr.to_contact()
        if self.store is not None:
            self.store.forget(contact)
        return contact
