"""Owner: Karthik. Stub from CP0 — replace."""
from __future__ import annotations

from typing import TypeVar

from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


async def structured(schema: type[T], *, system: str, instructions: str,
                     untrusted: list[str] | None = None, task_id: str | None = None) -> T:
    raise NotImplementedError("llm.client.structured: Karthik")
