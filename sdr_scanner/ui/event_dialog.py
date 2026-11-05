# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Detailed evidence card for one drone event."""
from __future__ import annotations

import time
from collections.abc import Callable
from pathlib import Path

import pyqtgraph as pg
from PySide6.QtCore import Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QHBoxLayout,
    QInputDialog,
    QLabel,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)

from ..config import format_bw, format_freq
from ..drone.deep_look import (
    DEFAULT_WINDOW_S,
    DEFAULT_WINDOWS,
    DeepResult,
    save_capture,
)
from ..drone.report import export_event_bundle
from ..drone.tracker import DroneEvent
from ..drone.features import CLASS_RU
from ..paths import DATA_DIR, RECORDINGS_DIR
from ..recordings import set_label
from ..signatures import SignatureStore, match_event
from ..drone.whitelist import DroneWhitelist
from .themes import load_settings, save_settings, set_style, tcol


class DroneEventDialog(QDialog):
    feedback_requested = Signal(str, str)

    def __init__(self, event: DroneEvent, parent: QWidget | None = None,
                 store: SignatureStore | None = None,
                 whitelist: DroneWhitelist | None = None,
                 deep_look: Callable[[float, float, int], DeepResult] | None = None,
                 deep_reason: str = "") -> None:
        super().__init__(parent)
        self.drone_event = event
        self.store = store or SignatureStore()
        self.whitelist = whitelist
        self._deep_look = deep_look
        self._deep_reason = deep_reason
        self._deep_result: DeepResult | None = None
        self._deep_recording = None
        settings = load_settings(DATA_DIR / "settings.json")
        self._deep_seconds = float(
            settings.get("deep_look_seconds") or DEFAULT_WINDOW_S
        )
        self._deep_windows = int(
            settings.get("deep_look_windows") or DEFAULT_WINDOWS
        )
        self.matches = match_event(event, self.store.all())
        self.setWindowTitle(f"Событие {event.event_id}")
        self.resize(980, 820)
        self.setMinimumSize(780, 680)
        set_style(self, "QDialog { background:#0b1020; }"
            "QPushButton { background:#17233b; color:#d7e2f0;"
            " border:1px solid #2b3d5f; border-radius:5px;"
            " padding:5px 9px; }"
            "QPushButton:hover { background:#22345a; border-color:#3b5b8a; }")

        root = QVBoxLayout(self)
        root.setContentsMargins(14, 12, 14, 12)
        root.setSpacing(8)

        title = QLabel(event.class_ru.upper())
        set_style(title, "color:#f472b6; font-size:20px; font-weight:700;")
        root.addWidget(title)

        subtitle = QLabel(
            f"{event.band_name} · {format_freq(event.freq_hz)} · "
            f"SNR {event.max_snr_db:.1f} дБ · "
            f"{event.count} подтверждений · "
            f"уверенность {event.confidence * 100:.0f}%"
        )
        set_style(subtitle, "color:#d7e2f0; font-size:13px;")
        root.addWidget(subtitle)

        self.whitelist_label = QLabel(self._whitelist_text())
        self.whitelist_label.setWordWrap(True)
        set_style(self.whitelist_label, "color:#4ade80; font-size:11px;" if event.whitelisted
            else "color:#64748b; font-size:11px;")
        root.addWidget(self.whitelist_label)

        self.ml_label = QLabel(self._ml_text())
        self.ml_label.setWordWrap(True)
        set_style(self.ml_label, "color:#c4b5fd; font-size:11px;" if event.ml
            else "color:#64748b; font-size:11px;")
        root.addWidget(self.ml_label)

        self.binary_label = QLabel(self._binary_text())
        self.binary_label.setWordWrap(True)
        set_style(self.binary_label, "color:#fda4af; font-size:12px; font-weight:600;"
            if event.binary else "color:#64748b; font-size:11px;")
        root.addWidget(self.binary_label)

        if event.background >= 0.6:
            background_label = QLabel(
                "Фон: сигнал был в эфире всё время обучения карты фона. "
                "Скорее всего это местный Wi-Fi, Bluetooth или помеха — "
                "тревога по нему не поднимается. Если он изменился или "
                "усилился, посмотрите вручную."
            )
            background_label.setWordWrap(True)
            set_style(background_label, "color:#94a3b8; font-size:11px;")
            root.addWidget(background_label)

        if event.wideband:
            wide_label = QLabel(
                "Широкополосный сигнал: занимает почти всю полосу захвата. "
                "Ровно так же выглядит занятый Wi-Fi-канал. Модель не может "
                "отличить его от видеолинка дрона — проверьте вручную "
                "(посмотрите, есть ли рядом точка доступа)."
            )
            wide_label.setWordWrap(True)
            set_style(wide_label, "color:#facc15; font-size:11px;")
            root.addWidget(wide_label)

        grid = QGridLayout()
        grid.setHorizontalSpacing(18)
        grid.setVerticalSpacing(3)
        values = [
            ("Событие", event.event_id),
            ("Класс", f"{event.class_ru} ({event.class_key})"),
            ("Полоса", f"{event.band_name} ({event.band_key})"),
            ("Частота", format_freq(event.freq_hz)),
            ("Диапазон", f"{format_freq(event.freq_min_hz)} – "
                         f"{format_freq(event.freq_max_hz)}"),
            ("Ширина", format_bw(event.bw_hz)),
            ("Скважность", f"{event.max_duty * 100:.0f}%"),
            ("Фон", f"{event.background * 100:.0f}%"),
            ("Макс. импульс", f"{event.max_burst_ms:.1f} мс"),
            ("Устройства", ", ".join(event.device_ids) or "—"),
            ("Время", time.strftime(
                "%d.%m.%Y %H:%M:%S", time.localtime(event.last_seen)
            )),
            ("IQ-запись", self._clip_text()),
        ]
        for row, (key, value) in enumerate(values):
            key_label = QLabel(key)
            set_style(key_label, "color:#8fa6c0; font-size:11px;")
            value_label = QLabel(value)
            set_style(value_label, "color:#d7e2f0; font-size:11px;")
            value_label.setTextInteractionFlags(
                Qt.TextInteractionFlag.TextSelectableByMouse
            )
            grid.addWidget(key_label, row // 2, (row % 2) * 2)
            grid.addWidget(value_label, row // 2, (row % 2) * 2 + 1)
        root.addLayout(grid)

        self.deep_label = QLabel("")
        self.deep_label.setWordWrap(True)
        self.deep_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        set_style(self.deep_label, "color:#8fa6c0; font-size:11px;")
        self.deep_label.hide()
        root.addWidget(self.deep_label)

        deep_row = QHBoxLayout()
        deep_row.setSpacing(6)
        deep_row.addWidget(QLabel("Окно"))
        self.window_spin = QDoubleSpinBox()
        self.window_spin.setRange(0.2, 2.0)
        self.window_spin.setSingleStep(0.1)
        self.window_spin.setDecimals(1)
        self.window_spin.setSuffix(" с")
        self.window_spin.setValue(max(0.2, min(2.0, self._deep_seconds)))
        self.window_spin.setToolTip(
            "Длительность одного окна. Несколько окон подряд показывают, "
            "насколько поведение сигнала стабильно."
        )
        deep_row.addWidget(self.window_spin)
        deep_row.addWidget(QLabel("Окон"))
        self.windows_spin = QSpinBox()
        self.windows_spin.setRange(1, 6)
        self.windows_spin.setValue(max(1, min(6, self._deep_windows)))
        deep_row.addWidget(self.windows_spin)
        deep_row.addStretch(1)
        if deep_look is None:
            self.window_spin.setEnabled(False)
            self.windows_spin.setEnabled(False)
        root.addLayout(deep_row)

        plots = QHBoxLayout()
        plots.setSpacing(8)

        spectrum_plot = pg.PlotWidget(background=tcol("graph_bg"))
        spectrum_plot.setMenuEnabled(False)
        spectrum_plot.showGrid(x=True, y=True, alpha=0.12)
        spectrum_plot.setLabel("bottom", "Частота", units="MHz")
        spectrum_plot.setLabel("left", "dBFS")
        spectrum_plot.setTitle("Спектр события", color=tcol("#67e8f9"), size="10pt")
        if event.spectrum_freqs_hz and event.spectrum_db:
            xs = [f / 1e6 for f in event.spectrum_freqs_hz]
            spectrum_plot.plot(
                xs, event.spectrum_db,
                pen=pg.mkPen(tcol("#22d3ee"), width=1.5),
            )
            peak_x = event.freq_hz / 1e6
            spectrum_plot.addItem(pg.InfiniteLine(
                pos=peak_x, angle=90,
                pen=pg.mkPen(tcol("#f472b6"), width=1,
                             style=Qt.PenStyle.DotLine),
            ))
        spectrum_plot.setMinimumHeight(220)
        plots.addWidget(spectrum_plot, 1)

        envelope_plot = pg.PlotWidget(background=tcol("graph_bg"))
        envelope_plot.setMenuEnabled(False)
        envelope_plot.showGrid(x=True, y=True, alpha=0.12)
        envelope_plot.setLabel("bottom", "Время", units="мс")
        envelope_plot.setLabel("left", "dB")
        envelope_plot.setTitle("Огибающая", color=tcol("#67e8f9"), size="10pt")
        if event.envelope_ms and event.envelope_db:
            envelope_plot.plot(
                event.envelope_ms, event.envelope_db,
                pen=pg.mkPen(tcol("#f59e0b"), width=1.6),
            )
        else:
            label = pg.TextItem("нет данных", color=tcol("#64748b"), anchor=(0.5, 0.5))
            label.setPos(0.5, 0.5)
            envelope_plot.addItem(label)
        envelope_plot.setMinimumHeight(200)
        plots.addWidget(envelope_plot, 1)
        root.addLayout(plots, 1)

        matches_title = QLabel("ПОХОЖИЕ СИГНАЛЫ В БИБЛИОТЕКЕ")
        set_style(matches_title, "color:#a78bfa; font-size:11px; font-weight:600; margin-top:4px;")
        root.addWidget(matches_title)
        self.matches_label = QLabel(self._matches_html())
        self.matches_label.setWordWrap(True)
        set_style(self.matches_label, "color:#d7e2f0; font-size:10px; background:#0d1426;"
            "border:1px solid #22304a; border-radius:6px; padding:6px;")
        self.matches_label.setTextInteractionFlags(
            Qt.TextInteractionFlag.TextSelectableByMouse
        )
        root.addWidget(self.matches_label)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        set_style(self.status, "color:#8fa6c0; font-size:11px;")
        root.addWidget(self.status)

        buttons = QHBoxLayout()
        self.deep_btn = QPushButton("Глубокий взгляд")
        self.deep_btn.setEnabled(deep_look is not None)
        if deep_look is None:
            self.deep_btn.setToolTip(
                "Недоступно: " + (deep_reason or "нет свободного приёмника")
                + ". Остановите мешающий режим и откройте событие снова."
            )
        else:
            self.deep_btn.setToolTip(
                "Снять несколько окон на частоте события и измерить "
                "скважность, занятую полосу и перескоки. Мониторинг на это "
                "время приостановится, приёмник потом вернётся на место."
            )
        self.deep_btn.clicked.connect(self._run_deep_look)
        self.save_iq_btn = QPushButton("Сохранить IQ")
        self.save_iq_btn.setEnabled(False)
        self.save_iq_btn.setToolTip(
            "Сохранит снятые окна как обычную IQ-запись: её можно открыть "
            "в панели записей и разметить для обучения."
        )
        self.save_iq_btn.clicked.connect(self._save_deep_iq)
        self.dataset_btn = QPushButton("В датасет")
        self.dataset_btn.setEnabled(False)
        self.dataset_btn.setToolTip(
            "Поставить метку класса сохранённой записи глубокого взгляда."
        )
        self.dataset_btn.clicked.connect(self._label_deep_iq)
        self.export_btn = QPushButton("Экспорт отчёта…")
        self.export_btn.clicked.connect(self._export)
        self.folder_btn = QPushButton("Папка IQ")
        self.folder_btn.setEnabled(bool(event.clip_path))
        self.folder_btn.clicked.connect(self._open_clip_folder)
        self.white_btn = QPushButton("В белый список")
        self.white_btn.setEnabled(
            self.whitelist is not None and not event.whitelisted
        )
        if event.whitelisted:
            self.white_btn.setText("Уже в белом списке")
        self.white_btn.clicked.connect(self._add_to_whitelist)
        self.ml_btn = QPushButton("ML ошибся? Указать класс")
        self.ml_btn.setEnabled(bool(event.clip_path))
        self.ml_btn.setToolTip(
            "Сохранит IQ-фрагмент с правильной меткой для дообучения."
            if event.clip_path else
            "Нужен IQ-фрагмент события: включите запись IQ в дрон-мониторе."
        )
        self.ml_btn.clicked.connect(self._ask_ml_feedback)
        close_btn = QPushButton("Закрыть")
        close_btn.clicked.connect(self.accept)
        buttons.addWidget(self.deep_btn)
        buttons.addWidget(self.save_iq_btn)
        buttons.addWidget(self.dataset_btn)
        buttons.addWidget(self.export_btn)
        buttons.addWidget(self.folder_btn)
        buttons.addWidget(self.white_btn)
        buttons.addWidget(self.ml_btn)
        buttons.addStretch(1)
        buttons.addWidget(close_btn)
        root.addLayout(buttons)

    # ------------------------------------------------------------- deep look
    @property
    def deep_recording(self):
        return self._deep_recording

    def _run_deep_look(self) -> None:
        if self._deep_look is None:
            return
        seconds = float(self.window_spin.value())
        windows = int(self.windows_spin.value())
        settings = load_settings(DATA_DIR / "settings.json")
        settings["deep_look_seconds"] = seconds
        settings["deep_look_windows"] = windows
        save_settings(DATA_DIR / "settings.json", settings)

        self.deep_btn.setEnabled(False)
        self.deep_label.show()
        self._deep_result = None
        self._deep_recording = None
        self.save_iq_btn.setEnabled(False)
        self.dataset_btn.setEnabled(False)
        set_style(self.deep_label, "color:#facc15; font-size:11px;")
        self.deep_label.setText(
            f"Слушаю {windows} окн. по {seconds:.1f} с на частоте события — "
            "мониторинг на паузе…"
        )
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        QApplication.processEvents()
        result: DeepResult | None = None
        error = ""
        try:
            result = self._deep_look(
                float(self.drone_event.freq_hz), seconds, windows,
            )
        except Exception as exc:                     # pragma: no cover - UI guard
            error = str(exc)
        finally:
            QApplication.restoreOverrideCursor()
            self.deep_btn.setEnabled(True)

        if result is None:
            set_style(self.deep_label, "color:#f87171; font-size:11px;")
            self.deep_label.setText(
                f"Проверка не удалась: {error or 'приёмник не ответил'}"
            )
            return
        self._deep_result = result
        if not result.ok:
            set_style(self.deep_label, "color:#f87171; font-size:11px;")
        elif (result.behavior is not None
                and result.behavior.duty >= 0.70
                and result.behavior.occupied >= 0.40):
            set_style(self.deep_label, "color:#4ade80; font-size:11px;")
        else:
            set_style(self.deep_label, "color:#facc15; font-size:11px;")
        self.deep_label.setText(result.text())
        if result.ok and result.data is not None:
            self.save_iq_btn.setEnabled(True)

    def _save_deep_iq(self) -> None:
        result = self._deep_result
        if result is None or not result.ok or result.data is None:
            return
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            info = save_capture(result, RECORDINGS_DIR)
        finally:
            QApplication.restoreOverrideCursor()
        if info is None:
            self.status.setText("Не удалось сохранить IQ глубокого взгляда.")
            set_style(self.status, "color:#f87171; font-size:11px;")
            return
        self._deep_recording = info
        self.save_iq_btn.setEnabled(False)
        self.dataset_btn.setEnabled(True)
        self.status.setText(
            f"IQ сохранён: {info.recording_id}. "
            "Его можно разметить кнопкой «В датасет»."
        )
        set_style(self.status, "color:#4ade80; font-size:11px;")
        self.deep_label.setText(result.text())

    def _label_deep_iq(self) -> None:
        info = self._deep_recording
        if info is None:
            return
        keys = [
            "FHSS", "TELEMETRY", "VIDEO_ANALOG", "VIDEO_DIGITAL",
            "WIFI", "NARROW",
        ]
        labels = [CLASS_RU[key] for key in keys]
        label, ok = QInputDialog.getItem(
            self, "Класс сигнала",
            "Какая это запись? Метка пойдёт в обучение.",
            labels, 0, False,
        )
        if not ok:
            return
        index = labels.index(label) if label in labels else 0
        set_label(info, keys[index])
        self.status.setText(
            f"Метка сохранена: {label}. Запись появится в панели ML."
        )
        set_style(self.status, "color:#4ade80; font-size:11px;")
        self.dataset_btn.setEnabled(False)

    # ------------------------------------------------------------------ helpers
    def _binary_text(self) -> str:
        data = self.drone_event.binary or {}
        if not data:
            return (
                "Дрон / не дрон: модель не установлена — только эвристика."
            )
        if self.drone_event.class_key == "OVERLOAD":
            return (
                "Дрон / не дрон: не определено из-за перегрузки входа."
            )
        verdict = str(data.get("verdict") or "")
        if verdict == "unknown":
            return (
                "Дрон / не дрон: сигнала слишком мало для оценки."
            )
        score = float(data.get("score") or 0.0)
        alarm = float(data.get("threshold_alarm") or 0.9) * 100.0
        candidate = float(data.get("threshold_candidate") or 0.6) * 100.0
        ru = {
            "drone": "похоже на дрон",
            "candidate": "кандидат, нужно подтверждение",
            "background": "не похоже на дрон",
        }.get(verdict, verdict)
        return (
            f"Дрон / не дрон: {score * 100:.0f}% — {ru}. "
            f"Тревога с {alarm:.0f}%, кандидат с {candidate:.0f}%. "
            "Это вероятность по обученной модели, а не гарантия."
        )

    def _ml_text(self) -> str:
        if self.drone_event.class_key == "OVERLOAD":
            return (
                "ML отключён: перегрузка входа. Уменьшите усиление "
                "или отодвиньте антенну."
            )
        data = self.drone_event.ml or {}
        if not data:
            return "ML: модель не обучена — доступна только эвристика."
        label = str(data.get("label") or "")
        confidence = float(data.get("confidence") or 0.0)
        ru = CLASS_RU.get(label, label or "неизвестно")
        alternatives = data.get("alternatives") or []
        extra = []
        for item in alternatives[1:3]:
            try:
                key, prob = item
            except Exception:
                continue
            extra.append(
                f"{CLASS_RU.get(str(key), str(key))} "
                f"{float(prob) * 100:.0f}%"
            )
        suffix = f" · ещё: {', '.join(extra)}" if extra else ""
        source = {
            "synthetic": "синтетика",
            "real": "реальные записи",
            "mixed": "реальные + синтетика",
        }.get(str(data.get("source") or ""), "неизвестно")
        return (
            f"ML-гипотеза: {ru} {confidence * 100:.0f}%{suffix} "
            f"(источник: {source}; не заменяет эвристику)."
        )

    def _ask_ml_feedback(self) -> None:
        keys = [
            "FHSS", "TELEMETRY", "VIDEO_ANALOG", "VIDEO_DIGITAL",
            "WIFI", "NARROW",
        ]
        labels = [CLASS_RU[key] for key in keys]
        current = 0
        predicted = str((self.drone_event.ml or {}).get("label") or "")
        if predicted in keys:
            current = keys.index(predicted)
        text, ok = QInputDialog.getItem(
            self,
            "ML: правильный класс",
            "Выберите класс сигнала:",
            labels,
            current,
            False,
        )
        if not ok:
            return
        index = labels.index(text)
        self.feedback_requested.emit(
            self.drone_event.event_id, keys[index]
        )
        set_style(self.status, "color:#4ade80; font-size:11px;")
        self.status.setText(
            "Пример сохранён. Во вкладке ML нажмите «Обучить на записях»."
        )

    def _whitelist_text(self) -> str:
        if self.drone_event.whitelisted:
            return (
                "В белом списке: "
                f"{self.drone_event.whitelist_name or 'известный сигнал'} — "
                "тревога подавлена."
            )
        return "В белом списке нет — событие может поднимать тревогу."

    def _add_to_whitelist(self) -> None:
        if self.whitelist is None:
            return
        try:
            entry = self.whitelist.add_event(self.drone_event)
        except Exception as exc:
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText(f"Не удалось добавить в белый список: {exc}")
            return
        self.drone_event.whitelisted = True
        self.drone_event.whitelist_name = entry.name
        self.whitelist_label.setText(self._whitelist_text())
        set_style(self.whitelist_label, "color:#4ade80; font-size:11px;")
        self.white_btn.setText("Уже в белом списке")
        self.white_btn.setEnabled(False)
        set_style(self.status, "color:#4ade80; font-size:11px;")
        self.status.setText(f"Добавлено в белый список: {entry.name}")

    def _matches_html(self) -> str:
        if not self.matches:
            return ("Нет уверенных совпадений. Это может быть неизвестный "
                    "сигнал, помеха или источник, которого нет в библиотеке.")
        lines = []
        for index, match in enumerate(self.matches, start=1):
            signature = match.signature
            score = match.score * 100.0
            reasons = ", ".join(match.reasons) or "частичное совпадение"
            ref = signature.references[0] if signature.references else "—"
            lines.append(
                f"<b>{index}. {signature.name}</b> — "
                f"<span style='color:{tcol('#4ade80')}'>{score:.0f}%</span> · "
                f"{signature.category} · {reasons}<br>"
                f"<span style='color:{tcol('#8fa6c0')}'>источник: "
                f"{signature.source_class} · {ref}</span>"
            )
        lines.append(
            f"<span style='color:{tcol('#64748b')}'>Гипотеза по признакам; "
            "не подтверждение модели дрона.</span>"
        )
        return "<br>".join(lines)

    def _clip_text(self) -> str:
        if not self.drone_event.clip_path:
            return "нет записи"
        seconds = (self.drone_event.clip_samples
                   / max(1.0, self.drone_event.clip_sample_rate))
        return (
            f"{seconds * 1000:.0f} мс · "
            f"{self.drone_event.clip_sample_rate / 1e6:.2f} MS/s · "
            f"{self.drone_event.clip_samples} отсчётов"
        )

    def _open_clip_folder(self) -> None:
        if not self.drone_event.clip_path:
            return
        folder = Path(self.drone_event.clip_path).parent
        QDesktopServices.openUrl(QUrl.fromLocalFile(str(folder)))

    def _export(self) -> None:
        folder = QFileDialog.getExistingDirectory(
            self, "Куда экспортировать событие", str(Path.cwd())
        )
        if not folder:
            return
        try:
            path = export_event_bundle(
                self.drone_event, folder,
                matches=[match.to_dict() for match in self.matches],
            )
        except Exception as exc:
            set_style(self.status, "color:#f87171; font-size:11px;")
            self.status.setText(f"Ошибка экспорта: {exc}")
            return
        set_style(self.status, "color:#4ade80; font-size:11px;")
        self.status.setText(f"Экспортировано: {path}")
