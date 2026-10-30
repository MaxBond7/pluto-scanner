"""Playback of a recorded cf32 IQ file through the normal DSP pipeline."""
from __future__ import annotations

import time

import numpy as np

from ..model import DeviceConfig, IQBlock
from ..recordings import load_info
from .base import DeviceWorker


class IqFileWorker(DeviceWorker):
    """Read a recording at real-time pace, like a radio stuck on one LO."""

    def __init__(self, config: DeviceConfig) -> None:
        super().__init__(config)
        self.info = load_info(config.uri)
        if self.info is not None:
            self.center_freq = float(self.info.center_freq)
            self.sample_rate = float(self.info.sample_rate)
            self.config.center_freq = self.center_freq
            self.config.sample_rate = self.sample_rate
        self._data = None
        self._chunk = max(4096, int(self.sample_rate * 0.08))

    def _apply_command(self, name: str, value) -> None:
        if name == "buffer_size":
            self._chunk = max(4096, int(value))
            return
        # Frequency, gain and bandwidth are properties of the recording.
        # Re-emit the real metadata so the UI snaps back instead of lying.
        if name in ("center", "sample_rate", "gain", "bandwidth"):
            self.info_ready.emit(self.config.device_id, {
                "center_freq": self.center_freq,
                "sample_rate": self.sample_rate,
                "gain": float(self.config.gain),
                "playback": True,
            })

    def run(self) -> None:
        self._set_status("starting")
        if self.info is None or not self.info.path.exists():
            self.error.emit(
                self.config.device_id,
                f"Запись не найдена: {self.config.uri}",
            )
            self._set_status("error")
            return
        try:
            self._data = np.memmap(
                self.info.path, dtype=np.complex64, mode="r"
            )
        except Exception as exc:
            self.error.emit(self.config.device_id, f"Не открыть запись: {exc}")
            self._set_status("error")
            return

        self.info_ready.emit(self.config.device_id, {
            "center_freq": self.center_freq,
            "sample_rate": self.sample_rate,
            "gain": float(self.config.gain),
            "playback": True,
            "samples": int(self._data.size),
        })
        self._set_status("running")
        sent = 0
        total = int(self._data.size)
        wall_start = time.perf_counter()
        try:
            while not self._stop_event.is_set() and sent < total:
                self._process_commands()
                if self._stop_event.is_set():
                    break
                count = min(self._chunk, total - sent)
                if count <= 0:
                    break
                block = np.array(
                    self._data[sent:sent + count],
                    dtype=np.complex64,
                    copy=True,
                )
                self.iq_ready.emit(IQBlock(
                    device_id=self.config.device_id,
                    samples=block,
                    sample_rate=self.sample_rate,
                    center_freq=self.center_freq,
                    timestamp=time.time(),
                ))
                sent += count
                target = wall_start + sent / max(1.0, self.sample_rate)
                now = time.perf_counter()
                if target > now:
                    time.sleep(min(0.1, target - now))
                elif now - target > 0.5:
                    # The UI or disk fell far behind; resync instead of
                    # emitting a burst of stale blocks.
                    wall_start = now - sent / max(1.0, self.sample_rate)
        except Exception as exc:
            self.error.emit(self.config.device_id, f"Воспроизведение: {exc}")
            self._set_status("error")
            return
        finally:
            self._data = None
        self._set_status("stopped")
