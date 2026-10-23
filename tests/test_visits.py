"""Expected visits: arrivals and departures matched from the family's
description, a missed window alerting once, and the outcome on the pages."""

from __future__ import annotations

import asyncio

import pytest
from fastapi.testclient import TestClient

from doorstep.alerts import visits
from doorstep.alerts.visits import Visits
from doorstep.core import clock
from doorstep.core.store import Store


class FakeRing:
    def __init__(self):
        self.chimes = []

    async def chime(self, device, event):
        self.chimes.append(device)
        return True


def at(settings, hhmm: str) -> int:
    lo, _ = clock.day_bounds("2026-10-20", settings.tz)
    h, m = hhmm.split(":")
    return lo + (int(h) * 60 + int(m)) * 60_000


@pytest.fixture
def tracker(settings):
    store = Store(settings.data / "t.sqlite3")
    store.put_camera("front", "Front door", "doorbell")
    return Visits(store, FakeRing())


def clip(tracker, settings, hhmm, event_id, **answer):
    t = at(settings, hhmm)
    tracker.store.put_event(event_id, "front", "motion", t)
    tracker.store.update_event(event_id, state="done")
    event = tracker.store.event(event_id)
    return asyncio.run(tracker.on_clip(event, {"visit_1": [answer], "visit_2": [answer]}))


def test_check_refuses_what_cannot_run():
    with pytest.raises(visits.VisitError) as e:
        visits.check("", "x", ["garage"], "10:00", "09:00", ["front"])
    text = str(e.value)
    assert "who is visiting" in text and "describe them" in text
    assert "no camera 'garage'" in text and "must end after it starts" in text
    v = visits.check(" the  carer ", "a woman, dark hair, blue tunic", [], "09:00", "10:00",
                     ["front"])
    assert v["label"] == "the carer"
    assert "If nobody matching has arrived by 10:00" in visits.sentence(v | {"id": 1})


def test_arrives_leaves_and_a_missed_window(tracker, settings):
    store = tracker.store
    store.add_visit("the carer", "a woman with dark hair, blue tunic", ["front"],
                    "09:00", "10:00", at(settings, "07:00"))
    store.add_visit("the evening carer", "a man in a green fleece", ["front"],
                    "18:00", "19:00", at(settings, "07:00"))
    assert tracker.questions_for("front") == ["visit_1", "visit_2"]

    # Unsure, or too early, is never an arrival.
    clip(tracker, settings, "06:30", "e0", matches="yes", doing="arriving")
    clip(tracker, settings, "09:05", "e1", matches="cannot tell", doing="arriving")
    assert store.visit_day(1, "2026-10-20") is None

    clip(tracker, settings, "09:12", "e2", matches="yes", doing="at the door")
    clip(tracker, settings, "09:14", "e2b", matches="yes", doing="cannot tell")  # too soon
    assert store.visit_day(1, "2026-10-20")["state"] == "arrived"
    clip(tracker, settings, "09:31", "e3", matches="yes", doing="at the door")
    [carer, evening] = tracker.view(at(settings, "12:00"))
    today = carer["today"]
    assert (carer["state"], today["arrived"], today["left"], today["stayed_minutes"]) == \
        ("left", "09:12", "09:31", 19)
    assert carer["seen"] == [today]
    assert evening["state"] == "due" and evening["seen"] == []

    # visit_2 matched those clips too, but before its window: still nothing.
    assert store.visit_day(2, "2026-10-20") is None
    asyncio.run(tracker.deadlines(at(settings, "18:59")))
    assert not store.alerts()
    asyncio.run(tracker.deadlines(at(settings, "19:00")))
    asyncio.run(tracker.deadlines(at(settings, "19:05")))         # alerts once
    [alert] = store.alerts()
    assert alert["title"] == "The evening carer hasn't arrived"
    assert "a man in a green fleece" in alert["message"]
    assert tracker.ring.chimes == ["chime"]

    clip(tracker, settings, "19:20", "e4", matches="yes", doing="arriving")
    assert store.visit_day(2, "2026-10-20")["state"] == "arrived"     # late

    # The timeline cleared later: the records go, and no alert comes back.
    store.clear()
    asyncio.run(tracker.deadlines(at(settings, "23:50")))
    assert not store.alerts() and tracker.view(at(settings, "23:50"))[0]["seen"] == []


def test_waits_for_clips_still_being_read(tracker, settings):
    store = tracker.store
    store.add_visit("the carer", "a woman with dark hair", [], "09:00", "10:00",
                    at(settings, "07:00"))
    store.put_event("e9", "front", "ding", at(settings, "09:58"))   # state: new
    asyncio.run(tracker.deadlines(at(settings, "10:01")))
    assert not store.alerts()
    store.update_event("e9", state="done")
    asyncio.run(tracker.deadlines(at(settings, "10:02")))
    assert len(store.alerts()) == 1


def test_set_up_after_the_window_does_not_alert_today(tracker, settings):
    tracker.store.add_visit("the carer", "a woman", [], "09:00", "10:00",
                            at(settings, "11:00"))
    asyncio.run(tracker.deadlines(at(settings, "11:05")))
    assert not tracker.store.alerts()


def test_through_the_server(settings, ring_sim):
    from doorstep.app import app

    with TestClient(app) as client:
        r = client.post("/api/visits", json={"label": "the carer", "description":
                        "a woman with dark hair in a blue tunic", "from_hhmm": "09:00",
                        "to_hhmm": "10:00", "cameras": ["front"]})
        assert r.status_code == 200 and "I'll look for the carer" in r.json()
        bad = client.post("/api/visits", json={"label": "x", "description": "y",
                          "from_hhmm": "9am", "to_hhmm": "10:00"})
        assert bad.status_code == 422 and "HH:MM" in bad.json()["detail"]
        [v] = client.get("/api/timeline").json()["visits"]
        assert v["label"] == "the carer" and v["from"] == "09:00" and v["enabled"]
        client.patch(f"/api/visits/{v['id']}", json={"enabled": False})
        assert client.get("/api/timeline").json()["visits"][0]["enabled"] is False
        assert client.delete(f"/api/visits/{v['id']}").json() == {"ok": True}
        assert client.get("/api/timeline").json()["visits"] == []
