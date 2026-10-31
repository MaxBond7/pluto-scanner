"""Band-scan controls, live graph and detection table.

The panel owns no scanning logic: it emits :attr:`start_requested` and
:attr:`stop_requested`; :class:`MainWindow` drives :class:`ScanController`.
That separation keeps the UI responsive and makes the panel usable in tests.
"""
from __future__ import annotations

import csv
import math
import time
from pathlib import Path

from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDoubleSpinBox,
    QGridLayout,
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

from ..config import PLUTO_MAX_FREQ, PLUTO_MIN_FREQ, format_bw, format_freq
from ..scanner.recorder import load_bundle
from .scan_graph import ScanGraph


class ScanPanel(QWidget):
    """Full-range sweep tab."""

    start_requested = Signal()
    stop_requested = Signal()
    pause_requested = Signal()
    resume_requested = Signal()
    export_requested = Signal()
    compare_requested = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._scanning = False
        self._paused = False
        self._sample_rate = 1.024e6
        self._scan_started = 0.0
        self._last_bundle: str | None = None
        self._rows = 0

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        title = QLabel("СКАНИРОВАНИЕ ДИАПАЗОНА")
        title.setStyleSheet(
            "color:#67e8f9; font-size:15px; font-weight:600; padding:2px;"
        )
        root.addWidget(title)

        params = QGroupBox("Параметры свипа")
        grid = QGridLayout(params)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        self.start_spin = QDoubleSpinBox()
        self.start_spin.setRange(PLUTO_MIN_FREQ / 1e6, PLUTO_MAX_FREQ / 1e6)
        self.start_spin.setDecimals(3)
        self.start_spin.setSuffix(" MHz")
        self.start_spin.setValue(PLUTO_MIN_FREQ / 1e6)
        self.start_spin.setKeyboardTracking(False)

        self.end_spin = QDoubleSpinBox()
        self.end_spin.setRange(PLUTO_MIN_FREQ / 1e6, PLUTO_MAX_FREQ / 1e6)
        self.end_spin.setDecimals(3)
        self.end_spin.setSuffix(" MHz")
        self.end_spin.setValue(PLUTO_MAX_FREQ / 1e6)
        self.end_spin.setKeyboardTracking(False)

        self.step_spin = QDoubleSpinBox()
        self.step_spin.setRange(25.0, 20000.0)
        self.step_spin.setDecimals(1)
        self.step_spin.setSuffix(" kHz")
        self.step_spin.setValue(800.0)
        self.step_spin.setKeyboardTracking(False)

        self.preset_btn = QPushButton("Весь диапазон Pluto")
        self.preset_btn.clicked.connect(self._full_range)

        grid.addWidget(QLabel("От"), 0, 0)
        grid.addWidget(self.start_spin, 0, 1)
        grid.addWidget(QLabel("До"), 0, 2)
        grid.addWidget(self.end_spin, 0, 3)
        grid.addWidget(QLabel("Шаг"), 1, 0)
        grid.addWidget(self.step_spin, 1, 1)
        grid.addWidget(self.preset_btn, 1, 2, 1, 2)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        root.addWidget(params)

        self.estimate = QLabel("")
        self.estimate.setWordWrap(True)
        self.estimate.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(self.estimate)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.start_btn = QPushButton("Старт сканирования")
        self.start_btn.setMinimumHeight(30)
        self.start_btn.clicked.connect(self._toggle)
        self.compare_btn = QPushButton("Сравнить с фоном…")
        self.compare_btn.clicked.connect(self.compare_requested)
        self.compare_btn.setEnabled(False)
        self.pause_btn = QPushButton("Пауза")
        self.pause_btn.setEnabled(False)
        self.pause_btn.clicked.connect(self._toggle_pause)
        self.export_btn = QPushButton("Экспорт CSV…")
        self.export_btn.setEnabled(False)
        self.export_btn.clicked.connect(self.export_requested)
        self.folder_btn = QPushButton("Папка сканов")
        self.folder_btn.clicked.connect(self._open_folder)
        actions.addWidget(self.start_btn, 1)
        actions.addWidget(self.pause_btn)
        actions.addWidget(self.compare_btn)
        actions.addWidget(self.export_btn)
        actions.addWidget(self.folder_btn)
        root.addLayout(actions)

        progress_row = QHBoxLayout()
        progress_row.setSpacing(6)
        self.progress = QProgressBar()
        self.progress.setRange(0, 100)
        self.progress.setValue(0)
        self.progress.setTextVisible(False)
        self.progress.setFixedHeight(14)
        self.step_label = QLabel("Готов")
        self.step_label.setMinimumWidth(190)
        self.step_label.setStyleSheet("color:#8fa6c0; font-size:10px;")
        progress_row.addWidget(self.progress, 1)
        progress_row.addWidget(self.step_label)
        root.addLayout(progress_row)

        self.graph = ScanGraph()
        self.graph.setMinimumHeight(210)
        root.addWidget(self.graph, 3)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Частота", "дБ", "SNR", "Тип", "Ширина", "Шаг"]
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
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        self.table.setColumnWidth(1, 58)
        self.table.setColumnWidth(2, 52)
        self.table.setColumnWidth(5, 54)
        root.addWidget(self.table, 2)

        self.status = QLabel("Выберите устройство и задайте диапазон.")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#94a3b8; font-size:11px;")
        root.addWidget(self.status)

        for widget in (self.start_spin, self.end_spin, self.step_spin):
            widget.valueChanged.connect(self._update_estimate)
        self._update_estimate()

    # ------------------------------------------------------------------ public
    def values(self) -> tuple[float, float, float]:
        return (
            float(self.start_spin.value()) * 1e6,
            float(self.end_spin.value()) * 1e6,
            float(self.step_spin.value()) * 1e3,
        )

    def set_context(self, center_hz: float, sample_rate_hz: float) -> None:
        self._sample_rate = max(1000.0, float(sample_rate_hz))
        # A sweep step wider than the capture band leaves gaps.  Offer a
        # sensible default once per selected device.
        if not self._scanning and abs(self.step_spin.value() - 800.0) < 1e-6:
            self.step_spin.setValue(
                round(self._sample_rate * 0.8 / 1e3, 1)
            )
        self._update_estimate()

    def set_device_enabled(self, enabled: bool) -> None:
        self.start_btn.setEnabled(bool(enabled))
        if not enabled:
            self.status.setText("Нет устройства: добавьте Pluto или симулятор.")

    def set_can_compare(self, available: bool) -> None:
        self.compare_btn.setEnabled(bool(available) and not self._scanning)

    def begin_scan(self, total: int, start_hz: float, end_hz: float) -> None:
        self._scanning = True
        self._paused = False
        self._scan_started = time.monotonic()
        self._rows = 0
        self.table.setRowCount(0)
        self.start_btn.setText("Остановить")
        self.start_btn.setEnabled(True)
        self.pause_btn.setText("Пауза")
        self.pause_btn.setEnabled(True)
        self.export_btn.setEnabled(False)
        for widget in (
            self.start_spin, self.end_spin, self.step_spin,
            self.preset_btn, self.compare_btn,
        ):
            widget.setEnabled(False)
        self.progress.setRange(0, max(1, int(total)))
        self.progress.setValue(0)
        self.step_label.setText(f"0 / {total}")
        self.graph.configure(start_hz, end_hz)
        self.status.setStyleSheet("color:#22d3ee; font-size:11px;")
        self.status.setText(
            f"Сканирую {format_freq(start_hz)} – {format_freq(end_hz)}, "
            f"{total} шагов…"
        )

    def update_progress(self, index: int, total: int, center_hz: float) -> None:
        self.progress.setRange(0, max(1, int(total)))
        self.progress.setValue(int(index))
        percent = 100.0 * index / max(1, total)
        elapsed = time.monotonic() - self._scan_started
        eta = ""
        if index > 0:
            remaining = elapsed / index * max(0, total - index)
            eta = f" · осталось ~{self._duration(remaining)}"
        self.step_label.setText(
            f"{index} / {total} · {percent:.1f}%{eta}"
        )
        self.status.setText(
            f"Сканирую: {format_freq(center_hz)} "
            f"({percent:.1f}%){eta}"
        )

    def update_step(self, record: dict) -> None:
        if not isinstance(record, dict):
            return
        self.graph.add_step(record)
        status = str(record.get("status", "ok"))
        if status != "ok":
            self._append_status_row(record, status)
            return
        peaks = record.get("peaks") or []
        center = float(record.get("center_hz", 0.0))
        for peak in peaks:
            self._append_peak(peak, center)
        self.export_btn.setEnabled(self.table.rowCount() > 0)
        if peaks and self.status.styleSheet().find("#22d3ee") < 0:
            self.status.setStyleSheet("color:#22d3ee; font-size:11px;")

    def finish_scan(self, result: dict, *, stopped: bool = False) -> None:
        self._scanning = False
        self._paused = False
        path = str(result.get("path", ""))
        self._last_bundle = path or None
        planned = int(result.get("planned_total", 0))
        completed = int(result.get("steps_completed", 0))
        total = planned or int(result.get("steps_total", self.progress.maximum()))
        self.progress.setRange(0, max(1, total))
        self.progress.setValue(completed)
        self.start_btn.setText("Старт сканирования")
        self.start_btn.setEnabled(True)
        self.pause_btn.setText("Пауза")
        self.pause_btn.setEnabled(False)
        self.export_btn.setEnabled(self.table.rowCount() > 0)
        for widget in (
            self.start_spin, self.end_spin, self.step_spin,
            self.preset_btn,
        ):
            widget.setEnabled(True)
        self.compare_btn.setEnabled(bool(path))
        self.graph.mark_finished(path)
        duration = self._duration(float(result.get("duration_s", 0.0)))
        head = "Скан остановлен" if stopped else "Скан завершён"
        extra = ""
        if result.get("new_contacts") is not None:
            extra = f" · новых контактов: {result['new_contacts']}"
        elif result.get("compare_skipped"):
            extra = " · сравнение пропущено (фон с другого устройства)"
        missed = int(result.get("steps_missed", 0))
        miss_text = f" · пропущено шагов: {missed}" if missed else ""
        self.status.setStyleSheet("color:#4ade80; font-size:11px;")
        self.status.setText(
            f"{head}: шагов {completed}, "
            f"пиков {result.get('peak_count', 0)}, {duration}"
            f"{miss_text}{extra}. Файл: {path}"
        )
        self.step_label.setText(f"{completed} / {total}")

    def show_compare(self, report: dict, path: str) -> None:
        counts = report.get("counts", {})
        summary = str(report.get("summary_ru", "Сравнение готово."))
        new_contacts = report.get("new_contacts") or []
        if new_contacts:
            examples = ", ".join(
                format_freq(float(item["freq_hz"]))
                for item in new_contacts[:5]
            )
            summary += f" Новые: {examples}."
        self.status.setStyleSheet(
            "color:#f87171; font-size:11px;"
            if counts.get("new")
            else "color:#4ade80; font-size:11px;"
        )
        self.status.setText(f"{summary} Отчёт: {path}")
        background_path = (report.get("background") or {}).get("path")
        if background_path:
            try:
                self.graph.set_background(load_bundle(background_path))
            except Exception:
                pass
        self.compare_btn.setEnabled(bool(self._last_bundle))

    def fail(self, message: str) -> None:
        self._scanning = False
        self._paused = False
        self.start_btn.setText("Старт сканирования")
        self.start_btn.setEnabled(True)
        self.pause_btn.setText("Пауза")
        self.pause_btn.setEnabled(False)
        self.export_btn.setEnabled(self.table.rowCount() > 0)
        for widget in (
            self.start_spin, self.end_spin, self.step_spin,
            self.preset_btn,
        ):
            widget.setEnabled(True)
        self.compare_btn.setEnabled(bool(self._last_bundle))
        self.status.setStyleSheet("color:#f87171; font-size:11px;")
        self.status.setText(message)
        self.graph.mark_finished(None)

    def set_paused(self, paused: bool) -> None:
        self._paused = bool(paused)
        self.pause_btn.setText("Продолжить" if paused else "Пауза")
        if paused:
            self.status.setStyleSheet("color:#facc15; font-size:11px;")
            self.status.setText("Пауза. Нажмите «Продолжить».")
        elif self._scanning:
            self.status.setStyleSheet("color:#22d3ee; font-size:11px;")
            self.status.setText("Сканирование продолжается…")

    def export_csv(self, path: str | Path) -> int:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8-sig", newline="") as fh:
            writer = csv.writer(fh, delimiter=";")
            writer.writerow([
                "freq_hz", "level_db", "snr_db", "type", "bw_hz", "step"
            ])
            for row in range(self.table.rowCount()):
                values = []
                for column in range(6):
                    item = self.table.item(row, column)
                    values.append(item.text() if item else "")
                writer.writerow(values)
        return self.table.rowCount()

    # ----------------------------------------------------------------- private
    def _toggle_pause(self) -> None:
        if not self._scanning:
            return
        if self._paused:
            self.resume_requested.emit()
        else:
            self.pause_requested.emit()

    def _toggle(self) -> None:
        if self._scanning:
            self.stop_requested.emit()
        else:
            self.start_requested.emit()

    def _full_range(self) -> None:
        self.start_spin.setValue(PLUTO_MIN_FREQ / 1e6)
        self.end_spin.setValue(PLUTO_MAX_FREQ / 1e6)

    def _update_estimate(self) -> None:
        start, end, step = self.values()
        if step <= 0 or end <= start:
            self.estimate.setText("Проверьте диапазон и шаг.")
            return
        total = max(
            1,
            int(math.ceil(
                max(0.0, (end - start) - self._sample_rate) / step
            )) + 1,
        )
        # Real hardware needs roughly 0.2-0.3 s per step (two frames plus
        # retune).  A rough estimate is enough for the operator.
        seconds = total * 0.25
        warn = ""
        if step > self._sample_rate * 0.95:
            warn = "  ⚠ шаг больше полосы захвата — возможны пропуски."
        self.estimate.setText(
            f"{total} шагов · оценка {self._duration(seconds)}"
            f" · шаг {step / 1e3:.1f} кГц, полоса {self._sample_rate / 1e6:.3f} МГц"
            f"{warn}"
        )

    @staticmethod
    def _duration(seconds: float) -> str:
        seconds = max(0.0, float(seconds))
        if seconds < 60:
            return f"{seconds:.0f} с"
        minutes = int(seconds // 60)
        if minutes < 60:
            return f"{minutes} мин {int(seconds % 60):02d} с"
        return f"{minutes // 60} ч {minutes % 60:02d} мин"

    def _append_peak(self, peak: dict, center_hz: float) -> None:
        try:
            freq = float(peak["freq_hz"])
            level = float(peak["peak_db"])
        except (KeyError, TypeError, ValueError):
            return
        row = self.table.rowCount()
        if row >= 5000:
            self.table.removeRow(0)
            row -= 1
        self.table.insertRow(row)
        values = [
            format_freq(freq),
            f"{level:.1f}",
            f"{float(peak.get('snr_db', 0.0)):.1f}",
            str(peak.get("type_ru", peak.get("type", "—"))),
            format_bw(float(peak.get("bw_hz", 0.0))),
            f"{center_hz / 1e6:.2f}",
        ]
        for column, text in enumerate(values):
            item = QTableWidgetItem(text)
            if column in (1, 2, 4, 5):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight
                    | Qt.AlignmentFlag.AlignVCenter
                )
            self.table.setItem(row, column, item)
        self._rows = self.table.rowCount()

    def _append_status_row(self, record: dict, status: str) -> None:
        row = self.table.rowCount()
        if row >= 5000:
            self.table.removeRow(0)
            row -= 1
        self.table.insertRow(row)
        item = QTableWidgetItem(
            f"{format_freq(float(record.get('center_hz', 0.0)))} — {status}"
        )
        self.table.setItem(row, 0, item)
        self.table.setSpan(row, 0, 1, 6)
        self._rows = self.table.rowCount()

    def _open_folder(self) -> None:
        folder = Path("scan_logs").resolve()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
