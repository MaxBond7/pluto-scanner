# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""IQ device producers."""
from __future__ import annotations

from ..model import DeviceConfig
from .base import DeviceWorker
from .hackrf import HackRFWorker, probe_hackrf
from .iqfile import IqFileWorker
from .pluto import PlutoWorker, scan_pluto_uris
from .simulator import SimulatorWorker


def create_worker(config: DeviceConfig) -> DeviceWorker:
    if config.kind == "sim":
        return SimulatorWorker(config)
    if config.kind == "pluto":
        return PlutoWorker(config)
    if config.kind == "hackrf":
        return HackRFWorker(config)
    if config.kind == "iqfile":
        return IqFileWorker(config)
    raise ValueError(f"Unknown device kind: {config.kind}")


__all__ = [
    "DeviceWorker",
    "HackRFWorker",
    "IqFileWorker",
    "PlutoWorker",
    "SimulatorWorker",
    "create_worker",
    "probe_hackrf",
    "scan_pluto_uris",
]
