# Copyright (C) 2026 Pluto Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Deep look: listen for one second on one frequency and describe behaviour.

The 20 ms blocks of the live monitor are enough for spectrum shape, but not
for rhythm: hop cadence, duty cycle and regularity need a longer listen.
This module retunes the given session for about a second, collects the IQ and
runs :mod:`pluto_scanner.ml.behavior`.

It is deliberately synchronous: the caller is a modal event card, and a short
freeze with a busy cursor is simpler and safer than another worker thread.
"""
from __future__ import annotations

import time
from dataclasses import dataclass

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer

from ..ml.behavior import Behavior, analyze

SETTLE_MS = 350
TOLERANCE_HZ = 20e3


@dataclass
class DeepResult:
    ok: bool
    error: str
    freq_hz: float
    sample_rate: float
    behavior: Behavior | None
    verdict: str

    def text(self) -> str:
        if not self.ok or self.behavior is None:
            return f"Глубокий взгляд не удался: {self.error}"
        b = self.behavior
        text = (
            f"{self.freq_hz / 1e6:.3f} МГц, {self.sample_rate / 1e6:.2f} МС/с, "
            f"{b.frames * 0.00025:.2f} с\n"
            f"скважность {b.duty:.2f} · пачек {b.burst_rate_hz:.0f}/с · "
            f"занято {b.occupied:.2f} полосы · перескоков {b.hop_rate_hz:.0f}/с · "
            f"каналов {b.channels}\n"
        )
        if self.sample_rate < 15e6:
            text += (
                "перескоки и каналы при полосе меньше 15 МГц недостоверны: "
                "для них нужен HackRF (20 МГц).\n"
            )
        return text + f"вывод: {self.verdict}"


def interpret(behavior: Behavior, bandwidth: float) -> str:
    """A cautious reading of the numbers, never a promise."""
    if behavior.duty >= 0.70 and behavior.occupied >= 0.40:
        verdict = "непрерывный широкий линк — похоже на видеолинк дрона"
    elif behavior.duty <= 0.40 and behavior.occupied < 0.40:
        verdict = ("рваный или узкий сигнал — похоже на маяки точки доступа, "
                   "пульт или бытовое устройство")
    else:
        verdict = "неоднозначно: нужен более широкий захват или вторая полоса"
    if bandwidth >= 15e6 and behavior.channels >= 8 and behavior.hop_rate_hz >= 200:
        verdict += f"; прыгает по частоте ({behavior.channels} каналов)"
    return verdict


def capture(
    session,
    center_hz: float,
    *,
    seconds: float = 1.0,
    sample_rate: float = 6.144e6,
    timeout_s: float = 8.0,
) -> tuple[np.ndarray, float, str]:
    """Retune one session, collect IQ, restore the previous settings."""
    old_center = float(session.config.center_freq)
    old_rate = float(session.config.sample_rate)
    collected: list[np.ndarray] = []
    state = {"accept": False, "total": 0}
    need = int(float(sample_rate) * float(seconds))

    def on_iq(device_id: str, block) -> None:
        if device_id != session.config.device_id or not state["accept"]:
            return
        if abs(float(block.center_freq) - float(center_hz)) > TOLERANCE_HZ:
            return
        if abs(float(block.sample_rate) - float(sample_rate)) > 1.0:
            return
        chunk = np.asarray(block.samples, dtype=np.complex64)
        collected.append(chunk)
        state["total"] += chunk.size

    session.iq_ready.connect(on_iq)
    loop = QEventLoop()
    error = ""
    try:
        session.set_sample_rate(float(sample_rate))
        session.set_center_freq(float(center_hz))
        QTimer.singleShot(SETTLE_MS, lambda: state.__setitem__("accept", True))
        deadline = time.monotonic() + float(timeout_s)
        poll = QTimer()
        poll.setInterval(50)

        def tick() -> None:
            if state["total"] >= need:
                loop.quit()
            elif time.monotonic() > deadline:
                loop.quit()

        poll.timeout.connect(tick)
        poll.start()
        loop.exec()
        poll.stop()
        if state["total"] < need:
            error = ("не удалось собрать данные: плата не ответила "
                     "или частота вне диапазона")
    except Exception as exc:
        error = str(exc)
    finally:
        try:
            session.iq_ready.disconnect(on_iq)
        except (RuntimeError, TypeError):
            pass
        try:
            session.set_sample_rate(old_rate)
            session.set_center_freq(old_center)
        except Exception:
            pass

    if not collected:
        return np.empty(0, dtype=np.complex64), float(sample_rate), error
    data = np.concatenate(collected)
    return data[:need], float(sample_rate), error


def look(
    session,
    center_hz: float,
    *,
    seconds: float = 1.0,
    sample_rate: float = 6.144e6,
) -> DeepResult:
    data, rate, error = capture(
        session, center_hz, seconds=seconds, sample_rate=sample_rate,
    )
    wanted = float(rate) * float(seconds)
    if data.size < wanted * 0.25:
        return DeepResult(False, error or "нет данных", center_hz, rate, None, "")
    behavior = analyze(
        data, rate, max_seconds=float(seconds),
    )
    return DeepResult(
        True, "", center_hz, rate, behavior,
        interpret(behavior, rate),
    )


__all__ = ["DeepResult", "capture", "interpret", "look"]
