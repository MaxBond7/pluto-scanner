"""Optional audio output.

sounddevice is imported lazily so the scanner still runs on machines without
PortAudio or without an output device.  Audio is a convenience feature, not a
prerequisite for the waterfall or the contact list.
"""
from __future__ import annotations

import logging
import threading

import numpy as np

log = logging.getLogger(__name__)


class AudioSink:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._buffer = np.zeros(0, dtype=np.float32)
        self._rate = 0
        self._stream = None
        self._sd = None
        self.error: str | None = None
        self.underruns = 0

    @property
    def running(self) -> bool:
        return self._stream is not None

    @property
    def rate(self) -> int:
        return self._rate

    def start(self, rate: float) -> bool:
        rate = int(round(rate))
        if rate <= 0:
            self.error = "invalid audio rate"
            return False
        if self._stream is not None and self._rate == rate:
            return True
        self.stop()
        try:
            import sounddevice as sd  # lazy, optional
            self._sd = sd
            self._stream = sd.OutputStream(
                samplerate=rate,
                channels=1,
                dtype="float32",
                callback=self._callback,
                blocksize=0,
                latency="low",
            )
            self._stream.start()
            self._rate = rate
            self.error = None
            with self._lock:
                self._buffer = np.zeros(0, dtype=np.float32)
            return True
        except Exception as exc:
            self._stream = None
            self.error = str(exc)
            log.warning("Audio start failed: %s", exc)
            return False

    def stop(self) -> None:
        stream = self._stream
        self._stream = None
        if stream is not None:
            try:
                stream.stop()
                stream.close()
            except Exception:
                pass
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)

    def clear(self) -> None:
        with self._lock:
            self._buffer = np.zeros(0, dtype=np.float32)

    def push(self, samples: np.ndarray) -> None:
        if self._stream is None or samples is None:
            return
        samples = np.asarray(samples, dtype=np.float32).ravel()
        if samples.size == 0:
            return
        with self._lock:
            self._buffer = np.concatenate((self._buffer, samples))
            max_len = max(1024, int(self._rate * 2.0))
            if self._buffer.size > max_len:
                self._buffer = self._buffer[-max_len:]

    def _callback(self, outdata, frames, time_info, status) -> None:
        if status:
            self.underruns += 1
        with self._lock:
            n = min(frames, self._buffer.size)
            if n:
                outdata[:n, 0] = self._buffer[:n]
                self._buffer = self._buffer[n:]
            if n < frames:
                outdata[n:, 0] = 0.0

    def shutdown(self) -> None:
        self.stop()
