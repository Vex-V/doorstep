"""The digest: the last 24 hours in order, every line tied to its clip.
Written at 8 pm, or whenever the family asks for it.

The app orders the clips by wall-clock time (the library's `combine` lays clips
end to end and loses the gaps between them), then one LLM call writes it."""

from __future__ import annotations

from typing import Any

from ..core import clock as clocks
from ..core import models as m
from ..core.bus import bus
from ..core.config import settings

SPAN_MS = 24 * 3_600_000

SCHEMA = m.strict("digest", {
    "headline": {"type": "string"},
    "lines": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["time", "text", "event_id"],
        "properties": {"time": {"type": "string"}, "text": {"type": "string"},
                       "event_id": {"type": "string"}}}},
    "worth_a_look": {"type": "array", "items": {"type": "string"}},
})

SYSTEM = """You write the digest of the last 24 hours for a family looking out for an \
older relative who lives alone, from their Ring cameras. Plain, warm, factual. One line \
per thing that happened, in time order, merging clips that are one visit (arrival and \
departure). Never name or identify people; describe them as the clips do. Do not invent \
anything the clips do not say; say when something is unclear. "worth_a_look" lists \
anything the family may want to check (alerts that fired, something unusual), or is empty."""


def evidence(store, lo: int, hi: int) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    tz = settings().tz
    names = {c["id"]: c["name"] for c in store.cameras()}
    events = []
    for e in store.events(lo, hi):
        text = e.get("summary") or "(not described)"
        events.append({"event_id": e["id"], "time": clocks.hhmm(e["start_ms"], tz),
                       "camera": names.get(e["camera"], e["camera"]),
                       "kind": "doorbell" if e["kind"] == "ding" else "motion",
                       "what": text[:1200]})
    alerts = [{"time": clocks.hhmm(a["at_ms"], tz), "title": a["title"],
               "message": a["message"]} for a in store.alerts(lo, hi)]
    return events, alerts


async def make(store) -> dict[str, Any]:
    import json

    from .ask import visits_between

    now = clocks.now_ms()
    lo, hi = now - SPAN_MS, now + 1
    events, alerts = evidence(store, lo, hi)
    expected = visits_between(store, lo, hi, now)
    if not events and not alerts:
        body: dict[str, Any] = {"headline": "Nothing was recorded in the last 24 hours.",
                                "lines": [], "worth_a_look": []}
    else:
        when = clocks.to_dt(now, settings().tz).strftime("%A %Y-%m-%d %H:%M")
        prompt = (f"Now: {when}\n\nClips, in time order:\n{json.dumps(events, indent=1)}"
                  f"\n\nExpected visits and what was seen of each:\n"
                  f"{json.dumps(expected, indent=1)}"
                  f"\n\nAlerts that fired:\n{json.dumps(alerts, indent=1)}")
        body = await m.complete(prompt, schema=SCHEMA, system=SYSTEM,
                                max_output_tokens=6000)
        known = {e["event_id"] for e in events}
        for line in body.get("lines") or []:
            if line.get("event_id") not in known:
                line["event_id"] = ""
    body["made_ms"] = now
    store.put_digest(body, now)
    bus.publish("family", {"type": "digest"})
    return body
