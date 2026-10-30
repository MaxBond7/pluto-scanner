"""Dark desktop theme shared by all widgets."""
from __future__ import annotations

import pyqtgraph as pg
from PySide6.QtWidgets import QApplication

STYLESHEET = """
QMainWindow, QWidget {
    background-color: #0b1020;
    color: #d7e2f0;
    font-family: "Segoe UI", "Inter", sans-serif;
    font-size: 12px;
}
QGroupBox {
    border: 1px solid #22304a;
    border-radius: 7px;
    margin-top: 10px;
    padding: 10px 8px 8px 8px;
    background-color: #0d1426;
}
QGroupBox::title {
    subcontrol-origin: margin;
    left: 10px;
    padding: 0 5px;
    color: #67e8f9;
    font-weight: 600;
}
QPushButton {
    background-color: #17233b;
    border: 1px solid #2b3d5f;
    border-radius: 5px;
    padding: 5px 9px;
}
QPushButton:hover { background-color: #22345a; border-color: #3b5b8a; }
QPushButton:pressed { background-color: #0f1a2e; }
QPushButton:checked { background-color: #0e7490; border-color: #22d3ee; }
QPushButton:disabled { color: #52627a; background-color: #111a2c; }
QComboBox, QSpinBox, QDoubleSpinBox, QLineEdit {
    background-color: #0f172a;
    border: 1px solid #2b3d5f;
    border-radius: 4px;
    padding: 4px 6px;
    selection-background-color: #155e75;
}
QComboBox::drop-down { border: 0; width: 18px; }
QComboBox QAbstractItemView {
    background-color: #0f172a;
    selection-background-color: #155e75;
}
QCheckBox { spacing: 6px; }
QCheckBox::indicator {
    width: 14px; height: 14px;
    border: 1px solid #3b5b8a; border-radius: 3px;
    background-color: #0f172a;
}
QCheckBox::indicator:checked { background-color: #06b6d4; border-color: #22d3ee; }
QSlider::groove:horizontal {
    height: 4px; background: #1e2a44; border-radius: 2px;
}
QSlider::handle:horizontal {
    width: 13px; margin: -5px 0; border-radius: 6px;
    background: #22d3ee;
}
QTableWidget {
    background-color: #0b1222;
    alternate-background-color: #0e172b;
    gridline-color: #1e2a44;
    border: 1px solid #22304a;
    border-radius: 5px;
    selection-background-color: #155e75;
    selection-color: #ffffff;
}
QHeaderView::section {
    background-color: #14203a;
    color: #9fb3c8;
    border: 0;
    border-right: 1px solid #22304a;
    border-bottom: 1px solid #22304a;
    padding: 5px;
    font-weight: 600;
}
QScrollBar:vertical { background: #0b1020; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2b3d5f; border-radius: 5px; min-height: 25px; }
QScrollBar::add-line:vertical, QScrollBar::sub-line:vertical { height: 0; }
QListWidget {
    background-color: #0f172a;
    border: 1px solid #22304a;
    border-radius: 5px;
    padding: 3px;
}
QListWidget::item {
    padding: 6px;
    border-radius: 4px;
}
QListWidget::item:selected { background-color: #155e75; }
QStatusBar {
    background-color: #0d1426;
    border-top: 1px solid #22304a;
    color: #8fa6c0;
}
QToolTip {
    background-color: #17233b;
    color: #e2e8f0;
    border: 1px solid #3b5b8a;
    padding: 4px;
}
QTabWidget::pane {
    border: 1px solid #22304a;
    border-radius: 6px;
    background-color: #0d1426;
    top: -1px;
}
QTabBar::tab {
    background-color: #111a2c;
    color: #8fa6c0;
    border: 1px solid #22304a;
    border-bottom: 0;
    padding: 7px 16px;
    margin-right: 2px;
    border-top-left-radius: 6px;
    border-top-right-radius: 6px;
}
QTabBar::tab:selected {
    background-color: #17233b;
    color: #67e8f9;
    border-color: #2b3d5f;
}
QTabBar::tab:hover { color: #d7e2f0; }
QProgressBar {
    background-color: #0f172a;
    border: 1px solid #22304a;
    border-radius: 4px;
    text-align: center;
    color: #d7e2f0;
}
QProgressBar::chunk {
    background-color: #0891b2;
    border-radius: 3px;
}
QSplitter::handle { background-color: #1e2a44; }
"""


def apply_theme(app: QApplication) -> None:
    app.setStyle("Fusion")
    app.setStyleSheet(STYLESHEET)
    pg.setConfigOption("background", "#0a0f1e")
    pg.setConfigOption("foreground", "#9fb3c8")
    pg.setConfigOptions(antialias=True)
