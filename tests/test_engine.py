"""The rules engine on its own: an "it didn't happen by" rule that asks a
question (the newspaper not taken in by 10:00)."""

from __future__ import annotations

import asyncio

from doorstep.alerts import rules
from doorstep.alerts.engine import Engine
from doorstep.core import clock
from doorstep.core.store import Store

NEWSPAPER = {"kind": "absent", "title": "The newspaper hasn't been taken in",
             "cameras": ["front"], "instruction": "Look at the doorstep.",
             "fields": [{"name": "taken_in", "about": "does someone pick up a newspaper "
                         "from the step and take it inside", "one_of": ["yes", "no"]}],
             "when": [{"field": "taken_in", "op": "is", "value": "yes"}],
             "window": {"from": "05:00", "to": "10:00"}, "deadline": "10:00"}


class FakeRing:
    async def chime(self, device, event):
        return True


def at(settings, hhmm):
    lo, _ = clock.day_bounds("2026-10-20", settings.tz)
    h, m = hhmm.split(":")
    return lo + (int(h) * 60 + int(m)) * 60_000


def setup(settings):
    store = Store(settings.data / "e.sqlite3")
    store.put_camera("front", "Front door", "doorbell")
    rid = store.add_rule("Tell me if the newspaper hasn't been taken in by 10am",
                         rules.check(NEWSPAPER, ["front"]), 0)
    return store, Engine(store, FakeRing()), rid


def clip(store, settings, hhmm, event_id, answer):
    store.put_event(event_id, "front", "motion", at(settings, hhmm))
    store.update_event(event_id, state="done", answers={"rule_1": [answer]},
                       snapshot=f"{event_id}.jpg")


def test_an_absent_rule_with_a_question_is_asked_of_every_clip(settings):
    store, engine, rid = setup(settings)
    assert engine.questions_for("front") == [rules.question_name(rid)]


def test_not_taken_in_by_the_deadline_alerts(settings):
    store, engine, _ = setup(settings)
    clip(store, settings, "07:05", "drop", {"taken_in": "no"})
    asyncio.run(engine.deadlines(at(settings, "09:59")))
    assert not store.alerts()
    asyncio.run(engine.deadlines(at(settings, "10:00")))
    [alert] = store.alerts()
    assert alert["title"] == "The newspaper hasn't been taken in"
    assert alert["message"] == ("None of the 1 clip from Front door since 05:00 showed it. "
                                "The picture is from 07:05.")
    assert (alert["event_id"], alert["snapshot"]) == ("drop", "drop.jpg")   # the step


def test_a_timeline_cleared_later_does_not_alert_about_the_morning(settings):
    store, engine, _ = setup(settings)
    clip(store, settings, "07:05", "drop", {"taken_in": "no"})
    asyncio.run(engine.deadlines(at(settings, "10:00")))
    store.clear()                                   # the rule's state goes with it
    asyncio.run(engine.deadlines(at(settings, "23:50")))
    assert not store.alerts()


def test_taken_in_in_time_stays_quiet(settings):
    store, engine, rid = setup(settings)
    clip(store, settings, "07:05", "drop", {"taken_in": "no"})
    clip(store, settings, "08:40", "pickup", {"taken_in": "yes"})
    asyncio.run(engine.deadlines(at(settings, "10:00")))
    assert not store.alerts() and store.state(rid)["state"] == "satisfied"
