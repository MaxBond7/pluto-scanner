"""Drone-band definitions and fast sweep chunking.

The drone monitor is deliberately *not* a full-range scan.  It watches a
small set of bands where drone control, telemetry and video links live, using
a wide instantaneous bandwidth and a short dwell time.

The chunking below uses only a part of the captured band (``fill``) so the
AD936x FIR/analog filter roll-off and the PSD edges do not hide a signal.
Chunks overlap slightly, so a carrier on a chunk boundary is still seen.
"""
from __future__ import annotations

import math
from dataclasses import dataclass


@dataclass(frozen=True)
class DroneBand:
    key: str
    name: str
    start_hz: float
    end_hz: float
    description: str = ""
    requires_extended: bool = False
    alarm: bool = True
    color: str = "#22d3ee"

    @property
    def width_hz(self) -> float:
        return max(0.0, self.end_hz - self.start_hz)

    @property
    def center_hz(self) -> float:
        return (self.start_hz + self.end_hz) / 2.0


DRONE_BANDS: list[DroneBand] = [
    DroneBand(
        "433", "433 МГц", 433.05e6, 434.79e6,
        "Пульты, телеметрия, LPD/ISM", color="#f59e0b",
    ),
    DroneBand(
        "868", "868 МГц", 863.0e6, 870.0e6,
        "EU ISM: телеметрия и пульты", color="#fbbf24",
    ),
    DroneBand(
        "915", "915 МГц", 902.0e6, 928.0e6,
        "US ISM: телеметрия и пульты", color="#f97316",
    ),
    DroneBand(
        "1.2", "1.2–1.3 ГГц", 1080.0e6, 1320.0e6,
        "Аналоговое и цифровое видео", color="#a78bfa",
    ),
    DroneBand(
        "2.4", "2.4 ГГц", 2400.0e6, 2483.5e6,
        "Управление, видео, Wi-Fi", color="#22d3ee",
    ),
    DroneBand(
        "5.8", "5.8 ГГц", 5725.0e6, 5875.0e6,
        "FPV-видео и часть управления; нужен Pluto+ / расширенный диапазон",
        requires_extended=True, color="#f472b6",
    ),
]

BANDS_BY_KEY = {band.key: band for band in DRONE_BANDS}


@dataclass(frozen=True)
class MonitorChunk:
    band: DroneBand
    center_hz: float
    start_hz: float
    end_hz: float
    index: int
    total: int

    @property
    def span_hz(self) -> float:
        return max(0.0, self.end_hz - self.start_hz)


def chunks_for_band(
    band: DroneBand,
    sample_rate: float,
    *,
    fill: float = 0.80,
    overlap: float = 0.15,
) -> list[MonitorChunk]:
    """Split ``band`` into LO centres that cover it without gaps.

    ``fill`` is the fraction of the sample rate actually used.  At 20.48 MS/s
    a chunk is therefore about 16.4 MHz wide.  ``overlap`` is the fraction of
    a chunk shared with the next one.
    """
    sample_rate = max(1.0, float(sample_rate))
    start = float(min(band.start_hz, band.end_hz))
    end = float(max(band.start_hz, band.end_hz))
    width = max(0.0, end - start)
    usable = min(width, sample_rate * max(0.2, min(0.95, fill)))
    if usable <= 0.0:
        return []

    if width <= usable + 1.0:
        centers = [(start + end) / 2.0]
    else:
        step = max(1.0, usable * (1.0 - max(0.0, min(0.8, overlap))))
        count = int(math.ceil((width - usable) / step)) + 1
        first = start + usable / 2.0
        last = end - usable / 2.0
        centers = [first + i * step for i in range(count)]
        if centers[-1] > last:
            centers[-1] = last
        # Keep the list strictly increasing even for degenerate parameters.
        cleaned: list[float] = []
        for center in centers:
            center = min(max(center, first), last)
            if not cleaned or center - cleaned[-1] > 1.0:
                cleaned.append(center)
        centers = cleaned

    total = len(centers)
    chunks: list[MonitorChunk] = []
    for index, center in enumerate(centers):
        chunks.append(MonitorChunk(
            band=band,
            center_hz=float(center),
            start_hz=float(center - usable / 2.0),
            end_hz=float(center + usable / 2.0),
            index=index,
            total=total,
        ))
    return chunks


def chunks_for_bands(
    bands: list[DroneBand],
    sample_rate: float,
    *,
    fill: float = 0.80,
    overlap: float = 0.15,
) -> list[MonitorChunk]:
    chunks: list[MonitorChunk] = []
    for band in bands:
        chunks.extend(chunks_for_band(
            band, sample_rate, fill=fill, overlap=overlap
        ))
    return chunks


def selected_bands(keys: list[str] | tuple[str, ...] | set[str]) -> list[DroneBand]:
    wanted = set(keys)
    return [band for band in DRONE_BANDS if band.key in wanted]


def band_names(keys: list[str] | tuple[str, ...] | set[str]) -> str:
    bands = selected_bands(keys)
    return ", ".join(band.name for band in bands) if bands else "—"
