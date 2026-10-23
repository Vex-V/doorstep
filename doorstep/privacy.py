"""Deleting footage and everything derived from it, which Ring's policy
requires and the family can do from the page: one clip, the whole timeline,
or everything (the alerts and visits they set up too). Retention runs the
same deletion on anything older than `DOORSTEP_RETENTION_DAYS`."""

from __future__ import annotations

import logging
import shutil
from pathlib import Path
from typing import Optional

from .core.config import settings

log = logging.getLogger("doorstep.privacy")


def _inside_data(path: Path) -> bool:
    try:
        return path.resolve().is_relative_to(settings().data.resolve())
    except OSError:
        return False


def _remove(path: Optional[str | Path]) -> None:
    if not path:
        return
    p = Path(path)
    if not _inside_data(p):
        log.warning("not deleting %s: outside the data folder", p)
        return
    if p.is_dir():
        shutil.rmtree(p, ignore_errors=True)
    elif p.exists():
        p.unlink()


def delete_event(store, event_id: str) -> bool:
    e = store.event(event_id)
    if e is None:
        return False
    _remove(e.get("clip"))
    _remove(e.get("snapshot"))
    if e.get("video_id"):
        _remove(settings().out / e["video_id"])
    store.delete_event(event_id)
    return True


def delete_range(store, lo: int, hi: int) -> int:
    n = 0
    for e in store.events(lo, hi):
        n += delete_event(store, e["id"])
    for snap in store.snapshots(lo, hi):
        _remove(snap["path"])
        store.delete_snapshot(snap["id"])
    return n


def _remove_footage() -> None:
    s = settings()
    for folder in (s.clips, s.snapshots, s.out):
        _remove(folder)


def clear_timeline(store) -> None:
    """Every clip, alert, visit seen and digest; what each rule was watching."""
    _remove_footage()
    store.clear()


def delete_everything(store) -> None:
    from .alerts import compiler, visits

    for r in store.rules():
        compiler.deactivate(r["id"])
    for v in store.visits():
        visits.unregister(v["id"])
    _remove_footage()
    store.wipe()


def enforce_retention(store, now_ms: int) -> int:
    cutoff = now_ms - settings().retention_days * 86_400_000
    n = delete_range(store, 0, cutoff)
    if n:
        log.info("retention: deleted %d clips older than %d days", n,
                 settings().retention_days)
    return n
