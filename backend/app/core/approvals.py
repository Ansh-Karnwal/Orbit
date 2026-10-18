"""Owner: Victor. Approval decisions. A decision binds to the exact proposal hash the user saw;
anything else is a stale proposal (HTTP 409 code "stale_proposal").

Rejecting means "not this one", not "stop" (roadmap A): the decision is stored as user_decision
evidence and becomes a fact — `{p}.declined_by_user` (scope "provider") or `{p}.declined_slots`
(scope "proposal") — so eligibility skips it and the coordinator re-coordinates the next option."""
from __future__ import annotations

from app.context import facts as ctx_facts
from app.context import proposals as ctx_proposals
from app.core import repo, telemetry, worker
from app.core.evidence import save_evidence
from app.core.schemas import TERMINAL_STATUSES, Approval, ApprovalDecisionIn


class StaleProposal(Exception):
    code = "stale_proposal"

    def __init__(self, reason: str, current_hash: str | None):
        super().__init__(reason)
        self.reason = reason
        self.current_hash = current_hash

    def detail(self) -> dict:
        return {"code": self.code, "current_hash": self.current_hash, "reason": self.reason}


def _record_decline(task_id: str, a: Approval, body: ApprovalDecisionIn, approver: str) -> None:
    p = a.proposal
    ev = save_evidence(task_id, "user_decision", "orbit", is_fixture=False, extracted={
        "approval_id": a.id, "decision": "rejected", "scope": body.scope, "reason": body.reason,
        "provider_id": p.provider_id, "slot_start": p.slot_start.isoformat(),
        "slot_end": p.slot_end.isoformat(), "approver": approver})
    if body.scope == "provider":
        key, value = f"{p.provider_id}.declined_by_user", True
    else:
        prior = repo.get_active_fact(task_id, f"{p.provider_id}.declined_slots")
        key = f"{p.provider_id}.declined_slots"
        value = [*(prior.value if prior else []),
                 {"start": p.slot_start.isoformat(), "end": p.slot_end.isoformat()}]
    res = ctx_facts.ingest_fact(task_id, key, value, source_id=ev.id)
    if res.changed:
        repo.emit(task_id, "fact.added",
                  f"{p.provider_name}: " + ("declined by you" if body.scope == "provider"
                                            else "that time declined by you"),
                  {"fact_id": res.fact.id, "key": key, "provider_id": p.provider_id,
                   "value": res.fact.value, "version": res.fact.version,
                   "status": res.fact.status.value, "source_id": ev.id})


def decide(task_id: str, body: ApprovalDecisionIn, approver: str | None = None) -> Approval:
    """`approver` is the signed-in user (the API passes it); body.approver is only a fallback."""
    approver = approver or body.approver
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
        decided = repo.decide_approval(a.id, body.decision, approver)
    except ValueError as e:            # lost a race with an invalidation
        raise StaleProposal(str(e), None) from e
    repo.emit(task_id, "approval.decided",
              f"{'Approved' if body.decision == 'approved' else 'Declined'}: "
              f"{a.proposal.provider_name}",
              {"approval_id": a.id, "decision": body.decision, "approver": approver,
               "proposal_hash": a.proposal_hash, "provider_id": a.proposal.provider_id,
               "scope": body.scope if body.decision == "rejected" else None,
               "reason": body.reason if body.decision == "rejected" else None})
    telemetry.record("approval.decided", task_id, provider_id=a.proposal.provider_id,
                     decision=body.decision, mode=task.mode)
    if body.decision == "rejected":
        _record_decline(task_id, a, body, approver)
    worker.wake(task_id)
    return decided
