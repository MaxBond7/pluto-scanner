# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Score a drone/not-drone model on the recordings you made yourself.

This is the honest check that matters most: the training archives come from
other receivers and other places, while these files were recorded here, with
this antenna and this gain.  The tool prints, per recording, the mean score
and the share of 20 ms blocks above the alarm and candidate thresholds.

Examples::

    python -m tools.check_binary
    python -m tools.check_binary --model user_data\\binary_cardrf.json
    python -m tools.check_binary --recordings iq_recordings --json report.json

Nothing is trained here and no file is modified.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

from sdr_scanner.drone.bands import DroneBand
from sdr_scanner.drone.features import QUIET, OVERLOAD, analyze_iq
from sdr_scanner.ml.binary import BinaryModel
from sdr_scanner.ml.binary_features import from_observation
from sdr_scanner.paths import DEFAULT_BINARY_MODEL, RECORDINGS_DIR
from sdr_scanner.recordings import list_recordings


def score_recording(model: BinaryModel, info, *, block_s: float = 0.02) -> dict:
    fs = max(1000.0, float(info.sample_rate))
    center = float(info.center_freq)
    band = DroneBand(
        "rec", "recording", center - 0.45 * fs, center + 0.45 * fs,
        alarm=True,
    )
    block = max(256, int(fs * block_s))
    try:
        samples = np.memmap(info.path, dtype=np.complex64, mode="r")
    except Exception as exc:
        return {"error": str(exc)}
    total = int(samples.size)
    if total < block:
        return {"error": "запись короче одного блока"}

    scores: list[float] = []
    for start in range(0, total - block + 1, block):
        iq = np.array(samples[start:start + block], dtype=np.complex64)
        observation = analyze_iq(
            iq, fs, center, band,
            device_id=info.recording_id,
            threshold_db=6.0, nfft=4096, notch_hz=300e3,
        )
        if observation is None or observation.class_key in (QUIET, OVERLOAD):
            continue
        scores.append(
            float(model.predict_proba(from_observation(observation)[None, :])[0])
        )
    del samples
    values = np.asarray(scores, dtype=np.float64)
    if values.size == 0:
        return {"error": "нет пригодных блоков"}
    return {
        "blocks": int(values.size),
        "mean": round(float(values.mean()), 4),
        "median": round(float(np.median(values)), 4),
        "above_alarm": round(float((values >= model.threshold_alarm).mean()), 4),
        "above_candidate": round(float((values >= model.threshold_candidate).mean()), 4),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--model", default=str(DEFAULT_BINARY_MODEL))
    parser.add_argument("--recordings", default=str(RECORDINGS_DIR))
    parser.add_argument("--json", default="")
    args = parser.parse_args(argv)

    path = Path(args.model)
    model = BinaryModel.load(path)
    if model is None:
        print(f"не удалось прочитать модель: {path}")
        return 2
    infos = [info for info in list_recordings(args.recordings) if info.exists]
    if not infos:
        print(f"в {args.recordings} нет записей")
        return 2

    print(f"модель: {path}")
    print(f"порог тревоги {model.threshold_alarm:.3f}, "
          f"кандидата {model.threshold_candidate:.3f}")
    print(f"{'запись':24s} {'метка':8s} {'центр':>9s} {'полоса':>8s} "
          f"{'блоков':>7s} {'score':>7s} {'тревог':>7s} {'кандид.':>8s}")
    report: dict[str, dict] = {}
    for info in sorted(infos, key=lambda item: item.recording_id):
        row = score_recording(model, info)
        report[info.recording_id] = {
            "label": info.label,
            "center_mhz": round(float(info.center_freq) / 1e6, 3),
            "rate_mhz": round(float(info.sample_rate) / 1e6, 3),
            **row,
        }
        if "error" in row:
            print(f"{info.recording_id:24s} {info.label or '-':8s} {row['error']}")
            continue
        print(
            f"{info.recording_id:24s} {info.label or '-':8s} "
            f"{info.center_freq/1e6:8.1f}M {info.sample_rate/1e6:7.3f}M "
            f"{row['blocks']:7d} {row['mean']:7.3f} "
            f"{row['above_alarm']:6.0%} {row['above_candidate']:7.0%}"
        )

    labelled = {
        label: [row for row in report.values() if row.get("label") == label]
        for label in {row.get("label") for row in report.values()} if label
    }
    if labelled:
        print("\nпо меткам:")
        for label, rows in sorted(labelled.items()):
            usable = [row for row in rows if "mean" in row]
            if not usable:
                continue
            weight = sum(row["blocks"] for row in usable)
            mean = sum(row["mean"] * row["blocks"] for row in usable) / weight
            alarms = sum(row["above_alarm"] * row["blocks"] for row in usable) / weight
            print(f"  {label:10s} записей {len(usable)}, блоков {weight}, "
                  f"средний score {mean:.3f}, тревог {alarms:.0%}")

    if args.json:
        out = Path(args.json)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(
            json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8",
        )
        print(f"\nJSON: {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
