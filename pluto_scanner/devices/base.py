"""Common QThread plumbing for IQ producers."""
from __future__ import annotations

import queue
import threading
from typing import Any

from PySide6.QtCore import QThread, Signal

from ..model import DeviceConfig, IQBlock


class DeviceWorker(QThread):
    """One worker thread per Pluto/simulator.

    The worker only produces IQ blocks.  Spectrum, detection, tracking and
    demodulation all happen in the GUI thread's DeviceSession, so a slow
    device cannot corrupt DSP state and a slow UI cannot change IQ timing.
    """

    iq_ready = Signal(object)                 # IQBlock
    status_changed = Signal(str, str)         # device_id, status
    error = Signal(str, str)                  # device_id, message
    info_ready = Signal(str, dict)            # device_id, actual config

    def __init__(self, config: DeviceConfig) -> None:
        super().__init__()
        self.config = config
        self.center_freq = float(config.center_freq)
        self.sample_rate = float(config.sample_rate)
        self.gain = float(config.gain)
        self.bandwidth = float(config.bandwidth)
        self._stop_event = threading.Event()
        self._commands: queue.Queue[tuple[str, Any]] = queue.Queue()
        self._status = "idle"

    # ---------------------------------------------------------------- commands
    def set_center_freq(self, hz: float) -> None:
        self._commands.put(("center", float(hz)))

    def set_sample_rate(self, hz: float) -> None:
        self._commands.put(("sample_rate", float(hz)))

    def set_gain(self, db: float) -> None:
        self._commands.put(("gain", float(db)))

    def set_bandwidth(self, hz: float) -> None:
        self._commands.put(("bandwidth", float(hz)))

    def set_buffer_size(self, samples: int) -> None:
        self._commands.put(("buffer_size", max(4096, int(samples))))

    def inject_signal(self, **kwargs: Any) -> None:
        """Optional; only the simulator implements it."""

    def _process_commands(self) -> None:
        while True:
            try:
                name, value = self._commands.get_nowait()
            except queue.Empty:
                return
            try:
                self._apply_command(name, value)
            except Exception as exc:
                self.error.emit(self.config.device_id, f"command {name}: {exc}")

    def _apply_command(self, name: str, value: Any) -> None:
        raise NotImplementedError

    # ------------------------------------------------------------------ status
    def _set_status(self, status: str) -> None:
        self._status = status
        self.status_changed.emit(self.config.device_id, status)

    @property
    def status(self) -> str:
        return self._status

    # ------------------------------------------------------------------- run
    def run(self) -> None:  # pragma: no cover - overridden
        raise NotImplementedError

    def stop(self) -> None:
        self._stop_event.set()
        self.requestInterruption()
        if self.isRunning():
            self.wait(3000)
