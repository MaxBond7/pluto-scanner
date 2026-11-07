# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Bench transmitter window: Pluto sends a picture, HackRF receives it.

The transmit controls and a preview need room, and the video tab is already
busy with the receiver, so the bench lives in its own window.  The main
window keeps a short launcher (menu and a button in the video tab).

This is a bench tool: it transmits only when the user presses a button, it
warns about antennas/attenuator, and it mutes the DAC on stop.
"""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QImage
from PySide6.QtWidgets import (
    QApplication,
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

from ..devices.pluto_tx import (
    DEFAULT_DEVIATION,
    DEFAULT_RATE,
    PlutoTransmitter,
    PlutoVideoStream,
)
from ..paths import RECORDINGS_DIR
from ..video import STANDARDS
from ..video.testcard import build as build_testcard
from ..video.testcard import build_frame as build_test_frame
from ..video.testcard import test_card
from .themes import set_style


class BenchWindow(QWidget):
    """Transmit a test card, a still picture or a video file from a Pluto."""

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent, Qt.WindowType.Window)
        self.setWindowTitle("Стенд: передача аналогового видео")
        self.setMinimumWidth(780)
        self._transmitter = PlutoTransmitter()
        self._stream = PlutoVideoStream()
        self._source = ""
        self._preview_rows: np.ndarray | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self._stop_job)
        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self.stop)

        root = QVBoxLayout(self)
        root.setContentsMargins(10, 10, 10, 10)
        root.setSpacing(8)

        top = QHBoxLayout()
        self.card_btn = QPushButton("Тест-картинка")
        self.card_btn.clicked.connect(lambda: self._start_job("card"))
        top.addWidget(self.card_btn)
        self.image_btn = QPushButton("Картинка…")
        self.image_btn.clicked.connect(self._choose_image)
        top.addWidget(self.image_btn)
        self.video_btn = QPushButton("Видео…")
        self.video_btn.clicked.connect(self._choose_video)
        top.addWidget(self.video_btn)
        top.addStretch(1)
        self.stop_btn = QPushButton("Стоп")
        self.stop_btn.setEnabled(False)
        self.stop_btn.clicked.connect(self._stop_job)
        top.addWidget(self.stop_btn)
        root.addLayout(top)

        settings = QHBoxLayout()
        settings.addWidget(QLabel("Pluto"))
        self.uri_label = QLabel("—")
        set_style(self.uri_label, "color:#94a3b8;")
        settings.addWidget(self.uri_label)
        settings.addSpacing(12)
        settings.addWidget(QLabel("Частота"))
        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setRange(1.0, 6000.0)
        self.freq_spin.setDecimals(3)
        self.freq_spin.setSuffix(" МГц")
        self.freq_spin.setValue(1241.0)
        self.freq_spin.setToolTip(
            "На 1 МГц выше центра приёма: ровно в центре HackRF сигнал "
            "тонет в DC-спайке."
        )
        settings.addWidget(self.freq_spin)
        settings.addWidget(QLabel("Усиление"))
        self.gain_spin = QDoubleSpinBox()
        self.gain_spin.setRange(-60.0, 0.0)
        self.gain_spin.setDecimals(1)
        self.gain_spin.setSuffix(" дБ")
        self.gain_spin.setValue(0.0)
        settings.addWidget(self.gain_spin)
        settings.addWidget(QLabel("Стандарт"))
        self.standard_combo = QComboBox()
        for key in ("PAL", "NTSC", "SECAM"):
            self.standard_combo.addItem(
                "SECAM (ч/б)" if key == "SECAM" else key, key,
            )
        settings.addWidget(self.standard_combo)
        settings.addWidget(QLabel("Время"))
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(0.0, 600.0)
        self.duration_spin.setDecimals(0)
        self.duration_spin.setSuffix(" с")
        self.duration_spin.setValue(30.0)
        self.duration_spin.setToolTip("0 — до кнопки «Стоп».")
        settings.addWidget(self.duration_spin)
        settings.addStretch(1)
        root.addLayout(settings)

        self.preview = QLabel("Здесь будет картинка, которую передаём")
        self.preview.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.preview.setMinimumSize(576, 432)
        set_style(
            self.preview,
            "background:#000000; color:#8fa6c0; border:1px solid #22304a;",
        )
        root.addWidget(self.preview, 1)

        self.status = QLabel(
            "Стенд: только антенны на столе или аттенюатор 30–40 дБ. "
            "Для приёма выберите HackRF в главном окне и нажмите «Смотреть» "
            "на частоте приёма."
        )
        self.status.setWordWrap(True)
        set_style(self.status, "color:#94a3b8; font-size:11px;")
        root.addWidget(self.status)
        self._update_buttons()

    # -------------------------------------------------------------- helpers
    @property
    def active(self) -> bool:
        return self._transmitter.active or self._stream.active

    def _update_buttons(self) -> None:
        busy = self.active
        ready = PlutoTransmitter.available()
        self.card_btn.setEnabled(not busy and ready)
        self.image_btn.setEnabled(not busy and ready)
        self.video_btn.setEnabled(not busy and ready)
        self.stop_btn.setEnabled(busy)
        self.freq_spin.setEnabled(not busy)
        self.gain_spin.setEnabled(not busy)
        self.standard_combo.setEnabled(not busy)
        self.duration_spin.setEnabled(not busy)
        self.uri_label.setText(
            self._transmitter.uri if self._transmitter.active else "—"
        )

    def _set_status(self, text: str, color: str = "#94a3b8") -> None:
        set_style(self.status, f"color:{color}; font-size:11px;")
        self.status.setText(text)

    def _show_preview(self, rows: np.ndarray) -> None:
        picture = np.clip(rows * 255.0, 0, 255).astype(np.uint8)
        height, width = picture.shape
        image = QImage(
            picture.tobytes(), width, height, width,
            QImage.Format.Format_Grayscale8,
        ).copy()
        self.preview.setPixmap(self.preview_pixmap(image))
        self._preview_rows = rows

    def preview_pixmap(self, image: QImage):
        from PySide6.QtGui import QPixmap

        return QPixmap.fromImage(image).scaled(
            self.preview.size(),
            Qt.AspectRatioMode.KeepAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )

    def resizeEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().resizeEvent(event)
        if self._preview_rows is not None:
            rows = np.clip(self._preview_rows * 255.0, 0, 255).astype(np.uint8)
            height, width = rows.shape
            image = QImage(
                rows.tobytes(), width, height, width,
                QImage.Format.Format_Grayscale8,
            ).copy()
            self.preview.setPixmap(self.preview_pixmap(image))

    def show_and_raise(self) -> None:
        if self.isMinimized():
            self.setWindowState(
                self.windowState() & ~Qt.WindowState.WindowMinimized
            )
        self.show()
        self.raise_()
        self.activateWindow()

    # ------------------------------------------------------------- choosing
    def _choose_image(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Картинка для передачи", str(RECORDINGS_DIR),
            "Картинка (*.jpg *.jpeg *.png *.bmp);;Все файлы (*)",
        )
        if path:
            self._start_job("image", Path(path))

    def _choose_video(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self, "Видео для передачи", str(RECORDINGS_DIR),
            "Видео (*.mp4 *.mkv *.mov *.avi *.m4v);;Все файлы (*)",
        )
        if path:
            self._start_job("video", Path(path))

    # ------------------------------------------------------------- transmit
    def _start_job(self, kind: str, path: Path | None = None) -> None:
        if self.active:
            self._set_status("сначала остановите текущую передачу", "#facc15")
            return
        self._update_buttons()
        self._set_status("готовлю передачу…", "#67e8f9")
        self.card_btn.setEnabled(False)
        self.image_btn.setEnabled(False)
        self.video_btn.setEnabled(False)
        threading.Thread(
            target=self._start_worker, args=(kind, path),
            name="bench-tx", daemon=True,
        ).start()

    def _standard(self):
        return STANDARDS[self.standard_combo.currentData()]

    def _start_worker(self, kind: str, path: Path | None) -> None:
        try:
            self._stop_engines()
            standard = self._standard()
            freq = self.freq_spin.value() * 1e6
            gain = self.gain_spin.value()
            if kind == "card":
                rows = test_card(standard.pixels, standard.active_lines, 0.0)
                self._show_preview(rows)
                iq, field = build_testcard(
                    standard, DEFAULT_RATE, 0.04, DEFAULT_DEVIATION,
                )
                whole = (iq.size // field) * field
                self._transmitter.start(
                    iq[:whole], DEFAULT_RATE, freq, gain,
                )
                label = "тест-картинка"
            elif kind == "image":
                rows = self._image_rows(path, standard)
                self._show_preview(rows)
                iq, field = build_test_frame(
                    standard, DEFAULT_RATE, rows, DEFAULT_DEVIATION, fields=2,
                )
                whole = (iq.size // field) * field
                self._transmitter.start(
                    iq[:whole], DEFAULT_RATE, freq, gain,
                )
                label = f"{path.name} (цикл)"
            else:
                frames = self._video_rows(path, standard)
                if not frames:
                    raise RuntimeError("в видео нет кадров")
                self._show_preview(frames[0].astype(np.float64) / 255.0)
                self._stream.start(frames, standard)
                label = f"{path.name} ({len(frames)} кадров)"
            self._source = label
            self._set_status(
                f"передаю {label} · {freq / 1e6:.3f} МГц · "
                f"{standard.name} · {self._transmitter.uri or 'поток'}",
                "#4ade80",
            )
            self._update_buttons()
            seconds = float(self.duration_spin.value())
            if seconds > 0:
                self._timer.start(int(seconds * 1000))
        except Exception as exc:
            self._stop_engines()
            self._set_status(f"не удалось: {exc}", "#f87171")
            self._update_buttons()

    def _stop_job(self) -> None:
        self._timer.stop()
        self._set_status("останавливаю…", "#67e8f9")
        self.stop_btn.setEnabled(False)
        threading.Thread(
            target=self._stop_worker, name="bench-tx", daemon=True,
        ).start()

    def _stop_worker(self) -> None:
        self._stop_engines()
        self._set_status("передача остановлена", "#94a3b8")
        self._update_buttons()

    def _stop_engines(self) -> None:
        self._transmitter.stop()
        self._stream.stop()

    def stop(self) -> None:
        """Synchronous stop, used on application exit."""
        self._timer.stop()
        self._stop_engines()

    # --------------------------------------------------------------- files
    @staticmethod
    def _image_rows(path: Path, standard) -> np.ndarray:
        image = QImage(str(path))
        if image.isNull():
            raise RuntimeError("не удалось прочитать картинку")
        image = image.convertToFormat(QImage.Format.Format_Grayscale8)
        width, height = standard.pixels, standard.active_lines
        scaled = image.scaled(
            width, height,
            Qt.AspectRatioMode.IgnoreAspectRatio,
            Qt.TransformationMode.SmoothTransformation,
        )
        raw = np.frombuffer(
            scaled.constBits(), dtype=np.uint8, count=scaled.sizeInBytes(),
        )
        stride = scaled.bytesPerLine()
        return (raw.reshape(height, stride)[:, :width]
                .astype(np.float64) / 255.0)

    def _video_rows(self, path: Path, standard) -> list[np.ndarray]:
        from ..devices.pluto_tx import STREAM_RATE
        from ..video.videofile import read_frames

        seconds = float(self.duration_spin.value())
        if seconds <= 0:
            seconds = 10.0
        seconds = min(seconds, 10.0)
        active = int(round(52e-6 * STREAM_RATE))
        frames: list[np.ndarray] = []
        for frame in read_frames(
            path, active, standard.active_lines,
            standard.fps, seconds=seconds,
        ):
            frames.append(frame)
            if len(frames) >= 250:
                break
        return frames

    def closeEvent(self, event) -> None:  # noqa: N802 - Qt API
        self.stop()
        super().closeEvent(event)


__all__ = ["BenchWindow"]
