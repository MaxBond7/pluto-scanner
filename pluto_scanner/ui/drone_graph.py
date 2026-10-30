"""Live spectrum plot for the drone monitor's current chunk."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..drone.features import DroneObservation
from ..drone.bands import MonitorChunk


class DroneGraph(QWidget):
    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(2)

        self.plot = pg.PlotWidget(background="#0a0f1e")
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.setLabel("bottom", "Частота", units="MHz")
        self.plot.setLabel("left", "Мощность", units="dBFS")
        self.plot.setMouseEnabled(x=True, y=True)
        self.plot.getAxis("left").setWidth(56)
        self.plot.getAxis("bottom").setHeight(26)
        layout.addWidget(self.plot, 1)

        self.curve = self.plot.plot([], [], pen=pg.mkPen("#22d3ee", width=1.2))
        self.peak_scatter = pg.ScatterPlotItem(
            size=9, symbol="o",
            brush=pg.mkBrush(248, 113, 113, 210),
            pen=pg.mkPen("#fecaca"),
        )
        self.plot.addItem(self.peak_scatter)
        self.peak_line = pg.InfiniteLine(
            pos=0, angle=90, movable=False,
            pen=pg.mkPen("#f87171", width=1, style=Qt.PenStyle.DotLine),
        )
        self.plot.addItem(self.peak_line)
        self.peak_line.hide()

        self.hint = QLabel("Ожидание данных…")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        layout.addWidget(self.hint)

        self._chunk: MonitorChunk | None = None
        self._last_range: tuple[float, float] | None = None

    def configure_chunk(self, chunk: MonitorChunk) -> None:
        self._chunk = chunk
        self.curve.setData([], [])
        self.peak_scatter.setData([], [])
        self.peak_line.hide()
        self._last_range = None
        self.plot.setXRange(
            chunk.start_hz / 1e6, chunk.end_hz / 1e6, padding=0
        )
        self.plot.setYRange(-125, -20, padding=0)
        self.hint.setText(
            f"{chunk.band.name} · {chunk.index + 1}/{chunk.total} · "
            f"{chunk.center_hz / 1e6:.3f} МГц"
        )

    def add_observation(self, obs: DroneObservation) -> None:
        if not obs.spectrum_freqs_hz:
            return
        x = np.asarray(obs.spectrum_freqs_hz, dtype=np.float64) / 1e6
        y = np.asarray(obs.spectrum_db, dtype=np.float64)
        if x.size != y.size or x.size < 2:
            return
        self.curve.setData(x, y)
        self.peak_scatter.setData([obs.peak_freq_hz / 1e6], [obs.peak_db])
        self.peak_line.setPos(obs.peak_freq_hz / 1e6)
        if obs.class_key not in ("QUIET",):
            self.peak_line.show()

        lo = float(np.percentile(y, 3.0)) - 6.0
        hi = float(np.percentile(y, 99.5)) + 6.0
        if hi - lo < 20.0:
            mid = (hi + lo) / 2.0
            lo, hi = mid - 10.0, mid + 10.0
        key = (round(lo, 1), round(hi, 1))
        if key != self._last_range:
            self._last_range = key
            self.plot.setYRange(lo, hi, padding=0)

        status = "тревога" if obs.drone_like else obs.class_ru
        self.hint.setText(
            f"{obs.band_name} · {obs.class_key} · {status} · "
            f"SNR {obs.snr_db:.1f} dB · Ш {obs.occupied_bw_hz / 1e6:.2f} МГц"
        )

    def clear(self) -> None:
        self._chunk = None
        self.curve.setData([], [])
        self.peak_scatter.setData([], [])
        self.peak_line.hide()
        self._last_range = None
        self.plot.setXRange(2400, 2484, padding=0)
        self.plot.setYRange(-125, -20, padding=0)
        self.hint.setText("Монитор остановлен.")

    def mark_finished(self, path: str | None = None) -> None:
        suffix = f" · журнал: {path}" if path else ""
        self.hint.setText(f"Мониторинг завершён{suffix}")
