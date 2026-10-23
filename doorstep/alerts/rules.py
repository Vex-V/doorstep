"""A rule as the engine runs it, checked, and said back in plain English.

    {"kind": "persists",                  on_event | persists | absent
     "title": "Parcel left on the step",  the alert's headline
     "cameras": ["front"],                [] is every camera
     "instruction": "Look at the doorstep.",
     "fields": [{"name": "parcel", "about": "is a parcel on the step",
                 "one_of": ["yes", "no", "cannot tell"]}],
     "when": [{"field": "parcel", "op": "is", "value": "yes"}],     all must hold
     "window": {"from": "08:00", "to": "20:00"},                    or null
     "on": "any",                         on_event: "doorbell" is presses only
     "for_minutes": 120, "check_every_minutes": 15,                 persists
     "deadline": null}                                              absent: "11:00"

`fields` become the rule's own question (`rule_<id>`), asked of every clip
from its cameras and, for `persists`, of a snapshot every few minutes. An
`absent` rule with no fields needs no model at all: any recorded motion
satisfies it.

The approval sentence is generated from this structure, never by a model, so
what the family approves is exactly what will run.
"""

from __future__ import annotations

import re
from typing import Any, Optional

from ..footage.questions import CANNOT_TELL

KINDS = ("on_event", "persists", "absent")
TRIGGERS = ("any", "doorbell")
OPS = ("is", "is_not", "mentions")
HHMM = re.compile(r"^([01]\d|2[0-3]):[0-5]\d$")
FIELD = re.compile(r"^[a-z][a-z0-9_]{0,31}$")


class RuleError(ValueError):
    pass


def question_name(rule_id: int) -> str:
    return f"rule_{rule_id}"


def library_fields(compiled: dict[str, Any]) -> dict[str, Any]:
    """The rule's fields in the library's field builder."""
    out = {}
    for f in compiled.get("fields") or []:
        spec: dict[str, Any] = {"type": "text", "about": f["about"]}
        if f.get("one_of"):
            values = [str(v) for v in f["one_of"]]
            if CANNOT_TELL not in values:
                values.append(CANNOT_TELL)
            spec["one_of"] = values
        out[f["name"]] = spec
    return out


def normalise(c: dict[str, Any]) -> dict[str, Any]:
    """Fill defaults and tidy a compiled rule; `problems` then checks it."""
    c = dict(c)
    c["kind"] = str(c.get("kind") or "").strip()
    c["title"] = str(c.get("title") or "").strip()[:80]
    c["cameras"] = [str(x) for x in c.get("cameras") or []]
    c["instruction"] = str(c.get("instruction") or "").strip()
    fields = []
    for f in c.get("fields") or []:
        name = re.sub(r"[^a-z0-9_]", "_", str(f.get("name", "")).strip().lower())[:32]
        one_of = [str(v).strip().lower() for v in f.get("one_of") or [] if str(v).strip()]
        if one_of and CANNOT_TELL not in one_of:
            one_of.append(CANNOT_TELL)
        fields.append({"name": name, "about": str(f.get("about", "")).strip(),
                       "one_of": one_of or None})
    c["fields"] = fields
    c["when"] = [{"field": str(w.get("field", "")).strip().lower(),
                  "op": str(w.get("op", "is")).strip(),
                  "value": str(w.get("value", "")).strip().lower()}
                 for w in c.get("when") or []]
    window = c.get("window")
    c["window"] = ({"from": window.get("from"), "to": window.get("to")}
                   if isinstance(window, dict) and window.get("from") and window.get("to")
                   else None)
    if c["kind"] == "persists":
        c["for_minutes"] = int(c.get("for_minutes") or 30)
        c["check_every_minutes"] = int(c.get("check_every_minutes") or
                                       max(5, min(15, c["for_minutes"] // 4 or 5)))
    else:
        c["for_minutes"] = None
        c["check_every_minutes"] = None
    c["deadline"] = c.get("deadline") if c["kind"] == "absent" else None
    c["on"] = (str(c.get("on") or "any").strip().lower() if c["kind"] == "on_event"
               else "any")
    return c


def problems(c: dict[str, Any], cameras: Optional[list[str]] = None) -> list[str]:
    out = []
    if c.get("kind") not in KINDS:
        out.append(f"kind must be one of {', '.join(KINDS)}")
    if not c.get("title"):
        out.append("a title is needed for the alert")
    for cam in c.get("cameras") or []:
        if cameras is not None and cam not in cameras:
            out.append(f"no camera {cam!r}; cameras: {', '.join(cameras)}")
    names = [f["name"] for f in c.get("fields") or []]
    if len(names) > 6:
        out.append("at most 6 fields")
    for f in c.get("fields") or []:
        if not FIELD.match(f["name"]):
            out.append(f"field name {f['name']!r} must be lowercase letters, digits, _")
        if not f["about"]:
            out.append(f"field {f['name']!r} needs an 'about'")
    if len(set(names)) != len(names):
        out.append("field names repeat")
    if names and not c.get("instruction"):
        out.append("an instruction is needed when the rule asks a question")
    if not names and c.get("kind") != "absent":
        out.append(f"a {c.get('kind')} rule must ask something: give it fields")
    for w in c.get("when") or []:
        if w["field"] not in names:
            out.append(f"condition on unknown field {w['field']!r}")
        if w["op"] not in OPS:
            out.append(f"op must be one of {', '.join(OPS)}")
        f = next((f for f in c.get("fields") or [] if f["name"] == w["field"]), None)
        if f and f["one_of"] and w["op"] != "mentions" and w["value"] not in f["one_of"]:
            out.append(f"{w['field']} is never {w['value']!r}; it answers one of "
                       f"{', '.join(f['one_of'])}")
        if w["value"] == CANNOT_TELL:
            out.append("a condition cannot be 'cannot tell': an unsure answer never fires")
    if names and not c.get("when"):
        out.append("the rule asks a question but has no condition")
    window = c.get("window")
    if window and not (HHMM.match(window["from"] or "") and HHMM.match(window["to"] or "")):
        out.append("window times must be HH:MM")
    if c.get("kind") == "persists":
        if not 1 <= c["for_minutes"] <= 24 * 60:
            out.append("for_minutes must be between 1 and 1440")
        if not 1 <= c["check_every_minutes"] <= c["for_minutes"]:
            out.append("check_every_minutes must be between 1 and for_minutes")
    if c.get("on", "any") not in TRIGGERS:
        out.append(f"on must be one of {', '.join(TRIGGERS)}")
    if c.get("kind") == "absent" and not HHMM.match(str(c.get("deadline") or "")):
        out.append("an absent rule needs a deadline, HH:MM")
    return out


def check(c: dict[str, Any], cameras: Optional[list[str]] = None) -> dict[str, Any]:
    c = normalise(c)
    found = problems(c, cameras)
    if found:
        raise RuleError("; ".join(found))
    return c


# -- evaluation ---------------------------------------------------------------

def _minutes(hhmm: str) -> int:
    h, m = hhmm.split(":")
    return int(h) * 60 + int(m)


def in_window(c: dict[str, Any], minute_of_day: int) -> bool:
    window = c.get("window")
    if not window:
        return True
    lo, hi = _minutes(window["from"]), _minutes(window["to"])
    if lo <= hi:
        return lo <= minute_of_day < hi
    return minute_of_day >= lo or minute_of_day < hi        # wraps midnight


def triggered_by(c: dict[str, Any], event_kind: str) -> bool:
    """A "doorbell" rule looks only at presses ("ding"), never at motion."""
    return c.get("on", "any") != "doorbell" or event_kind == "ding"


def watches(c: dict[str, Any], camera: str) -> bool:
    return not c.get("cameras") or camera in c["cameras"]


def _holds(cond: dict[str, Any], value: Any) -> Optional[bool]:
    """True, False, or None when the answer says nothing either way."""
    values = value if isinstance(value, list) else [value]
    texts = [str(v).strip().lower() for v in values if v is not None and str(v).strip()]
    if not texts or all(t in (CANNOT_TELL, "unclear", "unknown") for t in texts):
        return None
    target = cond["value"]
    if cond["op"] == "mentions":
        return any(target in t for t in texts)
    hit = any(t == target for t in texts)
    return hit if cond["op"] == "is" else not hit


def verdict(c: dict[str, Any], answer: Optional[dict[str, Any]]) -> Optional[bool]:
    """Does one answer (one chunk, or one snapshot) meet every condition?
    None is "cannot tell", which never fires and never clears."""
    if not answer:
        return None
    results = [_holds(cond, answer.get(cond["field"])) for cond in c.get("when") or []]
    if any(r is False for r in results):
        return False
    if any(r is None for r in results):
        return None
    return True


def verdict_over(c: dict[str, Any], answers: list[dict[str, Any]]) -> Optional[bool]:
    """A clip: true if any chunk meets the rule, false if every chunk that said
    anything did not, else unknown."""
    seen = [verdict(c, a) for a in answers]
    if any(v is True for v in seen):
        return True
    if any(v is False for v in seen):
        return False
    return None


# -- the approval sentence ----------------------------------------------------

def _cameras(c: dict[str, Any], names: dict[str, str]) -> str:
    cams = [names.get(x, x) for x in c.get("cameras") or []]
    if not cams:
        return "any camera"
    return "the " + " or the ".join(cams) + (" camera" if len(cams) == 1 else " cameras")


def _conditions(c: dict[str, Any]) -> str:
    about = {f["name"]: f["about"] for f in c.get("fields") or []}
    parts = []
    for w in c.get("when") or []:
        q = about.get(w["field"], w["field"])
        if w["op"] == "is":
            parts.append(f"the answer to “{q}” is “{w['value']}”")
        elif w["op"] == "is_not":
            parts.append(f"the answer to “{q}” is not “{w['value']}”")
        else:
            parts.append(f"the answer to “{q}” mentions “{w['value']}”")
    return " and ".join(parts)


def _minutes_n(n: int) -> str:
    return "1 minute" if n == 1 else f"{n} minutes"


def _window(c: dict[str, Any]) -> str:
    w = c.get("window")
    return f" between {w['from']} and {w['to']}" if w else ""


def sentence(c: dict[str, Any], names: Optional[dict[str, str]] = None) -> str:
    names = names or {}
    cams = _cameras(c, names)
    if c["kind"] == "on_event":
        when = (f"someone presses the doorbell on {cams}" if c.get("on") == "doorbell"
                else f"{cams} records something")
        return (f"Each time {when}{_window(c)}, I will look at the "
                f"clip and alert you if {_conditions(c)}.")
    if c["kind"] == "persists":
        every = c["check_every_minutes"]
        return (f"When {cams} shows that {_conditions(c)}, I will check again every "
                f"{'minute' if every == 1 else f'{every} minutes'}, and alert you"
                f"{_window(c)} if it is still true after {_minutes_n(c['for_minutes'])}. "
                f"An answer I am unsure of never alerts you.")
    start = (c.get("window") or {}).get("from", "00:00")
    if not c.get("fields"):
        return (f"If {cams} records no movement at all between {start} and "
                f"{c['deadline']}, I will alert you at {c['deadline']}.")
    return (f"If no clip from {cams} between {start} and {c['deadline']} shows that "
            f"{_conditions(c)}, I will alert you at {c['deadline']}.")
