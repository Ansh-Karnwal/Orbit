"""Phase 4: coordinator end-to-end over fakes — the canonical demo story and its failure paths."""
from __future__ import annotations

from datetime import timedelta

from app.core import approvals, repo
from app.core.api.demo import resolve_seed
from app.core.schemas import (ApprovalDecisionIn, StepKind as K, StepState, TaskStatus as S,
                              Verdict)
from tests.core.fakes import A2, B1, events, reply, to_approval_for_a, ticks, types


def _approve_latest(task_id: str) -> None:
    a = repo.get_latest_approval(task_id)
    approvals.decide(task_id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))


async def test_demo_story_price_change_replans_to_b_and_completes(task, env):
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.WAITING_EXTERNAL
    assert sorted(p for p, _ in env.messaging.sent) == ["provider_a", "provider_b"]

    await to_approval_for_a(task.id)
    t = repo.get_task(task.id)
    assert t.status == S.AWAITING_APPROVAL
    a1 = repo.get_latest_approval(task.id)
    assert a1.proposal.provider_id == "provider_a" and a1.proposal.visit_charge_cents == 12000

    await reply(task.id, "provider_a", A2)               # "$190 total"
    await ticks(task.id)

    assert repo.get_approval(a1.id).status == "invalidated"
    a2 = repo.get_latest_approval(task.id)
    assert a2.status == "requested" and a2.proposal.provider_id == "provider_b"
    assert a2.proposal.visit_charge_cents == 14500
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL
    sup, = events(task.id, "fact.superseded")
    assert (sup["old_value"], sup["new_value"]) == (12000, 19000)
    assert any(c["kind"] == "budget_violation" and c["provider_id"] == "provider_a"
               for c in events(task.id, "conflict.detected"))
    assert [d["provider_id"] for d in events(task.id, "provider.disqualified")] == ["provider_a"]
    assert events(task.id, "plan.revised")[0]["best_provider_id"] == "provider_b"
    assert ("submit", "provider_a") not in [c[:2] for c in env.portal.calls]

    _approve_latest(task.id)
    await ticks(task.id)

    t = repo.get_task(task.id)
    assert t.status == S.COMPLETED and t.summary
    v = repo.latest_verification(task.id)
    assert v.verdict == Verdict.PASS and v.approval_id == a2.id
    assert len(env.portal.created) == 1 and env.portal.ops() == ["submit"]
    assert len(env.messaging.sent) == 2                 # replan never re-sent an inquiry
    tl = types(task.id)
    for t_ in ("fact.superseded", "provider.disqualified", "approval.invalidated", "plan.revised",
               "approval.decided", "booking.submitted", "verification.completed", "task.completed"):
        assert t_ in tl, t_
    assert tl.index("approval.invalidated") < tl.index("plan.revised") < tl.index("booking.submitted")


async def test_ticks_are_idempotent_before_replies(task, env):
    await ticks(task.id, 5)
    assert len(env.messaging.sent) == 2
    assert repo.get_task(task.id).status == S.WAITING_EXTERNAL
    assert len(repo.list_actions(task.id)) == 2


async def test_reply_timeout_never_counts_as_success(task, env):
    await ticks(task.id)
    await reply(task.id, "provider_b", B1)
    send_a, = [s for s in repo.list_steps(task.id)
               if s.kind == K.SEND_INQUIRY and s.provider_id == "provider_a"]
    old = (repo.get_task(task.id).created_at - timedelta(hours=2)).isoformat()
    repo.save_step(send_a.model_copy(update={"result": {**send_a.result, "sent_at": old}}))
    await ticks(task.id)

    wait_a, = [s for s in repo.list_steps(task.id)
               if s.kind == K.AWAIT_REPLY and s.provider_id == "provider_a"]
    assert wait_a.state == StepState.FAILED
    assert repo.get_active_fact(task.id, "provider_a.no_reply").value is True
    assert repo.get_latest_approval(task.id).proposal.provider_id == "provider_b"
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL


async def test_verification_fail_blocks_and_never_completes(task, env):
    env.portal.submit_mode = "mismatch"
    await to_approval_for_a(task.id)
    _approve_latest(task.id)
    await ticks(task.id)
    t = repo.get_task(task.id)
    assert t.status == S.BLOCKED and "verification failed" in t.status_reason
    assert repo.latest_verification(task.id).verdict == Verdict.FAIL
    assert "task.completed" not in types(task.id)


async def test_no_confirmation_is_insufficient_not_completed(task, env):
    env.portal.submit_mode = "no_confirmation"
    await to_approval_for_a(task.id)
    _approve_latest(task.id)
    await ticks(task.id, 4)
    t = repo.get_task(task.id)
    assert t.status == S.BLOCKED and "verification pending" in t.status_reason
    assert repo.latest_verification(task.id).verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert len(env.portal.created) == 1                 # reconciling never re-booked
    assert "submit" not in env.portal.ops()[1:]


async def test_rejected_approval_blocks_with_question(task, env):
    await to_approval_for_a(task.id)
    a = repo.get_latest_approval(task.id)
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="rejected"))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.BLOCKED
    assert events(task.id, "question.asked")
    assert env.portal.ops() == []


async def test_budget_exceeded_blocks_once(env):
    body = resolve_seed("fixture")
    body.limits.max_tool_actions = 1
    task = repo.create_task(body)
    await ticks(task.id, 3)                              # 2 sends > 1
    t = repo.get_task(task.id)
    assert t.status == S.BLOCKED and t.status_reason.startswith("budget exceeded")
    assert types(task.id).count("budget.exceeded") == 1


async def test_transient_read_failure_retries_with_backoff(task, env):
    env.portal.read_fail_next = 1
    await to_approval_for_a(task.id)
    ra, = [s for s in repo.list_steps(task.id) if s.kind == K.READ_AVAILABILITY]
    assert ra.state == StepState.PENDING and ra.not_before is not None and ra.attempts == 1
    assert events(task.id, "step.failed")[-1]["retrying"] is True
    repo.save_step(ra.model_copy(update={"not_before": ra.not_before - timedelta(seconds=60)}))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL
