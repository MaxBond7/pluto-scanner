"""JSON logging for the drone monitor.

Layout::

    drone_logs/
      drone_20261030_141500/
        config.json      # bands, sample rate, devices
        events.jsonl     # one line per new/ended event
        summary.json     # all events at stop
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any

import numpy as np

from .tracker import DroneEvent


def make_drone_id(now: float | None = None) -> str:
    stamp = time.localtime(time.time() if now is None else now)
    return time.strftime("%Y%m%d_%H%M%S", stamp)


def _keep_spectrum(event: DroneEvent) -> bool:
    """Keep the small spectral snapshot for every event.

    It is only 256 points and makes the event card useful when the JSON is
    opened later, even for NARROW/UNKNOWN candidates.
    """
    return True


class DroneRecorder:
    def __init__(
        self,
        out_dir: str | Path,
        *,
        drone_id: str,
        sample_rate: float,
        dwell_ms: float,
        threshold_db: float,
        bands: list[str],
        devices: list[dict[str, str]],
    ) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.drone_id = drone_id
        self.sample_rate = float(sample_rate)
        self.dwell_ms = float(dwell_ms)
        self.threshold_db = float(threshold_db)
        self.bands = list(bands)
        self.devices = list(devices)
        self.started = time.time()
        self.events_path = self.out_dir / "events.jsonl"
        self.summary_path = self.out_dir / "summary.json"
        self.config_path = self.out_dir / "config.json"
        self.clips_dir = self.out_dir / "clips"
        self.clips_dir.mkdir(parents=True, exist_ok=True)
        self.config_path.write_text(
            json.dumps({
                "drone_id": self.drone_id,
                "created": round(self.started, 3),
                "sample_rate": round(self.sample_rate, 1),
                "dwell_ms": round(self.dwell_ms, 1),
                "threshold_db": round(self.threshold_db, 2),
                "bands": self.bands,
                "devices": self.devices,
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        self.events_path.touch()

    def log_event(self, event: DroneEvent, *, kind: str = "update") -> None:
        payload = {"log": kind, "logged": round(time.time(), 3)}
        payload.update(event.to_dict(
            include_spectrum=_keep_spectrum(event)
        ))
        with self.events_path.open("a", encoding="utf-8") as handle:
            handle.write(json.dumps(payload, ensure_ascii=False) + "\n")

    def save_clip(
        self,
        event: DroneEvent,
        samples: np.ndarray,
        *,
        sample_rate: float,
        center_hz: float,
        device_id: str,
    ) -> Path:
        """Write one raw IQ evidence clip as little-endian complex64.

        The companion ``.json`` file makes the clip self-describing even when
        it is copied out of the log folder.
        """
        arr = np.asarray(samples, dtype=np.complex64).ravel()
        if arr.size == 0:
            raise ValueError("empty IQ clip")
        clip_path = self.clips_dir / f"{event.event_id}.cf32"
        arr.astype("<c8", copy=False).tofile(clip_path)
        meta = {
            "event_id": event.event_id,
            "device_id": device_id,
            "band_key": event.band_key,
            "band_name": event.band_name,
            "class_key": event.class_key,
            "class_ru": event.class_ru,
            "freq_hz": round(float(event.freq_hz), 1),
            "center_hz": round(float(center_hz), 1),
            "sample_rate": round(float(sample_rate), 1),
            "samples": int(arr.size),
            "seconds": round(float(arr.size) / max(1.0, sample_rate), 6),
            "format": "cf32",
            "byte_order": "little",
            "created": round(time.time(), 3),
        }
        clip_path.with_suffix(".json").write_text(
            json.dumps(meta, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return clip_path.resolve()

    def finalize(
        self,
        summary: dict[str, Any],
        events: list[DroneEvent],
    ) -> Path:
        self.summary_path.write_text(
            json.dumps({
                "drone_id": self.drone_id,
                "created": round(self.started, 3),
                "finished": round(time.time(), 3),
                "sample_rate": round(self.sample_rate, 1),
                "dwell_ms": round(self.dwell_ms, 1),
                "threshold_db": round(self.threshold_db, 2),
                "bands": self.bands,
                "devices": self.devices,
                "summary": summary,
                "events": [
                    event.to_dict(include_spectrum=_keep_spectrum(event))
                    for event in events
                ],
            }, ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        return self.summary_path.resolve()
