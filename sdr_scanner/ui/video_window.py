# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Analog TV window: FM/AM video, PAL/NTSC line timing and a monochrome frame."""
from __future__ import annotations

import threading
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QImage, QPixmap
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import format_freq
from ..video import PAL, STANDARDS, DecodedFrame, decode_frame
from .themes import set_style


class VideoPanel(QWidget):
    """Analog video as a main-window tab; owns the receiver while running."""

    frame_ready = Signal(object)
    decode_failed = Signal(str)

    def __init__(self, session=None, parent: QWidget | None = None,
                 guard=None) -> None:
        super().__init__(parent)
        self.session = session
        self._guard = guard
        self._running = False
        self._old: dict = {}
        self._last_image: QImage | None = None
        self._last_frame: DecodedFrame | None = None
        self._video_blocks: list = []
        self._video_size = 0
        self._video_rate = 0.0
        self._decode_busy = False
        self._frame_seconds = 0.12
        self._max_seconds = 0.20
        self._file_mode = False
        self.frame_ready.connect(self._show_frame)
        self.decode_failed.connect(self._show_failure)

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        controls = QHBoxLayout()
        controls.setSpacing(6)
        controls.addWidget(QLabel("Частота"))
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(1.0, 6000.0)
        self.freq_spin.setDecimals(3)
        self.freq_spin.setSuffix(" МГц")
        center = (
            float(session.config.center_freq) if session is not None
            else 2437e6
        )
        self.freq_spin.setValue(center / 1e6)
        controls.addWidget(self.freq_spin)

        controls.addWidget(QLabel("Стандарт"))
        self.standard_combo = QComboBox()
        for key in ("PAL", "NTSC", "SECAM"):
            self.standard_combo.addItem(
                "SECAM (ч/б)" if key == "SECAM" else key, key,
            )
        controls.addWidget(self.standard_combo)

        controls.addWidget(QLabel("Демодуляция"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItem("FM", "fm")
        self.mode_combo.addItem("AM", "am")
        controls.addWidget(self.mode_combo)

        self.invert_check = QCheckBox("Инверсия")
        self.invert_check.setToolTip(
            "Если синхроимпульсы направлены вверх, включите инверсию."
        )
        controls.addWidget(self.invert_check)

        self.start_btn = QPushButton("Смотреть")
        self.start_btn.clicked.connect(self._toggle)
        controls.addWidget(self.start_btn)
        self.snapshot_btn = QPushButton("Снимок…")
        self.snapshot_btn.setEnabled(False)
        self.snapshot_btn.clicked.connect(self._snapshot)
        controls.addWidget(self.snapshot_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        self.display = QLabel("Нажмите «Смотреть»")
        self.display.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.display.setMinimumSize(640, 480)
        self.display.setScaledContents(False)
        set_style(
            self.display,
            "background:#000000; color:#8fa6c0; border:1px solid #22304a;",
        )
        root.addWidget(self.display, 1)

        self.status = QLabel(
            "Будет использован выбранный приёмник; запись, сканирование "
            "и дрон-монитор должны быть остановлены."
        )
        self.status.setWordWrap(True)
        set_style(self.status, "color:#94a3b8; font-size:11px;")
        root.addWidget(self.status)

    # ------------------------------------------------------------------ state
    @property
    def running(self) -> bool:
        return self._running

    def start_at(self, freq_hz: float, standard: str = "PAL") -> None:
        """Select the session/frequency and start watching immediately."""
        self.set_session(self.session)
        self.freq_spin.setValue(float(freq_hz) / 1e6)
        index = self.standard_combo.findData(str(standard).upper())
        if index >= 0:
            self.standard_combo.setCurrentIndex(index)
        self._start()

    def set_session(self, session) -> None:
        if self._running:
            self.stop()
        self.session = session
        if session is not None:
            self.freq_spin.setValue(float(session.config.center_freq) / 1e6)
            self.status.setText(
                f"Приёмник: {session.config.name}. Нажмите «Смотреть»."
            )
        else:
            self.status.setText("Выберите Pluto или HackRF для видео.")

    def stop(self) -> None:
        self._stop()
    def _rate_for_session(self) -> float:
        if self.session is None:
            return 6.144e6
        rate = float(self.session.config.sample_rate)
        if self.session.config.kind == "hackrf":
            from ..devices.hackrf import clamp_rate
            return clamp_rate(rate)
        if rate < 5e6:
            return 6.144e6
        return rate

    def _toggle(self) -> None:
        if self._running:
            self._stop()
        else:
            self._start()

    def _start(self) -> None:
        if self._guard is not None:
            reason = self._guard()
            if reason:
                set_style(self.status, "color:#facc15; font-size:11px;")
                self.status.setText(reason)
                return
        if self.session is None:
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText("Сначала выберите Pluto, HackRF или запись.")
            return
        if self.session.config.kind == "iqfile":
            self._start_file()
            return
        if not self.session.worker.isRunning():
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText("Приёмник не запущен.")
            return
        self._old = {
            "center": float(self.session.config.center_freq),
            "rate": float(self.session.config.sample_rate),
            "bandwidth": float(self.session.config.bandwidth),
            "audio": bool(self.session.audio_enabled),
        }
        standard = STANDARDS[self.standard_combo.currentData()]
        self._video_standard = standard
        self._video_mode = self.mode_combo.currentData()
        self._video_invert = self.invert_check.isChecked()
        self._video_blocks = []
        self._video_size = 0
        self._decode_busy = False
        self._file_mode = self.session.config.kind == "iqfile"
        # A dataset block can be only 30-40 ms; do not wait 120 ms for a
        # frame that will never arrive.
        self._frame_seconds = 0.025 if self._file_mode else 0.12
        self._max_seconds = 0.08 if self._file_mode else 0.20
        rate = self._rate_for_session()
        center = float(self.freq_spin.value()) * 1e6
        try:
            self.session.set_monitor_mode(True)
            self.session.set_audio_enabled(False)
            if not self._file_mode:
                self.session.set_sample_rate(rate)
                self.session.set_bandwidth(min(rate, 12.0e6))
                self.session.set_center_freq(center)
            self.session.set_buffer_size(int(rate * 0.02))
            self.session.iq_ready.connect(self._on_iq)
        except Exception as exc:
            self._restore()
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText(f"Не удалось запустить видео: {exc}")
            return
        self._running = True
        self.start_btn.setText("Остановить")
        self.snapshot_btn.setEnabled(False)
        set_style(self.status, "color:#67e8f9; font-size:11px;")
        prefix = "Файл" if self._file_mode else "Слушаю"
        self.status.setText(
            f"{prefix} {format_freq(center)} · {standard.name} · "
            f"{rate / 1e6:.2f} МС/с. Ждём строку…"
        )

    def _start_file(self) -> None:
        from ..recordings import load_info

        path = Path(str(self.session.config.uri))
        if path.suffix.lower() == ".json":
            info = load_info(path)
            if info is not None:
                path = info.path
        if not path.exists():
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText(f"Запись не найдена: {path}")
            return
        standard = STANDARDS[self.standard_combo.currentData()]
        rate = float(self.session.config.sample_rate)
        if rate <= 0:
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText("В записи не указана частота дискретизации.")
            return
        self._old = {}
        self._file_mode = True
        self._running = True
        self._decode_busy = True
        self._last_frame = None
        self._last_image = None
        self.start_btn.setText("Остановить")
        self.snapshot_btn.setEnabled(False)
        set_style(self.status, "color:#67e8f9; font-size:11px;")
        self.status.setText(
            f"Читаю запись {path.name} (первые 2 с) и собираю кадр…"
        )
        threading.Thread(
            target=self._decode_file,
            args=(
                path, rate, standard, self.mode_combo.currentData(),
                self.invert_check.isChecked(),
            ),
            name="analog-video-file",
            daemon=True,
        ).start()

    def _decode_file(self, path: Path, rate: float, standard,
                     mode: str, invert: bool) -> None:
        try:
            data = np.memmap(path, dtype=np.complex64, mode="r")
            count = min(int(data.size), int(rate * 2.0))
            iq = np.array(data[:count], dtype=np.complex64, copy=True)
            del data
            frame = decode_frame(
                iq, rate, standard, mode=mode, invert=invert,
            )
            if frame is None:
                self.decode_failed.emit(
                    "Кадр не собран: нет устойчивой строки. "
                    "Попробуйте другой стандарт, AM/FM или инверсию."
                )
            else:
                self.frame_ready.emit(frame)
        except Exception as exc:
            self.decode_failed.emit(f"Ошибка чтения записи: {exc}")
        finally:
            self._decode_busy = False

    def _show_failure(self, message: str) -> None:
        if not self._running:
            return
        self.start_btn.setText("Смотреть")
        self._running = False
        set_style(self.status, "color:#f87171; font-size:11px;")
        self.status.setText(message)

    def _stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.start_btn.setText("Смотреть")
        try:
            if self.session is not None and not self._file_mode:
                self.session.iq_ready.disconnect(self._on_iq)
        except (RuntimeError, TypeError):
            pass
        self._restore()
        self._video_blocks = []
        self._video_size = 0
        set_style(self.status, "color:#94a3b8; font-size:11px;")
        self.status.setText("Остановлено.")

    def _restore(self) -> None:
        old = self._old
        if not old:
            return
        self._old = {}
        try:
            if not self._file_mode:
                self.session.set_sample_rate(old["rate"])
                self.session.set_bandwidth(old["bandwidth"])
                self.session.set_center_freq(old["center"])
            self.session.set_audio_enabled(old["audio"])
            self.session.set_monitor_mode(False)
        except Exception:
            pass

    # ------------------------------------------------------------------ video
    def _on_iq(self, device_id: str, block) -> None:
        if (not self._running or self.session is None
                or device_id != self.session.config.device_id):
            return
        samples = np.asarray(block.samples, dtype=np.complex64)
        self._video_blocks.append(samples)
        self._video_size += int(samples.size)
        self._video_rate = float(block.sample_rate)
        need = int(self._frame_seconds * self._video_rate)
        if self._video_size < need:
            return
        if self._decode_busy:
            # Do not let a slow decoder grow the buffer without bound; the
            # next frame will use the freshest samples.
            limit = int(self._max_seconds * self._video_rate)
            while (self._video_blocks
                   and self._video_size - self._video_blocks[0].size >= limit):
                self._video_size -= int(self._video_blocks.pop(0).size)
            return
        data = np.concatenate(self._video_blocks)[-need:]
        self._video_blocks = []
        self._video_size = 0
        self._decode_busy = True
        threading.Thread(
            target=self._decode_worker,
            args=(
                data, self._video_rate, self._video_standard,
                self._video_mode, self._video_invert,
            ),
            name="analog-video-decode",
            daemon=True,
        ).start()

    def _decode_worker(self, data, rate, standard, mode, invert) -> None:
        try:
            frame = decode_frame(
                data, rate, standard, mode=mode, invert=invert,
            )
            if frame is not None and self._running:
                self.frame_ready.emit(frame)
        except Exception:
            pass
        finally:
            self._decode_busy = False

    def _show_frame(self, frame: DecodedFrame) -> None:
        if not self._running:
            return
        self._last_frame = frame
        image = QImage(
            frame.image.tobytes(),
            frame.image.shape[1],
            frame.image.shape[0],
            frame.image.strides[0],
            QImage.Format.Format_Grayscale8,
        ).copy()
        self._last_image = image
        pixmap = QPixmap.fromImage(image)
        self.display.setPixmap(pixmap.scaled(
            self.display.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        ))
        self.snapshot_btn.setEnabled(True)
        set_style(self.status, "color:#4ade80; font-size:11px;")
        self.status.setText(
            f"{frame.standard} · {frame.line_hz:.1f} Гц · "
            f"{frame.lines} строк · "
            f"{'кадр' if frame.frame_locked else 'поле/фрагмент'} · "
            f"синхронизация: {'есть' if frame.locked else 'слабая'}"
        )

    def _snapshot(self) -> None:
        if self._last_image is None:
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "Сохранить кадр", "analog_frame.png",
            "PNG (*.png);;JPEG (*.jpg)",
        )
        if path:
            self._last_image.save(path)

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._last_image is not None:
            self.display.setPixmap(QPixmap.fromImage(self._last_image).scaled(
                self.display.size(),
                Qt.AspectRatioMode.KeepAspectRatio,
                Qt.TransformationMode.SmoothTransformation,
            ))

__all__ = ["VideoPanel"]
