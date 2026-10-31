"""Passive drone-band monitor built on the existing Pluto/simulator sessions."""
from __future__ import annotations

from importlib import import_module

from .bands import (
    BANDS_BY_KEY,
    DRONE_BANDS,
    DroneBand,
    MonitorChunk,
    band_names,
    chunks_for_band,
    chunks_for_bands,
    selected_bands,
)
from .features import (
    CLASS_RU,
    DRONE_CLASSES,
    DroneObservation,
    analyze_iq,
)
from .recorder import DroneRecorder, make_drone_id
from .tracker import DroneEvent, DroneTracker

# ``manager`` and ``controller`` import ``..ml``, and ``..ml`` imports
# ``drone.features``.  Importing them eagerly here would make the package
# unimportable from the ``ml`` side first, so they are resolved on demand.
_LAZY = {
    "DroneWatchController": ".controller",
    "DroneMonitorManager": ".manager",
}


def __getattr__(name: str):
    module = _LAZY.get(name)
    if module is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
    value = getattr(import_module(module, __name__), name)
    globals()[name] = value
    return value


__all__ = [
    "DRONE_BANDS",
    "BANDS_BY_KEY",
    "DroneBand",
    "MonitorChunk",
    "chunks_for_band",
    "chunks_for_bands",
    "selected_bands",
    "band_names",
    "DroneWatchController",
    "DroneObservation",
    "analyze_iq",
    "CLASS_RU",
    "DRONE_CLASSES",
    "DroneTracker",
    "DroneEvent",
    "DroneRecorder",
    "make_drone_id",
    "DroneMonitorManager",
]
