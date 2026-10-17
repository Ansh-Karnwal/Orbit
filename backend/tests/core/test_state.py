"""Phase 2: state machine + completion gate (the coordinator cannot override the verifier)."""
from __future__ import annotations

import itertools

import pytest

from app.core import repo
from app.core.schemas import (TaskStatus as S, VerificationResult, Verdict, new_id, utcnow)
from app.core.state import ALLOWED, CompletionGateError, IllegalTransition, check_transition
from tests.core.test_repo import _proposal


def test_every_illegal_transition_raises():
    for a, b in itertools.product(S, S):
        if a == b:
            continue
        if b in ALLOWED[a]:
            check_transition(a, b)
        else:
            with pytest.raises(IllegalTransition):
                check_transition(a, b)


def test_set_status_enforces_table_and_emits(task):
    with pytest.raises(IllegalTransition):
        repo.set_status(task.id, S.VERIFYING)
    repo.set_status(task.id, S.PLANNING, "planning")
    t = repo.set_status(task.id, S.RUNNING)
    assert t.status == S.RUNNING
    changes = [e.data for e in repo.list_timeline(task.id) if e.type == "task.status_changed"]
    assert changes == [{"from": "DRAFT", "to": "PLANNING", "reason": "planning"},
                       {"from": "PLANNING", "to": "RUNNING", "reason": ""}]
    # same status again: no new event
    repo.set_status(task.id, S.RUNNING, "still running")
    assert len([e for e in repo.list_timeline(task.id) if e.type == "task.status_changed"]) == 2
    assert repo.get_task(task.id).status_reason == "still running"


def test_terminal_is_final(task):
    repo.set_status(task.id, S.CANCELLED)
    for s in S:
        if s != S.CANCELLED:
            with pytest.raises(IllegalTransition):
                repo.set_status(task.id, s)


def _to_verifying(task_id: str) -> None:
    for s in (S.PLANNING, S.RUNNING, S.VERIFYING):
        repo.set_status(task_id, s)


def _verification(task_id: str, verdict: Verdict, approval_id: str | None) -> VerificationResult:
    return repo.save_verification(VerificationResult(
        id=new_id("ver"), task_id=task_id, approval_id=approval_id, predicates=[],
        verdict=verdict, explanation="test", created_at=utcnow()))


def test_completed_rejected_without_pass(task):
    _to_verifying(task.id)
    with pytest.raises(CompletionGateError):
        repo.set_status(task.id, S.COMPLETED)          # no verification at all
    a = repo.create_approval_request(_proposal(task.id))
    repo.decide_approval(a.id, "approved", "demo_user")
    for verdict in (Verdict.FAIL, Verdict.INSUFFICIENT_EVIDENCE):
        _verification(task.id, verdict, a.id)
        with pytest.raises(CompletionGateError):
            repo.set_status(task.id, S.COMPLETED)
    assert repo.get_task(task.id).status == S.VERIFYING


def test_completed_rejected_when_pass_refers_to_old_approval(task):
    _to_verifying(task.id)
    old = repo.create_approval_request(_proposal(task.id, "provider_a", 12000))
    repo.decide_approval(old.id, "approved", "demo_user")
    _verification(task.id, Verdict.PASS, old.id)
    repo.invalidate_approvals(task.id, "price changed")
    new = repo.create_approval_request(_proposal(task.id))
    repo.decide_approval(new.id, "approved", "demo_user")
    with pytest.raises(CompletionGateError):
        repo.set_status(task.id, S.COMPLETED)


def test_completed_rejected_when_approval_not_approved(task):
    _to_verifying(task.id)
    a = repo.create_approval_request(_proposal(task.id))
    _verification(task.id, Verdict.PASS, a.id)          # still only "requested"
    with pytest.raises(CompletionGateError):
        repo.set_status(task.id, S.COMPLETED)


def test_completed_allowed_with_pass_on_current_approval(task):
    _to_verifying(task.id)
    a = repo.create_approval_request(_proposal(task.id))
    repo.decide_approval(a.id, "approved", "demo_user")
    _verification(task.id, Verdict.PASS, a.id)
    assert repo.set_status(task.id, S.COMPLETED).status == S.COMPLETED
