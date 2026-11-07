# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Analog TV window: FM/AM video, PAL/NTSC line timing and a monochrome frame."""
from __future__ import annotations

import threading
import time
from pathlib import Path

import numpy as np
from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QImage, QPainter, QPixmap
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config import format_freq
from ..devices.pluto_tx import (
    DEFAULT_DEVIATION,
    DEFAULT_RATE,
    PlutoTransmitter,
    PlutoVideoStream,
)
from ..paths import RECORDINGS_DIR
from ..recordings import load_info
from ..video import STANDARDS, DecodedFrame, decode_frame
from ..video.dataset import frequencies as dataset_frequencies
from ..video.dataset import load_blocks as dataset_blocks
from ..video.dataset import metadata_for as dataset_metadata
from ..video.testcard import build as build_testcard
from ..video.testcard import build_frame as build_test_frame
from .themes import set_style


class _DatasetDialog(QDialog):
    """Choose a sweep frequency and the sample rate of a dataset folder."""

    def __init__(self, meta: Path, current_hz: float,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Свип датасета")
        form = QFormLayout(self)
        self.freq_combo = QComboBox()
        values = dataset_frequencies(meta)
        nearest = min(values, key=lambda item: abs(item - float(current_hz)))
        for value in values:
            self.freq_combo.addItem(format_freq(value), value)
            if value == nearest:
                self.freq_combo.setCurrentIndex(self.freq_combo.count() - 1)
        form.addRow("Частота", self.freq_combo)
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.1, 80.0)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setSuffix(" МС/с")
        self.rate_spin.setValue(20.0)
        form.addRow("Частота дискретизации", self.rate_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[float, float]:
        return (
            float(self.freq_combo.currentData()),
            float(self.rate_spin.value()) * 1e6,
        )


class _RawDialog(QDialog):
    """Sample rate and centre frequency for a raw IQ file."""

    def __init__(self, name: str, rate_hz: float, center_hz: float,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setWindowTitle("Параметры записи")
        form = QFormLayout(self)
        form.addRow(QLabel(f"{name}\nВ файле нет метаданных, укажите их."))
        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.1, 80.0)
        self.rate_spin.setDecimals(2)
        self.rate_spin.setSuffix(" МС/с")
        self.rate_spin.setValue(max(0.1, float(rate_hz) / 1e6))
        form.addRow("Частота дискретизации", self.rate_spin)
        self.center_spin = QDoubleSpinBox()
        self.center_spin.setRange(1.0, 6000.0)
        self.center_spin.setDecimals(3)
        self.center_spin.setSuffix(" МГц")
        self.center_spin.setValue(max(1.0, float(center_hz) / 1e6))
        form.addRow("Центральная частота", self.center_spin)
        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self.accept)
        buttons.rejected.connect(self.reject)
        form.addRow(buttons)

    def values(self) -> tuple[float, float]:
        return (
            float(self.rate_spin.value()) * 1e6,
            float(self.center_spin.value()) * 1e6,
        )


class _PlaySource:
    """Random access to the IQ of one recording or dataset frequency."""

    def __init__(self, label: str, rate: float, total: int,
                 center: float, read) -> None:
        self.label = label
        self.rate = float(rate)
        self.total = int(total)
        self.center = float(center)
        self._read = read

    @property
    def duration(self) -> float:
        return self.total / self.rate if self.rate > 0 else 0.0

    def read(self, start: int, count: int) -> np.ndarray:
        start = max(0, min(int(start), self.total))
        count = max(0, min(int(count), self.total - start))
        if count <= 0:
            return np.empty(0, dtype=np.complex64)
        return np.asarray(self._read(start, count), dtype=np.complex64)


class VideoPanel(QWidget):
    """Analog video as a main-window tab; owns the receiver while running."""

    frame_ready = Signal(object)
    decode_failed = Signal(str)
    tx_state = Signal(bool, str)

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
        self._source = ""
        self._play_source: _PlaySource | None = None
        self._play_pos = 0.0
        self._play_playing = False
        self._play_busy = False
        self._play_started = 0.0
        self._play_origin = 0.0
        self._play_window = 0.12
        self._frame_pos = 0.0
        self._play_frames: list[np.ndarray] = []
        self._play_timer = QTimer(self)
        self._play_timer.setInterval(25)
        self._play_timer.timeout.connect(self._play_tick)
        self._transmitter = PlutoTransmitter()
        self._stream = PlutoVideoStream()
        self._tx_kind = ""
        self._tx_timer = QTimer(self)
        self._tx_timer.setSingleShot(True)
        self._tx_timer.timeout.connect(self._stop_tx_job)
        self.frame_ready.connect(self._show_frame)
        self.decode_failed.connect(self._show_failure)
        self.tx_state.connect(self._on_tx_state)

        app = QApplication.instance()
        if app is not None:
            app.aboutToQuit.connect(self._transmitter.stop)
            app.aboutToQuit.connect(self._stream.stop)

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
        self.open_btn = QPushButton("Открыть файл…")
        self.open_btn.setToolTip(
            "Открыть запись IQ или папку свипа датасета и собрать кадр, "
            "не занимая приёмник."
        )
        self.open_btn.clicked.connect(self.open_file)
        controls.addWidget(self.open_btn)
        self.snapshot_btn = QPushButton("Снимок…")
        self.snapshot_btn.setEnabled(False)
        self.snapshot_btn.clicked.connect(self._snapshot)
        controls.addWidget(self.snapshot_btn)
        controls.addStretch(1)
        root.addLayout(controls)

        player = QHBoxLayout()
        player.setSpacing(6)
        self.play_btn = QPushButton("Играть")
        self.play_btn.setEnabled(False)
        self.play_btn.setToolTip(
            "Воспроизведение открытой записи. Если декодер не успевает, "
            "кадры пропускаются, но время идёт ровно."
        )
        self.play_btn.clicked.connect(self._toggle_play)
        player.addWidget(self.play_btn)
        self.pos_slider = QSlider(Qt.Orientation.Horizontal)
        self.pos_slider.setRange(0, 1000)
        self.pos_slider.setEnabled(False)
        self.pos_slider.sliderReleased.connect(self._seek)
        player.addWidget(self.pos_slider, 1)
        self.time_label = QLabel("— / —")
        self.time_label.setMinimumWidth(110)
        self.time_label.setAlignment(Qt.AlignmentFlag.AlignRight
                                     | Qt.AlignmentFlag.AlignVCenter)
        player.addWidget(self.time_label)
        self.smooth_check = QCheckBox("Накопление")
        self.smooth_check.setToolTip(
            "Усреднять несколько кадров подряд: меньше шума, если сцена "
            "не двигается."
        )
        player.addWidget(self.smooth_check)
        root.addLayout(player)

        bench = QHBoxLayout()
        bench.setSpacing(6)
        self.tx_btn = QPushButton("Вещать тест-картинку")
        self.tx_btn.setCheckable(True)
        self.tx_btn.setToolTip(
            "Стендовая проверка: Pluto передаёт тестовую картинку, "
            "HackRF принимает её в этой же программе. Только антенны на "
            "столе или аттенюатор — не в эфир."
        )
        if not PlutoTransmitter.available():
            self.tx_btn.setEnabled(False)
            self.tx_btn.setToolTip("Не установлен pyadi-iio / libiio.")
        self.tx_btn.toggled.connect(self._toggle_tx)
        bench.addWidget(self.tx_btn)
        self.tx_file_btn = QPushButton("Файл…")
        self.tx_file_btn.setToolTip(
            "Передать картинку (JPEG/PNG) или видео (MP4/MKV): картинка "
            "идёт циклом, видео — кадрами."
        )
        self.tx_file_btn.clicked.connect(self._send_file)
        bench.addWidget(self.tx_file_btn)
        bench.addWidget(QLabel("Передача"))
        self.tx_freq_spin = QDoubleSpinBox()
        self.tx_freq_spin.setRange(1.0, 6000.0)
        self.tx_freq_spin.setDecimals(3)
        self.tx_freq_spin.setSuffix(" МГц")
        self.tx_freq_spin.setToolTip(
            "На 1 МГц выше приёма: ровно в центре HackRF сигнал тонет "
            "в DC-спайке."
        )
        self.tx_freq_spin.setValue(min(
            6000.0, self.freq_spin.value() + 1.0,
        ))
        bench.addWidget(self.tx_freq_spin)
        self.tx_gain_spin = QDoubleSpinBox()
        self.tx_gain_spin.setRange(-60.0, 0.0)
        self.tx_gain_spin.setDecimals(1)
        self.tx_gain_spin.setSingleStep(1.0)
        self.tx_gain_spin.setSuffix(" дБ")
        self.tx_gain_spin.setValue(0.0)
        self.tx_gain_spin.setToolTip(
            "0 дБ — максимум Pluto. Для кабеля нужен аттенюатор 30–40 дБ."
        )
        bench.addWidget(self.tx_gain_spin)
        bench.addWidget(QLabel("Время"))
        self.tx_duration_spin = QDoubleSpinBox()
        self.tx_duration_spin.setRange(0.0, 600.0)
        self.tx_duration_spin.setDecimals(0)
        self.tx_duration_spin.setSuffix(" с")
        self.tx_duration_spin.setValue(30.0)
        self.tx_duration_spin.setToolTip(
            "Сколько секунд вещать; 0 — до кнопки «Стоп»."
        )
        bench.addWidget(self.tx_duration_spin)
        self.tx_status = QLabel("стенд: антенны или аттенюатор")
        set_style(self.tx_status, "color:#94a3b8; font-size:11px;")
        bench.addWidget(self.tx_status, 1)
        root.addLayout(bench)
        self.freq_spin.valueChanged.connect(self._follow_rx)
        self.standard_combo.currentIndexChanged.connect(self._forget_frames)
        self.mode_combo.currentIndexChanged.connect(self._forget_frames)
        self.invert_check.toggled.connect(self._forget_frames)
        self.smooth_check.toggled.connect(self._forget_frames)

        self.display = QLabel("Нажмите «Смотреть» или «Открыть файл…»")
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

    # ------------------------------------------------------------- file input
    def open_file(self) -> None:
        """Ask for an IQ file or a sweep folder and decode it right away."""
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Открыть запись IQ",
            str(RECORDINGS_DIR),
            "Записи IQ (*.json *.cf32 *.bin *.iq);;Все файлы (*)",
        )
        if path:
            self.open_path(Path(path))

    def open_path(self, path: Path) -> None:
        """Open *path* for playback without taking over a receiver."""
        path = Path(path)
        info = load_info(path)
        if info is not None:
            self.freq_spin.setValue(float(info.center_freq) / 1e6)
            self._load_source(self._file_source(
                Path(info.path), float(info.sample_rate), info.center_freq,
            ))
            return
        meta = dataset_metadata(path)
        if meta is not None:
            dialog = _DatasetDialog(meta, self.freq_spin.value() * 1e6, self)
            if not dialog.exec():
                return
            freq, rate = dialog.values()
            self.freq_spin.setValue(freq / 1e6)
            iq, center = dataset_blocks(path, meta, freq)
            if iq.size == 0:
                set_style(self.status, "color:#f87171; font-size:11px;")
                self.status.setText(
                    "В свипе нет отсчётов для этой частоты."
                )
                return
            label = f"{path.parent.name} · {format_freq(center)}"
            self._load_source(_PlaySource(
                label, rate, iq.size, center,
                lambda start, count, data=iq: data[start:start + count],
            ))
            return
        dialog = _RawDialog(
            path.name, 20e6, self.freq_spin.value() * 1e6, self,
        )
        if not dialog.exec():
            return
        rate, center = dialog.values()
        self.freq_spin.setValue(center / 1e6)
        self._load_source(self._file_source(path, rate, center))

    @staticmethod
    def _file_source(path: Path, rate: float, center: float) -> _PlaySource:
        def read(start: int, count: int, target=Path(path)) -> np.ndarray:
            # Open per read: a memmap kept alive would lock the file for the
            # whole session, and the copy is only a few MB.
            data = np.memmap(target, dtype=np.complex64, mode="r")
            try:
                return np.array(data[start:start + count], dtype=np.complex64)
            finally:
                del data
        total = Path(path).stat().st_size // 8
        return _PlaySource(Path(path).name, rate, total, center, read)

    # -------------------------------------------------------------- playback
    def _load_source(self, source: _PlaySource) -> None:
        if self._running:
            self._stop()
        if source.total < 4096:
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText(
                f"{source.label}: слишком мало отсчётов для кадра."
            )
            return
        self._play_source = source
        self._file_mode = True
        self._source = source.label
        self._running = True
        self._play_pos = 0.0
        self._play_playing = False
        self._play_busy = False
        self._play_frames.clear()
        self._last_frame = None
        self._last_image = None
        self.snapshot_btn.setEnabled(False)
        self.start_btn.setText("Остановить")
        self.play_btn.setEnabled(source.duration > 0.02)
        self.play_btn.setText("Играть")
        self.pos_slider.setEnabled(source.duration > 0.02)
        self.pos_slider.setRange(0, max(1, int(source.duration * 1000)))
        self.pos_slider.setValue(0)
        self._update_time_label()
        set_style(self.status, "color:#67e8f9; font-size:11px;")
        self.status.setText(
            f"{source.label} · {source.duration * 1000:.0f} мс. "
            "Читаю первый кадр…"
        )
        self._play_timer.stop()
        self._decode_at(0.0)

    def _decode_at(self, position: float) -> None:
        source = self._play_source
        if source is None or self._play_busy:
            return
        start = max(0.0, min(float(position),
                             max(0.0, source.duration - 0.005)))
        offset = int(start * source.rate)
        count = min(int(self._play_window * source.rate),
                    source.total - offset)
        if count < 4096:
            return
        self._play_busy = True
        self._frame_pos = start
        threading.Thread(
            target=self._play_worker,
            args=(
                source, offset, count,
                STANDARDS[self.standard_combo.currentData()],
                self.mode_combo.currentData(),
                self.invert_check.isChecked(),
            ),
            name="analog-video-playback",
            daemon=True,
        ).start()

    def _play_worker(self, source: _PlaySource, offset: int, count: int,
                     standard, mode: str, invert: bool) -> None:
        try:
            iq = source.read(offset, count)
            frame = decode_frame(
                iq, source.rate, standard, mode=mode, invert=invert,
            )
            if self._play_source is not source:
                return
            if frame is not None:
                self.frame_ready.emit(frame)
            elif not self._play_playing:
                self.decode_failed.emit(
                    f"{source.label}: кадр не собран за "
                    f"{count / source.rate * 1000:.0f} мс. Попробуйте другой "
                    "стандарт, AM/FM или инверсию."
                )
        except Exception as exc:
            if self._play_source is source and not self._play_playing:
                self.decode_failed.emit(f"{source.label}: {exc}")
        finally:
            if self._play_source is source:
                self._play_busy = False

    def _toggle_play(self) -> None:
        source = self._play_source
        if source is None:
            return
        if self._play_playing:
            self._pause()
            return
        if self._play_pos >= source.duration - 0.01:
            self._play_pos = 0.0
        self._play_playing = True
        self._play_origin = self._play_pos
        self._play_started = time.monotonic()
        self.play_btn.setText("Пауза")
        self._play_timer.start()
        self._decode_at(self._play_pos)

    def _pause(self) -> None:
        self._play_playing = False
        self._play_timer.stop()
        self.play_btn.setText("Играть")

    def _play_tick(self) -> None:
        source = self._play_source
        if source is None or not self._play_playing:
            return
        elapsed = time.monotonic() - self._play_started
        target = self._play_origin + elapsed
        if target >= source.duration - 0.005:
            self._play_pos = source.duration
            self._pause()
            self._update_time_label()
            return
        self._play_pos = target
        self._decode_at(target)
        self._update_time_label()

    def _seek(self) -> None:
        source = self._play_source
        if source is None:
            return
        position = self.pos_slider.value() / 1000.0
        self._play_pos = min(position, source.duration)
        self._play_frames.clear()
        if self._play_playing:
            self._play_origin = self._play_pos
            self._play_started = time.monotonic()
        self._update_time_label()
        self._decode_at(self._play_pos)

    def _update_time_label(self) -> None:
        source = self._play_source
        if source is None:
            self.time_label.setText("— / —")
            return
        self.time_label.setText(
            f"{self._play_pos:.2f} / {source.duration:.2f} с"
        )

    def _clear_source(self) -> None:
        self._play_playing = False
        self._play_timer.stop()
        self._play_source = None
        self._play_busy = False
        self._play_frames.clear()
        self.play_btn.setEnabled(False)
        self.play_btn.setText("Играть")
        self.pos_slider.setEnabled(False)
        self.pos_slider.setValue(0)
        self.time_label.setText("— / —")
        self._source = ""

    # ------------------------------------------------------ bench transmitter
    def _follow_rx(self, value: float) -> None:
        """Keep the test transmitter 1 MHz above the receiver."""
        if not (self._transmitter.active or self._stream.active):
            self.tx_freq_spin.setValue(min(6000.0, float(value) + 1.0))

    def _toggle_tx(self, checked: bool) -> None:
        if checked:
            if not self._tx_allowed():
                return
            self._start_tx_job("card")
        else:
            self._stop_tx_job()

    def _tx_allowed(self) -> bool:
        kind = getattr(self.session.config, "kind", "") if self.session else ""
        if kind == "pluto":
            self._on_tx_state(
                False,
                "для приёма выберите HackRF: один Pluto не может "
                "одновременно вещать и принимать здесь",
            )
            return False
        return True

    def _send_file(self) -> None:
        if self._transmitter.active or self._stream.active:
            self._on_tx_state(False, "сначала остановите текущую передачу")
            return
        if not self._tx_allowed():
            return
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Что передавать",
            str(RECORDINGS_DIR),
            "Картинка или видео (*.jpg *.jpeg *.png *.bmp *.mp4 *.mkv "
            "*.mov *.avi);;Все файлы (*)",
        )
        if path:
            self._start_tx_job("file", Path(path))

    def _start_tx_job(self, kind: str, path: Path | None = None) -> None:
        self._set_tx_buttons(False)
        set_style(self.tx_status, "color:#67e8f9; font-size:11px;")
        self.tx_status.setText("готовлю передачу…")
        threading.Thread(
            target=self._start_tx_worker, args=(kind, path),
            name="bench-tx", daemon=True,
        ).start()

    def _start_tx_worker(self, kind: str, path: Path | None) -> None:
        try:
            self._stop_engines()
            standard = STANDARDS[self.standard_combo.currentData()]
            freq = self.tx_freq_spin.value() * 1e6
            gain = self.tx_gain_spin.value()
            rate = DEFAULT_RATE
            if kind == "card":
                iq, field = build_testcard(
                    standard, rate, 0.04, DEFAULT_DEVIATION,
                )
                whole = (iq.size // field) * field
                uri = self._transmitter.start(
                    iq[:whole], rate, freq, gain,
                )
                label = f"тест-картинка · {uri}"
            else:
                suffix = path.suffix.lower() if path else ""
                if suffix in (".jpg", ".jpeg", ".png", ".bmp"):
                    rows = self._image_rows(path, standard)
                    iq, field = build_test_frame(
                        standard, rate, rows, DEFAULT_DEVIATION, fields=2,
                    )
                    whole = (iq.size // field) * field
                    uri = self._transmitter.start(
                        iq[:whole], rate, freq, gain,
                    )
                    label = f"{path.name} (цикл) · {uri}"
                else:
                    frames = self._video_rows(path, standard)
                    if not frames:
                        raise RuntimeError("в видео нет кадров")
                    self._stream.start(
                        frames, standard, 6.144e6, freq, gain,
                    )
                    label = f"{path.name} ({len(frames)} кадров)"
            self._tx_kind = kind
            self.tx_state.emit(
                True,
                f"передаю {label} · {freq / 1e6:.3f} МГц · {standard.name}",
            )
        except Exception as exc:
            self.tx_state.emit(False, f"не удалось: {exc}")

    def _stop_tx_job(self) -> None:
        self._set_tx_buttons(False)
        self.tx_status.setText("останавливаю…")
        threading.Thread(
            target=self._stop_tx_worker, name="bench-tx", daemon=True,
        ).start()

    def _stop_tx_worker(self) -> None:
        self._stop_engines()
        self.tx_state.emit(False, "передача остановлена")

    def _stop_engines(self) -> None:
        self._transmitter.stop()
        self._stream.stop()

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

        seconds = float(self.tx_duration_spin.value())
        if seconds <= 0:
            seconds = 10.0
        seconds = min(seconds, 10.0)
        # The stream runs at STREAM_RATE; ffmpeg scales with its own
        # antialiasing, so the composite does not alias.
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

    def _set_tx_buttons(self, enabled: bool) -> None:
        ready = enabled and PlutoTransmitter.available()
        self.tx_btn.setEnabled(ready)
        self.tx_file_btn.setEnabled(ready)
        self.tx_freq_spin.setEnabled(ready)
        self.tx_gain_spin.setEnabled(ready)
        self.tx_duration_spin.setEnabled(ready)

    def _on_tx_state(self, active: bool, text: str) -> None:
        self.tx_btn.blockSignals(True)
        self.tx_btn.setChecked(bool(active))
        self.tx_btn.blockSignals(False)
        if active:
            self._set_tx_buttons(False)
            self.tx_btn.setEnabled(True)
            self.tx_btn.setText("Стоп вещания")
        else:
            self._set_tx_buttons(True)
            self.tx_btn.setText("Вещать тест-картинку")
        self._tx_timer.stop()
        if active:
            seconds = float(self.tx_duration_spin.value())
            if seconds > 0:
                self._tx_timer.start(int(seconds * 1000))
        set_style(
            self.tx_status,
            f"color:{'#4ade80' if active else '#94a3b8'}; font-size:11px;",
        )
        self.tx_status.setText(text)

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
        self._source = ""
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
        path = Path(str(self.session.config.uri))
        if path.suffix.lower() == ".json":
            info = load_info(path)
            if info is not None:
                path = Path(info.path)
        if not path.exists():
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText(f"Запись не найдена: {path}")
            return
        rate = float(self.session.config.sample_rate)
        if rate <= 0:
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText("В записи не указана частота дискретизации.")
            return
        self._old = {}
        self._load_source(self._file_source(
            path, rate, float(self.session.config.center_freq),
        ))

    def _show_failure(self, message: str) -> None:
        if not self._running:
            return
        if self._play_source is not None:
            # A player stays usable: the user can seek to another part.
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText(message)
            return
        self.start_btn.setText("Смотреть")
        self._running = False
        set_style(self.status, "color:#f87171; font-size:11px;")
        self.status.setText(message)

    def _stop(self) -> None:
        if self._transmitter.active:
            self._transmitter.stop()
            self._on_tx_state(False, "передача остановлена")
        if not self._running:
            return
        self._running = False
        self._clear_source()
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
        picture = frame.image
        if self._play_source is not None and self.smooth_check.isChecked():
            picture = self._smoothed(picture)
        image = QImage(
            picture.tobytes(),
            picture.shape[1],
            picture.shape[0],
            picture.strides[0],
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
        if self._play_source is not None:
            self.pos_slider.setValue(int(self._frame_pos * 1000))
            self._update_time_label()
        set_style(self.status, "color:#4ade80; font-size:11px;")
        # A woven frame is a picture even when the scene is plain: line
        # correlation is low on a flat wall, so the frame lock matters more.
        good = frame.frame_locked or frame.quality >= 0.45
        quality = "картинка" if good else "похоже на шум/снег"
        source = f"{self._source} · " if self._source else ""
        self.status.setText(
            f"{source}{frame.standard} · {frame.line_hz:.1f} Гц · "
            f"{frame.lines} строк · "
            f"{'кадр' if frame.frame_locked else 'поле/фрагмент'} · "
            f"синхронизация: {'есть' if frame.locked else 'слабая'} · "
            f"качество: {quality} ({frame.quality:.2f})"
        )

    def _smoothed(self, picture: np.ndarray) -> np.ndarray:
        """Average the last few frames: static scenes lose their noise."""
        self._play_frames.append(picture.astype(np.float32))
        while len(self._play_frames) > 4:
            self._play_frames.pop(0)
        if len(self._play_frames) == 1:
            return picture
        return np.clip(
            np.mean(self._play_frames, axis=0), 0, 255,
        ).astype(np.uint8)

    def _forget_frames(self, *_args) -> None:
        """Drop accumulated frames when the decoding settings change."""
        self._play_frames.clear()

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
