"""Long IQ recording tab: record the selected radio and replay recordings."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QComboBox,
    QDoubleSpinBox,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import format_freq
from ..drone.features import CLASS_RU
from ..recordings import RecordingInfo, estimated_bytes, format_size

ML_LABEL_CLASSES = [
    "FHSS", "TELEMETRY", "VIDEO_ANALOG", "VIDEO_DIGITAL", "WIFI", "NARROW",
]


class RecordingPanel(QWidget):
    record_requested = Signal(float)
    stop_requested = Signal()
    play_requested = Signal(str)
    stop_playback_requested = Signal()
    delete_requested = Signal(str)
    refresh_requested = Signal()
    label_changed = Signal(str, str)
    import_requested = Signal()

    def __init__(self, recordings_dir: str | Path,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.recordings_dir = Path(recordings_dir)
        self._infos: dict[str, RecordingInfo] = {}
        self._busy = False
        self._fs = 1.024e6
        self._device_name = ""
        self._device_kind = ""

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        title = QLabel("ЗАПИСЬ IQ")
        title.setStyleSheet(
            "color:#a78bfa; font-size:15px; font-weight:600; padding:2px;"
        )
        root.addWidget(title)

        hint = QLabel(
            "Сырой IQ с текущей настройки: спектр, водопад, контакты, "
            "демодуляция и повторное воспроизведение без платы."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(hint)

        params = QGroupBox("Новая запись")
        grid = QVBoxLayout(params)
        grid.setSpacing(5)

        self.device_label = QLabel("Устройство: —")
        self.device_label.setStyleSheet("color:#d7e2f0; font-size:11px;")
        grid.addWidget(self.device_label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.duration_spin = QDoubleSpinBox()
        self.duration_spin.setRange(1.0, 60.0)
        self.duration_spin.setDecimals(1)
        self.duration_spin.setSingleStep(1.0)
        self.duration_spin.setSuffix(" с")
        self.duration_spin.setValue(10.0)
        self.duration_spin.valueChanged.connect(self._update_estimate)
        row.addWidget(QLabel("Длительность"))
        row.addWidget(self.duration_spin, 1)
        self.record_btn = QPushButton("Начать запись")
        self.record_btn.setMinimumHeight(30)
        self.record_btn.clicked.connect(self._toggle_record)
        row.addWidget(self.record_btn, 2)
        grid.addLayout(row)

        self.estimate = QLabel("")
        self.estimate.setWordWrap(True)
        self.estimate.setStyleSheet("color:#8fa6c0; font-size:10px;")
        grid.addWidget(self.estimate)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(14)
        grid.addWidget(self.progress)
        self.status = QLabel("Выберите устройство и нажмите «Начать запись».")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#94a3b8; font-size:10px;")
        grid.addWidget(self.status)
        root.addWidget(params)

        box = QGroupBox("Записи")
        box_layout = QVBoxLayout(box)
        box_layout.setSpacing(5)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Файл", "Дата", "Длит.", "Центр / полоса", "Размер", "Статус"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.SingleSelection
        )
        self.table.setSelectionBehavior(
            QAbstractItemView.SelectionBehavior.SelectRows
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        self.table.setStyleSheet("QTableWidget { font-size: 10px; }")
        self.table.itemSelectionChanged.connect(self._update_buttons)
        self.table.itemDoubleClicked.connect(lambda *_: self._play())
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((0, 72, 50, 112, 60, 76)):
            if column:
                self.table.setColumnWidth(column, width)
        box_layout.addWidget(self.table, 1)

        self.summary = QLabel("Записей: 0")
        self.summary.setStyleSheet("color:#8fa6c0; font-size:10px;")
        box_layout.addWidget(self.summary)

        label_row = QHBoxLayout()
        label_row.setSpacing(5)
        self.label_combo = QComboBox()
        self.label_combo.addItem("без метки", "")
        for key in ML_LABEL_CLASSES:
            self.label_combo.addItem(CLASS_RU.get(key, key), key)
        self.label_btn = QPushButton("Сохранить метку")
        self.label_btn.clicked.connect(self._apply_label)
        label_row.addWidget(QLabel("Метка"))
        label_row.addWidget(self.label_combo, 1)
        label_row.addWidget(self.label_btn)
        box_layout.addLayout(label_row)
        self.table.itemSelectionChanged.connect(self._sync_label)

        actions = QHBoxLayout()
        actions.setSpacing(5)
        self.play_btn = QPushButton("Воспроизвести")
        self.play_btn.clicked.connect(self._play)
        self.stop_play_btn = QPushButton("Стоп")
        self.stop_play_btn.clicked.connect(self.stop_playback_requested)
        self.delete_btn = QPushButton("Удалить")
        self.delete_btn.clicked.connect(self._delete)
        self.folder_btn = QPushButton("Папка")
        self.folder_btn.clicked.connect(self._open_folder)
        self.import_btn = QPushButton("Импорт…")
        self.import_btn.setToolTip(
            "SigMF или raw float32 IQ из открытого датасета"
        )
        self.import_btn.clicked.connect(self.import_requested)
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh_requested)
        actions.addWidget(self.play_btn, 1)
        actions.addWidget(self.stop_play_btn)
        actions.addWidget(self.delete_btn)
        actions.addWidget(self.folder_btn)
        actions.addWidget(self.import_btn)
        actions.addWidget(self.refresh_btn)
        box_layout.addLayout(actions)
        root.addWidget(box, 1)

        self._update_estimate()
        self._update_buttons()

    # ------------------------------------------------------------------ device
    def set_device(self, name: str, kind: str, sample_rate: float) -> None:
        self._device_name = name
        self._device_kind = kind
        self._fs = max(1000.0, float(sample_rate))
        key = (name, kind, round(self._fs, 3))
        changed = key != getattr(self, "_device_key", None)
        self._device_key = key
        if not name:
            self.device_label.setText("Устройство: —")
        else:
            self.device_label.setText(f"Устройство: {name}")
        if changed and not self._busy:
            if name and kind != "iqfile":
                self.status.setStyleSheet("color:#94a3b8; font-size:10px;")
                self.status.setText(
                    f"Готов к записи: {name}, {self._fs / 1e6:.3f} MS/s."
                )
            elif kind == "iqfile":
                self.status.setStyleSheet("color:#facc15; font-size:10px;")
                self.status.setText(
                    "Это воспроизведение: записывать с него нельзя."
                )
            else:
                self.status.setStyleSheet("color:#94a3b8; font-size:10px;")
                self.status.setText(
                    "Выберите устройство и нажмите «Начать запись»."
                )
        self._update_estimate()
        self._update_buttons()

    # --------------------------------------------------------------- recordings
    def set_recordings(self, infos: list[RecordingInfo]) -> None:
        selected = self.selected_id()
        self._infos = {info.recording_id: info for info in infos}
        self.table.setRowCount(0)
        total_size = 0
        for info in infos:
            row = self.table.rowCount()
            self.table.insertRow(row)
            total_size += info.size_bytes
            values = [
                info.recording_id,
                time.strftime("%d.%m %H:%M", time.localtime(info.created)),
                f"{info.duration_s:.1f} с" if info.samples else "—",
                f"{info.center_freq / 1e6:.3f} / "
                f"{info.sample_rate / 1e6:.3f} МГц",
                format_size(info.size_bytes),
                self._status_text(info),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, info.recording_id)
                if column == 0:
                    tip = str(info.path)
                    if info.label:
                        tip += f"\nМетка: {CLASS_RU.get(info.label, info.label)}"
                    item.setToolTip(tip)
                if column == 5:
                    if info.complete:
                        item.setForeground(QColor("#4ade80"))
                    elif info.exists:
                        item.setForeground(QColor("#facc15"))
                    else:
                        item.setForeground(QColor("#f87171"))
                self.table.setItem(row, column, item)
            if info.recording_id == selected:
                self.table.selectRow(row)
        self.summary.setText(
            f"Записей: {len(infos)} · всего {format_size(total_size)}"
        )
        self._update_buttons()
        self._sync_label()

    def selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def selected_info(self) -> RecordingInfo | None:
        recording_id = self.selected_id()
        return self._infos.get(recording_id) if recording_id else None

    @staticmethod
    def _status_text(info: RecordingInfo) -> str:
        if not info.exists:
            return "нет файла"
        if info.error:
            return "ошибка"
        if info.complete:
            return "готово"
        return "не завершена"

    def _update_buttons(self) -> None:
        has_device = bool(self._device_name) and self._device_kind != "iqfile"
        self.record_btn.setEnabled(has_device or self._busy)
        info = self.selected_info()
        can_play = info is not None and info.size_bytes > 0
        self.play_btn.setEnabled(can_play and not self._busy)
        self.delete_btn.setEnabled(info is not None and not self._busy)
        self.label_btn.setEnabled(info is not None and not self._busy)
        self.label_combo.setEnabled(info is not None and not self._busy)

    # ------------------------------------------------------------------- label
    def _sync_label(self) -> None:
        info = self.selected_info()
        value = info.label if info is not None else ""
        index = self.label_combo.findData(value)
        self.label_combo.blockSignals(True)
        self.label_combo.setCurrentIndex(max(0, index))
        self.label_combo.blockSignals(False)

    def _apply_label(self) -> None:
        info = self.selected_info()
        if info is None:
            return
        self.label_changed.emit(
            info.recording_id, str(self.label_combo.currentData() or "")
        )

    # ------------------------------------------------------------------ record
    def _toggle_record(self) -> None:
        if self._busy:
            self.stop_requested.emit()
        else:
            self.record_requested.emit(float(self.duration_spin.value()))

    def begin_recording(self, info: RecordingInfo, seconds: float) -> None:
        self._busy = True
        self.record_btn.setText("Остановить запись")
        self.duration_spin.setEnabled(False)
        self.progress.setRange(0, 1000)
        self.progress.setValue(0)
        self.status.setStyleSheet("color:#a78bfa; font-size:10px;")
        self.status.setText(
            f"Пишу {info.device_name}: {info.center_freq / 1e6:.3f} МГц, "
            f"{info.sample_rate / 1e6:.3f} МГц полоса, {seconds:.1f} с…"
        )
        self._update_buttons()

    def set_progress(self, elapsed: float, progress: float,
                     dropped: int) -> None:
        self.progress.setValue(int(max(0.0, min(1.0, progress)) * 1000))
        text = f"Записано {elapsed:.1f} с"
        if dropped:
            text += f" · потеряно {dropped} отсчётов"
        self.status.setText(text)

    def finish_recording(self, info: RecordingInfo | None) -> None:
        self._busy = False
        self.record_btn.setText("Начать запись")
        self.duration_spin.setEnabled(True)
        self.progress.setRange(0, 100)
        self.progress.setValue(100 if info and info.complete else 0)
        if info is None:
            self.status.setText("Запись не началась.")
            self.status.setStyleSheet("color:#f87171; font-size:10px;")
        elif info.complete:
            self.status.setStyleSheet("color:#4ade80; font-size:10px;")
            extra = (
                f", потеряно {info.dropped_samples}"
                if info.dropped_samples else ""
            )
            self.status.setText(
                f"Готово: {info.recording_id}, {info.duration_s:.1f} с, "
                f"{format_size(info.size_bytes)}{extra}."
            )
        else:
            self.status.setStyleSheet("color:#facc15; font-size:10px;")
            self.status.setText(
                f"Запись не завершена: {info.error or 'нет данных'}. "
                "Файл сохранён, играть можно."
            )
        self._update_estimate()
        self._update_buttons()

    def _update_estimate(self) -> None:
        seconds = float(self.duration_spin.value())
        estimate = estimated_bytes(self._fs, seconds)
        self.estimate.setText(
            f"Оценка размера: {format_size(estimate)} · "
            f"{self._fs / 1e6:.3f} MS/s · cf32"
        )

    # -------------------------------------------------------------------- play
    def _play(self) -> None:
        info = self.selected_info()
        if info is not None:
            self.play_requested.emit(info.recording_id)

    def _delete(self) -> None:
        info = self.selected_info()
        if info is not None:
            self.delete_requested.emit(info.recording_id)

    def _open_folder(self) -> None:
        self.recordings_dir.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.recordings_dir.resolve()))
        )
