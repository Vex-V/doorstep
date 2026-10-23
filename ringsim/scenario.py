"""The scripted day: cameras, a video per event, and the day's clock.

A scenario file (paths relative to it):

    {"title": "A Tuesday at Mum's",
     "start": "2026-10-20T06:30:00",
     "tz": "Europe/London",
     "cameras": [{"id": "front", "name": "Front door", "kind": "doorbell"},
                 {"id": "chime", "name": "Hallway Chime", "kind": "chime"}],
     "events": [{"at": "10:02:00", "camera": "front", "type": "button_press",
                 "clip": "clips/courier.mp4", "note": "courier, parcel left"}]}

Each event is one video at a time of day. `type` is `button_press` (a
doorbell press) or `motion_detected` (with an optional `sub_type`: human,
vehicle, animal, other_motion). Videos added from the simulator's page are
copied into `clips/` and written back here (`save`). An MP4 in H.264 plays in
the page's camera view; anything OpenCV reads is served to the app.
"""

from __future__ import annotations

import json
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Any, Optional
from zoneinfo import ZoneInfo

#: Product images, by kind: Ring's device resources carry no type field, and
#: the image's path is how an app tells a doorbell from a camera.
IMAGES = {
    "doorbell": "https://app-content.ring.com/shared/images/devices/square_device_images/DoorbellPro/rvdp_3x.png",
    "camera": "https://app-content.ring.com/shared/images/devices/square_device_images/StickUpCam/stickup_cam_3x.png",
    "chime": "https://app-content.ring.com/shared/images/devices/square_device_images/Chime/chime_3x.png",
}


@dataclass
class Event:
    index: int
    camera: str
    type: str                    # button_press | motion_detected
    start_ms: int
    clip: Path
    duration_ms: int
    subtype: Optional[str] = None
    note: str = ""
    delivered: bool = False      # its webhook has been sent (and answered)
    at: str = ""                 # as written in the scenario: HH:MM[:SS]

    @property
    def end_ms(self) -> int:
        return self.start_ms + self.duration_ms

    @property
    def history_type(self) -> str:
        """Event History's `event_type`: `ding`, or `motion.<sub_type>`."""
        if self.type == "button_press":
            return "ding"
        return f"motion.{self.subtype}" if self.subtype else "motion"

    @property
    def id(self) -> str:
        segment = (self.subtype or "motion") if self.type == "motion_detected" else self.type
        return f"{self.camera}_{segment}_{self.start_ms}"


@dataclass
class Scenario:
    title: str
    tz: ZoneInfo
    start_ms: int
    cameras: list[dict[str, Any]]
    events: list[Event]
    path: Path

    def camera(self, device_id: str) -> Optional[dict[str, Any]]:
        return next((c for c in self.cameras if c["id"] == device_id), None)

    def on(self, device_id: str) -> list[Event]:
        return [e for e in self.events if e.camera == device_id]

    def day_ms(self, hhmm: str) -> int:
        """`HH:MM[:SS]` on the scenario's day, in epoch ms."""
        return _at(hhmm, datetime.fromtimestamp(self.start_ms / 1000, self.tz), self.tz)

    def add(self, at: str, camera: str, type: str, clip: Path, note: str = "",
            subtype: Optional[str] = None) -> Event:
        """A video at a time of day; the scenario is saved with it."""
        if self.camera(camera) is None:
            raise ValueError(f"no camera {camera!r}")
        if type not in TYPES:
            raise ValueError(f"type must be one of {', '.join(TYPES)}")
        if type == "button_press" and self.camera(camera).get("kind") != "doorbell":
            raise ValueError(f"{self.camera(camera).get('name', camera)} is not a doorbell: "
                             "only motion")
        e = Event(index=0, camera=camera, type=type, start_ms=self.day_ms(at),
                  clip=clip.resolve(), duration_ms=duration_ms(clip), note=note,
                  subtype=subtype if type == "motion_detected" else None, at=_hhmmss(at))
        self.events.append(e)
        self._renumber()
        self.save()
        return e

    def add_camera(self, name: str, kind: str) -> dict[str, Any]:
        """A device, named as the family would ("Kitchen"); saved with the scenario."""
        name = " ".join(str(name).split())[:40]
        if not name:
            raise ValueError("name the camera")
        if kind not in KINDS:
            raise ValueError(f"kind must be one of {', '.join(KINDS)}")
        base = "".join(c if c.isalnum() else "-" for c in name.lower()).strip("-") or "camera"
        id, n = base, 2
        while self.camera(id) is not None:
            id, n = f"{base}-{n}", n + 1
        camera = {"id": id, "name": name, "kind": kind}
        self.cameras.append(camera)
        self.save()
        return camera

    def remove(self, index: int) -> Event:
        """An event out of the day; its video file is left where it is."""
        e = next(e for e in self.events if e.index == index)
        self.events.remove(e)
        self._renumber()
        self.save()
        return e

    def _renumber(self) -> None:
        self.events.sort(key=lambda e: e.start_ms)
        for i, e in enumerate(e for e in self.events if e.index >= 0):
            e.index = i

    def save(self) -> None:
        doc = json.loads(self.path.read_text(encoding="utf-8"))
        doc["cameras"] = self.cameras
        doc["events"] = [
            {"at": e.at, "camera": e.camera, "type": e.type,
             **({"sub_type": e.subtype} if e.subtype else {}),
             "clip": _relative(e.clip, self.path.parent), "note": e.note}
            for e in self.events if e.index >= 0]
        self.path.write_text(json.dumps(doc, indent=2) + "\n", encoding="utf-8")


TYPES = ("button_press", "motion_detected")
KINDS = ("doorbell", "camera", "chime")


def _hhmmss(value: str) -> str:
    parts = [int(p) for p in str(value).split(":")]
    while len(parts) < 3:
        parts.append(0)
    if not (0 <= parts[0] < 24 and 0 <= parts[1] < 60 and 0 <= parts[2] < 60):
        raise ValueError(f"{value!r}: a time of day is HH:MM or HH:MM:SS")
    return "{:02d}:{:02d}:{:02d}".format(*parts[:3])


def _relative(path: Path, folder: Path) -> str:
    try:
        return path.relative_to(folder.resolve()).as_posix()
    except ValueError:
        return str(path)


def duration_ms(path: Path) -> int:
    import cv2
    cap = cv2.VideoCapture(str(path))
    try:
        fps = cap.get(cv2.CAP_PROP_FPS) or 25.0
        frames = cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0
    finally:
        cap.release()
    if frames <= 0:
        raise ValueError(f"{path}: not a readable video")
    return int(frames / fps * 1000)


def _at(value: str, start: datetime, tz: ZoneInfo) -> int:
    if "T" in value:
        dt = datetime.fromisoformat(value)
        dt = dt if dt.tzinfo else dt.replace(tzinfo=tz)
    else:
        parts = [int(p) for p in value.split(":")]
        while len(parts) < 3:
            parts.append(0)
        dt = start.replace(hour=parts[0], minute=parts[1], second=parts[2], microsecond=0)
    return int(dt.timestamp() * 1000)


def load(path: str | Path, tz: Optional[str] = None) -> Scenario:
    path = Path(path).resolve()
    doc = json.loads(path.read_text(encoding="utf-8"))
    zone = ZoneInfo(tz or doc.get("tz") or "Europe/London")
    start = datetime.fromisoformat(doc["start"])
    start = start if start.tzinfo else start.replace(tzinfo=zone)
    cameras = doc.get("cameras") or []
    ids = {c["id"] for c in cameras}
    events = []
    for e in doc.get("events") or []:
        if e["camera"] not in ids:
            raise ValueError(f"scenario {path.name}: event on unknown camera {e['camera']!r}")
        if "clip" not in e:
            raise ValueError(f"scenario {path.name}: the event at {e.get('at')} needs a \"clip\"")
        clip = (path.parent / e["clip"]).resolve()
        if not clip.is_file():
            raise FileNotFoundError(f"scenario {path.name}: clip {e['clip']} not found")
        events.append(Event(index=0, camera=e["camera"],
                            type=e.get("type", "motion_detected"),
                            start_ms=_at(e["at"], start, zone), clip=clip,
                            duration_ms=duration_ms(clip), subtype=e.get("sub_type"),
                            note=e.get("note", ""), at=_hhmmss(e["at"])))
    sc = Scenario(title=doc.get("title", path.parent.name), tz=zone,
                  start_ms=int(start.timestamp() * 1000), cameras=cameras,
                  events=events, path=path)
    sc._renumber()
    return sc


class DayClock:
    """The simulated time: paused until started, then `speed` times real time.
    It can be re-anchored (jump to a time, change speed) while running."""

    def __init__(self, at_ms: int, speed: float = 60.0) -> None:
        self._anchor_ms = int(at_ms)
        self._t0 = time.monotonic()
        self.speed = float(speed)
        self.running = False

    def now_ms(self) -> int:
        if not self.running:
            return self._anchor_ms
        return self._anchor_ms + int((time.monotonic() - self._t0) * 1000 * self.speed)

    def set(self, at_ms: Optional[int] = None, speed: Optional[float] = None,
            running: Optional[bool] = None) -> None:
        now = self.now_ms() if at_ms is None else int(at_ms)
        self._anchor_ms, self._t0 = now, time.monotonic()
        if speed is not None:
            self.speed = float(speed)
        if running is not None:
            self.running = running

    def view(self) -> dict[str, Any]:
        return {"now_ms": self.now_ms(), "speed": self.speed, "running": self.running}
