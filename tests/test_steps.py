from zoneinfo import ZoneInfo

from doorstep.core import clock as clocks
from doorstep.ring import steps

TZ = ZoneInfo("Europe/London")
DAY = "2026-10-20"


def at(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return clocks.day_bounds(DAY, TZ)[0] + (int(h) * 60 + int(m)) * 60_000


SIM = {"clock": {"now_ms": at("06:59")},
       "events": [{"index": 0, "at": "07:05:00", "start_ms": at("07:05"), "seconds": 6,
                   "camera": "Front door", "type": "motion_detected", "note": "a parcel"},
                  {"index": 1, "at": "11:12:00", "start_ms": at("11:12"), "seconds": 12,
                   "camera": "Front door", "type": "button_press", "note": "the carer"},
                  {"index": -3, "at": "12:00:00", "start_ms": at("12:00"), "seconds": 5,
                   "camera": "Front door", "type": "button_press", "note": "sent by hand"}]}
RULES = [{"enabled": True, "compiled": {"kind": "absent", "deadline": "10:00",
                                         "title": "Not taken in"}},
         {"enabled": False, "compiled": {"kind": "absent", "deadline": "09:00", "title": "off"}},
         {"enabled": True, "compiled": {"kind": "on_event", "deadline": None, "title": "x"}}]
VISITS = [{"enabled": True, "label": "the evening carer", "to_hhmm": "19:00"}]


def test_stops_are_events_and_deadlines_in_order():
    got = steps.stops(SIM, RULES, VISITS, 20 * 60, TZ)
    assert [s["what"][:5] for s in got] == ["07:05", "10:00", "11:12", "19:00", "20:00"]
    # An event: once its clip has been recorded; a deadline: a minute after it.
    assert got[0]["ms"] == at("07:05") + 6_000 + steps.AFTER_CLIP_MS
    assert got[0]["event_start"] == at("07:05")
    assert got[1]["ms"] == at("10:01") and got[1]["event_start"] is None


def test_next_stop_is_the_first_after_now():
    sim = SIM | {"clock": {"now_ms": at("10:01")}}
    assert steps.next_stop(sim, RULES, VISITS, 20 * 60, TZ)["what"].startswith("11:12")
    sim = SIM | {"clock": {"now_ms": at("21:00")}}
    assert steps.next_stop(sim, RULES, VISITS, 20 * 60, TZ) is None


def test_an_event_already_sent_is_not_a_stop():
    """Sent by hand on the simulator's page, which parks the clock just after
    the clip: Next goes on to what comes after it."""
    sent = [e | {"delivered": e["index"] == 0} for e in SIM["events"]]
    sim = SIM | {"events": sent, "clock": {"now_ms": at("07:05") + 7_000}}
    assert steps.next_stop(sim, RULES, VISITS, 20 * 60, TZ)["what"].startswith("10:00")


def test_a_watching_rule_stops_when_it_would_fire():
    watching = {"enabled": True, "state": {"state": "watching", "since_ms": at("15:10")},
                "compiled": {"kind": "persists", "for_minutes": 2, "title": "On the floor"}}
    idle = watching | {"state": {"state": "idle", "since_ms": None}}
    sim = SIM | {"clock": {"now_ms": at("15:11")}}
    stop = steps.next_stop(sim, [watching], [], 20 * 60, TZ)
    assert stop["ms"] == at("15:12") + steps.AFTER_DEADLINE_MS and "On the floor" in stop["what"]
    assert steps.next_stop(sim, [idle], [], 20 * 60, TZ)["what"].startswith("20:00")
