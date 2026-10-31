"""Long IQ recordings: cf32 storage, metadata and safe background writing.

A recording is a pair of files in ``iq_recordings/``:

    iq_20261031_120000.cf32   raw complex64 interleaved I/Q, little-endian
    iq_20261031_120000.json   frequency, sample rate, size and status

The writer runs in its own thread so a slow disk cannot stall the Qt event
loop.  If the bounded queue overflows, samples are dropped and the metadata
records how many, instead of silently pretending the recording is complete.
"""
from __future__ import annotations

import json
import queue
import shutil
import threading
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Iterator

import numpy as np

from .model import IQBlock
from .paths import RECORDINGS_DIR

CF32 = "cf32"
QUEUE_BLOCKS = 32
MIN_FREE_BYTES = 64 * 1024 * 1024


def estimated_bytes(sample_rate: float, seconds: float) -> int:
    """Raw cf32 size for a recording of *seconds* at *sample_rate*."""
    return int(max(0.0, float(sample_rate)) * max(0.0, float(seconds)) * 8.0)


def format_size(num_bytes: float) -> str:
    value = float(max(0, num_bytes))
    for unit in ("Б", "КБ", "МБ", "ГБ"):
        if value < 1024.0 or unit == "ГБ":
            if unit == "Б":
                return f"{int(value)} {unit}"
            return f"{value:.1f} {unit}"
        value /= 1024.0
    return f"{value:.1f} ГБ"


@dataclass
class RecordingInfo:
    recording_id: str
    device_id: str
    device_name: str
    device_kind: str
    cf32_path: str
    meta_path: str
    created: float
    sample_rate: float
    center_freq: float
    gain_db: float = 0.0
    bandwidth_hz: float = 0.0
    samples: int = 0
    dropped_samples: int = 0
    complete: bool = False
    error: str = ""
    notes: str = ""
    label: str = ""
    format: str = CF32

    @property
    def path(self) -> Path:
        return Path(self.cf32_path)

    @property
    def meta(self) -> Path:
        return Path(self.meta_path)

    @property
    def duration_s(self) -> float:
        if self.sample_rate > 0:
            return float(self.samples) / float(self.sample_rate)
        return 0.0

    @property
    def size_bytes(self) -> int:
        try:
            return self.path.stat().st_size
        except OSError:
            return 0

    @property
    def exists(self) -> bool:
        return self.path.exists()

    def to_dict(self) -> dict:
        return {
            "version": 1,
            "recording_id": self.recording_id,
            "device_id": self.device_id,
            "device_name": self.device_name,
            "device_kind": self.device_kind,
            "cf32": self.path.name,
            "created": round(float(self.created), 3),
            "sample_rate": float(self.sample_rate),
            "center_freq": float(self.center_freq),
            "gain_db": float(self.gain_db),
            "bandwidth_hz": float(self.bandwidth_hz),
            "samples": int(self.samples),
            "dropped_samples": int(self.dropped_samples),
            "complete": bool(self.complete),
            "error": self.error,
            "notes": self.notes,
            "label": self.label,
            "format": self.format,
        }

    @classmethod
    def from_dict(cls, data: dict, meta_path: Path) -> "RecordingInfo":
        cf32_name = str(data.get("cf32") or "")
        cf32_path = (
            Path(cf32_name)
            if cf32_name and Path(cf32_name).is_absolute()
            else meta_path.parent / cf32_name
        )
        return cls(
            recording_id=str(data.get("recording_id") or meta_path.stem),
            device_id=str(data.get("device_id") or ""),
            device_name=str(data.get("device_name") or "запись"),
            device_kind=str(data.get("device_kind") or ""),
            cf32_path=str(cf32_path),
            meta_path=str(meta_path),
            created=float(data.get("created") or 0.0),
            sample_rate=float(data.get("sample_rate") or 0.0),
            center_freq=float(data.get("center_freq") or 0.0),
            gain_db=float(data.get("gain_db") or 0.0),
            bandwidth_hz=float(data.get("bandwidth_hz") or 0.0),
            samples=int(data.get("samples") or 0),
            dropped_samples=int(data.get("dropped_samples") or 0),
            complete=bool(data.get("complete")),
            error=str(data.get("error") or ""),
            notes=str(data.get("notes") or ""),
            label=str(data.get("label") or ""),
            format=str(data.get("format") or CF32),
        )


def _unique_stem(out_dir: Path, prefix: str = "iq") -> str:
    stamp = time.strftime("%Y%m%d_%H%M%S", time.localtime())
    stem = f"{prefix}_{stamp}"
    candidate = stem
    index = 2
    while (out_dir / f"{candidate}.cf32").exists() or (
        out_dir / f"{candidate}.json"
    ).exists():
        candidate = f"{stem}_{index}"
        index += 1
    return candidate


def new_recording_info(
    out_dir: str | Path,
    *,
    device_id: str,
    device_name: str,
    device_kind: str,
    sample_rate: float,
    center_freq: float,
    gain_db: float = 0.0,
    bandwidth_hz: float = 0.0,
) -> RecordingInfo:
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stem = _unique_stem(out_dir)
    return RecordingInfo(
        recording_id=stem,
        device_id=device_id,
        device_name=device_name,
        device_kind=device_kind,
        cf32_path=str(out_dir / f"{stem}.cf32"),
        meta_path=str(out_dir / f"{stem}.json"),
        created=time.time(),
        sample_rate=float(sample_rate),
        center_freq=float(center_freq),
        gain_db=float(gain_db),
        bandwidth_hz=float(bandwidth_hz),
    )


def load_info(path: str | Path) -> RecordingInfo | None:
    """Load metadata from a .json sidecar, .cf32 file or directory."""
    path = Path(path)
    if path.is_dir():
        candidates = sorted(path.glob("*.json"))
        path = candidates[-1] if candidates else path
    if path.suffix.lower() == ".cf32":
        path = path.with_suffix(".json")
    if path.suffix.lower() != ".json" or not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        info = RecordingInfo.from_dict(data, path)
        if not info.cf32_path:
            return None
        # A crash can leave metadata older than the file.  The file size is
        # the truth for playback and for an unfinished recording's duration.
        try:
            actual = info.path.stat().st_size // 8
            if actual > info.samples:
                info.samples = int(actual)
        except OSError:
            pass
        return info
    except Exception:
        return None


def save_info(info: RecordingInfo) -> None:
    """Persist metadata without touching the IQ file."""
    meta = Path(info.meta_path)
    meta.parent.mkdir(parents=True, exist_ok=True)
    meta.write_text(
        json.dumps(info.to_dict(), ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def set_label(info: RecordingInfo, label: str) -> RecordingInfo:
    info.label = str(label or "")
    save_info(info)
    return info


def list_recordings(out_dir: str | Path = RECORDINGS_DIR) -> list[RecordingInfo]:
    out_dir = Path(out_dir)
    if not out_dir.exists():
        return []
    result: list[RecordingInfo] = []
    for meta_path in out_dir.glob("*.json"):
        info = load_info(meta_path)
        if info is None or info.format != CF32:
            continue
        result.append(info)
    result.sort(key=lambda item: item.created, reverse=True)
    return result


def delete_recording(info: RecordingInfo) -> None:
    for path in (info.path, info.meta):
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass


def iter_iq_chunks(
    path: str | Path, chunk_samples: int = 65536
) -> Iterator[np.ndarray]:
    """Yield complex64 chunks without loading the whole file into RAM."""
    path = Path(path)
    chunk_samples = max(1024, int(chunk_samples))
    data = np.memmap(path, dtype=np.complex64, mode="r")
    try:
        for start in range(0, data.size, chunk_samples):
            yield np.array(
                data[start:start + chunk_samples], dtype=np.complex64, copy=True
            )
    finally:
        del data


class IqRecorder:
    """Background cf32 writer bound to one device."""

    def __init__(self, out_dir: str | Path = RECORDINGS_DIR) -> None:
        self.out_dir = Path(out_dir)
        self.info: RecordingInfo | None = None
        self._queue: queue.Queue[np.ndarray | None] = queue.Queue(
            maxsize=QUEUE_BLOCKS
        )
        self._thread: threading.Thread | None = None
        self._file = None
        self._samples = 0
        self._dropped = 0
        self._error = ""
        self._fatal = False
        self._active = False
        self._lock = threading.Lock()

    # ------------------------------------------------------------------ state
    @property
    def active(self) -> bool:
        return self._active and not self._fatal

    @property
    def samples(self) -> int:
        return int(self._samples)

    @property
    def dropped_samples(self) -> int:
        return int(self._dropped)

    @property
    def error(self) -> str:
        return self._error

    def elapsed_s(self) -> float:
        info = self.info
        if info is None or info.sample_rate <= 0:
            return 0.0
        return float(self._samples) / float(info.sample_rate)

    def progress(self, seconds: float) -> float:
        if seconds <= 0:
            return 0.0
        return min(1.0, self.elapsed_s() / float(seconds))

    # ------------------------------------------------------------------ start
    def start(
        self, info: RecordingInfo, expected_seconds: float | None = None
    ) -> RecordingInfo:
        if self._active:
            raise RuntimeError("Запись уже идёт")
        self.out_dir.mkdir(parents=True, exist_ok=True)
        seconds = 5.0 if expected_seconds is None else max(0.0, float(expected_seconds))
        need = estimated_bytes(info.sample_rate, seconds) + MIN_FREE_BYTES
        free = shutil.disk_usage(self.out_dir).free
        if need > free:
            raise OSError(
                f"Мало места на диске: свободно {format_size(free)}, "
                f"нужно хотя бы {format_size(need)}"
            )
        self.info = info
        self._samples = 0
        self._dropped = 0
        self._error = ""
        self._fatal = False
        self._queue = queue.Queue(maxsize=QUEUE_BLOCKS)
        self._file = open(info.cf32_path, "wb", buffering=1024 * 1024)
        info.complete = False
        info.error = ""
        self._save_meta()
        self._active = True
        self._thread = threading.Thread(
            target=self._writer_loop, name="iq-recorder", daemon=True
        )
        self._thread.start()
        return info

    # ------------------------------------------------------------------ write
    def write(self, block: IQBlock) -> None:
        if not self._active or self.info is None:
            return
        if block.device_id != self.info.device_id:
            return
        if block.samples is None or len(block.samples) == 0:
            return
        chunk = np.array(block.samples, dtype=np.complex64, copy=True)
        try:
            self._queue.put_nowait(chunk)
        except queue.Full:
            with self._lock:
                self._dropped += int(chunk.size)

    def _writer_loop(self) -> None:
        while True:
            item = self._queue.get()
            if item is None:
                break
            try:
                item.tofile(self._file)
                with self._lock:
                    self._samples += int(item.size)
            except Exception as exc:  # disk full, removed drive, ...
                self._error = str(exc)
                self._fatal = True
                break
        try:
            if self._file is not None:
                self._file.flush()
                self._file.close()
        except Exception:
            pass
        self._file = None

    # ------------------------------------------------------------------- stop
    def stop(self, timeout: float = 10.0) -> RecordingInfo | None:
        info = self.info
        if info is None:
            return None
        if not self._active and self._thread is None:
            return info
        self._active = False
        try:
            self._queue.put(None, timeout=1.0)
        except queue.Full:
            pass
        thread = self._thread
        if thread is not None:
            thread.join(timeout=timeout)
            if thread.is_alive() and not self._error:
                self._error = "запись не успела завершиться"
        self._thread = None
        info.samples = self._samples
        info.dropped_samples = self._dropped
        info.error = self._error
        info.complete = not self._error and self._samples > 0
        self._save_meta()
        self.info = info
        return info

    def _save_meta(self) -> None:
        info = self.info
        if info is None:
            return
        meta = Path(info.meta_path)
        meta.parent.mkdir(parents=True, exist_ok=True)
        meta.write_text(
            json.dumps(info.to_dict(), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
