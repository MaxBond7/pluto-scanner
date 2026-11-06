# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Synthetic tests for the channel/dwell map."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np

from sdr_scanner.ml.behavior import Behavior
from sdr_scanner.ml.channels import (
    ChannelInfo,
    ChannelMap,
    analyze_channels,
    dwell_histogram,
    fingerprint,
)

RATE = 20.0e6


def _tone(freq: float, seconds: float) -> np.ndarray:
    t = np.arange(int(RATE * seconds)) / RATE
    return np.exp(2j * np.pi * freq * t).astype(np.complex64)


def test_frequency_hopper_gets_a_channel_map():
    piece = np.concatenate([
        _tone(-5e6, 0.001),
        _tone(3e6, 0.001),
        _tone(5e6, 0.001),
    ] * 10)
    result = analyze_channels(piece, RATE, max_seconds=0.03)
    assert len(result.channels) == 3
    assert result.active_share > 0.95
    assert 1.0 <= result.dwell_ms <= 1.5
    assert 0.7 <= result.hop_period_ms <= 1.3
    assert 700.0 <= result.hop_rate_hz <= 1300.0
    assert all(channel.share > 0.2 for channel in result.channels)


def test_steady_carrier_has_one_channel_and_no_hops():
    result = analyze_channels(_tone(3e6, 0.03), RATE, max_seconds=0.03)
    assert len(result.channels) == 1
    assert result.channels[0].center_hz == 3e6
    assert result.hop_rate_hz == 0.0
    assert result.dwell_ms > 20.0


def test_dwell_histogram_covers_every_run():
    piece = np.concatenate([_tone(-5e6, 0.002), _tone(5e6, 0.004)] * 5)
    result = analyze_channels(piece, RATE, max_seconds=0.06)
    counts = sum(count for _label, count in dwell_histogram(result))
    assert counts == len(result.dwells_ms)


def test_wide_noise_is_not_mistaken_for_channels():
    rng = np.random.default_rng(7)
    noise = (
        rng.normal(size=int(RATE * 0.03))
        + 1j * rng.normal(size=int(RATE * 0.03))
    ).astype(np.complex64)
    result = analyze_channels(noise, RATE, max_seconds=0.03)
    assert result.wide_share > 0.5
    assert len(result.channels) <= 2
    assert "широкополосный" in fingerprint(result)


def test_short_block_is_safe():
    result = analyze_channels(np.zeros(100, dtype=np.complex64), RATE)
    assert result.frames == 0
    assert result.channels == ()


def _map(count: int, hops: float, dwell: float) -> ChannelMap:
    channels = tuple(
        ChannelInfo(
            center_hz=2400e6 + index * 1e6, share=1.0 / count,
            dwell_ms=dwell, hits=10,
        )
        for index in range(count)
    )
    return ChannelMap(
        channels=channels, active_share=0.85, hop_rate_hz=hops,
        hop_period_ms=dwell, hop_period_cv=0.1, dwell_ms=dwell,
        dwells_ms=(dwell,), hop_intervals_ms=(dwell,),
        frames=100, duration_s=1.0,
    )


def test_fingerprint_prefers_dji_like_wide_hopper():
    behavior = Behavior(
        duty=0.85, burst_rate_hz=100.0, burst_interval_cv=0.1,
        hop_rate_hz=1000.0, channels=40, occupied=0.5,
        sync_khz=0.0, sync_strength=0.0, frames=4000,
    )
    verdict = fingerprint(_map(40, 1000.0, 1.2), behavior)
    assert "FHSS" in verdict or "DJI" in verdict


def test_fingerprint_prefers_wifi_for_few_long_channels():
    behavior = SimpleNamespace(duty=0.4)
    verdict = fingerprint(_map(4, 80.0, 20.0), behavior)
    assert "узкому" in verdict or "Wi-Fi" in verdict
