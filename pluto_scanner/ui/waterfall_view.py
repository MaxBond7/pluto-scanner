"""Fast rolling waterfall using one pyqtgraph ImageItem."""
from __future__ import annotations

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import QRectF, Qt, Signal
from PySide6.QtWidgets import QVBoxLayout, QWidget

from ..config import WATERFALL_HISTORY
from ..model import SpectrumFrame


class WaterfallView(QWidget):
    frequency_clicked = Signal(float)

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.history = WATERFALL_HISTORY
        layout = QVBoxLayout(self)
        layout.setContentsMargins(0, 0, 0, 0)
        self.plot = pg.PlotWidget(background="#0a0f1e")
        self.plot.setMenuEnabled(False)
        self.plot.setLabel("bottom", "Частота", units="MHz")
        self.plot.getAxis("left").hide()
        self.plot.getAxis("bottom").setHeight(28)
        self.plot.setMouseEnabled(x=True, y=False)
        self.plot.invertY(True)
        layout.addWidget(self.plot)

        self.image = pg.ImageItem(axisOrder="row-major")
        self.plot.addItem(self.image)
        try:
            self.image.setColorMap(pg.colormap.get("viridis"))
        except Exception:
            pass
        self.image.setLevels((-122.0, -35.0))

        self.buffer: np.ndarray | None = None
        self._key: tuple | None = None
        self._levels = (-122.0, -35.0)
        self.plot.scene().sigMouseClicked.connect(self._mouse_clicked)
        self.plot.setXRange(-0.5, 0.5, padding=0)
        self.plot.setYRange(0, self.history, padding=0)

    def _mouse_clicked(self, event) -> None:
        if event.button() != Qt.MouseButton.LeftButton:
            return
        if not self.plot.sceneBoundingRect().contains(event.scenePos()):
            return
        point = self.plot.getViewBox().mapSceneToView(event.scenePos())
        self.frequency_clicked.emit(float(point.x()) * 1e6)

    def update_frame(self, frame: SpectrumFrame) -> None:
        psd = np.asarray(frame.psd, dtype=np.float32)
        if psd.size == 0:
            return
        key = (round(float(frame.freqs[0]), 1),
               round(float(frame.freqs[-1]), 1),
               psd.size)
        if self.buffer is None or self.buffer.shape[1] != psd.size or key != self._key:
            # Fill the initial history with the current frame so the widget
            # looks alive immediately instead of showing a large empty area.
            self.buffer = np.tile(psd, (self.history, 1)).astype(np.float32)
            self._key = key
            finite = psd[np.isfinite(psd)]
            if finite.size:
                low = float(np.percentile(finite, 5.0)) - 3.0
                high = float(np.percentile(finite, 99.5)) + 6.0
                if high - low < 20.0:
                    high = low + 20.0
                self._levels = (low, high)
            # ImageItem.setRect() uses the current image dimensions, so the
            # first setImage() must happen before setRect().
            self.image.setImage(self.buffer, autoLevels=False,
                                levels=self._levels)
            f0 = float(frame.freqs[0]) / 1e6
            f1 = float(frame.freqs[-1]) / 1e6
            self.image.setRect(QRectF(f0, 0.0, f1 - f0, float(self.history)))
            self.plot.setXRange(f0, f1, padding=0)
            self.plot.setYRange(0, self.history, padding=0)
        # Newest row at the top (the y-axis is inverted).
        self.buffer[1:] = self.buffer[:-1]
        self.buffer[0] = psd
        self.image.setImage(self.buffer, autoLevels=False, levels=self._levels)

    def clear(self) -> None:
        if self.buffer is not None:
            self.buffer.fill(-120.0)
            self.image.setImage(self.buffer, autoLevels=False, levels=(-122.0, -35.0))
        self._key = None
