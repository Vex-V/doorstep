import asyncio

from doorstep.ring.api import HistoryEvent
from doorstep.ring.poller import HistoryPoller
from doorstep.core.store import Store


class FakeRing:
    def __init__(self):
        self.events = []

    async def history(self, device_id, event_types=None, limit=50):
        return [e for e in self.events if e.device_id == device_id][::-1][:limit]


def test_poller_feeds_new_events_only(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.put_camera("front", "Front door", "doorbell")
    ring = FakeRing()
    ring.events.append(HistoryEvent("h1", "front", "motion", 1000, 5000, "human"))
    handled = []

    async def handle(hook):
        handled.append(hook)
        store.put_event(hook.event_id, hook.device_id, "x", hook.timestamp_ms)
        return hook.event_id

    poller = HistoryPoller(ring, store, handle)

    async def go():
        assert await poller.run_once() == 0          # what was there at start-up is skipped
        ring.events.append(HistoryEvent("h2", "front", "ding", 9000, 15000))
        assert await poller.run_once() == 1
        assert await poller.run_once() == 0          # seen once, handled once
    asyncio.run(go())

    (hook,) = handled
    assert hook.type == "button_press" and hook.timestamp_ms == 9000
    assert hook.event_id == "front_ding_9000"         # the id a Ring webhook would carry
    assert store.event("front_ding_9000")["end_ms"] == 15000


def test_backfill_takes_existing_history(tmp_path):
    store = Store(tmp_path / "db.sqlite3")
    store.put_camera("front", "Front door", "doorbell")
    ring = FakeRing()
    ring.events.append(HistoryEvent("h1", "front", "motion", 1000, 5000))

    async def handle(hook):
        return None

    assert asyncio.run(HistoryPoller(ring, store, handle, backfill=True).run_once()) == 1
