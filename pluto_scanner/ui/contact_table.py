"""Contact list with stable IDs, NEW badges and known-contact actions."""
from __future__ import annotations

import time

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QAbstractItemView,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QVBoxLayout,
    QWidget,
)

from ..config import format_bw, format_freq
from ..model import Contact


class ContactTable(QWidget):
    contact_activated = Signal(str)
    mark_known = Signal(str)
    forget = Signal(str)

    HEADERS = ["", "Частота", "Полоса", "SNR", "Тип", "Увер.",
               "Устройство", "Хиты", "Время"]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._contacts: list[Contact] = []
        self._device_names: dict[str, str] = {}
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.title = QLabel("КОНТАКТЫ  ·  0")
        self.title.setStyleSheet(
            "color:#67e8f9; font-size:15px; font-weight:600; padding:2px 2px 4px 2px;"
        )
        layout.addWidget(self.title)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.verticalHeader().setVisible(False)
        self.table.setAlternatingRowColors(True)
        self.table.setShowGrid(False)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setSelectionMode(QAbstractItemView.SelectionMode.SingleSelection)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSortingEnabled(False)
        self.table.setWordWrap(False)
        header = self.table.horizontalHeader()
        header.setSectionResizeMode(QHeaderView.ResizeMode.ResizeToContents)
        header.setSectionResizeMode(1, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(6, QHeaderView.ResizeMode.Stretch)
        header.setSectionResizeMode(8, QHeaderView.ResizeMode.Fixed)
        self.table.setColumnWidth(0, 58)
        self.table.setColumnWidth(3, 62)
        self.table.setColumnWidth(5, 55)
        self.table.setColumnWidth(8, 64)
        self.table.cellDoubleClicked.connect(self._on_double_click)
        self.table.itemSelectionChanged.connect(self._update_buttons)
        layout.addWidget(self.table, 1)

        row = QHBoxLayout()
        row.setSpacing(5)
        self.tune_btn = QPushButton("Настроиться")
        self.known_btn = QPushButton("В фон")
        self.forget_btn = QPushButton("Забыть")
        self.tune_btn.clicked.connect(self._activate_selected)
        self.known_btn.clicked.connect(self._mark_selected)
        self.forget_btn.clicked.connect(self._forget_selected)
        row.addWidget(self.tune_btn)
        row.addWidget(self.known_btn)
        row.addWidget(self.forget_btn)
        row.addStretch(1)
        layout.addLayout(row)

        self.detail = QLabel("Топ-3: —")
        self.detail.setWordWrap(True)
        self.detail.setStyleSheet(
            "color:#67e8f9; font-size:11px; padding:2px 2px 0 2px;"
        )
        layout.addWidget(self.detail)
        self._update_buttons()

    def update_contacts(self, contacts: list[Contact],
                        device_names: dict[str, str]) -> None:
        self._contacts = sorted(
            contacts,
            key=lambda c: (c.known, -c.last_seen),
        )
        self._device_names = dict(device_names)
        selected = self.selected_contact_id()
        self.table.blockSignals(True)
        self.table.setRowCount(len(self._contacts))
        for row, c in enumerate(self._contacts):
            is_new = c.is_new()
            badge = "NEW" if is_new else ("KNOWN" if c.known else ("●" if c.active else "○"))
            badge_item = QTableWidgetItem(badge)
            badge_item.setData(Qt.ItemDataRole.UserRole, c.contact_id)
            if is_new:
                badge_item.setForeground(QColor("#4ade80"))
            elif c.known:
                badge_item.setForeground(QColor("#94a3b8"))
            elif c.active:
                badge_item.setForeground(QColor("#f59e0b"))
            else:
                badge_item.setForeground(QColor("#64748b"))

            freq_item = QTableWidgetItem(format_freq(c.freq_hz))
            freq_item.setForeground(QColor("#e2e8f0"))
            bw_item = QTableWidgetItem(format_bw(c.bw_hz))
            snr_item = QTableWidgetItem(f"{c.last_snr_db:.1f} dB")
            type_item = QTableWidgetItem(c.type.ru)
            type_item.setForeground(QColor("#67e8f9" if not c.known else "#94a3b8"))
            conf_item = QTableWidgetItem(f"{c.confidence * 100:.0f}%")
            dev_item = QTableWidgetItem(
                self._device_names.get(c.device_id, c.device_id)
            )
            hits_item = QTableWidgetItem(str(c.hits))
            hits_item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)
            last_item = QTableWidgetItem(
                time.strftime("%H:%M:%S", time.localtime(c.last_seen))
            )
            if not c.active:
                for item in (freq_item, bw_item, snr_item, type_item,
                             conf_item, dev_item, hits_item, last_item):
                    item.setForeground(QColor("#64748b"))

            alt = ", ".join(
                f"{t.value} {p * 100:.0f}%" for t, p in c.alternatives
            )
            tooltip = (
                f"ID: {c.contact_id}\n"
                f"{format_freq(c.freq_hz)}  {format_bw(c.bw_hz)}\n"
                f"Тип: {c.type.ru}  уверенность {c.confidence * 100:.0f}%\n"
                f"Гипотезы: {alt}\n"
                f"SNR макс: {c.max_snr_db:.1f} dB\n"
                f"Хитов: {c.hits}  пропусков: {c.misses}"
            )
            for col, item in enumerate((
                badge_item, freq_item, bw_item, snr_item, type_item,
                conf_item, dev_item, hits_item, last_item,
            )):
                item.setToolTip(tooltip)
                self.table.setItem(row, col, item)

        self.title.setText(f"КОНТАКТЫ  ·  {len(self._contacts)}")
        self.table.blockSignals(False)
        if selected:
            self.select_contact(selected)
        self._update_buttons()

    def set_device_names(self, names: dict[str, str]) -> None:
        self._device_names = dict(names)

    def selected_contact_id(self) -> str | None:
        row = self.table.currentRow()
        if row < 0:
            return None
        item = self.table.item(row, 0)
        return item.data(Qt.ItemDataRole.UserRole) if item else None

    def select_contact(self, contact_id: str) -> None:
        for row in range(self.table.rowCount()):
            item = self.table.item(row, 0)
            if item and item.data(Qt.ItemDataRole.UserRole) == contact_id:
                self.table.selectRow(row)
                return

    def _selected_contact(self) -> Contact | None:
        cid = self.selected_contact_id()
        for c in self._contacts:
            if c.contact_id == cid:
                return c
        return None

    def _on_double_click(self, row: int, column: int) -> None:
        item = self.table.item(row, 0)
        if item:
            self.contact_activated.emit(
                str(item.data(Qt.ItemDataRole.UserRole))
            )

    def _activate_selected(self) -> None:
        cid = self.selected_contact_id()
        if cid:
            self.contact_activated.emit(cid)

    def _mark_selected(self) -> None:
        cid = self.selected_contact_id()
        if cid:
            self.mark_known.emit(cid)

    def _forget_selected(self) -> None:
        cid = self.selected_contact_id()
        if cid:
            self.forget.emit(cid)

    def _update_buttons(self) -> None:
        c = self._selected_contact()
        has = c is not None
        self.tune_btn.setEnabled(has)
        self.known_btn.setEnabled(has and not c.known)
        self.forget_btn.setEnabled(has and c.known)
        visible = c
        prefix = "Топ-3:"
        if visible is None and self._contacts:
            visible = self._contacts[0]
            prefix = "Топ-3 (последний):"
        if visible is None:
            self.detail.setText("Топ-3: —")
            return
        alts = visible.alternatives or [(visible.type, visible.confidence)]
        text = "  ·  ".join(
            f"{label.ru} {prob * 100:.0f}%" for label, prob in alts[:3]
        )
        self.detail.setText(f"{prefix} {text}")
        self.detail.setToolTip(text)
