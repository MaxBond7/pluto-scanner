# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.21.2] - 2026-11-04

- Fixed why a recorded background still let alarms through. The map was kept
  per *band*, but a band is swept as a dozen 20 MHz chunks with different
  centres; their relative spectra were averaged into one vector and became
  meaningless (occupancy 0.02–0.19 everywhere). The map is now keyed by the
  chunk's absolute centre, so chunks no longer mix.
- The map is keyed by the chunk's absolute centre, so chunks of one band no
  longer mix. Changing the sample rate or the band layout rebuilds the chunks,
  so the map must be recorded again — the parameters now show an empty map
  instead of silently doing nothing.
- A bin is "known" if it was active in at least 12% of the background frames,
  and an event is background when more than half of its active bins are known.
  This catches beaconing access points (a few percent duty) instead of
  requiring a signal to be present in 60% of the time.
- The monitor parameters show how many known bins the map has per band and
  which bands are empty, so an empty map is visible instead of silent.
- The alarm banner no longer pops for events already marked as background
  (the alarm itself was already suppressed, the banner was not).
- Old version-1 maps are discarded on load: they mixed chunks and cannot be
  repaired. Recording the background once more is required.

## [0.21.1] - 2026-11-04

- The drone monitor now defaults to **6.144 MS/s**, and the rate list includes
  4.096 and 6.144 MS/s. A Pluto over USB 2.0 drops samples above ~6 MS/s
  (measured: 74% real time at 8.19, 29% at 20.48), so the old default produced
  recordings with gaps.
- Selecting a higher rate shows a visible warning in the monitor parameters,
  and the status line repeats it for both monitoring and background recording.
  The rate is still not changed silently.
- Analysed the first long field session (465 s, 425 events, 43 alarms): all
  alarms were at 2.4 GHz Wi-Fi-like plateaus and narrow bursts, and the run was
  recorded at 20.48 MS/s with dropped samples. Written up in
  `docs/FIELD_TEST_2026-11-04.md`.
- Tests for the safe default and the warning.

## [0.21.0] - 2026-11-04

- Licence changed from MIT to the **GNU General Public License v3**
  (`GPL-3.0-only`), using the standard 35 KB GPL text as the `LICENSE` file
  (the same form other GPL-3.0 projects publish).
- Updated every place that named the old licence: `pyproject.toml` metadata and
  classifier, README badge and status section, CONTRIBUTING, third-party
  notices, model card, GitHub docs, antivirus appeal text, the Windows version
  resource and the About box.
- Every Python source file now carries an SPDX header
  (`GPL-3.0-only`), so the licence is visible per file, not only at the root.
- The About box now states the licence, the source repository and the absence
  of warranty, as GPL section 5(d) expects for an interactive interface.
- Versions up to 0.20.3 were published under MIT; their terms are unchanged
  for those releases.

## [0.20.3] - 2026-11-04

- The drone monitor window is now a standalone top-level window instead of an
  owned child of the main window. On Windows an owned window has no taskbar
  button and minimises into a small title-bar strip; now it minimises to the
  taskbar and restores to its normal size.
- Bringing it back no longer forces the active-state flag; minimised windows
  are restored with the standard state mask.
- The window is closed explicitly during shutdown.

## [0.20.2] - 2026-11-04

- Fixed the theme menu: its items are now an exclusive action group, so only
  the active theme is checked instead of every theme the user has tried. The
  checks also follow changes made from the status-bar list.
- Menus got their own style: a calm hover instead of the theme accent filling
  the whole row, consistent padding and separators.
- Switching the theme now recolours the contact table and the drone event
  table immediately. The rows cache their colour tokens for speed, so without
  this they kept the previous theme's colours until their text changed.
- Debugged the UI end to end on the simulator: theme menu, tabs, monitor
  window (minimise/restore/close), background recording, drone monitoring, IQ
  recording, scanning, all dialogs and panels — no exceptions.

## [0.20.1] - 2026-11-04

- Interface performance: the contact table reuses its rows, caches theme
  colours and skips rows that did not change — 200 contacts now cost 2.1 ms
  per refresh instead of 8.5 ms. The drone table touches only the cells whose
  text/colour/tooltip changed.
- A spectrum frame no longer redraws anything while the window is minimised or
  hidden; the calibration label and the FPS/contact counters update only when
  needed (4 Hz for the counters).
- The monitor status line no longer re-applies a stylesheet on every chunk.
- The drone window remembers its size and position, opens centred the first
  time, and the launcher now brings it back from the taskbar instead of
  leaving it minimised. A hidden window is not repainted during a theme switch;
  it picks the new colours when shown.
- `docs/PERFORMANCE.md` records the new numbers and `tests/test_performance.py`
  guards the contact-table budget.

## [0.20.0] - 2026-11-04

- Background learning is now a separate action: a **«Записать фон»** button in
  the monitor window records the persistent signals for 20–600 seconds and
  freezes the map. The drone monitor only reads that map and never teaches it,
  so a drone hovering nearby cannot become "background" itself.
- The monitor reports whether a map exists; without one it says honestly that
  every signal will alarm.
- Narrow persistent carriers (Bluetooth, cameras) now count as background too,
  not just wide Wi-Fi plateaus.
- Smoke-tested end to end on the simulator: recorded background → 12 events →
  all marked `фон`, no alarms.

## [0.19.0] - 2026-11-04

- The drone monitor moved into its own window (1320×900) with the controls in
  one row, a full-width graph and a wide event table. The main window keeps a
  short launcher tab, so the other panels got their space back.
- The main window now has a menu bar: Файл, Устройство, Монитор, Вид (with a
  theme submenu), Справка. The left control column scrolls instead of
  squashing its widgets on a small screen.
- Learned background map: the monitor records which parts of the band are
  occupied during the first seconds, freezes that map, and marks such signals
  as `фон` instead of raising a false alarm. New activity still alarms. The
  rule is a checkbox in the monitor settings.
- Tests for the map: persistent signal, new signal, freeze, per-band storage
  and the tracker carrying the background share.

## [0.18.1] - 2026-11-04

- Fixed the drone alarm banner: its background and its text were both taken
  from the single `danger` token, so in every theme the warning looked like an
  empty coloured strip. The theme engine now has separate `danger_bg` and
  `danger_fg` tokens, and widget styles can use `$token` placeholders, which
  keeps the two colours apart when a theme is switched.
- The mono themes show the banner as a white block with black text, the accent
  themes use their accent colour, and `classic` keeps the dark red.

## [0.18.0] - 2026-11-04

- CardRF support: MATLAB v7.3 (HDF5) files are now read by the importer, and a
  new adapter (`pluto_scanner.ml.cardrf`) reads the 71 GB Cardinal RF archive
  straight from the ZIP — 2.4 GHz captures, carrier search, 4.096 MHz
  baseband slice, 20 ms windows.
- `tools/capture_pluto.py` records IQ from a real Pluto/Pluto+ into the app's
  own `cf32` + JSON format, without opening the GUI.
- `tools/check_binary.py` scores a drone/not-drone model on your own
  recordings, per file and per label.
- Measured the USB 2.0 ceiling of the Pluto: 4.096 MHz is the widest
  gap-free rate, 20.48 MHz delivers only 29% of real time. Documented in
  `docs/HARDWARE.md`.
- Trained with CardRF (real Wi-Fi/Bluetooth/drone recordings) and measured the
  result: the Wi-Fi-versus-drone trade is physical, not a data shortage.
  The shipped model is unchanged; the numbers are in `docs/BINARY.md`.

## [0.17.1] - 2026-11-04

- New monochrome application icon: black rounded square with white spectrum
  bars, drawn separately for each ICO size (16/24/32/48/64/128/256) so the
  16 px version stays crisp instead of turning into a grey blob.
- The installer and window icon use the same file, so the taskbar, Start menu
  and Setup now match the `mono` theme.

## [0.17.0] - 2026-11-04

- Boot splash with an animated ASCII bird: the window appears ~125 ms after
  launch, before pyqtgraph and the UI panels are imported, so the start feels
  instant instead of blank.
- The bird is a blurred seagull silhouette (`tools/make_ascii_bird.py`
  generates the grid); individual characters blink out and come back at 18 fps,
  and the progress bar names the current stage.
- `--no-splash` disables it; screenshot modes skip it automatically.

## [0.16.1] - 2026-11-04

- Faster startup: time to a visible window dropped from ~1.38 s to ~0.72 s
  (import 1040 → 482 ms) by removing SciPy from the import path.
- `scipy.ndimage` replaced with `dsp/arrayops.py` (1-D median filter, gap
  closing, run labelling) — same behaviour, no 235 ms import.
- `scipy.signal.get_window` replaced with NumPy Hann/Hamming/Blackman.
- `scipy.signal.find_peaks` in the classifier replaced with a local-maximum
  counter; `dsp/demod.py` imports `scipy.signal` lazily and a background
  thread preloads it right after the window appears.

## [0.16.0] - 2026-11-03

- Performance pass over the hot paths, measured with `tools/bench.py`:
  spectrum 2.1× faster, drone feature extraction 2.2× faster, spectrum plot
  update 13.8× faster, spectrum decimation 80–100× faster.
- `decimate_mean` now uses `np.add.reduceat` instead of a Python loop over
  hundreds of slices.
- `SpectrumAnalyzer` windows in place, converts only the segments that reach
  the FFT, shifts the 1-D PSD instead of the 32×nfft matrix, and computes
  power as `re² + im²` without a square root.
- Drone `_time_features` no longer casts 400k samples to complex128.
- The spectrum plot reuses a pool of seven label items instead of creating
  and destroying `TextItem`s on every frame.
- The calibration status label is re-styled only when the state changes.
- New `docs/PERFORMANCE.md`, `tools/bench.py` and `tests/test_performance.py`
  with correctness cross-checks and loose budgets.

## [0.15.1] - 2026-11-03

- Fixed a crash when selecting a signature in the library: the panel used the
  theme colour helper without importing it.
- Scanner action buttons moved to a two-row grid, so "Сравнить с фоном" and
  "Экспорт CSV" are no longer clipped in a narrow panel.
- The GitHub page is now in the same monochrome style: new banner and social
  preview (black, 1 px frames, ruler, barcode, spectrum trace), flat B/W
  badges, a terminal-style feature block, uppercase section titles and
  screenshots retaken in the `mono` theme.

## [0.15.0] - 2026-11-03

- Theme engine: every colour now goes through a palette, so the whole UI can
  be re-skinned without touching widgets.
- Five built-in themes: `mono` (new default, pure black-and-white terminal),
  `mono-acid`, `mono-ember`, `mono-ice` (monochrome plus one rare accent) and
  the previous blue `classic`.
- User themes: drop a `.json` into `user_data/themes/`; the folder is created
  on first run with a README and a full example.
- Theme picker in the status bar, `--theme NAME` flag, and the choice is
  remembered in `user_data/settings.json`.
- Switching a theme is live: stored stylesheet templates are re-applied and
  graphs re-colour their pens and waterfall colormap (grey for mono themes).
- `docs/THEMES.md`: token list, JSON format, font/radius/waterfall options.

## [0.14.2] - 2026-11-03

- The `.exe` version resource is now generated from `pyproject.toml` on every
  build; it used to stay at 0.13.0, which looked like a stale binary in the
  file properties.
- Added `docs/ANTIVIRUS.md`: why Windows Defender can delete the unsigned
  PyInstaller build, what has already been ruled out (no UPX, one-folder,
  no admin, no autostart), and the three real options — local exclusion,
  Microsoft false-positive submission, code signing.

## [0.14.1] - 2026-11-01

- Wideband guard: a signal that fills almost the whole captured band
  (`busy_fraction >= 0.70`) is flagged as `wideband`. The event keeps its
  alarm but is marked `Wi-Fi?` in the table and in the event card, because a
  busy Wi-Fi channel and a wide drone video link are indistinguishable without
  decoding.
- Measured on a real phone hotspot (2412 MHz): 45–63% of blocks score above
  the alarm threshold, and 90–91% of those alarms carry the new marker, so
  nothing is suppressed.
- Documented why retraining on the Wi-Fi recordings was rejected: false
  alarms drop to 0–4%, but Phantom recall drops from 0.57 to 0.19–0.36.
- Documented the split variance of the binary model (ROC-AUC 0.962 ± 0.054
  over five splits instead of one lucky 0.978).
- `.mat` IQ import (`--format mat`), so CardRF and similar datasets can be
  loaded without manual conversion; the importer finds complex vectors and
  I/Q pairs, normalises ADC counts and writes a normal `.cf32` recording.
- Documented that two different datasets are called "CardRF" and how to get
  each one (Louisville/OneDrive vs Tampere/Zenodo).

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
