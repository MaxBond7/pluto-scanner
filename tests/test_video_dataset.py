# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Sweep folders of the FPV dataset and the video tab file loader."""
from __future__ import annotations

import time

import numpy as np
import pytest
from PySide6.QtWidgets import QApplication

from sdr_scanner.video.dataset import (
    frequencies,
    load_blocks,
    metadata_for,
)


def _make_sweep(tmp_path, rate: float = 10e6):
    """Two blocks of IQ at 100 MHz and two at 1240 MHz, zero padded."""
    rng = np.random.default_rng(5)
    block_samples = 32768
    rows = []
    data = []
    offset = 0
    for center in (100e6, 1240e6):
        for _ in range(2):
            block = np.zeros(block_samples * 2, dtype=np.complex64)
            block[:block_samples] = (
                rng.normal(0, 0.1, block_samples)
                + 1j * rng.normal(0, 0.1, block_samples)
            ).astype(np.complex64)
            rows.append((center, offset * 8, block_samples * 2))
            data.append(block)
            offset += block_samples * 2
    iq = np.concatenate(data)
    iq_path = tmp_path / "iq.bin"
    iq.tofile(iq_path)
    meta = tmp_path / "metadata.csv"
    lines = ["timestamp,center_freq,offset_bytes,num_samples"]
    for center, offset, count in rows:
        lines.append(f"2026-01-01T00:00:00.000000,{center},{offset},{count}")
    meta.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return iq_path, meta, block_samples


def test_metadata_is_found_next_to_iq_bin(tmp_path):
    iq_path, meta, _ = _make_sweep(tmp_path)
    assert metadata_for(iq_path) == meta
    assert metadata_for(tmp_path / "other.bin") is None


def test_frequencies_are_unique_and_sorted(tmp_path):
    iq_path, meta, _ = _make_sweep(tmp_path)
    assert frequencies(meta) == [100e6, 1240e6]


def test_blocks_are_trimmed_and_joined(tmp_path):
    iq_path, meta, block_samples = _make_sweep(tmp_path)
    iq, center = load_blocks(iq_path, meta, 1240e6)
    assert center == 1240e6
    # Two blocks, padding removed, joined in time.
    assert iq.size == block_samples * 2
    assert np.all(np.abs(iq) > 0)
    iq2, center2 = load_blocks(iq_path, meta, 1200e6)
    assert center2 == 1240e6
    assert iq2.size == iq.size


def test_missing_frequency_falls_back_to_nearest(tmp_path):
    iq_path, meta, _ = _make_sweep(tmp_path)
    iq, center = load_blocks(iq_path, meta, 1e6)
    assert center == 100e6
    assert iq.size > 0


def test_video_panel_decodes_a_file_without_a_session(tmp_path):
    from sdr_scanner.ui.video_window import VideoPanel

    app = QApplication.instance() or QApplication([])
    rate = 10e6
    line = int(round(rate / 15734.264))
    video = np.zeros(line * 300, dtype=np.float64)
    for index in range(300):
        base = index * line
        sync = int(0.073 * line)
        porch = int(0.09 * line)
        active = int(0.78 * line)
        video[base + sync:base + sync + porch] = 0.12
        x = np.linspace(0.0, 1.0, active)
        video[base + sync + porch:base + sync + porch + active] = (
            0.2 + 0.65 * (0.5 + 0.5 * np.sin(2 * np.pi * (x * 6 + index / 40)))
        )
    t = np.arange(video.size) / rate
    iq = np.exp(2j * np.pi * (1e6 * t + 2e6 * np.cumsum(video) / rate))
    path = tmp_path / "video.cf32"
    iq.astype(np.complex64).tofile(path)

    panel = VideoPanel(None)
    panel._decode_job(
        lambda: panel._read_iq(path, rate), rate, "video.cf32",
    )
    deadline = time.monotonic() + 10.0
    while panel._last_image is None and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(0.02)
    assert panel._last_image is not None
    assert panel._last_frame is not None
    assert "video.cf32" in panel.status.text()
    panel.deleteLater()
    app.processEvents()
