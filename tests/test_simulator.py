from __future__ import annotations

import numpy as np

from pluto_scanner.devices.simulator import SimulatorWorker
from pluto_scanner.model import DeviceConfig


def _worker(tmp_path=None):
    cfg = DeviceConfig(device_id="sim", name="Sim", kind="sim",
                       center_freq=433.92e6, sample_rate=1.024e6,
                       fft_size=2048, seed=7)
    return SimulatorWorker(cfg)


def test_static_background_and_render():
    worker = _worker()
    assert len(worker._signals) >= 5
    t = np.arange(8192) / worker.sample_rate
    total = np.zeros(t.size, dtype=np.complex128)
    for sig in worker._signals:
        part = worker._render(sig, t, worker.sample_rate)
        if part is not None:
            assert part.shape == t.shape
            assert np.all(np.isfinite(part))
            total += part
    assert np.sqrt(np.mean(np.abs(total) ** 2)) > 0.0


def test_manual_injection_creates_wideband_signal():
    worker = _worker()
    worker.inject_signal(offset_hz=120e3, kind="wideband",
                         bw_hz=60e3, amp_db=-40.0, duration=2.0)
    worker._drain_manual()
    assert len(worker._signals) == 8
    sig = worker._signals[-1]
    assert sig.manual
    assert sig.noise_table is not None
    rms = float(np.sqrt(np.mean(np.abs(sig.noise_table) ** 2)))
    assert 0.6 < rms < 1.5

    t = worker._sim_time + 0.2 + np.arange(8192) / worker.sample_rate
    part = worker._render(sig, t, worker.sample_rate)
    assert part is not None
    assert np.max(np.abs(part)) > 0.0


def test_sample_rate_change_rebuilds_static_signals():
    worker = _worker()
    worker._apply_command("sample_rate", 2.048e6)
    assert worker.sample_rate == 2.048e6
    assert len(worker._signals) >= 5
    for sig in worker._signals:
        assert abs(sig.offset_hz) <= 0.46 * worker.sample_rate
    t = np.arange(2048) / worker.sample_rate
    sig = worker._signals[-1]
    part = worker._render(sig, t, worker.sample_rate)
    assert part is None or part.shape == t.shape
