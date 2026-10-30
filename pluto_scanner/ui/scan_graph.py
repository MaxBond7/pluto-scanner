"""Adaptive strength-vs-frequency plot used by the band scanner.

The plot keeps two live traces:

* **current step** - the averaged PSD of the spectrum being measured right now;
* **max hold** - the strongest level seen at every frequency since the sweep
  started.  It fills from left to right while the LO moves and is the visual
  representation of the whole scanned band.

The Y axis follows the data (robust percentiles), so weak bands and strong
broadcast bands are both readable without manual zooming.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
import pyqtgraph as pg
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

from ..config import format_freq

GRAPH_BINS = 8192


class ScanGraph(QWidget):
    """Live spectrum envelope for the sweep."""

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
        self.plot.setXRange(325, 3800, padding=0)
        self.plot.setYRange(-125, -20, padding=0)
        layout.addWidget(self.plot, 1)

        self.background_curve = self.plot.plot(
            [], [],
            pen=pg.mkPen("#475569", width=1.0, style=Qt.PenStyle.DashLine),
        )
        self.maxhold_curve = self.plot.plot(
            [], [], pen=pg.mkPen("#f59e0b", width=1.5)
        )
        self.current_curve = self.plot.plot(
            [], [], pen=pg.mkPen("#22d3ee", width=1.0)
        )
        self.peak_scatter = pg.ScatterPlotItem(
            size=7, symbol="o",
            brush=pg.mkBrush(245, 158, 11, 190),
            pen=pg.mkPen("#fbbf24"),
        )
        self.plot.addItem(self.peak_scatter)
        self.current_line = pg.InfiniteLine(
            pos=0, angle=90, movable=False,
            pen=pg.mkPen("#f472b6", width=1, style=Qt.PenStyle.DotLine),
            label="LO",
            labelOpts={"position": 0.04, "color": "#f472b6"},
        )
        self.plot.addItem(self.current_line)
        self.current_line.hide()

        self.hint = QLabel(
            "График заполняется по мере сканирования: бирюзовый — текущий шаг, "
            "жёлтый — накопленный максимум."
        )
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color:#8fa6c0; font-size:10px;")
        layout.addWidget(self.hint)

        self._start_hz = 325e6
        self._end_hz = 3800e6
        self._maxhold = np.full(GRAPH_BINS, np.nan, dtype=np.float64)
        self._x_grid = np.linspace(
            self._start_hz / 1e6, self._end_hz / 1e6, GRAPH_BINS
        )
        self._peak_x: list[float] = []
        self._peak_y: list[float] = []
        self._steps = 0
        self._last_y_range: tuple[float, float] | None = None
        self._has_background = False
        self._background_values = np.empty(0, dtype=np.float64)

    # ------------------------------------------------------------------ setup
    def configure(self, start_hz: float, end_hz: float) -> None:
        self._start_hz = float(min(start_hz, end_hz))
        self._end_hz = float(max(start_hz, end_hz))
        if self._end_hz - self._start_hz < 1.0:
            self._end_hz = self._start_hz + 1.0
        self._x_grid = np.linspace(
            self._start_hz / 1e6, self._end_hz / 1e6, GRAPH_BINS
        )
        self._maxhold = np.full(GRAPH_BINS, np.nan, dtype=np.float64)
        self._peak_x.clear()
        self._peak_y.clear()
        self._steps = 0
        self._last_y_range = None
        self._has_background = False
        self._background_values = np.empty(0, dtype=np.float64)
        self.background_curve.setData([], [])
        self.maxhold_curve.setData([], [])
        self.current_curve.setData([], [])
        self.peak_scatter.setData([], [])
        self.current_line.hide()
        self.plot.setXRange(
            self._start_hz / 1e6, self._end_hz / 1e6, padding=0
        )
        self.plot.setYRange(-125, -20, padding=0)
        self.hint.setText("Ожидание первого шага…")

    # ------------------------------------------------------------------- data
    def add_step(self, record: dict) -> None:
        spectrum = record.get("spectrum") or {}
        values = spectrum.get("psd_db") or []
        if not values:
            return
        x = np.linspace(
            float(spectrum.get("freq_start_hz", record.get("freq_start_hz", 0)))
            / 1e6,
            float(spectrum.get("freq_end_hz", record.get("freq_end_hz", 0)))
            / 1e6,
            len(values),
        )
        y = np.asarray(values, dtype=np.float64)
        self.current_curve.setData(x, y)

        # The per-step spectrum is decimated to 512 points while the global
        # grid has 8192 bins, so mapping point-to-point would leave a sparse
        # comb with NaN gaps.  Resample each step onto every global bin it
        # covers; the max-hold curve then fills continuously while scanning.
        span_mhz = max(1e-9, (self._end_hz - self._start_hz) / 1e6)
        i0 = int(round((x[0] - self._start_hz / 1e6) / span_mhz
                       * (GRAPH_BINS - 1)))
        i1 = int(round((x[-1] - self._start_hz / 1e6) / span_mhz
                       * (GRAPH_BINS - 1)))
        i0 = max(0, i0)
        i1 = min(GRAPH_BINS - 1, i1)
        if i1 > i0:
            grid = self._x_grid[i0:i1 + 1]
            values_on_grid = np.interp(grid, x, y)
            np.fmax.at(
                self._maxhold,
                np.arange(i0, i1 + 1, dtype=np.int64),
                values_on_grid,
            )
            self.maxhold_curve.setData(
                self._x_grid, self._maxhold, connect="finite"
            )

        peaks = record.get("peaks", [])
        for peak in peaks:
            try:
                peak_mhz = float(peak["freq_hz"]) / 1e6
                peak_db = float(peak["peak_db"])
            except (KeyError, TypeError, ValueError):
                continue
            self._peak_x.append(peak_mhz)
            self._peak_y.append(peak_db)
            # The decimated step spectrum underestimates a narrow peak by a
            # few dB.  Lift the matching max-hold bin to the real peak level
            # so the line and the peak markers agree.
            idx = int(round(
                (peak_mhz - self._start_hz / 1e6) / span_mhz
                * (GRAPH_BINS - 1)
            ))
            if 0 <= idx < GRAPH_BINS:
                self._maxhold[idx] = max(self._maxhold[idx], peak_db)
        if peaks and i1 > i0:
            self.maxhold_curve.setData(
                self._x_grid, self._maxhold, connect="finite"
            )
        if len(self._peak_x) > 20000:
            self._peak_x = self._peak_x[-20000:]
            self._peak_y = self._peak_y[-20000:]
        if self._peak_x:
            self.peak_scatter.setData(self._peak_x, self._peak_y)

        center = float(record.get("center_hz", 0.0)) / 1e6
        if self._start_hz / 1e6 <= center <= self._end_hz / 1e6:
            self.current_line.setPos(center)
            self.current_line.show()

        self._steps += 1
        if self._steps % 3 == 0 or self._last_y_range is None:
            self._adapt_y()
        self.hint.setText(
            f"Шагов: {self._steps} · пиков: {len(self._peak_x)} · "
            f"LO: {format_freq(record.get('center_hz', 0.0))}"
        )

    def set_background(self, bundle: dict) -> None:
        """Overlay the old max-hold spectrum after a comparison."""
        spectrum = bundle.get("spectrum") or {}
        values = spectrum.get("max_hold_db") or []
        if not values:
            return
        x = np.linspace(
            float(spectrum.get("freq_start_hz", 0)) / 1e6,
            float(spectrum.get("freq_end_hz", 0)) / 1e6,
            len(values),
        )
        self.background_curve.setData(x, np.asarray(values, dtype=np.float64))
        self._background_values = np.asarray(values, dtype=np.float64)
        self._has_background = True
        self._adapt_y()

    def _adapt_y(self) -> None:
        parts = [self._maxhold[np.isfinite(self._maxhold)]]
        if self._background_values.size:
            parts.append(
                self._background_values[np.isfinite(self._background_values)]
            )
        values = (
            np.concatenate(parts) if len(parts) > 1 else parts[0]
        )
        if values.size == 0:
            return
        lo = float(np.percentile(values, 3.0)) - 6.0
        hi = float(np.percentile(values, 99.7)) + 6.0
        if hi - lo < 24.0:
            mid = (hi + lo) / 2.0
            lo, hi = mid - 12.0, mid + 12.0
        key = (round(lo, 1), round(hi, 1))
        if key != self._last_y_range:
            self._last_y_range = key
            self.plot.setYRange(lo, hi, padding=0)

    # ------------------------------------------------------------------ state
    def mark_finished(self, path: str | Path | None = None) -> None:
        self.current_line.hide()
        suffix = f" · файл: {Path(path).name}" if path else ""
        self.hint.setText(
            f"Скан завершён · шагов: {self._steps} · "
            f"пиков: {len(self._peak_x)}{suffix}"
        )

    def clear(self) -> None:
        self._maxhold = np.full(GRAPH_BINS, np.nan, dtype=np.float64)
        self._peak_x.clear()
        self._peak_y.clear()
        self._steps = 0
        self._last_y_range = None
        self._has_background = False
        self._background_values = np.empty(0, dtype=np.float64)
        self.current_curve.setData([], [])
        self.maxhold_curve.setData([], [])
        self.background_curve.setData([], [])
        self.peak_scatter.setData([], [])
        self.current_line.hide()
        self.hint.setText("Готов к сканированию.")
