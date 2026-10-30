"""Coordinate one fast monitor per SDR and aggregate drone events."""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

from PySide6.QtCore import QObject, QTimer, Signal

from ..scanner.recorder import ranges_overlap
from .background import DroneBackgroundStore
from .bands import DroneBand, MonitorChunk, chunks_for_bands
from .controller import DroneWatchController
from .features import DroneObservation
from .recorder import DroneRecorder, make_drone_id
from .tracker import DroneEvent, DroneTracker
from .whitelist import DroneWhitelist

log = logging.getLogger(__name__)


class DroneMonitorManager(QObject):
    observation = Signal(object)          # DroneObservation (live graph)
    event_new = Signal(object)            # DroneEvent
    event_updated = Signal(object)        # DroneEvent
    alarm = Signal(object)                # DroneEvent
    status = Signal(str)                  # aggregate status
    device_status = Signal(str, str)      # device_id, text
    finished = Signal(object, str)        # summary, summary path
    error = Signal(str)

    def __init__(self, parent: QObject | None = None) -> None:
        super().__init__(parent)
        self._running = False
        self._stopping = False
        self._starting = False
        self._finalized = False
        self._controllers: list[DroneWatchController] = []
        self._pending = 0
        self._tracker = DroneTracker()
        self._recorder: DroneRecorder | None = None
        self._summary_path = ""
        self._last_emit: dict[str, float] = {}
        self._last_alarm: dict[str, float] = {}
        self._last_alarm_any = 0.0
        self._failure_message: str | None = None
        self._min_alarm_hits = 3
        self._min_alarm_conf = 0.70
        self._alarm_count = 0
        self._record_iq = True
        self._max_clips = 100
        self._clip_count = 0
        self._whitelist: DroneWhitelist | None = None
        self._background_store: DroneBackgroundStore | None = None
        self._expire = QTimer(self)
        self._expire.setInterval(2000)
        self._expire.timeout.connect(self._expire_events)
        self._started = 0.0

    # ------------------------------------------------------------------ state
    @property
    def running(self) -> bool:
        return self._running

    @property
    def events(self) -> list[DroneEvent]:
        return self._tracker.events()

    def summary(self) -> dict[str, Any]:
        return self._tracker.summary()

    # ------------------------------------------------------------------ start
    def start(
        self,
        sessions: list,
        bands: list[DroneBand],
        *,
        sample_rate: float = 20.48e6,
        dwell_ms: float = 40.0,
        threshold_db: float = 6.0,
        min_alarm_hits: int = 3,
        min_alarm_conf: float = 0.70,
        record_iq: bool = True,
        max_clips: int = 100,
        whitelist: DroneWhitelist | None = None,
        background_store: DroneBackgroundStore | None = None,
        use_all_devices: bool = True,
        out_dir: str | Path = "drone_logs",
    ) -> bool:
        if self._running:
            return False
        if not sessions:
            self.error.emit("Нет устройств для мониторинга.")
            return False
        if not bands:
            self.error.emit("Не выбрано ни одной полосы.")
            return False
        targets = list(sessions) if use_all_devices else list(sessions[:1])
        targets = [session for session in targets if session is not None]
        if not targets:
            self.error.emit("Нет доступных устройств.")
            return False

        chunks = chunks_for_bands(bands, sample_rate)
        if not chunks:
            self.error.emit("Не удалось построить частотные куски.")
            return False

        assigned: list[list[MonitorChunk]] = [[] for _ in targets]
        for index, chunk in enumerate(chunks):
            assigned[index % len(targets)].append(chunk)

        drone_id = make_drone_id()
        self._recorder = DroneRecorder(
            Path(out_dir) / f"drone_{drone_id}",
            drone_id=drone_id,
            sample_rate=sample_rate,
            dwell_ms=dwell_ms,
            threshold_db=threshold_db,
            bands=[band.key for band in bands],
            devices=[
                {
                    "device_id": session.config.device_id,
                    "name": session.config.name,
                    "kind": session.config.kind,
                    "uri": session.config.uri,
                }
                for session in targets
            ],
        )
        self._tracker.reset()
        self._controllers.clear()
        self._last_emit.clear()
        self._last_alarm.clear()
        self._last_alarm_any = 0.0
        self._failure_message = None
        self._min_alarm_hits = max(1, int(min_alarm_hits))
        self._min_alarm_conf = max(0.0, min(1.0, float(min_alarm_conf)))
        self._alarm_count = 0
        self._record_iq = bool(record_iq)
        self._max_clips = max(0, int(max_clips))
        self._clip_count = 0
        self._whitelist = whitelist
        self._background_store = background_store
        self._finalized = False
        self._stopping = False
        self._starting = True
        self._pending = 0
        self._started = time.monotonic()
        self._running = True
        self._expire.start()

        for session, controller_chunks in zip(targets, assigned):
            if not controller_chunks:
                continue
            controller = DroneWatchController(
                session,
                controller_chunks,
                sample_rate=sample_rate,
                dwell_ms=dwell_ms,
                threshold_db=threshold_db,
                background_store=background_store,
                parent=self,
            )
            controller.observation.connect(self._on_observation)
            controller.status.connect(self.device_status)
            controller.chunk_started.connect(self._on_chunk_started)
            controller.error.connect(self._on_device_error)
            controller.finished.connect(self._on_controller_finished)
            if not controller.start():
                controller.deleteLater()
                continue
            self._controllers.append(controller)
            self._pending += 1
        self._starting = False

        if not self._controllers:
            self._running = False
            self._expire.stop()
            self.error.emit("Не удалось запустить ни одного устройства.")
            return False

        names = ", ".join(session.config.name for session in targets)
        self.status.emit(
            f"Мониторинг: {len(bands)} полос, {len(chunks)} кусков, "
            f"{len(self._controllers)} устр. ({names})"
        )
        return True

    # ------------------------------------------------------------------- data
    def _on_observation(self, obs: DroneObservation) -> None:
        if not self._running:
            return
        self.observation.emit(obs)
        event, is_new = self._tracker.update(obs)
        if event is None:
            return
        if self._whitelist is not None:
            entry = self._whitelist.match(event)
            if entry is not None:
                event.whitelisted = True
                event.whitelist_name = entry.name
        self._maybe_record_iq(event, obs)
        now = time.monotonic()
        if is_new:
            self._last_emit[event.event_id] = now
            if self._recorder is not None:
                self._recorder.log_event(event, kind="new")
            self.event_new.emit(event)
            self._maybe_alarm(event, now)
            return
        if now - self._last_emit.get(event.event_id, 0.0) >= 0.5:
            self._last_emit[event.event_id] = now
            self.event_updated.emit(event)
        # Full updates are kept in memory and in summary.json; events.jsonl
        # only records the birth/death of an event so a multi-hour watch does
        # not grow into hundreds of megabytes.
        self._maybe_alarm(event, now)

    def _maybe_record_iq(self, event: DroneEvent, obs: DroneObservation) -> None:
        if not self._record_iq or self._recorder is None:
            return
        if event.clip_path:
            return
        if self._clip_count >= self._max_clips:
            return
        if obs.iq_samples is None or obs.iq_samples.size == 0:
            return
        try:
            path = self._recorder.save_clip(
                event,
                obs.iq_samples,
                sample_rate=obs.sample_rate,
                center_hz=obs.center_hz,
                device_id=obs.device_id,
            )
        except Exception as exc:
            log.warning("drone IQ clip write failed: %s", exc)
            return
        event.clip_path = str(path)
        event.clip_samples = int(obs.iq_samples.size)
        event.clip_sample_rate = float(obs.sample_rate)
        event.clip_center_hz = float(obs.center_hz)
        self._clip_count += 1

    def _maybe_alarm(self, event: DroneEvent, now: float) -> None:
        if not event.drone_like or event.whitelisted:
            return
        # A single short observation is usually Wi-Fi/Bluetooth/Zigbee or a
        # noise burst.  Only alarm after the event is confirmed by several
        # passes and has a high confidence.
        if event.count < self._min_alarm_hits:
            return
        if event.confidence < self._min_alarm_conf:
            return
        if now - self._last_alarm.get(event.event_id, 0.0) < 12.0:
            return
        if now - self._last_alarm_any < 6.0:
            return
        self._last_alarm[event.event_id] = now
        self._last_alarm_any = now
        self._alarm_count += 1
        self.alarm.emit(event)

    def _on_chunk_started(self, chunk: MonitorChunk) -> None:
        if not self._running:
            return
        self.status.emit(
            f"{chunk.band.name}: {chunk.index + 1}/{chunk.total} · "
            f"{chunk.center_hz / 1e6:.3f} МГц"
        )

    def _expire_events(self) -> None:
        changed = self._tracker.expire()
        for event in changed:
            if self._recorder is not None:
                self._recorder.log_event(event, kind="ended")
            self.event_updated.emit(event)

    # ------------------------------------------------------------------- stop
    def stop(self) -> None:
        if not self._running:
            return
        self._stopping = True
        self._running = False
        self._expire.stop()
        controllers = list(self._controllers)
        self._controllers.clear()
        if not controllers:
            self._finalize()
            return
        for controller in controllers:
            try:
                controller.stop()
            except Exception:
                log.exception("drone controller stop failed")
                self._pending -= 1
        if self._pending <= 0:
            self._finalize()

    def _on_controller_finished(self, device_id: str) -> None:
        self._pending -= 1
        if self._pending <= 0 and (self._stopping or not self._running):
            self._finalize()

    def _on_device_error(self, device_id: str, message: str) -> None:
        self.error.emit(f"{device_id}: {message}")
        text = message.lower()
        fatal = (
            "broken pipe" in text
            or "no device" in text
            or "no such device" in text
        )
        if (fatal and not self._starting):
            self.fail(
                f"{device_id}: {message}. "
                "Мониторинг остановлен, чтобы не потерять часть полос. "
                "Проверьте USB-кабель/питание или используйте Ethernet."
            )

    def fail(self, message: str) -> None:
        """Abort monitoring after a fatal device/session error."""
        if not self._running:
            self.error.emit(message)
            return
        if self._failure_message:
            return
        self._failure_message = message
        self.stop()

    def _finalize(self) -> None:
        if self._finalized:
            return
        self._finalized = True
        for event in self._tracker.events():
            event.active = False
        summary = self._tracker.summary()
        summary["duration_s"] = round(time.monotonic() - self._started, 2)
        summary["alarms"] = int(self._alarm_count)
        summary["alarm_hits"] = int(self._min_alarm_hits)
        summary["alarm_confidence"] = round(float(self._min_alarm_conf), 3)
        summary["iq_clips"] = int(self._clip_count)
        summary["whitelisted_events"] = sum(
            1 for event in self._tracker.events() if event.whitelisted
        )
        if self._failure_message:
            summary["failure"] = self._failure_message
        if self._recorder is not None:
            try:
                self._summary_path = str(self._recorder.finalize(
                    summary, self._tracker.events()
                ))
            except Exception as exc:
                log.exception("drone log write failed")
                self.error.emit(f"Не удалось сохранить журнал: {exc}")
        self.finished.emit(summary, self._summary_path)

    # ------------------------------------------------------------------ helper
    def stop_if_overlapping(self, start_hz: float, end_hz: float) -> bool:
        """Stop if the range overlaps a monitored band (used by the scanner)."""
        if not self._running:
            return False
        for event in self._tracker.events(include_inactive=False):
            if ranges_overlap(
                {"range_start_hz": start_hz, "range_end_hz": end_hz},
                {"range_start_hz": event.freq_min_hz,
                 "range_end_hz": event.freq_max_hz},
            ):
                self.stop()
                return True
        return False
