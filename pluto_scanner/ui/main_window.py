"""Main window: devices, spectrum, waterfall, contacts, software VFO."""
from __future__ import annotations

import logging
from dataclasses import replace
from pathlib import Path

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtGui import QCloseEvent, QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QFileDialog,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QSlider,
    QSplitter,
    QTabWidget,
    QVBoxLayout,
    QWidget,
)

from ..config import (
    APP_NAME,
    BANDS,
    DEFAULT_CENTER_FREQ,
    DEFAULT_FFT_SIZE,
    DEFAULT_SAMPLE_RATE,
    format_freq,
    in_stock_pluto_range,
)
from ..dsp.audio import AudioSink
from ..devices import scan_pluto_uris
from ..drone.background import DroneBackgroundStore
from ..drone.bands import chunks_for_bands, selected_bands
from ..drone.manager import DroneMonitorManager
from ..drone.whitelist import DroneWhitelist
from ..engine import DeviceSession
from ..model import Contact, DeviceConfig, SpectrumFrame, VFOConfig
from ..paths import ICON_PATH
from ..scanner.compare import compare_background_files
from ..scanner.controller import ScanController
from ..scanner.recorder import find_latest_background
from ..signatures import SignatureStore
from ..store import ContactStore
from .contact_table import ContactTable
from .device_panel import DevicePanel
from .drone_panel import DronePanel
from .event_dialog import DroneEventDialog
from .spectrum_view import SpectrumView
from .vfo_panel import VFOPanel
from .scan_panel import ScanPanel
from .signature_panel import SignaturePanel
from .waterfall_view import WaterfallView
from .whitelist_dialog import WhitelistDialog

log = logging.getLogger(__name__)

_FS_CHOICES = [0.512e6, 1.024e6, 1.536e6, 2.048e6, 2.4e6, 3.2e6]
_SIM_CENTERS = [433.92e6, 915.0e6, 2450.0e6, 1575.42e6, 868.0e6]
_STATUS_RU = {
    "idle": "ожидание",
    "starting": "запуск",
    "running": "работает",
    "error": "ошибка",
    "stopped": "остановлен",
}
_STATUS_COLOR = {
    "running": "#4ade80",
    "starting": "#facc15",
    "error": "#f87171",
    "stopped": "#94a3b8",
    "idle": "#94a3b8",
}


class MainWindow(QMainWindow):
    scan_done = Signal(object)
    drone_done = Signal(object, str)

    def __init__(self, args) -> None:
        super().__init__()
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.args = args
        self.store = ContactStore()
        self.signature_store = SignatureStore()
        self.drone_whitelist = DroneWhitelist()
        self.drone_background = DroneBackgroundStore()
        self.audio_sink = AudioSink()
        self.audio_enabled = False
        self._audio_guard = False
        self._guard = False
        self._device_seq = 0
        self.sessions: dict[str, DeviceSession] = {}
        self.selected_id: str | None = None
        self.contacts_by_device: dict[str, dict[str, Contact]] = {}
        self._last_frame: SpectrumFrame | None = None
        self._last_status = ""
        self._shutting_down = False
        self._scan_controller: ScanController | None = None
        self._scanning = False
        self._scan_audio_was_enabled = False
        self._last_scan_bundle: str | None = None
        self._scan_compare_override: str | None = None
        self._drone_manager: DroneMonitorManager | None = None
        self._drone_active = False
        self._drone_audio_was_enabled = False
        self._pre_drone_frame: SpectrumFrame | None = None
        self._await_center: float | None = None

        self.setWindowTitle(f"{APP_NAME} — software VFO / new contacts")
        self.resize(1500, 950)
        self.setMinimumSize(1120, 720)

        self._build_ui()
        self._connect()
        self._table_timer = QTimer(self)
        self._table_timer.setInterval(400)
        self._table_timer.timeout.connect(self._refresh_contacts)
        self._table_timer.start()

        self._initial_devices()

    # ------------------------------------------------------------------ UI build
    def _build_ui(self) -> None:
        central = QWidget()
        self.setCentralWidget(central)
        root = QHBoxLayout(central)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(6)

        self.splitter = QSplitter(Qt.Orientation.Horizontal)
        root.addWidget(self.splitter)

        # ---------------- left
        left = QWidget()
        left.setMinimumWidth(300)
        left.setMaximumWidth(390)
        ll = QVBoxLayout(left)
        ll.setContentsMargins(0, 0, 0, 0)
        ll.setSpacing(6)
        title = QLabel("PLUTO\nSCANNER")
        title.setFont(QFont("Segoe UI", 20, QFont.Weight.Bold))
        title.setStyleSheet("color:#22d3ee; letter-spacing:2px; line-height:0.9;")
        ll.addWidget(title)
        self.device_panel = DevicePanel()
        ll.addWidget(self.device_panel)
        self.vfo_panel = VFOPanel()
        ll.addWidget(self.vfo_panel)
        self.band_group = QGroupBox("Диапазоны")
        bl = QVBoxLayout(self.band_group)
        self.band_combo = QComboBox()
        for b in BANDS:
            self.band_combo.addItem(f"{b.name}  ·  {format_freq(b.frequency)}", b.frequency)
        bl.addWidget(self.band_combo)
        self.band_btn = QPushButton("Настроить диапазон")
        self.band_btn.clicked.connect(lambda: self._tune_band())
        bl.addWidget(self.band_btn)
        note = QLabel("Стоковый Pluto: 325 МГц – 3.8 ГГц")
        note.setStyleSheet("color:#64748b; font-size:10px;")
        bl.addWidget(note)
        ll.addWidget(self.band_group)
        self.sim_group = QGroupBox("Симулятор")
        sl = QHBoxLayout(self.sim_group)
        self.inject_btn = QPushButton("Впрыснуть сигнал в VFO")
        self.inject_btn.clicked.connect(lambda: self._inject_signal())
        sl.addWidget(self.inject_btn)
        ll.addWidget(self.sim_group)
        ll.addStretch(1)
        self.splitter.addWidget(left)

        # ---------------- centre
        centre = QWidget()
        cl = QVBoxLayout(centre)
        cl.setContentsMargins(0, 0, 0, 0)
        cl.setSpacing(4)
        self.rx_group = QGroupBox("Приёмник")
        rl = QGridLayout(self.rx_group)
        rl.setHorizontalSpacing(6)
        rl.setVerticalSpacing(4)
        self.center_spin = QDoubleSpinBox()
        self.center_spin.setRange(70.0, 6000.0)
        self.center_spin.setDecimals(6)
        self.center_spin.setSuffix(" MHz")
        self.center_spin.setKeyboardTracking(False)
        self.center_spin.setMinimumWidth(150)
        self.center_spin.setValue(DEFAULT_CENTER_FREQ / 1e6)
        self.center_spin.valueChanged.connect(self._on_center_spin)

        self.fs_combo = QComboBox()
        for fs in _FS_CHOICES:
            self.fs_combo.addItem(f"{fs / 1e6:.3f} MS/s", fs)
        self.fs_combo.currentIndexChanged.connect(self._on_fs_combo)

        self.gain_slider = QSlider(Qt.Orientation.Horizontal)
        self.gain_slider.setRange(0, 73)
        self.gain_slider.setValue(40)
        self.gain_slider.setFixedWidth(120)
        self.gain_slider.valueChanged.connect(self._on_gain)
        self.gain_label = QLabel("40 dB")
        self.gain_label.setMinimumWidth(42)

        self.threshold_spin = QDoubleSpinBox()
        self.threshold_spin.setRange(3.0, 30.0)
        self.threshold_spin.setDecimals(1)
        self.threshold_spin.setSuffix(" dB")
        self.threshold_spin.setValue(8.0)
        self.threshold_spin.valueChanged.connect(self._on_threshold)

        rl.addWidget(QLabel("Центр"), 0, 0)
        rl.addWidget(self.center_spin, 0, 1)
        rl.addWidget(QLabel("Полоса"), 0, 2)
        rl.addWidget(self.fs_combo, 0, 3)
        rl.addWidget(QLabel("Усиление"), 0, 4)
        rl.addWidget(self.gain_slider, 0, 5)
        rl.addWidget(self.gain_label, 0, 6)
        rl.addWidget(QLabel("Порог"), 1, 0)
        rl.addWidget(self.threshold_spin, 1, 1)
        self.reset_btn = QPushButton("Сброс фона")
        self.reset_btn.clicked.connect(lambda: self._reset_background())
        rl.addWidget(self.reset_btn, 1, 2)
        self.audio_btn = QCheckBox("Аудио")
        self.audio_btn.toggled.connect(self._toggle_audio)
        rl.addWidget(self.audio_btn, 1, 3)
        self.status_hint = QLabel("VFO — software, LO не трогаем")
        self.status_hint.setStyleSheet("color:#94a3b8;")
        rl.addWidget(self.status_hint, 1, 4, 1, 3)
        rl.setColumnStretch(6, 1)
        cl.addWidget(self.rx_group)

        self.spectrum = SpectrumView()
        self.waterfall = WaterfallView()
        vf = QSplitter(Qt.Orientation.Vertical)
        vf.addWidget(self.spectrum)
        vf.addWidget(self.waterfall)
        vf.setSizes([430, 300])
        cl.addWidget(vf, 1)
        self.splitter.addWidget(centre)

        # ---------------- right
        self.contact_table = ContactTable()
        self.contact_table.setMinimumWidth(520)
        self.scan_panel = ScanPanel()
        self.scan_panel.setMinimumWidth(520)
        self.drone_panel = DronePanel()
        self.drone_panel.setMinimumWidth(520)
        self.signature_panel = SignaturePanel(self.signature_store)
        self.signature_panel.setMinimumWidth(520)
        self.right_tabs = QTabWidget()
        self.right_tabs.addTab(self.contact_table, "Контакты")
        self.right_tabs.addTab(self.scan_panel, "Сканер диапазона")
        self.right_tabs.addTab(self.drone_panel, "Дрон-монитор")
        self.right_tabs.addTab(self.signature_panel, "Сигнатуры")
        self.splitter.addWidget(self.right_tabs)
        self.splitter.setSizes([350, 860, 640])
        self.splitter.setStretchFactor(0, 0)
        self.splitter.setStretchFactor(1, 1)
        self.splitter.setStretchFactor(2, 0)

        # status bar
        self.status_label = QLabel("Готов")
        self.cal_label = QLabel("Фон: —")
        self.fps_label = QLabel("— FPS")
        self.audio_label = QLabel("Аудио выкл")
        for w in (self.cal_label, self.fps_label, self.audio_label):
            w.setStyleSheet("color:#8fa6c0; padding:0 8px;")
        self.statusBar().addWidget(self.status_label, 1)
        self.statusBar().addPermanentWidget(self.cal_label)
        self.statusBar().addPermanentWidget(self.fps_label)
        self.statusBar().addPermanentWidget(self.audio_label)

    def _connect(self) -> None:
        self.device_panel.add_simulator.connect(self._add_simulator)
        self.device_panel.add_pluto.connect(self._add_pluto)
        self.device_panel.scan_pluto.connect(self._scan_pluto)
        self.device_panel.remove_device.connect(self._remove_device)
        self.device_panel.device_selected.connect(self._select_device)
        self.vfo_panel.vfo_changed.connect(self._on_vfo_changed)
        self.contact_table.contact_activated.connect(self._on_contact_activated)
        self.contact_table.mark_known.connect(self._mark_known)
        self.contact_table.forget.connect(self._forget_contact)
        self.spectrum.frequency_clicked.connect(self._on_frequency_clicked)
        self.waterfall.frequency_clicked.connect(self._on_frequency_clicked)
        self.scan_panel.start_requested.connect(self._start_scan)
        self.scan_panel.stop_requested.connect(self._stop_scan)
        self.scan_panel.compare_requested.connect(self._compare_scan)
        self.drone_panel.start_requested.connect(self._start_drone)
        self.drone_panel.stop_requested.connect(self._stop_drone)
        self.drone_panel.event_activated.connect(self._open_drone_event)
        self.drone_panel.whitelist_requested.connect(self._open_whitelist)

    def _initial_devices(self) -> None:
        devices = list(getattr(self.args, "device", []) or [])
        want_sim = bool(getattr(self.args, "sim", False)) or not devices
        center = float(getattr(self.args, "center", DEFAULT_CENTER_FREQ))
        fs = float(getattr(self.args, "sample_rate", DEFAULT_SAMPLE_RATE))
        fft = int(getattr(self.args, "fft", DEFAULT_FFT_SIZE))
        for uri in devices:
            self._make_pluto(uri, center=center, fs=fs, fft=fft)
        if want_sim:
            self._make_simulator(center=center, fs=fs, fft=fft)
        if self.sessions:
            first = next(iter(self.sessions))
            self._select_device(first)
        else:
            self._update_controls()

    # ------------------------------------------------------------------- devices
    def _next_id(self, prefix: str) -> str:
        self._device_seq += 1
        return f"{prefix}-{self._device_seq}"

    def _make_simulator(self, center: float | None = None,
                        fs: float | None = None,
                        fft: int | None = None) -> None:
        idx = len([s for s in self.sessions.values() if s.config.kind == "sim"])
        device_id = self._next_id("sim")
        center = center if center is not None else _SIM_CENTERS[idx % len(_SIM_CENTERS)]
        config = DeviceConfig(
            device_id=device_id,
            name=f"Симулятор {idx + 1}",
            kind="sim",
            center_freq=float(center),
            sample_rate=float(fs or DEFAULT_SAMPLE_RATE),
            gain=40.0,
            fft_size=int(fft or DEFAULT_FFT_SIZE),
            seed=17 + idx * 31,
        )
        self._add_session(config)

    def _make_pluto(self, uri: str, center: float | None = None,
                    fs: float | None = None,
                    fft: int | None = None) -> None:
        uri = (uri or "ip:192.168.2.1").strip()
        count = len([s for s in self.sessions.values() if s.config.kind == "pluto"])
        config = DeviceConfig(
            device_id=self._next_id("pluto"),
            name=f"Pluto {count + 1}",
            kind="pluto",
            uri=uri,
            center_freq=float(center or DEFAULT_CENTER_FREQ),
            sample_rate=float(fs or DEFAULT_SAMPLE_RATE),
            bandwidth=float(fs or DEFAULT_SAMPLE_RATE),
            gain=40.0,
            fft_size=int(fft or DEFAULT_FFT_SIZE),
            seed=1,
        )
        self._add_session(config)

    def _add_session(self, config: DeviceConfig) -> None:
        session = DeviceSession(config, self.store, self)
        session.spectrum_updated.connect(self._on_spectrum)
        session.contacts_updated.connect(self._on_contacts)
        session.status_changed.connect(self._on_status)
        session.error.connect(self._on_error)
        session.audio_ready.connect(self._on_audio)
        session.info_updated.connect(self._on_info)
        self.sessions[config.device_id] = session
        self.contacts_by_device.setdefault(config.device_id, {})
        self.device_panel.add_device(config)
        session.start()
        if self.selected_id is None:
            self._select_device(config.device_id)
        self._refresh_contacts()
        self.status_label.setText(f"{config.name}: запуск")

    def _add_simulator(self) -> None:
        self._make_simulator()
        self.status_label.setText("Добавлен симулятор")

    def _add_pluto(self, uri: str) -> None:
        self._make_pluto(uri)
        self.status_label.setText(f"Подключаю Pluto {uri}...")

    def _scan_pluto(self) -> None:
        QApplication.setOverrideCursor(Qt.CursorShape.WaitCursor)
        try:
            uris = scan_pluto_uris()
        finally:
            QApplication.restoreOverrideCursor()
        uris.sort(key=lambda u: (not u.startswith("usb:"), u))
        if uris:
            self.device_panel.uri_edit.setText(uris[0])
            self.status_label.setText(
                "Найдено: " + ", ".join(uris[:3])
            )
            self.status_label.setStyleSheet("color:#4ade80;")
        else:
            self.status_label.setText(
                "Pluto не найден. Проверьте USB/сеть и pyadi-iio."
            )
            self.status_label.setStyleSheet("color:#facc15;")

    def _remove_device(self, device_id: str) -> None:
        if self._drone_active:
            self._stop_drone()
        if self._scanning and device_id == self.selected_id:
            self._stop_scan()
        session = self.sessions.pop(device_id, None)
        if session is not None:
            try:
                session.stop()
            except Exception:
                pass
            session.deleteLater()
        self.contacts_by_device.pop(device_id, None)
        self.device_panel.remove_item(device_id)
        if self.selected_id == device_id:
            self.selected_id = None
            if self.sessions:
                self._select_device(next(iter(self.sessions)))
            else:
                self._last_frame = None
                self.spectrum.clear()
                self.waterfall.clear()
                self.contact_table.update_contacts([], self.device_panel.device_names())
                self._update_controls()
        self._refresh_contacts()
        self.status_label.setText("Устройство удалено")

    def _select_device(self, device_id: str) -> None:
        if device_id not in self.sessions:
            return
        if self._drone_active:
            self._stop_drone()
        if self._scanning:
            self._stop_scan()
        if self.selected_id == device_id:
            self._update_controls()
            return
        old = self.sessions.get(self.selected_id) if self.selected_id else None
        if old is not None:
            old.set_audio_enabled(False)
        self.selected_id = device_id
        self._await_center = None
        session = self.sessions[device_id]
        session.set_audio_enabled(self.audio_enabled)
        self.audio_sink.clear()
        self.device_panel.select_device(device_id)
        self._guard = True
        try:
            self.center_spin.setValue(session.config.center_freq / 1e6)
            self._set_fs_combo(session.config.sample_rate)
            self.gain_slider.setValue(int(round(session.config.gain)))
            self.threshold_spin.setValue(session.detector.threshold_db)
        finally:
            self._guard = False
        self.vfo_panel.set_enabled(True)
        self.vfo_panel.set_context(
            session.config.center_freq, session.config.sample_rate,
            session.vfo,
        )
        self.scan_panel.set_context(
            session.config.center_freq, session.config.sample_rate
        )
        if session.last_frame is not None:
            self._last_frame = session.last_frame
            self.spectrum.update_frame(
                session.last_frame,
                session.config.center_freq + session.vfo.offset_hz,
            )
            self.waterfall.update_frame(session.last_frame)
        else:
            self._last_frame = None
            self.spectrum.clear()
            self.waterfall.clear()
        self._update_controls()
        self.status_label.setText(f"Выбрано: {session.config.name}")

    def _set_fs_combo(self, fs: float) -> None:
        for i in range(self.fs_combo.count()):
            if abs(float(self.fs_combo.itemData(i)) - float(fs)) < 1.0:
                self.fs_combo.setCurrentIndex(i)
                return
        self.fs_combo.addItem(f"{fs / 1e6:.3f} MS/s", float(fs))
        self.fs_combo.setCurrentIndex(self.fs_combo.count() - 1)

    def _update_controls(self) -> None:
        has = self.selected_id is not None
        active = has and not self._drone_active
        self.rx_group.setEnabled(active)
        self.band_group.setEnabled(active)
        self.vfo_panel.setEnabled(active)
        self.audio_btn.setEnabled(active)
        self.scan_panel.set_device_enabled(active)
        if not has:
            self.sim_group.setEnabled(False)
            return
        session = self.sessions[self.selected_id]
        self.sim_group.setEnabled(session.config.kind == "sim")
        self.inject_btn.setEnabled(session.config.kind == "sim")
        self.scan_panel.set_context(
            session.config.center_freq, session.config.sample_rate
        )
        self.setWindowTitle(
            f"{APP_NAME} — {session.config.name} — "
            f"{format_freq(session.config.center_freq)}"
        )

    # ------------------------------------------------------------------- spectrum
    def _on_spectrum(self, device_id: str, frame: SpectrumFrame) -> None:
        if device_id != self.selected_id:
            return
        if self._await_center is not None:
            tolerance = max(1.0e6, frame.span_hz * 0.25)
            if abs(frame.center_freq - self._await_center) > tolerance:
                # A queued frame from the last monitored chunk; ignore it
                # until the radio actually reports the restored LO.
                return
            self._await_center = None
        self._last_frame = frame
        session = self.sessions.get(device_id)
        if session is None:
            return
        vfo_abs = frame.center_freq + session.vfo.offset_hz
        self.spectrum.update_frame(frame, vfo_abs)
        self.waterfall.update_frame(frame)
        if frame.calibrated:
            self.cal_label.setText("Фон: готов")
            self.cal_label.setStyleSheet("color:#4ade80; padding:0 8px;")
        else:
            self.cal_label.setText(
                f"Калибровка: {frame.calibration_progress * 100:.0f}%"
            )
            self.cal_label.setStyleSheet("color:#facc15; padding:0 8px;")
        self.fps_label.setText(
            f"{frame.fps:.1f} FPS · {frame.span_hz / 1e6:.3f} МГц"
        )
        new_count = sum(1 for c in frame.contacts if c.is_new())
        self.status_hint.setText(
            f"Контактов: {len(frame.contacts)} · новых: {new_count}"
        )
        self._on_contacts(device_id, frame.contacts)

    def _on_contacts(self, device_id: str, contacts: list[Contact]) -> None:
        self.contacts_by_device[device_id] = {
            c.contact_id: c for c in contacts
        }

    def _refresh_contacts(self) -> None:
        all_contacts: list[Contact] = []
        for contacts in self.contacts_by_device.values():
            all_contacts.extend(contacts.values())
        self.contact_table.update_contacts(
            all_contacts, self.device_panel.device_names()
        )

    def _on_status(self, device_id: str, status: str) -> None:
        self.device_panel.set_status(device_id, status)
        if device_id == self.selected_id:
            self._last_status = status
            name = self.device_panel.device_name(device_id)
            label = _STATUS_RU.get(status, status)
            self.status_label.setText(f"{name}: {label}")
            self.status_label.setStyleSheet(
                f"color:{_STATUS_COLOR.get(status, '#d7e2f0')};"
            )
        if status == "stopped":
            self.audio_sink.clear()

    def _on_error(self, device_id: str, message: str) -> None:
        log.error("%s: %s", device_id, message)
        text = message.lower()
        fatal = (
            "broken pipe" in text
            or "no device" in text
            or "no such device" in text
            or "bad file descriptor" in text
        )
        self.device_panel.set_status(device_id, "error")
        if self._drone_active and self._drone_manager is not None and fatal:
            self._drone_manager.fail(
                f"{device_id}: {message}. Проверьте USB-кабель/питание "
                "или используйте Ethernet."
            )
            return
        self.status_label.setText(message)
        self.status_label.setStyleSheet("color:#f87171;")
        self.status_label.setToolTip(message)

    def _on_info(self, device_id: str, info: dict) -> None:
        session = self.sessions.get(device_id)
        if session is None:
            return
        self.device_panel.set_status(device_id, session.worker.status)
        if device_id != self.selected_id or self._scanning or self._drone_active:
            return
        center = float(info.get("center_freq", session.config.center_freq))
        fs = float(info.get("sample_rate", session.config.sample_rate))
        self._guard = True
        try:
            self.center_spin.setValue(center / 1e6)
            self._set_fs_combo(fs)
        finally:
            self._guard = False
        self.vfo_panel.set_context(center, fs, session.vfo)

    # ---------------------------------------------------------------------- audio
    def _toggle_audio(self, checked: bool) -> None:
        if self._audio_guard or self._scanning or self._drone_active:
            # Audio is muted for the duration of a sweep; the button is
            # disabled too, this guard covers programmatic changes as well.
            return
        if checked:
            if not self.audio_sink.start(64_000):
                self._audio_guard = True
                self.audio_btn.setChecked(False)
                self._audio_guard = False
                self.audio_label.setText("Аудио: нет устройства")
                self.audio_label.setStyleSheet("color:#f87171; padding:0 8px;")
                return
            self.audio_enabled = True
            self.audio_label.setText("Аудио вкл")
            self.audio_label.setStyleSheet("color:#4ade80; padding:0 8px;")
        else:
            self.audio_enabled = False
            self.audio_sink.stop()
            self.audio_label.setText("Аудио выкл")
            self.audio_label.setStyleSheet("color:#8fa6c0; padding:0 8px;")
        for did, session in self.sessions.items():
            session.set_audio_enabled(self.audio_enabled and did == self.selected_id)
        if not self.audio_enabled:
            self.audio_sink.clear()

    def _on_audio(self, device_id: str, samples, rate: float) -> None:
        if (not self.audio_enabled or self._drone_active
                or device_id != self.selected_id):
            return
        if not self.audio_sink.running or self.audio_sink.rate != int(round(rate)):
            if not self.audio_sink.start(rate):
                self.audio_label.setText(f"Аудио: {self.audio_sink.error}")
                self.audio_label.setStyleSheet("color:#f87171; padding:0 8px;")
                return
        self.audio_sink.push(samples)
        self.audio_label.setText(f"Аудио {rate / 1000:.0f} kHz")
        self.audio_label.setStyleSheet("color:#4ade80; padding:0 8px;")

    # ------------------------------------------------------------------------ VFO
    def _on_vfo_changed(self, vfo: VFOConfig) -> None:
        if self.selected_id is None or self._scanning or self._drone_active:
            return
        session = self.sessions[self.selected_id]
        session.set_vfo(vfo)
        if not vfo.active:
            self.audio_sink.clear()
        if self._last_frame is not None:
            self.spectrum.update_frame(
                self._last_frame,
                self._last_frame.center_freq + vfo.offset_hz,
            )

    def _on_frequency_clicked(self, freq_hz: float) -> None:
        if self.selected_id is None or self._scanning or self._drone_active:
            return
        session = self.sessions[self.selected_id]
        offset = float(freq_hz) - session.config.center_freq
        self.vfo_panel.set_offset(offset)
        self.status_label.setText(
            f"VFO: {format_freq(freq_hz)}  "
            f"({offset / 1e3:+.1f} kHz)"
        )

    def _on_contact_activated(self, contact_id: str) -> None:
        if self._scanning or self._drone_active:
            return
        contact = self._find_contact(contact_id)
        if contact is None:
            return
        if contact.device_id != self.selected_id:
            self._select_device(contact.device_id)
        session = self.sessions.get(contact.device_id)
        if session is None:
            return
        offset = contact.freq_hz - session.config.center_freq
        max_offset = session.config.sample_rate * 0.48
        if abs(offset) > max_offset:
            # Contact is outside the current capture; retune the LO to it.
            new_vfo = replace(session.vfo, offset_hz=0.0)
            self._apply_center(contact.freq_hz, new_vfo, reset=True)
            session = self.sessions.get(contact.device_id)
            if session is None:
                return
            offset = 0.0
        mode = session.vfo.mode
        bw = session.vfo.bandwidth_hz
        if contact.type.value in ("FM", "BROADCAST"):
            mode = "FM"
            bw = max(120e3, contact.bw_hz * 1.5)
        elif contact.type.value == "AM":
            mode = "AM"
            bw = max(8e3, contact.bw_hz * 1.5)
        elif contact.type.value == "SSB":
            mode = "SSB"
            bw = max(2.4e3, contact.bw_hz * 1.5)
        elif contact.type.value == "CW":
            mode = "CW"
            bw = max(0.6e3, contact.bw_hz * 1.5)
        new_vfo = VFOConfig(
            offset_hz=offset,
            mode=mode,
            bandwidth_hz=min(500e3, bw),
            volume=session.vfo.volume,
            squelch_db=session.vfo.squelch_db,
            active=session.vfo.active,
        )
        self.vfo_panel.set_context(
            session.config.center_freq, session.config.sample_rate, new_vfo
        )
        session.set_vfo(new_vfo)
        self.status_label.setText(
            f"Настроено: {format_freq(contact.freq_hz)}  {contact.type.ru}"
        )

    def _find_contact(self, contact_id: str) -> Contact | None:
        for contacts in self.contacts_by_device.values():
            if contact_id in contacts:
                return contacts[contact_id]
        return None

    def _mark_known(self, contact_id: str) -> None:
        contact = self._find_contact(contact_id)
        if contact is None:
            return
        session = self.sessions.get(contact.device_id)
        if session is None:
            return
        session.mark_known(contact_id)
        contact.known = True
        self._refresh_contacts()
        self.status_label.setText(f"В фон: {format_freq(contact.freq_hz)}")

    def _forget_contact(self, contact_id: str) -> None:
        contact = self._find_contact(contact_id)
        if contact is None:
            return
        session = self.sessions.get(contact.device_id)
        if session is None:
            return
        session.forget(contact_id)
        contact.known = False
        self._refresh_contacts()
        self.status_label.setText(f"Забыт: {format_freq(contact.freq_hz)}")

    # -------------------------------------------------------------------- receiver
    def _on_center_spin(self, value_mhz: float) -> None:
        if (self._guard or self.selected_id is None
                or self._scanning or self._drone_active):
            return
        session = self.sessions[self.selected_id]
        old_abs = session.config.center_freq + session.vfo.offset_hz
        new_center = value_mhz * 1e6
        offset = old_abs - new_center
        offset = max(-session.config.sample_rate * 0.48,
                     min(session.config.sample_rate * 0.48, offset))
        vfo = replace(session.vfo, offset_hz=offset)
        self._apply_center(new_center, vfo, reset=True)

    def _apply_center(self, center: float, vfo: VFOConfig,
                      reset: bool = True) -> None:
        if self.selected_id is None or self._scanning or self._drone_active:
            return
        self._await_center = None
        session = self.sessions[self.selected_id]
        session.set_center_freq(center)
        session.set_vfo(vfo)
        self._guard = True
        try:
            self.center_spin.setValue(center / 1e6)
        finally:
            self._guard = False
        self.vfo_panel.set_context(center, session.config.sample_rate, vfo)
        if reset:
            session.reset_background()
            self.contacts_by_device[self.selected_id] = {}
            self.waterfall.clear()
            self._refresh_contacts()
        if not in_stock_pluto_range(center):
            self.status_label.setText(
                f"{format_freq(center)} вне паспортного диапазона Pluto"
            )
            self.status_label.setStyleSheet("color:#facc15;")
        else:
            self.status_label.setText(f"LO: {format_freq(center)}")

    def _on_fs_combo(self, _index: int) -> None:
        if (self._guard or self.selected_id is None
                or self._scanning or self._drone_active):
            return
        fs = float(self.fs_combo.currentData())
        session = self.sessions[self.selected_id]
        session.set_sample_rate(fs)
        max_offset = fs * 0.48
        offset = max(-max_offset, min(max_offset, session.vfo.offset_hz))
        vfo = replace(session.vfo, offset_hz=offset)
        session.set_vfo(vfo)
        self.vfo_panel.set_context(session.config.center_freq, fs, vfo)
        session.reset_background()
        self.contacts_by_device[self.selected_id] = {}
        self.waterfall.clear()
        self._refresh_contacts()
        self.status_label.setText(f"Полоса: {fs / 1e6:.3f} MS/s")

    def _on_gain(self, value: int) -> None:
        self.gain_label.setText(f"{value} dB")
        if (self._guard or self.selected_id is None
                or self._scanning or self._drone_active):
            return
        self.sessions[self.selected_id].set_gain(float(value))

    def _on_threshold(self, value: float) -> None:
        if (self._guard or self.selected_id is None
                or self._scanning or self._drone_active):
            return
        self.sessions[self.selected_id].set_threshold(value)

    def _reset_background(self) -> None:
        if self.selected_id is None or self._scanning or self._drone_active:
            return
        session = self.sessions[self.selected_id]
        session.reset_background()
        self.contacts_by_device[self.selected_id] = {}
        self.waterfall.clear()
        self.spectrum.baseline_curve.setData([], [])
        self._refresh_contacts()
        self.cal_label.setText("Калибровка: 0%")
        self.cal_label.setStyleSheet("color:#facc15; padding:0 8px;")
        self.status_label.setText("Фон сброшен, идёт калибровка")
        self.status_label.setStyleSheet("color:#d7e2f0;")

    # ---------------------------------------------------------------------- scan
    def start_scan(self) -> None:
        """Public entry point used by the CLI and tests."""
        self._start_scan()

    def _start_scan(self) -> None:
        if self._drone_active:
            self._stop_drone()
        if self._scanning:
            return
        if self.selected_id is None:
            self.status_label.setText("Выберите устройство для сканирования")
            return
        session = self.sessions.get(self.selected_id)
        if session is None:
            self.status_label.setText("Устройство не найдено")
            return
        start, end, step = self.scan_panel.values()
        if end <= start:
            self.scan_panel.fail(
                "Конец сканирования должен быть больше начала."
            )
            return
        if step <= 0:
            self.scan_panel.fail("Шаг сканирования должен быть положительным.")
            return
        if step > session.config.sample_rate * 0.95:
            self.status_label.setToolTip(
                "Шаг больше полосы захвата — между шагами возможны пропуски. "
                f"Рекомендуется не больше "
                f"{session.config.sample_rate / 1e3:.0f} кГц."
            )
        else:
            self.status_label.setToolTip("")

        previous = None
        if self._scan_compare_override:
            candidate = Path(self._scan_compare_override).expanduser()
            if candidate.is_file():
                previous = candidate
            else:
                log.warning(
                    "compare background not found: %s", candidate
                )
        if previous is None:
            previous = find_latest_background("scan_logs")
        self._scan_audio_was_enabled = self.audio_enabled
        self.audio_enabled = False
        self.audio_btn.setEnabled(False)
        if self._scan_audio_was_enabled:
            self.audio_label.setText("Аудио: пауза (скан)")
            self.audio_label.setStyleSheet("color:#8fa6c0; padding:0 8px;")
        try:
            session.set_audio_enabled(False)
            self.audio_sink.clear()
        except Exception:
            pass

        controller = ScanController(
            session,
            start_hz=start,
            end_hz=end,
            step_hz=step,
            threshold_db=float(self.threshold_spin.value()),
            compare_to=previous,
            auto_compare=previous is not None,
            parent=self,
        )
        controller.started.connect(self._on_scan_started)
        controller.progress.connect(self.scan_panel.update_progress)
        controller.step_ready.connect(self._on_scan_step)
        controller.finished.connect(self._on_scan_finished)
        controller.stopped.connect(self._on_scan_stopped)
        controller.failed.connect(self._on_scan_failed)
        controller.compare_ready.connect(self._on_scan_compare)

        self._scan_controller = controller
        self._scanning = True
        self.right_tabs.setCurrentWidget(self.scan_panel)
        self.rx_group.setEnabled(False)
        self.vfo_panel.setEnabled(False)
        self.band_group.setEnabled(False)
        self.scan_panel.set_can_compare(False)
        self.status_label.setText(
            f"Сканирование {format_freq(start)} – {format_freq(end)}…"
        )
        self.status_label.setStyleSheet("color:#22d3ee;")
        if not controller.start():
            # ``failed`` is emitted synchronously and the slot already
            # restored the UI and showed the reason.
            return

    def _stop_scan(self) -> None:
        if self._scan_controller is None:
            return
        self.status_label.setText("Останавливаю сканирование…")
        self.scan_panel.status.setText("Останавливаю сканирование…")
        self._scan_controller.stop()

    def _on_scan_started(self, total: int, start: float, end: float) -> None:
        self.scan_panel.begin_scan(total, start, end)
        self.status_label.setText(
            f"Сканирование: {total} шагов, "
            f"{format_freq(start)} – {format_freq(end)}"
        )

    def _on_scan_step(self, record: dict) -> None:
        self.scan_panel.update_step(record)
        if record.get("status") != "ok":
            self.status_label.setText(
                f"Шаг {record.get('step_index', 0)} пропущен: "
                f"{record.get('status')}"
            )

    def _on_scan_finished(self, result: dict, path: str) -> None:
        self._last_scan_bundle = path
        self.scan_panel.finish_scan(result, stopped=False)
        self._end_scan_ui()
        new = result.get("new_contacts")
        if new is not None:
            suffix = f" · новых контактов: {new}"
        elif result.get("compare_skipped"):
            suffix = " · сравнение с фоном пропущено"
        else:
            suffix = ""
        self.status_label.setStyleSheet("color:#4ade80;")
        self.status_label.setText(
            f"Скан завершён: шагов {result.get('steps_completed', 0)}, "
            f"пиков {result.get('peak_count', 0)}{suffix}"
        )
        self.scan_done.emit(result)

    def _on_scan_stopped(self, result: dict, path: str) -> None:
        self._last_scan_bundle = path
        self.scan_panel.finish_scan(result, stopped=True)
        self._end_scan_ui()
        self.status_label.setStyleSheet("color:#facc15;")
        self.status_label.setText(
            f"Скан остановлен: сохранено "
            f"{result.get('steps_completed', 0)} шагов"
        )
        self.scan_done.emit(result)

    def _on_scan_failed(self, message: str) -> None:
        self.scan_panel.fail(message)
        self._end_scan_ui()
        self.status_label.setStyleSheet("color:#f87171;")
        self.status_label.setText(message)
        self.status_label.setToolTip(message)
        self.scan_done.emit({"failure": message, "path": None})

    def _on_scan_compare(self, report: dict, path: str) -> None:
        self.scan_panel.show_compare(report, path)
        counts = report.get("counts", {})
        if counts.get("new"):
            self.status_label.setStyleSheet("color:#f87171;")
            self.status_label.setText(
                f"Новых контактов: {counts['new']} · "
                f"отчёт {Path(path).name}"
            )
        else:
            self.status_label.setStyleSheet("color:#4ade80;")
            self.status_label.setText(report.get("summary_ru", "Сравнение готово"))

    def _end_scan_ui(self) -> None:
        controller, self._scan_controller = self._scan_controller, None
        self._scanning = False
        if controller is not None:
            controller.deleteLater()
        has_device = self.selected_id is not None
        self.rx_group.setEnabled(has_device)
        self.band_group.setEnabled(has_device)
        self.vfo_panel.setEnabled(has_device)
        self.audio_btn.setEnabled(has_device)
        session = self.sessions.get(self.selected_id) if has_device else None
        if session is not None:
            self._guard = True
            try:
                self.center_spin.setValue(session.config.center_freq / 1e6)
            finally:
                self._guard = False
            self.vfo_panel.set_context(
                session.config.center_freq,
                session.config.sample_rate,
                session.vfo,
            )
            session.set_audio_enabled(self._scan_audio_was_enabled)
        self.audio_enabled = self._scan_audio_was_enabled
        if self._scan_audio_was_enabled and has_device:
            self.audio_label.setText("Аудио вкл")
            self.audio_label.setStyleSheet("color:#4ade80; padding:0 8px;")
        else:
            self.audio_label.setText("Аудио выкл")
            self.audio_label.setStyleSheet("color:#8fa6c0; padding:0 8px;")
        self._update_controls()
        self.scan_panel.set_can_compare(self._last_scan_bundle is not None)

    # ----------------------------------------------------------------- drone
    def start_drone(self) -> None:
        """Public entry point used by the CLI and tests."""
        self._start_drone()

    def stop_drone(self) -> None:
        self._stop_drone()

    def _start_drone(self) -> None:
        if self._drone_active:
            return
        if self._scanning:
            self._stop_scan()
        if not self.sessions:
            self._fail_drone("Нет устройств. Добавьте Pluto+ или симулятор.")
            return
        if self.drone_panel.use_all_devices():
            sessions = list(self.sessions.values())
        else:
            session = self.sessions.get(self.selected_id) if self.selected_id else None
            if session is None:
                self._fail_drone("Выберите устройство для мониторинга.")
                return
            sessions = [session]
        sessions = [
            session for session in sessions
            if session.worker.isRunning()
        ]
        if not sessions:
            self._fail_drone("Нет запущенных устройств для мониторинга.")
            return
        bands = selected_bands(self.drone_panel.selected_band_keys())
        if not bands:
            self._fail_drone("Выберите хотя бы одну полосу.")
            return
        if (any(band.requires_extended for band in bands)
                and not self.drone_panel.extended_allowed()):
            self._fail_drone(
                "Для 5.8 ГГц включите «Разрешить 5.8 ГГц (Pluto+)»."
            )
            return

        sample_rate = self.drone_panel.sample_rate()
        usb_plutos = sum(
            1 for session in sessions
            if session.config.kind == "pluto"
            and session.config.uri.startswith("usb:")
        )
        rate_note = ""
        if usb_plutos >= 2:
            if (not self.drone_panel.allow_high_usb()
                    and sample_rate > 10.24e6):
                # Safe default for two radios on one USB 2.0 bus.  The user
                # can explicitly opt into 20.48/30.72 above.
                sample_rate = 10.24e6
                index = self.drone_panel.rate_combo.findData(sample_rate)
                if index >= 0:
                    self.drone_panel.rate_combo.setCurrentIndex(index)
                rate_note = (
                    " · 2 USB: стабильные 10.24 MS/s (включите "
                    "«Разрешить 20.48/30.72…» для скорости)"
                )
            elif (self.drone_panel.allow_high_usb()
                    and sample_rate > 10.24e6):
                rate_note = (
                    f" · 2 USB: {sample_rate / 1e6:.2f} MS/s — "
                    "риск перегрузки USB"
                )
        chunks = chunks_for_bands(bands, sample_rate)
        manager = DroneMonitorManager(self)
        manager.observation.connect(self._on_drone_observation)
        manager.event_new.connect(
            lambda event: self._on_drone_event(event, True)
        )
        manager.event_updated.connect(
            lambda event: self._on_drone_event(event, False)
        )
        manager.alarm.connect(self._on_drone_alarm)
        manager.status.connect(self._on_drone_status)
        manager.device_status.connect(self.drone_panel.update_device_status)
        manager.finished.connect(self._on_drone_finished)
        manager.error.connect(self._on_drone_error)

        devices = [
            (session.config.device_id, session.config.name)
            for session in sessions
        ]
        self._drone_manager = manager
        self._drone_active = True
        self._pre_drone_frame = self._last_frame
        self._drone_audio_was_enabled = self.audio_enabled
        self.right_tabs.setCurrentWidget(self.drone_panel)
        self.rx_group.setEnabled(False)
        self.band_group.setEnabled(False)
        self.vfo_panel.setEnabled(False)
        self.audio_btn.setEnabled(False)
        self.scan_panel.set_device_enabled(False)
        self.scan_panel.set_can_compare(False)
        if self._drone_audio_was_enabled:
            self.audio_label.setText("Аудио: пауза (дрон-монитор)")
            self.audio_label.setStyleSheet("color:#8fa6c0; padding:0 8px;")
        self.drone_panel.begin_monitor(
            devices, len(bands), len(chunks)
        )
        self.status_label.setStyleSheet("color:#f472b6;")
        self.status_label.setText(
            f"Дрон-монитор: {len(bands)} полос, {len(chunks)} кусков"
            f"{rate_note}…"
        )
        if not manager.start(
            sessions,
            bands,
            sample_rate=sample_rate,
            dwell_ms=self.drone_panel.dwell_ms(),
            threshold_db=self.drone_panel.threshold_db(),
            min_alarm_hits=self.drone_panel.alarm_hits(),
            min_alarm_conf=self.drone_panel.alarm_confidence(),
            record_iq=self.drone_panel.record_iq(),
            whitelist=self.drone_whitelist,
            background_store=self.drone_background,
            use_all_devices=True,
        ):
            self._drone_manager = None
            manager.deleteLater()
            self._end_drone_ui()
            self._fail_drone("Не удалось запустить дрон-монитор.")

    def _fail_drone(self, message: str) -> None:
        self.drone_panel.fail(message)
        self.status_label.setStyleSheet("color:#f87171;")
        self.status_label.setText(message)
        self.drone_done.emit(
            {"failure": message, "events_total": 0,
             "events_active": 0, "events_drone_like": 0},
            "",
        )

    def _stop_drone(self) -> None:
        manager = self._drone_manager
        if manager is None:
            return
        self.drone_panel.status.setText("Останавливаю мониторинг…")
        manager.stop()

    def _on_drone_observation(self, obs) -> None:
        self.drone_panel.update_observation(obs)

    def _open_drone_event(self, event_id: str) -> None:
        event = self.drone_panel.find_event(event_id)
        if event is None:
            return
        dialog = DroneEventDialog(
            event, self,
            store=self.signature_store,
            whitelist=self.drone_whitelist,
        )
        dialog.exec()

    def _open_whitelist(self) -> None:
        dialog = WhitelistDialog(self.drone_whitelist, self)
        dialog.exec()
        self.drone_panel.refresh_events()

    def _on_drone_event(self, event, is_new: bool) -> None:
        self.drone_panel.add_event(event, is_new)
        if (is_new and event.drone_like
                and not self.drone_panel.is_confirmed(event)):
            self.status_label.setStyleSheet("color:#fb923c;")
            self.status_label.setText(
                f"Кандидат: {event.class_ru} · "
                f"{format_freq(event.freq_hz)} · ждём подтверждения"
            )

    def _on_drone_alarm(self, event) -> None:
        QApplication.beep()
        self.drone_panel.show_alarm(event)
        self.status_label.setStyleSheet("color:#f87171;")
        self.status_label.setText(
            f"ВОЗМОЖНЫЙ ДРОН: {event.band_name} · {event.class_ru} · "
            f"{format_freq(event.freq_hz)}"
        )

    def _on_drone_status(self, text: str) -> None:
        self.drone_panel.update_status(text)

    def _on_drone_error(self, message: str) -> None:
        self.drone_panel.status.setStyleSheet(
            "color:#f87171; font-size:11px;"
        )
        self.drone_panel.status.setText(message)
        self.status_label.setStyleSheet("color:#f87171;")
        self.status_label.setText(message)

    def _on_drone_finished(self, summary: dict, path: str) -> None:
        self.drone_panel.finish_monitor(summary, path)
        self._end_drone_ui()
        total = int(summary.get("events_total", 0))
        alarms = int(summary.get(
            "alarms", summary.get("events_drone_like", 0)
        ))
        failure = summary.get("failure")
        if failure:
            self.status_label.setStyleSheet("color:#f87171;")
            self.status_label.setText(f"Дрон-монитор: {failure}")
        else:
            self.status_label.setStyleSheet("color:#4ade80;")
            self.status_label.setText(
                f"Дрон-монитор остановлен: событий {total}, "
                f"подтверждённых тревог {alarms}"
            )
        manager, self._drone_manager = self._drone_manager, None
        if manager is not None:
            manager.deleteLater()
        self.drone_done.emit(summary, path)

    def _end_drone_ui(self) -> None:
        self._drone_active = False
        has = self.selected_id is not None
        self.rx_group.setEnabled(has)
        self.band_group.setEnabled(has)
        self.vfo_panel.setEnabled(has)
        self.audio_btn.setEnabled(has)
        session = self.sessions.get(self.selected_id) if has else None
        if session is not None:
            self._await_center = float(session.config.center_freq)
            self._guard = True
            try:
                self.center_spin.setValue(session.config.center_freq / 1e6)
                self._set_fs_combo(session.config.sample_rate)
            finally:
                self._guard = False
            self.vfo_panel.set_context(
                session.config.center_freq,
                session.config.sample_rate,
                session.vfo,
            )
            if (self._last_frame is not None
                    and abs(self._last_frame.center_freq
                            - session.config.center_freq) > 1.0e6):
                # The last monitored chunk was on a different band.  Restore
                # the frame that was on screen before the monitor started
                # instead of leaving a 5.8 GHz chunk under a 433 MHz label.
                pre = self._pre_drone_frame
                if (pre is not None
                        and abs(pre.center_freq
                                - session.config.center_freq) <= 1.0e6):
                    self._last_frame = pre
                    self.spectrum.update_frame(
                        pre,
                        session.config.center_freq + session.vfo.offset_hz,
                    )
                    self.waterfall.update_frame(pre)
                else:
                    self.spectrum.clear()
                    self.waterfall.clear()
                    f0 = (session.config.center_freq
                          - session.config.sample_rate / 2.0) / 1e6
                    f1 = (session.config.center_freq
                          + session.config.sample_rate / 2.0) / 1e6
                    self.spectrum.plot.setXRange(f0, f1, padding=0)
                    self.waterfall.plot.setXRange(f0, f1, padding=0)
                    self._last_frame = None
        if self._drone_audio_was_enabled and has:
            self.audio_label.setText("Аудио вкл")
            self.audio_label.setStyleSheet("color:#4ade80; padding:0 8px;")
        else:
            self.audio_label.setText("Аудио выкл")
            self.audio_label.setStyleSheet("color:#8fa6c0; padding:0 8px;")
        self._pre_drone_frame = None
        self._update_controls()
        self.scan_panel.set_can_compare(self._last_scan_bundle is not None)

    def _compare_scan(self) -> None:
        if not self._last_scan_bundle:
            self.status_label.setStyleSheet("color:#facc15;")
            self.status_label.setText(
                "Сначала выполните скан: сравнивать пока нечего."
            )
            return
        current = Path(self._last_scan_bundle)
        if not current.exists():
            self.status_label.setText("Файл последнего скана не найден.")
            return
        start_dir = (
            current.parent.parent
            if current.parent.name.startswith("scan_")
            else current.parent
        )
        filename, _ = QFileDialog.getOpenFileName(
            self,
            "Выберите сохранённый фон",
            str(start_dir),
            "Сканы JSON (background.json scan_background_*.json);;JSON (*.json)",
        )
        if not filename:
            return
        try:
            report = compare_background_files(filename, current)
        except Exception as exc:
            log.warning("manual comparison failed: %s", exc)
            self.status_label.setStyleSheet("color:#f87171;")
            self.status_label.setText(f"Сравнение не удалось: {exc}")
            return
        from ..scanner.compare import save_report

        report_path = save_report(
            report, current.parent / "compare_manual.json"
        )
        self._on_scan_compare(report, str(report_path))

    def _inject_signal(self) -> None:
        if self.selected_id is None:
            return
        session = self.sessions[self.selected_id]
        if session.config.kind != "sim":
            self.status_label.setText("Впрыск доступен только симулятору")
            return
        offset = session.vfo.offset_hz
        session.inject_signal(
            offset_hz=offset, kind="carrier",
            amp_db=-38.0, duration=12.0,
        )
        self.status_label.setText(
            f"Впрыснут сигнал на VFO {format_freq(session.config.center_freq + offset)}"
        )

    def _tune_band(self) -> None:
        if self.selected_id is None or self._scanning or self._drone_active:
            return
        freq = float(self.band_combo.currentData())
        session = self.sessions[self.selected_id]
        half = session.config.sample_rate * 0.48
        if abs(freq - session.config.center_freq) <= half:
            self.vfo_panel.set_offset(freq - session.config.center_freq)
            self.status_label.setText(f"VFO: {format_freq(freq)} (LO не менялся)")
        else:
            vfo = replace(session.vfo, offset_hz=0.0)
            self._apply_center(freq, vfo, reset=True)
            self.status_label.setText(f"LO: {format_freq(freq)}, фон пересобирается")

    # --------------------------------------------------------------------- smoke
    def inject_test_signal(self) -> None:
        if self.selected_id is None:
            return
        session = self.sessions[self.selected_id]
        if session.config.kind == "sim":
            session.inject_signal(offset_hz=120e3, kind="carrier",
                                  amp_db=-38.0, duration=20.0)
            session.inject_signal(offset_hz=-170e3, kind="wideband",
                                  bw_hz=60e3, amp_db=-46.0, duration=20.0)
            session.inject_signal(offset_hz=260e3, kind="pulsed",
                                  bw_hz=40e3, amp_db=-42.0, duration=20.0)

    def capture_screenshot(self, path: str | Path) -> str:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        pixmap = self.grab()
        ok = pixmap.save(str(path))
        print(f"SCREENSHOT {'OK' if ok else 'FAILED'}: {path.resolve()}", flush=True)
        return str(path.resolve())

    def closeEvent(self, event: QCloseEvent) -> None:
        self.shutdown()
        super().closeEvent(event)

    def shutdown(self) -> None:
        if self._shutting_down:
            return
        self._shutting_down = True
        if self._drone_manager is not None:
            try:
                self._drone_manager.stop()
            except Exception:
                pass
            self._drone_manager = None
        if self._scan_controller is not None:
            try:
                self._scan_controller.stop()
            except Exception:
                pass
        for session in list(self.sessions.values()):
            try:
                session.stop()
            except Exception:
                pass
        try:
            self.audio_sink.stop()
        except Exception:
            pass
        try:
            self.store.save()
        except Exception:
            pass
