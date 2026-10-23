"""Event History as an event source, for when Ring sends no webhooks -- the
Developer Playground sends none. Every `interval_s`, each camera's recent
history is read; an event not seen before is handed to the worker exactly as
a webhook would be, so nothing downstream knows which way it came.

The first read only records what is already there, unless `backfill`: an app
starting up should not alert on yesterday."""

from __future__ import annotations

import asyncio
import logging
from typing import Awaitable, Callable, Optional

from .webhooks import Webhook

log = logging.getLogger("doorstep.poller")


def as_webhook(device_id: str, event_type: str, start_ms: int,
               subtype: Optional[str], history_id: str) -> Webhook:
    """A history event in the shape a webhook arrives in. The data id follows
    Ring's webhook format, so a webhook for the same event deduplicates."""
    ding = event_type == "ding"
    return Webhook(request_id=f"history:{history_id}",
                   type="button_press" if ding else "motion_detected",
                   device_id=device_id, timestamp_ms=start_ms, subtype=subtype,
                   raw={"data": {"id": f"{device_id}_{'ding' if ding else 'motion'}"
                                       f"_{start_ms}"}})


class HistoryPoller:
    def __init__(self, ring, store, handle: Callable[[Webhook], Awaitable[Optional[str]]],
                 interval_s: float = 15.0, backfill: bool = False) -> None:
        self.ring = ring
        self.store = store
        self.handle = handle
        self.interval_s = interval_s
        self.backfill = backfill
        self.seen: set[str] = set()
        self.started = False
        self.found = 0

    async def run_once(self, now_ms: int = 0) -> int:
        """One pass over every camera; returns the number of new events."""
        new = 0
        for cam in self.store.cameras():
            if cam.get("kind") == "chime":
                continue
            try:
                events = await self.ring.history(cam["id"], ["motion", "ding"], limit=25)
            except Exception as exc:
                log.warning("history for %s failed: %s", cam["id"], exc)
                continue
            for h in sorted(events, key=lambda h: h.start_ms):   # oldest first
                if h.id in self.seen:
                    continue
                self.seen.add(h.id)
                if not self.started and not self.backfill:
                    continue
                hook = as_webhook(cam["id"], h.event_type, h.start_ms, h.subtype, h.id)
                if not self.store.first_delivery(hook.request_id, now_ms or h.start_ms):
                    continue
                event_id = await self.handle(hook)
                if event_id and h.end_ms:
                    self.store.update_event(event_id, end_ms=h.end_ms)
                new += 1
        self.started = True
        self.found += new
        return new

    async def run(self) -> None:
        while True:
            try:
                n = await self.run_once()
                if n:
                    log.info("history: %d new event(s)", n)
            except Exception:
                log.exception("history poll failed")
            await asyncio.sleep(self.interval_s)
