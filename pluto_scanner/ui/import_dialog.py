"""Simple import dialog for SigMF and raw float32 IQ datasets."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtWidgets import (
    QComboBox,
    QDialog,
    QDialogButtonBox,
    QDoubleSpinBox,
    QFileDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..drone.features import CLASS_RU
from ..ml.importers import import_raw_iq, import_sigmf

_LABELS = [
    "FHSS", "TELEMETRY", "VIDEO_ANALOG", "VIDEO_DIGITAL", "WIFI", "NARROW",
]


class DatasetImportDialog(QDialog):
    def __init__(self, out_dir: str | Path,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.out_dir = Path(out_dir)
        self.result_info = None
        self.setWindowTitle("Импорт IQ-датасета")
        self.resize(620, 320)
        self.setStyleSheet("QDialog { background:#0b1020; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        title = QLabel("ИМПОРТ SIGMF / RAW IQ")
        title.setStyleSheet(
            "color:#67e8f9; font-size:16px; font-weight:700;"
        )
        root.addWidget(title)
        hint = QLabel(
            "Скачайте датасет с первоисточника. Сюда кладётся только "
            "выбранный файл; лицензия остаётся у автора."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(hint)

        form = QFormLayout()
        form.setSpacing(6)

        path_row = QHBoxLayout()
        self.path_edit = QLineEdit()
        self.path_edit.setPlaceholderText(
            r"dataset.sigmf-meta или файл .dat"
        )
        browse = QPushButton("Обзор…")
        browse.clicked.connect(self._browse)
        path_row.addWidget(self.path_edit, 1)
        path_row.addWidget(browse)
        form.addRow("Файл", path_row)

        self.format_combo = QComboBox()
        self.format_combo.addItem("Авто", "auto")
        self.format_combo.addItem("SigMF", "sigmf")
        self.format_combo.addItem("Raw float32 I/Q", "dat")
        form.addRow("Формат", self.format_combo)

        self.label_combo = QComboBox()
        self.label_combo.addItem("без метки", "")
        for key in _LABELS:
            self.label_combo.addItem(CLASS_RU.get(key, key), key)
        form.addRow("Метка", self.label_combo)

        self.rate_spin = QDoubleSpinBox()
        self.rate_spin.setRange(0.1, 200.0)
        self.rate_spin.setDecimals(3)
        self.rate_spin.setSuffix(" MS/s")
        self.rate_spin.setValue(60.0)
        form.addRow("Частота дискретизации", self.rate_spin)

        self.center_spin = QDoubleSpinBox()
        self.center_spin.setRange(0.0, 6000.0)
        self.center_spin.setDecimals(3)
        self.center_spin.setSuffix(" MHz")
        self.center_spin.setValue(2437.5)
        form.addRow("Центр", self.center_spin)

        self.seconds_spin = QDoubleSpinBox()
        self.seconds_spin.setRange(0.1, 60.0)
        self.seconds_spin.setDecimals(1)
        self.seconds_spin.setSuffix(" с")
        self.seconds_spin.setValue(2.0)
        form.addRow("Взять секунд", self.seconds_spin)
        root.addLayout(form)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#94a3b8; font-size:10px;")
        root.addWidget(self.status)

        buttons = QDialogButtonBox(
            QDialogButtonBox.StandardButton.Ok
            | QDialogButtonBox.StandardButton.Cancel
        )
        buttons.accepted.connect(self._do_import)
        buttons.rejected.connect(self.reject)
        root.addWidget(buttons)

    def _browse(self) -> None:
        path, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите SigMF или raw IQ",
            "",
            "SigMF (*.sigmf-meta);;Raw IQ (*.dat *.cf32);;All files (*)",
        )
        if path:
            self.path_edit.setText(path)

    def _do_import(self) -> None:
        src = Path(self.path_edit.text().strip())
        if not src.exists():
            QMessageBox.warning(self, "Импорт", "Файл не найден.")
            return
        fmt = str(self.format_combo.currentData())
        if fmt == "auto":
            fmt = "sigmf" if src.suffix == ".sigmf-meta" else "dat"
        label = str(self.label_combo.currentData() or "")
        try:
            if fmt == "sigmf":
                result = import_sigmf(
                    src, self.out_dir,
                    label=label or None,
                    max_seconds=float(self.seconds_spin.value()),
                )
            else:
                result = import_raw_iq(
                    src, self.out_dir,
                    sample_rate=float(self.rate_spin.value()) * 1e6,
                    center_freq=float(self.center_spin.value()) * 1e6,
                    label=label or None,
                    max_seconds=float(self.seconds_spin.value()),
                )
        except Exception as exc:
            QMessageBox.critical(self, "Импорт", str(exc))
            return
        self.result_info = result.info
        self.status.setStyleSheet("color:#4ade80; font-size:10px;")
        self.status.setText(f"Импортировано: {result.info.recording_id}")
        self.accept()
