"""Drone-band monitor tab: band selection, live plot and event log."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QColor, QDesktopServices
from PySide6.QtWidgets import (
    QAbstractItemView,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
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
from ..drone.bands import DRONE_BANDS, MonitorChunk, chunks_for_bands
from ..drone.features import DroneObservation
from ..drone.tracker import DroneEvent
from .drone_graph import DroneGraph

_CLASS_COLORS = {
    "FHSS": "#f87171",
    "TELEMETRY": "#fb923c",
    "VIDEO_ANALOG": "#f472b6",
    "VIDEO_DIGITAL": "#e879f9",
    "WIFI": "#94a3b8",
    "NARROW": "#facc15",
    "UNKNOWN": "#64748b",
}

_CLASS_SHORT = {
    "FHSS": "FHSS / управл.",
    "TELEMETRY": "телеметрия",
    "VIDEO_ANALOG": "видео (аналог)",
    "VIDEO_DIGITAL": "видео (цифра)",
    "WIFI": "Wi-Fi",
    "NARROW": "узкий",
    "UNKNOWN": "неизвестно",
}


class DronePanel(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    event_activated = Signal(str)
    whitelist_requested = Signal()

    HEADERS = [
        "Время", "Полоса", "Класс", "Частота", "Ширина",
        "SNR", "Хиты", "Скваж.", "Увер.", "Устр.",
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._monitoring = False
        self._rows: dict[str, int] = {}
        self._events: dict[str, DroneEvent] = {}
        self._device_labels: dict[str, QLabel] = {}
        self._device_names: dict[str, str] = {}

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        title = QLabel("ДРОН-МОНИТОР")
        title.setStyleSheet(
            "color:#f472b6; font-size:15px; font-weight:600; padding:2px;"
        )
        root.addWidget(title)
        hint = QLabel(
            "Пассивный монитор эфира. Wi-Fi, Bluetooth и микроволновки "
            "могут давать похожие сигналы — смотрите класс и уверенность. "
            "Двойной клик по событию открывает карточку и экспорт."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(hint)

        bands_box = QGroupBox("Полосы")
        bgrid = QGridLayout(bands_box)
        bgrid.setHorizontalSpacing(8)
        bgrid.setVerticalSpacing(2)
        self.band_checks: dict[str, QCheckBox] = {}
        for index, band in enumerate(DRONE_BANDS):
            check = QCheckBox(band.name)
            check.setChecked(True)
            check.setToolTip(band.description)
            check.toggled.connect(self._update_estimate)
            self.band_checks[band.key] = check
            bgrid.addWidget(check, index // 3, index % 3)
        root.addWidget(bands_box)

        self.extended_check = QCheckBox(
            "Разрешить 5.8 ГГц (Pluto+ / расширенный диапазон)"
        )
        self.extended_check.setChecked(True)
        self.extended_check.setToolTip(
            "У stock ADALM-PLUTO паспортный диапазон 325 МГц – 3.8 ГГц. "
            "Pluto+ и модифицированные версии могут работать до 6 ГГц. "
            "Если 5.8 ГГц не поддерживается, снимите этот флажок."
        )
        root.addWidget(self.extended_check)

        params = QGroupBox("Параметры монитора")
        grid = QGridLayout(params)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        self.rate_combo = QComboBox()
        for rate in (10.24e6, 20.48e6, 30.72e6):
            self.rate_combo.addItem(f"{rate / 1e6:.2f} MS/s", rate)
        self.rate_combo.setCurrentIndex(1)

        self.dwell_spin = QDoubleSpinBox()
        self.dwell_spin.setRange(10.0, 200.0)
        self.dwell_spin.setDecimals(0)
        self.dwell_spin.setSuffix(" мс")
        self.dwell_spin.setValue(40.0)
        self.dwell_spin.setKeyboardTracking(False)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(3.0, 20.0)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setSuffix(" dB")
        self.threshold_spin.setValue(8.0)
        self.threshold_spin.setKeyboardTracking(False)

        self.use_all_check = QCheckBox("Использовать все устройства")
        self.use_all_check.setChecked(True)
        self.use_all_check.setToolTip(
            "Две Pluto+ делят куски диапазона между собой. "
            "Если выключено — работает только выбранное устройство."
        )

        self.alarm_hits_spin = QDoubleSpinBox()
        self.alarm_hits_spin.setRange(1, 10)
        self.alarm_hits_spin.setDecimals(0)
        self.alarm_hits_spin.setSuffix(" имп.")
        self.alarm_hits_spin.setValue(3)
        self.alarm_hits_spin.setToolTip(
            "Сколько раз событие должно подтвердиться, прежде чем давать "
            "тревогу. 1 — старый шумный режим, 3–5 — меньше ложных тревог."
        )

        self.alarm_conf_spin = QDoubleSpinBox()
        self.alarm_conf_spin.setRange(40.0, 99.0)
        self.alarm_conf_spin.setDecimals(0)
        self.alarm_conf_spin.setSuffix(" %")
        self.alarm_conf_spin.setValue(70.0)
        self.alarm_conf_spin.setToolTip(
            "Минимальная уверенность классификатора для тревоги."
        )

        self.high_usb_check = QCheckBox(
            "Разрешить 20.48/30.72 MS/s на двух USB (риск)"
        )
        self.high_usb_check.setChecked(True)
        self.high_usb_check.setToolTip(
            "Скорость не режется молча: по умолчанию выбранная полоса "
            "сохраняется. Для двух USB это риск перегрузки общей шины — "
            "одно устройство может отвалиться с Broken pipe. Снимите "
            "галочку для стабильных 10.24 MS/s или выберите 10.24 в списке."
        )

        grid.addWidget(QLabel("Полоса"), 0, 0)
        grid.addWidget(self.rate_combo, 0, 1)
        grid.addWidget(QLabel("Задержка"), 0, 2)
        grid.addWidget(self.dwell_spin, 0, 3)
        grid.addWidget(QLabel("Порог"), 1, 0)
        grid.addWidget(self.threshold_spin, 1, 1)
        grid.addWidget(self.use_all_check, 1, 2, 1, 2)
        grid.addWidget(self.high_usb_check, 2, 0, 1, 4)
        grid.addWidget(QLabel("Тревога после"), 3, 0)
        grid.addWidget(self.alarm_hits_spin, 3, 1)
        grid.addWidget(QLabel("Мин. увер."), 3, 2)
        grid.addWidget(self.alarm_conf_spin, 3, 3)

        self.record_iq_check = QCheckBox(
            "Писать IQ-фрагмент для событий"
        )
        self.record_iq_check.setChecked(True)
        self.record_iq_check.setToolTip(
            "Сохраняет один короткий IQ-блок вокруг события в папку clips/. "
            "Это доказательство для разбора и материал для будущей базы "
            "сигнатур. Отключайте, если экономите место."
        )
        grid.addWidget(self.record_iq_check, 4, 0, 1, 4)
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        root.addWidget(params)

        self.estimate = QLabel("")
        self.estimate.setWordWrap(True)
        self.estimate.setStyleSheet("color:#8fa6c0; font-size:10px;")
        root.addWidget(self.estimate)

        actions = QHBoxLayout()
        actions.setSpacing(6)
        self.start_btn = QPushButton("Старт мониторинга")
        self.start_btn.setMinimumHeight(30)
        self.start_btn.clicked.connect(self._toggle)
        self.folder_btn = QPushButton("Журнал")
        self.folder_btn.clicked.connect(self._open_folder)
        self.whitelist_btn = QPushButton("Белый список…")
        self.whitelist_btn.clicked.connect(self.whitelist_requested)
        actions.addWidget(self.start_btn, 1)
        actions.addWidget(self.folder_btn)
        actions.addWidget(self.whitelist_btn)
        root.addLayout(actions)

        self.alarm = QLabel("")
        self.alarm.setWordWrap(True)
        self.alarm.setVisible(False)
        self.alarm.setStyleSheet(
            "background:#7f1d1d; color:#fecaca; border:1px solid #ef4444; "
            "border-radius:5px; padding:7px; font-weight:600;"
        )
        root.addWidget(self.alarm)
        self._alarm_timer = QTimer(self)
        self._alarm_timer.setSingleShot(True)
        self._alarm_timer.timeout.connect(lambda: self.alarm.setVisible(False))

        self.device_box = QGroupBox("Устройства")
        self.device_layout = QVBoxLayout(self.device_box)
        self.device_layout.setSpacing(2)
        self.device_hint = QLabel("Устройства появятся после старта.")
        self.device_hint.setStyleSheet("color:#64748b; font-size:10px;")
        self.device_layout.addWidget(self.device_hint)
        root.addWidget(self.device_box)

        self.graph = DroneGraph()
        self.graph.setMinimumHeight(200)
        root.addWidget(self.graph, 3)

        self.table = QTableWidget(0, len(self.HEADERS))
        self.table.setHorizontalHeaderLabels(self.HEADERS)
        self.table.setMinimumHeight(150)
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
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate((50, 55, 0, 88, 52, 34, 38, 42, 36, 58)):
            if column != 2:
                self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 3)
        self.table.cellDoubleClicked.connect(self._on_cell_double_click)

        self.status = QLabel("Выберите полосы и нажмите «Старт мониторинга».")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color:#94a3b8; font-size:11px;")
        root.addWidget(self.status)

        for check in self.band_checks.values():
            check.toggled.connect(self._sync_extended)
        self.rate_combo.currentIndexChanged.connect(self._update_estimate)
        self.high_usb_check.toggled.connect(self._update_estimate)
        self._update_estimate()

    # ------------------------------------------------------------------ public
    def selected_band_keys(self) -> list[str]:
        return [
            key for key, check in self.band_checks.items()
            if check.isChecked()
        ]

    def sample_rate(self) -> float:
        return float(self.rate_combo.currentData())

    def dwell_ms(self) -> float:
        return float(self.dwell_spin.value())

    def threshold_db(self) -> float:
        return float(self.threshold_spin.value())

    def alarm_hits(self) -> int:
        return max(1, int(self.alarm_hits_spin.value()))

    def alarm_confidence(self) -> float:
        return max(0.0, min(1.0, float(self.alarm_conf_spin.value()) / 100.0))

    def is_confirmed(self, event: DroneEvent) -> bool:
        return (
            bool(event.drone_like)
            and event.count >= self.alarm_hits()
            and event.confidence >= self.alarm_confidence()
        )

    def use_all_devices(self) -> bool:
        return bool(self.use_all_check.isChecked())

    def allow_high_usb(self) -> bool:
        return bool(self.high_usb_check.isChecked())

    def record_iq(self) -> bool:
        return bool(self.record_iq_check.isChecked())

    def find_event(self, event_id: str) -> DroneEvent | None:
        return self._events.get(event_id)

    def refresh_events(self) -> None:
        for event in list(self._events.values()):
            self.add_event(event, False)

    def extended_allowed(self) -> bool:
        return bool(self.extended_check.isChecked())

    def set_devices(self, devices: list[tuple[str, str]]) -> None:
        while self.device_layout.count():
            item = self.device_layout.takeAt(0)
            widget = item.widget()
            if widget is not None:
                widget.deleteLater()
        self._device_labels.clear()
        self._device_names = dict(devices)
        if not devices:
            self.device_hint = QLabel("Нет устройств.")
            self.device_hint.setStyleSheet("color:#f87171; font-size:10px;")
            self.device_layout.addWidget(self.device_hint)
            return
        for device_id, name in devices:
            label = QLabel(f"{name}: ожидание")
            label.setStyleSheet("color:#8fa6c0; font-size:10px;")
            self.device_layout.addWidget(label)
            self._device_labels[device_id] = label

    def update_device_status(self, device_id: str, text: str) -> None:
        label = self._device_labels.get(device_id)
        if label is not None:
            name = self._device_names.get(device_id, device_id)
            label.setText(f"{name}: {text}")

    def begin_monitor(self, devices: list[tuple[str, str]],
                      band_count: int, chunks: int) -> None:
        self._monitoring = True
        self.start_btn.setText("Остановить")
        self.start_btn.setEnabled(True)
        self.table.setRowCount(0)
        self._rows.clear()
        self._events.clear()
        self.alarm.setVisible(False)
        self.set_devices(devices)
        for widget in (
            self.rate_combo, self.dwell_spin, self.threshold_spin,
            self.use_all_check, self.extended_check, self.high_usb_check,
            self.alarm_hits_spin, self.alarm_conf_spin,
            self.record_iq_check,
        ):
            widget.setEnabled(False)
        for check in self.band_checks.values():
            check.setEnabled(False)
        self.status.setStyleSheet("color:#22d3ee; font-size:11px;")
        self.status.setText(
            f"Мониторинг {band_count} полос · {chunks} кусков · "
            f"{len(devices)} устр. · {self.sample_rate() / 1e6:.2f} MS/s. "
            "Ждём первые кадры…"
        )
        self.graph.clear()

    def update_chunk(self, chunk: MonitorChunk) -> None:
        self.graph.configure_chunk(chunk)

    def update_observation(self, obs: DroneObservation) -> None:
        self.graph.add_observation(obs)

    def add_event(self, event: DroneEvent, is_new: bool) -> None:
        self._events[event.event_id] = event
        row = self._rows.get(event.event_id)
        if row is None:
            if self.table.rowCount() >= 500:
                self.table.removeRow(0)
                self._rows = {
                    key: value - 1 for key, value in self._rows.items()
                    if value > 0
                }
            row = self.table.rowCount()
            self.table.insertRow(row)
            self._rows[event.event_id] = row
            for column in range(len(self.HEADERS)):
                self.table.setItem(row, column, QTableWidgetItem(""))
        color = QColor(_CLASS_COLORS.get(event.class_key, "#d7e2f0"))
        if event.whitelisted:
            color = QColor("#64748b")
        elif self.is_confirmed(event):
            color = QColor("#f87171")
        elif event.drone_like:
            color = QColor("#fb923c")
        values = [
            time.strftime("%H:%M:%S", time.localtime(event.last_seen)),
            event.band_name,
            _CLASS_SHORT.get(event.class_key, event.class_ru),
            format_freq(event.freq_hz),
            format_bw(event.bw_hz),
            f"{event.max_snr_db:.1f}",
            str(event.count),
            f"{event.max_duty * 100:.0f}%",
            f"{event.confidence * 100:.0f}%",
            ", ".join(
                self._device_names.get(device_id, device_id)
                .replace("Симулятор", "SIM")
                for device_id in event.device_ids
            ),
        ]
        for column, text in enumerate(values):
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, column, item)
            item.setText(text)
            item.setData(Qt.ItemDataRole.UserRole, event.event_id)
            item.setForeground(color)
            tips = []
            if event.whitelisted:
                tips.append(
                    f"В белом списке: {event.whitelist_name or 'да'}"
                )
            if event.ml:
                tips.append(
                    "ML: "
                    f"{event.ml.get('label', '?')} "
                    f"{float(event.ml.get('confidence', 0.0)) * 100:.0f}%"
                )
            if tips:
                item.setToolTip("\n".join(tips))
            if column in (5, 6, 7, 8):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
        if is_new:
            self.table.scrollToBottom()
        if event.drone_like and is_new:
            self.show_alarm(event)

    def show_alarm(self, event: DroneEvent) -> None:
        self.alarm.setText(
            "⚠ ВОЗМОЖНЫЙ ДРОНОВЫЙ ЛИНК: "
            f"{event.band_name} · {event.class_ru} · "
            f"{format_freq(event.freq_hz)} · SNR {event.max_snr_db:.1f} дБ · "
            f"подтверждено {event.count}× · увер. {event.confidence * 100:.0f}%"
        )
        self.alarm.setVisible(True)
        self._alarm_timer.start(10000)

    def update_status(self, text: str) -> None:
        self.status.setStyleSheet("color:#22d3ee; font-size:11px;")
        self.status.setText(text)

    def finish_monitor(self, summary: dict, path: str) -> None:
        self._monitoring = False
        self.alarm.setVisible(False)
        self._end_monitor_ui()
        total = int(summary.get("events_total", 0))
        active = int(summary.get("events_active", 0))
        alarms = int(summary.get(
            "alarms", summary.get("events_drone_like", 0)
        ))
        clips = int(summary.get("iq_clips", 0))
        failure = summary.get("failure")
        self.status.setStyleSheet(
            "color:#f87171; font-size:11px;"
            if failure else "color:#4ade80; font-size:11px;"
        )
        suffix = f" · журнал: {path}" if path else ""
        if failure:
            self.status.setText(f"Мониторинг остановлен: {failure}{suffix}")
        else:
            self.status.setText(
                f"Мониторинг завершён: событий {total}, активных {active}, "
                f"подтверждённых тревог {alarms}, IQ-фрагментов {clips}"
                f"{suffix}"
            )
        self.graph.mark_finished(path or None)

    def fail(self, message: str) -> None:
        self._monitoring = False
        self.alarm.setVisible(False)
        self._end_monitor_ui()
        self.status.setStyleSheet("color:#f87171; font-size:11px;")
        self.status.setText(message)
        self.graph.mark_finished(None)

    # ----------------------------------------------------------------- private
    def _on_cell_double_click(self, row: int, column: int) -> None:
        item = self.table.item(row, 0)
        if item is None:
            return
        event_id = item.data(Qt.ItemDataRole.UserRole)
        if event_id:
            self.event_activated.emit(str(event_id))

    def _end_monitor_ui(self) -> None:
        self.start_btn.setText("Старт мониторинга")
        self.start_btn.setEnabled(True)
        for widget in (
            self.rate_combo, self.dwell_spin, self.threshold_spin,
            self.use_all_check, self.extended_check, self.high_usb_check,
            self.alarm_hits_spin, self.alarm_conf_spin,
            self.record_iq_check,
        ):
            widget.setEnabled(True)
        for check in self.band_checks.values():
            check.setEnabled(True)
        self._sync_extended()
        self._update_estimate()

    def _toggle(self) -> None:
        if self._monitoring:
            self.stop_requested.emit()
        else:
            self.start_requested.emit()

    def _sync_extended(self) -> None:
        check = self.band_checks.get("5.8")
        if check is not None:
            check.setEnabled(
                self.extended_check.isChecked() or self._monitoring is False
            )
            if not self.extended_check.isChecked():
                check.setChecked(False)
        self._update_estimate()

    def _update_estimate(self) -> None:
        if self._monitoring:
            return
        keys = self.selected_band_keys()
        if not keys:
            self.estimate.setText("Выберите хотя бы одну полосу.")
            return
        bands = [band for band in DRONE_BANDS if band.key in keys]
        rate = self.sample_rate()
        total_width = sum(band.width_hz for band in bands)
        usable = rate * 0.8
        exact_chunks = len(chunks_for_bands(bands, rate))
        dwell = self.dwell_ms() / 1000.0
        pass_s = exact_chunks * max(0.02, dwell)
        risk = ""
        if self.high_usb_check.isChecked() and rate > 10.24e6:
            risk = ("  ⚠ на двух USB высокая полоса может перегрузить шину; "
                    "для стабильности 10.24 MS/s или Ethernet")
        self.estimate.setText(
            f"полос: {len(bands)} · ~{total_width / 1e6:.0f} МГц · "
            f"{exact_chunks} кусков · проход ~{pass_s:.1f} с · "
            f"полоса захвата {usable / 1e6:.1f} МГц{risk}"
        )

    def _open_folder(self) -> None:
        folder = Path("drone_logs").resolve()
        folder.mkdir(parents=True, exist_ok=True)
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))
