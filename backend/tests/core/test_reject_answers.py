"""Roadmap A (reject -> coordinate other options) and F3 (questions, reason codes, answers)."""
from __future__ import annotations

from zoneinfo import ZoneInfo

import pytest

from app.core import answers, approvals, questions, repo
from app.core.api.demo import resolve_seed
from app.core.evidence import save_evidence
from app.core.schemas import (AnswerIn, ApprovalDecisionIn, BookingResult, ConfirmationExtract,
                              TaskStatus as S)
from tests.core.fakes import A1, A2, B1, events, reply, to_approval_for_a, ticks, types

A_190 = ("Hi! Dishwasher repair visit is $190 including travel. I can do Tuesday 3–4pm. "
         "Free cancellation with 24 hours notice.")
B_175 = ("Yes we repair dishwashers. Diagnostic visit is $175 including travel. Tuesday "
         "2:30–3:30pm or 4–5pm. Cancel free more than 12 hours ahead, $25 inside 12 hours.")
C_140 = ("Coastal Appliance Pros here. Dishwasher diagnostic visit is $140 including travel. "
         "Tuesday 4–5pm. Free cancellation with 48 hours notice.")


def _decide(task_id: str, decision: str, scope: str = "provider") -> None:
    a = repo.get_latest_approval(task_id)
    approvals.decide(task_id, ApprovalDecisionIn(proposal_hash=a.proposal_hash,
                                                 decision=decision, scope=scope))


def _answer(task_id: str, choice: str, **params):
    q = questions.open_question(task_id)
    assert q is not None, "expected an open question"
    return answers.answer(task_id, AnswerIn(question_id=q.question_id, choice=choice,
                                            params=params), "demo_user")


async def _both_over_budget(task_id: str) -> None:
    await ticks(task_id)
    await reply(task_id, "provider_a", A_190)
    await reply(task_id, "provider_b", B_175)
    await ticks(task_id)


# ---------------------------------------------------------------- A. reject
async def test_reject_slot_only_keeps_provider_and_offers_next_time(task, env):
    await to_approval_for_a(task.id)
    _decide(task.id, "rejected")                          # not Ace at all
    await ticks(task.id)
    first = repo.get_latest_approval(task.id)
    assert first.proposal.provider_id == "provider_b"
    _decide(task.id, "rejected", scope="proposal")        # not 2:30 — Bayside is still fine
    await ticks(task.id)
    second = repo.get_latest_approval(task.id)
    assert second.proposal.provider_id == "provider_b" and second.status == "requested"
    la = ZoneInfo("America/Los_Angeles")
    assert first.proposal.slot_start.astimezone(la).strftime("%H:%M") == "14:30"
    assert second.proposal.slot_start.astimezone(la).strftime("%H:%M") == "16:00"
    _decide(task.id, "approved")
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.COMPLETED
    evidence = repo.list_evidence(task.id, kind="user_decision")
    assert [e.extracted["scope"] for e in evidence] == ["provider", "proposal"]
    assert all(not e.is_fixture for e in evidence)        # the user's decisions are real


# ---------------------------------------------------------------- F3. answers
async def test_raise_budget_answer_resumes_and_books(task, env):
    await _both_over_budget(task.id)
    t = repo.get_task(task.id)
    assert t.status == S.BLOCKED and t.reason_code == "no_eligible_provider"
    q = questions.open_question(task.id)
    budget = next(o for o in q.options if o.id == "raise_budget")
    assert budget.params == {"current_cents": 15000, "suggested_cents": 17500}
    assert {o.id for o in q.options} >= {"raise_budget", "widen_window", "add_provider", "stop"}

    t = _answer(task.id, "raise_budget", max_visit_charge_cents=17500)
    assert t.status == S.PLANNING and t.constraints.max_visit_charge_cents == 17500
    assert questions.open_question(task.id) is None
    await ticks(task.id)
    a = repo.get_latest_approval(task.id)
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL
    assert a.proposal.provider_id == "provider_b" and a.proposal.visit_charge_cents == 17500
    answered, = events(task.id, "question.answered")
    assert answered["choice"] == "raise_budget" and answered["by"] == "demo_user"


async def test_worker_tick_during_an_answer_cannot_strand_the_task(task, env, monkeypatch):
    """Regression (found in the live drive after merging main): a worker tick that runs
    between the answer and its replan must not conclude "nothing left" and re-block."""
    from app.core import coordinator, planner
    await _both_over_budget(task.id)
    real_replan = planner.replan

    def tick_sneaks_in_first(task_id, reason):
        coordinator._derive_status(task_id)          # what a concurrent tick would do
        return real_replan(task_id, reason)
    monkeypatch.setattr(planner, "replan", tick_sneaks_in_first)

    t = _answer(task.id, "raise_budget", max_visit_charge_cents=17500)
    assert t.status == S.PLANNING
    assert "nothing left" not in " ".join(e.message for e in repo.list_timeline(task.id))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL
    assert repo.get_latest_approval(task.id).proposal.provider_id == "provider_b"


async def test_answer_validation(task, env):
    await _both_over_budget(task.id)
    q = questions.open_question(task.id)
    with pytest.raises(answers.AnswerError) as e:
        answers.answer(task.id, AnswerIn(question_id="q_old", choice="stop"), "demo_user")
    assert (e.value.status, e.value.code) == (409, "stale_question")
    with pytest.raises(answers.AnswerError) as e:
        answers.answer(task.id, AnswerIn(question_id=q.question_id, choice="check_again"), "u")
    assert (e.value.status, e.value.code) == (422, "invalid_answer")
    with pytest.raises(answers.AnswerError) as e:                      # must be an increase
        _answer(task.id, "raise_budget", max_visit_charge_cents=14000)
    assert e.value.status == 422
    assert repo.get_task(task.id).status == S.BLOCKED                  # nothing changed


async def test_reconsider_and_add_provider_after_rejecting_everyone(task, env):
    await to_approval_for_a(task.id)
    _decide(task.id, "rejected")
    await ticks(task.id)
    _decide(task.id, "rejected")
    await ticks(task.id)
    assert repo.get_task(task.id).reason_code == "user_rejected_all"
    q = questions.open_question(task.id)
    assert next(o for o in q.options if o.id == "reconsider").params["provider_ids"] == \
        ["provider_a", "provider_b"]

    _answer(task.id, "add_provider", provider={"id": "provider_c", "name": "Coastal Appliance Pros",
                                               "handle": "fixture:provider_c"})
    await ticks(task.id)
    assert ("provider_c" in {p for p, _ in env.messaging.sent})
    await reply(task.id, "provider_c", C_140)
    await ticks(task.id)
    a = repo.get_latest_approval(task.id)
    assert a.proposal.provider_id == "provider_c" and a.status == "requested"

    _decide(task.id, "rejected")
    await ticks(task.id)
    _answer(task.id, "reconsider", provider_id="provider_a")          # changed my mind on Ace
    await ticks(task.id)
    a = repo.get_latest_approval(task.id)
    assert a.proposal.provider_id == "provider_a" and repo.get_task(task.id).status == S.AWAITING_APPROVAL


async def test_extend_limits_answer_lets_orbit_continue(env):
    body = resolve_seed("fixture")
    body.limits.max_tool_actions = 1
    task = repo.create_task(body)
    await ticks(task.id)
    assert repo.get_task(task.id).reason_code == "budget_exceeded"
    assert env.messaging.sent == []                       # gated before spending
    _answer(task.id, "extend_limits")
    assert repo.get_task(task.id).limits.max_tool_actions == 2
    await ticks(task.id)
    assert len(env.messaging.sent) == 2 and repo.get_task(task.id).status == S.WAITING_EXTERNAL


async def test_must_text_first_blocks_once_then_retry_sends(task, env):
    env.messaging.must_text_first = {"provider_a"}
    await ticks(task.id, 3)
    t = repo.get_task(task.id)
    assert t.status == S.BLOCKED and t.reason_code == "integration_blocked"
    assert "must text the Orbit line" in t.status_reason
    assert types(task.id).count("question.asked") == 1                 # no retry loop
    env.messaging.must_text_first = set()                              # the teammate texted us
    _answer(task.id, "retry")
    await ticks(task.id)
    assert {p for p, _ in env.messaging.sent} == {"provider_a", "provider_b"}


async def test_check_again_answer_reverifies_without_resubmitting(task, env):
    env.portal.submit_mode = "no_confirmation"
    await to_approval_for_a(task.id)
    _decide(task.id, "approved")
    await ticks(task.id, 4)
    assert repo.get_task(task.id).reason_code == "verification_pending"
    # The portal now shows the confirmation for the same booking.
    ref, = env.portal.bookings
    p = repo.get_latest_approval(task.id).proposal
    conf = ConfirmationExtract(confirmation_id="BK-LATE", provider_id=p.provider_id,
                               service=p.service, slot_start=p.slot_start, slot_end=p.slot_end,
                               visit_charge_cents=p.visit_charge_cents,
                               cancellation_terms=p.cancellation_terms, orbit_ref=ref)
    ev = save_evidence(task.id, "portal_confirmation", "fixture_browser", is_fixture=True,
                       extracted=conf.model_dump(mode="json"), provider_ref="BK-LATE")
    env.portal.bookings[ref] = BookingResult(status="confirmed", confirmation=conf,
                                             evidence_ids=[ev.id])
    _answer(task.id, "check_again")
    await ticks(task.id, 3)
    assert repo.get_task(task.id).status == S.COMPLETED
    assert len(env.portal.created) == 1                                # never booked twice


async def test_stop_answer_cancels(task, env):
    await _both_over_budget(task.id)
    t = _answer(task.id, "stop")
    assert t.status == S.CANCELLED and t.reason_code == "cancelled"


async def test_new_provider_info_withdraws_question_and_resumes(task, env):
    await _both_over_budget(task.id)
    assert repo.get_task(task.id).reason_code == "no_eligible_provider"
    await reply(task.id, "provider_b", "Good news: we can do the diagnostic visit for $145 "
                                       "including travel.")
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL
    assert events(task.id, "question.answered")[-1]["choice"] == "withdrawn"
