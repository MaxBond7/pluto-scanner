# Changelog

All notable changes to this project are documented here.

## [Unreleased]

## [0.36.0] - 2026-11-06

- **Recorded IQ can be played in the video tab.** Selecting an IQ-file
  session and pressing «Смотреть» decodes the first 2 seconds offline in a
  background thread; no real-time stream is needed. This allows testing on
  a short dataset block that would end before a live playback could start.
- `tools/extract_fpv_recording.py` extracts one frequency block from the FPV
  dataset and writes a normal cf32 + JSON recording, ready for the IQ-file
  session.
- Checked with the real 1240 MHz VTX block: the app built a 345-line
  monochrome frame (PAL) and saved it as a PNG.

## [0.35.0] - 2026-11-06

- **SECAM (monochrome) standard** in the video tab for Russian 625/50 TV;
  line timing and geometry are shared with PAL, colour is still not decoded.
- **Analog TV scanner** `tools/scan_analog_tv.py`: scans Russian VHF/UHF
  video carriers, requires a 15.3–15.9 kHz line and a wide signal, and only
  counts blocks from the requested frequency. It does not mistake a 16 kHz
  spur or a DVB-T2 multiplex for analog TV.
- `docs/TV_KRASNODAR.md`: Russian D/K frequencies, scan commands, cable
  attenuator warning and the result of the local UHF/VHF scan.
- Local scan found **no analog TV** in Krasnodar (UHF 21–60, VHF 1–12):
  wideband signals and narrow spurs were present, but no 15.6 kHz line.
  This matches the analog switch-off; a cable or local RF source is needed
  for a real TV test.
- AM negative-modulation test for SECAM; the decoder now has PAL, NTSC and
  SECAM monochrome tests.

## [0.34.0] - 2026-11-06

- **Fixed the video viewer freezing the app.** A 20 MS/s frame took about
  15 seconds because every line interpolated over the whole 2.4M-sample
  capture. Interpolation now uses only the line segment: the same frame takes
  about 0.36 s.
- Frame decoding moved to a background thread; the GUI only formats the
  finished frame. The live HackRF check showed a maximum UI gap of 78 ms
  instead of a multi-second freeze.
- The IQ buffer is capped while a frame is being decoded, so a slow decoder
  cannot grow memory without bound or make the UI lag behind.
- Status now distinguishes a full frame from a field/fragment.
- Deep-look regression checks after the change: monitor pause/resume and
  deep look while monitoring still work at 20 MS/s.

## [0.33.0] - 2026-11-06

- **Video is now the first main-window tab**, not a modal dialog. It follows
  the selected Pluto/HackRF; switching away from the tab or starting a
  scan/record/drone monitor stops it and restores the receiver.
- Access from several places: the «Видео» tab, **Вид → Аналоговое видео…**
  (`Ctrl+Shift+V`), and a **«Смотреть видео»** button in the event card when
  deep look finds an analog line. The event button stops the drone monitor
  and opens the tab on the event frequency/standard.
- Frame/field split: vertical blanking gaps are detected, the longest
  uninterrupted field/frame is preferred, and short fragments are still
  stacked instead of being thrown away.
- Contacts remain the default tab; the video tab is first on the left.

## [0.32.0] - 2026-11-06

- **Analog video viewer (stage 4, first version).** New `video/analog.py`
  demodulates FM or AM, finds line sync, samples the active part of each line
  and stacks a monochrome frame. `Вид → Аналоговое видео…` opens a modal
  window with frequency, PAL/NTSC, FM/AM, inversion and a snapshot button.
- The window owns the receiver while open: it retunes the selected Pluto or
  HackRF, switches the session to raw-IQ mode and restores the previous
  centre/rate/bandwidth on close. Recording, scanning and the drone monitor
  must be stopped first.
- Line-grid filling recovers missed sync pulses: a real 1240 MHz VTX sweep
  from the FPV dataset produced a 345-line partial monochrome frame instead
  of the 190 lines found by raw sync detection.
- Synthetic PAL and NTSC signals decode into frames; the window is tested
  with a fake live session.
- Limits: monochrome only, no colour subcarrier, no full vertical-hold PLL;
  a live continuous VTX is still needed for a stable picture.

## [0.31.0] - 2026-11-06

- **Analog FPV validated on real recordings.** Downloaded the Zenodo
  `10.5281/zenodo.19870020` dataset (CC BY 4.0) and analyzed three 1240 MHz
  VTX sweeps captured with a HackRF: FM line rate **15.636 kHz**, strength
  147–175, verdict «аналоговый видеолинк». A 100 MHz broadcast block in the
  same sweep did not pass the analog test. Results in `docs/FPV_ANALOG.md`.
- **FM line-sync detection.** Analog FPV video is usually FM, so the
  envelope is flat. The analyzer now discriminates the IQ (phase derivative)
  and looks for 14–17 kHz in both the envelope and the FM signal.
  Synthetic FM PAL and envelope PAL tests both pass.
- `tools/download_fpv_analog.py` downloads selected chunks with resume;
  `tools/analyze_fpv_sweep.py` reads only the blocks around one frequency;
  `tools/check_analog.py` checks any cf32/int16 file.
- **Fixed non-multiple capture lengths.** `behavior.analyze` and
  `channels.analyze_channels` truncated the frame block incorrectly when the
  sample count was not a multiple of the 0.25 ms frame, which crashed on the
  dataset's 655360-sample sweep blocks.
- **Deep look after stopping the monitor on HackRF.** The monitor and deep
  look now use the rate the device was opened with (20.0 MS/s); the rate
  selector is locked for HackRF, and the worker reopens the device if a rate
  change is ever requested. A capture is retried once.
- The event card shows both envelope and FM line peaks, and a quiet channel
  or LO spur is reported as noise instead of 100% duty.
- The video viewer (FM demodulation to frames, PAL/NTSC decoder) is now a
  separate stage 4 in `docs/ROADMAP.md`; it is not part of this release.

## [0.30.0] - 2026-11-06

- **Fixed deep look failing on HackRF after the monitor was stopped.** The
  probe asked for a new sample rate (10.24 → 20.0); libhackrf sometimes
  returned `start_rx: -1000` or accepted the call without delivering any
  callbacks. The HackRF is now opened at 20.0 MS/s and the monitor/deep look
  adopt the device's current rate instead of changing it mid-stream. The
  rate selector is locked for HackRF with an explanation.
- The worker still reopens the device as a fallback if a rate change is ever
  requested, and deep look retries a capture once instead of returning an
  empty result immediately.
- **Quiet-channel guard.** A flat noise floor or a residual LO spur no longer
  looks like 100% duty: the result says «сигнал не обнаружен — только шум
  или узкий спур». This also stops a quiet channel from producing fake
  channel maps.
- **Stage 3: analog video line sync.** A strong envelope line in the
  14–17 kHz band is reported as a PAL/NTSC line rate (15.625 or 15.734 kHz)
  and gives the verdict «аналоговый видеолинк». A digital 5–8 kHz envelope
  peak is not called analog.
- The event card prints the envelope line rate and its strength; synthetic
  tests cover both the analog line and the digital false positive.
- Docs: HackRF rate behaviour, stage 3 limits; the real FPV recording is
  still needed to confirm the threshold on air.

## [0.29.0] - 2026-11-06

- **Deep look stage 2: channel map.** New `ml/channels.py` groups per-frame
  peaks into channels and reports dwell time, hop period, hop interval
  variation and a dwell histogram. The event card draws the busiest channels
  as a bar chart.
- **Honest wideband guard.** A 20 MHz Wi-Fi channel has no stable carrier;
  frames whose half-power width exceeds 4 MHz are excluded from the channel
  map. The result prints the wide-frame share and refuses to call a wide
  signal frequency-hopping. On live home Wi-Fi 91% of frames were wide, so
  the map is marked incomplete instead of inventing dozens of channels.
- **FHSS profile** compares the map with the Tampere measurements: DJI links
  used 41–74 channels, 700–1830 hops/s and short dwells; Wi-Fi drones and
  access points had fewer channels or longer dwells. It is a cautious profile,
  not a model verdict.
- At 20 MHz the channel map now supplies hop rate and channel count for the
  final verdict; the per-frame peak counter is no longer allowed to inflate
  them on noise frames.
- Tests build synthetic 3-channel hoppers, steady carriers, wide noise and
  histogram coverage; live HackRF check covers the wideband guard.
- Deep look capture on HackRF remains 20.0 MS/s and the controller still
  returns to the same chunk.

## [0.28.0] - 2026-11-06

- **HackRF readiness.** Fixed the `hackrf_device_list` call: libhackrf
  returns the list pointer directly and takes no arguments, so the old
  declaration would have found no device on real hardware.
- **Actual rate is reported and used.** `HackRFWorker` now clamps to the
  device limit (20.0 MS/s), stores the accepted value and emits it. Before,
  asking for 20.48 left the worker reporting 20.48 while blocks carried 20.0,
  and the drone controller rejected every block.
- The drone monitor clamps a HackRF request to 20.0 MS/s; the rate lists now
  include 20.0 and the warning explains that 20 MS/s is normal for HackRF but
  not for a Pluto on USB 2.0.
- Added `tools/check_hackrf.py`: first-contact check for serial, real stream
  rate, ADC clipping, DC offset, spectrum peak, duty/bursts/hops/channels,
  optional IQ save. Added `--hackrf` to start the app with the first board.
- **Live check passed** on a HackRF One: 20 MS/s, 99% real time, drone
  monitor and deep look working; the controller returns to the same chunk.
- **DC spur removed before behaviour analysis.** The HackRF centre spike made
  a quiet channel look 100% busy; per-frame mean removal brings duty back to
  the real value (home Wi-Fi: 0.57–0.61 instead of 1.00).
- Rate changes no longer restart the USB stream for the same value, and
  `start_rx` retries once after a real change — this removes the occasional
  `HACKRF_ERROR_OTHER` on resume.
- Verified the int8 I/Q scaling and block splitting with a synthetic
  transfer; buffer lengths, filter snapping, gain stages and missing-library
  errors are covered by tests.
- Deep look on HackRF uses 20.0 MS/s and caps the capture at 24M samples
  (about 192 MB), shortening the window with a visible note.

## [0.27.0] - 2026-11-05

- **Deep look stage 1: no more stopping the monitor.** The event card now
  pauses the drone controller, captures on the event frequency and resumes
  the same chunk afterwards. With two receivers it uses the one that heard
  the event.
- **Several windows instead of one.** The card takes 1–6 windows of
  0.2–2 s and reports the spread (min–max) and a stability line, so a verdict
  is not based on one lucky burst.
- **«Почему такой вывод»** lists the features and thresholds behind the
  verdict; the background share from the map is shown as well.
- **Save the capture.** «Сохранить IQ» writes the windows as a normal
  recording; «В датасет» labels it with the chosen class. Saved recordings
  appear in the recordings panel after the card closes.
- Window length and count are remembered in `user_data/settings.json`.
- Tests cover capture, multi-window analysis, saving, the dialog and
  controller pause/resume. Live Pluto check: pause, two windows, same chunk,
  timer running again.

## [0.26.0] - 2026-11-05

- **The drone event list moved into the right-hand column**, under
  «Устройства», instead of a full-width strip at the bottom. The graph keeps
  the full height of the window and new events no longer push it around.
- Compact columns for the side list: severity dot, time, class, frequency,
  confirmations, confidence and the binary verdict. SNR, duty, bandwidth and
  devices are in the tooltip and the event card.
- **Severity is visible by theme colour and shape**: ● alarm, ▲ candidate,
  ○ interesting, · background, with a legend above the list. High-confidence
  rows are tinted and bolded; the contact list in the main window uses the
  same theme tokens for its confidence column.
- **«Только важные» is on by default.** It hides single weak bursts, `NARROW`
  and `WIFI` contacts unless they are confirmed drone-like events, and hides
  background signals until «Фон» is ticked. Everything still goes to the
  journal and the summary; the counter shows how many are hidden.
- The in-memory event list is capped at 1200 entries (oldest inactive first),
  so a multi-hour watch no longer grows without bound.
- **Themes now survive a restart**: the choice is saved again on shutdown and
  re-applied after the window is built. An explicit `--theme` still wins over
  the saved value.
- The window opens wider (up to 1520 px) and the parameter labels are shorter,
  so the new side column does not squeeze the controls.

## [0.25.0] - 2026-11-05

- **Renamed from Pluto Scanner to SDR Scanner.** The app has outgrown one
  radio: it already supports Pluto+, HackRF One, IQ files and a simulator.
  The window title, About box, executable (`SDRScanner.exe`), installer,
  portable archive, data folder and documentation now use the new name.
  «Pluto» remains only where it means the hardware.
- The Python package is now `sdr_scanner` and the console script is
  `sdr-scanner`.
- Installed builds use `%LOCALAPPDATA%\SDRScanner`; the old `PlutoScanner`
  folder is moved there on first start, so models, background maps and
  recordings survive the rename. `SDR_SCANNER_DATA_DIR` replaces
  `PLUTO_SCANNER_DATA_DIR` (the old name is still accepted).
- GitHub banner, social preview and icon regenerated with the new wordmark
  and the multi-device line.

## [0.24.0] - 2026-11-05

- **Deep look** (`drone/deep_look.py`): the event card has a **«Проверить
  1 с»** button. It retunes the receiver to the event frequency, listens for
  one second at 6.144 MS/s, measures duty, occupied bandwidth, burst rate,
  hop rate and channel count, then restores the previous frequency and rate.
- The verdict is cautious by design: a continuous wide link is called
  drone-like, a bursty narrow one is called access-point/controller-like, and
  everything in between is ambiguous. Below 15 MHz the result explicitly says
  that hop rate and channel count are unreliable.
- The button is disabled, with the reason in its tooltip, while the drone
  monitor, IQ recording or scanning is running, because those modes own the
  receiver.
- Verified against the live Pluto: capture and settings restore work; the home
  access point reads duty 0.20–0.47 and 140–211 bursts/s, matching the Tampere
  bursty profile. Results added to `docs/TAMPERE.md`.
- Tests cover the verdicts, the capture loop with a fake session and the
  disabled/enabled button states.

## [0.23.0] - 2026-11-04

- New `ml/behavior.py`: measures duty cycle, burst rate and regularity,
  frequency-hop rate, channel count, occupied bandwidth and the analog-video
  line-rate peak over 0.5–2 s of IQ. Works at any sample rate; hop rate and
  channels need a wide block (~20 MHz).
- `tools/analyze_tampere.py`: runs those measurements over the Tampere
  recordings; tests build synthetic hopping, pulsed and line-sync signals.
- Tampere dataset downloaded to `Z:\datasets\Tampere` (19 files, 8.56 GB,
  CC BY 4.0) and measured. Results in `docs/TAMPERE.md`: DJI links are
  continuous (duty 0.78–0.89, occupied 0.48–0.56, 700–1830 hops/s), while
  Wi-Fi drones and controllers are bursty (duty 0.10–0.23). Hop rate is only
  trustworthy at high duty; Mavic Mini is a low-duty exception.
- No model retraining: 19 files with no negatives are too small a sample.

## [0.22.0] - 2026-11-04

- **HackRF One backend** (`devices/hackrf.py`): receive-only, ctypes over
  `libhackrf`, 1 MHz – 6 GHz, 2–20 MS/s, 8-bit, 20 ms blocks. No pip package
  needed: the app finds `hackrf.dll` next to the exe, in `_PATH`/System32, or
  via `HACKRF_DLL`.
- The device panel has a **«+ HackRF»** button and the menu has «Добавить
  HackRF»; the app probes serials through `hackrf_device_list` and reports a
  clear error when the library or driver is missing.
- Gain mapping: LNA fixed at 16 dB, VGA from the slider, 14 dB amp above 70;
  baseband filter snaps to the values libhackrf accepts.
- `docs/HACKRF.md`: Windows driver (Zadig/WinUSB), libhackrf install, DLL
  discovery, parameters and limits. Not tested on real hardware yet — the
  board is not in the project.
- `tools/download_tampere.py`: downloads the Tampere drone recordings
  (Zenodo 4264467, CC BY 4.0, 8.56 GB) in parallel, with resume.
- Tests for the HackRF limits, gain mapping, worker selection and the
  missing-library error.

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
  new adapter (`sdr_scanner.ml.cardrf`) reads the 71 GB Cardinal RF archive
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
- CLI `python -m sdr_scanner.ml.domain_gap` and `--domain-gap` flag.
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
- `python -m sdr_scanner.ml.import_dataset` with start/max seconds, centre
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
- `python -m sdr_scanner.ml.train` CLI and an in-app ML tab with training
  progress, holdout accuracy and per-class precision/recall.
- ML top-3 hypothesis in the event card and `ml` block in event JSON; the
  heuristic classifier remains the primary label.
- Tests for features, synthetic data, softmax training, persistence and
  missing/broken models.

## [0.5.0] - 2026-10-31

- One-command release build: tests, PyInstaller, portable ZIP, SHA256 and an
  optional Inno Setup installer (`-Installer`).
- Portable builds keep data next to the executable via `portable.flag`;
  installed builds use `%LOCALAPPDATA%\SDRScanner` so Program Files stays
  read-only.
- `--version` and the version in the window title.
- Rotating application log `sdr_scanner.log` in the active data directory.
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
  spec produce `dist/SDRScanner/SDRScanner.exe` without requiring Python
  on the target machine.
- Bundled libiio/libiio1 and their dependencies, so the frozen build works
  with a real Pluto+ on a machine without a system-wide libiio install.
- Frozen builds keep `user_data`, `scan_logs` and `drone_logs` next to the
  executable and write `sdr_scanner_error.log` plus a message box if
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

- Initial SDR Scanner desktop application.
- Spectrum, waterfall, software VFO, wobble, AM/FM/SSB/CW demodulation.
- Real ADALM-PLUTO / Pluto+ support and IQ simulator.
- Contact tracking, known-contact whitelist and JSON persistence.
- Full-range scanner 325 MHz – 3.8 GHz with adaptive max-hold graph.
- JSON background bundles and background comparison.
- Drone-band monitor 433/868/915 MHz, 1.2–1.3 / 2.4 / 5.8 GHz.
- Strict event confirmation and JSON event journal.
- Windows desktop shortcut launcher.
- Presentation deck and diagrams.
