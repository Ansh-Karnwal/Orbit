"""Phase 3: deterministic plan graph, idempotency keys, replanning."""
from __future__ import annotations

import re
from datetime import timedelta

from app.context.facts import ingest_fact
from app.core import planner, repo
from app.core.schemas import PlanStep, StepKind as K, StepState, TaskStatus
from tests.core.fakes import fact_source

BUDGET_OK_TERMS = "Cancel free more than 12 hours ahead."


def _by_kind(steps: list[PlanStep], kind: K, provider_id: str | None = None) -> list[PlanStep]:
    return [s for s in steps if s.kind == kind and (provider_id is None or s.provider_id == provider_id)]


def _set_state(steps: list[PlanStep], state: StepState) -> None:
    repo.save_steps([s.model_copy(update={"state": state}) for s in steps])


def _quote(task_id: str, pid: str, cents: int | None, terms: str | None = BUDGET_OK_TERMS) -> None:
    """A complete quote as the real eligibility rules need it (charge, scope, support, slot)."""
    src = fact_source(task_id)
    if cents is not None:
        ingest_fact(task_id, f"{pid}.visit_charge_cents", cents, source_id=src, currency="USD")
        ingest_fact(task_id, f"{pid}.service_supported", True, source_id=src)
        ingest_fact(task_id, f"{pid}.fee_scope", "diagnostic_visit_including_travel", source_id=src)
        start = repo.get_task(task_id).constraints.window_start + timedelta(minutes=30)
        slot = {"start": start.isoformat(), "end": (start + timedelta(hours=1)).isoformat()}
        ingest_fact(task_id, f"{pid}.slots_offered", [slot], source_id=src)
    if terms is not None:
        ingest_fact(task_id, f"{pid}.cancellation_terms", terms, source_id=src)


def _running(task_id: str) -> None:
    repo.set_status(task_id, TaskStatus.PLANNING)
    repo.set_status(task_id, TaskStatus.RUNNING)


def _demo_state_awaiting_approval(task_id: str) -> list[PlanStep]:
    """Plan v1 progressed to: quotes in, A chosen, A's availability read, approval pending."""
    steps = planner.build_initial_plan(task_id)
    _quote(task_id, "provider_a", 12000)
    _quote(task_id, "provider_b", 14500)
    done = [s for s in steps if s.kind in planner.QUOTE_KINDS or s.kind in (K.COMPARE_QUOTES,)]
    done += [planner.bind_step(_by_kind(steps, K.READ_AVAILABILITY)[0], provider_id="provider_a")]
    _set_state(done, StepState.SUCCEEDED)
    _set_state(_by_kind(steps, K.REQUEST_APPROVAL), StepState.RUNNING)
    return repo.list_steps(task_id)


# ---------------------------------------------------------------- keys
def test_step_keys_and_orbit_ref():
    t = "tsk_1"
    assert planner.step_key(t, K.SEND_INQUIRY, "provider_a", 7) == "tsk_1:send_inquiry:provider_a"
    assert planner.step_key(t, K.SEND_INQUIRY, "provider_a", 2, followup_n=1) == "tsk_1:followup:provider_a:1"
    assert planner.step_key(t, K.READ_AVAILABILITY, "provider_b", 2) == "tsk_1:read_availability:provider_b:v2"
    assert planner.step_key(t, K.COMPARE_QUOTES, None, 1) == "tsk_1:compare_quotes:-:v1"
    assert planner.step_key(t, K.SUBMIT_BOOKING, "provider_b", 3, proposal_hash="ab" * 32) == \
        "tsk_1:submit_booking:" + "ab" * 8
    ref = planner.orbit_ref("tsk_1:submit_booking:abababababababab")
    assert re.fullmatch(r"ORB-[0-9A-F]{10}", ref) and ref == planner.orbit_ref("tsk_1:submit_booking:abababababababab")


# ---------------------------------------------------------------- initial plan
def test_initial_plan_shape(task):
    steps = planner.build_initial_plan(task.id)
    assert len(steps) == 2 * 3 + 6
    for pid in ("provider_a", "provider_b"):
        send, = _by_kind(steps, K.SEND_INQUIRY, pid)
        wait, = _by_kind(steps, K.AWAIT_REPLY, pid)
        ext, = _by_kind(steps, K.EXTRACT_QUOTE, pid)
        assert send.depends_on == [] and wait.depends_on == [send.id] and ext.depends_on == [wait.id]
        assert send.idempotency_key == f"{task.id}:send_inquiry:{pid}"
    compare, = _by_kind(steps, K.COMPARE_QUOTES)
    assert set(compare.depends_on) == {s.id for s in _by_kind(steps, K.EXTRACT_QUOTE)}
    prev = compare
    for kind in planner.TAIL:
        s, = _by_kind(steps, kind)
        assert s.depends_on == [prev.id] and s.provider_id is None and s.plan_version == 1
        prev = s
    assert all(s.state == StepState.PENDING for s in steps)
    assert len({s.idempotency_key for s in steps}) == len(steps)

    created = [e for e in repo.list_timeline(task.id) if e.type == "plan.created"]
    assert len(created) == 1 and created[0].data["plan_version"] == 1


def test_initial_plan_idempotent(task):
    first = planner.build_initial_plan(task.id)
    again = planner.build_initial_plan(task.id)
    assert [s.id for s in again] == [s.id for s in first]
    assert len(repo.list_steps(task.id)) == len(first)
    assert len([e for e in repo.list_timeline(task.id) if e.type == "plan.created"]) == 1


def test_bind_step(task):
    steps = planner.build_initial_plan(task.id)
    ra = planner.bind_step(_by_kind(steps, K.READ_AVAILABILITY)[0], provider_id="provider_b")
    assert ra.provider_id == "provider_b"
    assert ra.idempotency_key == f"{task.id}:read_availability:provider_b:v1"
    sb = planner.bind_step(_by_kind(steps, K.SUBMIT_BOOKING)[0], provider_id="provider_b",
                           proposal_hash="f" * 64)
    assert sb.idempotency_key == f"{task.id}:submit_booking:{'f' * 16}"
    send = _by_kind(steps, K.SEND_INQUIRY, "provider_a")[0]
    assert planner.bind_step(send, provider_id="provider_b") == send


# ---------------------------------------------------------------- replan
def test_replan_after_price_change_moves_to_provider_b(task):
    _running(task.id)
    before = _demo_state_awaiting_approval(task.id)
    _quote(task.id, "provider_a", 19000, terms=None)     # A: "$190 total"

    added = planner.replan(task.id, "provider_a price changed to $190 (over budget)")

    steps = repo.list_steps(task.id)
    by_id = {s.id: s for s in steps}
    # old open tail skipped; succeeded history untouched
    for kind in (K.REQUEST_APPROVAL, K.SUBMIT_BOOKING, K.VERIFY, K.SUMMARIZE):
        old, = [s for s in _by_kind(steps, kind) if s.plan_version == 1]
        assert old.state == StepState.SKIPPED
    assert all(by_id[s.id].state == StepState.SUCCEEDED
               for s in before if s.state == StepState.SUCCEEDED)
    # fresh v2 decision chain, no re-sent inquiry
    assert [s.kind for s in added] == [K.COMPARE_QUOTES, *planner.TAIL]
    assert all(s.plan_version == 2 and s.state == StepState.PENDING for s in added)
    # compare v2 waits only on providers still in the running (A is disqualified)
    assert added[0].depends_on == [_by_kind(before, K.EXTRACT_QUOTE, "provider_b")[0].id]
    assert len(_by_kind(steps, K.SEND_INQUIRY)) == 2
    assert len({s.idempotency_key for s in steps}) == len(steps)

    tl = repo.list_timeline(task.id)
    revised = [e for e in tl if e.type == "plan.revised"][-1]
    assert revised.data["plan_version"] == 2
    assert revised.data["added_step_ids"] == [s.id for s in added]
    assert len(revised.data["skipped_step_ids"]) == 4
    assert revised.data["best_provider_id"] == "provider_b"
    assert "price changed" in revised.data["reason"]
    assert len([e for e in tl if e.type == "step.skipped"]) == 4
    assert repo.get_task(task.id).status == TaskStatus.RUNNING


def test_replan_before_compare_keeps_waiting_on_live_provider(task):
    """A replied over budget while B is still pending: decide over B only, keep B's steps."""
    _running(task.id)
    steps = planner.build_initial_plan(task.id)
    _set_state([s for s in steps if s.provider_id == "provider_a"], StepState.SUCCEEDED)
    _quote(task.id, "provider_a", 19000)

    added = planner.replan(task.id, "provider_a over budget")

    b_extract, = _by_kind(steps, K.EXTRACT_QUOTE, "provider_b")
    assert added[0].kind == K.COMPARE_QUOTES and added[0].depends_on == [b_extract.id]
    assert repo.get_step(b_extract.id).state == StepState.PENDING
    assert repo.get_step(_by_kind(steps, K.COMPARE_QUOTES)[0].id).state == StepState.SKIPPED


def test_replan_no_reply_provider_steps_skipped(task):
    _running(task.id)
    steps = planner.build_initial_plan(task.id)
    _set_state([s for s in steps if s.provider_id == "provider_b"], StepState.SUCCEEDED)
    _quote(task.id, "provider_b", 14500)
    _set_state(_by_kind(steps, K.SEND_INQUIRY, "provider_a"), StepState.SUCCEEDED)
    _set_state(_by_kind(steps, K.AWAIT_REPLY, "provider_a"), StepState.FAILED)
    ingest_fact(task.id, "provider_a.no_reply", True, source_id=fact_source(task.id))

    added = planner.replan(task.id, "provider_a did not reply")

    assert repo.get_step(_by_kind(steps, K.EXTRACT_QUOTE, "provider_a")[0].id).state == StepState.SKIPPED
    assert repo.get_step(_by_kind(steps, K.AWAIT_REPLY, "provider_a")[0].id).state == StepState.FAILED
    assert added[0].depends_on == [_by_kind(steps, K.EXTRACT_QUOTE, "provider_b")[0].id]


def test_replan_followup_once_then_blocked(task):
    """A over budget; B replied without a price -> one follow-up to B, then BLOCKED."""
    _running(task.id)
    steps = planner.build_initial_plan(task.id)
    _set_state([s for s in steps if s.kind in planner.QUOTE_KINDS], StepState.SUCCEEDED)
    _quote(task.id, "provider_a", 19000)
    _quote(task.id, "provider_b", None)

    added = planner.replan(task.id, "no eligible provider")

    send, wait, ext = added[:3]
    assert send.kind == K.SEND_INQUIRY and send.provider_id == "provider_b"
    assert send.idempotency_key == f"{task.id}:followup:provider_b:1" and planner.is_followup(send)
    assert wait.depends_on == [send.id] and ext.depends_on == [wait.id]
    assert [s.kind for s in added[3:]] == [K.COMPARE_QUOTES, *planner.TAIL]
    assert added[3].depends_on == [ext.id]
    assert repo.get_task(task.id).status == TaskStatus.RUNNING

    # B answers the follow-up but still gives no price -> no second follow-up -> BLOCKED
    _set_state(added[:3], StepState.SUCCEEDED)
    assert planner.replan(task.id, "still no eligible provider") == []
    t = repo.get_task(task.id)
    assert t.status == TaskStatus.BLOCKED and t.reason_code == "no_eligible_provider"
    assert "raise the budget" in t.status_reason.lower()
    assert repo.list_timeline(task.id)[-2].type == "question.asked"
    assert len([s for s in repo.list_steps(task.id) if planner.is_followup(s)]) == 1


def test_replan_all_over_budget_blocks_with_question(task):
    _running(task.id)
    steps = planner.build_initial_plan(task.id)
    _set_state([s for s in steps if s.kind in planner.QUOTE_KINDS], StepState.SUCCEEDED)
    _quote(task.id, "provider_a", 19000)
    _quote(task.id, "provider_b", 17500)

    assert planner.replan(task.id, "both over budget") == []
    assert repo.get_task(task.id).status == TaskStatus.BLOCKED
    q = [e for e in repo.list_timeline(task.id) if e.type == "question.asked"][-1]
    assert set(q.data["eligibility"]) == {"provider_a", "provider_b"}


def test_replan_refuses_after_booking_attempted(task):
    from app.core.schemas import ToolAction, new_id, utcnow
    _running(task.id)
    steps = _demo_state_awaiting_approval(task.id)
    sb = _by_kind(steps, K.SUBMIT_BOOKING)[0]
    repo.save_action(ToolAction(id=new_id("act"), task_id=task.id, step_id=sb.id,
                                adapter="fixture_browser", operation="submit_booking",
                                idempotency_key="k-book", request={}, status="ambiguous",
                                started_at=utcnow()))
    n_steps = len(repo.list_steps(task.id))
    assert planner.replan(task.id, "price changed") == []
    assert len(repo.list_steps(task.id)) == n_steps
    assert repo.get_task(task.id).status == TaskStatus.BLOCKED


def test_replan_noop_while_booking_running(task):
    _running(task.id)
    steps = _demo_state_awaiting_approval(task.id)
    _set_state(_by_kind(steps, K.SUBMIT_BOOKING), StepState.RUNNING)
    assert planner.replan(task.id, "price changed") == []
    assert planner.current_plan_version(task.id) == 1
