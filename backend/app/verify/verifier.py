"""Owner: Karthik. Stub from CP0 — replace. Read-only: never calls repo write functions."""
from __future__ import annotations

from app.core import repo
from app.core.schemas import VerificationResult, Verdict, new_id, utcnow


async def verify(task_id: str) -> VerificationResult:
    approval = repo.get_latest_approval(task_id)
    return VerificationResult(
        id=new_id("ver"), task_id=task_id, approval_id=approval.id if approval else None,
        predicates=[], verdict=Verdict.INSUFFICIENT_EVIDENCE,
        explanation="CP0 stub verifier: no predicates implemented yet.", created_at=utcnow(),
    )
