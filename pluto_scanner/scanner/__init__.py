"""Full-range sweep: peak detection, JSON recorder, controller and compare."""
from .compare import (
    background_compatible,
    compatibility_warnings,
    compare_background_files,
    compare_bundles,
    compare_spectrum,
    save_report,
)
from .controller import ScanController, latest_background
from .peaks import PeakResult, find_peaks
from .recorder import (
    ScanRecorder,
    find_latest_background,
    load_bundle,
    ranges_overlap,
)

__all__ = [
    "ScanController",
    "ScanRecorder",
    "PeakResult",
    "find_peaks",
    "find_latest_background",
    "latest_background",
    "load_bundle",
    "ranges_overlap",
    "compare_background_files",
    "compare_bundles",
    "compare_spectrum",
    "compatibility_warnings",
    "background_compatible",
    "save_report",
]
