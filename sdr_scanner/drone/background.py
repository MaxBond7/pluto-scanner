# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Persistent per-band noise-floor profiles for the drone monitor.

The first blocks of a band are used to learn its noise floor.  Profiles are
kept per device, band, gain and sample rate, so a different antenna or gain
setting does not reuse a meaningless baseline.
"""
from __future__ import annotations

import json
import time
from dataclasses import dataclass, field
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

# --------------------------------------------------------------- spectrum map
BACKGROUND_BINS = 32
BACKGROUND_MIN_FRAMES = 20      # trust the map only after this many blocks
BACKGROUND_LEARN_FRAMES = 120   # learn the site, then freeze the map
BACKGROUND_MARK = 0.6           # share of known bins to call it "background"
BACKGROUND_BIN_ACTIVE = 0.12    # a bin seen in 12% of frames has an emitter
BACKGROUND_VERSION = 2


@dataclass
class SpectrumProfile:
    """How often each part of one monitored chunk was occupied.

    A band such as 2.4 GHz is swept as a dozen 20 MHz chunks with different
    centres.  Their spectra must not be averaged together — the bin index is
    relative to the chunk — so the map is kept **per chunk centre**.

    ``occupancy`` is the share of learned frames where a bin was above the
    floor.  A busy access point gives 0.2-1.0, a rare burst a few hundredths;
    the query asks how much of the current activity lands on bins that were
    seen during the background recording.
    """

    device_id: str
    band_key: str
    gain_db: float
    sample_rate: float
    center_hz: float = 0.0
    occupancy: list[float] = field(default_factory=list)
    frames: int = 0
    updated: float = 0.0

    @property
    def key(self) -> str:
        # Absolute chunk centre, independent of the sample rate and of how
        # many chunks the current rate produces.
        center = round(float(self.center_hz) / 0.5e6)
        return (
            f"{self.device_id}|{self.band_key}|{center}|{self.gain_db:.1f}"
        )

    @property
    def ready(self) -> bool:
        return self.frames >= BACKGROUND_MIN_FRAMES

    def known_bins(self) -> list[bool]:
        return [
            value >= BACKGROUND_BIN_ACTIVE for value in self.occupancy
        ]

    def to_dict(self) -> dict[str, Any]:
        return {
            "device_id": self.device_id,
            "band_key": self.band_key,
            "gain_db": round(float(self.gain_db), 2),
            "sample_rate": round(float(self.sample_rate), 1),
            "center_hz": round(float(self.center_hz), 1),
            "occupancy": [round(float(v), 3) for v in self.occupancy],
            "frames": int(self.frames),
            "updated": round(float(self.updated), 3),
        }

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "SpectrumProfile":
        return cls(
            device_id=str(data.get("device_id") or ""),
            band_key=str(data.get("band_key") or ""),
            gain_db=float(data.get("gain_db") or 0.0),
            sample_rate=float(data.get("sample_rate") or 0.0),
            center_hz=float(data.get("center_hz") or 0.0),
            occupancy=[float(v) for v in data.get("occupancy") or []],
            frames=int(data.get("frames") or 0),
            updated=float(data.get("updated") or 0.0),
        )


def active_bins(spectrum_db, bins: int = BACKGROUND_BINS) -> list[bool] | None:
    """Mark the coarse bins that are above the block's own floor."""
    import numpy as np

    spec = np.asarray(spectrum_db, dtype=np.float64)
    if spec.size < bins * 4 or not bool(np.isfinite(spec).all()):
        return None
    floor = float(np.percentile(spec, 25.0))
    above = spec > floor + 6.0
    edges = np.linspace(0, spec.size, bins + 1).astype(int)
    result: list[bool] = []
    for start, end in zip(edges[:-1], edges[1:]):
        span = max(1, end - start)
        # A wide signal lifts most of the bin; a narrow carrier only a few
        # points of it.  Both are permanent residents and both must count,
        # otherwise a Bluetooth beacon or a baby monitor would be missed.
        wide = float(above[start:end].mean()) >= 0.5
        strong = float(np.max(spec[start:end]) - floor) >= 12.0
        result.append(bool(wide or strong))
    return result


class BackgroundMap:
    """Persistent map of the signals that are always there.

    The map is learned during the first seconds of a session and then frozen:
    a drone that appears later can never teach the program that drones are
    background.  It is stored per device, band, gain and sample rate, because
    a different antenna changes the picture completely.
    """

    def __init__(
        self,
        path: str | Path | None = None,
        *,
        learn_frames: int = BACKGROUND_LEARN_FRAMES,
    ) -> None:
        self.path = (
            Path(path)
            if path is not None
            else DATA_DIR / "background_map.json"
        )
        self.learn_frames = max(10, int(learn_frames))
        self.profiles: dict[str, SpectrumProfile] = {}
        self.load()

    def load(self) -> None:
        self.profiles = {}
        try:
            if not self.path.exists():
                return
            data = json.loads(self.path.read_text(encoding="utf-8"))
            if int(data.get("version") or 1) < BACKGROUND_VERSION:
                # Version 1 averaged a whole band's chunks into one vector,
                # which mixed unrelated frequencies.  It cannot be reused.
                return
            for item in data.get("profiles", []):
                profile = SpectrumProfile.from_dict(item)
                if profile.occupancy:
                    self.profiles[profile.key] = profile
        except Exception:
            self.profiles = {}

    def save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(
            json.dumps(
                {
                    "version": BACKGROUND_VERSION,
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

    def _profile(self, obs, *, create: bool) -> SpectrumProfile | None:
        probe = SpectrumProfile(
            device_id=str(obs.device_id),
            band_key=str(obs.band_key),
            gain_db=float(
                (getattr(obs, "extra", {}) or {}).get("gain_db", 0.0) or 0.0
            ),
            sample_rate=float(obs.sample_rate),
            center_hz=float(getattr(obs, "center_hz", 0.0) or 0.0),
        )
        profile = self.profiles.get(probe.key)
        if profile is None and create:
            profile = probe
            profile.occupancy = [0.0] * BACKGROUND_BINS
            self.profiles[probe.key] = profile
        return profile

    def learn(self, obs) -> None:
        """Add one block to the map (the dedicated background recording).

        Learning is a separate action on purpose: if the live monitor taught
        the map, a drone hovering nearby for a minute would slowly become
        "background" itself.
        """
        mask = active_bins(getattr(obs, "spectrum_db", []))
        if mask is None:
            return
        profile = self._profile(obs, create=True)
        if profile is None or profile.frames >= self.learn_frames:
            return
        weight = 1.0 / (profile.frames + 1)
        profile.occupancy = [
            (old * profile.frames + (1.0 if flag else 0.0)) * weight
            for old, flag in zip(profile.occupancy, mask)
        ]
        profile.frames += 1
        profile.updated = time.time()
        if profile.frames % 25 == 0 or profile.frames == self.learn_frames:
            self.save()

    def observe(self, obs) -> float:
        """Return the known share of this block (read-only).

        The monitor never teaches the map.  A bin counts as known when the
        background recording saw it in at least 12% of frames — enough for a
        beaconing access point, too much for one stray burst.  The result is
        the share of *this* block's active bins that are known.
        """
        mask = active_bins(getattr(obs, "spectrum_db", []))
        if mask is None or not any(mask):
            return 0.0
        profile = self._profile(obs, create=False)
        if profile is None or profile.frames < BACKGROUND_MIN_FRAMES:
            return 0.0
        known = profile.known_bins()
        active = [index for index, flag in enumerate(mask) if flag]
        hits = sum(1 for index in active if known[index])
        return float(hits) / max(1, len(active))

    def is_background(self, fraction: float) -> bool:
        return float(fraction) >= BACKGROUND_MARK

    def band_report(self, device_id: str | None = None) -> dict[str, dict[str, int]]:
        """What the map actually contains, per band: frames and busy bins."""
        report: dict[str, dict[str, int]] = {}
        for profile in self.profiles.values():
            if device_id and profile.device_id != device_id:
                continue
            active = sum(profile.known_bins())
            row = report.setdefault(
                profile.band_key, {"frames": 0, "active": 0}
            )
            row["frames"] = max(row["frames"], int(profile.frames))
            row["active"] += active
        return report

    def reset_key(
        self,
        *,
        device_id: str,
        band_key: str,
        gain_db: float,
        sample_rate: float = 0.0,
        center_hz: float = 0.0,
    ) -> bool:
        """Forget one chunk, so a new background recording replaces it."""
        probe = SpectrumProfile(
            device_id=str(device_id),
            band_key=str(band_key),
            gain_db=float(gain_db),
            sample_rate=float(sample_rate),
            center_hz=float(center_hz),
        )
        return self.profiles.pop(probe.key, None) is not None

    def reset(self, device_id: str | None = None) -> int:
        if device_id is None:
            count = len(self.profiles)
            self.profiles = {}
        else:
            keys = [
                key for key, profile in self.profiles.items()
                if profile.device_id == device_id
            ]
            count = len(keys)
            for key in keys:
                del self.profiles[key]
        self.save()
        return count

    def ready(self, obs) -> bool:
        profile = self._profile(obs, create=False)
        return bool(profile is not None and profile.ready)
