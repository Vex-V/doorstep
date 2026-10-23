"""An alert: stored, pushed to the family's page, and a Chime sounded in the
house when one is configured."""

from __future__ import annotations

import logging
from typing import Any, Optional

from ..core.bus import bus
from ..core.config import settings

log = logging.getLogger("doorstep.notify")


async def alert(store, ring, rule_id: Optional[int], at_ms: int, title: str,
                message: str, event_id: Optional[str] = None,
                snapshot: Optional[str] = None) -> int:
    alert_id = store.add_alert(rule_id, at_ms, title, message, event_id, snapshot)
    bus.publish("family", {"type": "alert", "id": alert_id, "rule_id": rule_id,
                           "at_ms": at_ms, "title": title, "message": message,
                           "event_id": event_id, "snapshot": snapshot is not None})
    log.info("ALERT %s: %s", title, message)
    s = settings()
    device = s.chime_device
    if device:
        try:
            await ring.chime(device, s.chime_event)
        except Exception as exc:                 # an alert is never lost to a chime
            log.warning("chime failed: %s", exc)
    return alert_id


def event_message(event: dict[str, Any]) -> dict[str, Any]:
    """An event as the family page shows it."""
    return {"type": "event", "id": event["id"], "camera": event["camera"],
            "kind": event["kind"], "state": event["state"],
            "start_ms": event["start_ms"], "end_ms": event.get("end_ms"),
            "summary": event.get("summary")}
