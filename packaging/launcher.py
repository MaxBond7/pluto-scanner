"""Frozen-application entry point for PyInstaller."""
from __future__ import annotations

import os
import sys
import traceback


def _report_startup_error(exc: BaseException) -> None:
    text = traceback.format_exc()
    try:
        from pluto_scanner.paths import APP_ROOT

        (APP_ROOT / "pluto_scanner_error.log").write_text(text, encoding="utf-8")
    except Exception:
        pass
    if any(arg in ("--smoke-test", "--screenshot", "--log-level") for arg in sys.argv):
        return
    try:
        import ctypes

        ctypes.windll.user32.MessageBoxW(
            None,
            "Pluto Scanner не смог запуститься.\n\n"
            f"{exc}\n\n"
            "Подробности: pluto_scanner_error.log рядом с .exe",
            "Pluto Scanner",
            0x10,
        )
    except Exception:
        pass


def main() -> int:
    from pluto_scanner import paths
    from pluto_scanner.__main__ import main as app_main

    if getattr(sys, "frozen", False):
        os.chdir(paths.APP_ROOT)
    return app_main()


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except SystemExit:
        raise
    except BaseException as exc:  # noqa: BLE001 - last-resort GUI report
        _report_startup_error(exc)
        raise SystemExit(1)
