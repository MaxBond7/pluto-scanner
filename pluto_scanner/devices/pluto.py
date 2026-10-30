"""Real ADALM-PLUTO worker (pyadi-iio / libiio)."""
from __future__ import annotations

import ctypes.util
import logging
import os
import time

import numpy as np

from ..model import DeviceConfig, IQBlock
from .base import DeviceWorker

log = logging.getLogger(__name__)

# AD936x is a 12-bit ADC.  pyadi-iio returns raw counts; normalise them so the
# same dBFS display and detector work for both the simulator and real hardware.
PLUTO_ADC_FULL_SCALE = 2048.0


def _ensure_pylibiio_windows() -> None:
    """Work around pylibiio 1.0's Windows libc lookup.

    ``ctypes.util.find_library('c')`` returns None on Windows.  pylibiio then
    calls ``CDLL(None)``, which raises before libiio is ever used.  Patch the
    lookup only for pylibiio's libc request; libiio1.dll itself is found
    normally in System32.

    Use the UCRT, not the legacy msvcrt.dll: libiio1.dll imports the
    api-ms-win-crt runtime, and freeing its XML buffer with a different CRT
    corrupts the heap at shutdown (0xC0000374).
    """
    if os.name != "nt":
        return
    if getattr(ctypes.util.find_library, "_pluto_scanner_patch", False):
        return
    try:
        ctypes.CDLL("ucrtbase.dll")
        libc_name = "ucrtbase.dll"
    except Exception:
        libc_name = "msvcrt.dll"
    original = ctypes.util.find_library

    def patched(name: str):
        if name in ("c", "libc"):
            return libc_name
        return original(name)

    patched._pluto_scanner_patch = True  # type: ignore[attr-defined]
    ctypes.util.find_library = patched


def scan_pluto_uris() -> list[str]:
    """Best-effort libiio context scan.

    Different pyadi-iio/pylibiio versions expose different helpers, so this
    tries the common ones and returns an empty list instead of failing the UI.
    """
    _ensure_pylibiio_windows()
    uris: list[str] = []
    try:
        import iio  # type: ignore
        contexts = iio.scan_contexts()
        if isinstance(contexts, dict):
            uris.extend(str(k) for k in contexts.keys())
        else:
            uris.extend(str(x) for x in contexts)
    except Exception as exc:
        log.debug("iio.scan_contexts failed: %s", exc)
    if not uris:
        try:
            import adi  # type: ignore
            scan = getattr(adi, "scan", None)
            if scan is not None:
                found = scan()
                if isinstance(found, dict):
                    uris.extend(str(k) for k in found.keys())
                else:
                    uris.extend(str(x) for x in found)
        except Exception as exc:
            log.debug("adi.scan failed: %s", exc)
    # Stable, unique
    seen: set[str] = set()
    result = []
    for u in uris:
        if u not in seen:
            seen.add(u)
            result.append(u)
    return result


class PlutoWorker(DeviceWorker):
    def __init__(self, config: DeviceConfig) -> None:
        super().__init__(config)
        self.sdr = None
        self.actual_info: dict = {}

    def _apply_command(self, name: str, value) -> None:
        if self.sdr is None:
            return
        if name == "center":
            self.sdr.rx_lo = int(value)
            self.center_freq = int(value)
        elif name == "sample_rate":
            self.sdr.sample_rate = int(value)
            self.sample_rate = int(value)
            self.sdr.rx_buffer_size = max(4096, int(self.sample_rate * 0.08))
        elif name == "bandwidth":
            self.bandwidth = float(value)
            self.sdr.rx_rf_bandwidth = int(value)
        elif name == "buffer_size":
            self.sdr.rx_buffer_size = max(4096, int(value))
        elif name == "gain":
            self.gain = float(value)
            self._set_gain(self.gain)

    def _set_gain(self, gain_db: float) -> None:
        assert self.sdr is not None
        try:
            if hasattr(self.sdr, "gain_control_mode_chan0"):
                self.sdr.gain_control_mode_chan0 = "manual"
            elif hasattr(self.sdr, "gain_control_mode_chan"):
                self.sdr.gain_control_mode_chan.attrs["gain_control_mode"] = "manual"
        except Exception:
            pass
        for name in ("rx_hardwaregain_chan0", "rx_hardwaregain_chan"):
            try:
                attr = getattr(self.sdr, name, None)
                if attr is None:
                    continue
                if hasattr(attr, "attrs"):
                    attr.attrs["hardwaregain"] = float(gain_db)
                else:
                    setattr(self.sdr, name, int(round(gain_db)))
                return
            except Exception:
                continue
        try:
            self.sdr.rx_hardwaregain = float(gain_db)
        except Exception:
            pass

    def run(self) -> None:
        self._set_status("starting")
        _ensure_pylibiio_windows()
        try:
            import adi  # type: ignore
        except Exception as exc:
            self.error.emit(
                self.config.device_id,
                "pyadi-iio is not installed. Run: "
                "pip install pyadi-iio  (original error: %s)" % exc,
            )
            self._set_status("error")
            return

        try:
            uri = self.config.uri.strip()
            self.sdr = adi.Pluto(uri=uri) if uri else adi.Pluto()
            self.sdr.sample_rate = int(self.config.sample_rate)
            self.sdr.rx_lo = int(self.config.center_freq)
            self.sdr.rx_rf_bandwidth = int(self.config.bandwidth)
            self.sdr.rx_buffer_size = max(
                4096, int(self.config.sample_rate * 0.08)
            )
            self._set_gain(self.config.gain)
            self._set_status("running")
            self.info_ready.emit(self.config.device_id, {
                "center_freq": float(self.sdr.rx_lo),
                "sample_rate": float(self.sdr.sample_rate),
                "gain": float(self.config.gain),
                "uri": uri,
            })
            while not self._stop_event.is_set():
                self._process_commands()
                if self._stop_event.is_set():
                    break
                data = self.sdr.rx()
                iq = np.asarray(data, dtype=np.complex64).ravel()
                if iq.size == 0:
                    time.sleep(0.01)
                    continue
                iq = iq / PLUTO_ADC_FULL_SCALE
                self.iq_ready.emit(IQBlock(
                    device_id=self.config.device_id,
                    samples=iq,
                    sample_rate=float(self.sdr.sample_rate),
                    center_freq=float(self.sdr.rx_lo),
                    timestamp=time.time(),
                ))
        except Exception as exc:
            log.exception("Pluto worker failed")
            self.error.emit(self.config.device_id, f"Pluto: {exc}")
            self._set_status("error")
        finally:
            try:
                if self.sdr is not None:
                    self.sdr.rx_destroy_buffer()
            except Exception:
                pass
            self.sdr = None
            self._set_status("stopped")
