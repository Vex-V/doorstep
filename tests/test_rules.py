import pytest

from doorstep.alerts import rules as model
from doorstep.alerts.compiler import EXAMPLES

CAMERAS = ["front", "kitchen"]


def test_examples_are_valid_rules():
    """The compiler's own examples must pass the checks it holds the model to."""
    for _, rule in EXAMPLES:
        model.check(rule, CAMERAS)


def test_cannot_tell_is_always_an_answer():
    c = model.check(EXAMPLES[0][1], CAMERAS)
    assert c["fields"][0]["one_of"] == ["yes", "no", "cannot tell"]
    assert model.library_fields(c)["parcel_on_step"]["one_of"][-1] == "cannot tell"


@pytest.mark.parametrize("change, problem", [
    ({"kind": "sometimes"}, "kind must be"),
    ({"cameras": ["garage"]}, "no camera 'garage'"),
    ({"when": [{"field": "nope", "op": "is", "value": "yes"}]}, "unknown field"),
    ({"when": [{"field": "parcel_on_step", "op": "is", "value": "maybe"}]}, "is never 'maybe'"),
    ({"when": [{"field": "parcel_on_step", "op": "is", "value": "cannot tell"}]}, "never fires"),
    ({"when": []}, "no condition"),
    ({"window": {"from": "8am", "to": "20:00"}}, "HH:MM"),
    ({"for_minutes": 30, "check_every_minutes": 45}, "check_every_minutes"),
])
def test_refused(change, problem):
    rule = {**EXAMPLES[0][1], **change}
    with pytest.raises(model.RuleError, match=problem):
        model.check(rule, CAMERAS)


def test_absent_needs_deadline():
    rule = {**EXAMPLES[2][1], "deadline": None}
    with pytest.raises(model.RuleError, match="deadline"):
        model.check(rule, CAMERAS)


def test_window_wraps_midnight():
    c = {"window": {"from": "22:00", "to": "05:00"}}
    assert model.in_window(c, 23 * 60)
    assert model.in_window(c, 3 * 60)
    assert not model.in_window(c, 12 * 60)
    assert model.in_window({"window": None}, 12 * 60)


def test_verdicts():
    c = model.check(EXAMPLES[0][1], CAMERAS)
    assert model.verdict(c, {"parcel_on_step": "yes"}) is True
    assert model.verdict(c, {"parcel_on_step": "No"}) is False
    assert model.verdict(c, {"parcel_on_step": "cannot tell"}) is None
    assert model.verdict(c, {}) is None
    assert model.verdict_over(c, [{"parcel_on_step": "no"}, {"parcel_on_step": "yes"}]) is True
    assert model.verdict_over(c, [{"parcel_on_step": "cannot tell"},
                                  {"parcel_on_step": "no"}]) is False
    assert model.verdict_over(c, [{"parcel_on_step": "cannot tell"}]) is None


def test_mentions_and_lists():
    c = model.check({"kind": "on_event", "title": "Hi-vis", "cameras": [],
                     "instruction": "Look.",
                     "fields": [{"name": "wearing", "about": "what they wear", "one_of": None}],
                     "when": [{"field": "wearing", "op": "mentions", "value": "hi-vis"}]},
                    CAMERAS)
    assert model.verdict(c, {"wearing": "a yellow Hi-Vis vest"}) is True
    assert model.verdict(c, {"wearing": ["dark coat", "hi-vis jacket"]}) is True
    assert model.verdict(c, {"wearing": "a dark coat"}) is False


def test_sentences_say_what_runs():
    names = {"front": "Front door", "kitchen": "Kitchen"}
    persists = model.sentence(model.check(EXAMPLES[0][1], CAMERAS), names)
    assert "every 15 minutes" in persists and "120 minutes" in persists
    assert "the Front door camera" in persists
    night = model.sentence(model.check(EXAMPLES[1][1], CAMERAS), names)
    assert "between 00:00 and 05:00" in night
    absent = model.sentence(model.check(EXAMPLES[2][1], CAMERAS), names)
    assert "no movement at all between 05:00 and 11:00" in absent


def test_the_compiler_is_told_who_is_expected():
    from doorstep.alerts.compiler import _prompt

    carer = {"label": "the carer", "description": "dark hair in a bun, white T-shirt",
             "from_hhmm": "11:00", "to_hhmm": "12:00"}
    prompt = _prompt("Tell me if anyone rings who isn't the carer", [], [carer])
    assert prompt.endswith("- the carer: dark hair in a bun, white T-shirt (due "
                           "11:00-12:00)\nAlert: Tell me if anyone rings who isn't "
                           "the carer\nRule:")
    assert "- (none)\nAlert: x" in _prompt("x", [], [])


def test_a_doorbell_rule_ignores_motion():
    caller = next(r for t, r in EXAMPLES if "rings" in t)
    c = model.check(caller, CAMERAS)
    assert c["on"] == "doorbell"
    assert model.triggered_by(c, "ding") and not model.triggered_by(c, "motion")
    assert "presses the doorbell" in model.sentence(c, {"front": "Front door"})
    night = model.check(EXAMPLES[1][1], CAMERAS)
    assert model.triggered_by(night, "motion")
    # Rules stored before "on" existed watch everything, as they did.
    old = {k: v for k, v in caller.items() if k != "on"}
    assert model.check(old, CAMERAS)["on"] == "any"
