"""Offline ML model panel: train on synthetic IQ, inspect classes."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QThread, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QGroupBox,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPlainTextEdit,
    QProgressBar,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..drone.features import CLASS_RU
from ..ml.dataset import dataset_summary, train_from_recordings
from ..ml.model import SoftmaxModel, train_and_save
from ..paths import DEFAULT_ML_MODEL, RECORDINGS_DIR


class _TrainWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object, object)
    failed = Signal(str)

    def __init__(self, path: Path, per_class: int, epochs: int,
                 seed: int = 1, mode: str = "synthetic",
                 recordings_dir: Path | None = None) -> None:
        super().__init__()
        self.path = path
        self.per_class = per_class
        self.epochs = epochs
        self.seed = seed
        self.mode = mode
        self.recordings_dir = recordings_dir or RECORDINGS_DIR

    def run(self) -> None:
        try:
            if self.mode == "recordings":
                model, metrics = train_from_recordings(
                    self.path,
                    self.recordings_dir,
                    include_synthetic=True,
                    synthetic_per_class=max(8, self.per_class // 2),
                    epochs=self.epochs,
                    seed=self.seed,
                    progress=lambda done, total, label: self.progress.emit(
                        done, total, label
                    ),
                )
            else:
                model, metrics = train_and_save(
                    self.path,
                    per_class=self.per_class,
                    epochs=self.epochs,
                    seed=self.seed,
                    progress=lambda done, total, label: self.progress.emit(
                        done, total, label
                    ),
                )
        except Exception as exc:
            self.failed.emit(str(exc))
            return
        self.done.emit(model, metrics)


class MLPanel(QWidget):
    model_changed = Signal(object)

    def __init__(self, model_path: str | Path,
                 recordings_dir: str | Path | None = None,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model_path = Path(model_path)
        self.recordings_dir = Path(recordings_dir or RECORDINGS_DIR)
        self._worker: _TrainWorker | None = None
        self._model: SoftmaxModel | None = None

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        title = QLabel("ML-КЛАССИФИКАТОР")
        title.setStyleSheet(
            "color:#c4b5fd; font-size:15px; font-weight:600; padding:2px;"
        )
        root.addWidget(title)

        hint = QLabel(
            "Вторая гипотеза к эвристике дрон-монитора. Обучение офлайн на "
            "синтетическом IQ; модель не заменяет декодирование протокола."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(hint)

        box = QGroupBox("Модель")
        bl = QVBoxLayout(box)
        bl.setSpacing(5)
        self.model_label = QLabel("")
        self.model_label.setWordWrap(True)
        self.model_label.setStyleSheet(
            "color:#d7e2f0; font-size:11px;"
        )
        bl.addWidget(self.model_label)

        self.data_label = QLabel("")
        self.data_label.setWordWrap(True)
        self.data_label.setStyleSheet(
            "color:#8fa6c0; font-size:10px;"
        )
        bl.addWidget(self.data_label)

        self.accuracy_label = QLabel("")
        self.accuracy_label.setWordWrap(True)
        self.accuracy_label.setStyleSheet(
            "color:#4ade80; font-size:11px;"
        )
        bl.addWidget(self.accuracy_label)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.train_btn = QPushButton("Обучить на синтетике")
        self.train_btn.setMinimumHeight(30)
        self.train_btn.clicked.connect(
            lambda: self.start_training("synthetic")
        )
        self.real_btn = QPushButton("Обучить на записях")
        self.real_btn.setMinimumHeight(30)
        self.real_btn.clicked.connect(
            lambda: self.start_training("recordings")
        )
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        self.folder_btn = QPushButton("Папка модели")
        self.folder_btn.clicked.connect(self._open_folder)
        row.addWidget(self.train_btn, 1)
        row.addWidget(self.real_btn, 1)
        row.addWidget(self.refresh_btn)
        row.addWidget(self.folder_btn)
        bl.addLayout(row)

        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(14)
        bl.addWidget(self.progress)
        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#94a3b8; font-size:10px;")
        bl.addWidget(self.status)
        root.addWidget(box)

        classes_box = QGroupBox("Классы")
        cl = QVBoxLayout(classes_box)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels(
            ["Класс", "precision", "recall", "support"]
        )
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionMode(
            QAbstractItemView.SelectionMode.NoSelection
        )
        self.table.setEditTriggers(
            QAbstractItemView.EditTrigger.NoEditTriggers
        )
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((0, 90, 90, 70)):
            if column:
                self.table.setColumnWidth(column, width)
        cl.addWidget(self.table, 1)
        root.addWidget(classes_box, 1)

        self.log = QPlainTextEdit()
        self.log.setReadOnly(True)
        self.log.setMaximumHeight(110)
        self.log.setStyleSheet(
            "QPlainTextEdit { background:#080d19; color:#8fa6c0;"
            " border:1px solid #1e2d4a; font-size:10px; }"
        )
        root.addWidget(self.log)

        self.refresh()

    # ------------------------------------------------------------------ model
    def refresh(self) -> None:
        summary = dataset_summary(self.recordings_dir)
        counts = summary.get("counts") or {}
        label_text = ", ".join(
            f"{CLASS_RU.get(key, key)}={value}"
            for key, value in counts.items()
        )
        self.data_label.setText(
            f"Записей: {summary['recordings']} · с меткой: "
            f"{summary['labeled']}"
            + (f" ({label_text})" if label_text else "")
        )
        self.real_btn.setEnabled(
            summary["labeled"] > 0
            and (self._worker is None or not self._worker.isRunning())
        )
        user_model = SoftmaxModel.load(self.model_path)
        self._using_default = user_model is None
        self._model = user_model or SoftmaxModel.load(DEFAULT_ML_MODEL)
        if self._model is None:
            self.model_label.setText(
                "Модель не обучена. Обучите на синтетике или на размеченных записях."
            )
            self.accuracy_label.setText("")
            self.table.setRowCount(0)
            return
        meta = self._model.metadata
        trained = float(meta.get("trained_at") or 0.0)
        when = (
            time.strftime("%d.%m.%Y %H:%M", time.localtime(trained))
            if trained else "—"
        )
        self.model_label.setText(
            ("Встроенная синтетическая модель (можно заменить своей)\n"
             if self._using_default else f"Файл: {self.model_path}\n")
            + f"Источник: {self._model.source} · обучена: {when} · "
            f"примеров: {int(meta.get('total_blocks', meta.get('n', 0)))}"
        )
        real_blocks = meta.get("real_blocks")
        extra = ""
        if real_blocks is not None:
            extra = (
                f"   Реальных блоков: {int(real_blocks)}, "
                f"синтетических: {int(meta.get('synthetic_blocks', 0))}"
            )
        self.accuracy_label.setText(
            f"Точность: {self._model.accuracy * 100:.1f}%"
            + (" (отложенная выборка)" if meta.get("holdout", True)
               else " (на обучении — мало записей)")
            + extra
        )
        per_class = meta.get("per_class") or {}
        self.table.setRowCount(0)
        for name in self._model.classes:
            row = self.table.rowCount()
            self.table.insertRow(row)
            stats = per_class.get(name) or {}
            values = [
                CLASS_RU.get(name, name),
                f"{float(stats.get('precision', 0.0)):.2f}",
                f"{float(stats.get('recall', 0.0)):.2f}",
                str(int(stats.get("support", 0))),
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, name)
                self.table.setItem(row, column, item)
        self.log.appendPlainText(
            f"Загружена модель: {self._model.source}, "
            f"{len(self._model.classes)} классов."
        )

    # ------------------------------------------------------------------ train
    def start_training(self, mode: str = "synthetic") -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.train_btn.setEnabled(False)
        self.real_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log.clear()
        if mode == "recordings":
            self.log.appendPlainText(
                "Размеченные записи → признаки → обучение…"
            )
            self.status.setText(
                "Использую размеченные записи + синтетику для баланса."
            )
        else:
            self.log.appendPlainText("Генерация датасета и обучение…")
            self.status.setText("Это может занять 10–40 секунд.")
        self.status.setStyleSheet("color:#c4b5fd; font-size:10px;")
        self._worker = _TrainWorker(
            self.model_path, per_class=60, epochs=600, seed=1,
            mode=mode, recordings_dir=self.recordings_dir,
        )
        self._worker.progress.connect(self._on_progress)
        self._worker.done.connect(self._on_done)
        self._worker.failed.connect(self._on_failed)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.start()

    def _on_progress(self, done: int, total: int, label: str) -> None:
        self.progress.setValue(int(done * 100 / max(1, total)))
        self.log.appendPlainText(
            f"[{done}/{total}] {CLASS_RU.get(label, label)}"
        )

    def _on_done(self, model, metrics) -> None:
        self.train_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.progress.setValue(100)
        self.status.setStyleSheet("color:#4ade80; font-size:10px;")
        source = metrics.get("source", "synthetic")
        real = metrics.get("real_blocks")
        suffix = (
            f", реальных блоков {real}" if real is not None else ""
        )
        self.status.setText(
            f"Готово ({source}{suffix}): точность "
            f"{metrics['accuracy'] * 100:.1f}%. Модель применена."
        )
        self._worker = None
        self.refresh()
        self.model_changed.emit(model)

    def _on_failed(self, message: str) -> None:
        self.train_btn.setEnabled(True)
        self.real_btn.setEnabled(True)
        self.refresh_btn.setEnabled(True)
        self.progress.setValue(0)
        self.status.setStyleSheet("color:#f87171; font-size:10px;")
        self.status.setText(f"Ошибка обучения: {message}")
        self._worker = None

    def _open_folder(self) -> None:
        self.model_path.parent.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(
            QUrl.fromLocalFile(str(self.model_path.parent.resolve()))
        )
