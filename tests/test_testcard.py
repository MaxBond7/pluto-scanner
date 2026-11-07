# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Bench transmitter: test card generation and the video tab controls."""
from __future__ import annotations

from types import SimpleNamespace

import numpy as np
from PySide6.QtWidgets import QApplication

from sdr_scanner.video.analog import NTSC, PAL, decode_frame
from sdr_scanner.video.testcard import build, composite_field
from sdr_scanner.video.testcard import test_card as make_card


def test_card_is_drawn_and_moves():
    first = make_card(640, 480, 0.0)
    second = make_card(640, 480, 0.6)
    assert first.shape == (480, 640)
    assert 0.0 <= first.min() and first.max() <= 1.0
    assert first.max() > 0.9
    # The travelling marker makes the two frames different.
    assert not np.array_equal(first, second)


def test_composite_field_has_line_sync_and_picture():
    line = int(round(20e6 / PAL.line_hz))
    rows = make_card(PAL.pixels, PAL.active_lines, 0.0)
    video = composite_field(PAL, 20e6, rows, 0)
    assert video.size == line * (PAL.lines // 2)
    assert video.min() == 0.0
    # The first line of the field starts with a vertical-sync pulse.
    assert video[:10].max() == 0.0


def _decoded(standard, fields: int = 6):
    iq, field = build(
        standard, 20e6, fields / 50.0, 3.5e6, field_only=False,
    )
    return decode_frame(iq, 20e6, standard), iq, field


def test_generated_pal_decodes_to_a_full_frame():
    frame, iq, field = _decoded(PAL)
    assert frame is not None
    assert frame.standard == "PAL"
    assert frame.lines == PAL.active_lines
    assert frame.frame_locked is True
    assert frame.quality > 0.8
    assert abs(frame.line_hz - PAL.line_hz) < 20
    assert field == int(round(20e6 / PAL.line_hz)) * (PAL.lines // 2)


def test_generated_ntsc_decodes_to_a_full_frame():
    frame, _iq, _field = _decoded(NTSC)
    assert frame is not None
    assert frame.standard == "NTSC"
    assert frame.lines == NTSC.active_lines
    assert frame.frame_locked is True
    assert frame.quality > 0.8


def test_bench_window_has_controls():
    from sdr_scanner.devices.pluto_tx import PlutoTransmitter
    from sdr_scanner.ui.bench_window import BenchWindow

    app = QApplication.instance() or QApplication([])
    window = BenchWindow()
    assert "передача" in window.windowTitle().lower()
    assert window.freq_spin.value() == 1241.0
    assert "антенн" in window.status.text()
    if PlutoTransmitter.available():
        assert window.card_btn.isEnabled()
        assert not window.stop_btn.isEnabled()
    window.deleteLater()
    app.processEvents()


def test_bench_preview_shows_the_card():
    from sdr_scanner.ui.bench_window import BenchWindow

    app = QApplication.instance() or QApplication([])
    window = BenchWindow()
    rows = make_card(PAL.pixels, PAL.active_lines, 0.0)
    window._show_preview(rows)
    assert window._preview_rows is not None
    assert window._preview_rows.shape == (PAL.active_lines, PAL.pixels)
    assert window.preview.pixmap() is not None
    window.deleteLater()
    app.processEvents()


def test_bench_image_is_converted_to_a_picture(tmp_path):
    from PySide6.QtGui import QImage

    from sdr_scanner.ui.bench_window import BenchWindow

    app = QApplication.instance() or QApplication([])
    card = make_card(768, 576, 0.0)
    path = tmp_path / "still.png"
    buffer = (card * 255).astype(np.uint8).tobytes()
    image = QImage(buffer, 768, 576, 768, QImage.Format.Format_Grayscale8)
    assert image.save(str(path), "PNG")
    rows = BenchWindow._image_rows(path, PAL)
    assert rows.shape == (PAL.active_lines, PAL.pixels)
    assert 0.0 <= rows.min() and rows.max() <= 1.0
    assert rows.max() > 0.8
    app.processEvents()


def test_video_file_is_decoded_as_frames(tmp_path):
    import subprocess

    import pytest

    from sdr_scanner.video.videofile import (
        VideoUnavailable,
        ffmpeg_exe,
        read_frames,
    )

    try:
        exe = ffmpeg_exe()
    except VideoUnavailable as exc:
        pytest.skip(str(exc))
    path = tmp_path / "clip.mp4"
    subprocess.run(
        [
            exe, "-y", "-v", "error", "-f", "lavfi",
            "-i", "testsrc=size=320x240:rate=25", "-t", "0.4",
            "-pix_fmt", "yuv420p", str(path),
        ],
        check=True,
    )
    frames = list(read_frames(
        path, PAL.pixels, PAL.active_lines, PAL.fps, seconds=0.4,
    ))
    assert len(frames) >= 8
    assert frames[0].shape == (PAL.active_lines, PAL.pixels)
    assert frames[0].dtype == np.uint8