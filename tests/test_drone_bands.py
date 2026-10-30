"""Tests for drone band chunking."""
from __future__ import annotations

from pluto_scanner.drone.bands import (
    DRONE_BANDS,
    BANDS_BY_KEY,
    chunks_for_band,
    chunks_for_bands,
)


def test_every_chunk_stays_inside_its_band():
    for band in DRONE_BANDS:
        chunks = chunks_for_band(band, 20.48e6)
        assert chunks, band.key
        for chunk in chunks:
            assert chunk.start_hz >= band.start_hz - 1.0
            assert chunk.end_hz <= band.end_hz + 1.0
            assert chunk.end_hz > chunk.start_hz
            assert chunk.index < chunk.total


def test_chunks_cover_band_without_gaps():
    for band in DRONE_BANDS:
        chunks = chunks_for_band(band, 20.48e6)
        assert abs(chunks[0].start_hz - band.start_hz) <= 1.0
        assert abs(chunks[-1].end_hz - band.end_hz) <= 1.0
        for left, right in zip(chunks, chunks[1:]):
            assert right.start_hz <= left.end_hz + 1.0


def test_wide_band_needs_several_chunks_and_narrow_band_one():
    assert len(chunks_for_band(BANDS_BY_KEY["433"], 20.48e6)) == 1
    assert len(chunks_for_band(BANDS_BY_KEY["915"], 20.48e6)) == 2
    assert len(chunks_for_band(BANDS_BY_KEY["2.4"], 20.48e6)) >= 5
    assert len(chunks_for_band(BANDS_BY_KEY["5.8"], 20.48e6)) >= 9


def test_combined_chunks_are_ordered_by_band():
    bands = [BANDS_BY_KEY["433"], BANDS_BY_KEY["2.4"]]
    chunks = chunks_for_bands(bands, 20.48e6)
    assert chunks[0].band.key == "433"
    assert chunks[0].total == 1
    assert chunks[-1].band.key == "2.4"
    assert chunks[-1].total >= 5
