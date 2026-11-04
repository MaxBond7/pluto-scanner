"""Adapter for the Cardinal RF (CardRF) dataset (Medaiyese et al., 2020).

CardRF is a set of 10,100 MATLAB files recorded outdoors at 2.4 GHz with an
oscilloscope: Wi-Fi access points, phones and smartwatches (Bluetooth), drone
links and drone controllers, both in line of sight and behind a building.

Layout (inside the published ``CARDRF.zip``)::

    CARDRF/LOS/{Train,Test}/{WIFI,BLUETOOTH,UAV,UAV_Controller}/<device>/...
    CARDRF/NLOS/UAV/<model>/<mode>/...

Every file holds one capture in ``Channel_1/Data`` (MATLAB v7.3, i.e. HDF5):
5,000,000 real ``int16`` samples.  The metadata gives the sample interval
``Channel_1/XInc = 5e-11 s``, so the capture rate is **20 GSa/s** and each
file lasts 250 µs.  The spectrum peaks at 0.12 of the sample rate — 2.4 GHz —
which is the ISM band itself, sampled directly, not a downconverted IF.

That short window is the one real obstacle: the rest of the project works in
20 ms blocks.  This adapter therefore

* mixes the 2.4 GHz band down to DC and keeps a slice — 4.096 MHz by default,
  the widest a Pluto over USB 2.0 can stream without dropping samples —
  giving 1,024-sample complex blocks that look like the live monitor's view;
* rebuilds 20 ms windows by concatenating 80 such blocks from the same
  folder, so the duty cycle and burst structure stay meaningful and the
  window matches DroneRF;
* caches the baseband blocks, because re-reading 71 GB of compressed MATLAB
  is slow and the archive is meant to stay untouched on disk.

Only derived feature vectors are stored in the repository; the dataset itself
stays where the user put it.  CardRF is published under CC BY 4.0.
"""
from __future__ import annotations

import argparse
import io
import zipfile
from collections import Counter, OrderedDict
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import numpy as np

from ..drone.bands import DroneBand
from ..drone.features import OVERLOAD, QUIET, analyze_iq

CARDRF_RAW_RATE = 20.0e9
CARDRF_BASEBAND_RATE = 20.0e6
CARDRF_SEARCH_HZ = (2.39e9, 2.49e9)
CARDRF_CAPTURE_S = 250e-6       # one file = 5,000,000 samples at 20 GSa/s
CARDRF_BLOCK_S = 0.02           # same 20 ms window as DroneRF and the monitor


def chunk_samples(rate: float = CARDRF_BASEBAND_RATE) -> int:
    return int(round(float(rate) * CARDRF_CAPTURE_S))


def window_samples(rate: float = CARDRF_BASEBAND_RATE) -> int:
    return int(round(float(rate) * CARDRF_BLOCK_S))


# Wi-Fi and Bluetooth are the negatives the binary model was missing.
_LABELS: dict[str, int] = {
    "wifi": 0,
    "bluetooth": 0,
    "uav": 1,
    "uav_controller": 1,
}
_SOURCES: dict[str, str] = {
    "wifi": "cardrf-wifi",
    "bluetooth": "cardrf-bluetooth",
    "uav": "cardrf-uav",
    "uav_controller": "cardrf-controller",
}


@dataclass(frozen=True)
class CardRFFile:
    """One ``.mat`` capture with the label taken from its folder."""

    entry: str          # path inside the archive, or relative to a folder
    split: str          # "Train", "Test", or "LOS"/"NLOS" when unlabelled
    category: str       # WIFI, BLUETOOTH, UAV, UAV_Controller
    group: str          # parent folder: the device / model / mode
    label: int
    source: str

    @property
    def name(self) -> str:
        return self.entry.rsplit("/", 1)[-1]


def parse_entry(entry: str) -> CardRFFile | None:
    """Turn ``CARDRF/LOS/Train/WIFI/TPLINK/wifi_1.mat`` into a labelled file.

    Files outside the documented tree (``__MACOSX`` copies, loose files) are
    ignored instead of being guessed.
    """
    text = entry.replace("\\", "/").strip("/")
    parts = text.split("/")
    if len(parts) < 5 or not parts[-1].lower().endswith(".mat"):
        return None
    if parts[0].upper() != "CARDRF":
        return None
    category_index = 3 if parts[2] in ("Train", "Test") else 2
    if len(parts) < category_index + 3:  # a device folder must follow the class
        return None
    category = parts[category_index]
    key = category.lower()
    label = _LABELS.get(key)
    if label is None:
        return None
    split = parts[2] if parts[2] in ("Train", "Test") else parts[1]
    group = "cardrf-" + "/".join(parts[1:-1])
    return CardRFFile(
        entry=text,
        split=split,
        category=category,
        group=group,
        label=label,
        source=_SOURCES[key],
    )


def scan_entries(source: str | Path) -> list[CardRFFile]:
    """List the usable ``.mat`` entries of an archive or a folder."""
    path = Path(source)
    if path.is_dir():
        names = [
            item.relative_to(path).as_posix()
            for item in sorted(path.rglob("*.mat"))
        ]
    else:
        with zipfile.ZipFile(path) as archive:
            names = [name for name in archive.namelist()
                     if name.lower().endswith(".mat")]
    found = [parse_entry(name) for name in names]
    return [item for item in found if item is not None]


# ------------------------------------------------------------------ samples
def read_samples(blob: bytes) -> np.ndarray:
    """Pull the sample vector out of one MATLAB v7.3 file."""
    import h5py

    with h5py.File(io.BytesIO(blob), "r") as handle:
        node = handle.get("Channel_1/Data")
        if node is None:
            best: str | None = None
            best_size = 0

            def visit(name: str, item: object) -> None:
                nonlocal best, best_size
                if not isinstance(item, h5py.Dataset):
                    return
                if not np.issubdtype(item.dtype, np.number):
                    return
                if item.size > best_size:
                    best, best_size = name, int(item.size)

            handle.visititems(visit)
            if best is None:
                raise ValueError("в .mat нет числового массива с отсчётами")
            node = handle[best]
        return np.asarray(node[...]).ravel()


def to_baseband(
    samples: np.ndarray,
    *,
    sample_rate: float = CARDRF_RAW_RATE,
    out_rate: float = CARDRF_BASEBAND_RATE,
    search_hz: tuple[float, float] = CARDRF_SEARCH_HZ,
    smooth_hz: float = 1.0e6,
) -> np.ndarray:
    """Move the strongest 2.4 GHz link to DC and decimate to ``out_rate``.

    The capture is real-valued at 20 GSa/s and contains the whole 2.4 GHz
    band.  Keeping a complex slice around the actual emission (found by
    locating the peak, not by assuming channel 1) gives the same 20 MHz view
    a Pluto would produce when tuned to that link.
    """
    x = np.asarray(samples, dtype=np.float64)
    if x.size < 1024:
        return np.empty(0, dtype=np.complex64)
    x = x - float(np.mean(x))
    spectrum = np.asarray(np.fft.rfft(x))
    df = float(sample_rate) / x.size
    keep = int(round(x.size * float(out_rate) / float(sample_rate)))
    if keep < 64 or keep >= spectrum.size:
        return np.empty(0, dtype=np.complex64)

    lo = int(np.clip(search_hz[0] / df, 0, spectrum.size - keep))
    hi = int(np.clip(search_hz[1] / df, lo + keep, spectrum.size))
    window = np.abs(spectrum[lo:hi])
    taps = max(1, int(round(smooth_hz / df)))
    if taps > 1 and window.size > taps:
        smoothed = np.convolve(window, np.ones(taps) / taps, mode="same")
    else:
        smoothed = window
    center = lo + int(np.argmax(smoothed))
    # A moving average pulls the maximum towards nearby weaker energy by up to
    # half its length, so the true carrier is the raw peak in that
    # neighbourhood, not the smoothed one.
    radius = max(1, taps // 2)
    left = max(lo, center - radius)
    right = min(hi, center + radius + 1)
    center = left + int(np.argmax(window[left - lo:right - lo]))
    start = int(np.clip(center - keep // 2, 0, spectrum.size - keep))
    segment = spectrum[start:start + keep]
    block = np.fft.ifft(np.fft.fftshift(segment))
    return np.ascontiguousarray(block, dtype=np.complex64)


def build_window(
    chunks: list[np.ndarray],
    rng: np.random.Generator,
    *,
    size: int = 0,
    fade: int = 16,
) -> np.ndarray:
    """Join 250 µs chunks into one 20 ms block.

    Chunks are taken in random order and trimmed with a short ramp so the
    joins do not add a periodic click every 5,000 samples: a fixed splice
    grid would put a 4 kHz comb into every spectrum.
    """
    if size <= 0:
        size = window_samples()
    order = rng.permutation(len(chunks))
    out = np.zeros(size, dtype=np.complex64)
    position = 0
    for index in order:
        chunk = np.asarray(chunks[int(index)], dtype=np.complex64)
        room = size - position
        if room <= 0:
            break
        if chunk.size > room:
            chunk = chunk[:room]
        piece = chunk.copy()
        if fade > 1 and piece.size > 2 * fade:
            ramp = np.linspace(0.0, 1.0, fade, dtype=np.float32)
            piece[:fade] *= ramp
            piece[-fade:] *= ramp[::-1]
        out[position:position + piece.size] = piece
        position += piece.size
    return out


def normalize(block: np.ndarray, peak: float = 0.25) -> np.ndarray:
    """Scale a block to a fixed peak so ``OVERLOAD`` does not fire always."""
    scale = float(np.max(np.abs(block))) if block.size else 0.0
    if scale <= 0.0:
        return block
    return (block * (float(peak) / scale)).astype(np.complex64)


def analyze_block(
    block: np.ndarray,
    rate: float = CARDRF_BASEBAND_RATE,
    *,
    nfft: int = 4096,
):
    """Run the application's own feature extractor on one window."""
    band = DroneBand(
        "cardrf", "CardRF", -0.45 * float(rate), 0.45 * float(rate),
        "adapter band", alarm=True,
    )
    return analyze_iq(
        normalize(block),
        float(rate),
        0.0,
        band,
        device_id="cardrf",
        threshold_db=6.0,
        nfft=nfft,
        notch_hz=0.0,
    )


def is_usable(observation, *, min_snr_db: float = 6.0) -> bool:
    if observation is None:
        return False
    if observation.class_key in (QUIET, OVERLOAD):
        return False
    return float(observation.snr_db) >= float(min_snr_db)


# ------------------------------------------------------------------ chunks
_STATE: dict[str, object] = {}


def _init_worker(source: str, rate: float = CARDRF_BASEBAND_RATE) -> None:
    path = Path(source)
    _STATE["rate"] = float(rate)
    if path.is_dir():
        _STATE["dir"] = path
    else:
        _STATE["zip"] = zipfile.ZipFile(path)


def _read_chunk(entry: str) -> tuple[str, np.ndarray | None]:
    try:
        archive = _STATE.get("zip")
        if archive is not None:
            blob = archive.read(entry)
        else:
            folder = Path(_STATE["dir"])  # type: ignore[arg-type]
            blob = (folder / entry).read_bytes()
        rate = float(_STATE.get("rate") or CARDRF_BASEBAND_RATE)
        chunk = to_baseband(read_samples(blob), out_rate=rate)
        return entry, chunk if chunk.size else None
    except Exception:
        return entry, None


def _evenly_spaced(items: list[CardRFFile], count: int) -> list[CardRFFile]:
    if count <= 0 or count >= len(items):
        return list(items)
    step = len(items) / float(count)
    return [items[min(len(items) - 1, int(i * step))] for i in range(count)]


def load_chunk_cache(
    path: str | Path, rate: float = CARDRF_BASEBAND_RATE,
) -> tuple[list[str], dict[str, np.ndarray]] | None:
    path = Path(path)
    if not path.exists():
        return None
    try:
        payload = np.load(path, allow_pickle=True)
        stored_rate = float(payload["rate"]) if "rate" in payload else 0.0
        entries = [str(value) for value in payload["entries"]]
        chunks = np.asarray(payload["chunks"])
    except Exception:
        return None
    if len(entries) != len(chunks):
        return None
    if stored_rate and abs(stored_rate - float(rate)) > 1.0:
        return None  # cache was built at another bandwidth
    return entries, {name: chunks[i] for i, name in enumerate(entries)}


def save_chunk_cache(
    path: str | Path,
    entries: list[str],
    chunks: dict[str, np.ndarray],
    rate: float = CARDRF_BASEBAND_RATE,
) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    ordered = [name for name in entries if name in chunks]
    if not ordered:
        raise ValueError("нет ни одного фрагмента для кэша")
    matrix = np.stack([chunks[name] for name in ordered])
    np.savez(
        path,
        rate=np.float64(rate),
        entries=np.array(ordered, dtype=object),
        chunks=matrix,
    )
    return path


def extract_chunks(
    source: str | Path,
    files: Iterable[CardRFFile],
    *,
    rate: float = CARDRF_BASEBAND_RATE,
    workers: int = 0,
    chunk_cache: str | Path = "",
    progress=None,
) -> dict[str, np.ndarray]:
    """Read every listed capture once and keep its baseband block."""
    wanted = [item.entry for item in files]
    chunks: dict[str, np.ndarray] = {}
    cached = load_chunk_cache(chunk_cache, rate) if str(chunk_cache) else None
    if cached is not None:
        _, stored = cached
        for entry in wanted:
            if entry in stored:
                chunks[entry] = stored[entry]
    missing = [entry for entry in wanted if entry not in chunks]
    if not missing:
        return chunks

    workers = int(workers) if workers else min(12, max(1, (len(missing) // 200) + 1))
    workers = max(1, min(workers, len(missing)))
    done = 0
    total = len(missing)
    if workers == 1:
        _init_worker(str(source), rate)
        for entry, chunk in (_read_chunk(name) for name in missing):
            if chunk is not None:
                chunks[entry] = chunk
            done += 1
            if progress is not None and (done % 100 == 0 or done == total):
                progress(done, total, entry)
    else:
        with ProcessPoolExecutor(
            max_workers=workers, initializer=_init_worker,
            initargs=(str(source), float(rate)),
        ) as pool:
            for entry, chunk in pool.map(_read_chunk, missing, chunksize=8):
                if chunk is not None:
                    chunks[entry] = chunk
                done += 1
                if progress is not None and (done % 100 == 0 or done == total):
                    progress(done, total, entry)
    if str(chunk_cache):
        save_chunk_cache(chunk_cache, wanted, chunks, rate)
    return chunks


# ---------------------------------------------------------------- dataset
def collect_cardrf(
    source: str | Path,
    *,
    split: str = "Train",
    baseband_rate: float = CARDRF_BASEBAND_RATE,
    windows_per_group: int = 6,
    limit_per_group: int = 0,
    negatives_only: bool = False,
    workers: int = 0,
    chunk_cache: str | Path = "",
    nfft: int = 4096,
    seed: int = 11,
    progress=None,
):
    """Build the binary dataset from CardRF negatives and drone links.

    ``negatives_only`` keeps just Wi-Fi and Bluetooth.  CardRF records each
    drone capture in the middle of a transmission and lasts 250 µs, so its
    drone windows come out continuous, while DroneRF drone windows are gated.
    Mixing the two contradictions costs more recall than the extra negatives
    are worth, so the default use of this dataset is "negatives only".
    """
    from .dronerf import BinaryDataset
    from .binary_features import BINARY_FEATURE_NAMES, from_observation
    from .binary import BACKGROUND, DRONE

    rate = float(baseband_rate)
    files = [
        item for item in scan_entries(source)
        if split == "all" or item.split.lower() == split.lower()
    ]
    if negatives_only:
        files = [item for item in files if item.label == 0]
    if not files:
        raise FileNotFoundError(f"в {source} не найдено файлов CardRF")

    grouped: "OrderedDict[str, list[CardRFFile]]" = OrderedDict()
    for item in files:
        grouped.setdefault(item.group, []).append(item)

    if progress is not None:
        progress(0, len(files), "чтение фрагментов")

    chunks = extract_chunks(
        source,
        [item for group in grouped.values() for item in group],
        rate=rate,
        workers=workers,
        chunk_cache=chunk_cache,
        progress=progress,
    )
    usable_groups = {
        name: [chunks[item.entry] for item in _evenly_spaced(items, limit_per_group)
               if item.entry in chunks]
        for name, items in grouped.items()
    }
    usable_groups = {name: values for name, values in usable_groups.items() if values}

    rng = np.random.default_rng(seed)
    data = BinaryDataset(
        X=np.empty((0, len(BINARY_FEATURE_NAMES)), dtype=np.float64),
        y=[], groups=[], sources=[], snr=np.empty(0), meta=[],
    )
    need = max(1, int(round(window_samples(rate) / max(1, chunk_samples(rate)))))
    for name, group_chunks in usable_groups.items():
        sample = next(item for item in grouped[name] if item.entry in chunks)
        for _ in range(max(1, int(windows_per_group))):
            if len(group_chunks) >= need:
                picked = rng.choice(len(group_chunks), size=need, replace=False)
                chosen = [group_chunks[int(index)] for index in picked]
            else:
                chosen = [group_chunks[int(index)]
                          for index in rng.integers(0, len(group_chunks), size=need)]
            block = build_window(chosen, rng, size=window_samples(rate))
            observation = analyze_block(block, rate, nfft=nfft)
            if not is_usable(observation):
                continue
            data.X = np.vstack([data.X, from_observation(observation)[None, :]])
            data.y.append(DRONE if sample.label else BACKGROUND)
            data.groups.append(name)
            data.sources.append(sample.source)
            data.snr = np.append(data.snr, float(observation.snr_db))
            data.meta.append({
                "class_key": observation.class_key,
                "snr_db": round(float(observation.snr_db), 2),
                "duty": round(float(observation.active_fraction), 3),
            })
    return data


# ---------------------------------------------------------------------- CLI
def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Read CardRF captures and cache their baseband blocks.",
    )
    parser.add_argument("--source", required=True,
                        help="CARDRF.zip or a folder with the .mat files")
    parser.add_argument("--chunk-cache", default="",
                        help="where to store the baseband blocks (.npz)")
    parser.add_argument("--rate", type=float, default=CARDRF_BASEBAND_RATE,
                        help="baseband sample rate in Hz (default 20 MHz)")
    parser.add_argument("--split", default="Train")
    parser.add_argument("--workers", type=int, default=0)
    parser.add_argument("--limit", type=int, default=0,
                        help="captures per folder; 0 means all")
    parser.add_argument("--list", action="store_true",
                        help="only print counts and exit")
    args = parser.parse_args(argv)

    files = [item for item in scan_entries(args.source)
             if args.split == "all" or item.split.lower() == args.split.lower()]
    counts = Counter((item.split, item.category) for item in files)
    print(f"файлов: {len(files)}")
    for (split, category), count in sorted(counts.items()):
        print(f"  {split:6s} {category:15s} {count}")
    groups = Counter(item.group for item in files)
    print(f"папок (групп): {len(groups)}")
    if args.list:
        return 0

    chosen: list[CardRFFile] = []
    for name, items in sorted(groups.items()):
        subset = [item for item in items][: max(0, args.limit) or len(items)]
        chosen.extend(subset)
    print(f"читать: {len(chosen)}")

    chunks = extract_chunks(
        args.source, chosen,
        rate=args.rate,
        workers=args.workers,
        chunk_cache=args.chunk_cache,
        progress=lambda i, n, name: print(f"  [{i}/{n}] {name}", flush=True)
        if i % 200 == 0 or i == n else None,
    )
    print(f"фрагментов: {len(chunks)}")
    if chunks:
        sample = next(iter(chunks.values()))
        print(f"длина фрагмента: {sample.size} отсчётов "
              f"({sample.size / args.rate * 1e3:.3f} мс)")
    if args.chunk_cache:
        print(f"кэш: {args.chunk_cache}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
