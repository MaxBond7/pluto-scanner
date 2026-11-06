# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Analog video decoding and the TV window."""
from __future__ import annotations

from .analog import (
    NTSC,
    PAL,
    SECAM,
    STANDARDS,
    DecodedFrame,
    VideoDecoder,
    VideoStandard,
    decode_frame,
    demodulate,
)
from .dataset import frequencies as dataset_frequencies
from .dataset import load_blocks as dataset_blocks
from .dataset import metadata_for as dataset_metadata

__all__ = [
    "DecodedFrame",
    "NTSC",
    "PAL",
    "SECAM",
    "STANDARDS",
    "VideoDecoder",
    "VideoStandard",
    "dataset_blocks",
    "dataset_frequencies",
    "dataset_metadata",
    "decode_frame",
    "demodulate",
]
