"""Compare a fresh sweep with a saved background sweep.

Two complementary tests are used:

* peak matching - every peak of the new sweep is matched to the closest peak
  of the background.  An unmatched peak is a **new contact**; a matched peak
  that is ``margin_db`` stronger is reported as a changed contact.  This is
  the primary detector because it is insensitive to small noise-floor drift.
* spectrum rise - the stored max-hold spectra are aligned by frequency and
  regions rising by more than ``margin_db`` are reported as background rises.
  This catches wideband/weak signals that do not form a narrow peak.

All functions are plain Python/numpy so they can be tested without Qt.
"""
from __future__ import annotations

import json
import time
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from scipy import ndimage

from .recorder import load_bundle, ranges_overlap

COMPARE_VERSION = 1


def _freq(peak: dict[str, Any]) -> float:
    return float(peak.get("freq_hz", 0.0))


def _bw(peak: dict[str, Any]) -> float:
    return abs(float(peak.get("bw_hz", 0.0)))


def _level(peak: dict[str, Any]) -> float:
    return float(peak.get("peak_db", -200.0))


def dedupe_peaks(
    peaks: Iterable[dict[str, Any]], tolerance_hz: float = 20e3
) -> list[dict[str, Any]]:
    """Merge duplicates caused by overlapping sweep steps."""
    ordered = sorted(
        (dict(peak) for peak in peaks if peak.get("freq_hz") is not None),
        key=_freq,
    )
    merged: list[dict[str, Any]] = []
    for peak in ordered:
        if merged and abs(_freq(peak) - _freq(merged[-1])) <= tolerance_hz:
            # Keep the stronger observation, but remember how many times it
            # was seen; that is useful when judging a marginal signal.
            previous = merged[-1]
            seen = int(previous.get("seen_steps", 1)) + 1
            if _level(peak) > _level(previous):
                peak["seen_steps"] = seen
                merged[-1] = peak
            else:
                previous["seen_steps"] = seen
        else:
            peak.setdefault("seen_steps", 1)
            merged.append(peak)
    return merged


def _nearest(
    peak: dict[str, Any], pool: list[dict[str, Any]], tolerance_hz: float
) -> dict[str, Any] | None:
    if not pool:
        return None
    freq = _freq(peak)
    best: dict[str, Any] | None = None
    best_delta = float("inf")
    for candidate in pool:
        delta = abs(_freq(candidate) - freq)
        limit = max(tolerance_hz, 2.0 * max(_bw(peak), _bw(candidate)))
        if delta <= limit and delta < best_delta:
            best = candidate
            best_delta = delta
    return best


def _public_peak(peak: dict[str, Any], reason: str,
                 old_peak: dict[str, Any] | None = None) -> dict[str, Any]:
    out = {
        "freq_hz": _freq(peak),
        "bw_hz": _bw(peak),
        "peak_db": _level(peak),
        "snr_db": float(peak.get("snr_db", 0.0)),
        "type": peak.get("type", "UNKNOWN"),
        "type_ru": peak.get("type_ru", peak.get("type", "НЕИЗВ.")),
        "confidence": float(peak.get("confidence", 0.0)),
        "seen_steps": int(peak.get("seen_steps", 1)),
        "reason": reason,
    }
    if old_peak is not None:
        out["old_peak_db"] = _level(old_peak)
        out["delta_db"] = round(_level(peak) - _level(old_peak), 2)
        out["old_freq_hz"] = _freq(old_peak)
    return out


def compatibility_warnings(
    background: dict[str, Any], current: dict[str, Any]
) -> list[str]:
    """Explain why two bundles may not be directly comparable."""
    old = background.get("device") or {}
    new = current.get("device") or {}
    warnings: list[str] = []
    if background.get("scan_version", 2) < 2:
        warnings.append(
            "Фон сохранён старой версией сканера — формат несовместим."
        )
        return warnings
    try:
        completed = int(background.get("steps_completed", 0))
    except (TypeError, ValueError):
        completed = 0
    if completed <= 0:
        warnings.append("В фоне нет завершённых шагов — сравнивать не с чем.")
        return warnings
    if background.get("complete") is False:
        warnings.append(
            "Фон неполный (скан был остановлен) — сравнение только по "
            "покрытой части диапазона."
        )
    try:
        old0 = float(background["range_start_hz"])
        old1 = float(background["range_end_hz"])
        new0 = float(current["range_start_hz"])
        new1 = float(current["range_end_hz"])
        if (old1 > old0 and new1 > new0
                and (old0 > new0 + 1.0 or old1 < new1 - 1.0)):
            warnings.append(
                f"Фон покрывает {old0 / 1e6:.3f}–{old1 / 1e6:.3f} МГц — "
                "сравнение только в этой полосе."
            )
    except (KeyError, TypeError, ValueError):
        pass
    if not old or not old.get("kind"):
        warnings.append(
            "В сохранённом фоне нет сведений об устройстве/усилении."
        )
        return warnings
    if old.get("kind") != new.get("kind"):
        warnings.append(
            "Фон снят с другого типа устройства "
            f"({old.get('kind') or '?'} вместо {new.get('kind') or '?'})."
        )
        return warnings
    try:
        gain_delta = abs(float(old.get("gain_db", 0.0))
                         - float(new.get("gain_db", 0.0)))
    except (TypeError, ValueError):
        gain_delta = 0.0
    if gain_delta > 3.0:
        warnings.append(
            f"Усиление отличается на {gain_delta:.1f} дБ — уровни не "
            "сопоставимы."
        )
    try:
        old_fs = float(background.get("sample_rate", 0.0))
        new_fs = float(current.get("sample_rate", 0.0))
        if old_fs > 0 and new_fs > 0 and abs(old_fs - new_fs) / old_fs > 0.2:
            warnings.append(
                "Полоса захвата отличается более чем на 20%."
            )
    except (TypeError, ValueError):
        pass
    return warnings


def background_compatible(
    background: dict[str, Any], current: dict[str, Any]
) -> tuple[bool, list[str]]:
    """Return whether automatic comparison is meaningful."""
    warnings = compatibility_warnings(background, current)
    old = background.get("device") or {}
    new = current.get("device") or {}
    if background.get("scan_version", 2) < 2:
        return False, warnings
    try:
        completed = int(background.get("steps_completed", 0))
    except (TypeError, ValueError):
        completed = 0
    if completed <= 0:
        return False, warnings
    if old.get("kind") and new.get("kind") and old.get("kind") != new.get("kind"):
        return False, warnings
    try:
        gain_delta = abs(float(old.get("gain_db", 0.0))
                         - float(new.get("gain_db", 0.0)))
    except (TypeError, ValueError):
        gain_delta = 0.0
    if old.get("kind") and gain_delta > 3.0:
        return False, warnings
    return True, warnings


def compare_spectrum(
    background: dict[str, Any],
    current: dict[str, Any],
    *,
    margin_db: float = 6.0,
    min_bins: int = 3,
) -> list[dict[str, Any]]:
    """Return frequency regions whose max-hold rose above the background."""
    old_spec = background.get("spectrum") or {}
    new_spec = current.get("spectrum") or {}
    try:
        old_values = np.asarray(old_spec["max_hold_db"], dtype=np.float64)
        new_values = np.asarray(new_spec["max_hold_db"], dtype=np.float64)
        old_f0 = float(old_spec["freq_start_hz"])
        old_f1 = float(old_spec["freq_end_hz"])
        new_f0 = float(new_spec["freq_start_hz"])
        new_f1 = float(new_spec["freq_end_hz"])
    except (KeyError, TypeError, ValueError):
        return []
    if old_values.size < 8 or new_values.size < 8:
        return []

    overlap0 = max(old_f0, new_f0)
    overlap1 = min(old_f1, new_f1)
    if overlap1 <= overlap0:
        return []

    old_freqs = np.linspace(old_f0, old_f1, old_values.size)
    new_freqs = np.linspace(new_f0, new_f1, new_values.size)
    mask = (new_freqs >= overlap0) & (new_freqs <= overlap1)
    old_coverage = old_spec.get("coverage")
    new_coverage = new_spec.get("coverage")
    if isinstance(new_coverage, list) and len(new_coverage) == new_values.size:
        mask &= np.asarray(new_coverage) > 0
    if mask.sum() < 8:
        return []
    # If the old scan was stopped early, its uncovered tail was filled with
    # the noise floor and must not be treated as a real reference.
    if isinstance(old_coverage, list) and len(old_coverage) == old_values.size:
        covered = np.asarray(old_coverage) > 0
        if covered.any():
            covered_freqs = old_freqs[covered]
            mask &= (new_freqs >= covered_freqs[0]) & (
                new_freqs <= covered_freqs[-1]
            )
    if mask.sum() < 8:
        return []
    grid = new_freqs[mask]
    current_values = new_values[mask]
    reference = np.interp(grid, old_freqs, old_values)
    diff = current_values - reference
    above = diff >= float(margin_db)
    if not above.any():
        return []
    above = ndimage.binary_closing(
        above, structure=np.ones(3, dtype=bool)
    )
    labels, count = ndimage.label(above)
    rises: list[dict[str, Any]] = []
    for label in range(1, count + 1):
        idx = np.flatnonzero(labels == label)
        if idx.size < max(1, int(min_bins)):
            continue
        peak_local = int(np.argmax(diff[idx]))
        idx_peak = int(idx[peak_local])
        rises.append({
            "freq_hz": float(grid[idx_peak]),
            "freq_start_hz": float(grid[idx[0]]),
            "freq_end_hz": float(grid[idx[-1]]),
            "delta_db": round(float(diff[idx_peak]), 2),
            "level_db": round(float(current_values[idx_peak]), 2),
            "background_db": round(float(reference[idx_peak]), 2),
        })
    rises.sort(key=lambda item: item["freq_hz"])
    return rises


def compare_bundles(
    background: dict[str, Any],
    current: dict[str, Any],
    *,
    tolerance_hz: float = 50e3,
    margin_db: float = 6.0,
    dedupe_hz: float = 20e3,
) -> dict[str, Any]:
    old_peaks = dedupe_peaks(background.get("peaks", []), dedupe_hz)
    new_peaks = dedupe_peaks(current.get("peaks", []), dedupe_hz)

    # Only compare the part of the band that the saved background actually
    # covers.  A narrow test scan must not turn every peak of a later
    # full-range scan into a "new contact".
    old0 = old1 = new0 = new1 = 0.0
    try:
        old0 = float(background["range_start_hz"])
        old1 = float(background["range_end_hz"])
        new0 = float(current["range_start_hz"])
        new1 = float(current["range_end_hz"])
    except (KeyError, TypeError, ValueError):
        pass
    outside_background = 0
    if old1 > old0 and new1 > new0:
        lo = max(old0, new0)
        hi = min(old1, new1)
        if hi > lo:
            old_peaks = [
                peak for peak in old_peaks
                if lo <= _freq(peak) <= hi
            ]
            kept = [
                peak for peak in new_peaks
                if lo <= _freq(peak) <= hi
            ]
            outside_background = len(new_peaks) - len(kept)
            new_peaks = kept

    new_contacts: list[dict[str, Any]] = []
    stronger: list[dict[str, Any]] = []
    matched = 0
    for peak in new_peaks:
        old = _nearest(peak, old_peaks, tolerance_hz)
        if old is None:
            new_contacts.append(_public_peak(peak, "new"))
            continue
        matched += 1
        if _level(peak) - _level(old) >= float(margin_db):
            stronger.append(_public_peak(peak, "stronger", old))

    # A new contact found by peak matching may also produce a spectral rise;
    # do not report the same frequency twice.
    rises = compare_spectrum(background, current, margin_db=margin_db)
    if new_contacts:
        rises = [
            rise for rise in rises
            if not any(
                abs(float(rise["freq_hz"]) - float(contact["freq_hz"]))
                <= max(tolerance_hz, 2.0 * float(contact["bw_hz"]))
                for contact in new_contacts
            )
        ]

    counts = {
        "new": len(new_contacts),
        "stronger": len(stronger),
        "matched": matched,
        "background_peaks": len(old_peaks),
        "current_peaks": len(new_peaks),
        "outside_background": outside_background,
        "spectral_rises": len(rises),
    }
    warnings = compatibility_warnings(background, current)
    outside_note = (
        f" Вне сохранённого фона: {outside_background} пиков — они не "
        "считаются новыми."
        if outside_background else ""
    )
    if counts["new"]:
        summary = (
            f"Найдено новых контактов: {counts['new']}. "
            f"Изменившихся: {counts['stronger']}. "
            f"Подъёмов фона: {counts['spectral_rises']}."
        )
    elif counts["stronger"] or counts["spectral_rises"]:
        summary = (
            "Новых частот нет, но есть изменения относительно фона: "
            f"сильнее на {counts['stronger']}, подъёмов {counts['spectral_rises']}."
        )
    else:
        summary = "Новых контактов относительно сохранённого фона не найдено."
    summary += outside_note
    if warnings:
        summary = " ⚠ " + " ".join(warnings) + " " + summary

    return {
        "compare_version": COMPARE_VERSION,
        "created": round(time.time(), 3),
        "background": {
            "scan_id": background.get("scan_id"),
            "created": background.get("created"),
            "range_start_hz": background.get("range_start_hz"),
            "range_end_hz": background.get("range_end_hz"),
            "device": background.get("device"),
        },
        "current": {
            "scan_id": current.get("scan_id"),
            "created": current.get("created"),
            "range_start_hz": current.get("range_start_hz"),
            "range_end_hz": current.get("range_end_hz"),
            "device": current.get("device"),
        },
        "params": {
            "tolerance_hz": float(tolerance_hz),
            "margin_db": float(margin_db),
            "dedupe_hz": float(dedupe_hz),
        },
        "warnings": warnings,
        "counts": counts,
        "summary_ru": summary,
        "new_contacts": new_contacts,
        "stronger_contacts": stronger,
        "spectral_rises": rises,
    }


def compare_background_files(
    background_path: str | Path,
    current_path: str | Path,
    *,
    tolerance_hz: float = 50e3,
    margin_db: float = 6.0,
    dedupe_hz: float = 20e3,
) -> dict[str, Any]:
    background = load_bundle(background_path)
    current = load_bundle(current_path)
    if not ranges_overlap(background, current):
        raise ValueError("диапазоны сканов не пересекаются")
    report = compare_bundles(
        background,
        current,
        tolerance_hz=tolerance_hz,
        margin_db=margin_db,
        dedupe_hz=dedupe_hz,
    )
    report["background"]["path"] = str(Path(background_path).resolve())
    report["current"]["path"] = str(Path(current_path).resolve())
    return report


def save_report(report: dict[str, Any], path: str | Path) -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return path.resolve()
