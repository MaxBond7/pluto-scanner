from __future__ import annotations

import numpy as np

from pluto_scanner.dsp.demod import Demodulator
from pluto_scanner.model import VFOConfig

FS = 1.024e6
N = 65_536


def _cfg(mode, bw, offset=0.0, squelch=-120.0):
    return VFOConfig(offset_hz=offset, mode=mode, bandwidth_hz=bw,
                     volume=1.0, squelch_db=squelch, active=True)


def _am_iq(offset=100e3):
    t = np.arange(N) / FS
    message = np.sin(2 * np.pi * 1_000.0 * t)
    return (1.0 + 0.5 * message) * np.exp(2j * np.pi * offset * t) * 0.1


def _fm_iq(offset=100e3):
    t = np.arange(N) / FS
    phase = (2 * np.pi * offset * t
             + (5_000.0 / 1_000.0) * np.sin(2 * np.pi * 1_000.0 * t))
    return 0.2 * np.exp(1j * phase)


def test_am_audio_has_signal():
    audio, rate, level = Demodulator().process(
        _am_iq(), FS, 433.92e6, _cfg("AM", 10e3, 100e3)
    )
    assert rate >= 32_000
    assert audio.size > 1000
    assert np.all(np.isfinite(audio))
    assert float(np.sqrt(np.mean(audio ** 2))) > 0.05
    assert level > -80


def test_fm_audio_has_signal():
    audio, rate, level = Demodulator().process(
        _fm_iq(), FS, 433.92e6, _cfg("FM", 200e3, 100e3)
    )
    assert rate >= 32_000
    assert audio.size > 1000
    assert float(np.max(np.abs(audio))) > 0.01
    assert level > -80


def test_ssb_and_cw_produce_audio():
    t = np.arange(N) / FS
    ssb = 0.2 * np.exp(2j * np.pi * 1_000.0 * t)
    audio, _, _ = Demodulator().process(
        ssb, FS, 433.92e6, _cfg("SSB", 3e3, 0.0)
    )
    assert audio.size > 1000
    assert float(np.sqrt(np.mean(audio ** 2))) > 0.05

    cw = np.full(N, 0.2 + 0.0j)
    audio, _, _ = Demodulator().process(
        cw, FS, 433.92e6, _cfg("CW", 1e3, 0.0)
    )
    assert audio.size > 1000
    assert float(np.sqrt(np.mean(audio ** 2))) > 0.05


def test_squelch_closes_audio():
    audio, _, _ = Demodulator().process(
        _fm_iq(), FS, 433.92e6, _cfg("FM", 200e3, 100e3, squelch=0.0)
    )
    assert audio.size > 0
    assert float(np.max(np.abs(audio))) == 0.0


def test_inactive_vfo_is_silent():
    cfg = _cfg("FM", 200e3, 100e3)
    cfg.active = False
    audio, _, _ = Demodulator().process(_fm_iq(), FS, 433.92e6, cfg)
    assert float(np.max(np.abs(audio))) == 0.0
