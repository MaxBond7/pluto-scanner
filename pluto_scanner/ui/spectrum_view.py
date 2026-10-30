"""Live spectrum plot with detection markers and a software VFO line."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..model import SpectrumFrame


class SpectrumView(QWidget):
    frequency_clicked = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget(background="#0a0f1e")
        self.plot.setMenuEnabled(False)
        self.plot.showGrid(x=True, y=True, alpha=0.12)
        self.plot.setLabel("bottom", "Частота", units="MHz")
        self.plot.setLabel("left", "Мощность", units="dBFS")
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.getAxis("left").setWidth(58)
        self.plot.getAxis("bottom").setHeight(28)
        layout.addWidget(self.plot)

        self.curve = self.plot.plot(
            [], [], pen=pg.mkPen("#22d3ee", width=1.3), name="Live"
        )
        self.baseline_curve = self.plot.plot(
            [], [],
            pen=pg.mkPen("#64748b", width=1.0, style=Qt.PenStyle.DashLine),
            name="Background",
        )
        self.det_scatter = pg.ScatterPlotItem(
            size=8, symbol="t",
            brush=pg.mkBrush("#f59e0b"),
            pen=pg.mkPen("#fbbf24"),
        )
        self.plot.addItem(self.det_scatter)
        self.vfo_line = pg.InfiniteLine(
            pos=0, angle=90, movable=False,
            pen=pg.mkPen("#f472b6", width=2),
            label="VFO",
            labelOpts={"position": 0.96, "color": "#f472b6"},
        )
        self.plot.addItem(self.vfo_line)
        self.plot.setYRange(-125, -20, padding=0)
        self._labels: list[pg.TextItem] = []
        self._range_key: tuple | None = None
        self.plot.scene().sigMouseClicked.connect(self._mouse_clicked)

    def _mouse_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self.plot.sceneBoundingRect().contains(event.scenePos()):
            return
        point = self.plot.getViewBox().mapSceneToView(event.scenePos())
        self.frequency_clicked.emit(float(point.x()) * 1e6)

    def _clear_labels(self) -> None:
        for label in self._labels:
            self.plot.removeItem(label)
        self._labels.clear()

    def update_frame(self, frame: SpectrumFrame, vfo_abs_hz: float) -> None:
        if len(frame.freqs) == 0:
            return
        x = frame.freqs / 1e6
        self.curve.setData(x, frame.psd)
        if frame.baseline is not None:
            self.baseline_curve.setData(x, frame.baseline)
        else:
            self.baseline_curve.setData([], [])

        key = (round(float(x[0]), 3), round(float(x[-1]), 3))
        if key != self._range_key:
            self._range_key = key
            self.plot.setXRange(float(x[0]), float(x[-1]), padding=0)

        if frame.detections:
            xs = [d.freq_hz / 1e6 for d in frame.detections]
            ys = [d.peak_db for d in frame.detections]
            self.det_scatter.setData(xs, ys)
            self._clear_labels()
            for det in frame.detections[:7]:
                text = f"{det.type.value} {det.confidence * 100:.0f}%"
                label = pg.TextItem(
                    text, color="#fbbf24", anchor=(0.5, 1.15),
                    fill=pg.mkBrush(13, 20, 38, 190),
                )
                label.setPos(det.freq_hz / 1e6, det.peak_db)
                self.plot.addItem(label)
                self._labels.append(label)
        else:
            self.det_scatter.setData([], [])
            self._clear_labels()

        vfo_mhz = float(vfo_abs_hz) / 1e6
        if x[0] <= vfo_mhz <= x[-1]:
            self.vfo_line.setPos(vfo_mhz)
            self.vfo_line.show()
        else:
            self.vfo_line.hide()

    def clear(self) -> None:
        self.curve.setData([], [])
        self.baseline_curve.setData([], [])
        self.det_scatter.setData([], [])
        self._clear_labels()
        self.vfo_line.hide()
        self._range_key = None
