"""SQLite: cameras, events, rules and their state, alerts, snapshots, the digest.

The library keeps its own files per clip (`data/vidra/out/<video_id>/`); this
database holds what only the application knows -- above all, each clip's
wall-clock time, which is what every rule and the digest are about.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path
from typing import Any, Iterable, Optional

SCHEMA = """
create table if not exists cameras (
    id text primary key,
    name text not null,
    kind text not null default 'camera',      -- doorbell | camera
    component text
);
create table if not exists events (
    id text primary key,
    camera text not null,
    kind text not null,                       -- motion | ding
    subtype text,
    start_ms integer not null,
    end_ms integer,
    state text not null default 'new',        -- new | processing | done | failed
    video_id text,
    clip text,
    snapshot text,
    summary text,
    answers text,                             -- json: {question: [answer per chunk]}
    error text
);
create index if not exists events_time on events (start_ms);
create table if not exists rules (
    id integer primary key autoincrement,
    text text not null,
    compiled text not null,
    enabled integer not null default 1,
    created_ms integer not null
);
create table if not exists rule_state (
    rule_id integer primary key,
    state text not null default 'idle',       -- idle | watching | fired | satisfied
    since_ms integer,
    last_check_ms integer,
    event_id text,
    day text,
    detail text
);
create table if not exists alerts (
    id integer primary key autoincrement,
    rule_id integer,
    at_ms integer not null,
    title text not null,
    message text not null,
    event_id text,
    snapshot text,
    seen integer not null default 0
);
create table if not exists snapshots (
    id integer primary key autoincrement,
    camera text not null,
    at_ms integer not null,
    path text not null,
    question text,
    answer text
);
create table if not exists webhooks (
    request_id text primary key,
    received_ms integer not null
);
create table if not exists digest (
    id integer primary key check (id = 1),    -- one: the latest
    made_ms integer not null,
    body text not null
);
create table if not exists visits (
    id integer primary key autoincrement,
    label text not null,                      -- "the carer"
    description text not null,                -- "a woman with dark hair, blue tunic"
    cameras text not null,                    -- json: [] is every camera
    from_hhmm text not null,
    to_hhmm text not null,
    enabled integer not null default 1,
    created_ms integer not null
);
create table if not exists visit_days (     -- a visit is expected every day
    visit_id integer not null,
    day text not null,
    state text not null,                      -- arrived | left | missed
    arrived_ms integer,
    arrived_event text,
    left_ms integer,
    left_event text,
    primary key (visit_id, day)
);
"""

_JSON = {"answers", "compiled", "answer", "body", "detail", "cameras"}


class Store:
    def __init__(self, path: str | Path) -> None:
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._db = sqlite3.connect(self.path, check_same_thread=False)
        self._db.row_factory = sqlite3.Row
        self._db.executescript(SCHEMA)
        self._db.commit()

    # -- plumbing -------------------------------------------------------------

    def _rows(self, sql: str, args: Iterable[Any] = ()) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._db.execute(sql, tuple(args)).fetchall()
        return [self._decode(dict(r)) for r in rows]

    def _one(self, sql: str, args: Iterable[Any] = ()) -> Optional[dict[str, Any]]:
        rows = self._rows(sql, args)
        return rows[0] if rows else None

    def _run(self, sql: str, args: Iterable[Any] = ()) -> int:
        with self._lock:
            cur = self._db.execute(sql, tuple(args))
            self._db.commit()
            return cur.lastrowid or cur.rowcount

    @staticmethod
    def _decode(row: dict[str, Any]) -> dict[str, Any]:
        for key in _JSON & row.keys():
            if isinstance(row[key], str):
                row[key] = json.loads(row[key])
        return row

    @staticmethod
    def _encode(value: Any) -> Any:
        return json.dumps(value) if isinstance(value, (dict, list)) else value

    def close(self) -> None:
        with self._lock:
            self._db.close()

    # -- cameras --------------------------------------------------------------

    def put_camera(self, id: str, name: str, kind: str = "camera",
                   component: Optional[str] = None) -> None:
        self._run("insert into cameras (id, name, kind, component) values (?,?,?,?) "
                  "on conflict(id) do update set name=excluded.name, kind=excluded.kind, "
                  "component=excluded.component", (id, name, kind, component))

    def cameras(self) -> list[dict[str, Any]]:
        return self._rows("select * from cameras order by name")

    def camera(self, id: str) -> Optional[dict[str, Any]]:
        return self._one("select * from cameras where id = ?", (id,))

    # -- webhooks -------------------------------------------------------------

    def first_delivery(self, request_id: str, now_ms: int) -> bool:
        """True the first time a request id is seen; Ring retries deliveries."""
        with self._lock:
            try:
                self._db.execute("insert into webhooks values (?, ?)", (request_id, now_ms))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    # -- events ---------------------------------------------------------------

    def put_event(self, id: str, camera: str, kind: str, start_ms: int,
                  subtype: Optional[str] = None) -> bool:
        """Insert an event; False when it already exists."""
        with self._lock:
            try:
                self._db.execute(
                    "insert into events (id, camera, kind, subtype, start_ms) "
                    "values (?,?,?,?,?)", (id, camera, kind, subtype, start_ms))
                self._db.commit()
                return True
            except sqlite3.IntegrityError:
                return False

    def update_event(self, id: str, **values: Any) -> None:
        if not values:
            return
        cols = ", ".join(f"{k} = ?" for k in values)
        self._run(f"update events set {cols} where id = ?",
                  [self._encode(v) for v in values.values()] + [id])

    def event(self, id: str) -> Optional[dict[str, Any]]:
        return self._one("select * from events where id = ?", (id,))

    def events(self, start_ms: int = 0, end_ms: int = 1 << 62,
               camera: Optional[str] = None, kind: Optional[str] = None,
               state: Optional[str] = None) -> list[dict[str, Any]]:
        sql = "select * from events where start_ms >= ? and start_ms < ?"
        args: list[Any] = [start_ms, end_ms]
        for col, value in (("camera", camera), ("kind", kind), ("state", state)):
            if value is not None:
                sql += f" and {col} = ?"
                args.append(value)
        return self._rows(sql + " order by start_ms", args)

    def delete_event(self, id: str) -> None:
        self._run("delete from events where id = ?", (id,))
        self._run("delete from alerts where event_id = ?", (id,))

    # -- rules ----------------------------------------------------------------

    def add_rule(self, text: str, compiled: dict[str, Any], now_ms: int) -> int:
        return self._run("insert into rules (text, compiled, enabled, created_ms) "
                         "values (?,?,1,?)", (text, json.dumps(compiled), now_ms))

    def set_rule(self, id: int, **values: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in values)
        self._run(f"update rules set {cols} where id = ?",
                  [self._encode(v) for v in values.values()] + [id])

    def rules(self, enabled: Optional[bool] = None) -> list[dict[str, Any]]:
        if enabled is None:
            return self._rows("select * from rules order by id")
        return self._rows("select * from rules where enabled = ? order by id",
                          (1 if enabled else 0,))

    def rule(self, id: int) -> Optional[dict[str, Any]]:
        return self._one("select * from rules where id = ?", (id,))

    def delete_rule(self, id: int) -> None:
        self._run("delete from rules where id = ?", (id,))
        self._run("delete from rule_state where rule_id = ?", (id,))

    def state(self, rule_id: int) -> dict[str, Any]:
        return self._one("select * from rule_state where rule_id = ?", (rule_id,)) or {
            "rule_id": rule_id, "state": "idle", "since_ms": None,
            "last_check_ms": None, "event_id": None, "day": None, "detail": None}

    def set_state(self, rule_id: int, **values: Any) -> None:
        current = self.state(rule_id)
        current.update(values)
        self._run("insert into rule_state (rule_id, state, since_ms, last_check_ms, "
                  "event_id, day, detail) values (?,?,?,?,?,?,?) on conflict(rule_id) "
                  "do update set state=excluded.state, since_ms=excluded.since_ms, "
                  "last_check_ms=excluded.last_check_ms, event_id=excluded.event_id, "
                  "day=excluded.day, detail=excluded.detail",
                  (rule_id, current["state"], current["since_ms"],
                   current["last_check_ms"], current["event_id"], current["day"],
                   self._encode(current["detail"])))

    # -- alerts ---------------------------------------------------------------

    def add_alert(self, rule_id: Optional[int], at_ms: int, title: str, message: str,
                  event_id: Optional[str] = None, snapshot: Optional[str] = None) -> int:
        return self._run("insert into alerts (rule_id, at_ms, title, message, event_id, "
                         "snapshot) values (?,?,?,?,?,?)",
                         (rule_id, at_ms, title, message, event_id, snapshot))

    def alerts(self, start_ms: int = 0, end_ms: int = 1 << 62) -> list[dict[str, Any]]:
        return self._rows("select * from alerts where at_ms >= ? and at_ms < ? "
                          "order by at_ms", (start_ms, end_ms))

    def alerted(self, rule_id: int, event_id: str) -> bool:
        return self._one("select 1 as x from alerts where rule_id = ? and event_id = ?",
                         (rule_id, event_id)) is not None

    # -- snapshots ------------------------------------------------------------

    def add_snapshot(self, camera: str, at_ms: int, path: str,
                     question: Optional[str] = None, answer: Any = None) -> int:
        return self._run("insert into snapshots (camera, at_ms, path, question, answer) "
                         "values (?,?,?,?,?)",
                         (camera, at_ms, path, question, self._encode(answer)))

    def snapshot(self, id: int) -> Optional[dict[str, Any]]:
        return self._one("select * from snapshots where id = ?", (id,))

    def snapshots(self, start_ms: int = 0, end_ms: int = 1 << 62) -> list[dict[str, Any]]:
        return self._rows("select * from snapshots where at_ms >= ? and at_ms < ? "
                          "order by at_ms", (start_ms, end_ms))

    def delete_snapshot(self, id: int) -> None:
        self._run("delete from snapshots where id = ?", (id,))

    # -- digests --------------------------------------------------------------

    def put_digest(self, body: dict[str, Any], now_ms: int) -> None:
        self._run("insert into digest (id, made_ms, body) values (1,?,?) on "
                  "conflict(id) do update set made_ms=excluded.made_ms, "
                  "body=excluded.body", (now_ms, json.dumps(body)))

    def digest(self) -> Optional[dict[str, Any]]:
        return self._one("select * from digest where id = 1")

    # -- expected visits ------------------------------------------------------

    def add_visit(self, label: str, description: str, cameras: list[str],
                  from_hhmm: str, to_hhmm: str, now_ms: int) -> int:
        return self._run("insert into visits (label, description, cameras, from_hhmm, "
                         "to_hhmm, enabled, created_ms) values (?,?,?,?,?,1,?)",
                         (label, description, json.dumps(cameras), from_hhmm, to_hhmm,
                          now_ms))

    def visits(self, enabled: Optional[bool] = None) -> list[dict[str, Any]]:
        if enabled is None:
            return self._rows("select * from visits order by from_hhmm, id")
        return self._rows("select * from visits where enabled = ? order by from_hhmm, id",
                          (1 if enabled else 0,))

    def visit(self, id: int) -> Optional[dict[str, Any]]:
        return self._one("select * from visits where id = ?", (id,))

    def set_visit(self, id: int, **values: Any) -> None:
        cols = ", ".join(f"{k} = ?" for k in values)
        self._run(f"update visits set {cols} where id = ?",
                  [self._encode(v) for v in values.values()] + [id])

    def delete_visit(self, id: int) -> None:
        self._run("delete from visits where id = ?", (id,))
        self._run("delete from visit_days where visit_id = ?", (id,))

    def visit_day(self, visit_id: int, day: str) -> Optional[dict[str, Any]]:
        return self._one("select * from visit_days where visit_id = ? and day = ?",
                         (visit_id, day))

    def put_visit_day(self, visit_id: int, day: str, **values: Any) -> None:
        row = self.visit_day(visit_id, day) or {
            "state": "missed", "arrived_ms": None, "arrived_event": None,
            "left_ms": None, "left_event": None}
        row.update(values)
        self._run("insert into visit_days (visit_id, day, state, arrived_ms, "
                  "arrived_event, left_ms, left_event) values (?,?,?,?,?,?,?) "
                  "on conflict(visit_id, day) do update set state=excluded.state, "
                  "arrived_ms=excluded.arrived_ms, arrived_event=excluded.arrived_event, "
                  "left_ms=excluded.left_ms, left_event=excluded.left_event",
                  (visit_id, day, row["state"], row["arrived_ms"], row["arrived_event"],
                   row["left_ms"], row["left_event"]))

    def visit_days(self, visit_id: int) -> list[dict[str, Any]]:
        return self._rows("select * from visit_days where visit_id = ? order by day",
                          (visit_id,))

    # -- clearing -------------------------------------------------------------

    TIMELINE = ("events", "alerts", "snapshots", "webhooks", "digest", "visit_days",
                "rule_state")

    def clear(self, tables: Iterable[str] = TIMELINE) -> None:
        """The timeline and everything worked out from it; the family's alerts,
        visits and the cameras stay."""
        with self._lock:
            for table in tables:
                self._db.execute(f"delete from {table}")
            self._db.commit()

    def wipe(self) -> None:
        self.clear(self.TIMELINE + ("rules", "visits"))
