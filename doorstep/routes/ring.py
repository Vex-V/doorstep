"""Ring's webhook, and stepping through the Ring simulator's day.

    POST /ring/webhook        signed by Ring (or the simulator)
    POST /api/sim/next        the simulator, straight to the next thing that happens
    POST /api/sim/restart     the simulator's day from the top, paused, the timeline cleared
"""

from __future__ import annotations

import asyncio

from fastapi import APIRouter, HTTPException, Request

from .. import privacy
from ..core import clock as clocks
from ..core.bus import bus
from ..core.config import settings
from ..ring import steps, webhooks
from ..state import state, sync_sim
from ..worker import DIGEST_AT

#: How long a step waits for the simulator's webhook to reach Doorstep.
WEBHOOK_WAIT_S = 10

router = APIRouter()


@router.post("/ring/webhook")
async def ring_webhook(request: Request):
    body = await request.body()
    try:
        hook = webhooks.verify_and_parse(settings().ring_webhook_secret, body,
                                         request.headers.get(webhooks.HEADER))
    except webhooks.InvalidSignature:
        raise HTTPException(401, "bad signature")
    except (ValueError, KeyError):
        raise HTTPException(400, "not a Ring webhook")
    if hook.request_id and not state.store.first_delivery(hook.request_id,
                                                          clocks.now_ms()):
        return {"ok": True, "duplicate": True}
    event_id = await state.worker.handle(hook)       # a row and a queue entry: fast
    return {"ok": True, "event_id": event_id}


# -- stepping through the simulator's day ---------------------------------------

def _need_sim() -> None:
    if state.sim is None:
        raise HTTPException(400, "stepping needs the Ring simulator (RING_SIM=1)")


def _rules() -> list:
    return [r | {"state": state.store.state(r["id"])} for r in state.store.rules()]


def _visits_still_due() -> list:
    """A visit that has already arrived today has nothing left to stop for."""
    day = clocks.day_of(state.sim["clock"]["now_ms"], settings().tz)
    return [v for v in state.store.visits() if not state.store.visit_day(v["id"], day)]


async def _sim(path: str, body: dict) -> None:
    import httpx

    async with httpx.AsyncClient(timeout=5) as http:
        (await http.post(f"{settings().ring_api_base}{path}", json=body)).raise_for_status()


@router.post("/api/sim/next")
async def sim_next():
    """Jump the simulator, paused, to just after the next stop; for an event,
    return once its webhook has arrived, so "busy" means what it says."""
    _need_sim()
    await sync_sim()
    s = settings()
    stop = steps.next_stop(state.sim, _rules(), _visits_still_due(),
                           DIGEST_AT, s.tz)
    if stop is None:
        return {"done": True}
    at = clocks.to_dt(stop["ms"], s.tz).strftime("%H:%M:%S")
    await _sim("/sim/clock", {"at": at, "running": False})
    await sync_sim()
    if stop["event_start"] is not None:
        lo, hi = stop["event_start"] - 1, stop["event_start"] + 1
        for _ in range(WEBHOOK_WAIT_S * 4):
            if state.store.events(lo, hi):
                break
            await asyncio.sleep(0.25)
    left = steps.stops(state.sim, _rules(), _visits_still_due(), DIGEST_AT, s.tz)
    return {"done": False, "at": at[:5], "what": stop["what"],
            "left": sum(x["ms"] > stop["ms"] for x in left)}


@router.post("/api/sim/restart")
async def sim_restart():
    """The day again from the top, paused, on a cleared timeline: the simulator
    re-sends every event, and each would otherwise be there twice."""
    _need_sim()
    privacy.clear_timeline(state.store)
    state.worker.forget()
    bus.publish("family", {"type": "deleted", "everything": False})
    await _sim("/sim/start", {"mode": "schedule"})
    await _sim("/sim/clock", {"running": False})
    await sync_sim()
    return {"ok": True}
