"""The running server's state: what the lifespan builds and every route reads."""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from .core import clock as clocks
from .core.config import settings
from .ring.api import RingAPI

log = logging.getLogger("doorstep")


class State:
    store: Any = None                            # core.store.Store
    ring: Optional[RingAPI] = None               # RingClient
    worker: Any = None                           # worker.Worker
    poller: Any = None                           # Event History polling (Playground)
    poll_task: Optional[asyncio.Task] = None
    sim: Optional[dict[str, Any]] = None         # the Ring simulator's last state
    sim_task: Optional[asyncio.Task] = None


state = State()


async def sync_sim() -> None:
    """Read the Ring simulator's state and put our clock on its time."""
    import httpx

    s = settings()
    async with httpx.AsyncClient(timeout=5) as http:
        doc = (await http.get(f"{s.ring_api_base}/sim/state")).json()
    c = doc["clock"]
    clock = clocks.clock()
    if isinstance(clock, clocks.SyncedClock):
        clock.anchor(c["now_ms"], c["speed"] if c["running"] else 0.0)
    state.sim = doc


async def follow_sim() -> None:
    while True:
        await asyncio.sleep(2)
        try:
            await sync_sim()
        except Exception as exc:
            log.warning("could not read the Ring simulator's clock: %s", exc)


def sim_view() -> Optional[dict[str, Any]]:
    """The Ring simulator's clock, when that is what Doorstep is connected to."""
    if state.sim is None:
        return None
    c = state.sim["clock"]
    return {"title": state.sim["title"], "running": c["running"], "speed": c["speed"]}
