"""Tests for the read-only Pluto RX capability probe."""
from __future__ import annotations

from pluto_scanner.devices.pluto import count_rx_channels


def test_one_complex_channel_is_1r1t():
    assert count_rx_channels(["voltage0", "voltage1"]) == 1


def test_two_complex_channels_are_2r2t():
    assert count_rx_channels(
        ["voltage0", "voltage1", "voltage2", "voltage3"]
    ) == 2


def test_empty_and_unrelated_channels():
    assert count_rx_channels([]) == 0
    assert count_rx_channels(["altvoltage0", "temp0"]) == 0
