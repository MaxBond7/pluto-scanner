"""Per-device DSP session: IQ -> spectrum -> detections -> contacts -> audio."""
from __future__ import annotations

import time
from collections import deque
from typing import Any

import numpy as np
from PySide6.QtCore import QObject, Signal, Slot

from .config import (
    CALIBRATION_FRAMES,
    DETECTION_MIN_HITS,
    DETECTOR_EXIT_DB,
    DETECTOR_THRESHOLD_DB,
    MAX_MISSES,
    UI_FPS,
)
from .devices import create_worker
from .dsp.classifier import SignalClassifier
from .dsp.demod import Demodulator
from .dsp.detector import Detector
from .dsp.spectrum import SpectrumAnalyzer
from .dsp.tracker import ContactTracker
from .model import (
    Contact,
    DeviceConfig,
    IQBlock,
    SpectrumFrame,
    VFOConfig,
)
from .store import ContactStore


class DeviceSession(QObject):
    spectrum_updated = Signal(str, object)     # device_id, SpectrumFrame
    contacts_updated = Signal(str, object)     # device_id, list[Contact]
    status_changed = Signal(str, str)
    error = Signal(str, str)
    audio_ready = Signal(str, object, float)   # device_id, float32[], rate
    info_updated = Signal(str, dict)
    iq_ready = Signal(str, object)             # device_id, IQBlock (monitor mode)

    def __init__(self, config: DeviceConfig, store: ContactStore,
                 parent: QObject | None = None) -> None:
        super().__init__(parent)
        self.config = config
        self.store = store
        self.worker = create_worker(config)
        self.analyzer = SpectrumAnalyzer(config.fft_size)
        self.detector = Detector(
            threshold_db=DETECTOR_THRESHOLD_DB,
            exit_db=DETECTOR_EXIT_DB,
            calibration_frames=CALIBRATION_FRAMES,
        )
        self.classifier = SignalClassifier()
        self.tracker = ContactTracker(
            config.device_id, store,
            min_hits=DETECTION_MIN_HITS,
            max_misses=MAX_MISSES,
        )
        self.demod = Demodulator()
        self.vfo = VFOConfig()
        self.audio_enabled = False
        self.monitor_mode = False

        self._last_center: float | None = None
        self._last_fs: float | None = None
        self._last_spectrum_emit = 0.0
        self._last_contacts_emit = 0.0
        self._fps_times: deque[float] = deque(maxlen=32)
        self._fps = 0.0
        self._last_audio_level = -120.0
        self.last_frame: SpectrumFrame | None = None

        self.worker.iq_ready.connect(self._on_iq)
        self.worker.status_changed.connect(
            lambda did, st: self.status_changed.emit(did, st)
        )
        self.worker.error.connect(
            lambda did, msg: self.error.emit(did, msg)
        )
        self.worker.info_ready.connect(self._on_info)

    # ------------------------------------------------------------------ lifecycle
    def start(self) -> None:
        self.worker.start()

    def stop(self) -> None:
        self.worker.stop()
        self.status_changed.emit(self.config.device_id, "stopped")

    @Slot(object)
    def _on_info(self, device_id: str, info: dict) -> None:
        try:
            if "center_freq" in info:
                self.config.center_freq = float(info["center_freq"])
            if "sample_rate" in info:
                self.config.sample_rate = float(info["sample_rate"])
            if "gain" in info:
                self.config.gain = float(info["gain"])
        except Exception:
            pass
        self.info_updated.emit(device_id, dict(info))

    # ----------------------------------------------------------------------- IQ
    @Slot(object)
    def _on_iq(self, block: IQBlock) -> None:
        if block.device_id != self.config.device_id:
            return
        if block.samples is None or len(block.samples) == 0:
            return
        if (not self.monitor_mode
                and self._last_center is not None
                and (abs(block.center_freq - self._last_center) > 1.0
                     or abs(block.sample_rate - self._last_fs) > 1.0)):
            # Retuning changed the whole frequency axis: the old background
            # is meaningless.  Contacts are cleared as well.
            self.detector.reset()
            self.tracker.reset()
            self.demod.reset()
            self.contacts_updated.emit(self.config.device_id, [])
        self._last_center = block.center_freq
        self._last_fs = block.sample_rate
        self.config.center_freq = block.center_freq
        self.config.sample_rate = block.sample_rate
        self.iq_ready.emit(self.config.device_id, block)

        now_mono = time.monotonic()
        self._fps_times.append(now_mono)
        if len(self._fps_times) >= 3:
            elapsed = self._fps_times[-1] - self._fps_times[0]
            if elapsed > 0:
                self._fps = (len(self._fps_times) - 1) / elapsed

        freqs, psd = self.analyzer.compute(
            block.samples, block.sample_rate, block.center_freq
        )

        if self.monitor_mode:
            # The drone monitor owns the raw IQ; the normal detector/tracker
            # would only reset on every retune and waste CPU.
            frame = SpectrumFrame(
                device_id=self.config.device_id,
                freqs=freqs,
                psd=psd,
                baseline=None,
                detections=[],
                contacts=[],
                center_freq=block.center_freq,
                sample_rate=block.sample_rate,
                timestamp=block.timestamp,
                calibrated=False,
                calibration_progress=0.0,
                fps=self._fps,
                audio_level_db=-120.0,
                extra={"monitor": True},
            )
            self.last_frame = frame
            now = time.monotonic()
            if now - self._last_spectrum_emit >= 1.0 / max(1.0, UI_FPS):
                self._last_spectrum_emit = now
                self.spectrum_updated.emit(self.config.device_id, frame)
            return

        result = self.detector.process(freqs, psd)
        detections = result.detections
        for det in detections:
            self.classifier.apply(det)
        bin_hz = self.analyzer.bin_hz(block.sample_rate)
        contacts = self.tracker.update(detections, block.timestamp, bin_hz)

        if self.audio_enabled and self.vfo.active:
            audio, audio_rate, level = self.demod.process(
                block.samples, block.sample_rate, block.center_freq, self.vfo
            )
            self._last_audio_level = level
            if audio.size:
                self.audio_ready.emit(self.config.device_id, audio, audio_rate)

        frame = SpectrumFrame(
            device_id=self.config.device_id,
            freqs=freqs,
            psd=psd,
            baseline=result.baseline,
            detections=detections,
            contacts=contacts,
            center_freq=block.center_freq,
            sample_rate=block.sample_rate,
            timestamp=block.timestamp,
            calibrated=result.calibrated,
            calibration_progress=result.calibration_progress,
            fps=self._fps,
            audio_level_db=self._last_audio_level,
        )
        self.last_frame = frame

        now = time.monotonic()
        if now - self._last_spectrum_emit >= 1.0 / max(1.0, UI_FPS):
            self._last_spectrum_emit = now
            self.spectrum_updated.emit(self.config.device_id, frame)
        if now - self._last_contacts_emit >= 0.18:
            self._last_contacts_emit = now
            self.contacts_updated.emit(self.config.device_id, contacts)

    # ------------------------------------------------------------------- control
    def set_vfo(self, vfo: VFOConfig) -> None:
        self.vfo = vfo.copy()

    def set_audio_enabled(self, enabled: bool) -> None:
        self.audio_enabled = bool(enabled)
        if not enabled:
            self.demod.reset()

    def set_monitor_mode(self, enabled: bool) -> None:
        """Switch between normal DSP and raw-IQ monitoring.

        In monitor mode the detector/tracker are bypassed: the LO is retuned
        every few tens of milliseconds, so a stationary background would
        never calibrate and would only produce noise.
        """
        self.monitor_mode = bool(enabled)
        if enabled:
            self.set_audio_enabled(False)
            self.demod.reset()
        else:
            self.detector.reset()
            self.tracker.reset()
            self.demod.reset()

    def set_buffer_size(self, samples: int) -> None:
        self.worker.set_buffer_size(max(4096, int(samples)))

    def reset_background(self, clear_contacts: bool = True) -> None:
        self.detector.reset()
        self.tracker.reset()
        self.demod.reset()
        self._last_audio_level = -120.0
        if clear_contacts:
            self.contacts_updated.emit(self.config.device_id, [])

    def set_center_freq(self, hz: float) -> None:
        hz = float(hz)
        self.config.center_freq = hz
        self.worker.set_center_freq(hz)

    def set_sample_rate(self, hz: float) -> None:
        hz = float(hz)
        self.config.sample_rate = hz
        self.worker.set_sample_rate(hz)

    def set_gain(self, db: float) -> None:
        db = float(db)
        self.config.gain = db
        self.worker.set_gain(db)

    def set_bandwidth(self, hz: float) -> None:
        hz = float(hz)
        self.config.bandwidth = hz
        self.worker.set_bandwidth(hz)

    def inject_signal(self, **kwargs: Any) -> None:
        try:
            self.worker.inject_signal(**kwargs)
        except Exception as exc:
            self.error.emit(self.config.device_id, f"inject: {exc}")

    def set_threshold(self, enter_db: float, exit_db: float | None = None) -> None:
        self.detector.threshold_db = float(enter_db)
        self.detector.exit_db = float(
            exit_db if exit_db is not None else max(2.0, enter_db * 0.5)
        )

    def mark_known(self, contact_id: str) -> Contact | None:
        contact = self.tracker.mark_known(contact_id)
        if contact is not None and self.last_frame is not None:
            for item in self.last_frame.contacts:
                if item.contact_id == contact_id:
                    item.known = True
        self.contacts_updated.emit(self.config.device_id, self.tracker.snapshot())
        return contact

    def forget(self, contact_id: str) -> Contact | None:
        contact = self.tracker.forget(contact_id)
        if contact is not None and self.last_frame is not None:
            for item in self.last_frame.contacts:
                if item.contact_id == contact_id:
                    item.known = False
        self.contacts_updated.emit(self.config.device_id, self.tracker.snapshot())
        return contact

    def tracker_contacts(self) -> list[Contact]:
        return self.tracker.snapshot()

    @property
    def contacts(self) -> list[Contact]:
        return self.tracker_contacts()

    @property
    def fps(self) -> float:
        return self._fps
