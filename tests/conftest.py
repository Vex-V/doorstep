"""Shared fixtures: settings pointing at a temporary folder, a tiny generated
scenario (no real footage needed), and a fake VLM whose answers a test sets."""

from __future__ import annotations

import json
from dataclasses import replace
from pathlib import Path
from typing import Any

import numpy as np
import pytest

from doorstep.core import clock, config
from doorstep.core import models as doorstep_models


def make_clip(path: Path, seconds: float = 4.0, colour=(40, 120, 200), fps: int = 10,
              size=(320, 240)) -> Path:
    import cv2

    path.parent.mkdir(parents=True, exist_ok=True)
    w = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    for i in range(int(seconds * fps)):
        frame = np.full((size[1], size[0], 3), colour, np.uint8)
        cv2.putText(frame, str(i), (20, 120), cv2.FONT_HERSHEY_SIMPLEX, 2, (255, 255, 255), 3)
        w.write(frame)
    w.release()
    return path


@pytest.fixture
def scenario(tmp_path) -> Path:
    folder = tmp_path / "scenario"
    make_clip(folder / "clips" / "courier.mp4", colour=(20, 60, 200))
    make_clip(folder / "clips" / "taken.mp4", colour=(200, 60, 20))
    doc = {"title": "Test day", "start": "2026-10-20T07:00:00",
           "cameras": [{"id": "front", "name": "Front door", "kind": "doorbell"},
                       {"id": "kitchen", "name": "Kitchen", "kind": "camera"},
                       {"id": "chime", "name": "Hallway Chime", "kind": "chime"}],
           "events": [{"at": "08:00:00", "camera": "front", "type": "button_press",
                       "clip": "clips/courier.mp4"},
                      {"at": "11:00:00", "camera": "front", "type": "motion_detected",
                       "sub_type": "human", "clip": "clips/taken.mp4"}]}
    path = folder / "scenario.json"
    path.write_text(json.dumps(doc))
    return path


@pytest.fixture
def settings(tmp_path, scenario):
    s = replace(config.from_env(), data=tmp_path / "data", ring_api_base="http://sim",
                ring_token="tok", ring_token_file=None, ring_sim=False, ring_poll_s=0,
                models="stub", embedder="hash", audio=False,
                ring_webhook_secret="test-secret", chime_device="chime")
    config.use(s)
    doorstep_models.reset()
    import vidra
    vidra.configure(data_root=s.data / "vidra")
    yield s
    config.use(None)
    clock.use(None)
    doorstep_models.reset()


def fake_vlm(script: dict[str, dict[str, Any]]):
    """A VLM answering each question with what `script[question]` holds; a
    test edits `script` between calls. Unscripted fields are "cannot tell"."""
    from vidra import VLM

    class _Fake(VLM):
        key = "fake:vlm"
        concurrency = 4

        async def generate(self, parts, schema=None, system=None, max_output_tokens=4000):
            name = (schema or {}).get("name", "")
            props = ((schema or {}).get("schema") or {}).get("properties") or {}
            # The library names a describe schema `description_<question>`.
            chosen = script.get(name.removeprefix("description_"), {})
            out = {}
            for key, spec in props.items():
                if key in chosen:
                    out[key] = chosen[key]
                elif key == "summary":
                    out[key] = chosen.get("summary", "A person at the door.")
                else:
                    out[key] = [] if spec.get("type") == "array" else "cannot tell"
            return out

    return _Fake()


@pytest.fixture
def script(settings, monkeypatch):
    """Use the fake VLM for describing; returns its script to edit."""
    from vidra import HashEmbedder, Models, Stub

    answers: dict[str, dict[str, Any]] = {}
    built = Models(vlm=fake_vlm(answers), llm=Stub(), embedder=HashEmbedder())
    monkeypatch.setattr(doorstep_models, "models", lambda: built)
    # Every module that imported `models` by name.
    from doorstep.alerts import engine
    from doorstep.footage import clips
    for module in (clips, engine):
        monkeypatch.setattr(module, "models", lambda: built)
    return answers


@pytest.fixture
def ring_sim(settings, scenario, monkeypatch):
    """The Ring simulator in-process, with its whole day recorded (the clock at
    23:59, paused): Doorstep's own Ring client reaches it, through the Partner
    API, when the server starts."""
    import httpx

    import doorstep.app
    from doorstep.ring.client import RingClient
    from ringsim.scenario import load
    from ringsim.server import Sim, create_app

    sim = Sim(load(scenario, str(settings.tz)), token="tok", secret="test-secret",
              webhook_url=None)
    sim.clock.set(at_ms=sim.scenario.day_ms("23:59"), running=False)
    app = create_app(sim)

    def ring_client(token, base):
        ring = RingClient(token, base)
        ring._http = httpx.AsyncClient(transport=httpx.ASGITransport(app), base_url=base)
        ring._media = httpx.AsyncClient(transport=httpx.ASGITransport(app))
        return ring

    monkeypatch.setattr(doorstep.app, "RingClient", ring_client)
    return sim
