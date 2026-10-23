"""In-process publish/subscribe, behind the family page's server-sent event
stream (`family`: events, alerts, visits, rule states)."""

from __future__ import annotations

import asyncio
from typing import Any, AsyncIterator


class Bus:
    def __init__(self) -> None:
        self._subs: dict[str, set[asyncio.Queue]] = {}

    def publish(self, channel: str, message: dict[str, Any]) -> None:
        for q in list(self._subs.get(channel, ())):
            try:
                q.put_nowait(message)
            except asyncio.QueueFull:
                pass                      # a stalled page loses messages, not the server

    async def subscribe(self, channel: str) -> AsyncIterator[dict[str, Any]]:
        q: asyncio.Queue = asyncio.Queue(maxsize=200)
        self._subs.setdefault(channel, set()).add(q)
        try:
            while True:
                yield await q.get()
        finally:
            self._subs[channel].discard(q)


bus = Bus()
