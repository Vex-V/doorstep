"""The family's search box: a question in, an answer citing clips out.

    1. plan     an LLM turns the question into search phrasings and a date range
    2. search   vidra's hybrid search over every clip in that range, plus the
                list of what was recorded (for "how many", "when did ... last")
    3. answer   an LLM answers from that evidence alone, citing event ids

The clips' wall-clock times live in the app's database, so the date range is
resolved here into the library's video ids.
"""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timedelta
from typing import Any

from ..core import clock as clocks
from ..core import models as m
from ..core.config import settings

PLAN = m.strict("plan", {
    "searches": {"type": "array", "items": {"type": "string"}},
    "from_day": {"type": ["string", "null"]},
    "to_day": {"type": ["string", "null"]},
    "cameras": {"type": "array", "items": {"type": "string"}},
})

ANSWER = m.strict("answer", {
    "answer": {"type": "string"},
    "cited": {"type": "array", "items": {"type": "string"}},
})

PLAN_SYSTEM = """You plan a search over an older relative's home camera clips. Give 1-3 \
short search phrasings describing what would be visible in the footage (not the question \
itself: "a person in a delivery uniform leaving a parcel", not "when did my parcel come"). \
Give the date range the question is about as YYYY-MM-DD (null for the last 7 days), and \
camera ids if the question names a camera, else an empty list."""

ANSWER_SYSTEM = """You answer a family member's question about an older relative's day, \
using only the camera evidence given. Be brief and plain, give times, and list the \
event ids your answer rests on in "cited" (never in the answer's text). If the evidence \
does not answer the question, say so rather than guessing. Never name or identify a \
person; describe them as the clips do."""


def _range(store, plan: dict[str, Any], now: int) -> tuple[int, int]:
    tz = settings().tz
    today = clocks.day_of(now, tz)
    lo_day = plan.get("from_day") or (datetime.strptime(today, "%Y-%m-%d")
                                      - timedelta(days=6)).strftime("%Y-%m-%d")
    hi_day = plan.get("to_day") or today
    try:
        lo, _ = clocks.day_bounds(lo_day, tz)
        _, hi = clocks.day_bounds(hi_day, tz)
    except ValueError:
        lo, _ = clocks.day_bounds(today, tz)
        _, hi = clocks.day_bounds(today, tz)
    return lo, min(hi, now + 1)


def visits_between(store, lo: int, hi: int, now: int) -> list[dict[str, Any]]:
    """What was seen of each expected visit in [lo, hi)."""
    from ..alerts.visits import Visits

    return Visits(store, None).outcomes(lo, hi, now)


def _search(query: str, video_ids: list[str]) -> list[Any]:
    from vidra import Folder
    from vidra.video_rag import search

    from ..core.models import models

    moments, _ = search(query, video_id=video_ids, moments=6,
                        database=Folder(settings().out), models=models())
    return moments


async def answer(store, question: str) -> dict[str, Any]:
    tz = settings().tz
    now = clocks.now_ms()
    cameras = store.cameras()
    names = {c["id"]: c["name"] for c in cameras}
    plan = await m.complete(
        f"Now: {clocks.to_dt(now, tz).strftime('%A %Y-%m-%d %H:%M')}\n"
        f"Cameras: {json.dumps(names)}\nQuestion: {question}",
        schema=PLAN, system=PLAN_SYSTEM, max_output_tokens=2000)
    lo, hi = _range(store, plan, now)
    wanted = [c for c in plan.get("cameras") or [] if c in names]
    events = [e for e in store.events(lo, hi)
              if not wanted or e["camera"] in wanted]
    done = [e for e in events if e["state"] == "done" and e.get("video_id")]
    by_video = {e["video_id"]: e for e in done}

    found: dict[str, dict[str, Any]] = {}
    if done:
        for query in (plan.get("searches") or [question])[:3]:
            moments = await asyncio.to_thread(_search, query, list(by_video))
            for mo in moments:
                e = by_video.get(mo.video_id)
                if e is None:
                    continue
                hit = found.setdefault(e["id"], {"event_id": e["id"], "offset_s": mo.start_ts,
                                                 "matched": []})
                hit["matched"] += [h.get("content", "")[:400] for h in mo.hits[:2]]

    expected = visits_between(store, lo, hi, now)
    listing = [{"event_id": e["id"],
                "time": clocks.to_dt(e["start_ms"], tz).strftime("%a %H:%M"),
                "camera": names.get(e["camera"], e["camera"]),
                "kind": "doorbell" if e["kind"] == "ding" else "motion",
                "what": (e.get("summary") or "(not described yet)")[:300]}
               for e in events][-80:]
    if not listing and not expected:
        return {"answer": "Nothing was recorded in that period.", "citations": [],
                "plan": plan}
    result = await m.complete(
        f"Question: {question}\n\nEverything recorded in the period:\n"
        f"{json.dumps(listing, indent=1)}\n\nExpected visits the family set up, and what "
        f"was seen of each (matched by the family's description):\n"
        f"{json.dumps(expected, indent=1)}\n\nClips the search ranked highest, with what "
        f"matched:\n{json.dumps(list(found.values()), indent=1)}",
        schema=ANSWER, system=ANSWER_SYSTEM, max_output_tokens=3000)
    citations = []
    for event_id in result.get("cited") or []:
        e = store.event(event_id)
        if e is None:
            continue
        citations.append({"event_id": e["id"], "camera": names.get(e["camera"], e["camera"]),
                          "time": clocks.to_dt(e["start_ms"], tz).strftime("%a %d %b %H:%M"),
                          "offset_s": (found.get(e["id"]) or {}).get("offset_s", 0),
                          "summary": e.get("summary")})
    return {"answer": result.get("answer", ""), "citations": citations, "plan": plan}
