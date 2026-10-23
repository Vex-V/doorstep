"""The clip path: motion or ding -> wait for the event's end -> download the MP4
-> `video_rag` (the `doorstep` question, plus every question a watcher wants
for that camera) -> answers stored -> each watcher reads them.

A watcher is anything with `questions_for(camera)` and `on_clip(event,
answers)`: the rules engine and the expected-visits tracker. Clips run one at a
time (one GPU, one embedder).
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Protocol

from ..alerts.notify import event_message
from ..core import clock as clocks
from ..core.bus import bus
from ..core.config import settings
from ..core.models import models
from ..ring.api import MediaNotFound

log = logging.getLogger("doorstep.clips")

#: Seconds of footage kept either side of an event.
PAD_MS = 2000
#: How long to wait for Ring to report an event's end before guessing it.
END_WAIT_S = 180
#: A clip's length when Ring never reports the end.
DEFAULT_MS = 30_000

_clip_lock = asyncio.Lock()


class Watcher(Protocol):
    def questions_for(self, camera: str) -> list[str]: ...

    async def on_clip(self, event: dict[str, Any],
                      answers: dict[str, list[dict[str, Any]]]) -> None: ...


def safe_id(text: str) -> str:
    """An id vidra accepts as a directory name. Ring's device ids run past 100
    characters, so a long id keeps its end (the event type and time, which tell
    events apart) and a hash of the whole."""
    out = re.sub(r"[^A-Za-z0-9._-]", "-", text).strip("-.")
    if len(out) > 64:
        digest = hashlib.sha1(text.encode()).hexdigest()[:10]
        out = f"{digest}-{out[-40:]}".replace("--", "-")
    return ("e" + out) if not out or out[0] in "_-." else out


def save_snapshot(camera: str, at_ms: int, jpeg: bytes) -> Path:
    folder = settings().snapshots
    folder.mkdir(parents=True, exist_ok=True)
    path = folder / f"{safe_id(camera)}-{at_ms}.jpg"
    path.write_bytes(jpeg)
    return path


def _iso(ms: int) -> str:
    return datetime.fromtimestamp(ms / 1000, tz=timezone.utc).isoformat()


async def _event_end(ring, event: dict[str, Any]) -> int:
    """The event's end, from Event History; Ring reports it once the recording
    has finished. Falls back to a fixed length rather than waiting forever."""
    kinds = ["ding"] if event["kind"] == "ding" else ["motion", "ding"]
    waited = 0.0
    while waited < END_WAIT_S:
        try:
            for h in await ring.history(event["camera"], kinds):
                if abs(h.start_ms - event["start_ms"]) <= 5000 and h.end_ms:
                    return h.end_ms
        except Exception as exc:
            log.warning("history for %s failed: %s", event["camera"], exc)
        await clocks.clock().sleep(5)
        waited += 5
    return event["start_ms"] + DEFAULT_MS


def _answers(descriptions_path: Path) -> dict[str, list[dict[str, Any]]]:
    """{question: [answer per chunk]} from a descriptions.json."""
    from vidra.video_rag import describe

    doc = describe.load(descriptions_path)
    out: dict[str, list[dict[str, Any]]] = {}
    for chunk in doc.chunks:
        for block in (chunk.get("samplers") or {}).values():
            answer = {"summary": block.get("description", ""),
                      **(block.get("structured") or {}),
                      "_chunk": chunk.get("chunk_id")}
            out.setdefault(block.get("question", ""), []).append(answer)
    return out


def _run_vidra(clip: Path, video_id: str, camera_name: str, start_ms: int,
               questions: list[str]):
    from vidra.video_rag import video_rag
    from vidra.video_rag.samplers import Uniform

    s = settings()
    return video_rag(clip, into=s.out, video_id=video_id, name=camera_name,
                     recorded_at=_iso(start_ms),
                     sampler=Uniform(every_n=2, max_per_chunk=6, prompts=questions),
                     models=models(), use_audio=s.audio)


async def process_clip(store, ring, watchers: list[Watcher], event_id: str) -> None:
    event = store.event(event_id)
    if event is None:
        return
    camera = store.camera(event["camera"]) or {"name": event["camera"]}
    store.update_event(event_id, state="processing")
    bus.publish("family", event_message(store.event(event_id)))
    try:
        end_ms = event.get("end_ms") or await _event_end(ring, event)
        start = event["start_ms"] - PAD_MS
        duration = end_ms - event["start_ms"] + 2 * PAD_MS
        data = await ring.clip(event["camera"], start, duration, audio=settings().audio)
        folder = settings().clips
        folder.mkdir(parents=True, exist_ok=True)
        clip = folder / f"{safe_id(event_id)}.mp4"
        clip.write_bytes(data)
        questions = ["doorstep"]
        for w in watchers:
            questions += [q for q in w.questions_for(event["camera"]) if q not in questions]
        async with _clip_lock:
            run = await asyncio.to_thread(_run_vidra, clip, safe_id(event_id),
                                          camera["name"], event["start_ms"], questions)
        answers = _answers(run.folder / "descriptions.json")
        summary = " ".join(a["summary"] for a in answers.get("doorstep", [])
                           if a.get("summary")).strip()
        frames = sorted((run.folder / "store").glob("*.jpg"))
        values: dict[str, Any] = {"state": "done", "end_ms": end_ms,
                                  "video_id": run.video_id, "clip": str(clip),
                                  "summary": summary, "answers": answers}
        if frames:                       # the event's picture: its first frame read
            values["snapshot"] = str(frames[0])
        store.update_event(event_id, **values)
        event = store.event(event_id)
        bus.publish("family", event_message(event))
        for w in watchers:
            await w.on_clip(event, answers)
    except MediaNotFound as exc:
        store.update_event(event_id, state="failed", error=f"no recording: {exc}")
        bus.publish("family", event_message(store.event(event_id)))
    except Exception as exc:
        log.exception("clip %s failed", event_id)
        store.update_event(event_id, state="failed", error=f"{type(exc).__name__}: {exc}")
        bus.publish("family", event_message(store.event(event_id)))
