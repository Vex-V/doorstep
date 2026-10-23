"""End to end, through the real server and the Ring simulator: a signed
doorbell webhook -> the clip fetched through the Partner API and read by
vidra -> a rule watching -> snapshots -> the alert and the Chime -> cleared;
plus an absent rule, ask, the digest and deletion.
The VLM is a fake whose answers the test sets; everything else is real."""

import asyncio
import time
from pathlib import Path

from fastapi.testclient import TestClient

from doorstep.alerts.compiler import EXAMPLES
from doorstep.core import clock
from doorstep.ring import webhooks


def _wait_done(store, event_id, timeout=120):
    t0 = time.time()
    while time.time() - t0 < timeout:
        e = store.event(event_id)
        if e and e["state"] in ("done", "failed"):
            return e
        time.sleep(0.25)
    raise AssertionError(f"event {event_id} not processed: {store.event(event_id)}")


def test_doorbell_to_alert(settings, script, ring_sim):
    from doorstep.app import app, state

    sim = ring_sim
    courier = sim.scenario.events[0]
    script["doorstep"] = {"summary": "A courier in a blue uniform leaves a parcel.",
                          "items_left": ["parcel"]}
    script["rule_1"] = {"parcel_on_step": "yes"}

    with TestClient(app) as client:
        clock.use(clock.SyncedClock(courier.end_ms + 5000, speed=1))   # the tick loop idles

        # The family writes two rules and approves them.
        r = client.post("/api/rules", json={"text": EXAMPLES[0][0],
                                            "compiled": EXAMPLES[0][1]})
        assert r.status_code == 200, r.text
        assert "every 15 minutes" in r.json()["sentence"]
        r = client.post("/api/rules", json={"text": EXAMPLES[2][0],
                                            "compiled": EXAMPLES[2][1]})
        assert r.status_code == 200, r.text

        # A forged webhook is refused; the real one is taken once.
        bad = client.post("/ring/webhook", content=b"{}", headers={webhooks.HEADER: "sha256=00"})
        assert bad.status_code == 401
        body = webhooks.build("button_press", "front", courier.start_ms)
        headers = {webhooks.HEADER: webhooks.sign(settings.ring_webhook_secret, body)}
        first = client.post("/ring/webhook", content=body, headers=headers).json()
        again = client.post("/ring/webhook", content=body, headers=headers).json()
        assert again.get("duplicate") is True
        event = _wait_done(state.store, first["event_id"])

        assert event["state"] == "done", event.get("error")
        assert "parcel" in event["summary"]
        assert event["answers"]["rule_1"][0]["parcel_on_step"] == "yes"
        assert Path(event["clip"]).is_file() and Path(event["snapshot"]).is_file()
        st = state.store.state(1)
        assert st["state"] == "watching" and st["since_ms"] == courier.start_ms

        engine = state.worker.engine
        since = courier.start_ms
        assert asyncio.run(engine.poll(since + 30 * 60_000)) == 1
        assert state.store.state(1)["state"] == "watching"          # not yet 2 hours
        assert not state.store.alerts()
        asyncio.run(engine.poll(since + 125 * 60_000))
        alerts = state.store.alerts()
        assert [a["title"] for a in alerts] == ["Parcel left on the step"]
        assert "125 minutes" in alerts[0]["message"] and alerts[0]["snapshot"]
        assert sim.chimes, "the Chime should sound"
        assert state.store.state(1)["state"] == "fired"

        script["rule_1"] = {"parcel_on_step": "no"}                 # someone took it in
        asyncio.run(engine.poll(since + 140 * 60_000))
        assert state.store.state(1)["state"] == "idle"

        # The kitchen saw nothing by 11:00.
        day_start, _ = clock.day_bounds(clock.day_of(since, settings.tz), settings.tz)
        asyncio.run(engine.deadlines(day_start + (11 * 60 + 5) * 60_000))
        assert [a["title"] for a in state.store.alerts()][-1] == \
            "No movement in the kitchen this morning"

        # The family asks a question, and the digest is written.
        clock.use(clock.SyncedClock(courier.start_ms + 3_600_000, speed=1))
        r = client.post("/api/ask", json={"question": "When did the parcel come?"})
        assert r.status_code == 200, r.text
        r = client.post("/api/digest")
        assert r.status_code == 200 and "headline" in r.json()

        timeline = client.get("/api/timeline").json()
        assert len(timeline["events"]) == 1 and len(timeline["alerts"]) == 2
        assert timeline["digest"]["headline"] == r.json()["headline"]

        # Deleting the clip removes the files and everything derived.
        folder = settings.out / event["video_id"]
        assert folder.is_dir()
        assert client.delete(f"/api/events/{event['id']}").status_code == 200
        assert not Path(event["clip"]).exists() and not folder.exists()
        assert state.store.event(event["id"]) is None

        # Clearing the timeline leaves what the family set up.
        rules = len(state.store.rules())
        assert client.delete("/api/timeline").json() == {"ok": True}
        timeline = client.get("/api/timeline").json()
        assert (timeline["events"], timeline["alerts"], timeline["digest"]) == ([], [], None)
        assert len(timeline["rules"]) == rules > 0
        assert all(r["state"]["state"] == "idle" for r in timeline["rules"])
