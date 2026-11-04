# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Dedicated window for the drone monitor.

The monitor needs a graph, a wide table and a row of controls.  Cramming that
into a tab of the main window left no room for any of them, so it lives in its
own window and the main window keeps a short launcher.

The window remembers its place on screen and restores itself properly when the
user brings it back from the taskbar.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import QByteArray, Qt
from PySide6.QtGui import QCloseEvent, QIcon
from PySide6.QtWidgets import QApplication, QMainWindow, QWidget

from .. import __version__
from ..config import APP_NAME
from ..paths import DATA_DIR, ICON_PATH
from .drone_panel import DronePanel
from .themes import load_settings, retint, save_settings

GEOMETRY_KEY = "drone_window_geometry"


class DroneWindow(QMainWindow):
    def __init__(
        self,
        panel: DronePanel,
        parent: QWidget | None = None,
        *,
        settings_path: str | Path | None = None,
    ) -> None:
        super().__init__(parent)
        self.panel = panel
        self._settings_path = Path(
            settings_path or (DATA_DIR / "settings.json")
        )
        self.setCentralWidget(panel)
        self.setWindowTitle(f"Дрон-монитор — {APP_NAME} {__version__}")
        if ICON_PATH.exists():
            self.setWindowIcon(QIcon(str(ICON_PATH)))
        self.setMinimumSize(1040, 640)
        self._restore_geometry()

    # ------------------------------------------------------------- geometry
    def _restore_geometry(self) -> None:
        data = load_settings(self._settings_path)
        encoded = data.get(GEOMETRY_KEY)
        if isinstance(encoded, str) and encoded:
            try:
                geometry = QByteArray.fromBase64(encoded.encode("ascii"))
                if self.restoreGeometry(geometry) and self.width() > 200:
                    return
            except Exception:
                pass
        self._center_on_screen()

    def _center_on_screen(self) -> None:
        parent = self.parentWidget()
        screen = parent.screen() if parent is not None else None
        available = (
            screen.availableGeometry() if screen is not None
            else QApplication.primaryScreen().availableGeometry()
        )
        width = min(1520, max(1100, available.width() - 80))
        height = min(940, max(640, available.height() - 80))
        self.resize(width, height)
        self.move(
            available.x() + (available.width() - width) // 2,
            available.y() + (available.height() - height) // 2,
        )

    def _save_geometry(self) -> None:
        data = load_settings(self._settings_path)
        data[GEOMETRY_KEY] = bytes(
            self.saveGeometry().toBase64()
        ).decode("ascii")
        save_settings(self._settings_path, data)

    # ------------------------------------------------------------ behaviour
    def show_and_raise(self) -> None:
        """Bring the window back, including from the taskbar.

        ``show(); raise_()`` alone leaves a minimised window minimised on
        Windows, which is why the launcher button used to do nothing after the
        monitor had been collapsed.
        """
        if self.isMinimized():
            self.setWindowState(
                self.windowState() & ~Qt.WindowState.WindowMinimized
            )
        self.show()
        self.raise_()
        self.activateWindow()

    def showEvent(self, event) -> None:  # noqa: N802 - Qt API
        super().showEvent(event)
        # The window may have been hidden during a theme switch; per-widget
        # styles are re-applied here so it never opens in stale colours.
        retint(self)

    def closeEvent(self, event: QCloseEvent) -> None:
        # Closing hides the window; monitoring keeps running.  The geometry is
        # stored so the next open looks the same.
        self._save_geometry()
        super().closeEvent(event)
