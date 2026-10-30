"""Persist a band sweep: per-step JSON files plus one background bundle.

Layout::

    scan_logs/
      scan_20261026_153012/
        step_00000.json
        step_00001.json
        ...
        background.json      <- reference for future comparisons
        compare.json         <- written when an older background was found

The bundle is deliberately plain JSON (no numpy) so it can be inspected,
archived and compared by any tool.  The per-step spectrum is decimated for
readability; peak frequencies keep the full FFT resolution.
"""
from __future__ import annotations

import json
import math
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np

from ..model import Detection
from .peaks import decimate_mean

SCAN_VERSION = 2
BUNDLE_BINS = 8192
STEP_BINS = 512


def make_scan_id(now: float | None = None) -> str:
    stamp = time.localtime(time.time() if now is None else now)
    return time.strftime("%Y%m%d_%H%M%S", stamp)


def _r(value: float, digits: int = 3) -> float:
    value = float(value)
    if not math.isfinite(value):
        return -200.0
    return round(value, digits)


def _r_list(values: Iterable[float], digits: int = 3) -> list[float]:
    return [_r(v, digits) for v in values]


def peak_to_dict(
    peak: Detection,
    *,
    step_index: int,
    center_hz: float,
    noise_floor_db: float,
) -> dict[str, Any]:
    return {
        "freq_hz": _r(peak.freq_hz, 1),
        "bw_hz": _r(peak.bw_hz, 1),
        "peak_db": _r(peak.peak_db, 2),
        "snr_db": _r(peak.snr_db, 2),
        "mean_snr_db": _r(peak.mean_snr_db, 2),
        "type": peak.type.value,
        "type_ru": peak.type.ru,
        "confidence": _r(peak.confidence, 3),
        "step_index": int(step_index),
        "center_hz": _r(center_hz, 1),
        "noise_floor_db": _r(noise_floor_db, 2),
    }


class ScanRecorder:
    """Accumulates steps and writes the background bundle."""

    def __init__(
        self,
        out_dir: str | Path,
        *,
        scan_id: str,
        range_start_hz: float,
        range_end_hz: float,
        step_hz: float,
        sample_rate: float,
        fft_size: int,
        threshold_db: float,
        dwell_frames: int,
        device_name: str = "",
        device_kind: str = "",
        device_uri: str = "",
        gain_db: float = 0.0,
        bandwidth_hz: float = 0.0,
    ) -> None:
        self.out_dir = Path(out_dir)
        self.out_dir.mkdir(parents=True, exist_ok=True)
        self.scan_id = scan_id
        self.range_start_hz = float(range_start_hz)
        self.range_end_hz = float(range_end_hz)
        self.step_hz = float(step_hz)
        self.sample_rate = float(sample_rate)
        self.fft_size = int(fft_size)
        self.threshold_db = float(threshold_db)
        self.dwell_frames = int(dwell_frames)
        self.device_name = str(device_name)
        self.device_kind = str(device_kind)
        self.device_uri = str(device_uri)
        self.gain_db = float(gain_db)
        self.bandwidth_hz = float(bandwidth_hz)
        self.started = time.time()
        self.finished: float | None = None

        self._max_hold = np.full(BUNDLE_BINS, -np.inf, dtype=np.float64)
        self._sum = np.zeros(BUNDLE_BINS, dtype=np.float64)
        self._count = np.zeros(BUNDLE_BINS, dtype=np.int32)
        self._noise_floors: list[float] = []

        self.steps: list[dict[str, Any]] = []
        self.peaks: list[dict[str, Any]] = []
        self.files: list[str] = []

    # ------------------------------------------------------------------ public
    @property
    def completed(self) -> int:
        return sum(1 for step in self.steps if step.get("status") == "ok")

    @property
    def missed(self) -> int:
        return sum(1 for step in self.steps if step.get("status") != "ok")

    @property
    def peak_count(self) -> int:
        return len(self.peaks)

    def add_step(
        self,
        *,
        index: int,
        center_hz: float,
        freqs: np.ndarray,
        psd: np.ndarray,
        noise_floor_db: float,
        peaks: list[Detection],
        status: str = "ok",
        dwell_frames: int = 0,
    ) -> dict[str, Any]:
        freqs = np.asarray(freqs, dtype=np.float64)
        psd = np.asarray(psd, dtype=np.float64)
        step_peaks = [
            peak_to_dict(
                peak,
                step_index=index,
                center_hz=center_hz,
                noise_floor_db=noise_floor_db,
            )
            for peak in peaks
        ]
        spectrum_db = decimate_mean(psd, STEP_BINS) if psd.size else np.empty(0)
        record: dict[str, Any] = {
            "scan_version": SCAN_VERSION,
            "scan_id": self.scan_id,
            "step_index": int(index),
            "center_hz": _r(center_hz, 1),
            "freq_start_hz": _r(freqs[0], 1) if freqs.size else _r(center_hz, 1),
            "freq_end_hz": _r(freqs[-1], 1) if freqs.size else _r(center_hz, 1),
            "sample_rate": _r(self.sample_rate, 1),
            "fft_size": self.fft_size,
            "timestamp": round(time.time(), 3),
            "dwell_frames": int(dwell_frames),
            "noise_floor_db": _r(noise_floor_db, 2),
            "threshold_db": _r(self.threshold_db, 2),
            "status": status,
            "spectrum": {
                "bins": int(spectrum_db.size),
                "freq_start_hz": _r(freqs[0], 1) if freqs.size else _r(center_hz, 1),
                "freq_end_hz": _r(freqs[-1], 1) if freqs.size else _r(center_hz, 1),
                "psd_db": _r_list(spectrum_db, 2),
            },
            "peaks": step_peaks,
        }
        fname = f"step_{index:05d}.json"
        (self.out_dir / fname).write_text(
            json.dumps(record, ensure_ascii=False), encoding="utf-8"
        )
        self.files.append(fname)

        self.steps.append({
            "step_index": int(index),
            "center_hz": _r(center_hz, 1),
            "noise_floor_db": _r(noise_floor_db, 2),
            "peaks": len(step_peaks),
            "status": status,
            "file": fname,
        })
        self.peaks.extend(step_peaks)
        if math.isfinite(noise_floor_db):
            self._noise_floors.append(float(noise_floor_db))

        if status == "ok" and freqs.size and psd.size:
            self._update_spectrum(freqs, psd)
        return record

    def add_missed(
        self, *, index: int, center_hz: float, status: str = "missed"
    ) -> dict[str, Any]:
        record: dict[str, Any] = {
            "scan_version": SCAN_VERSION,
            "scan_id": self.scan_id,
            "step_index": int(index),
            "center_hz": _r(center_hz, 1),
            "status": status,
            "noise_floor_db": None,
            "spectrum": {"bins": 0, "psd_db": []},
            "peaks": [],
        }
        self.steps.append({
            "step_index": int(index),
            "center_hz": _r(center_hz, 1),
            "noise_floor_db": None,
            "peaks": 0,
            "status": status,
            "file": None,
        })
        return record

    def finalize(self, *, stopped: bool = False) -> tuple[dict[str, Any], Path]:
        self.finished = time.time()
        duration = max(0.0, self.finished - self.started)
        noise_median = (
            float(np.median(self._noise_floors)) if self._noise_floors
            else -200.0
        )
        fill = noise_median if math.isfinite(noise_median) else -200.0
        max_hold = np.where(
            np.isfinite(self._max_hold), self._max_hold, fill
        )
        mean = np.divide(
            self._sum,
            self._count,
            out=np.full(BUNDLE_BINS, fill, dtype=np.float64),
            where=self._count > 0,
        )
        bundle: dict[str, Any] = {
            "scan_version": SCAN_VERSION,
            "scan_id": self.scan_id,
            "created": round(self.started, 3),
            "finished": round(self.finished, 3),
            "duration_s": round(duration, 3),
            "complete": not stopped,
            "stopped": bool(stopped),
            "range_start_hz": _r(self.range_start_hz, 1),
            "range_end_hz": _r(self.range_end_hz, 1),
            "step_hz": _r(self.step_hz, 1),
            "sample_rate": _r(self.sample_rate, 1),
            "fft_size": self.fft_size,
            "threshold_db": _r(self.threshold_db, 2),
            "dwell_frames": self.dwell_frames,
            "device": {
                "name": self.device_name,
                "kind": self.device_kind,
                "uri": self.device_uri,
                "gain_db": _r(self.gain_db, 2),
                "bandwidth_hz": _r(self.bandwidth_hz, 1),
            },
            "steps_total": len(self.steps),
            "steps_completed": self.completed,
            "steps_missed": self.missed,
            "noise_floor_db_median": _r(noise_median, 2),
            "peak_count": len(self.peaks),
            "peaks": self.peaks,
            "steps": self.steps,
            "files": self.files,
            "spectrum": {
                "bins": BUNDLE_BINS,
                "freq_start_hz": _r(self.range_start_hz, 1),
                "freq_end_hz": _r(self.range_end_hz, 1),
                "max_hold_db": _r_list(max_hold, 2),
                "mean_db": _r_list(mean, 2),
                "coverage": [int(v) for v in self._count],
            },
        }
        path = self.out_dir / "background.json"
        path.write_text(
            json.dumps(bundle, ensure_ascii=False), encoding="utf-8"
        )
        return bundle, path.resolve()

    # ----------------------------------------------------------------- private
    def _update_spectrum(self, freqs: np.ndarray, psd: np.ndarray) -> None:
        span = self.range_end_hz - self.range_start_hz
        if span <= 0:
            return
        idx = np.rint(
            (freqs - self.range_start_hz) / span * (BUNDLE_BINS - 1)
        ).astype(np.int64)
        valid = (idx >= 0) & (idx < BUNDLE_BINS)
        if not valid.any():
            return
        idx = idx[valid]
        values = psd[valid]
        np.maximum.at(self._max_hold, idx, values)
        np.add.at(self._sum, idx, values)
        np.add.at(self._count, idx, 1)


# --------------------------------------------------------------------- loading
def find_latest_background(
    root: str | Path = "scan_logs",
    *,
    exclude: str | Path | None = None,
) -> Path | None:
    """Return the newest background bundle (new layout or old flat files)."""
    root = Path(root)
    if not root.exists():
        return None
    exclude_path = Path(exclude).resolve() if exclude else None
    candidates = list(root.glob("scan_*/background.json"))
    candidates.extend(root.glob("scan_background_*.json"))
    found: list[Path] = []
    for item in candidates:
        try:
            if exclude_path is not None and item.resolve() == exclude_path:
                continue
            if item.is_file():
                found.append(item)
        except OSError:
            continue
    if not found:
        return None
    found.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return found[0]


def load_bundle(path: str | Path) -> dict[str, Any]:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"not a scan bundle: {path}")
    return data


def ranges_overlap(first: dict[str, Any], second: dict[str, Any]) -> bool:
    try:
        a0 = float(first["range_start_hz"])
        a1 = float(first["range_end_hz"])
        b0 = float(second["range_start_hz"])
        b1 = float(second["range_end_hz"])
    except (KeyError, TypeError, ValueError):
        return False
    return min(a1, b1) > max(a0, b0)
