"""Settings, read once from the environment (and `.env` beside the working
directory, when there is one). Everything else asks `settings()`."""

from __future__ import annotations

import os
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path
from typing import Optional
from zoneinfo import ZoneInfo


def _load_env_file(path: Path) -> None:
    """KEY=value lines, never over a variable already set."""
    if not path.is_file():
        return
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip('"').strip("'"))


@dataclass(frozen=True)
class Settings:
    data: Path
    tz: ZoneInfo
    ring_api_base: str
    ring_token: str = field(repr=False)
    ring_webhook_secret: str = field(repr=False)
    chime_device: str
    chime_event: str
    models: str                    # openai | stub
    vlm: str
    llm: str
    embedder: str                  # local | openai | hash
    audio: bool
    retention_days: int
    #: A file holding the Ring token, re-read on every request: the Developer
    #: Playground's tokens last ~30 minutes, so a new one can be pasted in live.
    ring_token_file: Optional[Path] = None
    #: Poll Event History every N seconds for new events (0: webhooks only). The
    #: Playground sends no webhooks, so this is how it drives Doorstep.
    ring_poll_s: float = 0.0
    #: Also process the events already in history when polling starts.
    ring_backfill: bool = False
    #: `RING_API_BASE` is the Ring simulator (`python -m ringsim`): follow its
    #: clock, so the scripted day's times are the app's times too.
    ring_sim: bool = False

    @property
    def db_path(self) -> Path:
        return self.data / "doorstep.sqlite3"

    @property
    def clips(self) -> Path:
        return self.data / "clips"

    @property
    def snapshots(self) -> Path:
        return self.data / "snapshots"

    @property
    def out(self) -> Path:
        """Where vidra writes one folder per clip."""
        return self.data / "vidra" / "out"


def from_env() -> Settings:
    _load_env_file(Path.cwd() / ".env")
    env = os.environ.get
    data = Path(env("DOORSTEP_DATA", "data")).resolve()
    return Settings(
        data=data,
        tz=ZoneInfo(env("DOORSTEP_TZ", "Europe/London")),
        ring_api_base=env("RING_API_BASE", "https://api.amazonvision.com"),
        ring_token=env("RING_TOKEN", ""),
        # Ring signs webhooks with the HMAC key it issues at onboarding.
        ring_webhook_secret=(env("RING_WEBHOOK_SECRET") or env("HMAC_SIGNATURE_KEY")
                             or "change-me"),
        chime_device=env("RING_CHIME_DEVICE", ""),
        chime_event=env("RING_CHIME_EVENT", "ring-appstore-event-1"),
        models=env("DOORSTEP_MODELS", "openai"),
        vlm=env("DOORSTEP_VLM", ""),
        llm=env("DOORSTEP_LLM", ""),
        embedder=env("DOORSTEP_EMBEDDER", "local"),
        audio=env("DOORSTEP_AUDIO", "0") not in ("0", "", "false", "no"),
        retention_days=int(env("DOORSTEP_RETENTION_DAYS", "7")),
        ring_token_file=Path(env("RING_TOKEN_FILE")).resolve() if env("RING_TOKEN_FILE") else None,
        ring_poll_s=float(env("RING_POLL_SECONDS", "0")),
        ring_backfill=env("RING_BACKFILL", "0") not in ("0", "", "false", "no"),
        ring_sim=env("RING_SIM", "0") not in ("0", "", "false", "no"),
    )


_override: Optional[Settings] = None


@lru_cache(maxsize=1)
def _cached() -> Settings:
    return from_env()


def settings() -> Settings:
    return _override or _cached()


def use(value: Optional[Settings]) -> None:
    """Replace the settings (the tests)."""
    global _override
    _override = value
