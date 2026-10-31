# Changelog

All notable changes to this project are documented here.

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
