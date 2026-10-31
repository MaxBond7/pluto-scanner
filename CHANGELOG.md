# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.14.0] - 2026-11-01

- New binary `drone / background` model, trained on real DroneRF recordings
  (Bebop, AR, Phantom) plus local 433 MHz voice recordings and synthetic
  blocks. See `docs/BINARY.md` and `docs/BINARY_REPORT.md`.
- 18 binary features with a robust baseline fit, so a shaped receiver floor
  no longer turns a 9 MHz video link into "narrow 15 kHz activity".
- Drone monitor shows the binary score in a new `Дрон` column and in the
  event card; the model can veto an alarm but never creates one.
- CLI: `--train-binary`, `--binary-dronerf`, `--binary-out`.
- DroneRF adapter: real 40 MS/s CSV windows are converted to 20 MS/s complex
  baseband blocks, with noise augmentation down to 7 dB SNR.
- Documented the failed U-Boot 2R2T experiment on the current Pluto: the
  device lost USB/SSH shortly after the change; the original `ad9364`/`1r1t`
  environment was restored and verified. See `docs/PLUTO_2R2T.md`.

## [0.13.0] - 2026-10-31

- Domain-gap report comparing fresh synthetic, augmented synthetic and real
  recordings, with accuracy, coverage, confidence, per-class results and
  feature drift.
- CLI `python -m pluto_scanner.ml.domain_gap` and `--domain-gap` flag.
- Current real 433 MHz result: 72.7% on 11 NARROW blocks vs 98.9% on
  synthetic; report in `docs/DOMAIN_GAP.md`.

## [0.12.0] - 2026-10-31

- Front-end overload guard: near-field signals with peak above -6 dBFS and
  SNR over 30 dB are marked `OVERLOAD`, do not alarm and skip ML.
- Event card explains overload and asks to reduce gain or move the antenna.
- Real 433 MHz field test with Baofeng: 4 labeled recordings, overload at
  0 m, correct `NARROW` at 1/3/5 m; report in `docs/FIELD_TEST_2026-10-31.md`.
- Dataset builder ignores overloaded blocks.

## [0.11.0] - 2026-10-31

- Band scanner pause/resume: the current step is re-armed on resume, and
  timeouts do not fire while paused.
- Scanner CSV export from the live results table.
- Pause button state and status text in the scanner panel.
- Verified pause, resume and CSV export on the simulator.

## [0.10.0] - 2026-10-31

- Active learning: event card action "ML ошибся? Указать класс" saves the
  event IQ clip as a labeled training recording.
- Import dialog in the recording tab for SigMF and raw float32 IQ, with
  label, sample rate, centre and max seconds.
- Simple five-step ML guide in Russian (`docs/ML_SIMPLE.md`), written for
  users without a terminal.
- ML panel shows labeled recording counts and source of the active model.

## [0.9.0] - 2026-10-31

- Bundled synthetic ML model (`assets/ml_model_default.json`) so the ML tab
  and event-card hypothesis work out of the box before any local training.
- ML results now carry their source (`synthetic`, `real`, `mixed`) and the
  event card shows it instead of always claiming synthetic training.
- Fallback order: user model in `user_data/ml_model.json`, then bundled
  default model.
- Test for the bundled default model.

## [0.8.0] - 2026-10-31

- Import external IQ datasets into the local recording format:
  SigMF (`.sigmf-meta` + `.sigmf-data`) and raw interleaved float32 `.dat`.
- `python -m pluto_scanner.ml.import_dataset` with start/max seconds, centre
  frequency, sample rate and optional morphology label.
- Dataset catalogue with verified sizes, licences and fit for our six classes:
  DroneDetect, DroneRFa, RadioML, WiSig, SigMF, SigIDWiki, RadioScanner.
- No third-party dataset is bundled; licensing and huge sizes stay with the
  original source.
- Tests for SigMF and raw-IQ import.

## [0.7.0] - 2026-10-31

- Label IQ recordings with a drone class (`FHSS`, `TELEMETRY`,
  `VIDEO_ANALOG`, `VIDEO_DIGITAL`, `WIFI`, `NARROW`) from the recording tab.
- Train on labeled recordings with `--real-dir`, optional synthetic mixing,
  block extraction and recording-level train/test split.
- ML tab: "Обучить на записях", real/synthetic block counts and honest
  no-holdout warning when there are too few recordings.
- New tests for label persistence, real dataset building and training.
- Recording analysis can disable the DC notch so a signal at the recording
  centre is not erased.

## [0.6.0] - 2026-10-31

- Offline ML baseline for the drone monitor: 12 IQ features, six classes,
  NumPy softmax regression, JSON persistence.
- Synthetic IQ generator for FHSS, telemetry, analog/digital video, Wi-Fi and
  narrowband activity.
- `python -m pluto_scanner.ml.train` CLI and an in-app ML tab with training
  progress, holdout accuracy and per-class precision/recall.
- ML top-3 hypothesis in the event card and `ml` block in event JSON; the
  heuristic classifier remains the primary label.
- Tests for features, synthetic data, softmax training, persistence and
  missing/broken models.

## [0.5.0] - 2026-10-31

- One-command release build: tests, PyInstaller, portable ZIP, SHA256 and an
  optional Inno Setup installer (`-Installer`).
- Portable builds keep data next to the executable via `portable.flag`;
  installed builds use `%LOCALAPPDATA%\PlutoScanner` so Program Files stays
  read-only.
- `--version` and the version in the window title.
- Rotating application log `pluto_scanner.log` in the active data directory.
- Build script validates that `pyproject.toml`, `__init__.py` and the release
  version agree.
- Inno Setup template with per-user install, shortcuts and uninstall entry.
- Tests for portable/installed data-directory selection.

## [0.4.2] - 2026-10-31

- Playback devices are rejected by the band scanner and drone monitor instead
  of producing meaningless sweeps.
- Center frequency, bandwidth, gain, threshold and band preset are disabled
  for a recording, while VFO and audio remain available.
- Playback device names use a short time stamp instead of the full file id.
- Windows build script forces UTF-8 console output.
- Documented the `iqfile` device kind.

## [0.4.1] - 2026-10-31

- Read-only `--rx-info` probe: reports firmware model, IIO RX channels,
  `1r1t`/`2r2t` mode and writes `rx_info.json`.
- Documented the second RX limitation, the 2R2T firmware options, a
  reversible U-Boot environment check and DFU recovery risks.
- Added tests for complex RX channel counting.

## [0.4.0] - 2026-10-31

- Long IQ recording to `iq_recordings/*.cf32` with JSON sidecar metadata.
- Background writer thread with a bounded queue, drop accounting and a free
  space check before recording starts.
- Recording tab: duration, estimated size, progress, file table, playback,
  delete and folder buttons.
- Playback of a recording as a normal device (`IqFileWorker`), so spectrum,
  waterfall, contacts, VFO and demodulation all work without hardware.
- Unfinished recordings are recovered by file size and can still be played.
- CLI: `--record`, `--quit-after-record`, `--screenshot-after-record`,
  `--play`.
- New tests for cf32 writing, metadata, chunked reading and deletion.

## [0.3.0] - 2026-10-30

- Portable Windows one-folder build: `build_windows.ps1` and a PyInstaller
  spec produce `dist/PlutoScanner/PlutoScanner.exe` without requiring Python
  on the target machine.
- Bundled libiio/libiio1 and their dependencies, so the frozen build works
  with a real Pluto+ on a machine without a system-wide libiio install.
- Frozen builds keep `user_data`, `scan_logs` and `drone_logs` next to the
  executable and write `pluto_scanner_error.log` plus a message box if
  startup fails.
- Version and icon metadata embedded into the `.exe`.
- Verified the frozen build with the simulator and a real Pluto+ over USB.

## [0.2.0] - 2026-10-30

- Signal-signature library with SQLite storage, open-reference seed catalog,
  JSON/CSV import/export and top-3 matching in the event card.
- IQ evidence clips for drone events (`clips/*.cf32` + metadata).
- Event evidence card: spectrum, envelope, parameters, clip info and export.
- Persistent drone white list with an event-card action and a management
  dialog; whitelisted events stay visible but do not alarm.
- Learned per-band noise-floor profiles keyed by device, band, gain and sample
  rate (`user_data/drone_background.json`).
- Portable local data directory (`NEW/user_data`) so the project can be moved
  without writing to the user profile.
- Application icon for the window and Windows shortcut.
- Packaging plan for a portable Windows `.exe` and installer.
- Stricter alarm confirmation (3 hits / 70% confidence).

## [0.1.0] - 2026-10-30

- Initial Pluto Scanner desktop application.
- Spectrum, waterfall, software VFO, wobble, AM/FM/SSB/CW demodulation.
- Real ADALM-PLUTO / Pluto+ support and IQ simulator.
- Contact tracking, known-contact whitelist and JSON persistence.
- Full-range scanner 325 MHz – 3.8 GHz with adaptive max-hold graph.
- JSON background bundles and background comparison.
- Drone-band monitor 433/868/915 MHz, 1.2–1.3 / 2.4 / 5.8 GHz.
- Strict event confirmation and JSON event journal.
- Windows desktop shortcut launcher.
- Presentation deck and diagrams.
