"""Owner: Victor. Durable background worker. Stub from CP0 — Phase 4."""
from __future__ import annotations


def wake(task_id: str | None = None) -> None:
    """Signal the worker loop to tick now. No-op until Phase 4."""
    return None


async def start() -> None:
    return None


async def stop() -> None:
    return None
