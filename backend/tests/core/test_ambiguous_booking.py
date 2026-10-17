"""A12: an ambiguous booking is reconciled (find_booking) before any resubmission; exactly one
booking exists at the end."""
from __future__ import annotations

import pytest

from app.core import approvals, planner, repo
from app.core.schemas import (ApprovalDecisionIn, BookingRequest, StepKind as K, TaskStatus as S,
                              ToolAction, new_id, utcnow)
from tests.core.fakes import events, to_approval_for_a, ticks


async def _approved(task_id: str) -> str:
    await to_approval_for_a(task_id)
    a = repo.get_latest_approval(task_id)
    approvals.decide(task_id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))
    return a.proposal_hash


@pytest.mark.parametrize("mode", ["ambiguous_booked", "timeout_booked"])
async def test_ambiguous_but_booked_is_reconciled_without_resubmit(task, env, mode):
    env.portal.submit_mode = mode
    await _approved(task.id)
    await ticks(task.id, 3)

    assert env.portal.ops() == ["submit", "find"]
    assert len(env.portal.created) == 1
    assert events(task.id, "booking.ambiguous") and events(task.id, "booking.reconciled")[0]["found"]
    assert repo.get_task(task.id).status == S.COMPLETED


async def test_ambiguous_not_booked_resubmits_once_with_same_ref(task, env):
    env.portal.submit_mode = "timeout_not_booked"
    await _approved(task.id)
    await ticks(task.id, 3)

    submits = [c for c in env.portal.calls if c[0] == "submit"]
    assert env.portal.ops() == ["submit", "find", "submit"]
    assert len({ref for _, _, ref in submits}) == 1                 # same orbit_ref
    assert len(env.portal.created) == 1
    assert events(task.id, "booking.submitted")[0]["resubmitted"] is True
    assert repo.get_task(task.id).status == S.COMPLETED


async def test_submit_in_flight_at_crash_is_looked_up_not_resent(task, env):
    """The action row says `started` (we died mid-call) and the portal did take the booking."""
    h = await _approved(task.id)
    a = repo.get_latest_approval(task.id)
    key = planner.step_key(task.id, K.SUBMIT_BOOKING, proposal_hash=h)
    req = BookingRequest(task_id=task.id, proposal=a.proposal, approval_id=a.id,
                         orbit_ref=planner.orbit_ref(key))
    await env.portal.submit_booking(req)                     # it went through before the crash
    env.portal.calls.clear()
    repo.save_action(ToolAction(id=new_id("act"), task_id=task.id, step_id="stp_crashed",
                                adapter="fixture_browser", operation="submit_booking",
                                idempotency_key=key, request=req.model_dump(mode="json"),
                                status="started", started_at=utcnow()))
    await ticks(task.id, 3)

    assert env.portal.ops() == ["find"]
    assert len(env.portal.created) == 1
    assert repo.get_action_by_key(key).status == "succeeded"
    assert repo.get_task(task.id).status == S.COMPLETED
