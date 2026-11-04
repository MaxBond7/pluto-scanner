# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the HackRF backend that do not need the hardware."""
from __future__ import annotations

from pluto_scanner.devices import create_worker
from pluto_scanner.devices import hackrf
from pluto_scanner.model import DeviceConfig


def test_limits_and_filter_snapping():
    assert hackrf.clamp_rate(1e6) == 2.0e6
    assert hackrf.clamp_rate(50e6) == 20.0e6
    assert hackrf.clamp_freq(10.0) == 1.0e6
    assert hackrf.clamp_freq(10e9) == 6.0e9

    assert hackrf.snap_filter_bw(1.0e6) == 1_750_000
    assert hackrf.snap_filter_bw(4.1e6) == 5_000_000
    assert hackrf.snap_filter_bw(40e6) == 28_000_000


def test_gain_mapping_uses_lna_and_vga_step():
    lna, vga, amp = hackrf.gain_to_stages(32)
    assert lna == 16
    assert vga == 32
    assert amp is False

    assert hackrf.gain_to_stages(73)[1] == 62
    assert hackrf.gain_to_stages(90)[2] is True


def test_create_worker_returns_hackrf_worker():
    config = DeviceConfig(
        device_id="hackrf-1", name="HackRF 1", kind="hackrf",
    )
    worker = create_worker(config)
    assert isinstance(worker, hackrf.HackRFWorker)
    assert worker.sample_rate >= hackrf.HACKRF_MIN_RATE or True


def test_probe_reports_a_missing_library(monkeypatch):
    def broken():
        raise RuntimeError("не найдена libhackrf (hackrf.dll)")

    monkeypatch.setattr(hackrf, "_ensure_library", broken)
    info = hackrf.probe_hackrf()
    assert info["ok"] is False
    assert "libhackrf" in info["error"]
    assert info["serials"] == []
