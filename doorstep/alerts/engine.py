"""Runs the approved rules.

    on_clip     a processed clip's answers, for on_event and persists rules
    poll        snapshots for persists rules that are watching something
    deadlines   absent rules whose deadline has passed today

State per rule: idle -> watching -> fired, back to idle when an answer says
the condition no longer holds. An unsure answer ("cannot tell") changes
nothing, in either direction.
"""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..core import clock as clocks
from . import notify
from ..core.bus import bus
from ..core.config import settings
from ..core.models import models
from ..ring.api import MediaNotFound
from . import rules

log = logging.getLogger("doorstep.rules")

#: An absent rule alerts only this soon after its deadline: a timeline cleared
#: later, or a server started hours on, must not alert about the morning.
ALERT_WITHIN_MIN = 60


class Engine:
    def __init__(self, store, ring) -> None:
        self.store = store
        self.ring = ring

    @property
    def tz(self):
        return settings().tz

    def enabled(self) -> list[tuple[int, dict[str, Any]]]:
        return [(r["id"], r["compiled"]) for r in self.store.rules(enabled=True)]

    def questions_for(self, camera: str) -> list[str]:
        """The rule questions every clip from `camera` must be asked -- an absent
        rule's too: its deadline reads them back from the day's clips."""
        return [rules.question_name(rid) for rid, c in self.enabled()
                if c.get("fields") and rules.watches(c, camera)]

    def _camera_name(self, camera: str) -> str:
        cam = self.store.camera(camera)
        return cam["name"] if cam else camera

    async def fire(self, rule_id: int, c: dict[str, Any], at_ms: int, message: str,
                   event_id: Optional[str] = None, snapshot: Optional[str] = None) -> None:
        await notify.alert(self.store, self.ring, rule_id, at_ms, c["title"], message,
                           event_id, snapshot)

    def _publish_state(self, rule_id: int) -> None:
        bus.publish("family", {"type": "rule_state", "rule_id": rule_id,
                               **self.store.state(rule_id)})

    # -- clips ----------------------------------------------------------------

    async def on_clip(self, event: dict[str, Any],
                      answers: dict[str, list[dict[str, Any]]]) -> None:
        at = event["start_ms"]
        minute = clocks.minutes_of_day(at, self.tz)
        for rid, c in self.enabled():
            if c["kind"] == "absent" or not rules.watches(c, event["camera"]):
                continue
            v = rules.verdict_over(c, answers.get(rules.question_name(rid), []))
            if c["kind"] == "on_event":
                if v is True and rules.in_window(c, minute) and \
                        rules.triggered_by(c, event["kind"]) and \
                        not self.store.alerted(rid, event["id"]):
                    summary = event.get("summary") or "see the clip"
                    await self.fire(rid, c, at,
                                    f"{self._camera_name(event['camera'])}, "
                                    f"{clocks.hhmm(at, self.tz)}: {summary}",
                                    event["id"], event.get("snapshot"))
                continue
            st = self.store.state(rid)
            if v is True and st["state"] not in ("watching", "fired"):
                self.store.set_state(rid, state="watching", since_ms=at,
                                     event_id=event["id"],
                                     last_check_ms=event.get("end_ms") or at,
                                     detail={"camera": event["camera"]})
                self._publish_state(rid)
            elif v is False and st["state"] in ("watching", "fired"):
                self._clear(rid, event["camera"], at, f"clip {event['id']}")

    def _clear(self, rid: int, camera: str, at_ms: int, why: str) -> None:
        self.store.set_state(rid, state="idle", since_ms=None,
                             detail={"camera": camera, "cleared_ms": at_ms, "by": why})
        self._publish_state(rid)

    # -- snapshots ------------------------------------------------------------

    async def poll(self, now_ms: Optional[int] = None) -> int:
        """Check every watching persists rule that is due. Returns checks made."""
        from vidra.video_rag import describe
        from ..footage.clips import save_snapshot
        from ..footage.questions import answer_dict

        now = clocks.now_ms() if now_ms is None else now_ms
        made = 0
        for rid, c in self.enabled():
            if c["kind"] != "persists":
                continue
            st = self.store.state(rid)
            if st["state"] not in ("watching", "fired"):
                continue
            last = st["last_check_ms"] or st["since_ms"] or now
            if now - last < c["check_every_minutes"] * 60_000:
                continue
            camera = (st.get("detail") or {}).get("camera") or (c["cameras"] or [None])[0]
            self.store.set_state(rid, last_check_ms=now)
            if camera is None:
                continue
            try:
                jpeg = await self.ring.snapshot(camera, now)
            except MediaNotFound:
                log.info("rule %s: no snapshot from %s at %s", rid, camera, now)
                continue
            path = save_snapshot(camera, now, jpeg)
            q = rules.question_name(rid)
            try:
                answer = answer_dict(await describe.ask_async([jpeg], q, vlm=models().vlm))
            except Exception as exc:
                log.warning("rule %s: snapshot question failed: %s", rid, exc)
                continue
            self.store.add_snapshot(camera, now, str(path), q, answer)
            made += 1
            v = rules.verdict(c, answer)
            if v is False:
                self._clear(rid, camera, now, "snapshot")
            elif v is True and st["state"] == "watching" and \
                    now - st["since_ms"] >= c["for_minutes"] * 60_000 and \
                    rules.in_window(c, clocks.minutes_of_day(now, self.tz)):
                minutes = (now - st["since_ms"]) // 60_000
                await self.fire(rid, c, now,
                                f"{self._camera_name(camera)}: still true at "
                                f"{clocks.hhmm(now, self.tz)}, {minutes} minutes after "
                                f"{clocks.hhmm(st['since_ms'], self.tz)}.",
                                st["event_id"], str(path))
                self.store.set_state(rid, state="fired")
                self._publish_state(rid)
        return made

    # -- deadlines ------------------------------------------------------------

    async def deadlines(self, now_ms: Optional[int] = None) -> None:
        now = clocks.now_ms() if now_ms is None else now_ms
        day = clocks.day_of(now, self.tz)
        minute = clocks.minutes_of_day(now, self.tz)
        day_start, _ = clocks.day_bounds(day, self.tz)
        for rid, c in self.enabled():
            if c["kind"] != "absent":
                continue
            deadline = rules._minutes(c["deadline"])
            st = self.store.state(rid)
            if not deadline <= minute < deadline + ALERT_WITHIN_MIN or (
                    st["day"] == day and st["state"] in ("satisfied", "fired")):
                continue
            begin = rules._minutes((c.get("window") or {}).get("from", "00:00"))
            lo, hi = day_start + begin * 60_000, day_start + deadline * 60_000
            events = [e for e in self.store.events(lo, hi)
                      if rules.watches(c, e["camera"])]
            if c.get("fields"):
                if any(e["state"] in ("new", "processing") for e in events):
                    continue                     # decide once the clips are read
                q = rules.question_name(rid)
                met = [e for e in events
                       if rules.verdict_over(c, (e.get("answers") or {}).get(q, [])) is True]
            else:
                met = events
            if met:
                self.store.set_state(rid, state="satisfied", day=day,
                                     event_id=met[0]["id"], since_ms=met[0]["start_ms"])
            else:
                cams = ", ".join(self._camera_name(x) for x in c["cameras"]) or "any camera"
                since = clocks.hhmm(lo, self.tz)
                if not c.get("fields"):
                    message = f"Nothing recorded on {cams} between {since} and {c['deadline']}."
                elif not events:
                    message = (f"Not seen by {c['deadline']}: nothing was recorded on {cams} "
                               f"since {since}.")
                else:
                    message = (f"None of the {len(events)} clip"
                               f"{'s' if len(events) > 1 else ''} from {cams} since "
                               f"{since} showed it.")
                # The latest clip's picture: what the camera last saw (the paper
                # still on the step).
                last = events[-1] if events else {}
                if last.get("snapshot"):
                    message += f" The picture is from {clocks.hhmm(last['start_ms'], self.tz)}."
                await self.fire(rid, c, now, message, last.get("id"), last.get("snapshot"))
                self.store.set_state(rid, state="fired", day=day)
            self._publish_state(rid)
