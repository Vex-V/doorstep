"""What time it is. Real time against Ring; the Ring simulator's scripted day
when that is what Doorstep is connected to. Rules, the poller and the
scheduler only ever ask this module."""

from __future__ import annotations

import asyncio
import time
from datetime import datetime, timezone
from typing import Optional


class Clock:
    """Wall-clock time in epoch milliseconds, and sleeps measured in it."""

    speed = 1.0

    def now_ms(self) -> int:
        return int(time.time() * 1000)

    async def sleep(self, seconds: float) -> None:
        await asyncio.sleep(max(0.0, seconds) / self.speed)


class SyncedClock(Clock):
    """Another process's simulated time (the Ring simulator's), re-anchored
    whenever it is read from there; paused while that clock is paused."""

    def __init__(self, at_ms: int, speed: float = 0.0) -> None:
        self.anchor(at_ms, speed)

    def anchor(self, at_ms: int, speed: float) -> None:
        self._at_ms, self.speed, self._t0 = int(at_ms), float(speed), time.monotonic()

    def now_ms(self) -> int:
        return self._at_ms + int((time.monotonic() - self._t0) * 1000 * self.speed)

    async def sleep(self, seconds: float) -> None:
        if self.speed > 0:
            await asyncio.sleep(max(0.0, seconds) / self.speed)
        else:                    # paused: wake soon, in case it starts
            await asyncio.sleep(min(max(0.0, seconds), 1.0))


_clock: Clock = Clock()


def clock() -> Clock:
    return _clock


def use(value: Optional[Clock]) -> None:
    global _clock
    _clock = value or Clock()


def now_ms() -> int:
    return _clock.now_ms()


def to_dt(ms: int, tz) -> datetime:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).astimezone(tz)


def day_of(ms: int, tz) -> str:
    return to_dt(ms, tz).strftime("%Y-%m-%d")


def day_bounds(day: str, tz) -> tuple[int, int]:
    """[start, end) of a local day, in epoch ms."""
    start = datetime.strptime(day, "%Y-%m-%d").replace(tzinfo=tz)
    end = start.replace(hour=23, minute=59, second=59, microsecond=999000)
    return int(start.timestamp() * 1000), int(end.timestamp() * 1000) + 1


def minutes_of_day(ms: int, tz) -> int:
    t = to_dt(ms, tz)
    return t.hour * 60 + t.minute


def hhmm(ms: int, tz) -> str:
    return to_dt(ms, tz).strftime("%H:%M")
