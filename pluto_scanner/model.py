"""Shared data model for the scanner."""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any

import numpy as np


class SignalType(str, Enum):
    AM = "AM"
    FM = "FM"
    SSB = "SSB"
    CW = "CW"
    DIGITAL = "DIGITAL"
    BROADCAST = "BROADCAST"
    RADAR = "RADAR"
    NOISE = "NOISE"
    UNKNOWN = "UNKNOWN"

    @property
    def ru(self) -> str:
        return {
            SignalType.AM: "AM",
            SignalType.FM: "FM",
            SignalType.SSB: "SSB",
            SignalType.CW: "CW",
            SignalType.DIGITAL: "ЦИФРА",
            SignalType.BROADCAST: "ВЕЩАНИЕ",
            SignalType.RADAR: "ИМПУЛЬС",
            SignalType.NOISE: "ШУМ",
            SignalType.UNKNOWN: "НЕИЗВ.",
        }[self]


@dataclass
class DeviceConfig:
    device_id: str
    name: str
    kind: str                       # "sim" | "pluto" | "iqfile"
    uri: str = ""
    center_freq: float = 433.92e6
    sample_rate: float = 1.024e6
    bandwidth: float = 1.0e6
    gain: float = 40.0
    fft_size: int = 2048
    seed: int = 1

    def copy(self) -> "DeviceConfig":
        return DeviceConfig(**self.__dict__)


@dataclass
class VFOConfig:
    offset_hz: float = 0.0
    mode: str = "FM"                # AM | FM | SSB | CW
    bandwidth_hz: float = 200e3
    volume: float = 0.7
    squelch_db: float = -85.0
    active: bool = True

    def copy(self) -> "VFOConfig":
        return VFOConfig(**self.__dict__)


@dataclass
class IQBlock:
    device_id: str
    samples: np.ndarray
    sample_rate: float
    center_freq: float
    timestamp: float


@dataclass
class Detection:
    freq_hz: float
    bw_hz: float
    peak_db: float
    snr_db: float
    mean_snr_db: float
    bin_start: int
    bin_end: int
    bin_hz: float
    region_db: np.ndarray = field(default_factory=lambda: np.empty(0), repr=False)
    baseline_db: np.ndarray = field(default_factory=lambda: np.empty(0), repr=False)
    type: SignalType = SignalType.UNKNOWN
    confidence: float = 0.0
    alternatives: list[tuple[SignalType, float]] = field(default_factory=list)


@dataclass
class Contact:
    contact_id: str
    device_id: str
    freq_hz: float
    bw_hz: float
    type: SignalType
    confidence: float
    first_seen: float
    last_seen: float
    hits: int
    misses: int
    max_snr_db: float
    last_snr_db: float
    known: bool = False
    active: bool = True
    alternatives: list[tuple[SignalType, float]] = field(default_factory=list)

    @property
    def age_s(self) -> float:
        return max(0.0, time.time() - self.first_seen)

    @property
    def last_heard_s(self) -> float:
        return max(0.0, time.time() - self.last_seen)

    def is_new(self, window_s: float = 60.0) -> bool:
        return (not self.known) and (time.time() - self.first_seen <= window_s)

    @property
    def short_id(self) -> str:
        return self.contact_id.rsplit("-", 1)[-1]


@dataclass
class SpectrumFrame:
    device_id: str
    freqs: np.ndarray
    psd: np.ndarray
    baseline: np.ndarray | None
    detections: list[Detection]
    contacts: list[Contact]
    center_freq: float
    sample_rate: float
    timestamp: float
    calibrated: bool
    calibration_progress: float
    fps: float = 0.0
    audio_level_db: float = -120.0
    extra: dict[str, Any] = field(default_factory=dict)

    @property
    def span_hz(self) -> float:
        return float(self.freqs[-1] - self.freqs[0]) if len(self.freqs) else 0.0

    @property
    def freq_min(self) -> float:
        return float(self.freqs[0]) if len(self.freqs) else 0.0

    @property
    def freq_max(self) -> float:
        return float(self.freqs[-1]) if len(self.freqs) else 0.0
