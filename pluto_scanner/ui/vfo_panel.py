"""Software VFO controls.

Wobble is implemented here as a 30 Hz animation of the VFO offset.  The LO
is never retuned by this widget; only the mixer inside Demodulator moves.
"""
from __future__ import annotations

import math

from PySide6.QtCore import Qt, QTimer, Signal
from PySide6.QtWidgets import (
    QCheckBox,
    QComboBox,
    QDoubleSpinBox,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QPushButton,
    QSlider,
    QVBoxLayout,
    QWidget,
)

from ..config import format_freq
from ..model import VFOConfig


class VFOPanel(QGroupBox):
    vfo_changed = Signal(object)

    _DEFAULT_BW = {"FM": 200.0, "AM": 10.0, "SSB": 3.0, "CW": 0.8}

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__("VFO / демодулятор", parent)
        self._center = 433.92e6
        self._span = 1.024e6
        self._offset = 0.0
        self._vfo = VFOConfig()
        self._loading = False
        self._wobble_base = 0.0
        self._wobble_phase = 0.0
        self._timer = QTimer(self)
        self._timer.setInterval(33)
        self._timer.timeout.connect(self._wobble_tick)

        layout = QVBoxLayout(self)
        layout.setSpacing(5)

        self.freq_spin = QDoubleSpinBox()
        self.freq_spin.setDecimals(6)
        self.freq_spin.setSingleStep(0.001)
        self.freq_spin.setSuffix(" MHz")
        self.freq_spin.setKeyboardTracking(False)
        self.freq_spin.setMinimumWidth(160)
        self.freq_spin.valueChanged.connect(self._on_freq_spin)
        layout.addWidget(self.freq_spin)

        self.offset_label = QLabel()
        self.offset_label.setStyleSheet(
            "color:#64748b; font-size:10px; font-family:Consolas,monospace;"
        )
        layout.addWidget(self.offset_label)

        row = QHBoxLayout()
        row.addWidget(QLabel("Режим"))
        self.mode_combo = QComboBox()
        self.mode_combo.addItems(["FM", "AM", "SSB", "CW"])
        self.mode_combo.currentTextChanged.connect(self._on_mode)
        row.addWidget(self.mode_combo, 1)
        row.addWidget(QLabel("Полоса"))
        self.bw_spin = QDoubleSpinBox()
        self.bw_spin.setRange(0.1, 500.0)
        self.bw_spin.setDecimals(1)
        self.bw_spin.setSuffix(" kHz")
        self.bw_spin.setKeyboardTracking(False)
        self.bw_spin.valueChanged.connect(self._on_bw)
        row.addWidget(self.bw_spin, 1)
        layout.addLayout(row)

        self.active_check = QCheckBox("Демодуляция и звук")
        self.active_check.setChecked(True)
        self.active_check.toggled.connect(self._on_active)
        layout.addWidget(self.active_check)

        vol_row = QHBoxLayout()
        vol_row.addWidget(QLabel("Громк."))
        self.volume = QSlider(Qt.Orientation.Horizontal)
        self.volume.setRange(0, 100)
        self.volume.setValue(70)
        self.volume.valueChanged.connect(self._on_volume)
        self.volume_label = QLabel("70")
        self.volume_label.setMinimumWidth(24)
        vol_row.addWidget(self.volume, 1)
        vol_row.addWidget(self.volume_label)
        layout.addLayout(vol_row)

        sq_row = QHBoxLayout()
        sq_row.addWidget(QLabel("Шумоп."))
        self.squelch = QSlider(Qt.Orientation.Horizontal)
        self.squelch.setRange(-120, -30)
        self.squelch.setValue(-85)
        self.squelch.valueChanged.connect(self._on_squelch)
        self.squelch_label = QLabel("-85 dB")
        self.squelch_label.setMinimumWidth(50)
        sq_row.addWidget(self.squelch, 1)
        sq_row.addWidget(self.squelch_label)
        layout.addLayout(sq_row)

        steps = QGridLayout()
        steps.setSpacing(3)
        for i, (text, delta) in enumerate((
            ("−100k", -100e3), ("−10k", -10e3), ("−1k", -1e3),
            ("+1k", 1e3), ("+10k", 10e3), ("+100k", 100e3),
        )):
            btn = QPushButton(text)
            btn.clicked.connect(lambda _=False, d=delta: self._nudge(d))
            steps.addWidget(btn, 0 if i < 3 else 1, i % 3)
        layout.addLayout(steps)

        self.wobble_check = QCheckBox("Качание (wobble)")
        self.wobble_check.toggled.connect(self._on_wobble_toggled)
        layout.addWidget(self.wobble_check)

        wob = QHBoxLayout()
        wob.addWidget(QLabel("Ширина"))
        self.wobble_width = QDoubleSpinBox()
        self.wobble_width.setRange(0.1, 500.0)
        self.wobble_width.setDecimals(1)
        self.wobble_width.setSuffix(" kHz")
        self.wobble_width.setValue(50.0)
        wob.addWidget(self.wobble_width, 1)
        wob.addWidget(QLabel("Скорость"))
        self.wobble_speed = QDoubleSpinBox()
        self.wobble_speed.setRange(0.02, 5.0)
        self.wobble_speed.setDecimals(2)
        self.wobble_speed.setSuffix(" Hz")
        self.wobble_speed.setValue(0.4)
        wob.addWidget(self.wobble_speed, 1)
        layout.addLayout(wob)

        hint = QLabel(
            "VFO двигается в цифре; LO не перестраивается. "
            "Клик по спектру/водопаду ставит VFO."
        )
        hint.setWordWrap(True)
        hint.setStyleSheet("color:#64748b; font-size:10px;")
        layout.addWidget(hint)

        self.set_context(self._center, self._span, VFOConfig())

    # ------------------------------------------------------------------ context
    def set_context(self, center_freq: float, span_hz: float,
                    vfo: VFOConfig) -> None:
        self._loading = True
        try:
            self._center = float(center_freq)
            self._span = max(1e3, float(span_hz))
            max_offset = self._span * 0.48
            self._offset = float(max(-max_offset, min(max_offset, vfo.offset_hz)))
            lo = (self._center - max_offset) / 1e6
            hi = (self._center + max_offset) / 1e6
            self.freq_spin.setRange(lo, hi)
            self.freq_spin.setValue((self._center + self._offset) / 1e6)
            self.mode_combo.setCurrentText(vfo.mode if vfo.mode in ("FM", "AM", "SSB", "CW") else "FM")
            self.bw_spin.setValue(max(0.1, vfo.bandwidth_hz / 1e3))
            self.volume.setValue(int(round(vfo.volume * 100)))
            self.squelch.setValue(int(round(vfo.squelch_db)))
            self.active_check.setChecked(bool(vfo.active))
            self._vfo = vfo.copy()
            self._vfo.offset_hz = self._offset
            self._wobble_base = self._offset
            self._update_labels()
        finally:
            self._loading = False

    def set_offset(self, offset_hz: float, emit: bool = True) -> None:
        max_offset = self._span * 0.48
        offset = float(max(-max_offset, min(max_offset, offset_hz)))
        self._offset = offset
        self._loading = True
        try:
            self.freq_spin.setValue((self._center + offset) / 1e6)
            self._update_labels()
        finally:
            self._loading = False
        if self.wobble_check.isChecked():
            self._wobble_base = offset
            self._wobble_phase = 0.0
        if emit:
            self._emit()

    def get_vfo(self) -> VFOConfig:
        return self._read_vfo()

    def set_enabled(self, enabled: bool) -> None:
        self.setEnabled(enabled)

    # --------------------------------------------------------------------- read
    def _read_vfo(self) -> VFOConfig:
        return VFOConfig(
            offset_hz=float(self._offset),
            mode=self.mode_combo.currentText(),
            bandwidth_hz=float(self.bw_spin.value()) * 1e3,
            volume=float(self.volume.value()) / 100.0,
            squelch_db=float(self.squelch.value()),
            active=self.active_check.isChecked(),
        )

    def _emit(self) -> None:
        if self._loading:
            return
        self._vfo = self._read_vfo()
        self.vfo_changed.emit(self._vfo)

    def _update_labels(self) -> None:
        self.offset_label.setText(
            f"LO {format_freq(self._center)}   ·   "
            f"{self._offset / 1e3:+.1f} kHz"
        )
        self.volume_label.setText(str(self.volume.value()))
        self.squelch_label.setText(f"{self.squelch.value()} dB")

    # ------------------------------------------------------------------ handlers
    def _on_freq_spin(self, value: float) -> None:
        if self._loading:
            return
        offset = value * 1e6 - self._center
        max_offset = self._span * 0.48
        self._offset = float(max(-max_offset, min(max_offset, offset)))
        if self.wobble_check.isChecked():
            self._wobble_base = self._offset
            self._wobble_phase = 0.0
        self._update_labels()
        self._emit()

    def _on_mode(self, mode: str) -> None:
        if self._loading:
            return
        self._loading = True
        try:
            self.bw_spin.setValue(self._DEFAULT_BW.get(mode, 50.0))
        finally:
            self._loading = False
        self._emit()

    def _on_bw(self, _value: float) -> None:
        self._emit()

    def _on_active(self, _checked: bool) -> None:
        self._emit()

    def _on_volume(self, _value: int) -> None:
        self._update_labels()
        self._emit()

    def _on_squelch(self, _value: int) -> None:
        self._update_labels()
        self._emit()

    def _nudge(self, delta_hz: float) -> None:
        if self.wobble_check.isChecked():
            self._wobble_base += delta_hz
            self._wobble_phase = 0.0
            self.set_offset(self._wobble_base)
        else:
            self.set_offset(self._offset + delta_hz)

    # ------------------------------------------------------------------- wobble
    def _on_wobble_toggled(self, checked: bool) -> None:
        if checked:
            self._wobble_base = self._offset
            self._wobble_phase = 0.0
            self._timer.start()
        else:
            self._timer.stop()

    def _wobble_tick(self) -> None:
        if not self.wobble_check.isChecked():
            return
        width = float(self.wobble_width.value()) * 1e3
        speed = float(self.wobble_speed.value())
        dt = self._timer.interval() / 1000.0
        self._wobble_phase += 2.0 * math.pi * speed * dt
        offset = self._wobble_base + math.sin(self._wobble_phase) * width / 2.0
        max_offset = self._span * 0.48
        offset = max(-max_offset, min(max_offset, offset))
        self._offset = offset
        self._loading = True
        try:
            self.freq_spin.setValue((self._center + offset) / 1e6)
            self._update_labels()
        finally:
            self._loading = False
        self._emit()
