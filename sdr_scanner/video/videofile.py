# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Read an ordinary video file as grayscale frames for the bench transmitter.

FFmpeg is used through ``imageio-ffmpeg`` (a wheel with a static binary) or
a system ``ffmpeg``.  The frames are scaled to the active picture area of the
TV standard with the original aspect ratio kept and black bars added.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path
from typing import Iterator

import numpy as np


class VideoUnavailable(RuntimeError):
    """No usable FFmpeg binary."""


def ffmpeg_exe() -> str:
    try:
        import imageio_ffmpeg  # type: ignore

        return str(imageio_ffmpeg.get_ffmpeg_exe())
    except Exception:
        found = shutil.which("ffmpeg")
        if found:
            return found
    raise VideoUnavailable(
        "нужен FFmpeg: установите imageio-ffmpeg или ffmpeg в PATH"
    )


def read_frames(
    path: str | Path,
    width: int,
    height: int,
    fps: float,
    *,
    seconds: float | None = None,
) -> Iterator[np.ndarray]:
    """Yield uint8 frames of *width* x *height* at *fps* frames per second."""
    command = [ffmpeg_exe(), "-v", "error", "-i", str(path)]
    filters = (
        f"fps={fps:.6f},"
        f"scale={width}:{height},"
        "format=gray"
    )
    command += ["-vf", filters]
    if seconds is not None and seconds > 0:
        command += ["-t", f"{seconds:.3f}"]
    command += ["-f", "rawvideo", "-pix_fmt", "gray", "-"]
    frame_bytes = width * height
    process = subprocess.Popen(
        command, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
    )
    try:
        while True:
            chunk = process.stdout.read(frame_bytes) if process.stdout else b""
            if len(chunk) < frame_bytes:
                break
            yield np.frombuffer(chunk, dtype=np.uint8).reshape(
                height, width,
            ).copy()
    finally:
        try:
            process.stdout.close() if process.stdout else None
        except Exception:
            pass
        try:
            process.terminate()
        except Exception:
            pass
        try:
            process.wait(timeout=3)
        except Exception:
            pass
        error = b""
        try:
            error = process.stderr.read() if process.stderr else b""
        except Exception:
            pass
        if error:
            text = error.decode("utf-8", "replace").strip()
            if text:
                raise VideoUnavailable(text)


__all__ = ["VideoUnavailable", "ffmpeg_exe", "read_frames"]
