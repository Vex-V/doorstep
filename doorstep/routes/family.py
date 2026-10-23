"""The family's page.

    GET  /                          the page
    GET  /api/timeline              everything received: cameras, events, alerts,
                                    rules, visits, the digest
    GET  /api/events/{id}           one event, with everything the model answered
    POST /api/ask                   a question about the footage
    POST /api/digest                write the digest now
    GET  /media/...                 clips and pictures
    DELETE /api/events/{id}         one clip
    DELETE /api/timeline            every clip, alert and visit seen; the setup stays
    DELETE /api/everything          the setup too
    GET  /api/stream/family         server-sent events
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Optional

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import FileResponse, StreamingResponse
from pydantic import BaseModel

from .. import privacy
from ..answers import ask as asking
from ..answers import digest
from ..core import clock as clocks
from ..core.bus import bus
from ..core.config import settings
from ..state import sim_view, state
from .alerts import names, rule_view

router = APIRouter()
STATIC = Path(__file__).parent.parent / "static"


def event_view(e: dict[str, Any]) -> dict[str, Any]:
    return {k: e.get(k) for k in ("id", "camera", "kind", "subtype", "start_ms", "end_ms",
                                   "state", "summary", "error")} | {
        "has_clip": bool(e.get("clip")), "has_snapshot": bool(e.get("snapshot"))}


@router.get("/")
async def family_page():
    return FileResponse(STATIC / "family.html")


@router.get("/api/timeline")
async def timeline():
    now = clocks.now_ms()
    cameras = names()
    d = state.store.digest()
    return {"now_ms": now, "tz": str(settings().tz),
            "cameras": state.store.cameras(),
            "events": [event_view(e) for e in state.store.events()],
            "alerts": state.store.alerts(),
            "rules": [rule_view(r, cameras) for r in state.store.rules()],
            "visits": state.worker.visits.view(now),
            "digest": d["body"] if d else None,
            "worker": state.worker.status(),
            "sim": sim_view()}


@router.get("/api/events/{event_id}")
async def event_detail(event_id: str):
    e = state.store.event(event_id)
    if e is None:
        raise HTTPException(404, "no such event")
    return event_view(e) | {"answers": e.get("answers")}


# -- ask and the digest ---------------------------------------------------------

class AskBody(BaseModel):
    question: str


@router.post("/api/ask")
async def ask(body: AskBody):
    if not body.question.strip():
        raise HTTPException(400, "ask a question")
    return await asking.answer(state.store, body.question.strip())


@router.post("/api/digest")
async def digest_make():
    return await digest.make(state.store)


# -- media ----------------------------------------------------------------------

def _file(path: Optional[str], media_type: str) -> FileResponse:
    if not path or not Path(path).is_file():
        raise HTTPException(404, "not available")
    return FileResponse(path, media_type=media_type)


@router.get("/media/clip/{event_id}")
async def media_clip(event_id: str):
    e = state.store.event(event_id) or {}
    return _file(e.get("clip"), "video/mp4")


@router.get("/media/event-snapshot/{event_id}")
async def media_event_snapshot(event_id: str):
    e = state.store.event(event_id) or {}
    return _file(e.get("snapshot"), "image/jpeg")


@router.get("/media/alert-snapshot/{alert_id}")
async def media_alert_snapshot(alert_id: int):
    a = next((a for a in state.store.alerts() if a["id"] == alert_id), None) or {}
    return _file(a.get("snapshot"), "image/jpeg")


# -- deletion -------------------------------------------------------------------

@router.delete("/api/events/{event_id}")
async def delete_event(event_id: str):
    if not privacy.delete_event(state.store, event_id):
        raise HTTPException(404, "no such event")
    bus.publish("family", {"type": "deleted", "event_id": event_id})
    return {"ok": True}


@router.delete("/api/timeline")
async def clear_timeline():
    privacy.clear_timeline(state.store)
    state.worker.forget()
    bus.publish("family", {"type": "deleted", "everything": False})
    return {"ok": True}


@router.delete("/api/everything")
async def delete_everything():
    privacy.delete_everything(state.store)
    state.worker.forget()
    bus.publish("family", {"type": "deleted", "everything": True})
    return {"ok": True}


# -- live updates ---------------------------------------------------------------

@router.get("/api/stream/{channel}")
async def stream(channel: str, request: Request):
    if channel != "family":
        raise HTTPException(404, "no such stream")

    async def events():
        yield ": connected\n\n"
        async for message in bus.subscribe(channel):
            if await request.is_disconnected():
                break
            yield f"data: {json.dumps(message, default=str)}\n\n"

    return StreamingResponse(events(), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})
