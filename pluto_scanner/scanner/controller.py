"""Qt state machine for a real full-range sweep.

The scanner does not move the LO from a background thread: it retunes through
:class:`DeviceSession`, then waits for the already-running IQ pipeline to
deliver frames whose centre matches the new LO.  That keeps a single owner of
the device and lets the normal spectrum/waterfall keep working.

One step is completed after ``dwell_frames`` matching frames.  The average PSD
is analysed with :func:`pluto_scanner.scanner.peaks.find_peaks`; the step is
written to JSON immediately.  A full bundle is written when the sweep ends,
stops, or times out.
"""
from __future__ import annotations

import logging
import time
from pathlib import Path
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, QTimer, Signal

from ..config import PLUTO_MAX_FREQ, PLUTO_MIN_FREQ, format_freq
from .compare import (
    background_compatible,
    compare_background_files,
    save_report,
)
from .peaks import find_peaks
from .recorder import ScanRecorder, find_latest_background, load_bundle, make_scan_id

log = logging.getLogger(__name__)


class ScanController(QObject):
    """Run one sweep over ``[start_hz, end_hz]`` on a live session."""

    started = Signal(int, float, float)        # total steps, start, end
    progress = Signal(int, int, float)         # index, total, center_hz
    step_ready = Signal(object)                # step record (dict)
    finished = Signal(object, str)             # result dict, bundle path
    stopped = Signal(object, str)              # result dict, bundle path
    failed = Signal(str)
    compare_ready = Signal(object, str)        # report dict, report path
    pause_changed = Signal(bool)

    def __init__(
        self,
        session,
        *,
        start_hz: float = PLUTO_MIN_FREQ,
        end_hz: float = PLUTO_MAX_FREQ,
        step_hz: float = 800e3,
        out_dir: str | Path = "scan_logs",
        threshold_db: float = 8.0,
        dwell_frames: int = 2,
        step_timeout_s: float = 4.0,
        compare_to: str | Path | None = None,
        auto_compare: bool = True,
        parent: QObject | None = None,
    ) -> None:
        super().__init__(parent)
        self.session = session
        self.start_hz = float(start_hz)
        self.end_hz = float(end_hz)
        self.step_hz = max(1000.0, float(step_hz))
        self.out_dir = Path(out_dir)
        self.threshold_db = float(threshold_db)
        self.dwell_frames = max(1, int(dwell_frames))
        self.step_timeout_s = max(0.5, float(step_timeout_s))
        self.compare_to = Path(compare_to) if compare_to else None
        self.auto_compare = bool(auto_compare)

        self._running = False
        self._paused = False
        self._centers = np.empty(0, dtype=np.float64)
        self._index = 0
        self._current_center = 0.0
        self._frames: list[tuple[np.ndarray, np.ndarray]] = []
        self._step_started = 0.0
        self._consecutive_missed = 0
        self._started_at = 0.0
        self._recorder: ScanRecorder | None = None
        self._scan_dir: Path | None = None
        self._original_center: float | None = None
        self._audio_was_enabled = False

        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._check_timeout)

    # ------------------------------------------------------------------ state
    @property
    def running(self) -> bool:
        return self._running

    @property
    def paused(self) -> bool:
        return self._paused

    @property
    def total(self) -> int:
        return int(self._centers.size)

    @property
    def index(self) -> int:
        return int(self._index)

    @property
    def current_center_hz(self) -> float:
        return float(self._current_center)

    @property
    def scan_dir(self) -> Path | None:
        return self._scan_dir

    # ------------------------------------------------------------------ start
    def start(self) -> bool:
        if self._running:
            return False
        start = min(self.start_hz, self.end_hz)
        end = max(self.start_hz, self.end_hz)
        if end - start < 1.0:
            self.failed.emit("Диапазон сканирования пуст: начало и конец совпадают.")
            return False
        self.start_hz, self.end_hz = start, end
        # Centre the first/last LO so the captured bands exactly cover
        # [start, end] instead of tuning half a band outside the range.
        half_band = float(self.session.config.sample_rate) * 0.5
        first = start + half_band
        last = end - half_band
        if last <= first:
            centers = np.array([(start + end) / 2.0], dtype=np.float64)
        else:
            centers = np.arange(first, last, self.step_hz, dtype=np.float64)
            if centers.size == 0 or centers[-1] < last - 1.0:
                centers = np.append(centers, last)
        self._centers = centers
        if self._centers.size == 0:
            self.failed.emit("Не удалось построить шаги сканирования.")
            return False

        scan_id = make_scan_id()
        self._scan_dir = self.out_dir / f"scan_{scan_id}"
        try:
            self._recorder = ScanRecorder(
                self._scan_dir,
                scan_id=scan_id,
                range_start_hz=start,
                range_end_hz=end,
                step_hz=self.step_hz,
                sample_rate=float(self.session.config.sample_rate),
                fft_size=int(self.session.config.fft_size),
                threshold_db=self.threshold_db,
                dwell_frames=self.dwell_frames,
                device_name=self.session.config.name,
                device_kind=self.session.config.kind,
                device_uri=self.session.config.uri,
                gain_db=self.session.config.gain,
                bandwidth_hz=self.session.config.bandwidth,
            )
        except Exception as exc:
            log.exception("scan recorder init failed")
            self.failed.emit(f"Не удалось создать папку скана: {exc}")
            return False

        self._running = True
        self._paused = False
        self._index = 0
        self._consecutive_missed = 0
        self._started_at = time.monotonic()
        self._original_center = float(self.session.config.center_freq)
        self._audio_was_enabled = bool(self.session.audio_enabled)
        try:
            self.session.set_audio_enabled(False)
            self.session.spectrum_updated.connect(self._on_frame)
        except Exception:
            pass

        self.started.emit(self.total, start, end)
        self._begin_step()
        return True

    # ------------------------------------------------------------------- step
    def _begin_step(self) -> None:
        if not self._running or self._recorder is None:
            return
        if self._index >= self.total:
            self._finish(stopped=False)
            return
        self._current_center = float(self._centers[self._index])
        self._frames = []
        self._step_started = time.monotonic()
        try:
            # DeviceSession updates config immediately and queues the LO change
            # for the worker thread.
            self.session.set_center_freq(self._current_center)
        except Exception as exc:
            log.warning("scan retune failed: %s", exc)
        self.progress.emit(self._index, self.total, self._current_center)
        self._timer.start()

    def _on_frame(self, device_id: str, frame) -> None:
        if not self._running or self._paused or self._recorder is None:
            return
        if device_id != self.session.config.device_id:
            return
        if frame is None or len(frame.psd) == 0:
            return
        # Tight enough to reject a frame from the previous (very close) centre
        # on short sweeps, yet forgiving of LO rounding on the hardware.
        tolerance = max(5e3, min(self.step_hz * 0.25, 100e3))
        if abs(float(frame.center_freq) - self._current_center) > tolerance:
            return
        self._frames.append(
            (np.asarray(frame.freqs, dtype=np.float64),
             np.asarray(frame.psd, dtype=np.float64))
        )
        # Keep only the newest dwell frames: after a retune the first buffer
        # can still belong to the previous LO.
        if len(self._frames) > self.dwell_frames:
            self._frames = self._frames[-self.dwell_frames:]
        if len(self._frames) >= self.dwell_frames:
            self._complete_step()

    def _complete_step(self) -> None:
        if not self._running or self._recorder is None:
            return
        self._timer.stop()
        freqs = self._frames[-1][0]
        psd = np.mean(
            np.stack([item[1] for item in self._frames], axis=0), axis=0
        )
        try:
            peak_result = find_peaks(
                freqs,
                psd,
                threshold_db=self.threshold_db,
                center_hz=self._current_center,
            )
            record = self._recorder.add_step(
                index=self._index,
                center_hz=self._current_center,
                freqs=freqs,
                psd=psd,
                noise_floor_db=peak_result.noise_floor_db,
                peaks=peak_result.peaks,
                status="ok",
                dwell_frames=len(self._frames),
            )
        except Exception as exc:
            log.exception("scan step failed")
            record = self._recorder.add_missed(
                index=self._index,
                center_hz=self._current_center,
                status=f"error: {exc}",
            )
        self._consecutive_missed = 0
        self.step_ready.emit(record)
        self._index += 1
        if self._index >= self.total:
            self._finish(stopped=False)
        else:
            self._begin_step()

    def _check_timeout(self) -> None:
        if not self._running or self._paused or self._recorder is None:
            return
        elapsed = time.monotonic() - self._step_started
        if elapsed < self.step_timeout_s:
            return
        log.warning(
            "scan step %s at %s timed out after %.1f s",
            self._index, format_freq(self._current_center), elapsed,
        )
        self._timer.stop()
        record = self._recorder.add_missed(
            index=self._index, center_hz=self._current_center
        )
        self.step_ready.emit(record)
        self._index += 1
        self._consecutive_missed += 1
        if self._consecutive_missed >= 4:
            self._finish(
                stopped=True,
                failure="Нет данных от устройства: четыре шага подряд без спектра. "
                        "Проверьте подключение Pluto.",
            )
            return
        if self._index >= self.total:
            self._finish(stopped=False)
        else:
            self._begin_step()

    # ------------------------------------------------------------------ stop
    def pause(self) -> None:
        if not self._running or self._paused:
            return
        self._paused = True
        self._timer.stop()
        self.pause_changed.emit(True)

    def resume(self) -> None:
        if not self._running or not self._paused:
            return
        self._paused = False
        self._frames = []
        self._step_started = time.monotonic()
        try:
            self.session.set_center_freq(self._current_center)
        except Exception:
            pass
        self._timer.start()
        self.pause_changed.emit(False)

    def stop(self) -> None:
        if not self._running:
            return
        self._finish(stopped=True)

    def _finish(self, *, stopped: bool, failure: str | None = None) -> None:
        if not self._running:
            return
        self._running = False
        self._paused = False
        self._timer.stop()
        try:
            self.session.spectrum_updated.disconnect(self._on_frame)
        except (RuntimeError, TypeError):
            pass
        if self._recorder is None:
            return
        try:
            bundle, path = self._recorder.finalize(stopped=stopped or bool(failure))
        except Exception as exc:
            log.exception("scan bundle write failed")
            self.failed.emit(f"Не удалось сохранить результат скана: {exc}")
            self._restore_device()
            return

        result = {
            "scan_id": bundle.get("scan_id"),
            "path": str(path),
            "planned_total": int(self.total),
            "steps_total": bundle.get("steps_total", 0),
            "steps_completed": bundle.get("steps_completed", 0),
            "steps_missed": bundle.get("steps_missed", 0),
            "duration_s": bundle.get("duration_s", 0.0),
            "peak_count": bundle.get("peak_count", 0),
            "stopped": bool(stopped),
            "failure": failure,
            "new_contacts": None,
            "compare_path": None,
        }

        if self.auto_compare and not failure and self.compare_to is not None:
            try:
                if self.compare_to.exists():
                    old_bundle = load_bundle(self.compare_to)
                    compatible, warnings = background_compatible(
                        old_bundle, bundle
                    )
                    if not compatible:
                        log.warning(
                            "auto comparison skipped: %s", " ".join(warnings)
                        )
                        result["compare_skipped"] = " ".join(warnings)
                    else:
                        report = compare_background_files(
                            self.compare_to, path
                        )
                        report_path = save_report(
                            report, self._scan_dir / "compare.json"
                        )
                        result["new_contacts"] = int(
                            report["counts"].get("new", 0)
                        )
                        result["stronger_contacts"] = int(
                            report["counts"].get("stronger", 0)
                        )
                        result["compare_path"] = str(report_path)
                        result["compare_warnings"] = warnings
                        self.compare_ready.emit(report, str(report_path))
            except Exception as exc:
                log.warning("scan comparison failed: %s", exc)

        self._restore_device()
        result["restore_center_hz"] = self._original_center
        self.pause_changed.emit(False)

        if failure:
            self.failed.emit(f"{failure} Результат: {path}")
        elif stopped:
            self.stopped.emit(result, str(path))
        else:
            self.finished.emit(result, str(path))

    def _restore_device(self) -> None:
        if self._original_center is not None:
            try:
                self.session.set_center_freq(self._original_center)
            except Exception:
                pass
        try:
            self.session.set_audio_enabled(self._audio_was_enabled)
        except Exception:
            pass


def latest_background(out_dir: str | Path = "scan_logs") -> Path | None:
    """Convenience wrapper used by the UI before starting a scan."""
    return find_latest_background(out_dir)
