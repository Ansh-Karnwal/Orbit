"""Owner: Victor. Approval decisions (hash binding, 409 stale_proposal). Stub from CP0 — Phase 4."""
from __future__ import annotations

from app.core.schemas import Approval, ApprovalDecisionIn


def decide(task_id: str, body: ApprovalDecisionIn) -> Approval:
    raise NotImplementedError("approvals.decide: Phase 4")
