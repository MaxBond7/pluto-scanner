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
from ..ml.model import SoftmaxModel, train_and_save


class _TrainWorker(QThread):
    progress = Signal(int, int, str)
    done = Signal(object, object)
    failed = Signal(str)

    def __init__(self, path: Path, per_class: int, epochs: int,
                 seed: int = 1) -> None:
        super().__init__()
        self.path = path
        self.per_class = per_class
        self.epochs = epochs
        self.seed = seed

    def run(self) -> None:
        try:
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
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.model_path = Path(model_path)
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
        self.train_btn.clicked.connect(self.start_training)
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(self.refresh)
        self.folder_btn = QPushButton("Папка модели")
        self.folder_btn.clicked.connect(self._open_folder)
        row.addWidget(self.train_btn, 1)
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
        self._model = SoftmaxModel.load(self.model_path)
        if self._model is None:
            self.model_label.setText(
                "Модель не обучена. Нажмите «Обучить на синтетике»."
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
            f"Файл: {self.model_path}\n"
            f"Источник: {self._model.source} · обучена: {when} · "
            f"примеров: {int(meta.get('n', 0))}"
        )
        self.accuracy_label.setText(
            f"Точность на отложенной выборке: "
            f"{self._model.accuracy * 100:.1f}%   "
            f"Согласие с эвристикой: "
            f"{float(meta.get('heuristic_agreement', 0.0)) * 100:.1f}%"
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
    def start_training(self) -> None:
        if self._worker is not None and self._worker.isRunning():
            return
        self.train_btn.setEnabled(False)
        self.refresh_btn.setEnabled(False)
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.log.clear()
        self.log.appendPlainText("Генерация датасета и обучение…")
        self.status.setStyleSheet("color:#c4b5fd; font-size:10px;")
        self.status.setText("Это может занять 10–40 секунд.")
        self._worker = _TrainWorker(
            self.model_path, per_class=60, epochs=600, seed=1
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
        self.status.setText(
            f"Готово: точность {metrics['accuracy'] * 100:.1f}% "
            f"на синтетике. Модель применена к новым событиям."
        )
        self._worker = None
        self.refresh()
        self.model_changed.emit(model)

    def _on_failed(self, message: str) -> None:
        self.train_btn.setEnabled(True)
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
