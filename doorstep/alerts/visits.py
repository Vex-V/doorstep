"""Expected visits: the family says who is due and when -- "the carer, a woman
with dark hair in a blue tunic, between 09:00 and 10:00" -- and Doorstep notes
when someone matching arrives and leaves, and alerts if nobody has arrived by
the end of the window.

Matching is the family's own description, asked of every clip from the
visit's cameras as a question of its own (`visit_<id>`): appearance and
clothing only, never a face and never a name. An answer of "cannot tell" is
never an arrival. A visit is expected every day, and each day's outcome is
one row:

    arrived   someone matching came (on time, or late after a missed alert)
    left      ... and was seen again at least 5 minutes later, not arriving: how
              long they stayed
    missed    the window closed with nobody matching; the family was alerted
              (only within an hour of the close, so a cleared timeline stays
              quiet)
"""

from __future__ import annotations

import logging
import re
from typing import Any, Optional

from ..core import clock as clocks
from ..core.bus import bus
from ..core.config import settings
from ..footage.questions import CANNOT_TELL
from . import notify

log = logging.getLogger("doorstep.visits")

HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
#: An arrival counts from this many minutes before the window opens.
EARLY_MIN = 60
ARRIVING = {"arriving", "at the door"}
#: A later sighting counts as leaving only this long after the arrival.
LEFT_AFTER_MS = 5 * 60_000
#: A missed visit is alerted only this soon after its window closes: a timeline
#: cleared later, or a server started hours on, must not alert about the morning.
ALERT_WITHIN_MIN = 60


class VisitError(ValueError):
    pass


def question_name(visit_id: int) -> str:
    return f"visit_{visit_id}"


def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def check(label: str, description: str, cameras: list[str], from_hhmm: str,
          to_hhmm: str, known: list[str]) -> dict[str, Any]:
    """A visit as given, tidied; raises `VisitError` listing every problem."""
    v = {"label": " ".join(str(label).split())[:40],
         "description": " ".join(str(description).split())[:300],
         "cameras": [str(c) for c in cameras or []],
         "from_hhmm": str(from_hhmm).strip(), "to_hhmm": str(to_hhmm).strip()}
    found = []
    if not v["label"]:
        found.append("say who is visiting (\"the carer\")")
    if len(v["description"]) < 3:
        found.append("describe them: what they look like and usually wear")
    for cam in v["cameras"]:
        if cam not in known:
            found.append(f"no camera {cam!r}; cameras: {', '.join(known)}")
    if not (HHMM.match(v["from_hhmm"]) and HHMM.match(v["to_hhmm"])):
        found.append("times must be HH:MM")
    elif _minutes(v["from_hhmm"]) >= _minutes(v["to_hhmm"]):
        found.append("the window must end after it starts, on the same day")
    if found:
        raise VisitError("; ".join(found))
    return v


def _question(v: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    # Braces would read as the library's {n}/{span} placeholders.
    description = v["description"].replace("{", "(").replace("}", ")")
    instruction = (
        "These {n} frames come from a home camera and span {span}. The family is "
        f"expecting a visitor they describe as: \"{description}\". Say whether a "
        "person matching that description is in view, judging only by appearance and "
        "clothing, and what that person is doing. Never name or identify anyone.")
    fields = {
        "matches": {"type": "text", "one_of": ["yes", "no", CANNOT_TELL],
                    "about": "is a person matching the description in view"},
        "doing": {"type": "text",
                  "one_of": ["arriving", "leaving", "at the door", "passing by",
                             CANNOT_TELL],
                  "about": "what the matching person is doing; 'cannot tell' if "
                           "nobody matches"},
    }
    return instruction, fields


def register(v: dict[str, Any]) -> None:
    from vidra.video_rag import describe

    instruction, fields = _question(v)
    describe.add_question(question_name(v["id"]), instruction, fields=fields,
                          summary="brief")


def unregister(visit_id: int) -> None:
    from vidra.video_rag import describe

    try:
        describe.remove_question(question_name(visit_id))
    except Exception:          # already gone
        pass


def sentence(v: dict[str, Any], names: Optional[dict[str, str]] = None) -> str:
    """What the visit will do, said back from its fields (never by a model)."""
    names = names or {}
    cams = [names.get(c, c) for c in v.get("cameras") or []]
    where = ("the " + " or the ".join(cams) + " camera") if cams else "any camera"
    return (f"I'll look for {v['label']} (“{v['description']}”) on {where}, and note "
            f"when they arrive and leave. If nobody matching has arrived by "
            f"{v['to_hhmm']} (expected from {v['from_hhmm']}), I'll alert you at "
            f"{v['to_hhmm']}.")


def _norm(value: Any) -> str:
    return str(value or "").strip().lower()


class Visits:
    """The expected-visits tracker: a clip watcher, and a deadline checker."""

    def __init__(self, store, ring) -> None:
        self.store = store
        self.ring = ring

    @property
    def tz(self):
        return settings().tz

    def enabled(self) -> list[dict[str, Any]]:
        return self.store.visits(enabled=True)

    @staticmethod
    def watches(v: dict[str, Any], camera: str) -> bool:
        return not v.get("cameras") or camera in v["cameras"]

    def _where(self, v: dict[str, Any]) -> str:
        names = {c["id"]: c["name"] for c in self.store.cameras()}
        cams = [names.get(c, c) for c in v.get("cameras") or []]
        return ", ".join(cams) or "any camera"

    def _publish(self, v: dict[str, Any], day: str, message: str) -> None:
        """`message` is the notification's body; the page titles it with the
        visitor and what happened ("The carer arrived")."""
        bus.publish("family", {"type": "visit", "visit_id": v["id"], "day": day,
                               "label": v["label"], "message": message,
                               **(self.store.visit_day(v["id"], day) or {})})
        log.info("visit %s: %s", v["label"], message)

    # -- clips ----------------------------------------------------------------

    def questions_for(self, camera: str) -> list[str]:
        return [question_name(v["id"]) for v in self.enabled() if self.watches(v, camera)]

    async def on_clip(self, event: dict[str, Any],
                      answers: dict[str, list[dict[str, Any]]]) -> None:
        at = event["start_ms"]
        day = clocks.day_of(at, self.tz)
        minute = clocks.minutes_of_day(at, self.tz)
        for v in self.enabled():
            if not self.watches(v, event["camera"]):
                continue
            seen = [a for a in answers.get(question_name(v["id"]), [])
                    if _norm(a.get("matches")) == "yes"]
            if not seen or minute < _minutes(v["from_hhmm"]) - EARLY_MIN:
                continue
            doing = {_norm(a.get("doing")) for a in seen}
            leaving = "leaving" in doing and not (doing & ARRIVING)
            row = self.store.visit_day(v["id"], day)
            when = clocks.hhmm(at, self.tz)
            if row is None or (row["arrived_ms"] is None and row["state"] != "left"):
                if leaving:          # arrived out of sight: seen only going
                    self.store.put_visit_day(v["id"], day, state="left", left_ms=at,
                                             left_event=event["id"])
                    self._publish(v, day, f"Left at {when}; not seen arriving.")
                    continue
                late = row is not None and row["state"] == "missed"
                self.store.put_visit_day(v["id"], day, state="arrived", arrived_ms=at,
                                         arrived_event=event["id"])
                self._publish(v, day, f"Arrived{' late,' if late else ''} at {when}, "
                                      f"matching “{v['description']}”.")
            elif row["state"] == "arrived" and at - row["arrived_ms"] >= LEFT_AFTER_MS and \
                    "arriving" not in doing:
                # A doorbell sees people come and go: the visitor seen again a while
                # after arriving is going, whatever the model calls it ("leaving",
                # "at the door" on the way out, "cannot tell" mid-step).
                self.store.put_visit_day(v["id"], day, state="left", left_ms=at,
                                         left_event=event["id"])
                stayed = (at - row["arrived_ms"]) // 60_000 if row["arrived_ms"] else None
                self._publish(v, day, f"Left at {when}" +
                              (f", after {stayed} minutes." if stayed is not None else "."))

    # -- deadlines ------------------------------------------------------------

    async def deadlines(self, now_ms: Optional[int] = None) -> None:
        now = clocks.now_ms() if now_ms is None else now_ms
        day = clocks.day_of(now, self.tz)
        minute = clocks.minutes_of_day(now, self.tz)
        day_start, _ = clocks.day_bounds(day, self.tz)
        for v in self.enabled():
            end = _minutes(v["to_hhmm"])
            if not end <= minute < end + ALERT_WITHIN_MIN or \
                    self.store.visit_day(v["id"], day) is not None:
                continue
            if v["created_ms"] > day_start + end * 60_000:
                continue                 # set up after today's window had closed
            lo = day_start + (_minutes(v["from_hhmm"]) - EARLY_MIN) * 60_000
            events = [e for e in self.store.events(lo, day_start + end * 60_000)
                      if self.watches(v, e["camera"])]
            if any(e["state"] in ("new", "processing") for e in events):
                continue                 # decide once the clips are read
            self.store.put_visit_day(v["id"], day, state="missed")
            await notify.alert(
                self.store, self.ring, None, now, f"{v['label'].capitalize()} hasn't arrived",
                f"Nobody matching “{v['description']}” on {self._where(v)} between "
                f"{v['from_hhmm']} and {v['to_hhmm']}.")
            self._publish(v, day, f"Not seen by {v['to_hhmm']}.")

    # -- for the page, ask and the digest ------------------------------------

    def view(self, now_ms: int) -> list[dict[str, Any]]:
        """Each visit as set up, today's status, and every time it was seen."""
        tz = self.tz
        today = clocks.day_of(now_ms, tz)
        minute = clocks.minutes_of_day(now_ms, tz)
        names = {c["id"]: c["name"] for c in self.store.cameras()}
        out = []
        for v in self.store.visits():
            seen = [_record(r, tz) for r in self.store.visit_days(v["id"])]
            now_row = next((r for r in seen if r["day"] == today), None)
            state = now_row["state"] if now_row else (
                "due" if minute < _minutes(v["to_hhmm"]) else "checking")
            out.append({"id": v["id"], "label": v["label"], "description": v["description"],
                        "cameras": v["cameras"], "from": v["from_hhmm"], "to": v["to_hhmm"],
                        "enabled": bool(v["enabled"]), "state": state,
                        "today": now_row, "seen": seen, "sentence": sentence(v, names)})
        return out

    def outcomes(self, lo: int, hi: int, now_ms: int) -> list[dict[str, Any]]:
        """What was seen of each visit in [lo, hi), for a model to read; a visit
        still due today says so."""
        tz = self.tz
        out = []
        for v in self.view(now_ms):
            base = {"who": v["label"], "looks like": v["description"],
                    "expected": f"{v['from']}-{v['to']} every day"}
            rows = [r for r in v["seen"] if lo <= (r["arrived_ms"] or r["left_ms"] or
                                                   clocks.day_bounds(r["day"], tz)[0]) < hi]
            for r in rows:
                out.append(base | {"date": r["day"], "outcome": r["state"],
                                   "arrived": r["arrived"], "left": r["left"],
                                   "stayed_minutes": r["stayed_minutes"],
                                   "event_ids": [x for x in (r["arrived_event"],
                                                             r["left_event"]) if x]})
            if v["today"] is None and lo <= now_ms <= hi:
                out.append(base | {"date": clocks.day_of(now_ms, tz), "outcome": v["state"]})
        return out


def _record(row: dict[str, Any], tz) -> dict[str, Any]:
    arrived, left = row.get("arrived_ms"), row.get("left_ms")
    return {"day": row["day"], "state": row["state"],
            "arrived": clocks.hhmm(arrived, tz) if arrived else None,
            "left": clocks.hhmm(left, tz) if left else None,
            "stayed_minutes": (left - arrived) // 60_000 if arrived and left else None,
            "arrived_ms": arrived, "left_ms": left,
            "arrived_event": row.get("arrived_event"), "left_event": row.get("left_event")}
