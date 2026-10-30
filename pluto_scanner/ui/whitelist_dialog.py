"""Manage the drone-monitor white list."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QMessageBox,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import format_freq
from ..drone.whitelist import DroneWhitelist


class WhitelistDialog(QDialog):
    def __init__(self, whitelist: DroneWhitelist,
                 parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.whitelist = whitelist
        self.setWindowTitle("Белый список дрон-монитора")
        self.resize(820, 520)
        self.setMinimumSize(680, 420)
        self.setStyleSheet("QDialog { background:#0b1020; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(12, 10, 12, 10)
        root.setSpacing(8)

        title = QLabel("БЕЛЫЙ СПИСОК")
        title.setStyleSheet(
            "color:#4ade80; font-size:17px; font-weight:700;"
        )
        root.addWidget(title)
        hint = QLabel(
            "Сигналы из этого списка не поднимают тревогу, но остаются "
            "в таблице для наблюдения."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(hint)

        self.table = QTableWidget(0, 6)
        self.table.setHorizontalHeaderLabels(
            ["Название", "Полоса", "Класс", "Диапазон", "Хиты", "Источник"]
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
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(0, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((0, 72, 100, 210, 48, 70)):
            if column:
                self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 1)

        self.status = QLabel("")
        self.status.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(self.status)

        row = QHBoxLayout()
        self.delete_btn = QPushButton("Удалить выбранное")
        self.delete_btn.clicked.connect(self._delete)
        self.clear_btn = QPushButton("Очистить")
        self.clear_btn.clicked.connect(self._clear)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        row.addWidget(self.delete_btn)
        row.addWidget(self.clear_btn)
        row.addStretch(1)
        row.addWidget(close_btn)
        root.addLayout(row)

        self.refresh()

    def refresh(self) -> None:
        entries = self.whitelist.all()
        self.table.setRowCount(0)
        for entry in entries:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                entry.name,
                entry.band_key,
                entry.class_key,
                f"{format_freq(entry.freq_min_hz)} – "
                f"{format_freq(entry.freq_max_hz)}",
                str(entry.hits),
                entry.source,
            ]
            for column, value in enumerate(values):
                item = QTableWidgetItem(value)
                item.setData(Qt.ItemDataRole.UserRole, entry.id)
                self.table.setItem(row, column, item)
        self.status.setText(f"Записей: {len(entries)}")

    def _selected_id(self) -> str | None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            return None
        item = self.table.item(rows[0].row(), 0)
        return str(item.data(Qt.ItemDataRole.UserRole)) if item else None

    def _delete(self) -> None:
        entry_id = self._selected_id()
        if not entry_id:
            self.status.setText("Выберите запись.")
            return
        if self.whitelist.remove(entry_id):
            self.refresh()
            self.status.setText("Запись удалена.")

    def _clear(self) -> None:
        if not self.whitelist.all():
            return
        answer = QMessageBox.question(
            self,
            "Очистить белый список",
            "Удалить все записи? Сигналы снова начнут поднимать тревогу.",
        )
        if answer != QMessageBox.StandardButton.Yes:
            return
        self.whitelist.clear()
        self.refresh()
        self.status.setText("Белый список очищен.")
