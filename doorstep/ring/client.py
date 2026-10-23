"""The Ring Partner API, over httpx: the handful of calls Doorstep makes.

Base `https://api.amazonvision.com`, bearer token. Media answers with the bytes,
or a redirect to a pre-signed URL that must be fetched *without* the token.
429 is retried after `Retry-After`, with exponential backoff from 1 s.
"""

from __future__ import annotations

import asyncio
from typing import Any, Callable, Optional
from urllib.parse import urljoin

import httpx

from .api import Device, HistoryEvent, MediaNotFound, RingError

_REDIRECTS = (301, 302, 303, 307, 308)


class RingClient:
    def __init__(self, token: str | Callable[[], str], base_url: str,
                 timeout: float = 60.0, max_retries: int = 4) -> None:
        self._token = token
        self._http = httpx.AsyncClient(base_url=base_url, timeout=timeout)
        self._media = httpx.AsyncClient(timeout=timeout)   # never carries the token
        self._retries = max_retries

    async def aclose(self) -> None:
        await self._http.aclose()
        await self._media.aclose()

    def _headers(self) -> dict[str, str]:
        token = self._token() if callable(self._token) else self._token
        if not token:
            raise RingError("no Ring access token: set RING_TOKEN")
        return {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async def _send(self, method: str, path: str, *, params: Optional[dict] = None,
                    json: Any = None, media: bool = False) -> httpx.Response:
        attempt = 0
        while True:
            resp = await self._http.request(method, path, params=params, json=json,
                                            headers=self._headers(),
                                            follow_redirects=False)
            if media and resp.status_code in _REDIRECTS:
                resp = await self._media.get(urljoin(str(resp.request.url),
                                                     resp.headers["location"]))
            if resp.status_code == 429 and attempt < self._retries:
                wait = float(resp.headers.get("retry-after") or 2 ** attempt)
                await asyncio.sleep(wait)
                attempt += 1
                continue
            if resp.status_code == 401:
                raise RingError(f"{method} {path}: Ring refused the token (401): it is "
                                "wrong or has expired. Playground tokens last 30 minutes; "
                                "put a new one in RING_TOKEN_FILE")
            if resp.status_code == 416 or (resp.status_code == 403 and
                                           "TIME_RANGE_NOT_AUTHORIZED" in resp.text):
                raise MediaNotFound(f"{method} {path}: no recording we may see at that time")
            if resp.status_code not in (200, 201, 204, 206):
                raise RingError(f"{method} {path}: {resp.status_code} {resp.text[:300]}")
            return resp

    # -- devices and history --------------------------------------------------

    async def devices(self) -> list[Device]:
        doc = (await self._send("GET", "/v1/devices",
                                params={"include": "status,capabilities"})).json()
        out = []
        for r in doc.get("data") or []:
            attrs = r.get("attributes") or {}
            # Devices carry no type field; the product image's path names the model
            # (".../square_device_images/DoorbellPro/...").
            kind = " ".join(str(attrs.get(k) or "") for k in
                            ("device_type", "kind", "image_url")).lower()
            if "doorbell" in kind:
                kind = "doorbell"
            elif "chime" in kind:
                kind = "chime"
            else:
                kind = "camera"
            out.append(Device(id=r["id"], name=attrs.get("name") or r["id"], kind=kind))
        return out

    async def history(self, device_id: str, event_types: Optional[list[str]] = None,
                      limit: int = 50) -> list[HistoryEvent]:
        params = {"event_types": ",".join(event_types)} if event_types else None
        doc = (await self._send("GET", f"/v1/history/devices/{device_id}/events",
                                params=params)).json()
        out = []
        for r in (doc.get("data") or [])[:limit]:
            a = r.get("attributes") or {}
            etype = str(a.get("event_type", "unknown"))
            main, _, sub = etype.partition(".")
            out.append(HistoryEvent(id=r["id"], device_id=device_id, event_type=main,
                                    subtype=sub or a.get("sub_type"),
                                    start_ms=int(a["start"]),
                                    end_ms=int(a["end"]) if a.get("end") else None))
        return out

    # -- media ----------------------------------------------------------------

    async def clip(self, device_id: str, start_ms: int, duration_ms: int,
                   audio: bool = False) -> bytes:
        body = {"timestamp": int(start_ms),
                "duration": int(min(duration_ms, 900_000)),
                "audio_options": {"audio_enabled": bool(audio)}}
        resp = await self._send("POST", f"/v1/devices/{device_id}/media/video/download",
                                json=body, media=True)
        return resp.content

    async def snapshot(self, device_id: str, at_ms: Optional[int] = None) -> bytes:
        if at_ms is None:
            # "Latest" is a moment ago: media is only served from after the token
            # was granted, so a range reaching further back is refused (403
            # TIME_RANGE_NOT_AUTHORIZED) on a fresh token.
            import time
            at_ms = int(time.time() * 1000) - 3000
        body: dict[str, Any] = {"type": "at_timestamp", "timestamp": int(at_ms)}
        body["image_options"] = {"format": "jpeg"}
        resp = await self._send("POST", f"/v1/devices/{device_id}/media/image/download",
                                json=body, media=True)
        return resp.content

    async def chime(self, device_id: str, event: str) -> bool:
        """Play the Chime's sound for `event` (a customizable slot's event name).
        The slot's `audio_ref` is read from the device's configuration each
        time: the docs warn it can change."""
        conf = (await self._send("GET", f"/v1/devices/{device_id}/configurations")).json()
        attrs = (conf.get("data") or {}).get("attributes") or conf
        slots = ((attrs.get("audio") or {}).get("customizable_slots")) or []
        ref = next((s.get("audio_ref") for s in slots
                    if s.get("event") == event and not s.get("disabled")), None)
        if not ref:
            raise RingError(f"chime {device_id} has no enabled slot for {event!r}")
        resp = await self._send("POST", f"/v1/devices/{device_id}/media/audio/playback",
                                json={"data": {"type": "audio",
                                               "attributes": {"audio_ref": ref}}})
        status = ((resp.json().get("data") or {}).get("attributes") or {}).get("status")
        return status == "completed"
