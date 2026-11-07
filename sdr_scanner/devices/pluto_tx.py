# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Bench transmitter on an ADALM-PLUTO.

This is not part of the passive receiver: it exists so the analogue video
chain can be checked on a desk (Pluto transmits, HackRF receives).  The
caller must keep the transmit power low and use antennas or an attenuator —
a direct cable into a receiver input can damage it.

The class owns one libiio context.  ``stop()`` mutes the DAC first: a Pluto+
can keep the last cyclic buffer playing after the host process is gone.
"""
from __future__ import annotations

import queue
import threading
import time

import numpy as np

from ..video.testcard import composite_field

DEFAULT_RATE = 20e6
DEFAULT_DEVIATION = 3.5e6
#: USB 2.0 on the Pluto cannot carry 20 MS/s of 16-bit I/Q (80 MB/s), so the
#: video stream runs at 6.144 MS/s: 24.6 MB/s fits, and the picture is still
#: about 300 pixels wide.
STREAM_RATE = 6.144e6
STREAM_BANDWIDTH = 2.2e6
STREAM_DEVIATION = 1.0e6


class PlutoTransmitter:
    """One Pluto transmitting a cyclic IQ buffer."""

    def __init__(self) -> None:
        self._sdr = None
        self._lock = threading.Lock()
        self.uri = ""

    @property
    def active(self) -> bool:
        return self._sdr is not None

    @staticmethod
    def available() -> bool:
        try:
            from .pluto import _ensure_pylibiio_windows

            _ensure_pylibiio_windows()
            import adi  # type: ignore  # noqa: F401
        except Exception:
            return False
        return True

    @staticmethod
    def _find_uris(scan) -> list[str]:
        """Scan a few times: the Pluto re-enumerates for a second or two."""
        for attempt in range(4):
            uris = [item for item in scan() if item.startswith("usb:")]
            if uris:
                return uris
            if attempt < 3:
                time.sleep(1.0)
        return []

    def start(self, iq: np.ndarray, rate: float, freq: float,
              gain_db: float = 0.0, amplitude: float = 0.5) -> str:
        """Start transmitting; returns the Pluto URI that was opened."""
        from .pluto import _ensure_pylibiio_windows, scan_pluto_uris

        _ensure_pylibiio_windows()
        import adi  # type: ignore

        uris = self._find_uris(scan_pluto_uris)
        if not uris:
            raise RuntimeError(
                "Pluto не найден по USB. Подключите плату и повторите."
            )
        uri = uris[0]
        sdr = adi.Pluto(uri=uri)
        try:
            sdr.sample_rate = int(rate)
            sdr.tx_rf_bandwidth = int(rate)
            sdr.tx_lo = int(freq)
            sdr.tx_hardwaregain_chan0 = float(gain_db)
            sdr.tx_cyclic_buffer = True
            data = np.asarray(iq, dtype=np.complex64) * float(amplitude) * 2 ** 14
            sdr.tx(data.astype(np.complex64))
        except Exception:
            try:
                sdr.tx_hardwaregain_chan0 = -89.75
                sdr.tx_destroy_buffer()
            except Exception:
                pass
            del sdr
            raise
        with self._lock:
            self._sdr = sdr
            self.uri = uri
        return uri

    def stop(self) -> None:
        with self._lock:
            sdr = self._sdr
            self._sdr = None
        if sdr is None:
            return
        try:
            sdr.tx_hardwaregain_chan0 = -89.75
        except Exception:
            pass
        try:
            sdr.tx_destroy_buffer()
        except Exception:
            pass
        try:
            del sdr
        except Exception:
            pass


class PlutoVideoStream:
    """Transmit a looping sequence of pictures.

    The Pluto has no buffer large enough for real video, so fields are built
    in a producer thread and pushed with a non-cyclic TX buffer of constant
    size.  The queue absorbs jitter between Python and the DAC.
    """

    def __init__(self) -> None:
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._lock = threading.Lock()
        self.error = ""

    @property
    def active(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def start(
        self,
        frames,
        standard,
        rate: float = STREAM_RATE,
        freq: float = 1241e6,
        gain_db: float = 0.0,
        amplitude: float = 0.5,
        deviation: float = STREAM_DEVIATION,
    ) -> None:
        self.stop()
        self._stop.clear()
        self.error = ""
        self._thread = threading.Thread(
            target=self._run,
            args=(list(frames), standard, rate, freq, gain_db,
                  amplitude, deviation),
            name="pluto-video-stream",
            daemon=True,
        )
        self._thread.start()

    def stop(self) -> None:
        self._stop.set()
        thread = self._thread
        self._thread = None
        if thread is not None and thread.is_alive():
            thread.join(timeout=3.0)

    def _run(self, frames, standard, rate, freq, gain_db, amplitude,
             deviation) -> None:
        from .pluto import _ensure_pylibiio_windows, scan_pluto_uris

        _ensure_pylibiio_windows()
        import adi  # type: ignore

        sdr = None
        producer = None
        try:
            uris = [item for item in scan_pluto_uris()
                    if item.startswith("usb:")]
            if not uris:
                raise RuntimeError(
                    "Pluto не найден по USB. Подключите плату и повторите."
                )
            if not frames:
                raise RuntimeError("нет кадров для передачи")
            sdr = adi.Pluto(uri=uris[0])
            sdr.sample_rate = int(rate)
            sdr.tx_rf_bandwidth = int(rate)
            sdr.tx_lo = int(freq)
            sdr.tx_hardwaregain_chan0 = float(gain_db)
            sdr.tx_cyclic_buffer = False

            chunks: queue.Queue = queue.Queue(maxsize=6)

            def produce() -> None:
                from ..video.analog import band_limit

                index = 0
                phase = 0.0
                count = len(frames)
                while not self._stop.is_set():
                    rows = frames[index % count]
                    if rows.dtype == np.uint8:
                        rows = rows.astype(np.float64) / 255.0
                    video = composite_field(
                        standard, rate, rows, index % 2,
                    )
                    index += 1
                    # Keep the FM spectrum inside the DAC band: at 6.144 MS/s
                    # there is no room for the 5 MHz detail of a full TV.
                    video = band_limit(video, rate, STREAM_BANDWIDTH)
                    step = 2.0 * np.pi * deviation * (video - 0.5) / rate
                    angle = np.cumsum(step) + phase
                    phase = float(angle[-1]) % (2.0 * np.pi)
                    iq = (np.exp(1j * angle) * amplitude * 2 ** 14)
                    iq = iq.astype(np.complex64)
                    while not self._stop.is_set():
                        try:
                            chunks.put(iq, timeout=0.1)
                            break
                        except queue.Full:
                            continue

            producer = threading.Thread(
                target=produce, name="pluto-video-produce", daemon=True,
            )
            producer.start()
            while not self._stop.is_set():
                try:
                    chunk = chunks.get(timeout=0.2)
                except queue.Empty:
                    continue
                sdr.tx(chunk)
        except Exception as exc:
            self.error = str(exc)
        finally:
            self._stop.set()
            if producer is not None and producer.is_alive():
                producer.join(timeout=2.0)
            if sdr is not None:
                try:
                    sdr.tx_hardwaregain_chan0 = -89.75
                except Exception:
                    pass
                try:
                    sdr.tx_destroy_buffer()
                except Exception:
                    pass
                try:
                    del sdr
                except Exception:
                    pass


__all__ = [
    "DEFAULT_DEVIATION",
    "DEFAULT_RATE",
    "PlutoTransmitter",
    "PlutoVideoStream",
]
