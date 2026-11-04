# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Render the boot splash to a PNG for the documentation.

    python tools/make_splash_shot.py presentation/splash.png
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from PySide6.QtTest import QTest  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from pluto_scanner.ui.splash import SplashScreen  # noqa: E402


def main() -> int:
    target = Path(sys.argv[1]) if len(sys.argv) > 1 else ROOT / "presentation" / "splash.png"
    app = QApplication([])
    splash = SplashScreen()
    splash.set_progress(0.62, "ИНТЕРФЕЙС")
    splash.show()
    QTest.qWait(500)
    splash.grab().save(str(target))
    splash.close()
    print("written", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
