# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Render UI screenshots for the README in the mono theme.

    python presentation/make_screens.py

The simulator is used, so no SDR hardware is needed.  The real Qt event loop
runs, otherwise the DSP thread never produces frames and the spectrum is empty.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtCore import QTimer  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from sdr_scanner.__main__ import build_parser  # noqa: E402
from sdr_scanner.ui.main_window import MainWindow  # noqa: E402
from sdr_scanner.ui.themes import apply_theme, resolve_theme  # noqa: E402


def main() -> int:
    args = build_parser().parse_args(["--sim"])
    app = QApplication([sys.argv[0]])
    apply_theme(app, resolve_theme("mono", ROOT / "user_data" / "themes"))

    window = MainWindow(args)
    window.resize(1500, 940)
    window.show()

    shots = [
        ("ui_ml.png", window.ml_panel),
        ("ui_signatures.png", window.signature_panel),
        ("ui_recording.png", window.recording_panel),
    ]
    state = {"index": 0}

    def take(name: str) -> None:
        path = ROOT / "presentation" / name
        window.capture_screenshot(str(path))
        print("written", path)
        QTimer.singleShot(300, capture_next)

    def capture_next() -> None:
        if state["index"] >= len(shots):
            app.quit()
            return
        name, panel = shots[state["index"]]
        state["index"] += 1
        window.right_tabs.setCurrentWidget(panel)
        QTimer.singleShot(1200, lambda: take(name))

    QTimer.singleShot(3000, capture_next)
    app.exec()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
