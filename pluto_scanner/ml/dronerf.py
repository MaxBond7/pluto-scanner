"""Adapter for the DroneRF dataset (Al-Sa'd et al., 2019, CC BY 4.0).

The dataset ships one recording per CSV file: a single line of 10,000,000
real ADC samples at 40 MS/s (250 ms).  Files come in ``L``/``H`` pairs that
cover two adjacent 20 MHz slices of the 2.4 GHz band; the drone link may be
in either slice, so both are used.

Every 800,000-sample window (20 ms) is converted into a complex baseband
block at 20 MS/s, so it looks exactly like one block the Pluto drone monitor
sees:

* take the one-sided spectrum of the real window (0..20 MHz),
* shift it down by 10 MHz,
* inverse-transform to a 400,000-sample complex signal.

This is mathematically the analytic signal shifted to baseband, but it needs
one ``rfft`` and one ``ifft`` instead of a Hilbert transform plus a resampling
filter.

Nothing here is bundled with the application; the raw data stays on disk and
only derived feature vectors are cached.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from ..drone.bands import DroneBand
from ..drone.features import OVERLOAD, QUIET, analyze_iq
from .features import feature_vector

DRONERF_SAMPLE_RATE = 40.0e6
DRONERF_SAMPLES_PER_FILE = 10_000_000
DRONERF_WINDOW = 800_000          # 20 ms at 40 MS/s -> 400k complex at 20 MS/s
DRONERF_BASEBAND_RATE = 20.0e6

BACKGROUND = "00000"

FAMILY_BY_BUI: dict[str, str] = {
    "00000": "background",
    "10000": "bebop",
    "10001": "bebop",
    "10010": "bebop",
    "10011": "bebop",
    "10100": "ar",
    "10101": "ar",
    "10110": "ar",
    "10111": "ar",
    "11000": "phantom",
}

# The paper documents four Bebop and four AR modes and one Phantom mode.
# File names only carry the BUI code, so the mode is kept as its ordinal
# within the family rather than guessed from an undocumented order.
_NAME_RE = re.compile(r"^(\d{5})([LH])_(\d+)\.csv$", re.IGNORECASE)

_ANALYSIS_BAND = DroneBand(
    "dronerf", "DroneRF", -9.0e6, 9.0e6, "adapter band", alarm=True,
)


@dataclass(frozen=True)
class DroneRFRecording:
    path: Path
    bui: str
    channel: str
    index: int

    @property
    def family(self) -> str:
        return FAMILY_BY_BUI.get(self.bui, "unknown")

    @property
    def is_background(self) -> bool:
        return self.bui == BACKGROUND

    @property
    def group(self) -> str:
        """Recording session group used for leakage-free splits."""
        return f"{self.bui}{self.channel}"

    @property
    def key(self) -> str:
        return f"{self.bui}{self.channel}_{self.index}"


def scan_recordings(root: str | Path) -> list[DroneRFRecording]:
    """Find every ``<BUI><L|H>_<n>.csv`` file below ``root``."""
    root = Path(root)
    if not root.exists():
        raise FileNotFoundError(f"DroneRF folder not found: {root}")
    found: list[DroneRFRecording] = []
    for path in sorted(root.rglob("*.csv")):
        match = _NAME_RE.match(path.name)
        if not match:
            continue
        found.append(DroneRFRecording(
            path=path,
            bui=match.group(1),
            channel=match.group(2).upper(),
            index=int(match.group(3)),
        ))
    return found


def read_window(
    path: str | Path,
    start_sample: int,
    count: int,
    *,
    total_samples: int = DRONERF_SAMPLES_PER_FILE,
) -> np.ndarray:
    """Read ``count`` real samples starting near ``start_sample``.

    The CSV is a single line, so the byte offset is estimated from the average
    bytes per sample and then aligned to the nearest comma.  The returned array
    may start a few samples later than requested and can be shorter at the end
    of the file; callers only need a full window, not exact alignment.
    """
    path = Path(path)
    count = max(1, int(count))
    size = path.stat().st_size
    per_sample = size / float(max(1, int(total_samples)))
    offset = max(0, min(size - 1, int(start_sample * per_sample)))
    want = int(count * per_sample) + 16384
    with path.open("rb") as handle:
        handle.seek(offset)
        raw = handle.read(want)
    if offset > 0:
        cut = raw.find(b",")
        if cut < 0:
            return np.empty(0, dtype=np.float64)
        raw = raw[cut + 1:]
    end = raw.rfind(b",")
    if end > 0:
        raw = raw[:end]
    if not raw:
        return np.empty(0, dtype=np.float64)
    values = np.fromstring(raw.decode("ascii", errors="ignore"),
                           dtype=np.float64, sep=",")
    return values[:count]


def to_baseband(window: np.ndarray) -> np.ndarray:
    """Convert a real 40 MS/s window to complex baseband at 20 MS/s."""
    x = np.asarray(window, dtype=np.float64)
    if x.size < 1024:
        return np.empty(0, dtype=np.complex64)
    x = x - float(np.mean(x))
    half = x.size // 2
    spectrum = np.fft.rfft(x)[:half]
    if spectrum.size < 64:
        return np.empty(0, dtype=np.complex64)
    shifted = np.fft.fftshift(spectrum)
    return np.fft.ifft(shifted).astype(np.complex64)


def iter_windows(
    recording: DroneRFRecording,
    *,
    chunks: int = 4,
    window: int = DRONERF_WINDOW,
    total_samples: int = DRONERF_SAMPLES_PER_FILE,
) -> Iterator[np.ndarray]:
    """Yield up to ``chunks`` evenly spread baseband windows of one recording."""
    chunks = max(1, int(chunks))
    window = max(4096, int(window))
    usable = int(total_samples) - window
    if usable <= 0:
        starts = [0]
    else:
        step = usable // max(1, chunks - 1) if chunks > 1 else 0
        starts = [min(usable, i * step) for i in range(chunks)]
    for start in starts:
        raw = read_window(
            recording.path, start, window, total_samples=total_samples,
        )
        if raw.size < window:
            continue
        block = to_baseband(raw)
        if block.size:
            yield block


def normalize(block: np.ndarray, peak: float = 0.25) -> np.ndarray:
    """Scale a block to a fixed peak amplitude.

    DroneRF stores raw ADC counts, so the absolute level has nothing to do
    with dBFS and the ``OVERLOAD`` rule would fire on every strong signal.
    All features are relative, but the overload decision is not, so the block
    is normalised before analysis.
    """
    scale = float(np.max(np.abs(block))) if block.size else 0.0
    if scale <= 0.0:
        return block
    return (block * (float(peak) / scale)).astype(np.complex64)


def analyze_window(
    block: np.ndarray,
    *,
    threshold_db: float = 6.0,
    nfft: int = 4096,
):
    """Run the application's own feature extractor on one window."""
    return analyze_iq(
        normalize(block),
        DRONERF_BASEBAND_RATE,
        0.0,
        _ANALYSIS_BAND,
        device_id="dronerf",
        threshold_db=threshold_db,
        nfft=nfft,
        notch_hz=0.0,
    )


def is_usable(observation, *, min_snr_db: float = 6.0) -> bool:
    """Reject empty and saturated blocks: they carry no class information."""
    if observation is None:
        return False
    if observation.class_key in (QUIET, OVERLOAD):
        return False
    return float(observation.snr_db) >= min_snr_db


def mix_noise(
    iq: np.ndarray,
    snr_db: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Add complex Gaussian noise so total block SNR becomes ``snr_db``."""
    power = float(np.mean(np.abs(iq) ** 2))
    if power <= 0.0:
        return iq
    noise_power = power / (10.0 ** (float(snr_db) / 10.0))
    sigma = np.sqrt(noise_power / 2.0)
    noise = sigma * (
        rng.normal(size=iq.size).astype(np.float64)
        + 1j * rng.normal(size=iq.size).astype(np.float64)
    )
    return (iq.astype(np.complex128) + noise).astype(np.complex64)


@dataclass
class BinaryDataset:
    X: np.ndarray
    y: list[str]
    groups: list[str]
    sources: list[str]
    snr: np.ndarray
    meta: list[dict]

    def __len__(self) -> int:
        return len(self.y)


def _features(observation) -> np.ndarray:
    return feature_vector(observation)
