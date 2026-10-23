"""The Ring simulator, driven by Doorstep's own Ring client: what the client
reads back is what the simulator served, in the Partner API's shapes."""

from __future__ import annotations

import asyncio

import httpx
import pytest

from doorstep.ring import webhooks
from doorstep.ring.api import MediaNotFound, RingError
from doorstep.ring.client import RingClient
from ringsim.scenario import load
from ringsim.server import Sim, create_app, sign


@pytest.fixture
def sim(scenario):
    return Sim(load(scenario, "Europe/London"), token="tok", secret="test-secret",
               webhook_url=None)


def client_for(sim: Sim, token: str = "tok") -> RingClient:
    app = create_app(sim)
    ring = RingClient(token, "http://sim")
    ring._http = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url="http://sim")
    ring._media = httpx.AsyncClient(transport=httpx.ASGITransport(app))
    return ring


def at(sim: Sim, hhmm: str) -> None:
    sim.clock.set(at_ms=sim.scenario.day_ms(hhmm), running=False)


def run(coro):
    return asyncio.run(coro)


def test_devices_are_told_apart_by_their_image(sim):
    kinds = {d.id: d.kind for d in run(client_for(sim).devices())}
    assert kinds == {"front": "doorbell", "kitchen": "camera", "chime": "chime"}


def test_history_grows_with_the_clock(sim):
    ring = client_for(sim)
    at(sim, "07:59:00")
    assert run(ring.history("front")) == []
    at(sim, "08:00:01")
    [h] = run(ring.history("front"))
    assert (h.event_type, h.end_ms) == ("ding", None)          # still recording
    at(sim, "11:00:30")
    events = run(ring.history("front"))
    assert [(h.event_type, h.subtype) for h in events] == [("motion", "human"), ("ding", None)]
    assert all(h.end_ms for h in events)
    assert [h.event_type for h in run(ring.history("front", ["ding"]))] == ["ding"]


def test_clip_only_once_recorded_and_through_a_tokenless_redirect(sim):
    ring = client_for(sim)
    start = sim.scenario.day_ms("08:00")
    at(sim, "08:00:02")
    with pytest.raises(MediaNotFound):
        run(ring.clip("front", start, 4000))
    at(sim, "08:01")
    assert run(ring.clip("front", start - 2000, 8000)) == sim.scenario.events[0].clip.read_bytes()
    with pytest.raises(MediaNotFound):
        run(ring.clip("kitchen", start, 4000))


def test_media_url_refuses_a_token(sim):
    async def go():
        app = create_app(sim)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                     base_url="http://sim") as http:
            at(sim, "08:01")
            r = await http.post("/v1/devices/front/media/image/download",
                                headers={"Authorization": "Bearer tok"},
                                json={"type": "at_timestamp",
                                      "timestamp": sim.scenario.day_ms("08:00:01")})
            assert r.status_code == 303
            again = await http.get(r.headers["location"], headers={"Authorization": "Bearer tok"})
            assert again.status_code == 400
            ok = await http.get(r.headers["location"])
            assert ok.status_code == 200 and ok.content[:2] == b"\xff\xd8"
    run(go())


def test_snapshots_follow_the_day(sim):
    ring = client_for(sim)
    at(sim, "07:30")
    with pytest.raises(MediaNotFound):                      # nothing recorded yet
        run(ring.snapshot("front", sim.scenario.day_ms("07:30")))
    at(sim, "09:00")
    with pytest.raises(MediaNotFound):                      # the future
        run(ring.snapshot("front", sim.scenario.day_ms("09:30")))
    during = run(ring.snapshot("front", sim.scenario.day_ms("08:00:01")))
    # Doorstep always names the time: "latest" is wall-clock time, not the day's.
    after = run(ring.snapshot("front", sim.scenario.day_ms("08:59")))   # as the courier left it
    assert during[:2] == after[:2] == b"\xff\xd8" and during != after


def test_chime(sim):
    ring = client_for(sim)
    assert run(ring.chime("chime", "ring-appstore-event-1")) is True
    assert len(sim.chimes) == 1
    with pytest.raises(RingError):
        run(ring.chime("front", "ring-appstore-event-1"))


def test_wrong_token(sim):
    with pytest.raises(RingError, match="401"):
        run(client_for(sim, token="nope").devices())


def test_webhooks_verify_and_parse_in_doorstep(sim):
    ding, motion = sim.scenario.events
    for e in (ding, motion):
        body = sim.webhook_body(e)
        hook = webhooks.verify_and_parse("test-secret", body, sign("test-secret", body))
        assert (hook.type, hook.device_id, hook.timestamp_ms) == (e.type, "front", e.start_ms)
        assert hook.request_id
    assert hook.subtype == "human" and \
        hook.event_id == f"front_human_{motion.start_ms}_{sim.run_id}"


def test_the_day_played_again_is_new_events(sim):
    """Doorstep keeps one copy of an event id: a second run must not reuse them."""
    def event_id(e):
        return webhooks.parse(sim.webhook_body(e)).event_id

    e = sim.scenario.events[0]
    first = event_id(e)
    assert event_id(e) == first                       # a retry: the same event
    run(_start(sim))
    assert event_id(e) != first


async def _start(sim):                                # start() wants a running loop
    sim.start(mode="manual")


def test_a_video_added_at_a_time_is_saved_with_the_scenario(sim, tmp_path):
    from conftest import make_clip

    async def go():
        app = create_app(sim)
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app),
                                     base_url="http://sim") as http:
            data = make_clip(tmp_path / "up" / "My Visitor!.mp4", seconds=3).read_bytes()
            r = await http.post("/sim/videos", content=data, params={
                "at": "09:30", "camera": "front", "type": "button_press",
                "note": "the window cleaner", "name": "My Visitor!.mp4"})
            assert r.status_code == 200, r.text
            bad = await http.post("/sim/videos", content=data, params={
                "at": "25:00", "camera": "front", "name": "x.mp4"})
            assert bad.status_code == 400
            return r.json()

    added = run(go())
    assert added["clip"] == "My-Visitor-.mp4" and added["index"] == 1     # between 08:00 and 11:00
    reloaded = load(sim.scenario.path)
    assert [(e.at, e.note) for e in reloaded.events] == [
        ("08:00:00", ""), ("09:30:00", "the window cleaner"), ("11:00:00", "")]
    assert len(list((sim.scenario.path.parent / "clips").glob("x*"))) == 0  # refused: not kept
    sim.scenario.remove(1)
    assert len(load(sim.scenario.path).events) == 2


def test_by_hand_sends_only_what_is_asked_at_its_own_time(sim):
    async def go():
        sim.start(mode="manual")
        dispatcher = asyncio.create_task(sim.dispatch())
        await asyncio.sleep(0.3)
        assert not any(e.delivered for e in sim.scenario.events)          # nothing on its own
        sim.send(1)                                                       # the 11:00 one
        await asyncio.sleep(0.3)
        first, second = sim.scenario.events
        assert second.delivered and not first.delivered                   # 08:00 skipped
        assert sim.clock.now_ms() > second.end_ms and not sim.clock.running
        now = sim.clock.now_ms()
        copy = sim.send(0)                                                # past: sent now
        assert copy.index < 0 and copy.start_ms == now
        assert sim.clock.now_ms() > copy.end_ms and not sim.clock.running  # recorded
        dispatcher.cancel()

    run(go())


def test_one_after_another(sim):
    async def go():
        sim.start(mode="sequence", gap_s=0)
        dispatcher = asyncio.create_task(sim.dispatch())
        for _ in range(50):
            if sim._sequence is None:
                break
            await asyncio.sleep(0.1)
        assert all(e.delivered for e in sim.scenario.events)
        assert sim.clock.now_ms() > sim.scenario.events[-1].end_ms and not sim.clock.running
        dispatcher.cancel()

    run(go())


def test_restart_forgets_what_was_sent_by_hand(sim):
    async def go():
        sim.start(speed=60)
        assert sim.clock.running and sim.clock.now_ms() < sim.scenario.events[0].start_ms
        sim.clock.set(at_ms=sim.scenario.events[1].end_ms + 5000)
        sim.send(0)                                             # past: a copy, now
        assert len(sim.scenario.events) == 3
        sim.start()
        assert len(sim.scenario.events) == 2

    run(go())


def test_a_camera_added_is_saved_and_takes_motion_only(sim, tmp_path):
    from conftest import make_clip

    cam = sim.scenario.add_camera("Living room", "camera")
    assert cam == {"id": "living-room", "name": "Living room", "kind": "camera"}
    assert sim.scenario.add_camera("Living room", "camera")["id"] == "living-room-2"
    clip = make_clip(tmp_path / "fall.mp4", seconds=2)
    with pytest.raises(ValueError, match="not a doorbell"):
        sim.scenario.add("15:10", "living-room", "button_press", clip)
    sim.scenario.add("15:10", "living-room", "motion_detected", clip, note="a fall")
    reloaded = load(sim.scenario.path)
    assert reloaded.camera("living-room")["name"] == "Living room"
    assert [e.camera for e in reloaded.events].count("living-room") == 1
