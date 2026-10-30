"""Read-only view of the local known-signal signature library."""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (
    QAbstractItemView,
    QFileDialog,
    QHBoxLayout,
    QHeaderView,
    QLabel,
    QLineEdit,
    QPushButton,
    QTableWidget,
    QTableWidgetItem,
    QTextBrowser,
    QVBoxLayout,
    QWidget,
)

from ..config import format_bw, format_freq
from ..signatures import SignatureStore, SignalSignature


class SignaturePanel(QWidget):
    def __init__(self, store: SignatureStore, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.store = store
        self._items: list[SignalSignature] = []

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        title = QLabel("БИБЛИОТЕКА СИГНАТУР")
        title.setStyleSheet(
            "color:#a78bfa; font-size:15px; font-weight:600; padding:2px;"
        )
        root.addWidget(title)
        hint = QLabel(
            "Справочник типовых сигналов и открытых источников. "
            "Совпадение — гипотеза, а не подтверждение модели."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(hint)

        row = QHBoxLayout()
        row.setSpacing(6)
        self.search_edit = QLineEdit()
        self.search_edit.setPlaceholderText(
            "Поиск: Wi-Fi, Bluetooth, LoRa, 2.4, видео…"
        )
        self.search_edit.textChanged.connect(self.refresh)
        self.count_label = QLabel("")
        self.count_label.setStyleSheet("color:#8fa6c0; font-size:10px;")
        row.addWidget(self.search_edit, 1)
        row.addWidget(self.count_label)
        root.addLayout(row)

        self.table = QTableWidget(0, 5)
        self.table.setHorizontalHeaderLabels(
            ["Название", "Категория", "Диапазон", "Ширина", "Модуляция"]
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
        for column, width in enumerate((0, 82, 130, 62, 130)):
            if column != 0:
                self.table.setColumnWidth(column, width)
        self.table.itemSelectionChanged.connect(self._show_selected)
        root.addWidget(self.table, 3)

        self.details = QTextBrowser()
        self.details.setOpenExternalLinks(True)
        self.details.setStyleSheet(
            "QTextBrowser { background:#0d1426; border:1px solid #22304a;"
            " border-radius:6px; padding:6px; font-size:11px; }"
        )
        root.addWidget(self.details, 2)

        buttons = QHBoxLayout()
        buttons.setSpacing(6)
        self.import_btn = QPushButton("Импорт JSON/CSV…")
        self.import_btn.clicked.connect(self._import)
        self.export_btn = QPushButton("Экспорт…")
        self.export_btn.clicked.connect(self._export)
        self.refresh_btn = QPushButton("Обновить")
        self.refresh_btn.clicked.connect(lambda: self.refresh(self.search_edit.text()))
        buttons.addWidget(self.import_btn)
        buttons.addWidget(self.export_btn)
        buttons.addStretch(1)
        buttons.addWidget(self.refresh_btn)
        root.addLayout(buttons)

        self.status = QLabel(f"База хранится в {store.path}")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(self.status)

        self.refresh()

    # ------------------------------------------------------------------ public
    def refresh(self, query: str | None = None) -> None:
        self._items = self.store.search(query or "")
        self.table.setRowCount(0)
        for item in self._items:
            row = self.table.rowCount()
            self.table.insertRow(row)
            values = [
                item.name,
                item.category,
                f"{format_freq(item.start_hz)} – {format_freq(item.end_hz)}",
                format_bw(item.bw_hz) if item.bw_hz else "—",
                item.modulation or "—",
            ]
            for column, text in enumerate(values):
                cell = QTableWidgetItem(text)
                cell.setData(Qt.ItemDataRole.UserRole, item.id)
                self.table.setItem(row, column, cell)
        self.count_label.setText(f"записей: {len(self._items)}")
        if self._items:
            self.table.selectRow(0)

    # ----------------------------------------------------------------- private
    def _show_selected(self) -> None:
        rows = self.table.selectionModel().selectedRows()
        if not rows:
            self.details.setHtml("Выберите сигнал в таблице.")
            return
        item = self.table.item(rows[0].row(), 0)
        if item is None:
            return
        signature = self.store.get(str(item.data(Qt.ItemDataRole.UserRole)))
        if signature is None:
            return
        refs = "<br>".join(
            f'<a href="{ref}">{ref}</a>' if ref.startswith("http") else ref
            for ref in signature.references
        ) or "—"
        self.details.setHtml(
            f"<h3 style='color:#67e8f9; margin:0 0 6px 0'>{signature.name}</h3>"
            f"<p style='color:#d7e2f0'>{signature.notes or '—'}</p>"
            f"<p><b>Категория:</b> {signature.category} · "
            f"<b>Источник:</b> {signature.source_class} · "
            f"<b>Hop:</b> {signature.hop}</p>"
            f"<p><b>Диапазон:</b> {format_freq(signature.start_hz)} – "
            f"{format_freq(signature.end_hz)}<br>"
            f"<b>Ширина:</b> {format_bw(signature.bw_hz) if signature.bw_hz else '—'}<br>"
            f"<b>Модуляция:</b> {signature.modulation or '—'}<br>"
            f"<b>Скважность:</b> {signature.duty * 100:.0f}% · "
            f"<b>Импульс:</b> {signature.burst_ms:.1f} мс</p>"
            f"<p><b>Ссылки:</b><br>{refs}</p>"
            f"<p style='color:#64748b'><b>Лицензия:</b> "
            f"{signature.license or '—'}</p>"
        )

    def _import(self) -> None:
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Импорт библиотеки сигнатур",
            str(Path.cwd()),
            "Сигнатуры (*.json *.csv);;JSON (*.json);;CSV (*.csv)",
        )
        if not filename:
            return
        try:
            count = self.store.import_file(filename)
        except Exception as exc:
            self.status.setStyleSheet("color:#f87171; font-size:10px;")
            self.status.setText(f"Ошибка импорта: {exc}")
            return
        self.refresh(self.search_edit.text())
        self.status.setStyleSheet("color:#4ade80; font-size:10px;")
        self.status.setText(f"Импортировано записей: {count}")

    def _export(self) -> None:
        filename, _ = QFileDialog.getSaveFileName(
            self,
            "Экспорт библиотеки сигнатур",
            str(Path.cwd() / "signatures.json"),
            "JSON (*.json);;CSV (*.csv)",
        )
        if not filename:
            return
        try:
            path = self.store.export_file(filename)
        except Exception as exc:
            self.status.setStyleSheet("color:#f87171; font-size:10px;")
            self.status.setText(f"Ошибка экспорта: {exc}")
            return
        self.status.setStyleSheet("color:#4ade80; font-size:10px;")
        self.status.setText(f"Экспортировано: {path}")
