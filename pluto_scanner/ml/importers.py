"""Import external IQ datasets into the app's cf32 recording format.

Supported:
- SigMF (``.sigmf-meta`` + ``.sigmf-data``), the open exchange format used by
  many public RF datasets;
- raw interleaved float32 ``.dat``/``.cf32`` files, e.g. DroneDetect;
- label override for datasets whose labels model the source, not our six
  classes.

The dataset itself is never bundled or redistributed.  The user downloads it
from the original source and imports it locally, keeping the licence intact.
"""
from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import numpy as np

from ..recordings import (
    RecordingInfo,
    new_recording_info,
    save_info,
)

KNOWN_LABELS = [
    "FHSS", "TELEMETRY", "VIDEO_ANALOG", "VIDEO_DIGITAL", "WIFI", "NARROW",
]


@dataclass
class ImportResult:
    info: RecordingInfo
    source: str
    format: str


def _normalise_label(value: str | None) -> str:
    text = str(value or "").strip().upper()
    aliases = {
        "VIDEO": "VIDEO_DIGITAL",
        "ANALOG_VIDEO": "VIDEO_ANALOG",
        "DIGITAL_VIDEO": "VIDEO_DIGITAL",
        "WI-FI": "WIFI",
        "WIFI-LIKE": "WIFI",
        "TELEMETRY/RC": "TELEMETRY",
        "RC": "TELEMETRY",
        "NARROWBAND": "NARROW",
    }
    text = aliases.get(text, text)
    return text if text in KNOWN_LABELS else ""


def _sigmf_paths(src: str | Path) -> tuple[Path, Path]:
    path = Path(src)
    if path.is_dir():
        metas = sorted(path.glob("*.sigmf-meta"))
        if not metas:
            raise FileNotFoundError("в папке нет .sigmf-meta")
        path = metas[0]
    if path.suffix != ".sigmf-meta":
        raise ValueError("ожидался файл .sigmf-meta или папка с ним")
    data = Path(str(path)[:-len(".sigmf-meta")] + ".sigmf-data")
    if not data.exists():
        raise FileNotFoundError(f"нет файла данных: {data.name}")
    return path, data


def _sigmf_array(data: Path, datatype: str, start: int, count: int | None):
    dt = datatype.lower()
    if dt in ("cf32_le", "cf32_be"):
        dtype = np.dtype("<c8" if dt.endswith("_le") else ">c8")
        raw = np.memmap(data, dtype=dtype, mode="r")
    elif dt in ("ci16_le", "ci16_be"):
        dtype = np.dtype("<i2" if dt.endswith("_le") else ">i2")
        raw = np.memmap(data, dtype=dtype, mode="r")
        raw = raw[start * 2: (start + (count or raw.size // 2)) * 2]
        iq = (raw[0::2].astype(np.float64)
              + 1j * raw[1::2].astype(np.float64)) / 32768.0
        return iq.astype(np.complex64)
    elif dt in ("cf64_le", "cf64_be"):
        dtype = np.dtype("<c16" if dt.endswith("_le") else ">c16")
        raw = np.memmap(data, dtype=dtype, mode="r")
    else:
        raise ValueError(f"пока не поддержан SigMF datatype: {datatype}")
    if count is None:
        return np.array(raw[start:], dtype=np.complex64, copy=True)
    return np.array(raw[start:start + count], dtype=np.complex64, copy=True)


def import_sigmf(
    src: str | Path,
    out_dir: str | Path,
    *,
    label: str | None = None,
    start_seconds: float = 0.0,
    max_seconds: float = 10.0,
    device_name: str = "SigMF import",
) -> ImportResult:
    meta_path, data_path = _sigmf_paths(src)
    meta = json.loads(meta_path.read_text(encoding="utf-8"))
    glob = meta.get("global") or {}
    sample_rate = float(
        glob.get("core:sample_rate")
        or glob.get("sample_rate")
        or 0.0
    )
    if sample_rate <= 0:
        raise ValueError("в SigMF metadata нет sample_rate")
    datatype = str(
        glob.get("core:datatype") or glob.get("datatype") or "cf32_le"
    )
    captures = meta.get("captures") or []
    center = float(
        captures[0].get("core:frequency", 0.0) if captures else 0.0
    )
    if not label:
        for annotation in meta.get("annotations") or []:
            raw_label = (
                annotation.get("core:label")
                or annotation.get("label")
                or ""
            )
            if _normalise_label(raw_label):
                label = raw_label
                break

    start = max(0, int(float(start_seconds) * sample_rate))
    count = max(1, int(float(max_seconds) * sample_rate))
    iq = _sigmf_array(data_path, datatype, start, count)
    if iq.size == 0:
        raise ValueError("в SigMF файле нет отсчётов")
    info = new_recording_info(
        out_dir,
        device_id="sigmf",
        device_name=device_name,
        device_kind="import",
        sample_rate=sample_rate,
        center_freq=center,
        bandwidth_hz=sample_rate,
    )
    iq.tofile(info.cf32_path)
    info.samples = int(iq.size)
    info.complete = True
    info.label = _normalise_label(label)
    info.notes = f"SigMF: {meta_path.name}"
    save_info(info)
    return ImportResult(info, str(meta_path), "sigmf")


def import_raw_iq(
    src: str | Path,
    out_dir: str | Path,
    *,
    sample_rate: float,
    center_freq: float = 0.0,
    label: str | None = None,
    start_seconds: float = 0.0,
    max_seconds: float = 10.0,
    device_name: str = "Raw IQ import",
) -> ImportResult:
    """Import interleaved float32 I/Q (the common ``.dat``/``.cf32`` layout)."""
    path = Path(src)
    if not path.exists():
        raise FileNotFoundError(path)
    raw = np.memmap(path, dtype="<f4", mode="r")
    total = raw.size // 2
    start = max(0, int(float(start_seconds) * sample_rate))
    count = max(1, min(
        total - start,
        int(float(max_seconds) * sample_rate),
    ))
    if count <= 0:
        raise ValueError("в файле нет отсчётов в выбранном интервале")
    iq = np.array(
        raw[start * 2: (start + count) * 2], dtype=np.float32, copy=True
    ).view(np.complex64)
    info = new_recording_info(
        out_dir,
        device_id="raw-import",
        device_name=device_name,
        device_kind="import",
        sample_rate=float(sample_rate),
        center_freq=float(center_freq),
        bandwidth_hz=float(sample_rate),
    )
    iq.tofile(info.cf32_path)
    info.samples = int(iq.size)
    info.complete = True
    info.label = _normalise_label(label)
    info.notes = f"raw float32 I/Q: {path.name}"
    save_info(info)
    return ImportResult(info, str(path), "dat")
