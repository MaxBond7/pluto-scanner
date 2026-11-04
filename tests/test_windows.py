# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Window behaviour: geometry memory and restoring from the taskbar."""
from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget

from sdr_scanner.ui.drone_window import DroneWindow


def _app() -> QApplication:
    return QApplication.instance() or QApplication([])


def test_drone_window_remembers_its_geometry(tmp_path):
    app = _app()
    settings = tmp_path / "settings.json"
    first = DroneWindow(QWidget(), settings_path=settings)
    first.resize(760, 600)
    first.move(10, 10)
    first.show()
    app.processEvents()
    expected = (first.width(), first.height(), first.x(), first.y())
    first.close()
    assert settings.exists()

    second = DroneWindow(QWidget(), settings_path=settings)
    second.show()
    app.processEvents()
    assert (second.width(), second.height()) == expected[:2]
    second.close()


def test_show_and_raise_restores_a_minimised_window(tmp_path):
    app = _app()
    window = DroneWindow(QWidget(), settings_path=tmp_path / "s.json")
    window.show()
    app.processEvents()
    window.showMinimized()
    app.processEvents()
    window.show_and_raise()
    app.processEvents()
    assert not window.isMinimized()
    window.close()

def test_drone_window_is_standalone(tmp_path):
    """An owned window has no taskbar button and collapses oddly on Windows."""
    window = DroneWindow(QWidget(), settings_path=tmp_path / "s.json")
    assert window.parent() is None
    assert window.isWindow()
    window.close()

def test_main_window_module_imports():
    """A stray edit once merged two lines and broke the whole UI import."""
    import sdr_scanner.ui.main_window  # noqa: F401
