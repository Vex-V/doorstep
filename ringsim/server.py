"""The simulator's HTTP surface.

    Partner API (bearer token)
    GET  /v1/devices                                   devices, JSON:API
    GET  /v1/history/devices/{id}/events               Event History, newest first
    POST /v1/devices/{id}/media/video/download         303 -> /media/{key} (MP4)
    POST /v1/devices/{id}/media/image/download         303 -> /media/{key} (JPEG)
    GET  /v1/devices/{id}/configurations               a Chime's audio slots
    POST /v1/devices/{id}/media/audio/playback         sound a Chime
    GET  /media/{key}                                  the pre-signed URL: refuses a token

    Control (no token; the page at / drives it)
    GET  /sim/state
    POST /sim/start {"mode", "speed", "gap_s"}   the day from the top, played:
         schedule   on the clock, at `speed` times real time
         sequence   each video in turn, `gap_s` real seconds apart
         manual     nothing until an event is sent by hand
    POST /sim/stop · POST /sim/clock {"at", "speed", "running"}
    POST /sim/events/{n}/send       one event, by hand
    POST /sim/videos?at=&camera=&type=&note=&name=   the request body is the video
    DELETE /sim/videos/{n} · POST /sim/cameras {"name", "kind"}
    GET  /sim/clip/{n}   an event's footage, for the page's camera view

Media follows Ring's rules as far as they are documented: nothing before an
event starts or after the simulated now (416 MEDIA_NOT_FOUND), a clip only
once its event has finished recording, at most 15 minutes. A snapshot after
an event is that event's last frame: the camera still sees what the last
visitor left, which is what "the parcel is still there" is checked against.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import secrets
import time
import uuid
from collections import deque
from contextlib import asynccontextmanager
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import httpx
from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, Response

from .scenario import IMAGES, DayClock, Event, Scenario

log = logging.getLogger("ringsim")
STATIC = Path(__file__).parent / "static"

#: Ring retries an undelivered webhook six times.
RETRIES = (1, 2, 4, 8, 16, 32)
#: Ring expects a webhook answered within five seconds.
WEBHOOK_TIMEOUT_S = 5.0
#: How long a media URL stays valid.
MEDIA_TTL_S = 300
MAX_CLIP_MS = 900_000
CHIME_SLOTS = ("ring-appstore-event-1", "ring-appstore-event-2")
MODES = ("schedule", "sequence", "manual")
#: Sequence mode stops this long after a clip ends, so it has finished recording.
AFTER_CLIP_MS = 1_000


def sign(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _error(status: int, code: str, title: str) -> JSONResponse:
    return JSONResponse({"errors": [{"status": str(status), "code": code, "title": title}]},
                        status_code=status)


def frame_jpeg(clip: Path, offset_ms: Optional[int]) -> Optional[bytes]:
    """The frame `offset_ms` into a clip; None means its last frame. A
    container's frame count is an estimate, so a failed read steps back."""
    import cv2
    cap = cv2.VideoCapture(str(clip))
    try:
        frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        last = max(0, frames - 2)
        index = last if offset_ms is None else min(last, int(offset_ms / 1000 * fps))
        for back in (0, 5, 15, 30, 60, 120, 250):
            cap.set(cv2.CAP_PROP_POS_FRAMES, max(0, index - back))
            ok, frame = cap.read()
            if ok:
                ok, buf = cv2.imencode(".jpg", frame, [cv2.IMWRITE_JPEG_QUALITY, 90])
                return buf.tobytes()
        return None
    finally:
        cap.release()


class Sim:
    def __init__(self, scenario: Scenario, *, token: str, secret: str,
                 webhook_url: Optional[str], speed: float = 60.0,
                 account_id: str = "ringsim") -> None:
        self.scenario = scenario
        self.token = token
        self.secret = secret
        self.webhook_url = webhook_url
        self.account_id = account_id
        self.clock = DayClock(self._day_start(), speed)
        self.media: dict[str, tuple[Path | bytes, str, float]] = {}
        self.chimes: list[dict[str, Any]] = []
        self.calls: deque[dict[str, Any]] = deque(maxlen=40)
        self.deliveries: deque[dict[str, Any]] = deque(maxlen=40)
        self.generation = 0
        self.run_id = secrets.token_hex(3)   # in each webhook's event id: a run's own
        self._pending: set[int] = set()
        self.mode = "schedule"
        self.gap_s = 20.0
        self._sequence: Optional[asyncio.Task] = None

    def _day_start(self) -> int:
        first = min((e.start_ms for e in self.scenario.events),
                    default=self.scenario.start_ms)
        return min(self.scenario.start_ms, first - 60_000)

    # -- the day ---------------------------------------------------------------

    def start(self, speed: Optional[float] = None, mode: str = "schedule",
              gap_s: Optional[float] = None) -> None:
        """The day from the top: the clock a minute before the first event,
        every webhook unsent, anything sent by hand forgotten. `schedule` runs
        the clock; `sequence` steps through the videos; `manual` waits."""
        if mode not in MODES:
            raise ValueError(f"mode must be one of {', '.join(MODES)}")
        self.stop()
        self.generation += 1
        self.run_id = secrets.token_hex(3)
        self._pending.clear()
        self.scenario.events = [e for e in self.scenario.events if e.index >= 0]
        for e in self.scenario.events:
            e.delivered = False
        self.chimes.clear()
        self.deliveries.clear()
        self.mode = mode
        if gap_s is not None:
            self.gap_s = max(0.0, float(gap_s))
        self.clock.set(at_ms=self._day_start(), speed=speed, running=mode == "schedule")
        if mode == "sequence":
            self._sequence = asyncio.create_task(self._play_in_turn(self.generation))

    def stop(self) -> None:
        """Pause the clock, and stop stepping through the videos."""
        if self._sequence is not None:
            self._sequence.cancel()
            self._sequence = None
        self.clock.set(running=False)

    async def _play_in_turn(self, generation: int) -> None:
        """Each video in time order: the clock to just after it ends (paused),
        its webhook sent, then `gap_s` of real time for the app to read it."""
        for e in [e for e in self.scenario.events if e.index >= 0]:
            if generation != self.generation:
                return
            self.clock.set(at_ms=max(self.clock.now_ms(), e.end_ms + AFTER_CLIP_MS),
                           running=False)
            for _ in range(int(WEBHOOK_TIMEOUT_S * 10 * len(RETRIES))):
                if e.delivered or generation != self.generation:
                    break
                await asyncio.sleep(0.1)
            await asyncio.sleep(self.gap_s)
        self._sequence = None

    def send(self, index: int) -> Event:
        """One event, by hand. Still ahead: the clock goes to just after it
        (paused) and it is sent at its own time. Already past: a copy happens
        now, as a doorbell pressed again would; on a paused clock, the clock
        goes to just after the copy too, or its clip would never finish
        recording and could not be downloaded."""
        e = next(e for e in self.scenario.events if e.index == index)
        now = self.clock.now_ms()
        if e.end_ms + AFTER_CLIP_MS > now:
            self.clock.set(at_ms=e.end_ms + AFTER_CLIP_MS, running=False)
            e.delivered = False
        else:
            e = self.trigger_now(index)
            if not self.clock.running:
                self.clock.set(at_ms=e.end_ms + AFTER_CLIP_MS)
        if self.mode == "manual":            # nothing else is sent in manual mode
            self._pending.add(id(e))
            asyncio.create_task(self._deliver(e, self.generation))
        return e

    def trigger_now(self, index: int) -> Event:
        """A copy of scripted event `index`, happening now (the doorbell pressed
        on cue during a demo). Marked with a negative index, so a restart drops it."""
        source = next(e for e in self.scenario.events if e.index == index)
        now = self.clock.now_ms()
        copy = replace(source, index=-(len(self.scenario.events) + 1), start_ms=now,
                       delivered=False, note=f"{source.note} (sent by hand)")
        self.scenario.events.append(copy)
        self.scenario.events.sort(key=lambda e: e.start_ms)
        return copy

    async def dispatch(self) -> None:
        """Send each event's webhook once the simulated clock reaches it,
        unless events are only being sent by hand."""
        while True:
            now = self.clock.now_ms()
            for e in list(self.scenario.events if self.mode != "manual" else ()):
                if e.start_ms <= now and not e.delivered and id(e) not in self._pending:
                    self._pending.add(id(e))
                    asyncio.create_task(self._deliver(e, self.generation))
            await asyncio.sleep(0.2)

    def webhook_body(self, e: Event) -> bytes:
        attributes: dict[str, Any] = {"source": e.camera, "source_type": "devices",
                                      "timestamp": e.start_ms}
        if e.type == "motion_detected":
            attributes["sub_type"] = e.subtype or "motion"
            attributes["timestamp_readable"] = _iso(e.start_ms).replace("T", " ")[:-1]
        doc = {"meta": {"version": "1.1", "time": _iso(self.clock.now_ms()),
                        "request_id": str(uuid.uuid4()), "account_id": self.account_id},
               # Ring gives every press its own id: the day played again is new
               # events, not the old ones delivered twice.
               "data": {"id": f"{e.id}_{self.run_id}", "type": e.type,
                        "attributes": attributes,
                        "relationships": {"devices": {"links": {
                            "self": f"/v1/devices/{e.camera}"}}}}}
        return json.dumps(doc, separators=(",", ":")).encode()

    async def _deliver(self, e: Event, generation: int) -> None:
        if not self.webhook_url:
            e.delivered = True
            return
        body = self.webhook_body(e)        # one body, one request_id, for every retry
        headers = {"Content-Type": "application/json", "X-Signature": sign(self.secret, body)}
        async with httpx.AsyncClient(timeout=WEBHOOK_TIMEOUT_S) as http:
            for attempt, wait in enumerate((0, *RETRIES)):
                await asyncio.sleep(wait)
                if generation != self.generation:
                    return
                try:
                    resp = await http.post(self.webhook_url, content=body, headers=headers)
                    status: Any = resp.status_code
                except httpx.HTTPError as exc:
                    status = type(exc).__name__
                self.deliveries.appendleft({"event": e.id, "type": e.type,
                                            "at_ms": self.clock.now_ms(),
                                            "attempt": attempt + 1, "status": status})
                log.info("webhook %s %s -> %s (attempt %d)", e.type, e.id, status, attempt + 1)
                if isinstance(status, int) and 200 <= status < 300:
                    e.delivered = generation == self.generation
                    break
        self._pending.discard(id(e))

    # -- media -----------------------------------------------------------------

    def presign(self, content: Path | bytes, media_type: str) -> str:
        now = time.monotonic()
        self.media = {k: v for k, v in self.media.items() if v[2] > now}
        key = secrets.token_urlsafe(24)
        self.media[key] = (content, media_type, now + MEDIA_TTL_S)
        return f"/media/{key}"

    def recorded(self, device_id: str) -> list[Event]:
        """Events on a device that have started by the simulated now."""
        now = self.clock.now_ms()
        return [e for e in self.scenario.on(device_id) if e.start_ms <= now]

    def view(self) -> dict[str, Any]:
        tz = self.scenario.tz

        def hhmm(ms: int) -> str:
            return datetime.fromtimestamp(ms / 1000, tz).strftime("%H:%M:%S")

        names = {c["id"]: c.get("name", c["id"]) for c in self.scenario.cameras}
        return {"title": self.scenario.title, "tz": str(tz),
                "clock": self.clock.view() | {"time": hhmm(self.clock.now_ms())},
                "mode": self.mode, "gap_s": self.gap_s,
                "playing": self.clock.running or self._sequence is not None,
                "webhook_url": self.webhook_url,
                "cameras": self.scenario.cameras,
                "events": [{"index": e.index, "at": hhmm(e.start_ms), "start_ms": e.start_ms,
                            "camera": names.get(e.camera, e.camera), "type": e.type,
                            "subtype": e.subtype, "note": e.note, "clip": e.clip.name,
                            "seconds": round(e.duration_ms / 1000),
                            "delivered": e.delivered, "pending": id(e) in self._pending}
                           for e in self.scenario.events],
                "chimes": [c | {"time": hhmm(c["at_ms"])} for c in self.chimes],
                "deliveries": [d | {"time": hhmm(d["at_ms"])} for d in self.deliveries],
                "calls": list(self.calls)}


def create_app(sim: Sim) -> FastAPI:
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        dispatcher = asyncio.create_task(sim.dispatch())
        yield
        dispatcher.cancel()

    app = FastAPI(title="Ring Partner API simulator", lifespan=lifespan)
    app.state.sim = sim

    @app.middleware("http")
    async def auth_and_log(request: Request, call_next):
        path = request.url.path
        if path.startswith("/v1/"):
            if request.headers.get("authorization") != f"Bearer {sim.token}":
                resp: Response = _error(401, "UNAUTHORIZED", "missing or invalid access token")
            else:
                resp = await call_next(request)
            sim.calls.appendleft({"time": datetime.now().strftime("%H:%M:%S"),
                                  "method": request.method, "path": path,
                                  "status": resp.status_code})
            return resp
        return await call_next(request)

    def device_or_404(device_id: str) -> Optional[dict[str, Any]]:
        return sim.scenario.camera(device_id)

    # -- devices -----------------------------------------------------------------

    @app.get("/v1/devices")
    async def devices():
        data, included = [], []
        for c in sim.scenario.cameras:
            kind = c.get("kind", "camera")
            data.append({"type": "devices", "id": c["id"],
                         "attributes": {"name": c.get("name", c["id"]),
                                        "image_url": IMAGES.get(kind, IMAGES["camera"])},
                         "relationships": {"status": {"data": {
                             "type": "device-status", "id": f"{c['id']}.status"}}}})
            included.append({"type": "device-status", "id": f"{c['id']}.status",
                             "attributes": {"online": True,
                                            "reported_at": _iso(sim.clock.now_ms())}})
        return {"data": data, "included": included,
                "meta": {"time": _iso(sim.clock.now_ms())}}

    @app.get("/v1/history/devices/{device_id}/events")
    async def history(device_id: str, request: Request):
        if not device_or_404(device_id):
            return _error(404, "NOT_FOUND", f"no device {device_id}")
        wanted = [t for t in (request.query_params.get("event_types") or "").split(",") if t]
        now = sim.clock.now_ms()
        rows = []
        for e in sorted(sim.recorded(device_id), key=lambda e: -e.start_ms):
            kind = e.history_type
            if wanted and not any(kind == w or kind.startswith(w + ".") for w in wanted):
                continue
            rows.append({"type": "history-events", "id": f"evt-{e.camera}-{e.start_ms}",
                         "attributes": {"event_type": kind, "start": e.start_ms,
                                        "end": e.end_ms if now >= e.end_ms else None,
                                        "is_third_party_reviewed": False},
                         "relationships": {"source": {"data": {"type": "devices",
                                                               "id": e.camera}}}})
        return {"data": rows[:50], "links": {}, "meta": {"time": _iso(now)}}

    # -- media -------------------------------------------------------------------

    @app.post("/v1/devices/{device_id}/media/video/download")
    async def video_download(device_id: str, request: Request):
        if not device_or_404(device_id):
            return _error(404, "NOT_FOUND", f"no device {device_id}")
        body = await request.json()
        start, duration = int(body["timestamp"]), int(body["duration"])
        if duration <= 0 or duration > MAX_CLIP_MS:
            return _error(400, "INVALID_DURATION", "duration must be 1 ms to 15 minutes")
        now = sim.clock.now_ms()
        best, overlap = None, 0
        for e in sim.recorded(device_id):
            o = min(start + duration, e.end_ms) - max(start, e.start_ms)
            if o > overlap:
                best, overlap = e, o
        if best is None or best.end_ms > now:
            return _error(416, "MEDIA_NOT_FOUND", "no finished recording in that range")
        return Response(status_code=303, headers={
            "Location": sim.presign(best.clip, "video/mp4")})

    @app.post("/v1/devices/{device_id}/media/image/download")
    async def image_download(device_id: str, request: Request):
        if not device_or_404(device_id):
            return _error(404, "NOT_FOUND", f"no device {device_id}")
        body = await request.json()
        now = sim.clock.now_ms()
        at = int(body["timestamp"]) if body.get("type") == "at_timestamp" else now
        if at > now:
            return _error(416, "MEDIA_NOT_FOUND", "that time has not happened yet")
        before = [e for e in sim.scenario.on(device_id) if e.start_ms <= at]
        if not before:
            return _error(416, "MEDIA_NOT_FOUND", "nothing recorded before that time")
        e = max(before, key=lambda e: e.start_ms)
        offset = at - e.start_ms
        jpeg = await asyncio.to_thread(frame_jpeg, e.clip,
                                       offset if offset < e.duration_ms else None)
        if jpeg is None:
            return _error(416, "MEDIA_NOT_FOUND", "no decodable frame at that time")
        return Response(status_code=303, headers={"Location": sim.presign(jpeg, "image/jpeg")})

    @app.get("/media/{key}")
    async def media(key: str, request: Request):
        if "authorization" in request.headers:
            # A pre-signed URL carries its own signature; S3 refuses a second one.
            return Response("InvalidArgument: Only one auth mechanism allowed",
                            status_code=400, media_type="text/plain")
        entry = sim.media.get(key)
        if entry is None or entry[2] < time.monotonic():
            return Response("AccessDenied: Request has expired", status_code=403,
                            media_type="text/plain")
        content, media_type, _ = entry
        if isinstance(content, Path):
            return FileResponse(content, media_type=media_type)
        return Response(content, media_type=media_type)

    # -- the Chime ---------------------------------------------------------------

    @app.get("/v1/devices/{device_id}/configurations")
    async def configurations(device_id: str):
        c = device_or_404(device_id)
        if not c:
            return _error(404, "NOT_FOUND", f"no device {device_id}")
        slots = None
        if c.get("kind") == "chime":
            slots = [{"event": name, "audio_ref": f"{device_id}.{name}", "disabled": False}
                     for name in CHIME_SLOTS]
        return {"data": {"type": "device-configurations", "id": f"{device_id}.configurations",
                         "attributes": {"audio": {"customizable_slots": slots, "volume": 8}}}}

    @app.post("/v1/devices/{device_id}/media/audio/playback")
    async def playback(device_id: str, request: Request):
        c = device_or_404(device_id)
        if not c:
            return _error(404, "NOT_FOUND", f"no device {device_id}")
        if c.get("kind") != "chime":
            return _error(400, "UNSUPPORTED", f"{device_id} cannot play audio")
        ref = (((await request.json()).get("data") or {}).get("attributes") or {}).get("audio_ref")
        if ref not in {f"{device_id}.{n}" for n in CHIME_SLOTS}:
            return _error(400, "INVALID_AUDIO_REF", "unknown audio_ref")
        sim.chimes.append({"at_ms": sim.clock.now_ms(), "device": device_id, "audio_ref": ref})
        log.info("chime %s: %s", device_id, ref)
        return {"data": {"type": "audio", "id": str(uuid.uuid4()),
                         "attributes": {"status": "completed"}}}

    # -- control -----------------------------------------------------------------

    @app.get("/")
    async def page():
        return FileResponse(STATIC / "index.html")

    @app.get("/sim/state")
    async def state():
        return sim.view()

    @app.get("/sim/clock")
    async def clock():
        return sim.clock.view()

    @app.get("/sim/clip/{index}")
    async def clip(index: int):
        """An event's footage, for the page's camera view (not the Partner API)."""
        e = next((e for e in sim.scenario.events if e.index == index), None)
        if e is None:
            return _error(404, "NOT_FOUND", f"no event {index}")
        return FileResponse(e.clip, media_type="video/mp4")

    @app.post("/sim/start")
    async def start(request: Request):
        body = await _json(request)
        try:
            sim.start(body.get("speed"), body.get("mode") or "schedule", body.get("gap_s"))
        except ValueError as exc:
            return _error(400, "BAD_MODE", str(exc))
        return sim.view()

    @app.post("/sim/stop")
    async def stop():
        sim.stop()
        return sim.view()

    @app.post("/sim/clock")
    async def set_clock(request: Request):
        """{"at": "HH:MM[:SS]"} jumps; {"speed": n} and {"running": bool} as named."""
        body = await _json(request)
        at = sim.scenario.day_ms(body["at"]) if body.get("at") else None
        if at is not None and at < sim.clock.now_ms():
            return _error(400, "BACKWARDS", "the clock only goes forward: start the day again")
        sim.clock.set(at_ms=at, speed=body.get("speed"), running=body.get("running"))
        return sim.clock.view()

    @app.post("/sim/events/{index}/send")
    async def send(index: int):
        if not any(e.index == index for e in sim.scenario.events):
            return _error(404, "NOT_FOUND", f"no scripted event {index}")
        e = sim.send(index)
        return {"id": e.id, "start_ms": e.start_ms}

    @app.post("/sim/videos")
    async def add_video(request: Request):
        """A video at a time of day: the body is the file, copied into the
        scenario's `clips/` folder; the scenario file is saved with it."""
        q = request.query_params
        data = await request.body()
        if not data:
            return _error(400, "NO_VIDEO", "send the video as the request body")
        name = Path(q.get("name") or "video.mp4").name
        stem = "".join(c if c.isalnum() or c in "-_" else "-" for c in Path(name).stem)[:40]
        folder = sim.scenario.path.parent / "clips"
        folder.mkdir(parents=True, exist_ok=True)
        path = folder / f"{stem or 'video'}{Path(name).suffix.lower() or '.mp4'}"
        n = 2
        while path.exists():
            path = folder / f"{stem or 'video'}-{n}{path.suffix}"
            n += 1
        path.write_bytes(data)
        try:
            e = sim.scenario.add(q.get("at") or "", q.get("camera") or "",
                                 q.get("type") or "motion_detected", path,
                                 note=q.get("note") or "",
                                 subtype=q.get("sub_type") or None)
        except (ValueError, KeyError) as exc:
            path.unlink(missing_ok=True)
            return _error(400, "BAD_VIDEO", str(exc))
        return {"index": e.index, "clip": path.name, "seconds": round(e.duration_ms / 1000)}

    @app.post("/sim/cameras")
    async def add_camera(request: Request):
        body = await _json(request)
        try:
            return sim.scenario.add_camera(body.get("name") or "", body.get("kind") or "camera")
        except ValueError as exc:
            return _error(400, "BAD_CAMERA", str(exc))

    @app.delete("/sim/videos/{index}")
    async def remove_video(index: int):
        if not any(e.index == index for e in sim.scenario.events if e.index >= 0):
            return _error(404, "NOT_FOUND", f"no scripted event {index}")
        sim.scenario.remove(index)
        return sim.view()

    return app


async def _json(request: Request) -> dict[str, Any]:
    raw = await request.body()
    return json.loads(raw) if raw.strip() else {}
