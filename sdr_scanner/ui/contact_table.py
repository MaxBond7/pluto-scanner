# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
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
from .themes import set_style, tcol


_COLOR_CACHE: dict[str, QColor] = {}


def _qcolor(token: str) -> QColor:
    """Resolve a theme token to a QColor once, not once per table cell."""
    value = tcol(token)
    color = _COLOR_CACHE.get(value)
    if color is None:
        if len(_COLOR_CACHE) > 256:
            _COLOR_CACHE.clear()
        color = QColor(value)
        _COLOR_CACHE[value] = color
    return color


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
        self._row_ids: list[str] = []
        self._row_sig: list[tuple | None] = []
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(5)

        self.title = QLabel("КОНТАКТЫ  ·  0")
        set_style(self.title, "color:#67e8f9; font-size:15px; font-weight:600; padding:2px 2px 4px 2px;")
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
        set_style(self.detail, "color:#67e8f9; font-size:11px; padding:2px 2px 0 2px;")
        layout.addWidget(self.detail)
        self._update_buttons()

    def update_contacts(self, contacts: list[Contact],
                        device_names: dict[str, str]) -> None:
        ordered = sorted(
            contacts,
            key=lambda c: (c.known, -c.last_seen),
        )
        self._device_names = dict(device_names)
        ids = [c.contact_id for c in ordered]
        selected = self.selected_contact_id()
        self.table.blockSignals(True)
        try:
            # Rows are reused: rebuilding 9 items per contact every 400 ms
            # costs more than comparing the strings and touching only what
            # actually changed.
            if ids != self._row_ids:
                self.table.setRowCount(len(ordered))
                for row in range(len(ordered)):
                    for column in range(len(self.HEADERS)):
                        if self.table.item(row, column) is None:
                            self.table.setItem(row, column, QTableWidgetItem(""))
                self._row_ids = ids
                self._row_sig = [None] * len(ordered)
            self._contacts = ordered
            for row, contact in enumerate(ordered):
                self._fill_row(row, contact)
            self.title.setText(f"КОНТАКТЫ  ·  {len(ordered)}")
        finally:
            self.table.blockSignals(False)
        if selected:
            self.select_contact(selected)
        self._update_buttons()

    def _fill_row(self, row: int, contact: Contact) -> None:
        is_new = contact.is_new()
        if is_new:
            badge = "NEW"
        elif contact.known:
            badge = "KNOWN"
        else:
            badge = "●" if contact.active else "○"
        if is_new:
            badge_color = "#4ade80"
        elif contact.known:
            badge_color = "#94a3b8"
        elif contact.active:
            badge_color = "#f59e0b"
        else:
            badge_color = "#64748b"
        muted = not contact.active
        text_color = "#64748b" if muted else "#e2e8f0"
        type_color = "#94a3b8" if (muted or contact.known) else "#67e8f9"
        values = (
            badge,
            format_freq(contact.freq_hz),
            format_bw(contact.bw_hz),
            f"{contact.last_snr_db:.1f} dB",
            contact.type.ru,
            f"{contact.confidence * 100:.0f}%",
            self._device_names.get(contact.device_id, contact.device_id),
            str(contact.hits),
            time.strftime("%H:%M:%S", time.localtime(contact.last_seen)),
        )
        colors = (
            badge_color, text_color, text_color, text_color, type_color,
            text_color, text_color, text_color, text_color,
        )
        alt = ", ".join(
            f"{t.value} {p * 100:.0f}%" for t, p in contact.alternatives
        )
        tooltip = (
            f"ID: {contact.contact_id}\n"
            f"{format_freq(contact.freq_hz)}  {format_bw(contact.bw_hz)}\n"
            f"Тип: {contact.type.ru}  уверенность {contact.confidence * 100:.0f}%\n"
            f"Гипотезы: {alt}\n"
            f"SNR макс: {contact.max_snr_db:.1f} dB\n"
            f"Хитов: {contact.hits}  пропусков: {contact.misses}"
        )
        signature = (values, colors, tooltip)
        if row < len(self._row_sig):
            if self._row_sig[row] == signature:
                return
            self._row_sig[row] = signature
        for column, (text, token) in enumerate(zip(values, colors)):
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem("")
                self.table.setItem(row, column, item)
            if item.text() != text:
                item.setText(text)
            color = _qcolor(token)
            if item.foreground().color() != color:
                item.setForeground(color)
            if item.toolTip() != tooltip:
                item.setToolTip(tooltip)
            if column == 0:
                item.setData(Qt.ItemDataRole.UserRole, contact.contact_id)
            if column == 7:
                item.setTextAlignment(Qt.AlignmentFlag.AlignCenter)

    def set_device_names(self, names: dict[str, str]) -> None:
        self._device_names = dict(names)

    def refresh_theme(self) -> None:
        """Recolour every row after a theme switch.

        The per-row signature caches only the *tokens*, so without this the
        rows would keep the previous theme's colours until their text changed.
        """
        self._row_sig = [None] * len(self._row_sig)
        if self._contacts:
            self.update_contacts(self._contacts, self._device_names)

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
