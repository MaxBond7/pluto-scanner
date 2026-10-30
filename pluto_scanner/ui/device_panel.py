"""Device list and add/remove controls."""
from __future__ import annotations

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QColor
from PySide6.QtWidgets import (
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListWidget,
    QListWidgetItem,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from ..config import format_freq
from ..model import DeviceConfig

_STATUS_RU = {
    "idle": "ожидание",
    "starting": "запуск",
    "running": "работает",
    "error": "ошибка",
    "stopped": "остановлен",
}
_STATUS_COLOR = {
    "idle": "#94a3b8",
    "starting": "#facc15",
    "running": "#4ade80",
    "error": "#f87171",
    "stopped": "#64748b",
}


class DevicePanel(QGroupBox):
    add_simulator = Signal()
    add_pluto = Signal(str)
    remove_device = Signal(str)
    device_selected = Signal(str)
    scan_pluto = Signal()

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("Устройства", parent)
        self._configs: dict[str, DeviceConfig] = {}
        self._status: dict[str, str] = {}
        self._items: dict[str, QListWidgetItem] = {}
        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        self.list = QListWidget()
        self.list.setMinimumHeight(96)
        self.list.currentItemChanged.connect(self._on_current_changed)
        layout.addWidget(self.list)

        row = QHBoxLayout()
        self.add_sim_btn = QPushButton("+ Симулятор")
        self.remove_btn = QPushButton("Удалить")
        self.add_sim_btn.clicked.connect(lambda: self.add_simulator.emit())
        self.remove_btn.clicked.connect(self._remove_current)
        row.addWidget(self.add_sim_btn)
        row.addWidget(self.remove_btn)
        layout.addLayout(row)

        uri_row = QHBoxLayout()
        self.uri_edit = QLineEdit("ip:192.168.2.1")
        self.uri_edit.setPlaceholderText("URI: ip:... / usb:...")
        self.scan_btn = QPushButton("Найти")
        self.scan_btn.clicked.connect(lambda: self.scan_pluto.emit())
        self.add_pluto_btn = QPushButton("+ Pluto")
        self.add_pluto_btn.clicked.connect(
            lambda: self.add_pluto.emit(self.uri_edit.text().strip())
        )
        uri_row.addWidget(self.uri_edit, 1)
        uri_row.addWidget(self.scan_btn)
        uri_row.addWidget(self.add_pluto_btn)
        layout.addLayout(uri_row)

        hint = QLabel(
            "Плата по USB/сети. Для второго Pluto добавьте ещё один URI."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px;")
        layout.addWidget(hint)

    def add_device(self, config: DeviceConfig) -> None:
        self._configs[config.device_id] = config
        item = QListWidgetItem()
        item.setData(Qt.ItemDataRole.UserRole, config.device_id)
        self._items[config.device_id] = item
        self.list.addItem(item)
        self._refresh_item(config.device_id)
        if self.list.count() == 1:
            self.list.setCurrentItem(item)

    def remove_item(self, device_id: str) -> None:
        item = self._items.pop(device_id, None)
        self._configs.pop(device_id, None)
        self._status.pop(device_id, None)
        if item is not None:
            row = self.list.row(item)
            self.list.takeItem(row)

    def set_status(self, device_id: str, status: str) -> None:
        self._status[device_id] = status
        self._refresh_item(device_id)

    def _refresh_item(self, device_id: str) -> None:
        item = self._items.get(device_id)
        config = self._configs.get(device_id)
        if item is None or config is None:
            return
        status = self._status.get(device_id, "idle")
        item.setText(
            f"{config.name}\n{format_freq(config.center_freq)}   ·   "
            f"{_STATUS_RU.get(status, status)}"
        )
        color = _STATUS_COLOR.get(status, "#d7e2f0")
        item.setForeground(QColor(color))
        item.setToolTip(
            f"ID: {config.device_id}\nТип: {config.kind}\nURI: {config.uri or '—'}"
        )

    def _on_current_changed(self, current: QListWidgetItem | None,
                            previous: QListWidgetItem | None) -> None:
        if current is None:
            return
        device_id = current.data(Qt.ItemDataRole.UserRole)
        if device_id:
            self.device_selected.emit(str(device_id))

    def _remove_current(self) -> None:
        current = self.list.currentItem()
        if current is None:
            return
        device_id = current.data(Qt.ItemDataRole.UserRole)
        if device_id:
            self.remove_device.emit(str(device_id))

    def select_device(self, device_id: str) -> None:
        item = self._items.get(device_id)
        if item is None:
            return
        self.list.blockSignals(True)
        self.list.setCurrentItem(item)
        self.list.blockSignals(False)

    def current_device_id(self) -> str | None:
        item = self.list.currentItem()
        if item is None:
            return None
        value = item.data(Qt.ItemDataRole.UserRole)
        return str(value) if value else None

    def device_name(self, device_id: str) -> str:
        config = self._configs.get(device_id)
        return config.name if config else device_id

    def device_names(self) -> dict[str, str]:
        return {k: v.name for k, v in self._configs.items()}

    def devices(self) -> list[DeviceConfig]:
        return list(self._configs.values())
