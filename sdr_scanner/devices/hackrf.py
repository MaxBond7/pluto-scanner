# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""HackRF One backend.

The Pluto talks through pyadi-iio; the HackRF is a plain C library
(``libhackrf``) and its Python bindings are either Linux-only or need extra
packages.  This module therefore talks to the library directly with ctypes —
no pip dependency, one DLL on Windows.

What it unlocks over the Pluto:

* 2–20 MS/s instead of the ~6 MS/s a Pluto sustains over USB 2.0;
* 1 MHz – 6 GHz tuning;
* enough bandwidth to capture OcuSync hops and, later, decode DJI DroneID
  even when Remote ID is disabled.

The adapter only receives.  It never starts a transmit stream.
"""
from __future__ import annotations

import ctypes
import os
import sys
import threading
import time
from pathlib import Path

import numpy as np

from ..model import DeviceConfig, IQBlock
from .base import DeviceWorker

HACKRF_MIN_RATE = 2.0e6
HACKRF_MAX_RATE = 20.0e6
HACKRF_MIN_FREQ = 1.0e6
HACKRF_MAX_FREQ = 6.0e9

# libhackrf only accepts these baseband filter values.
BASEBAND_FILTERS = (
    1_750_000, 2_500_000, 3_500_000, 5_000_000, 5_500_000, 6_000_000,
    7_000_000, 8_000_000, 9_000_000, 10_000_000, 12_000_000, 14_000_000,
    15_000_000, 20_000_000, 24_000_000, 28_000_000,
)

# The 8-bit ADC is scaled like the Pluto's 12-bit one: |1.0| is full scale.
HACKRF_FULL_SCALE = 128.0
BLOCK_SECONDS = 0.02


class _Transfer(ctypes.Structure):
    _fields_ = [
        ("device", ctypes.c_void_p),
        ("buffer", ctypes.POINTER(ctypes.c_byte)),
        ("buffer_length", ctypes.c_int),
        ("valid_length", ctypes.c_int),
        ("rx_ctx", ctypes.c_void_p),
        ("tx_ctx", ctypes.c_void_p),
    ]


class _DeviceList(ctypes.Structure):
    # Only the prefix used by this module.  The C struct has more fields, but
    # ctypes is happy to under-declare a pointer target.
    _fields_ = [
        ("serial_numbers", ctypes.POINTER(ctypes.c_char_p)),
        ("usb_board_ids", ctypes.c_void_p),
        ("usb_device_index", ctypes.POINTER(ctypes.c_int)),
        ("devicecount", ctypes.c_int),
        ("usb_devices", ctypes.c_void_p),
        ("usb_devicecount", ctypes.c_int),
    ]


_RX_CALLBACK = ctypes.CFUNCTYPE(ctypes.c_int, ctypes.POINTER(_Transfer))
_LIB: ctypes.CDLL | None = None
_LIB_LOCK = threading.Lock()


# ------------------------------------------------------------------ helpers
def _library_candidates() -> list[str]:
    names: list[str] = []
    custom = os.environ.get("HACKRF_DLL", "").strip()
    if custom:
        names.append(custom)
    roots = [
        Path(sys.executable).resolve().parent,
        Path(__file__).resolve().parents[2],
        Path.cwd(),
    ]
    if os.name == "nt":
        names.append("hackrf.dll")
        for root in roots:
            names.append(str(root / "hackrf.dll"))
            names.append(str(root / "_internal" / "hackrf.dll"))
            names.append(str(root / "dist" / "SDRScanner" / "hackrf.dll"))
            names.append(str(
                root / "dist" / "SDRScanner" / "_internal" / "hackrf.dll"
            ))
    else:
        names.extend(("libhackrf.so.0", "libhackrf.so", "libhackrf.dylib"))
        # macOS builds usually put it in /usr/local/lib, which the loader
        # already searches.
    return names


def _ensure_library() -> ctypes.CDLL:
    """Load libhackrf once and describe what the worker needs."""
    global _LIB
    with _LIB_LOCK:
        if _LIB is not None:
            return _LIB
        errors: list[str] = []
        loader = ctypes.WinDLL if os.name == "nt" else ctypes.CDLL
        for name in _library_candidates():
            try:
                library = loader(name)
            except OSError as exc:
                errors.append(f"{name}: {exc}")
                continue
            _describe(library)
            _LIB = library
            return library
        raise RuntimeError(
            "не найдена libhackrf (hackrf.dll). Установите hackrf-tools "
            "или положите DLL рядом с программой; подробности — "
            "docs/HACKRF.md. " + "; ".join(errors[:3])
        )


def _describe(library: ctypes.CDLL) -> None:
    library.hackrf_init.restype = ctypes.c_int
    library.hackrf_init.argtypes = []
    library.hackrf_exit.restype = ctypes.c_int
    library.hackrf_exit.argtypes = []
    library.hackrf_open.restype = ctypes.c_int
    library.hackrf_open.argtypes = [ctypes.POINTER(ctypes.c_void_p)]
    library.hackrf_open_by_serial.restype = ctypes.c_int
    library.hackrf_open_by_serial.argtypes = [
        ctypes.c_char_p, ctypes.POINTER(ctypes.c_void_p),
    ]
    library.hackrf_close.restype = ctypes.c_int
    library.hackrf_close.argtypes = [ctypes.c_void_p]
    # libhackrf returns the list pointer directly; it takes no arguments.
    library.hackrf_device_list.restype = ctypes.POINTER(_DeviceList)
    library.hackrf_device_list.argtypes = []
    library.hackrf_device_list_free.restype = None
    library.hackrf_device_list_free.argtypes = [ctypes.POINTER(_DeviceList)]
    library.hackrf_set_freq.restype = ctypes.c_int
    library.hackrf_set_freq.argtypes = [ctypes.c_void_p, ctypes.c_uint64]
    library.hackrf_set_sample_rate.restype = ctypes.c_int
    library.hackrf_set_sample_rate.argtypes = [ctypes.c_void_p, ctypes.c_double]
    library.hackrf_set_baseband_filter_bandwidth.restype = ctypes.c_int
    library.hackrf_set_baseband_filter_bandwidth.argtypes = [
        ctypes.c_void_p, ctypes.c_uint32,
    ]
    library.hackrf_set_amp_enable.restype = ctypes.c_int
    library.hackrf_set_amp_enable.argtypes = [ctypes.c_void_p, ctypes.c_uint8]
    library.hackrf_set_lna_gain.restype = ctypes.c_int
    library.hackrf_set_lna_gain.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    library.hackrf_set_vga_gain.restype = ctypes.c_int
    library.hackrf_set_vga_gain.argtypes = [ctypes.c_void_p, ctypes.c_uint32]
    library.hackrf_start_rx.restype = ctypes.c_int
    library.hackrf_start_rx.argtypes = [
        ctypes.c_void_p, _RX_CALLBACK, ctypes.c_void_p,
    ]
    library.hackrf_stop_rx.restype = ctypes.c_int
    library.hackrf_stop_rx.argtypes = [ctypes.c_void_p]
    library.hackrf_is_streaming.restype = ctypes.c_int
    library.hackrf_is_streaming.argtypes = [ctypes.c_void_p]


def clamp_rate(hz: float) -> float:
    return float(min(HACKRF_MAX_RATE, max(HACKRF_MIN_RATE, float(hz))))


def clamp_freq(hz: float) -> float:
    return float(min(HACKRF_MAX_FREQ, max(HACKRF_MIN_FREQ, float(hz))))


def snap_filter_bw(hz: float) -> int:
    """Smallest allowed baseband filter that still covers ``hz``."""
    wanted = int(max(1.0, float(hz)))
    for value in BASEBAND_FILTERS:
        if value >= wanted:
            return value
    return BASEBAND_FILTERS[-1]


def gain_to_stages(gain_db: float) -> tuple[int, int, bool]:
    """Map the app's single gain slider to LNA, VGA and the 14 dB amp.

    The UI slider is 0–73.  LNA stays at 16 dB (a good noise figure without
    overloading on city noise); the rest goes into VGA in 2 dB steps, and the
    front-end amplifier is only used at the very top.
    """
    value = max(0.0, min(90.0, float(gain_db)))
    lna = 16
    vga = int(round(min(62.0, max(0.0, value)) / 2.0) * 2)
    amp = bool(value >= 70.0)
    return lna, vga, amp


def probe_hackrf() -> dict:
    """Read-only probe: library, serials, and a human-readable error."""
    try:
        library = _ensure_library()
    except Exception as exc:
        return {"ok": False, "error": str(exc), "serials": [], "library": ""}
    serials: list[str] = []
    try:
        status = library.hackrf_init()
        if status != 0:
            return {
                "ok": False, "error": f"hackrf_init: {status}",
                "serials": [], "library": getattr(library, "_name", ""),
            }
        device_list = library.hackrf_device_list()
        if not device_list:
            return {
                "ok": False, "error": "hackrf_device_list failed",
                "serials": [], "library": getattr(library, "_name", ""),
            }
        try:
            count = int(device_list.contents.devicecount)
            for index in range(count):
                raw = device_list.contents.serial_numbers[index]
                if raw:
                    serials.append(raw.decode("utf-8", "replace"))
        finally:
            library.hackrf_device_list_free(device_list)
        return {
            "ok": True, "error": "", "serials": serials,
            "library": str(getattr(library, "_name", "")),
        }
    except Exception as exc:
        return {"ok": False, "error": str(exc), "serials": [], "library": ""}
    finally:
        try:
            library.hackrf_exit()
        except Exception:
            pass


# ------------------------------------------------------------------- worker
class HackRFWorker(DeviceWorker):
    """Receive-only HackRF worker producing 20 ms complex blocks."""

    def __init__(self, config: DeviceConfig) -> None:
        super().__init__(config)
        self.sdr: ctypes.c_void_p | None = None
        self.actual_info: dict = {}
        self._callback = None
        self._pending: list[np.ndarray] = []
        self._pending_len = 0
        self._block_len = max(4096, int(clamp_rate(config.sample_rate)
                                     * BLOCK_SECONDS))
        self._serial = str(config.uri or "").strip()

    # ------------------------------------------------------------ commands
    @staticmethod
    def _require(status: int, what: str) -> None:
        if int(status) != 0:
            raise RuntimeError(f"{what}: {status}")

    def _apply_command(self, name: str, value) -> None:
        library = _ensure_library()
        if self.sdr is None:
            return
        if name == "center":
            freq = clamp_freq(value)
            self._require(library.hackrf_set_freq(self.sdr, int(freq)),
                          "set_freq")
            self.center_freq = freq
        elif name == "sample_rate":
            rate = clamp_rate(value)
            self._block_len = max(4096, int(rate * BLOCK_SECONDS))
            if abs(rate - self.sample_rate) < 1.0:
                # Deep look usually restores the same rate.  Restarting the
                # USB stream for an unchanged value can fail with
                # HACKRF_ERROR_OTHER while stop_rx is still unwinding.
                return
            streaming = bool(library.hackrf_is_streaming(self.sdr) == 1)
            if streaming:
                self._require(library.hackrf_stop_rx(self.sdr), "stop_rx")
                for _ in range(50):
                    if library.hackrf_is_streaming(self.sdr) != 1:
                        break
                    time.sleep(0.02)
                time.sleep(0.05)
            self.sample_rate = rate
            self._require(
                library.hackrf_set_sample_rate(self.sdr, rate),
                "set_sample_rate",
            )
            # During shutdown the worker is about to close the device; do not
            # restart the stream just to satisfy a queued restore command.
            if streaming and not self._stop_event.is_set():
                self._start_rx(library)
        elif name == "bandwidth":
            self.bandwidth = float(value)
            self._require(
                library.hackrf_set_baseband_filter_bandwidth(
                    self.sdr, snap_filter_bw(value)
                ),
                "set_baseband_filter_bandwidth",
            )
        elif name == "gain":
            self.gain = float(value)
            self._apply_gain()
        elif name == "buffer_size":
            self._block_len = max(4096, int(value))

    def _start_rx(self, library: ctypes.CDLL) -> None:
        """Start RX, retrying after a rate change.

        libhackrf occasionally returns HACKRF_ERROR_OTHER when ``start_rx``
        follows ``stop_rx`` immediately; increasing pauses make the retry
        reliable without changing the requested settings.
        """
        status = 0
        for delay in (0.0, 0.1, 0.3, 0.7):
            if delay:
                time.sleep(delay)
            status = library.hackrf_start_rx(self.sdr, self._callback, None)
            if status == 0:
                return
        self._require(status, "start_rx")

    def _apply_gain(self) -> None:
        library = _ensure_library()
        if self.sdr is None:
            return
        lna, vga, amp = gain_to_stages(self.gain)
        self._require(library.hackrf_set_lna_gain(self.sdr, lna), "set_lna_gain")
        self._require(library.hackrf_set_vga_gain(self.sdr, vga), "set_vga_gain")
        self._require(
            library.hackrf_set_amp_enable(self.sdr, 1 if amp else 0),
            "set_amp_enable",
        )

    # -------------------------------------------------------------- receive
    def _on_transfer(self, transfer_ptr) -> int:
        try:
            transfer = transfer_ptr.contents
            length = int(transfer.valid_length) or int(transfer.buffer_length)
            if length <= 0:
                return 0
            raw = ctypes.string_at(transfer.buffer, length)
            pairs = (len(raw) // 2) * 2
            if pairs == 0:
                return 0
            data = np.frombuffer(raw[:pairs], dtype=np.int8)
            iq = (
                data[0::2].astype(np.float32)
                + 1j * data[1::2].astype(np.float32)
            ) / HACKRF_FULL_SCALE
            self._pending.append(iq.astype(np.complex64))
            self._pending_len += iq.size
            while self._pending_len >= self._block_len:
                block = np.concatenate(self._pending)
                chunk = block[: self._block_len]
                rest = block[self._block_len:]
                self._pending = [rest] if rest.size else []
                self._pending_len = int(rest.size)
                self.iq_ready.emit(IQBlock(
                    device_id=self.config.device_id,
                    samples=chunk,
                    sample_rate=float(self.sample_rate),
                    center_freq=float(self.center_freq),
                    timestamp=time.time(),
                ))
        except Exception:
            # Never let an exception escape into libhackrf's C thread.
            pass
        return 0

    def run(self) -> None:
        self._set_status("starting")
        try:
            library = _ensure_library()
        except Exception as exc:
            self.error.emit(self.config.device_id, str(exc))
            self._set_status("error")
            return
        try:
            status = library.hackrf_init()
            if status != 0:
                raise RuntimeError(f"hackrf_init: {status}")
            device = ctypes.c_void_p()
            if self._serial:
                status = library.hackrf_open_by_serial(
                    self._serial.encode("utf-8"), ctypes.byref(device)
                )
            else:
                status = library.hackrf_open(ctypes.byref(device))
            if status != 0:
                raise RuntimeError(
                    "hackrf_open: " + str(status)
                    + (" (устройство занято?)" if status == -6 else "")
                )
            self.sdr = device
            # Keep the reported values equal to what the device accepted;
            # otherwise the monitor compares 20.48 against the 20.0 that
            # libhackrf returns and silently drops every block.
            self.sample_rate = clamp_rate(self.config.sample_rate)
            self.center_freq = clamp_freq(self.config.center_freq)
            self.bandwidth = float(self.config.bandwidth)
            self._block_len = max(4096, int(self.sample_rate * BLOCK_SECONDS))
            self._require(
                library.hackrf_set_sample_rate(self.sdr, self.sample_rate),
                "set_sample_rate",
            )
            self._require(
                library.hackrf_set_freq(self.sdr, int(self.center_freq)),
                "set_freq",
            )
            self._require(
                library.hackrf_set_baseband_filter_bandwidth(
                    self.sdr, snap_filter_bw(self.bandwidth)
                ),
                "set_baseband_filter_bandwidth",
            )
            self._apply_gain()
            self._callback = _RX_CALLBACK(self._on_transfer)
            self._start_rx(library)
            self._set_status("running")
            self.info_ready.emit(self.config.device_id, {
                "center_freq": float(self.center_freq),
                "sample_rate": float(self.sample_rate),
                "gain": float(self.gain),
                "uri": self._serial,
                "library": str(getattr(library, "_name", "")),
            })
            while not self._stop_event.is_set():
                self._process_commands()
                time.sleep(0.05)
        except Exception as exc:
            self.error.emit(self.config.device_id, f"HackRF: {exc}")
            self._set_status("error")
        finally:
            try:
                if self.sdr is not None:
                    library.hackrf_stop_rx(self.sdr)
                    library.hackrf_close(self.sdr)
            except Exception:
                pass
            try:
                library.hackrf_exit()
            except Exception:
                pass
            self.sdr = None
            self._set_status("stopped")


__all__ = [
    "BASEBAND_FILTERS",
    "HackRFWorker",
    "clamp_freq",
    "clamp_rate",
    "gain_to_stages",
    "probe_hackrf",
    "snap_filter_bw",
]
