# Contributing

Thanks for considering a contribution. The project is open source under the
MIT license, and the codebase and data model are designed to stay
reproducible and community-friendly.

## Development setup

Requirements: Python 3.10+, Windows is the primary target, but the DSP/core
modules are platform-neutral.

```powershell
py -3.10 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m pip install pytest
```

For real hardware:

```powershell
python -m pip install pyadi-iio
```

## Tests

```powershell
.\.venv\Scripts\python.exe -m pytest -q
.\.venv\Scripts\python.exe -m compileall -q pluto_scanner
```

All tests must pass without a Pluto connected. The simulator is the reference
for automated tests.

## Project layout

```text
pluto_scanner/
  devices/       IQ producers (Pluto / simulator)
  dsp/           spectrum, detector, tracker, classifier, demod
  scanner/       full-range sweep, JSON recorder, comparison
  drone/         fast band monitor, features, events, evidence clips
  signatures/    local signal catalog, SQLite store, matcher
  ui/            PySide6/pyqtgraph front end
tests/           pure-Python and Qt-light tests
presentation/    project deck and diagrams
```

## Pull requests

- Keep changes focused; one feature or bug fix per pull request.
- Add or update tests for new behaviour.
- Do not commit `.venv/`, `user_data/`, `scan_logs/`, `drone_logs/`, IQ clips,
  local screenshots or shortcuts. `.gitignore` covers them.
- Do not add API keys, tokens, personal paths or device serials.
- Update `README.md`, `CHANGELOG.md` and the relevant docs when behaviour
  changes.
- Hardware-dependent changes should state which Pluto+ revision/firmware and
  sample rate were tested.

## Signal-library contributions

The signature library is intentionally conservative.

- Every entry must include an open reference and a licence/usage note.
- Do not contribute proprietary or scraped closed databases.
- A typical band/modulation entry is a **hypothesis**, not a confirmed model.
- Model-level claims require protocol decoding, Remote ID or a labelled
  dataset plus reproducible measurements.
- Keep confidence values honest; `UNKNOWN` is a valid result.

## Legal and safety

The project is a **passive receiver**. Contributions that add jamming,
spoofing, unauthorised transmission or active interception will not be
accepted. Follow local radio regulations.
