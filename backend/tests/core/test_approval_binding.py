"""A6 / A7: booking is bound to the approved proposal hash; material changes invalidate approval."""
from __future__ import annotations

import pytest

from app.context.facts import ingest_fact
from app.core import approvals, repo
from app.core.schemas import ApprovalDecisionIn, StepKind as K, StepState, TaskStatus as S
from tests.core.fakes import A2, events, fact_source, reply, to_approval_for_a, ticks


def _force_request_step_succeeded(task_id: str) -> None:
    ra, = [s for s in repo.list_steps(task_id)
           if s.kind == K.REQUEST_APPROVAL and s.state == StepState.RUNNING]
    repo.save_step(ra.model_copy(update={"state": StepState.SUCCEEDED}))


async def test_price_change_after_approval_never_books_a(task, env):
    await to_approval_for_a(task.id)
    a_appr = repo.get_latest_approval(task.id)
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a_appr.proposal_hash,
                                                 decision="approved"))
    await reply(task.id, "provider_a", A2)               # lands before the next tick
    await ticks(task.id)

    assert repo.get_approval(a_appr.id).status == "invalidated"
    assert not any(op == "submit" and pid == "provider_a" for op, pid, _ in env.portal.calls)
    assert events(task.id, "approval.invalidated")[0]["approval_id"] == a_appr.id
    b_appr = repo.get_latest_approval(task.id)
    assert b_appr.proposal.provider_id == "provider_b" and b_appr.status == "requested"

    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=b_appr.proposal_hash,
                                                 decision="approved"))
    await ticks(task.id)
    assert [c[1] for c in env.portal.calls if c[0] == "submit"] == ["provider_b"]
    assert repo.get_task(task.id).status == S.COMPLETED


async def test_stale_hash_is_rejected(task, env):
    await to_approval_for_a(task.id)
    a_appr = repo.get_latest_approval(task.id)
    with pytest.raises(approvals.StaleProposal) as e:
        approvals.decide(task.id, ApprovalDecisionIn(proposal_hash="0" * 64, decision="approved"))
    assert e.value.detail() == {"code": "stale_proposal", "current_hash": a_appr.proposal_hash,
                                "reason": "proposal has changed since it was shown"}

    await reply(task.id, "provider_a", A2)
    await ticks(task.id)
    b_hash = repo.get_latest_approval(task.id).proposal_hash
    with pytest.raises(approvals.StaleProposal) as e:      # the user clicks approve on old A card
        approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a_appr.proposal_hash,
                                                     decision="approved"))
    assert e.value.current_hash == b_hash
    assert repo.get_approval(a_appr.id).status == "invalidated"


async def test_submit_preflight_refuses_unapproved(task, env):
    await to_approval_for_a(task.id)
    _force_request_step_succeeded(task.id)               # approval still only "requested"
    await ticks(task.id)
    assert env.portal.ops() == []
    assert any(d["kind"] == "submit_booking" for d in events(task.id, "step.skipped"))
    assert any("pre-flight" in d["reason"] for d in events(task.id, "plan.revised"))


async def test_submit_preflight_refuses_changed_terms(task, env):
    await to_approval_for_a(task.id)
    a_appr = repo.get_latest_approval(task.id)
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a_appr.proposal_hash,
                                                 decision="approved"))
    # terms change without going through inbound processing (worst case: detection missed it)
    ingest_fact(task.id, "provider_a.cancellation_terms", "No cancellations.",
                source_id=fact_source(task.id))
    _force_request_step_succeeded(task.id)
    await ticks(task.id)
    assert env.portal.ops() == []
    assert repo.get_approval(a_appr.id).status == "invalidated"
