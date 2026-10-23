"""The server: built here, its routes in `routes/` (one router per audience).

Start-up registers every question with vidra (the built-in ones, each rule's,
each expected visit's), connects to Ring -- the Partner API, Ring's, or the
Ring simulator's -- lists the cameras, and starts the background worker.
"""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles

from .alerts import compiler, visits
from .core import clock as clocks
from .core.config import settings
from .core.store import Store
from .footage import questions
from .ring.client import RingClient
from .ring.poller import HistoryPoller
from .routes import alerts, family, ring
from .state import follow_sim, state, sync_sim
from .worker import Worker

log = logging.getLogger("doorstep")
STATIC = Path(__file__).parent / "static"


def _warm_up() -> None:
    """Load the local embedder now, not inside the first clip: its weights take
    tens of seconds to load (minutes to download, the first time)."""
    from .core.models import models

    try:
        models().embedder.embed_query("warm up")
    except Exception as exc:
        log.warning("embedder warm-up failed: %s", exc)


@asynccontextmanager
async def lifespan(app: FastAPI):
    import vidra

    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(name)s %(message)s")
    s = settings()
    s.data.mkdir(parents=True, exist_ok=True)
    vidra.configure(data_root=s.data / "vidra")
    state.store = Store(s.db_path)
    questions.register()
    for r in state.store.rules():
        compiler.activate(r["id"], r["compiled"])
    for v in state.store.visits():
        visits.register(v)
    token = s.ring_token
    if s.ring_token_file:
        path = s.ring_token_file
        token = lambda: path.read_text(encoding="utf-8").strip()  # noqa: E731
    state.ring = RingClient(token, s.ring_api_base)
    if s.ring_sim:
        clocks.use(clocks.SyncedClock(clocks.now_ms()))
        # The simulator may still be loading its videos: wait for it.
        for attempt in range(120):
            try:
                await sync_sim()
                break
            except Exception:
                if attempt == 0:
                    log.info("waiting for the Ring simulator at %s", s.ring_api_base)
                await asyncio.sleep(1)
        else:
            raise RuntimeError(f"no Ring simulator at {s.ring_api_base}: start "
                               "`python -m ringsim` first")
        state.sim_task = asyncio.create_task(follow_sim())
    try:
        for d in await state.ring.devices():
            if d.kind != "chime":
                state.store.put_camera(d.id, d.name, d.kind)
    except Exception as exc:
        log.warning("could not list Ring devices: %s", exc)
    state.worker = Worker(state.store, state.ring)
    state.worker.start()
    warm = asyncio.create_task(asyncio.to_thread(_warm_up))
    if s.ring_poll_s > 0:
        state.poller = HistoryPoller(state.ring, state.store, state.worker.handle,
                                     s.ring_poll_s, s.ring_backfill)
        state.poll_task = asyncio.create_task(state.poller.run())
    yield
    for task in (state.poll_task, state.sim_task, warm):
        if task:
            task.cancel()
    await state.worker.stop()
    await state.ring.aclose()
    state.store.close()


app = FastAPI(title="Doorstep", lifespan=lifespan)
app.mount("/static", StaticFiles(directory=STATIC), name="static")
for module in (ring, family, alerts):
    app.include_router(module.router)


@app.exception_handler(Exception)
async def unhandled(request: Request, exc: Exception):
    log.exception("unhandled error on %s", request.url.path)
    return JSONResponse({"detail": f"{type(exc).__name__}: {exc}"}, status_code=500)


__all__ = ["app", "state"]
