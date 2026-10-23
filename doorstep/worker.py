"""Everything that runs in the background.

    handle      a verified webhook -> an event row, queued for the clip path
    clips       one clip at a time through the clip path, then the rules engine
                and the visits tracker read its answers
    ticks       every simulated minute: persists checks, absent deadlines, missed
                visits, the 8 pm digest, retention
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Optional

from . import privacy
from .alerts.engine import Engine
from .alerts.notify import event_message
from .alerts.visits import Visits
from .answers import digest
from .core import clock as clocks
from .core.bus import bus
from .core.config import settings
from .footage import clips
from .ring.webhooks import Webhook

log = logging.getLogger("doorstep.worker")

DIGEST_AT = 20 * 60          # the digest, minutes after midnight


class Worker:
    def __init__(self, store, ring) -> None:
        self.store = store
        self.ring = ring
        self.engine = Engine(store, ring)
        self.visits = Visits(store, ring)
        self.queue: asyncio.Queue[str] = asyncio.Queue()
        self.tasks: list[asyncio.Task] = []
        self._reading: Optional[str] = None           # the clip being read now
        self._digesting = False
        self._polling = False                         # snapshots being asked about
        self._digested: set[str] = set()              # days written at 8 pm
        self._retained: set[str] = set()

    # -- events ---------------------------------------------------------------

    async def handle(self, hook: Webhook) -> Optional[str]:
        if hook.type not in ("motion_detected", "button_press"):
            bus.publish("family", {"type": "device", "event": hook.type,
                                   "device": hook.device_id})
            return None
        if not hook.device_id or hook.timestamp_ms is None:
            return None
        if self.store.camera(hook.device_id) is None:
            self.store.put_camera(hook.device_id, hook.device_id,
                                  "doorbell" if hook.type == "button_press" else "camera")
        kind = "ding" if hook.type == "button_press" else "motion"
        event_id = clips.safe_id(hook.event_id)
        if not self.store.put_event(event_id, hook.device_id, kind, hook.timestamp_ms,
                                    hook.subtype):
            return event_id                     # the same event, delivered twice
        bus.publish("family", event_message(self.store.event(event_id)))
        await self.queue.put(event_id)
        return event_id

    async def _clips(self) -> None:
        while True:
            event_id = await self.queue.get()
            self._reading = event_id
            try:
                await clips.process_clip(self.store, self.ring, [self.engine, self.visits],
                                         event_id)
            finally:
                self._reading = None
                self.queue.task_done()

    # -- the clock ------------------------------------------------------------

    async def tick(self, now: Optional[int] = None) -> None:
        now = clocks.now_ms() if now is None else now
        tz = settings().tz
        try:
            self._polling = True
            try:
                await self.engine.poll(now)
            finally:
                self._polling = False
            await self.engine.deadlines(now)
            await self.visits.deadlines(now)
        except Exception:
            log.exception("rules tick failed")
        day = clocks.day_of(now, tz)
        if clocks.minutes_of_day(now, tz) >= DIGEST_AT and day not in self._digested:
            self._digested.add(day)
            self._digesting = True
            try:
                await digest.make(self.store)
            except Exception:
                log.exception("the 8 pm digest failed")
            finally:
                self._digesting = False
        if day not in self._retained:
            self._retained.add(day)
            privacy.enforce_retention(self.store, now)

    async def _ticks(self) -> None:
        while True:
            await self.tick()
            await clocks.clock().sleep(60)

    def start(self) -> None:
        self.tasks = [asyncio.create_task(self._clips(), name="clips"),
                      asyncio.create_task(self._ticks(), name="ticks")]

    async def stop(self) -> None:
        for t in self.tasks:
            t.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def forget(self) -> None:
        """The timeline was cleared: the next 8 pm writes a digest again."""
        self._digested.clear()

    def status(self) -> dict[str, Any]:
        queued = self.queue.qsize()
        return {"queued": queued,
                "busy": bool(queued or self._reading or self._digesting or self._polling)}
