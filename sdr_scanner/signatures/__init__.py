# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Known-signal signature library for SDR Scanner."""
from .matcher import CLASS_SOURCES, SignatureMatch, match_event
from .models import SignalSignature
from .seed import SEED_VERSION, seed_signatures
from .store import DEFAULT_DB, SignatureStore

__all__ = [
    "SignalSignature",
    "SignatureStore",
    "SignatureMatch",
    "match_event",
    "CLASS_SOURCES",
    "SEED_VERSION",
    "seed_signatures",
    "DEFAULT_DB",
]
