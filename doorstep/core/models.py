"""Which models answer, built once from the settings, and the one call the app
makes to an LLM itself (rules, ask, digest). Describing frames always goes
through the library."""

from __future__ import annotations

from functools import lru_cache
from typing import Any, Optional

from .config import settings


@lru_cache(maxsize=1)
def models():
    from vidra import HashEmbedder, LocalEmbedder, Models, OpenAI, OpenAIEmbedder, Stub

    s = settings()
    if s.models == "stub":
        vlm = llm = Stub()
    elif s.models == "openai":
        vlm = OpenAI(s.vlm) if s.vlm else OpenAI()
        llm = OpenAI(s.llm) if s.llm else OpenAI()
    else:
        raise ValueError(f"DOORSTEP_MODELS={s.models!r}: openai or stub")
    embedder = {"local": LocalEmbedder, "openai": OpenAIEmbedder,
                "hash": HashEmbedder}[s.embedder]()
    return Models(vlm=vlm, llm=llm, embedder=embedder)


def reset() -> None:
    models.cache_clear()


async def complete(prompt: str, schema: Optional[dict[str, Any]] = None,
                   system: Optional[str] = None, max_output_tokens: int = 4000) -> Any:
    """One LLM call, through the library's wrapper: a concurrency cap, JSON
    parsed for a schema, and any failure raised as `ModelFailed`."""
    from vidra.shared.models.base import calls

    llm = calls("llm", models().llm)
    return await llm.complete(prompt, schema=schema, system=system,
                              max_output_tokens=max_output_tokens)


def strict(name: str, properties: dict[str, Any]) -> dict[str, Any]:
    """A strict JSON schema: every property required, nothing else allowed."""
    return {"name": name, "schema": {"type": "object", "properties": properties,
                                     "required": list(properties),
                                     "additionalProperties": False}}
