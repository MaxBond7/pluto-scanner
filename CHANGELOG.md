# Changelog

All notable changes to this project are documented here.

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
