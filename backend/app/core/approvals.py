"""Owner: Victor. Approval decisions. A decision binds to the exact proposal hash the user saw;
anything else is a stale proposal (HTTP 409 code "stale_proposal")."""
from __future__ import annotations

from app.context import proposals as ctx_proposals
from app.core import repo, worker
from app.core.schemas import TERMINAL_STATUSES, Approval, ApprovalDecisionIn


class StaleProposal(Exception):
    code = "stale_proposal"

    def __init__(self, reason: str, current_hash: str | None):
        super().__init__(reason)
        self.reason = reason
        self.current_hash = current_hash

    def detail(self) -> dict:
        return {"code": self.code, "current_hash": self.current_hash, "reason": self.reason}


def decide(task_id: str, body: ApprovalDecisionIn) -> Approval:
    task = repo.get_task(task_id)
    a = repo.get_latest_approval(task_id)
    current = a.proposal_hash if a is not None and a.status == "requested" else None
    if task.status in TERMINAL_STATUSES:
        raise StaleProposal(f"task is {task.status.value}", current)
    if a is None or a.status != "requested":
        raise StaleProposal("no proposal is awaiting approval", current)
    if body.proposal_hash != a.proposal_hash:
        raise StaleProposal("proposal has changed since it was shown", current)
    valid, why = ctx_proposals.approval_still_valid(task_id)
    if not valid:
        raise StaleProposal(why, current)
    try:
        decided = repo.decide_approval(a.id, body.decision, body.approver)
    except ValueError as e:            # lost a race with an invalidation
        raise StaleProposal(str(e), None) from e
    repo.emit(task_id, "approval.decided",
              f"{'Approved' if body.decision == 'approved' else 'Rejected'}: "
              f"{a.proposal.provider_name}",
              {"approval_id": a.id, "decision": body.decision, "approver": body.approver,
               "proposal_hash": a.proposal_hash, "provider_id": a.proposal.provider_id})
    worker.wake(task_id)
    return decided
