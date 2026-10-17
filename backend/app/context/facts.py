"""Owner: Karthik. Stub from CP0 — replace."""
from __future__ import annotations

from datetime import datetime

from app.core import repo
from app.core.schemas import ContextFact, FactStatus, IngestResult, new_id, utcnow


def ingest_fact(task_id: str, key: str, value, *, source_id: str, scope: str | None = None,
                currency: str | None = None, observed_at: datetime | None = None,
                valid_until: datetime | None = None,
                status: FactStatus = FactStatus.CONFIRMED) -> IngestResult:
    prev = repo.get_active_fact(task_id, key)
    if prev is not None and prev.value == value:
        return IngestResult(fact=prev, changed=False)
    fact = repo.insert_fact(ContextFact(
        id=new_id("fct"), task_id=task_id, key=key, value=value, currency=currency, scope=scope,
        source_id=source_id, observed_at=observed_at or utcnow(), valid_until=valid_until,
        status=status, version=(prev.version + 1) if prev else 1,
        supersedes=prev.id if prev else None,
    ))
    if prev is not None:
        repo.set_fact_status(prev.id, FactStatus.SUPERSEDED)
    return IngestResult(fact=fact, superseded=prev)
