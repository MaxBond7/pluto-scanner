"""Entry point for ``python -m pluto_scanner`` and the console script."""
from __future__ import annotations

import argparse
import json
import logging
import sys
from logging.handlers import RotatingFileHandler
from pathlib import Path

from PySide6.QtCore import QTimer
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import QApplication

from . import __version__
from .config import APP_NAME, DEFAULT_CENTER_FREQ, DEFAULT_FFT_SIZE, DEFAULT_SAMPLE_RATE
from .paths import DATA_DIR, DATA_HOME, ICON_PATH, ensure_data_home
from .ui.main_window import MainWindow
from .ui.theme import apply_theme


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="pluto-scanner",
        description="Desktop new-contact scanner for ADALM-PLUTO + IQ simulator",
    )
    p.add_argument("--sim", action="store_true",
                   help="add a synthetic simulator even when --device is used")
    p.add_argument("--device", action="append", default=[], metavar="URI",
                   help="Pluto URI (e.g. ip:192.168.2.1 or usb:...). Repeat for multiple devices.")
    p.add_argument("--center", type=float, default=DEFAULT_CENTER_FREQ,
                   help="initial LO / centre frequency in Hz")
    p.add_argument("--sample-rate", type=float, default=DEFAULT_SAMPLE_RATE,
                   help="initial sample rate in samples/s")
    p.add_argument("--fft", type=int, default=DEFAULT_FFT_SIZE,
                   help="FFT size (spectrum bins)")
    p.add_argument("--no-audio", action="store_true",
                   help="do not enable the audio output")
    p.add_argument("--smoke-test", action="store_true",
                   help="open the window, inject test signals, save smoke.png, quit")
    p.add_argument("--scan", action="store_true",
                   help="start a full-range sweep after startup")
    p.add_argument("--scan-start", type=float, default=None, metavar="HZ",
                   help="sweep start frequency in Hz (default: 325 MHz)")
    p.add_argument("--scan-end", type=float, default=None, metavar="HZ",
                   help="sweep end frequency in Hz (default: 3.8 GHz)")
    p.add_argument("--scan-step", type=float, default=None, metavar="HZ",
                   help="sweep step in Hz (default: 0.8 * sample rate)")
    p.add_argument("--scan-threshold", type=float, default=None, metavar="DB",
                   help="peak threshold above the per-step noise floor")
    p.add_argument("--compare", type=str, default=None, metavar="BACKGROUND",
                   help="compare the new sweep with this background.json")
    p.add_argument("--quit-after-scan", action="store_true",
                   help="quit when the sweep finishes/stops/fails (for scripts)")
    p.add_argument("--screenshot-after-scan", type=str, default=None,
                   metavar="PNG",
                   help="save a screenshot after the sweep and quit")
    p.add_argument("--drone", action="store_true",
                   help="start the drone-band monitor after startup")
    p.add_argument("--drone-bands", default="433,868,915,1.2,2.4,5.8",
                   metavar="KEYS",
                   help="comma-separated drone bands: 433,868,915,1.2,2.4,5.8")
    p.add_argument("--drone-rate", type=float, default=20.48e6,
                   metavar="S/s", help="monitor sample rate (default 20.48 MS/s)")
    p.add_argument("--drone-dwell", type=float, default=40.0,
                   metavar="MS", help="dwell per chunk in ms (default 40)")
    p.add_argument("--drone-threshold", type=float, default=8.0,
                   metavar="DB", help="peak threshold above noise (default 8)")
    p.add_argument("--drone-stable-usb", action="store_true",
                   help="force the safe 10.24 MS/s mode for two USB radios")
    p.add_argument("--drone-alarm-hits", type=int, default=3,
                   metavar="N", help="confirmations required for an alarm")
    p.add_argument("--drone-alarm-conf", type=float, default=70.0,
                   metavar="PCT", help="minimum confidence for an alarm")
    p.add_argument("--drone-no-iq", action="store_true",
                   help="do not save IQ evidence clips")
    p.add_argument("--drone-seconds", type=float, default=0.0,
                   metavar="SEC", help="stop the monitor after N seconds")
    p.add_argument("--quit-after-drone", action="store_true",
                   help="quit when the drone monitor stops")
    p.add_argument("--screenshot-after-drone", type=str, default=None,
                   metavar="PNG",
                   help="save a screenshot after the drone monitor stops")
    p.add_argument("--screenshot", type=str, default=None,
                   help="save a screenshot after startup and quit")
    p.add_argument("--record", type=float, default=0.0, metavar="SEC",
                   help="record raw IQ from the selected device for SEC seconds")
    p.add_argument("--quit-after-record", action="store_true",
                   help="quit when the IQ recording stops")
    p.add_argument("--screenshot-after-record", type=str, default=None,
                   metavar="PNG",
                   help="save a screenshot after the recording stops and quit")
    p.add_argument("--play", type=str, default=None, metavar="CF32",
                   help="open a recorded .cf32 IQ file for playback")
    p.add_argument("--rx-info", action="store_true",
                   help="print Pluto RX channel capability (1R1T/2R2T) and exit")
    p.add_argument("--train-ml", action="store_true",
                   help="train the offline ML model on synthetic IQ and exit")
    p.add_argument("--ml-per-class", type=int, default=60,
                   help="synthetic training blocks per class (default 60)")
    p.add_argument("--ml-epochs", type=int, default=600,
                   help="ML training epochs (default 600)")
    p.add_argument("--domain-gap", action="store_true",
                   help="build a synthetic-vs-real domain-gap report and exit")
    p.add_argument("--train-binary", action="store_true",
                   help="train the binary drone/background model and exit")
    p.add_argument("--binary-dronerf", default="", metavar="PATH",
                   help="folder with extracted DroneRF CSV files (optional)")
    p.add_argument("--binary-out", default="", metavar="PATH",
                   help="where to save the binary model")
    p.add_argument("--version", action="version",
                   version=f"%(prog)s {__version__}")
    p.add_argument("--log-level", default="INFO",
                   choices=["DEBUG", "INFO", "WARNING", "ERROR"])
    return p


def main(argv: list[str] | None = None) -> int:
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8", errors="replace")
        except Exception:
            pass
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s %(levelname)s %(name)s: %(message)s",
    )
    try:
        ensure_data_home()
        handler = RotatingFileHandler(
            DATA_HOME / "pluto_scanner.log",
            maxBytes=1_000_000,
            backupCount=3,
            encoding="utf-8",
        )
        handler.setFormatter(logging.Formatter(
            "%(asctime)s %(levelname)s %(name)s: %(message)s"
        ))
        logging.getLogger().addHandler(handler)
    except Exception:
        pass

    if args.rx_info:
        from .devices.pluto import probe_pluto_rx

        uri = args.device[0] if args.device else ""
        try:
            info = probe_pluto_rx(uri)
        except Exception as exc:
            print(f"RX probe failed: {exc}", flush=True)
            return 1
        print(json.dumps(info, ensure_ascii=False, indent=2), flush=True)
        try:
            out = Path("rx_info.json")
            out.write_text(
                json.dumps(info, ensure_ascii=False, indent=2) + "\n",
                encoding="utf-8",
            )
            print(f"JSON: {out.resolve()}", flush=True)
        except Exception:
            pass
        print(
            "2R2T доступен" if info["dual_rx"]
            else "2R2T недоступен: прошивка отдаёт только один RX",
            flush=True,
        )
        return 0

    if args.train_ml:
        from .ml.train import main as train_main

        return train_main([
            "--per-class", str(args.ml_per_class),
            "--epochs", str(args.ml_epochs),
        ])

    if args.domain_gap:
        from .ml.domain import build_report

        try:
            report, path = build_report(
                per_class=max(2, args.ml_per_class),
                out_dir=DATA_DIR / "domain_gap",
            )
        except Exception as exc:
            print(f"Domain-gap report failed: {exc}", flush=True)
            return 1
        print(f"Domain-gap report: {path}", flush=True)
        for name, item in report["domains"].items():
            print(
                f"{name}: n={item['n']} "
                f"accuracy={item['accuracy']}",
                flush=True,
            )
        return 0

    if args.train_binary:
        from .ml.train_binary import main as binary_main

        argv = ["--synthetic", str(max(8, args.ml_per_class // 3))]
        if args.binary_dronerf:
            argv += ["--dronerf-root", args.binary_dronerf]
        if args.binary_out:
            argv += ["--out", args.binary_out]
        return binary_main(argv)

    app = QApplication([sys.argv[0]])
    app.setApplicationName(APP_NAME)
    app.setOrganizationName("PlutoScanner")
    if ICON_PATH.exists():
        app.setWindowIcon(QIcon(str(ICON_PATH)))
    apply_theme(app)

    window = MainWindow(args)
    window.show()
    app.aboutToQuit.connect(window.shutdown)
    if args.no_audio:
        window.audio_btn.setChecked(False)
        window.audio_btn.setEnabled(False)

    if args.compare:
        window._scan_compare_override = str(Path(args.compare).expanduser())
    if args.scan_start is not None:
        window.scan_panel.start_spin.setValue(args.scan_start / 1e6)
    if args.scan_end is not None:
        window.scan_panel.end_spin.setValue(args.scan_end / 1e6)
    if args.scan_step is not None:
        window.scan_panel.step_spin.setValue(args.scan_step / 1e3)
    if args.scan_threshold is not None:
        window.threshold_spin.setValue(args.scan_threshold)

    if args.drone_bands:
        wanted = {
            item.strip() for item in str(args.drone_bands).split(",")
            if item.strip()
        }
        for key, check in window.drone_panel.band_checks.items():
            check.setChecked(key in wanted)
    if args.drone_rate:
        index = window.drone_panel.rate_combo.findData(args.drone_rate)
        if index < 0:
            window.drone_panel.rate_combo.addItem(
                f"{args.drone_rate / 1e6:.2f} MS/s", float(args.drone_rate)
            )
            index = window.drone_panel.rate_combo.count() - 1
        window.drone_panel.rate_combo.setCurrentIndex(index)
    window.drone_panel.dwell_spin.setValue(args.drone_dwell)
    window.drone_panel.threshold_spin.setValue(args.drone_threshold)
    window.drone_panel.alarm_hits_spin.setValue(args.drone_alarm_hits)
    window.drone_panel.alarm_conf_spin.setValue(args.drone_alarm_conf)
    if args.drone_no_iq:
        window.drone_panel.record_iq_check.setChecked(False)
    if args.drone_stable_usb:
        window.drone_panel.high_usb_check.setChecked(False)
        index = window.drone_panel.rate_combo.findData(10.24e6)
        if index >= 0:
            window.drone_panel.rate_combo.setCurrentIndex(index)

    if args.quit_after_scan or args.screenshot_after_scan:
        def finish_scan_and_quit(result) -> None:
            screenshot = args.screenshot_after_scan
            if screenshot:
                QTimer.singleShot(
                    350, lambda: (window.capture_screenshot(screenshot),
                                  window.close(), app.quit())
                )
            else:
                window.close()
                app.quit()

        window.scan_done.connect(finish_scan_and_quit)

    if args.scan:
        QTimer.singleShot(1200, window.start_scan)

    if args.quit_after_drone or args.screenshot_after_drone:
        def finish_drone_and_quit(summary, path) -> None:
            screenshot = args.screenshot_after_drone
            if screenshot:
                QTimer.singleShot(
                    800, lambda: (window.capture_screenshot(screenshot),
                                  window.close(), app.quit())
                )
            else:
                window.close()
                app.quit()

        window.drone_done.connect(finish_drone_and_quit)

    if args.drone:
        QTimer.singleShot(1200, window.start_drone)
        if args.drone_seconds and args.drone_seconds > 0:
            QTimer.singleShot(
                int(1200 + args.drone_seconds * 1000),
                window.stop_drone,
            )

    if args.play:
        def start_playback() -> None:
            if not window.play_recording_path(args.play):
                window.status_label.setText(
                    f"Запись не найдена: {args.play}"
                )
                window.status_label.setStyleSheet("color:#f87171;")

        QTimer.singleShot(1200, start_playback)

    if args.quit_after_record or args.screenshot_after_record:
        def finish_record_and_quit(info) -> None:
            screenshot = args.screenshot_after_record
            if screenshot:
                QTimer.singleShot(
                    350, lambda: (window.capture_screenshot(screenshot),
                                  window.close(), app.quit())
                )
            else:
                window.close()
                app.quit()

        window.record_done.connect(finish_record_and_quit)

    if args.record and args.record > 0:
        QTimer.singleShot(1200, lambda: window.start_recording(args.record))

    screenshot = args.screenshot
    if args.smoke_test and not screenshot:
        screenshot = str(Path.cwd() / "smoke.png")
    if screenshot:
        def finish_smoke() -> None:
            window.capture_screenshot(screenshot)
            window.close()
            app.quit()

        QTimer.singleShot(2000, window.inject_test_signal)
        QTimer.singleShot(6000, finish_smoke)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
