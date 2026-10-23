"""Rehearse the demo: set Doorstep up as the video does, play the simulator's
day through Doorstep's own Next (as the recording does), and check that each
thing the video shows happened.

    python -m ringsim scenarios/demo/scenario.json            # terminal 1
    python -m doorstep                                         # terminal 2 (RING_SIM=1)
    python scripts/rehearse.py

It starts from an empty Doorstep (everything is deleted first), adds the
expected visits, then the alerts through the real compiler (which reads the
visits: "anyone who isn't the carer" needs to know what the carer looks like),
and starts the day over. Each stop is printed as it is reached, with what it
brought and how many real seconds it took; then each check, PASS or FAIL.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime
from typing import Any, Callable, Optional
from zoneinfo import ZoneInfo

import httpx

ON_CAMERA = "Tell me if anyone rings who isn't the carer or a delivery"
OFF_CAMERA = {
    "kitchen": "Tell me if there's no movement in the kitchen by 9:30am",
    "floor": "Tell me if someone is on the floor for more than 2 minutes",
    "night": "Let me know if Mum goes out the front door between 11pm and 6am",
}


class Rehearsal:
    def __init__(self, doorstep: str, sim: str) -> None:
        self.d = httpx.Client(base_url=doorstep, timeout=120)
        self.s = httpx.Client(base_url=sim, timeout=30)
        self.results: list[dict[str, Any]] = []
        self.rule_ids: dict[str, int] = {}

    # -- plumbing -------------------------------------------------------------

    def day(self) -> dict[str, Any]:
        return self.d.get("/api/timeline").json()

    def settled(self, timeout: float = 300) -> None:
        """Nothing queued, read or asked, twice running (as the page waits)."""
        quiet, t0 = 0, time.time()
        while quiet < 2 and time.time() - t0 < timeout:
            time.sleep(1)
            d = self.day()
            reading = any(e["state"] in ("new", "processing") for e in d["events"])
            quiet = 0 if d["worker"]["busy"] or reading else quiet + 1

    def check(self, name: str, run: Callable[[], tuple[bool, str]]) -> None:
        try:
            ok, detail = run()
        except Exception as exc:                     # a check failing must not stop the rest
            ok, detail = False, f"{type(exc).__name__}: {exc}"
        self.results.append({"check": name, "ok": ok, "detail": detail})
        print(f"{'PASS' if ok else 'FAIL'}  {name:<52} {detail}", flush=True)

    def alerts_of(self, key: str) -> list[dict[str, Any]]:
        return [a for a in self.day()["alerts"] if a.get("rule_id") == self.rule_ids[key]]

    def at_of(self, ms: Optional[int]) -> str:
        tz = ZoneInfo(self.day()["tz"])
        return datetime.fromtimestamp(ms / 1000, tz).strftime("%H:%M") if ms else "?"

    # -- the day --------------------------------------------------------------

    def run(self, carer: str, evening: str) -> None:
        self.d.delete("/api/everything").raise_for_status()
        for label, desc, lo, hi in (("the carer", carer, "11:00", "12:00"),
                                    ("the evening carer", evening, "18:00", "19:00")):
            self.d.post("/api/visits", json={"label": label, "description": desc,
                                             "from_hhmm": lo, "to_hhmm": hi,
                                             "cameras": ["front"]}).raise_for_status()
        rule = self.d.post("/api/rules", json={"text": ON_CAMERA}).json()
        self.rule_ids["caller"] = rule["id"]
        self.check("on camera: the alert names the carer, doorbell only",
                   lambda: ("VOLUNTEER" in rule["sentence"] and "doorbell" in rule["sentence"],
                            f"“{rule['sentence'][:120]}…”"))
        for key, text in OFF_CAMERA.items():
            r = self.d.post("/api/rules", json={"text": text}).json()
            self.rule_ids[key] = r["id"]
            print(f"      alert: {r['sentence'][:110]}")
        self.d.post("/api/sim/restart").raise_for_status()

        t0 = time.time()
        while True:
            t = time.time()
            before = len(self.day()["alerts"])
            s = self.d.post("/api/sim/next").json()
            if s.get("done"):
                break
            self.settled()
            new = self.day()["alerts"][before:]
            print(f"STOP  {s['what'][:60]:<60} {time.time() - t:5.1f}s  "
                  + ("; ".join(a["title"] for a in new) or "-"), flush=True)
        print(f"      the whole day: {time.time() - t0:.0f}s\n")

        d = self.day()
        events = {e["id"]: e for e in d["events"]}

        def one(key: str, at: str, camera: Optional[str] = None) -> tuple[bool, str]:
            got = self.alerts_of(key)
            times = [self.at_of(a["at_ms"]) for a in got]
            where = [events.get(a.get("event_id"), {}).get("camera") for a in got]
            ok = len(got) == 1 and times[0].startswith(at[:4]) and \
                (camera is None or where[0] == camera)
            return ok, f"{len(got)} alert(s) at {', '.join(times) or '-'}" + \
                (f": “{got[0]['message'][:90]}”" if got else "")

        self.check("09:30 nobody in the kitchen", lambda: one("kitchen", "09:30"))
        self.check("15:1x someone still on the floor (living room)",
                   lambda: one("floor", "15:1", None))
        self.check("16:40 an unexpected caller, and no one else",
                   lambda: one("caller", "16:40", "front"))
        self.check("23:50 going out at night", lambda: one("night", "23:5", "front"))

        def visits():
            v = {x["label"]: x for x in d["visits"]}
            c, e = v["the carer"]["today"] or {}, v["the evening carer"]
            return (c.get("arrived") == "11:12" and c.get("left") == "11:31"
                    and e["state"] == "missed",
                    f"carer {c.get('arrived')}–{c.get('left')} ({c.get('stayed_minutes')} min); "
                    f"evening carer {e['state']}")
        self.check("the carer came and went; the evening carer missed", visits)

        def rings():
            dings = [e for e in d["events"] if e["kind"] == "ding" and e["state"] == "done"]
            return len(dings) == 3, f"{len(dings)} doorbell presses read: " + \
                ", ".join(self.at_of(e["start_ms"]) for e in dings)
        self.check("doorbell presses become notifications", rings)

        def chimes():
            c = self.s.get("/sim/state").json()["chimes"]
            return len(c) == len(d["alerts"]), f"{len(c)} chimes for {len(d['alerts'])} alerts"
        self.check("every alert rang the Chime", chimes)

        def ask():
            a = self.d.post("/api/ask", json={
                "question": "Did the carer come today, and how long did they stay?"}).json()
            return "19" in a["answer"], f"“{a['answer'][:120]}”"
        self.check("ask: did the carer come, how long", ask)

        self.check("the evening digest", lambda: (bool(d.get("digest")),
                                                  f"“{(d.get('digest') or {}).get('headline')}”"))


def main() -> None:
    p = argparse.ArgumentParser(description=__doc__,
                                formatter_class=argparse.RawDescriptionHelpFormatter)
    p.add_argument("--doorstep", default="http://127.0.0.1:8000")
    p.add_argument("--sim", default="http://127.0.0.1:8100")
    # The demo footage's carer, and an evening carer who never comes.
    p.add_argument("--carer", default="someone in a white VOLUNTEER T-shirt")
    p.add_argument("--evening-carer", default="a woman in a green care uniform")
    p.add_argument("--out", help="write the results here as JSON")
    a = p.parse_args()
    r = Rehearsal(a.doorstep, a.sim)
    t0 = time.time()
    r.run(a.carer, a.evening_carer)
    passed = sum(x["ok"] for x in r.results)
    print(f"\n{passed}/{len(r.results)} checks, {time.time() - t0:.0f}s in all")
    if a.out:
        with open(a.out, "w", encoding="utf-8") as f:
            json.dump(r.results, f, indent=1)
    sys.exit(0 if passed == len(r.results) else 1)


if __name__ == "__main__":
    main()
