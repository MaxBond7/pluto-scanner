"""IQ device producers."""
from __future__ import annotations

from ..model import DeviceConfig
from .base import DeviceWorker
from .pluto import PlutoWorker, scan_pluto_uris
from .simulator import SimulatorWorker


def create_worker(config: DeviceConfig) -> DeviceWorker:
    if config.kind == "sim":
        return SimulatorWorker(config)
    if config.kind == "pluto":
        return PlutoWorker(config)
    raise ValueError(f"Unknown device kind: {config.kind}")


__all__ = [
    "DeviceWorker",
    "PlutoWorker",
    "SimulatorWorker",
    "create_worker",
    "scan_pluto_uris",
]
