"""What Doorstep needs from Ring, as one interface with two implementations:
`client.RingClient` (the Partner API) and `replay.ReplayRing` (a scripted day
of local clips). The pipeline cannot tell them apart."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional, Protocol


class RingError(Exception):
    """A request Ring refused or could not answer."""


class MediaNotFound(RingError):
    """No recording covers the time asked for (416 MEDIA_NOT_FOUND)."""


@dataclass
class Device:
    id: str
    name: str
    kind: str = "camera"          # doorbell | camera | chime


@dataclass
class HistoryEvent:
    id: str
    device_id: str
    event_type: str               # motion | ding | on_demand
    start_ms: int
    end_ms: Optional[int]
    subtype: Optional[str] = None


class RingAPI(Protocol):
    async def devices(self) -> list[Device]: ...

    async def history(self, device_id: str, event_types: Optional[list[str]] = None,
                      limit: int = 50) -> list[HistoryEvent]:
        """Newest first."""
        ...

    async def clip(self, device_id: str, start_ms: int, duration_ms: int,
                   audio: bool = False) -> bytes:
        """MP4 bytes; raises `MediaNotFound`."""
        ...

    async def snapshot(self, device_id: str, at_ms: Optional[int] = None) -> bytes:
        """JPEG bytes at a time, or the latest; raises `MediaNotFound`."""
        ...

    async def chime(self, device_id: str, event: str) -> bool: ...

    async def aclose(self) -> None: ...
