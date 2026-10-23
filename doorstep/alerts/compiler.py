"""A sentence the family wrote -> a rule the engine can run.

One LLM call fills a strict schema; `rules.check` then holds it to the same
rules a hand-written one meets. Nothing runs until the family has read the
generated sentence and approved it (`activate`)."""

from __future__ import annotations

import json
from typing import Any

from ..core import models as m
from . import rules

_NULLABLE_STR = {"type": ["string", "null"]}

SCHEMA = m.strict("rule", {
    "kind": {"type": "string", "enum": list(rules.KINDS)},
    "title": {"type": "string"},
    "cameras": {"type": "array", "items": {"type": "string"}},
    "instruction": {"type": "string"},
    "fields": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["name", "about", "one_of"],
        "properties": {"name": {"type": "string"}, "about": {"type": "string"},
                       "one_of": {"type": ["array", "null"],
                                  "items": {"type": "string"}}}}},
    "when": {"type": "array", "items": {
        "type": "object", "additionalProperties": False,
        "required": ["field", "op", "value"],
        "properties": {"field": {"type": "string"},
                       "op": {"type": "string", "enum": list(rules.OPS)},
                       "value": {"type": "string"}}}},
    "window": {"anyOf": [{"type": "null"}, {
        "type": "object", "additionalProperties": False, "required": ["from", "to"],
        "properties": {"from": {"type": "string"}, "to": {"type": "string"}}}]},
    "for_minutes": {"type": ["integer", "null"]},
    "check_every_minutes": {"type": ["integer", "null"]},
    "deadline": _NULLABLE_STR,
    "on": {"type": "string", "enum": list(rules.TRIGGERS)},
})

SYSTEM = """You turn a family's plain-English alert into a rule for Doorstep, an app on \
an older relative's Ring cameras. A vision model will answer the rule's question about \
camera footage; your rule decides when an answer means "alert the family".

Kinds:
- on_event: check each new clip; alert when the answer matches (optionally only inside \
a time window). For things that happen: someone leaves at night, a stranger in hi-vis.
- persists: when a clip shows the condition, keep checking snapshots every \
check_every_minutes; alert if it is still true after for_minutes. For states that should \
not last: a parcel left out, the gate open, the newspaper not taken in.
- absent: alert at the deadline if nothing matching happened since the window's start \
that day. With no fields, "nothing" means no recorded movement at all (no model needed).

Write fields as short questions about one image or clip, each answered from a fixed list \
whenever possible. The camera already says where: ask what is visible in its view, \
without restating the camera's place ("is an animal visible", not "is an animal at the \
front door"), unless the alert is about one spot within the view (the step, the gate) \
(one_of, e.g. ["yes", "no"]; "cannot tell" is added for you). Field \
names are snake_case. Conditions compare a field to one of its values (op "is" / \
"is_not"), or look for a word in a free-text field ("mentions"). Never condition on \
"cannot tell". Never ask the model to identify or name a person: describe by appearance, \
clothing, uniform. The family's expected visitors are listed with how they look: the \
vision model has never seen them, so when an alert names one ("the carer"), write their \
description into the field's about. To single out callers who are not someone expected, \
never ask a negative question ("is this not the carer"): ask who is calling, from a list \
naming each expected visitor, the other kinds the alert excuses, "someone else" and \
"nobody calling" (for people of the house and passers-by), and alert on "someone else". \
An on_event rule about someone ringing, knocking or calling at the door has on \
"doorbell", so it looks only at doorbell presses; every other rule has on "any". \
Times are 24-hour HH:MM in the family's time zone. cameras holds \
camera ids from the list given, or is empty for any camera. The title is a short alert \
headline. Leave fields that do not apply to the kind null."""

EXAMPLES = [
    ("Tell me if a parcel is still on the front step after two hours",
     {"kind": "persists", "title": "Parcel left on the step", "cameras": ["front"],
      "instruction": "Look at the doorstep.",
      "fields": [{"name": "parcel_on_step", "about": "is a parcel or package lying on "
                  "the step or by the door", "one_of": ["yes", "no"]}],
      "when": [{"field": "parcel_on_step", "op": "is", "value": "yes"}],
      "window": None, "for_minutes": 120, "check_every_minutes": 15, "deadline": None, "on": "any"}),
    ("Let me know if Mum goes out between midnight and 5am",
     {"kind": "on_event", "title": "Front door: someone went out at night",
      "cameras": ["front"], "instruction": "Watch the front door.",
      "fields": [{"name": "went_out", "about": "does someone leave the house through "
                  "the door", "one_of": ["yes", "no"]}],
      "when": [{"field": "went_out", "op": "is", "value": "yes"}],
      "window": {"from": "00:00", "to": "05:00"}, "for_minutes": None,
      "check_every_minutes": None, "deadline": None, "on": "any"}),
    ("Alert me if there's no movement in the kitchen by 11",
     {"kind": "absent", "title": "No movement in the kitchen this morning",
      "cameras": ["kitchen"], "instruction": "", "fields": [], "when": [],
      "window": {"from": "05:00", "to": "11:00"}, "for_minutes": None,
      "check_every_minutes": None, "deadline": "11:00", "on": "any"}),
    # A state at a time of day is "nobody changed it by then": absent, not a
    # one-minute on_event window.
    ("Tell me if the milk is still on the doorstep at 9am",
     {"kind": "absent", "title": "The milk hasn't been taken in", "cameras": ["front"],
      "instruction": "Look at the doorstep.",
      "fields": [{"name": "milk_taken_in", "about": "does someone pick up the milk from "
                  "the doorstep and take it inside", "one_of": ["yes", "no"]}],
      "when": [{"field": "milk_taken_in", "op": "is", "value": "yes"}],
      "window": {"from": "05:00", "to": "09:00"}, "for_minutes": None,
      "check_every_minutes": None, "deadline": "09:00", "on": "any"}),
    # A visitor is known by the description the family gave; "not them" is one
    # answer of a list, never a negative question.
    ("Tell me if anyone rings who isn't the cleaner or the postman",
     {"kind": "on_event", "title": "An unexpected caller at the door",
      "cameras": ["front"],
      "instruction": "Look at whoever is calling at the door.",
      "fields": [{"name": "caller", "about": "who is calling at the door: the cleaner "
                  "(a tall man in a grey polo shirt), the postman (a postal worker in "
                  "uniform with letters or a parcel), someone else, or nobody calling "
                  "(nobody at the door, someone of the house, or a passer-by)",
                  "one_of": ["the cleaner", "the postman", "someone else",
                             "nobody calling"]}],
      "when": [{"field": "caller", "op": "is", "value": "someone else"}],
      "window": None, "for_minutes": None, "check_every_minutes": None,
      "deadline": None, "on": "doorbell"}),
]

#: The expected visitors each example was written against.
_EXAMPLE_VISITORS = {
    "Tell me if anyone rings who isn't the cleaner or the postman":
        [{"label": "the cleaner", "description": "a tall man in a grey polo shirt",
          "from_hhmm": "09:00", "to_hhmm": "10:00"}],
}


def _visitors(visits: list[dict[str, Any]]) -> str:
    return "\n".join(f"- {v['label']}: {v['description']} (due {v['from_hhmm']}-"
                     f"{v['to_hhmm']})" for v in visits) or "- (none)"


def _prompt(text: str, cameras: list[dict[str, Any]],
            visits: list[dict[str, Any]]) -> str:
    cams = "\n".join(f"- {c['id']}: {c['name']} ({c.get('kind', 'camera')})"
                     for c in cameras) or "- (none yet)"
    shots = "\n\n".join(
        (f"Expected visitors:\n{_visitors(_EXAMPLE_VISITORS[t])}\n"
         if t in _EXAMPLE_VISITORS else "") + f"Alert: {t}\nRule: {json.dumps(r)}"
        for t, r in EXAMPLES)
    return (f"Cameras:\n{cams}\n\nExamples:\n\n{shots}\n\n"
            f"Expected visitors:\n{_visitors(visits)}\nAlert: {text}\nRule:")


async def compile_rule(text: str, cameras: list[dict[str, Any]],
                       visits: list[dict[str, Any]] = ()) -> dict[str, Any]:
    """The rule for `text`, checked; raises `rules.RuleError` when it cannot be.
    `visits` are the expected visitors an alert may name: their descriptions are
    written into the rule, so the family sees them in the approval sentence."""
    text = " ".join(text.split())
    if not text:
        raise rules.RuleError("write the alert you want")
    raw = await m.complete(_prompt(text, cameras, list(visits)), schema=SCHEMA,
                           system=SYSTEM, max_output_tokens=4000)
    if not isinstance(raw, dict):
        raise rules.RuleError("the model did not return a rule")
    return rules.check(raw, [c["id"] for c in cameras])


def activate(rule_id: int, compiled: dict[str, Any]) -> None:
    """Register the rule's question with the library, so clips and snapshots
    are asked it. A rule with no fields asks nothing."""
    from vidra.video_rag import describe

    fields = rules.library_fields(compiled)
    if fields:
        describe.add_question(rules.question_name(rule_id), compiled["instruction"],
                              fields=fields, summary="brief")


def deactivate(rule_id: int) -> None:
    from vidra.video_rag import describe

    try:
        describe.remove_question(rules.question_name(rule_id))
    except Exception:          # never registered (no fields), or already gone
        pass
