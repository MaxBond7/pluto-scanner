"""IQ device producers."""
from __future__ import annotations

from ..model import DeviceConfig
from .base import DeviceWorker
from .iqfile import IqFileWorker
from .pluto import PlutoWorker, scan_pluto_uris
from .simulator import SimulatorWorker


def create_worker(config: DeviceConfig) -> DeviceWorker:
    if config.kind == "sim":
        return SimulatorWorker(config)
    if config.kind == "pluto":
        return PlutoWorker(config)
    if config.kind == "iqfile":
        return IqFileWorker(config)
    raise ValueError(f"Unknown device kind: {config.kind}")


__all__ = [
    "DeviceWorker",
    "IqFileWorker",
    "PlutoWorker",
    "SimulatorWorker",
    "create_worker",
    "scan_pluto_uris",
]
