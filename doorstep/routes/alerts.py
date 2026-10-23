"""Rules written in plain English, and expected visits.

    POST   /api/rules             a sentence -> a rule, on at once (or a compiled rule)
    PATCH  /api/rules/{id}        on or off
    DELETE /api/rules/{id}
    POST   /api/visits            the carer: who, what they look like, when
    PATCH  /api/visits/{id} · DELETE /api/visits/{id}
"""

from __future__ import annotations

from typing import Any, Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from ..alerts import compiler, rules, visits
from ..core import clock as clocks
from ..state import state

router = APIRouter()


class RuleAdd(BaseModel):
    text: str
    compiled: Optional[dict[str, Any]] = None       # None: compile `text` now


class Enabled(BaseModel):
    enabled: bool


class VisitAdd(BaseModel):
    label: str
    description: str
    from_hhmm: str
    to_hhmm: str
    cameras: list[str] = []


def names() -> dict[str, str]:
    return {c["id"]: c["name"] for c in state.store.cameras()}


def rule_view(r: dict[str, Any], cameras: dict[str, str]) -> dict[str, Any]:
    return {"id": r["id"], "text": r["text"], "enabled": bool(r["enabled"]),
            "title": r["compiled"]["title"], "kind": r["compiled"]["kind"],
            "sentence": rules.sentence(r["compiled"], cameras),
            "state": state.store.state(r["id"])}


# -- rules ----------------------------------------------------------------------

async def _compile(text: str) -> dict[str, Any]:
    try:
        return await compiler.compile_rule(text, state.store.cameras(),
                                           state.store.visits(enabled=True))
    except rules.RuleError as exc:
        raise HTTPException(422, str(exc))


@router.post("/api/rules")
async def rule_add(body: RuleAdd):
    """On at once: the card shows the sentence it runs as, and the family can
    switch it off or remove it there."""
    try:
        compiled = (rules.check(body.compiled, list(names())) if body.compiled
                    else await _compile(body.text))
    except rules.RuleError as exc:
        raise HTTPException(422, str(exc))
    rule_id = state.store.add_rule(body.text, compiled, clocks.now_ms())
    compiler.activate(rule_id, compiled)
    return rule_view(state.store.rule(rule_id), names())


@router.patch("/api/rules/{rule_id}")
async def rule_patch(rule_id: int, body: Enabled):
    if state.store.rule(rule_id) is None:
        raise HTTPException(404, "no such rule")
    state.store.set_rule(rule_id, enabled=1 if body.enabled else 0)
    return rule_view(state.store.rule(rule_id), names())


@router.delete("/api/rules/{rule_id}")
async def rule_delete(rule_id: int):
    state.store.delete_rule(rule_id)
    compiler.deactivate(rule_id)
    return {"ok": True}


# -- expected visits ------------------------------------------------------------

@router.post("/api/visits")
async def visit_add(body: VisitAdd):
    try:
        v = visits.check(body.label, body.description, body.cameras, body.from_hhmm,
                         body.to_hhmm, list(names()))
    except visits.VisitError as exc:
        raise HTTPException(422, str(exc))
    visit_id = state.store.add_visit(v["label"], v["description"], v["cameras"],
                                     v["from_hhmm"], v["to_hhmm"], clocks.now_ms())
    visits.register(state.store.visit(visit_id))
    return visits.sentence(state.store.visit(visit_id), names())


@router.patch("/api/visits/{visit_id}")
async def visit_patch(visit_id: int, body: Enabled):
    if state.store.visit(visit_id) is None:
        raise HTTPException(404, "no such visit")
    state.store.set_visit(visit_id, enabled=1 if body.enabled else 0)
    return {"ok": True}


@router.delete("/api/visits/{visit_id}")
async def visit_delete(visit_id: int):
    state.store.delete_visit(visit_id)
    visits.unregister(visit_id)
    return {"ok": True}
