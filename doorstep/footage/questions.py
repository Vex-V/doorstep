"""The questions Doorstep asks, registered with the library at start-up.

    doorstep        every clip, every camera: who, doing what, what was left
                    or taken. This is what the family's search box searches.

Each alert rule brings a question of its own (`rule_<id>`), registered when
the rule is approved (rules/compiler.py). No question here asks for a name:
people are described by what they look like, never identified.
"""

from __future__ import annotations

from typing import Any

CANNOT_TELL = "cannot tell"


QUESTIONS: dict[str, dict[str, Any]] = {
    "doorstep": {
        "instruction": (
            "These {n} frames come from a home security camera and span {span}. "
            "Describe what happens. People are described by appearance and "
            "clothing only, never named or identified."),
        "fields": {
            "people": {"type": "list", "about": "each person seen",
                       "of": {"looks": "appearance and clothing, plainly",
                              "doing": "what they do: arriving, leaving, delivering, "
                                       "waiting, passing by, ...",
                              "uniform": "a delivery, postal, utility, carer or other "
                                         "uniform, with any company name, or 'none'"}},
            "someone_left_home": {"type": "text", "one_of": ["yes", "no", CANNOT_TELL],
                                  "about": "did someone leave the home through a "
                                           "door in view"},
            "someone_came_home": {"type": "text", "one_of": ["yes", "no", CANNOT_TELL],
                                  "about": "did someone enter the home through a "
                                           "door in view"},
            "items_left": {"type": "list", "about": "things left at the door or in "
                           "view: a parcel, letters, a newspaper, groceries, ..."},
            "items_taken": {"type": "list", "about": "things picked up or taken away"},
            "vehicles": {"type": "list", "about": "vehicles in view, with any "
                         "company name on them"},
            "animals": {"type": "list", "about": "animals in view"},
        },
        "summary": "brief",
    },
}


def register() -> None:
    """Add (or refresh) every question above. Idempotent: the same text hashes
    the same, so nothing already answered goes stale."""
    from vidra.video_rag import describe

    for name, q in QUESTIONS.items():
        describe.add_question(name, q["instruction"], fields=q["fields"],
                              summary=q.get("summary"))


def answer_dict(description: Any) -> dict[str, Any]:
    """A library `Description` as {"summary", **fields}."""
    return {"summary": description.summary, **(description.fields or {})}
