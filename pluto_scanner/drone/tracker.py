"""Aggregate per-block observations into human-readable events."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any

from .features import DroneObservation, QUIET


@dataclass
class DroneEvent:
    event_id: str
    band_key: str
    band_name: str
    class_key: str
    class_ru: str
    freq_hz: float
    freq_min_hz: float
    freq_max_hz: float
    bw_hz: float = 0.0
    first_seen: float = 0.0
    last_seen: float = 0.0
    count: int = 0
    max_snr_db: float = 0.0
    max_duty: float = 0.0
    max_burst_ms: float = 0.0
    confidence: float = 0.0
    drone_like: bool = False
    active: bool = True
    device_ids: list[str] = field(default_factory=list)
    spectrum_freqs_hz: list[float] = field(default_factory=list)
    spectrum_db: list[float] = field(default_factory=list)
    envelope_db: list[float] = field(default_factory=list)
    envelope_ms: list[float] = field(default_factory=list)
    clip_path: str = ""
    clip_samples: int = 0
    clip_sample_rate: float = 0.0
    clip_center_hz: float = 0.0
    whitelisted: bool = False
    whitelist_name: str = ""
    ml: dict[str, Any] = field(default_factory=dict)

    @property
    def duration_s(self) -> float:
        return max(0.0, self.last_seen - self.first_seen)

    @property
    def last_heard_s(self) -> float:
        return max(0.0, time.time() - self.last_seen)

    def to_dict(self, *, include_spectrum: bool = True) -> dict[str, Any]:
        payload: dict[str, Any] = {
            "event_id": self.event_id,
            "band_key": self.band_key,
            "band_name": self.band_name,
            "class_key": self.class_key,
            "class_ru": self.class_ru,
            "freq_hz": round(float(self.freq_hz), 1),
            "freq_min_hz": round(float(self.freq_min_hz), 1),
            "freq_max_hz": round(float(self.freq_max_hz), 1),
            "bw_hz": round(float(self.bw_hz), 1),
            "first_seen": round(float(self.first_seen), 3),
            "last_seen": round(float(self.last_seen), 3),
            "duration_s": round(self.duration_s, 3),
            "count": int(self.count),
            "max_snr_db": round(float(self.max_snr_db), 2),
            "max_duty": round(float(self.max_duty), 3),
            "max_burst_ms": round(float(self.max_burst_ms), 2),
            "confidence": round(float(self.confidence), 3),
            "drone_like": bool(self.drone_like),
            "active": bool(self.active),
            "device_ids": list(self.device_ids),
            "envelope_db": list(self.envelope_db),
            "envelope_ms": list(self.envelope_ms),
            "clip_path": self.clip_path,
            "clip_samples": int(self.clip_samples),
            "clip_sample_rate": round(float(self.clip_sample_rate), 1),
            "clip_center_hz": round(float(self.clip_center_hz), 1),
            "whitelisted": bool(self.whitelisted),
            "whitelist_name": self.whitelist_name,
            "ml": dict(self.ml),
        }
        if include_spectrum:
            payload["spectrum_freqs_hz"] = list(self.spectrum_freqs_hz)
            payload["spectrum_db"] = list(self.spectrum_db)
        return payload


class DroneTracker:
    """Merge observations that describe the same transmitter.

    FHSS and Wi-Fi events are merged across the whole band because their
    frequency changes from burst to burst.  Narrowband events are merged only
    within ``merge_hz``.
    """

    def __init__(self, *, merge_hz: float = 3.0e6, timeout_s: float = 10.0) -> None:
        self.merge_hz = float(merge_hz)
        self.timeout_s = max(1.0, float(timeout_s))
        self._events: dict[str, DroneEvent] = {}
        self._seq = 0

    # ------------------------------------------------------------------ update
    def update(self, obs: DroneObservation) -> tuple[DroneEvent | None, bool]:
        if obs.class_key == QUIET:
            return None, False
        match = self._find(obs)
        is_new = match is None
        if match is None:
            self._seq += 1
            match = DroneEvent(
                event_id=f"drone-{self._seq:04d}",
                band_key=obs.band_key,
                band_name=obs.band_name,
                class_key=obs.class_key,
                class_ru=obs.class_ru,
                freq_hz=obs.peak_freq_hz,
                freq_min_hz=obs.peak_freq_hz,
                freq_max_hz=obs.peak_freq_hz,
                first_seen=obs.timestamp,
                last_seen=obs.timestamp,
                count=0,
                device_ids=[],
            )
            self._events[match.event_id] = match

        if obs.peak_freq_hz < match.freq_min_hz:
            match.freq_min_hz = obs.peak_freq_hz
        if obs.peak_freq_hz > match.freq_max_hz:
            match.freq_max_hz = obs.peak_freq_hz
        # Keep the strongest peak as the representative frequency.
        if obs.snr_db >= match.max_snr_db:
            match.freq_hz = obs.peak_freq_hz
            if obs.spectrum_freqs_hz:
                match.spectrum_freqs_hz = list(obs.spectrum_freqs_hz)
                match.spectrum_db = list(obs.spectrum_db)
            if obs.envelope_db:
                match.envelope_db = list(obs.envelope_db)
                match.envelope_ms = list(obs.envelope_ms)
        match.last_seen = max(match.last_seen, obs.timestamp)
        match.count += 1
        match.max_snr_db = max(match.max_snr_db, obs.snr_db)
        match.max_duty = max(match.max_duty, obs.active_fraction)
        match.max_burst_ms = max(match.max_burst_ms, obs.max_burst_ms)
        match.bw_hz = max(match.bw_hz, obs.occupied_bw_hz)
        match.confidence = max(match.confidence, obs.confidence)
        match.drone_like = match.drone_like or obs.drone_like
        if obs.extra.get("ml"):
            match.ml = dict(obs.extra["ml"])
        match.active = True
        if obs.device_id not in match.device_ids:
            match.device_ids.append(obs.device_id)
        return match, is_new

    def _find(self, obs: DroneObservation) -> DroneEvent | None:
        candidates = [
            event for event in self._events.values()
            if event.band_key == obs.band_key
            and event.class_key == obs.class_key
            and event.active
        ]
        if not candidates:
            return None
        if obs.class_key in ("FHSS", "WIFI"):
            return max(candidates, key=lambda event: event.last_seen)
        best = None
        best_delta = float("inf")
        for event in candidates:
            delta = abs(event.freq_hz - obs.peak_freq_hz)
            limit = max(self.merge_hz, 2.0 * obs.occupied_bw_hz)
            if delta <= limit and delta < best_delta:
                best = event
                best_delta = delta
        return best

    # ------------------------------------------------------------------ expire
    def expire(self, now: float | None = None) -> list[DroneEvent]:
        now = time.time() if now is None else float(now)
        changed: list[DroneEvent] = []
        for event in self._events.values():
            if event.active and now - event.last_seen > self.timeout_s:
                event.active = False
                changed.append(event)
        return changed

    def events(self, *, include_inactive: bool = True) -> list[DroneEvent]:
        values = list(self._events.values())
        if not include_inactive:
            values = [event for event in values if event.active]
        values.sort(key=lambda event: event.last_seen, reverse=True)
        return values

    def get(self, event_id: str) -> DroneEvent | None:
        return self._events.get(event_id)

    def summary(self) -> dict[str, Any]:
        events = self.events()
        by_class: dict[str, int] = {}
        by_band: dict[str, int] = {}
        for event in events:
            by_class[event.class_key] = by_class.get(event.class_key, 0) + 1
            by_band[event.band_key] = by_band.get(event.band_key, 0) + 1
        return {
            "events_total": len(events),
            "events_active": sum(1 for event in events if event.active),
            "events_drone_like": sum(1 for event in events if event.drone_like),
            "by_class": by_class,
            "by_band": by_band,
        }

    def reset(self) -> None:
        self._events.clear()
        self._seq = 0
