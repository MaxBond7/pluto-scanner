"""Persistent per-band noise-floor profiles for the drone monitor.

The first blocks of a band are used to learn its noise floor.  Profiles are
kept per device, band, gain and sample rate, so a different antenna or gain
setting does not reuse a meaningless baseline.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from ..paths import DATA_DIR


@dataclass
class NoiseProfile:
    device_id: str
    band_key: str
    gain_db: float
    sample_rate: float
    noise_floor_db: float
    samples: int = 0
    updated: float = 0.0

    @property
    def key(self) -> str:
        return (
            f"{self.device_id}|{self.band_key}|"
            f"{self.gain_db:.1f}|{self.sample_rate / 1e6:.3f}"
        )

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "band_key": self.band_key,
            "gain_db": round(float(self.gain_db), 2),
            "sample_rate": round(float(self.sample_rate), 1),
            "noise_floor_db": round(float(self.noise_floor_db), 2),
            "samples": int(self.samples),
            "updated": round(float(self.updated), 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "NoiseProfile":
        return cls(
            device_id=str(data.get("device_id") or ""),
            band_key=str(data.get("band_key") or ""),
            gain_db=float(data.get("gain_db") or 0.0),
            sample_rate=float(data.get("sample_rate") or 0.0),
            noise_floor_db=float(data.get("noise_floor_db") or -200.0),
            samples=int(data.get("samples") or 0),
            updated=float(data.get("updated") or 0.0),
        )


class DroneBackgroundStore:
    def __init__(self, path: str | Path | None = None) -> None:
        self.path = (
            Path(path)
            if path is not None
            else DATA_DIR / "drone_background.json"
        )
        self.profiles: dict[str, NoiseProfile] = {}
        self.load()

    def load(self) -> None:
        self.profiles = {}
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            for item in data.get("profiles", []):
                profile = NoiseProfile.from_dict(item)
                self.profiles[profile.key] = profile
        except Exception:
            self.profiles = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "version": 1,
                    "profiles": [
                        profile.to_dict()
                        for profile in self.profiles.values()
                    ],
                },
                ensure_ascii=False,
                indent=2,
            ),
            encoding="utf-8",
        )

    def get(
        self,
        *,
        device_id: str,
        band_key: str,
        gain_db: float,
        sample_rate: float,
    ) -> float | None:
        key = NoiseProfile(
            device_id=device_id,
            band_key=band_key,
            gain_db=gain_db,
            sample_rate=sample_rate,
            noise_floor_db=-200.0,
        ).key
        profile = self.profiles.get(key)
        return None if profile is None else profile.noise_floor_db

    def update(
        self,
        *,
        device_id: str,
        band_key: str,
        gain_db: float,
        sample_rate: float,
        noise_floor_db: float,
        count_samples: int = 1,
    ) -> NoiseProfile:
        probe = NoiseProfile(
            device_id=device_id,
            band_key=band_key,
            gain_db=gain_db,
            sample_rate=sample_rate,
            noise_floor_db=noise_floor_db,
        )
        profile = self.profiles.get(probe.key)
        if profile is None:
            profile = probe
            profile.samples = max(1, count_samples)
            profile.updated = time.time()
            self.profiles[profile.key] = profile
        else:
            # Exponential smoothing across sessions.
            profile.noise_floor_db = (
                0.8 * profile.noise_floor_db + 0.2 * float(noise_floor_db)
            )
            profile.samples += max(1, count_samples)
            profile.updated = time.time()
        self.save()
        return profile
