from __future__ import annotations

from pluto_scanner.config import (BANDS, DEFAULT_FFT_SIZE, DEFAULT_SAMPLE_RATE,
                                  format_bw, format_freq,
                                  in_stock_pluto_range)


def test_formatting_and_stock_range():
    assert format_freq(433.92e6) == "433.9200 MHz"
    assert format_freq(1.57542e9) == "1.575420 GHz"
    assert format_bw(200e3) == "200.0 kHz"
    assert in_stock_pluto_range(433.92e6)
    assert in_stock_pluto_range(3.6e9)
    assert not in_stock_pluto_range(100e6)
    assert not in_stock_pluto_range(6e9)


def test_defaults_and_band_presets():
    assert DEFAULT_FFT_SIZE == 2048
    assert DEFAULT_SAMPLE_RATE == 1.024e6
    assert len(BANDS) >= 5
    assert all(b.frequency > 0 for b in BANDS)
    assert any("433" in b.name for b in BANDS)
