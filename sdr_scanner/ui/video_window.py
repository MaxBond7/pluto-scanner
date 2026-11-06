# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Analog TV window: FM/AM video, PAL/NTSC line timing and a monochrome frame."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
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
from ..video import NTSC, PAL, STANDARDS, DecodedFrame, VideoDecoder
from .themes import set_style


class VideoPanel(QWidget):
    """Analog video as a main-window tab; owns the receiver while running."""

    def __init__(self, session=None, parent: QWidget | None = None,
                 guard=None) -> None:
        super().__init__(parent)
        self.session = session
        self._guard = guard
        self.decoder = VideoDecoder(PAL)
        self._running = False
        self._old: dict = {}
        self._last_image: QImage | None = None
        self._last_frame: DecodedFrame | None = None

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
        for key in ("PAL", "NTSC"):
            self.standard_combo.addItem(key, key)
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
            self.status.setText("Сначала выберите Pluto или HackRF.")
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
        self.decoder = VideoDecoder(
            standard,
            mode=self.mode_combo.currentData(),
            invert=self.invert_check.isChecked(),
            frame_seconds=0.12,
            max_seconds=0.35,
        )
        rate = self._rate_for_session()
        center = float(self.freq_spin.value()) * 1e6
        try:
            self.session.set_monitor_mode(True)
            self.session.set_audio_enabled(False)
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
        self.status.setText(
            f"Слушаю {format_freq(center)} · {standard.name} · "
            f"{rate / 1e6:.2f} МС/с. Ждём строку…"
        )

    def _stop(self) -> None:
        if not self._running:
            return
        self._running = False
        self.start_btn.setText("Смотреть")
        try:
            if self.session is not None:
                self.session.iq_ready.disconnect(self._on_iq)
        except (RuntimeError, TypeError):
            pass
        self._restore()
        self.decoder.reset()
        set_style(self.status, "color:#94a3b8; font-size:11px;")
        self.status.setText("Остановлено.")

    def _restore(self) -> None:
        old = self._old
        if not old:
            return
        self._old = {}
        try:
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
        frame = self.decoder.feed(block.samples, block.sample_rate)
        if frame is None:
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
            f"{frame.lines} строк · синхронизация: "
            f"{'есть' if frame.locked else 'слабая'} · снимок кадра"
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
