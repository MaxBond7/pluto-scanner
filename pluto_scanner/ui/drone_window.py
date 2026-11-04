"""Dedicated window for the drone monitor.

The monitor needs a graph, a wide table and a row of controls.  Cramming that
into a tab of the main window left no room for any of them, so it lives in its
own window and the main window keeps a short launcher.
"""
from __future__ import annotations

from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QMainWindow, QWidget

from .. import __version__
from ..config import APP_NAME
from ..paths import ICON_PATH
from .drone_panel import DronePanel


class DroneWindow(QMainWindow):
    def __init__(
        self, panel: DronePanel, parent: QWidget | None = None,
    ) -> None:
        super().__init__(parent)
        self.panel = panel
        self.setCentralWidget(panel)
        self.setWindowTitle(f"Дрон-монитор — {APP_NAME} {__version__}")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.resize(1320, 900)
        self.setMinimumSize(1000, 680)

    def show_and_raise(self) -> None:
        self.show()
        self.raise_()
        self.activateWindow()
