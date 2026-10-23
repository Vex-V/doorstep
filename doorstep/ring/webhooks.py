"""Ring webhooks (payload v1.1): verify the signature over the raw body, then
parse. Ring signs with HMAC-SHA256, hex, sent as `X-Signature: sha256=<hex>`;
it retries a delivery up to six times, so `request_id` is deduplicated by the
caller."""

from __future__ import annotations

import hashlib
import hmac
import json
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Optional

HEADER = "X-Signature"


class InvalidSignature(Exception):
    pass


def sign(secret: str | bytes, body: bytes) -> str:
    key = secret.encode() if isinstance(secret, str) else secret
    return "sha256=" + hmac.new(key, body, hashlib.sha256).hexdigest()


def verify(secret: str | bytes, body: bytes, header: Optional[str]) -> bool:
    if not header:
        return False
    received = header.strip().lower()
    if not received.startswith("sha256="):
        received = "sha256=" + received
    return hmac.compare_digest(sign(secret, body).encode(), received.encode())


@dataclass
class Webhook:
    request_id: str
    type: str                     # motion_detected | button_press | device_online | ...
    device_id: Optional[str]
    timestamp_ms: Optional[int]
    subtype: Optional[str] = None
    raw: dict[str, Any] = field(default_factory=dict, repr=False)

    @property
    def event_id(self) -> str:
        """Stable across retries: Ring's own data id, else device + time."""
        return (self.raw.get("data") or {}).get("id") or \
            f"{self.device_id}_{self.type}_{self.timestamp_ms}"


def parse(body: bytes | str | dict[str, Any]) -> Webhook:
    doc = body if isinstance(body, dict) else json.loads(body)
    meta = doc.get("meta") or {}
    data = doc.get("data") or {}
    attrs = data.get("attributes") or {}
    device = attrs.get("source") if attrs.get("source_type") == "devices" else None
    ts = attrs.get("timestamp")
    return Webhook(
        request_id=meta.get("request_id") or data.get("id") or "",
        type=data.get("type", "unknown"),
        device_id=device,
        timestamp_ms=int(ts) if ts is not None else None,
        subtype=attrs.get("sub_type"),
        raw=doc)


def verify_and_parse(secret: str | bytes, body: bytes, header: Optional[str]) -> Webhook:
    if not verify(secret, body, header):
        raise InvalidSignature("X-Signature does not match the request body")
    return parse(body)


def build(type: str, device_id: str, timestamp_ms: int, subtype: Optional[str] = None,
          account_id: str = "replay") -> bytes:
    """The body Ring would send (the tests)."""
    suffix = {"motion_detected": "motion", "button_press": "ding"}.get(type, type)
    attributes: dict[str, Any] = {"source": device_id, "source_type": "devices",
                                  "timestamp": int(timestamp_ms)}
    if subtype:
        attributes["sub_type"] = subtype
    doc = {"meta": {"version": "1.1",
                    "time": datetime.now(timezone.utc).isoformat(),
                    "request_id": str(uuid.uuid4()),
                    "account_id": account_id},
           "data": {"id": f"{device_id}_{suffix}_{int(timestamp_ms)}",
                    "type": type, "attributes": attributes}}
    return json.dumps(doc, separators=(",", ":")).encode()
