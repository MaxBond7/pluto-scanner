"""Synthetic, continuous-time-ish IQ source.

This is not just a fake spectrum: it produces complex IQ at the requested
sample rate, including a static background, random new contacts, chirps,
pulses, wideband blobs and manual injections.  The same DSP path is used for
the simulator and a real Pluto.
"""
from __future__ import annotations

import queue
import time
from dataclasses import dataclass, field

import numpy as np

from ..model import DeviceConfig, IQBlock
from .base import DeviceWorker


@dataclass
class _SimSignal:
    offset_hz: float
    amplitude: float
    bandwidth_hz: float
    kind: str
    start: float
    duration: float | None
    phase: float
    tones: np.ndarray
    tone_phases: np.ndarray
    pulse_rate: float = 0.0
    duty: float = 0.5
    chirp_hz_s: float = 0.0
    manual: bool = False
    noise_table: np.ndarray | None = None

    @property
    def end(self) -> float:
        return float("inf") if self.duration is None else self.start + self.duration


class SimulatorWorker(DeviceWorker):
    def __init__(self, config: DeviceConfig, seed: int | None = None) -> None:
        super().__init__(config)
        self._rng = np.random.default_rng(config.seed if seed is None else seed)
        self.noise_std = 2.5e-4
        self._sim_time = 0.0
        self._auto_next = 2.0
        self.buffer_size = 0
        self._signals: list[_SimSignal] = []
        self._manual: queue.Queue[dict] = queue.Queue()
        self._build_static()

    # ------------------------------------------------------------------ setup
    def _new_signal(self, offset_hz: float, kind: str, bw_hz: float,
                    amp_db: float, start: float, duration: float | None,
                    manual: bool = False) -> _SimSignal:
        amp = float(10.0 ** (amp_db / 20.0))
        kind = kind.lower()
        if kind == "carrier":
            bw_hz = 0.0
            tones = np.array([0.0])
            tone_phases = self._rng.uniform(0, 2 * np.pi, 1)
            pulse_rate = duty = 0.0
            chirp = 0.0
        elif kind == "chirp":
            chirp = bw_hz / max(0.1, float(duration or 4.0))
            tones = np.array([0.0])
            tone_phases = self._rng.uniform(0, 2 * np.pi, 1)
            pulse_rate = duty = 0.0
            offset_hz -= bw_hz / 2.0
        else:
            # Wideband signals are rendered from a short precomputed
            # band-limited noise table.  Re-FFT-ing a fresh noise block for
            # every signal every 80 ms is surprisingly expensive; looping a
            # table is both cheap and visually indistinguishable on a PSD.
            tones = np.array([0.0])
            tone_phases = self._rng.uniform(0, 2 * np.pi, 1)
            pulse_rate = 0.0
            duty = 0.5
            chirp = 0.0
            if kind == "pulsed":
                pulse_rate = float(self._rng.uniform(20.0, 180.0))
                duty = float(self._rng.uniform(0.05, 0.3))
            elif kind in ("wideband", "noise"):
                kind = "wideband"
        # Keep the signal inside the captured band.
        limit = 0.46 * self.sample_rate
        offset_hz = float(np.clip(offset_hz, -limit, limit))
        noise_table = None
        if kind in ("wideband", "pulsed"):
            m = max(4096, int(self.sample_rate * 0.25))
            raw = (self._rng.normal(size=m)
                   + 1j * self._rng.normal(size=m))
            spec = np.fft.fft(raw)
            ff = np.fft.fftfreq(m, d=1.0 / self.sample_rate)
            mask = np.abs(ff - offset_hz) <= max(200.0, bw_hz / 2.0)
            k = max(1, int(mask.sum()))
            noise_table = (np.fft.ifft(spec * mask)
                           * np.sqrt(m / (2.0 * k))).astype(np.complex64)
        return _SimSignal(
            offset_hz=offset_hz,
            amplitude=amp,
            bandwidth_hz=float(bw_hz),
            kind=kind,
            start=float(start),
            duration=duration,
            phase=float(self._rng.uniform(0, 2 * np.pi)),
            tones=tones,
            tone_phases=tone_phases,
            pulse_rate=pulse_rate,
            duty=duty,
            chirp_hz_s=chirp,
            manual=manual,
            noise_table=noise_table,
        )

    def _build_static(self) -> None:
        # Static emissions are included in the background calibration and are
        # therefore *not* contacts.  They make the display look like a real
        # band instead of a single spike on a flat noise floor.
        self._signals = []
        static = [
            (-0.42, "carrier", 0.0, -58.0),
            (-0.33, "carrier", 0.0, -64.0),
            (-0.21, "wideband", 70e3, -59.0),
            (-0.04, "carrier", 0.0, -56.0),
            (0.10, "carrier", 0.0, -62.0),
            (0.27, "wideband", 22e3, -60.0),
            (0.38, "carrier", 0.0, -57.0),
        ]
        for off, kind, bw, amp in static:
            self._signals.append(
                self._new_signal(off * self.sample_rate, kind, bw, amp,
                                 0.0, None, manual=False)
            )

    # ----------------------------------------------------------------- commands
    def _apply_command(self, name: str, value) -> None:
        if name == "center":
            self.center_freq = float(value)
            self.info_ready.emit(self.config.device_id, {
                "center_freq": self.center_freq,
                "sample_rate": self.sample_rate,
                "gain": self.gain,
            })
        elif name == "sample_rate":
            self.sample_rate = float(value)
            self._build_static()
            self._auto_next = self._sim_time + 1.8
            self.info_ready.emit(self.config.device_id, {
                "center_freq": self.center_freq,
                "sample_rate": self.sample_rate,
                "gain": self.gain,
            })
        elif name == "gain":
            self.gain = float(value)
        elif name == "bandwidth":
            self.bandwidth = float(value)
        elif name == "buffer_size":
            self.buffer_size = max(4096, int(value))

    def inject_signal(self, offset_hz: float | None = None,
                      kind: str | None = None, bw_hz: float | None = None,
                      amp_db: float | None = None,
                      duration: float | None = None) -> None:
        self._manual.put({
            "offset_hz": offset_hz,
            "kind": kind,
            "bw_hz": bw_hz,
            "amp_db": amp_db,
            "duration": duration,
        })

    def _drain_manual(self) -> None:
        while True:
            try:
                req = self._manual.get_nowait()
            except queue.Empty:
                return
            kind = req["kind"] or self._rng.choice(
                ["carrier", "wideband", "pulsed", "chirp"]
            )
            offset = req["offset_hz"]
            if offset is None:
                offset = self._rng.uniform(-0.3, 0.3) * self.sample_rate
            bw = req["bw_hz"]
            if bw is None:
                bw = 0.0 if kind == "carrier" else self._rng.uniform(8e3, 140e3)
            amp = req["amp_db"]
            if amp is None:
                amp = self._rng.uniform(-54.0, -36.0)
            duration = req["duration"] or self._rng.uniform(4.0, 12.0)
            self._signals.append(
                self._new_signal(offset, kind, bw, amp,
                                 self._sim_time + 0.15, duration, manual=True)
            )

    def _spawn_auto(self) -> None:
        if len(self._signals) > 16:
            return
        kind = str(self._rng.choice(["carrier", "wideband", "pulsed",
                                     "chirp", "carrier", "wideband"]))
        offset = self._rng.uniform(-0.34, 0.34) * self.sample_rate
        if kind == "carrier":
            bw = 0.0
        elif kind == "chirp":
            bw = self._rng.uniform(60e3, 220e3)
        elif kind == "pulsed":
            bw = self._rng.uniform(20e3, 180e3)
        else:
            bw = self._rng.uniform(8e3, 160e3)
        amp = self._rng.uniform(-56.0, -34.0)
        duration = self._rng.uniform(2.5, 10.0)
        self._signals.append(
            self._new_signal(offset, kind, bw, amp,
                             self._sim_time + 0.1, duration, manual=False)
        )

    # ---------------------------------------------------------------- rendering
    def _render(self, sig: _SimSignal, t: np.ndarray,
                fs: float) -> np.ndarray | None:
        dt = t - sig.start
        if sig.duration is None:
            valid = np.ones_like(t, dtype=bool)
        else:
            valid = (dt >= 0.0) & (dt <= sig.duration)
            if not valid.any():
                return None
        out = np.zeros_like(t, dtype=np.complex128)
        tv = t[valid]

        if sig.kind in ("wideband", "pulsed"):
            m = tv.size
            table = sig.noise_table
            if table is None or table.size == 0:
                return None
            start = int(round(float(tv[0]) * fs)) % table.size
            idx = (start + np.arange(m)) % table.size
            wave = table[idx].astype(np.complex128)
        elif sig.kind == "chirp":
            dtv = dt[valid]
            phase = (2 * np.pi * (sig.offset_hz * dtv
                                  + 0.5 * sig.chirp_hz_s * dtv * dtv)
                     + sig.phase)
            wave = np.exp(1j * phase)
        else:
            freqs = sig.offset_hz + sig.tones
            phase = (2 * np.pi * freqs[:, None] * tv[None, :]
                     + sig.tone_phases[:, None])
            wave = np.sum(np.exp(1j * phase), axis=0)

        if sig.duration is not None:
            ramp = 0.004
            dtv = dt[valid]
            env = np.clip(dtv / ramp, 0.0, 1.0) * np.clip(
                (sig.duration - dtv) / ramp, 0.0, 1.0
            )
            if sig.kind == "pulsed" and sig.pulse_rate > 0:
                gate = (np.mod(dtv * sig.pulse_rate, 1.0) < sig.duty)
                env = env * gate.astype(float)
            wave = wave * env

        out[valid] = sig.amplitude * wave
        return out

    # --------------------------------------------------------------------- run
    def run(self) -> None:
        self._set_status("running")
        self.info_ready.emit(self.config.device_id, {
            "center_freq": self.center_freq,
            "sample_rate": self.sample_rate,
            "gain": self.gain,
        })
        next_time = time.perf_counter()
        try:
            while not self._stop_event.is_set():
                self._process_commands()
                if self._stop_event.is_set():
                    break
                n = max(
                    4096,
                    int(self.buffer_size or self.sample_rate * 0.08),
                )
                t = self._sim_time + np.arange(n, dtype=np.float64) / self.sample_rate
                iq = self.noise_std * (
                    self._rng.normal(size=n) + 1j * self._rng.normal(size=n)
                )

                for sig in self._signals:
                    part = self._render(sig, t, self.sample_rate)
                    if part is not None:
                        iq += part

                if self._sim_time >= self._auto_next:
                    self._spawn_auto()
                    self._auto_next = self._sim_time + self._rng.uniform(2.2, 5.5)

                self._drain_manual()

                # Drop expired auto signals, but let manual ones linger a bit
                # so the display does not flicker at the very end.
                self._signals = [
                    s for s in self._signals
                    if s.duration is None or t[-1] <= s.start + s.duration + 0.3
                ]

                gain = 10.0 ** ((self.gain - 40.0) / 20.0)
                iq *= gain
                if np.max(np.abs(iq)) > 1.2:
                    iq = (np.clip(iq.real, -1.0, 1.0)
                          + 1j * np.clip(iq.imag, -1.0, 1.0))

                self.iq_ready.emit(IQBlock(
                    device_id=self.config.device_id,
                    samples=iq.astype(np.complex64, copy=False),
                    sample_rate=self.sample_rate,
                    center_freq=self.center_freq,
                    timestamp=time.time(),
                ))
                self._sim_time += n / self.sample_rate

                next_time += n / self.sample_rate
                now = time.perf_counter()
                if next_time > now:
                    time.sleep(min(0.1, next_time - now))
                else:
                    next_time = now
        except Exception as exc:
            self.error.emit(self.config.device_id, f"simulator: {exc}")
            self._set_status("error")
        finally:
            self._set_status("stopped")
