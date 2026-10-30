"""Fast per-device band monitor used by the drone detector.

Each controller owns one device.  It retunes across a list of wide chunks,
waits for two fresh IQ blocks per chunk, extracts features from the second
block, and then moves on.  The Qt event loop stays responsive because every
step is short and the worker thread does the USB/Ethernet reading.
"""
from __future__ import annotations

import logging
import time

from PySide6.QtCore import QObject, QTimer, Signal

from ..config import format_freq
from ..dsp.spectrum import SpectrumAnalyzer
from .bands import MonitorChunk
from .features import DroneObservation, QUIET, analyze_iq

log = logging.getLogger(__name__)


class DroneWatchController(QObject):
    observation = Signal(object)          # DroneObservation
    status = Signal(str, str)             # device_id, text
    chunk_started = Signal(object)        # MonitorChunk
    error = Signal(str, str)              # device_id, message
    finished = Signal(str)                # device_id

    def __init__(
        self,
        session,
        chunks: list[MonitorChunk],
        *,
        sample_rate: float,
        dwell_ms: float = 40.0,
        threshold_db: float = 6.0,
        min_blocks: int = 2,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.chunks = list(chunks)
        self.sample_rate = max(1.0e6, float(sample_rate))
        self.dwell_ms = max(5.0, float(dwell_ms))
        self.threshold_db = float(threshold_db)
        self.min_blocks = max(1, int(min_blocks))

        self._running = False
        self._index = 0
        self._blocks = 0
        self._passes = 0
        self._chunk_started = 0.0
        self._last_block = None
        self._analyzed_current = False
        self._original: dict | None = None
        self._noise_floors: dict[str, float] = {}
        self._analyzer = SpectrumAnalyzer(nfft=4096)

        self._timer = QTimer(self)
        self._timer.setInterval(250)
        self._timer.timeout.connect(self._on_timeout)

    # ------------------------------------------------------------------ state
    @property
    def running(self) -> bool:
        return self._running

    @property
    def passes(self) -> int:
        return self._passes

    @property
    def device_id(self) -> str:
        return self.session.config.device_id

    # ------------------------------------------------------------------ start
    def start(self) -> bool:
        if self._running:
            return False
        if not self.chunks:
            self.error.emit(self.device_id, "Нет полос для мониторинга.")
            return False
        config = self.session.config
        self._original = {
            "center_freq": float(config.center_freq),
            "sample_rate": float(config.sample_rate),
            "bandwidth": float(config.bandwidth),
            "gain": float(config.gain),
            "audio": bool(self.session.audio_enabled),
        }
        try:
            self.session.set_monitor_mode(True)
            self.session.set_audio_enabled(False)
            self.session.set_sample_rate(self.sample_rate)
            self.session.set_bandwidth(
                max(1.0e6, min(self.sample_rate, self.sample_rate * 0.8))
            )
            self.session.set_buffer_size(int(self.sample_rate * 0.02))
            self.session.iq_ready.connect(self._on_iq)
        except Exception as exc:
            log.exception("drone controller start failed")
            self.session.set_monitor_mode(False)
            self._restore_device()
            self.error.emit(self.device_id, f"Не удалось запустить монитор: {exc}")
            return False

        self._running = True
        self._index = 0
        self._passes = 0
        self._begin_chunk()
        return True

    # ------------------------------------------------------------------- chunk
    def _begin_chunk(self) -> None:
        if not self._running:
            return
        if self._index >= len(self.chunks):
            self._index = 0
            self._passes += 1
        chunk = self.chunks[self._index]
        self._blocks = 0
        self._last_block = None
        self._analyzed_current = False
        self._chunk_started = time.monotonic()
        try:
            self.session.set_center_freq(chunk.center_hz)
        except Exception as exc:
            log.warning("drone retune failed: %s", exc)
        self._timer.start()
        self.chunk_started.emit(chunk)
        self.status.emit(
            self.device_id,
            f"{chunk.band.name} · {chunk.index + 1}/{chunk.total} · "
            f"{format_freq(chunk.center_hz)}",
        )

    def _on_iq(self, device_id: str, block) -> None:
        if not self._running or block is None:
            return
        if device_id != self.device_id:
            return
        if abs(float(block.sample_rate) - self.sample_rate) > 1.0:
            return
        tolerance = max(20e3, min(self.sample_rate * 0.01, 400e3))
        chunk = self.chunks[self._index]
        if abs(float(block.center_freq) - chunk.center_hz) > tolerance:
            return
        self._blocks += 1
        self._last_block = block
        if self._blocks < self.min_blocks:
            return
        self._analyze_block(block)
        self._next_chunk()

    def _on_timeout(self) -> None:
        if not self._running:
            return
        if not self._analyzed_current and self._last_block is not None:
            self._analyze_block(self._last_block)
        else:
            chunk = self.chunks[self._index]
            self.status.emit(
                self.device_id,
                f"{chunk.band.name} · нет данных · {format_freq(chunk.center_hz)}",
            )
        self._next_chunk()

    def _analyze_block(self, block) -> None:
        chunk = self.chunks[self._index]
        baseline = self._noise_floors.get(chunk.band.key)
        try:
            obs = analyze_iq(
                block.samples,
                block.sample_rate,
                block.center_freq,
                chunk.band,
                device_id=self.device_id,
                threshold_db=self.threshold_db,
                analyzer=self._analyzer,
                noise_floor_db=baseline,
            )
        except Exception as exc:
            log.exception("drone feature extraction failed")
            self.error.emit(self.device_id, f"Ошибка анализа: {exc}")
            self._analyzed_current = True
            return
        if obs is None:
            self._analyzed_current = True
            return
        self._analyzed_current = True
        self._update_baseline(obs)
        self.observation.emit(obs)

    def _update_baseline(self, obs: DroneObservation) -> None:
        raw = float(obs.extra.get("median_floor_db", obs.noise_floor_db))
        if obs.class_key == QUIET or obs.busy_fraction < 0.15:
            old = self._noise_floors.get(obs.band_key)
            self._noise_floors[obs.band_key] = (
                raw if old is None else 0.8 * old + 0.2 * raw
            )

    def _next_chunk(self) -> None:
        if not self._running:
            return
        self._timer.stop()
        self._index += 1
        if self._index >= len(self.chunks):
            self._index = 0
            self._passes += 1
        self._begin_chunk()

    # ------------------------------------------------------------------- stop
    def stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self._timer.stop()
        try:
            self.session.iq_ready.disconnect(self._on_iq)
        except (RuntimeError, TypeError):
            pass
        try:
            self.session.set_monitor_mode(False)
        except Exception:
            pass
        self._restore_device()
        self.finished.emit(self.device_id)

    def _restore_device(self) -> None:
        original = self._original
        if not original:
            return
        try:
            self.session.set_sample_rate(original["sample_rate"])
            self.session.set_buffer_size(int(original["sample_rate"] * 0.08))
            self.session.set_bandwidth(original["bandwidth"])
            self.session.set_center_freq(original["center_freq"])
            self.session.set_gain(original["gain"])
            self.session.set_audio_enabled(original["audio"])
            self.session.reset_background()
        except Exception:
            log.exception("drone restore failed")
