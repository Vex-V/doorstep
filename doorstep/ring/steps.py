"""Step through the Ring simulator's day: straight to the next thing that
happens, with nothing in between to wait for.

A stop is a scripted event (jumped to once its clip has finished recording,
so it can be downloaded at once) or a moment Doorstep itself acts on: an
absent rule's deadline, the moment a watching persists rule would fire, the
end of an expected visit's window, the digest. The simulator knows
only its events and Doorstep only its deadlines, so the stops are worked out
here, from both.
"""

from __future__ import annotations

from typing import Any, Optional

from ..core import clock as clocks

#: How long after an event's clip ends, or after a deadline, to stop: long
#: enough that the clip is recorded and the minute's tick has run.
AFTER_CLIP_MS = 5_000
AFTER_DEADLINE_MS = 60_000


def _at(day: str, hhmm: str, tz) -> int:
    h, m = hhmm.split(":")[:2]
    return clocks.day_bounds(day, tz)[0] + (int(h) * 60 + int(m)) * 60_000


def stops(sim: dict[str, Any], rules: list[dict[str, Any]],
          visits: list[dict[str, Any]], digest_min: int, tz) -> list[dict[str, Any]]:
    """Every stop in the simulator's day, in order: {"ms", "what", "event_start"}.
    `rules` carry their `state` (the store's rule_state row)."""
    day = clocks.day_of(sim["clock"]["now_ms"], tz)
    out = [{"ms": e["start_ms"] + e["seconds"] * 1000 + AFTER_CLIP_MS,
            "what": f"{e['at'][:5]} {e['camera']}: {e['note'] or e['type']}",
            "event_start": e["start_ms"]}
           # Sent already (by hand, on the simulator's page): nothing to stop for.
           for e in sim["events"] if e["index"] >= 0 and not e.get("delivered")]
    for r in rules:
        c = r["compiled"]
        if r["enabled"] and c["kind"] == "absent" and c.get("deadline"):
            out.append({"ms": _at(day, c["deadline"], tz) + AFTER_DEADLINE_MS,
                        "what": f"{c['deadline']} deadline: {c['title']}", "event_start": None})
        st = r.get("state") or {}
        if (r["enabled"] and c["kind"] == "persists" and st.get("state") == "watching"
                and st.get("since_ms")):
            ms = st["since_ms"] + c["for_minutes"] * 60_000 + AFTER_DEADLINE_MS
            out.append({"ms": ms, "what": f"{clocks.hhmm(ms, tz)} still? {c['title']}",
                        "event_start": None})
    for v in visits:
        if v["enabled"]:
            out.append({"ms": _at(day, v["to_hhmm"], tz) + AFTER_DEADLINE_MS,
                        "what": f"{v['to_hhmm']} {v['label']} due by now", "event_start": None})
    out.append({"ms": clocks.day_bounds(day, tz)[0] + digest_min * 60_000 + AFTER_DEADLINE_MS,
                "what": f"{digest_min // 60:02d}:{digest_min % 60:02d} the digest",
                "event_start": None})
    return sorted(out, key=lambda s: s["ms"])


def next_stop(sim: dict[str, Any], rules: list[dict[str, Any]],
              visits: list[dict[str, Any]], digest_min: int, tz) -> Optional[dict[str, Any]]:
    now = sim["clock"]["now_ms"]
    return next((s for s in stops(sim, rules, visits, digest_min, tz) if s["ms"] > now), None)
