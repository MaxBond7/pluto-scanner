# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""SDR Scanner - a desktop SDR spectrum, scanner and drone-band monitor.

The application is split into three layers:
    devices  - IQ producers (simulator, Pluto+, HackRF One or an IQ file)
    dsp      - spectrum, background, detector, tracker, classifier, demodulator
    ui       - PySide6/pyqtgraph front end
"""

__version__ = "0.34.0"
