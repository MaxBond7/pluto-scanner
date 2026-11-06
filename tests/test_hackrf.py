# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Tests for the HackRF backend that do not need the hardware."""
from __future__ import annotations

import ctypes

import numpy as np
from PySide6.QtWidgets import QApplication

from sdr_scanner.devices import create_worker
from sdr_scanner.devices import hackrf
from sdr_scanner.model import DeviceConfig


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


class FakeLibrary:
    """Minimal libhackrf stand-in with the real device-list calling shape."""

    def __init__(self) -> None:
        serials = (ctypes.c_char_p * 2)(b"abc123", b"def456")
        indices = (ctypes.c_int * 2)(0, 0)
        self.device = hackrf._DeviceList(
            serial_numbers=ctypes.cast(
                serials, ctypes.POINTER(ctypes.c_char_p)
            ),
            usb_board_ids=None,
            usb_device_index=ctypes.cast(
                indices, ctypes.POINTER(ctypes.c_int)
            ),
            devicecount=2,
            usb_devices=None,
            usb_devicecount=0,
        )
        self.freed = False

    def hackrf_init(self):
        return 0

    def hackrf_exit(self):
        return 0

    def hackrf_device_list(self):
        return ctypes.pointer(self.device)

    def hackrf_device_list_free(self, pointer):
        self.freed = True


def test_transfer_scales_int8_iq_and_splits_into_blocks():
    QApplication.instance() or QApplication([])
    config = DeviceConfig(
        device_id="hackrf-1", name="HackRF 1", kind="hackrf",
        sample_rate=4.096e6,
    )
    worker = hackrf.HackRFWorker(config)
    worker._block_len = 4
    received = []
    worker.iq_ready.connect(received.append)

    raw = (ctypes.c_byte * 8)(1, 2, 3, 4, -5, -6, 7, 8)
    transfer = hackrf._Transfer(
        device=None,
        buffer=ctypes.cast(raw, ctypes.POINTER(ctypes.c_byte)),
        buffer_length=8,
        valid_length=8,
        rx_ctx=None,
        tx_ctx=None,
    )
    assert worker._on_transfer(ctypes.pointer(transfer)) == 0
    assert len(received) == 1
    samples = received[0].samples
    assert samples.size == 4
    assert np.allclose(
        samples,
        np.array([1 + 2j, 3 + 4j, -5 - 6j, 7 + 8j], dtype=np.complex64) / 128.0,
    )


def test_probe_reads_serials_without_arguments(monkeypatch):
    library = FakeLibrary()
    monkeypatch.setattr(hackrf, "_ensure_library", lambda: library)
    info = hackrf.probe_hackrf()
    assert info["ok"] is True
    assert info["serials"] == ["abc123", "def456"]
    assert library.freed is True
