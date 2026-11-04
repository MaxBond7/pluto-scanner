# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
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
from ..drone.background import BACKGROUND_MARK
from ..drone.tracker import DroneEvent
from .drone_graph import DroneGraph
from .themes import set_style, tcol

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


def _binary_short(event: DroneEvent) -> str:
    """Short text for the binary model column."""
    data = event.binary or {}
    if not data:
        text = "—"
    elif str(data.get("verdict") or "") == "unknown":
        text = "н/д"
    else:
        text = f"{float(data.get('score') or 0.0) * 100:.0f}%"
        if event.wideband:
            text += " Wi-Fi?"
    if event.background >= BACKGROUND_MARK:
        return "фон" if text in ("—", "н/д") else f"{text} · фон"
    return text


class DronePanel(QWidget):
    start_requested = Signal()
    stop_requested = Signal()
    event_activated = Signal(str)
    whitelist_requested = Signal()
    background_requested = Signal()
    background_stop_requested = Signal()

    HEADERS = [
        "Время", "Полоса", "Класс", "Частота", "Ширина",
        "SNR", "Хиты", "Скваж.", "Увер.", "Дрон", "Устр.",
    ]

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self._monitoring = False
        self._rows: dict[str, int] = {}
        self._events: dict[str, DroneEvent] = {}
        self._device_labels: dict[str, QLabel] = {}
        self._device_names: dict[str, str] = {}
        self._background_running = False

        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        title = QLabel("ДРОН-МОНИТОР")
        set_style(title, "color:#f472b6; font-size:15px; font-weight:600; padding:2px;")
        root.addWidget(title)
        hint = QLabel(
            "Пассивный монитор эфира. Wi-Fi, Bluetooth и микроволновки "
            "могут давать похожие сигналы — смотрите класс и уверенность. "
            "Двойной клик по событию открывает карточку и экспорт."
        )
        hint.setWordWrap(True)
        set_style(hint, "color:#8fa6c0; font-size:10px;")
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
        # The monitor lives in its own window, so the controls sit in one row
        # instead of a long column.
        self.controls = QHBoxLayout()
        self.controls.setSpacing(8)
        left_col = QVBoxLayout()
        left_col.setSpacing(4)
        left_col.addWidget(bands_box)

        self.extended_check = QCheckBox(
            "Разрешить 5.8 ГГц (Pluto+ / расширенный диапазон)"
        )
        self.extended_check.setChecked(True)
        self.extended_check.setToolTip(
            "У stock ADALM-PLUTO паспортный диапазон 325 МГц – 3.8 ГГц. "
            "Pluto+ и модифицированные версии могут работать до 6 ГГц. "
            "Если 5.8 ГГц не поддерживается, снимите этот флажок."
        )
        left_col.addWidget(self.extended_check)

        self.controls.addLayout(left_col, 2)

        params = QGroupBox("Параметры монитора")
        grid = QGridLayout(params)
        grid.setHorizontalSpacing(8)
        grid.setVerticalSpacing(5)

        self.rate_combo = QComboBox()
        for rate in (4.096e6, 6.144e6, 10.24e6, 20.48e6, 30.72e6):
            self.rate_combo.addItem(f"{rate / 1e6:.2f} MS/s", rate)
        # 4.096-6.144 MS/s is what a Pluto over USB 2.0 sustains without
        # dropping samples; the higher rates are kept for Ethernet/network
        # radios and are flagged below.
        index = self.rate_combo.findData(6.144e6)
        self.rate_combo.setCurrentIndex(index if index >= 0 else 0)
        self.rate_combo.setToolTip(
            "Полоса мониторинга. Pluto по USB 2.0 честно держит 4.096–6.144 MS/s; "
            "выше начинаются потери отсчётов, и время в записи рвётся."
        )
        self.rate_combo.currentIndexChanged.connect(self._update_rate_warning)

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

        self.background_check = QCheckBox("Не тревожить фоновые сигналы")
        self.background_check.setChecked(True)
        self.background_check.setToolTip(
            "Сигналы, которые были в эфире всё время обучения фона "
            "(роутер, точка доступа, помеха), остаются в таблице с "
            "пометкой «фон», но тревогу не поднимают. Новая активность "
            "тревожит как обычно."
        )
        grid.addWidget(self.background_check, 5, 0, 1, 4)

        bg_row = QHBoxLayout()
        bg_row.setSpacing(6)
        self.background_btn = QPushButton("Записать фон")
        self.background_btn.setToolTip(
            "Отдельный сеанс записи: монитор слушает выбранные полосы, "
            "но не ищет дронов, а запоминает постоянные сигналы. "
            "Потом они помечаются как «фон»."
        )
        self.background_btn.clicked.connect(self._toggle_background)
        bg_row.addWidget(self.background_btn)
        self.background_seconds_spin = QDoubleSpinBox()
        self.background_seconds_spin.setRange(20.0, 600.0)
        self.background_seconds_spin.setDecimals(0)
        self.background_seconds_spin.setSuffix(" с")
        self.background_seconds_spin.setValue(60.0)
        bg_row.addWidget(self.background_seconds_spin)
        self.background_status = QLabel("Фон: не записан")
        self.background_status.setWordWrap(True)
        set_style(self.background_status, "color:#64748b; font-size:10px;")
        bg_row.addStretch(1)
        grid.addLayout(bg_row, 6, 0, 1, 4)
        grid.addWidget(self.background_status, 7, 0, 1, 4)

        self.rate_warning = QLabel("")
        self.rate_warning.setWordWrap(True)
        set_style(self.rate_warning, "color:#facc15; font-size:10px;")
        self.rate_warning.setVisible(False)
        grid.addWidget(self.rate_warning, 8, 0, 1, 4)
        self._update_rate_warning()
        grid.setColumnStretch(1, 1)
        grid.setColumnStretch(3, 1)
        self.controls.addWidget(params, 3)

        side = QVBoxLayout()
        side.setSpacing(4)
        self.estimate = QLabel("")
        self.estimate.setWordWrap(True)
        set_style(self.estimate, "color:#8fa6c0; font-size:10px;")
        side.addWidget(self.estimate)

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
        side.addLayout(actions)

        self.alarm = QLabel("")
        self.alarm.setWordWrap(True)
        self.alarm.setVisible(False)
        set_style(
            self.alarm,
            "background:$danger_bg; color:$danger_fg; "
            "border:1px solid $danger_fg; "
            "border-radius:5px; padding:7px; font-weight:600;",
        )
        root.addWidget(self.alarm)
        self._alarm_timer = QTimer(self)
        self._alarm_timer.setSingleShot(True)
        self._alarm_timer.timeout.connect(lambda: self.alarm.setVisible(False))

        self.device_box = QGroupBox("Устройства")
        self.device_layout = QVBoxLayout(self.device_box)
        self.device_layout.setSpacing(2)
        self.device_hint = QLabel("Устройства появятся после старта.")
        set_style(self.device_hint, "color:#64748b; font-size:10px;")
        self.device_layout.addWidget(self.device_hint)
        side.addWidget(self.device_box)

        self.controls.addLayout(side, 2)
        root.addLayout(self.controls)

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
        set_style(self.table, "QTableWidget { font-size: 10px; }")
        header = self.table.horizontalHeader()
        header.setMinimumSectionSize(40)
        header.setSectionResizeMode(QHeaderView.ResizeMode.Interactive)
        header.setSectionResizeMode(2, QHeaderView.ResizeMode.Stretch)
        for column, width in enumerate(
            (50, 55, 0, 88, 52, 34, 38, 42, 36, 72, 58)
        ):
            if column != 2:
                self.table.setColumnWidth(column, width)
        root.addWidget(self.table, 3)
        self.table.cellDoubleClicked.connect(self._on_cell_double_click)

        self.status = QLabel("Выберите полосы и нажмите «Старт мониторинга».")
        self.status.setWordWrap(True)
        set_style(self.status, "color:#94a3b8; font-size:11px;")
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

    def _update_rate_warning(self, *_args) -> None:
        rate = self.sample_rate()
        if rate > 6.2e6:
            text = (
                "USB 2.0: выше ~6 МГц отсчёты теряются и время в записи "
                "рвётся. Для честного мониторинга выберите 4.096–6.144 MS/s "
                "(или подключите Pluto по сети)."
            )
        else:
            text = ""
        if text != self.rate_warning.text():
            self.rate_warning.setText(text)
        self.rate_warning.setVisible(bool(text))

    def dwell_ms(self) -> float:
        return float(self.dwell_spin.value())

    def threshold_db(self) -> float:
        return float(self.threshold_spin.value())

    def alarm_hits(self) -> int:
        return max(1, int(self.alarm_hits_spin.value()))

    def alarm_confidence(self) -> float:
        return max(0.0, min(1.0, float(self.alarm_conf_spin.value()) / 100.0))

    def background_seconds(self) -> float:
        return float(self.background_seconds_spin.value())

    def _toggle_background(self) -> None:
        if self._background_running:
            self.background_stop_requested.emit()
        else:
            self.background_requested.emit()

    def begin_background(self) -> None:
        self._background_running = True
        self.background_btn.setText("Остановить запись")
        self.background_btn.setEnabled(True)
        self.background_seconds_spin.setEnabled(False)
        for widget in (
            self.rate_combo, self.dwell_spin, self.threshold_spin,
            self.use_all_check, self.extended_check, self.high_usb_check,
            self.alarm_hits_spin, self.alarm_conf_spin,
            self.record_iq_check, self.background_check,
        ):
            widget.setEnabled(False)
        for check in self.band_checks.values():
            check.setEnabled(False)
        self.start_btn.setEnabled(False)
        self.set_background_status("Запись фона…")

    def end_background(self, summary: dict | None = None) -> None:
        self._background_running = False
        self.background_btn.setText("Записать фон")
        self.background_btn.setEnabled(True)
        self.background_seconds_spin.setEnabled(True)
        for widget in (
            self.rate_combo, self.dwell_spin, self.threshold_spin,
            self.use_all_check, self.extended_check, self.high_usb_check,
            self.alarm_hits_spin, self.alarm_conf_spin,
            self.record_iq_check, self.background_check,
            self.background_btn, self.background_seconds_spin,
        ):
            widget.setEnabled(True)
        for check in self.band_checks.values():
            check.setEnabled(True)
        self.start_btn.setEnabled(True)
        frames = int((summary or {}).get("frames", 0))
        profiles = int((summary or {}).get("profiles", 0))
        ready = int((summary or {}).get("ready_profiles", 0))
        failure = str((summary or {}).get("failure") or "")
        if failure:
            self.set_background_status(f"Фон не записан: {failure}")
        elif ready == 0:
            self.set_background_status(
                f"Фон не записан: мало данных ({frames} блоков). "
                "Запишите дольше и без движения рядом."
            )
        else:
            self.set_background_status(
                f"Фон записан: {frames} блоков, полос готово {ready}"
            )

    def set_background_status(self, text: str) -> None:
        self.background_status.setText(str(text))

    def skip_background(self) -> bool:
        return bool(self.background_check.isChecked())

    def is_confirmed(self, event: DroneEvent) -> bool:
        if self.skip_background() and event.background >= BACKGROUND_MARK:
            return False
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
            set_style(self.device_hint, "color:#f87171; font-size:10px;")
            self.device_layout.addWidget(self.device_hint)
            return
        for device_id, name in devices:
            label = QLabel(f"{name}: ожидание")
            set_style(label, "color:#8fa6c0; font-size:10px;")
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
            self.record_iq_check, self.background_check,
            self.background_btn, self.background_seconds_spin,
        ):
            widget.setEnabled(False)
        for check in self.band_checks.values():
            check.setEnabled(False)
        set_style(self.status, "color:#22d3ee; font-size:11px;")
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
        color = QColor(tcol(_CLASS_COLORS.get(event.class_key, "#d7e2f0")))
        if event.whitelisted:
            color = QColor(tcol("#64748b"))
        elif event.class_key == "OVERLOAD":
            color = QColor(tcol("#facc15"))
        elif event.background >= BACKGROUND_MARK:
            color = QColor(tcol("#64748b"))
        elif self.is_confirmed(event):
            color = QColor(tcol("#f87171"))
        elif event.drone_like:
            color = QColor(tcol("#fb923c"))
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
            _binary_short(event),
            ", ".join(
                self._device_names.get(device_id, device_id)
                .replace("Симулятор", "SIM")
                for device_id in event.device_ids
            ),
        ]
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
        if event.binary:
            tips.append(
                "Бинарная модель: "
                f"{_binary_short(event)} "
                f"(порог тревоги "
                f"{float(event.binary.get('threshold_alarm', 0.9)) * 100:.0f}%)"
            )
        if event.wideband:
            tips.append(
                "Широкополосный сигнал: занимает почти всю полосу. "
                "Так же выглядит занятый Wi-Fi — проверьте вручную."
            )
        tooltip = "\n".join(tips)
        for column, text in enumerate(values):
            item = self.table.item(row, column)
            if item is None:
                item = QTableWidgetItem()
                self.table.setItem(row, column, item)
            # The monitor refreshes live rows twice a second; touching every
            # cell would force a full repaint even when nothing changed.
            if item.text() != text:
                item.setText(text)
            if item.data(Qt.ItemDataRole.UserRole) != event.event_id:
                item.setData(Qt.ItemDataRole.UserRole, event.event_id)
            if item.foreground().color() != color:
                item.setForeground(color)
            if tooltip and item.toolTip() != tooltip:
                item.setToolTip(tooltip)
            if column in (5, 6, 7, 8, 9):
                item.setTextAlignment(
                    Qt.AlignmentFlag.AlignRight | Qt.AlignmentFlag.AlignVCenter
                )
        if is_new:
            self.table.scrollToBottom()
        if (event.drone_like and is_new
                and event.background < BACKGROUND_MARK):
            self.show_alarm(event)

    def show_alarm(self, event: DroneEvent) -> None:
        binary = _binary_short(event)
        self.alarm.setText(
            "⚠ ВОЗМОЖНЫЙ ДРОНОВЫЙ ЛИНК: "
            f"{event.band_name} · {event.class_ru} · "
            f"{format_freq(event.freq_hz)} · SNR {event.max_snr_db:.1f} дБ · "
            f"подтверждено {event.count}× · увер. {event.confidence * 100:.0f}%"
            + (f" · дрон {binary}" if binary not in ("—", "н/д") else "")
            + (" · широкополосный, возможно Wi-Fi" if event.wideband else "")
        )
        self.alarm.setVisible(True)
        self._alarm_timer.start(10000)

    def update_status(self, text: str) -> None:
        # Called for every chunk; re-applying a stylesheet here forces Qt to
        # repolish the label each time. The colour is set once in begin_monitor.
        if self.status.text() != text:
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
        set_style(self.status, "color:#f87171; font-size:11px;"
            if failure else "color:#4ade80; font-size:11px;")
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
        set_style(self.status, "color:#f87171; font-size:11px;")
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
            self.record_iq_check, self.background_check,
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
