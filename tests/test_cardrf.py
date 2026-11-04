# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the CardRF adapter (archive parsing and baseband conversion)."""
from __future__ import annotations

import numpy as np
import pytest

from pluto_scanner.ml.cardrf import (
    build_window,
    chunk_samples,
    parse_entry,
    to_baseband,
    window_samples,
)


def test_parse_entry_reads_label_from_the_folder():
    wifi = parse_entry("CARDRF/LOS/Train/WIFI/TPLINK_TL_WR940N/wifi_1.mat")
    assert wifi is not None
    assert (wifi.label, wifi.split, wifi.category) == (0, "Train", "WIFI")
    assert wifi.group.endswith("WIFI/TPLINK_TL_WR940N")

    drone = parse_entry(
        "CARDRF/LOS/Train/UAV_Controller/DJI_MAVICPRO/MAVICPRO1_1.mat"
    )
    assert drone is not None
    assert drone.label == 1

    nlos = parse_entry("CARDRF/NLOS/UAV/DJI_M600/FLYING/m600_1.mat")
    assert nlos is not None
    assert (nlos.label, nlos.split) == (1, "NLOS")


@pytest.mark.parametrize("name", [
    "__MACOSX/CARDRF/LOS/Train/WIFI/._wifi_1.mat",
    "CARDRF/LOS/Train/WIFI/wifi_1.mat",          # no device folder
    "CARDRF/readme.txt",
    "CARDRF/LOS/Train/UNKNOWN/DEV/x.mat",        # unknown class
])
def test_parse_entry_rejects_unusable_paths(name):
    assert parse_entry(name) is None


def test_chunk_and_window_sizes_follow_the_rate():
    assert chunk_samples(20e6) == 5000
    assert window_samples(20e6) == 400_000
    assert chunk_samples(4.096e6) == 1024
    assert window_samples(4.096e6) == 81_920


def test_to_baseband_centres_the_strongest_tone():
    rate = 8.0e6
    n = 8192
    t = np.arange(n) / rate
    strong = 0.5 * np.cos(2 * np.pi * 3.0e6 * t)
    weak = 0.05 * np.cos(2 * np.pi * 3.1e6 * t)
    block = to_baseband(
        strong + weak,
        sample_rate=rate,
        out_rate=1.0e6,
        search_hz=(2.0e6, 4.0e6),
        smooth_hz=50e3,
    )
    assert block.dtype == np.complex64
    assert block.size == 1024
    spectrum = np.abs(np.fft.fftshift(np.fft.fft(block)))
    # The strong tone sits at DC; the weak one shows up 100 kHz to the side.
    # Decimation keeps the bin width, so 100 kHz is ~102 bins here.
    bins = 0.1e6 / (rate / n)
    peak = int(np.argmax(spectrum))
    assert peak == block.size // 2
    # Zero out the DC lobe before looking for the weaker neighbour.
    masked = spectrum.copy()
    masked[block.size // 2 - 4: block.size // 2 + 5] = 0.0
    second = int(np.argmax(masked))
    assert abs(second - (block.size // 2 + bins)) <= 3


def test_to_baseband_rejects_tiny_input():
    assert to_baseband(np.zeros(16)).size == 0


def test_build_window_fills_a_20ms_block():
    rate = 4.096e6
    rng = np.random.default_rng(3)
    need = window_samples(rate) // chunk_samples(rate)
    chunks = [
        (rng.normal(size=chunk_samples(rate))
         + 1j * rng.normal(size=chunk_samples(rate))).astype(np.complex64)
        for _ in range(need)
    ]
    window = build_window(chunks, rng, size=window_samples(rate))
    assert window.shape == (window_samples(rate),)
    assert window.dtype == np.complex64
    assert np.isfinite(window).all()
    # Every chunk contributes, so the whole block is non-zero.
    assert np.count_nonzero(window) > window.size * 0.99
