"""Offline ML for the drone monitor.

The classifier is a small softmax regression over measured IQ features.  It
runs fully offline on the desktop and adds a second, confidence-scored
hypothesis; the heuristic classifier remains the primary label.
"""
from __future__ import annotations

__all__ = ["features", "model", "synthetic"]
