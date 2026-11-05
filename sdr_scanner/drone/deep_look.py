# Copyright (C) 2026 SDR Scanner contributors
# SPDX-License-Identifier: GPL-3.0-only
"""Deep look: listen for a few seconds on one frequency and describe behaviour.

The 20 ms blocks of the live monitor are enough for spectrum shape, but not
for rhythm: hop cadence, duty cycle and regularity need a longer listen.
This module retunes the given session, collects several short windows, runs
:mod:`sdr_scanner.ml.behavior` on each and reports the spread instead of a
single number.

It is deliberately synchronous: the caller is a modal event card, and a short
freeze with a busy cursor is simpler and safer than another worker thread.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
from PySide6.QtCore import QEventLoop, QTimer

from ..ml.behavior import Behavior, analyze
from ..recordings import RecordingInfo, new_recording_info, save_info

SETTLE_MS = 350
TOLERANCE_HZ = 20e3
DEFAULT_WINDOW_S = 0.7
DEFAULT_WINDOWS = 3
MAX_WINDOWS = 6


@dataclass
class DeepResult:
    ok: bool
    error: str
    freq_hz: float
    sample_rate: float
    behavior: Behavior | None
    verdict: str
    windows: list[Behavior] = field(default_factory=list)
    reasons: list[str] = field(default_factory=list)
    stability: str = ""
    background: float = 0.0
    data: np.ndarray | None = field(default=None, repr=False)
    path: str = ""
    device_id: str = ""
    device_name: str = ""
    device_kind: str = ""
    gain_db: float = 0.0

    def _range(self, values: list[float], fmt: str = "{:.2f}") -> str:
        if not values:
            return ""
        if len(values) == 1:
            return fmt.format(values[0])
        return f"{fmt.format(min(values))}–{fmt.format(max(values))}"

    def text(self) -> str:
        if not self.ok or self.behavior is None:
            return f"Глубокий взгляд не удался: {self.error}"
        b = self.behavior
        windows = self.windows or [b]
        duration = sum(window.frames for window in windows) * 0.00025
        duties = [window.duty for window in windows]
        occupied = [window.occupied for window in windows]
        text = (
            f"{self.freq_hz / 1e6:.3f} МГц · "
            f"{self.sample_rate / 1e6:.2f} МС/с · "
            f"{len(windows)} окн. · {duration:.2f} с\n"
            f"скважность {b.duty:.2f}"
            f" ({self._range(duties)} по окнам) · "
            f"занято {b.occupied:.2f} ({self._range(occupied)}) полосы · "
            f"пачек {b.burst_rate_hz:.0f}/с · "
            f"перескоков {b.hop_rate_hz:.0f}/с · каналов {b.channels}\n"
        )
        if self.sample_rate < 15e6:
            text += (
                "перескоки и каналы при полосе меньше 15 МГц недостоверны: "
                "для них нужен HackRF (20 МГц).\n"
            )
        if self.background >= 0.6:
            text += (
                f"карта фона: {self.background * 100:.0f}% — сигнал был "
                "в эфире всё время обучения фона.\n"
            )
        elif self.background > 0:
            text += f"карта фона: {self.background * 100:.0f}%.\n"
        if self.stability:
            text += self.stability + "\n"
        if self.reasons:
            text += "почему: " + " · ".join(self.reasons) + "\n"
        text += f"вывод: {self.verdict}"
        if self.path:
            text += f"\nIQ: {self.path}"
        return text


def _category(behavior: Behavior) -> str:
    if behavior.duty >= 0.70 and behavior.occupied >= 0.40:
        return "continuous"
    if behavior.duty <= 0.40 and behavior.occupied < 0.40:
        return "bursty"
    return "mixed"


def reasons(behavior: Behavior, bandwidth: float) -> list[str]:
    """Human-readable causes for the verdict, with the thresholds used."""
    result: list[str] = []
    if behavior.duty >= 0.70:
        result.append(f"скважность {behavior.duty:.2f} ≥ 0.70")
    elif behavior.duty <= 0.40:
        result.append(f"скважность {behavior.duty:.2f} ≤ 0.40")
    else:
        result.append(f"скважность {behavior.duty:.2f} в переходной зоне")
    if behavior.occupied >= 0.40:
        result.append(f"занято {behavior.occupied:.2f} ≥ 0.40 полосы")
    elif behavior.occupied < 0.40:
        result.append(f"занято {behavior.occupied:.2f} < 0.40 полосы")
    if bandwidth >= 15e6:
        if behavior.channels >= 8 and behavior.hop_rate_hz >= 200:
            result.append(
                f"перескоки {behavior.hop_rate_hz:.0f}/с, "
                f"{behavior.channels} каналов"
            )
        else:
            result.append(
                f"перескоков мало: {behavior.hop_rate_hz:.0f}/с, "
                f"{behavior.channels} каналов"
            )
    else:
        result.append("полоса < 15 МГц: перескоки не оцениваются")
    return result


def interpret(behavior: Behavior, bandwidth: float) -> str:
    """A cautious reading of the numbers, never a promise."""
    category = _category(behavior)
    if category == "continuous":
        verdict = "непрерывный широкий линк — похоже на видеолинк дрона"
    elif category == "bursty":
        verdict = ("рваный или узкий сигнал — похоже на маяки точки доступа, "
                   "пульт или бытовое устройство")
    else:
        verdict = "неоднозначно: нужен более широкий захват или вторая полоса"
    if bandwidth >= 15e6 and behavior.channels >= 8 and behavior.hop_rate_hz >= 200:
        verdict += f"; прыгает по частоте ({behavior.channels} каналов)"
    return verdict


def _stability(windows: list[Behavior]) -> str:
    if len(windows) < 2:
        return ""
    categories = [_category(window) for window in windows]
    if len(set(categories)) == 1:
        return f"стабильно: одинаковый характер во всех {len(windows)} окнах"
    counts: dict[str, int] = {}
    for category in categories:
        counts[category] = counts.get(category, 0) + 1
    parts = ", ".join(
        f"{counts[key]} из {len(categories)}"
        for key in ("continuous", "bursty", "mixed")
        if counts.get(key)
    )
    return f"нестабильно: {parts}"


def _median(values: list[float]) -> float:
    return float(np.median(np.asarray(values, dtype=np.float64)))


def _aggregate(windows: list[Behavior]) -> Behavior:
    return Behavior(
        duty=_median([window.duty for window in windows]),
        burst_rate_hz=_median([window.burst_rate_hz for window in windows]),
        burst_interval_cv=_median(
            [window.burst_interval_cv for window in windows]
        ),
        hop_rate_hz=_median([window.hop_rate_hz for window in windows]),
        channels=int(round(_median([window.channels for window in windows]))),
        occupied=_median([window.occupied for window in windows]),
        sync_khz=_median([window.sync_khz for window in windows]),
        sync_strength=_median([window.sync_strength for window in windows]),
        frames=sum(window.frames for window in windows),
    )


def capture(
    session,
    center_hz: float,
    *,
    seconds: float = DEFAULT_WINDOW_S,
    windows: int = DEFAULT_WINDOWS,
    sample_rate: float = 6.144e6,
    timeout_s: float = 12.0,
) -> tuple[np.ndarray, float, str]:
    """Retune one session, collect IQ, restore the previous settings."""
    old_center = float(session.config.center_freq)
    old_rate = float(session.config.sample_rate)
    collected: list[np.ndarray] = []
    state = {"accept": False, "total": 0}
    total_seconds = max(0.1, float(seconds)) * max(1, int(windows))
    need = int(float(sample_rate) * total_seconds)

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


def save_capture(
    result: DeepResult,
    out_dir: str | Path,
    *,
    label: str = "",
    notes: str = "",
) -> RecordingInfo | None:
    """Write the captured IQ as a normal recording, ready for labelling."""
    if not result.ok or result.data is None or result.data.size == 0:
        return None
    info = new_recording_info(
        out_dir,
        device_id=result.device_id or "deep-look",
        device_name=result.device_name or "глубокий взгляд",
        device_kind=result.device_kind or "deep-look",
        sample_rate=float(result.sample_rate),
        center_freq=float(result.freq_hz),
        gain_db=float(result.gain_db),
        bandwidth_hz=float(result.sample_rate),
    )
    data = np.asarray(result.data, dtype=np.complex64)
    data.tofile(info.cf32_path)
    info.samples = int(data.size)
    info.complete = True
    info.label = str(label or "")
    info.notes = str(notes or (
        f"Глубокий взгляд: {result.freq_hz / 1e6:.3f} МГц, "
        f"{result.sample_rate / 1e6:.2f} МС/с. {result.verdict}"
    ))
    save_info(info)
    result.path = info.cf32_path
    return info


def look(
    session,
    center_hz: float,
    *,
    seconds: float = DEFAULT_WINDOW_S,
    windows: int = DEFAULT_WINDOWS,
    sample_rate: float = 6.144e6,
    background: float = 0.0,
    gain_db: float = 0.0,
) -> DeepResult:
    windows = max(1, min(MAX_WINDOWS, int(windows)))
    seconds = max(0.1, min(3.0, float(seconds)))
    data, rate, error = capture(
        session, center_hz,
        seconds=seconds, windows=windows, sample_rate=sample_rate,
    )
    wanted = float(rate) * seconds * windows
    if data.size < wanted * 0.25:
        return DeepResult(
            False, error or "нет данных", center_hz, rate, None, "",
        )

    parts = np.array_split(data, windows)
    behaviors = [
        analyze(part, rate, max_seconds=seconds)
        for part in parts
        if part.size > 0
    ]
    behaviors = [item for item in behaviors if item.frames > 0]
    if not behaviors:
        return DeepResult(
            False, error or "окна слишком короткие", center_hz, rate, None, "",
        )
    aggregate = _aggregate(behaviors)
    config = session.config
    return DeepResult(
        True, "", center_hz, rate, aggregate,
        interpret(aggregate, rate),
        windows=behaviors,
        reasons=reasons(aggregate, rate),
        stability=_stability(behaviors),
        background=float(background),
        data=data,
        device_id=str(getattr(config, "device_id", "")),
        device_name=str(getattr(config, "name", "")),
        device_kind=str(getattr(config, "kind", "")),
        gain_db=float(getattr(config, "gain", gain_db) or gain_db),
    )


__all__ = [
    "DeepResult",
    "capture",
    "interpret",
    "look",
    "reasons",
    "save_capture",
]
