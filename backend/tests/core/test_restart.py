"""A13 (+A12 across restarts): a fresh app/worker on the same DB resumes the run without
duplicate sends or bookings. "Crash" = dispose the engine and drop all in-memory state; the
fake adapters stand for the outside world, which keeps whatever happened before the crash."""
from __future__ import annotations

import time
from datetime import timedelta

from fastapi.testclient import TestClient

from app.core import approvals, coordinator, db, planner, recovery, repo
from app.core.schemas import (ApprovalDecisionIn, BookingRequest, PlanStep, StepKind as K,
                              StepState, TaskStatus as S, ToolAction, new_id, utcnow)
from app.main import app
from tests.core.fakes import A1, B1, events, reply, to_approval_for_a, ticks, types


def _restart(url: str) -> dict:
    db._engine.dispose()
    db._engine = db._sessionmaker = None
    db.init_db(url)
    return recovery.recover()


def _step(task_id: str, kind: K, provider_id: str | None = None) -> PlanStep:
    return [s for s in repo.list_steps(task_id) if s.kind == kind
            and (provider_id is None or s.provider_id == provider_id)][-1]


def _wait(pred, max_s: float = 10.0) -> None:
    end = time.monotonic() + max_s
    while not pred():
        assert time.monotonic() < end, "timed out"
        time.sleep(0.02)


async def _approve(task_id: str) -> tuple[str, BookingRequest]:
    """Approve A; return the bound submit key and the request a submit would send."""
    await to_approval_for_a(task_id)
    a = repo.get_latest_approval(task_id)
    approvals.decide(task_id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))
    rq = _step(task_id, K.REQUEST_APPROVAL)
    repo.save_step(rq.model_copy(update={"state": StepState.SUCCEEDED,
                                         "result": {"approval_id": a.id}}))
    key = planner.step_key(task_id, K.SUBMIT_BOOKING, proposal_hash=a.proposal_hash)
    req = BookingRequest(task_id=task_id, proposal=a.proposal, approval_id=a.id,
                         orbit_ref=planner.orbit_ref(key))
    return key, req


def _crash_mid_submit(task_id: str, key: str, req: BookingRequest) -> None:
    sb = planner.bind_step(_step(task_id, K.SUBMIT_BOOKING), provider_id=req.proposal.provider_id,
                           proposal_hash=req.proposal.compute_hash())
    repo.save_step(sb.model_copy(update={"state": StepState.RUNNING, "attempts": 1}))
    repo.save_action(ToolAction(id=new_id("act"), task_id=task_id, step_id=sb.id,
                                adapter="fixture_browser", operation="submit_booking",
                                idempotency_key=key, request=req.model_dump(mode="json"),
                                status="started", started_at=utcnow()))


# ---------------------------------------------------------------- whole app, real lifespan
def test_run_resumes_after_restart_through_lifespan(env, fresh_db):
    with TestClient(app) as c:                                   # process 1
        tid = c.post("/tasks", json=c.get("/demo/seed").json()).json()["task"]["id"]
        _wait(lambda: len(env.messaging.sent) == 2
              and repo.get_task(tid).status == S.WAITING_EXTERNAL)
    # process 1 is gone; replies arrive while we're down? No — after restart, via the API.
    db._engine.dispose()
    db._engine = db._sessionmaker = None

    with TestClient(app) as c:                                   # process 2: init + recover + worker
        for pid, text in (("provider_a", A1), ("provider_b", B1)):
            r = c.post("/demo/inject-event", json={"task_id": tid, "provider_id": pid, "text": text})
            assert r.json()["created"] is True
        _wait(lambda: repo.get_task(tid).status == S.AWAITING_APPROVAL)
        h = c.get(f"/tasks/{tid}").json()["approvals"][-1]["proposal_hash"]
        assert c.post(f"/tasks/{tid}/approvals",
                      json={"proposal_hash": h, "decision": "approved"}).status_code == 200
        _wait(lambda: repo.get_task(tid).status == S.COMPLETED)

    assert sorted(p for p, _ in env.messaging.sent) == ["provider_a", "provider_b"]
    assert env.portal.ops() == ["submit"] and len(env.portal.created) == 1
    seqs = [e.seq for e in repo.list_timeline(tid)]
    assert seqs == list(range(1, len(seqs) + 1))


# ---------------------------------------------------------------- targeted crash points
async def test_crash_mid_send_never_resends(task, env, fresh_db):
    await ticks(task.id)
    send_a = _step(task.id, K.SEND_INQUIRY, "provider_a")
    repo.save_step(send_a.model_copy(update={"state": StepState.RUNNING, "result": None}))
    wait_a = _step(task.id, K.AWAIT_REPLY, "provider_a")
    repo.save_step(wait_a.model_copy(update={"state": StepState.PENDING}))
    act = repo.get_action_by_key(send_a.idempotency_key)
    repo.save_action(act.model_copy(update={"status": "started", "finished_at": None}))

    stats = _restart(fresh_db)
    assert stats["actions_ambiguous"] == 1 and stats["steps_reset"] == 1
    await ticks(task.id)
    await reply(task.id, "provider_a", A1)
    await reply(task.id, "provider_b", B1)
    await ticks(task.id)

    assert len(env.messaging.sent) == 2                          # A was not re-sent
    assert _step(task.id, K.SEND_INQUIRY, "provider_a").result["status"] == "assumed_sent"
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL


async def test_pending_approval_survives_restart(task, env, fresh_db):
    await to_approval_for_a(task.id)
    a = repo.get_latest_approval(task.id)
    stats = _restart(fresh_db)
    assert stats["steps_reset"] == 0                             # polled steps stay running
    assert repo.get_approval(a.id).status == "requested"
    assert _step(task.id, K.REQUEST_APPROVAL).state == StepState.RUNNING
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.COMPLETED
    assert len(env.messaging.sent) == 2 and len(env.portal.created) == 1


async def test_crash_mid_submit_after_portal_booked(task, env, fresh_db):
    key, req = await _approve(task.id)
    await env.portal.submit_booking(req)                         # the booking landed...
    env.portal.calls.clear()
    _crash_mid_submit(task.id, key, req)                         # ...then we died

    stats = _restart(fresh_db)
    assert stats["bookings_reconciling"] == 1
    assert _step(task.id, K.SUBMIT_BOOKING).state == StepState.FAILED
    await ticks(task.id, 3)

    assert env.portal.ops() == ["find"] and len(env.portal.created) == 1
    assert events(task.id, "booking.reconciled")[0]["found"] is True
    assert repo.get_task(task.id).status == S.COMPLETED


async def test_crash_mid_submit_before_portal_booked(task, env, fresh_db):
    key, req = await _approve(task.id)
    _crash_mid_submit(task.id, key, req)                         # died before the portal saw it

    _restart(fresh_db)
    await ticks(task.id, 3)

    assert env.portal.ops() == ["find", "submit"]                # looked first, resubmitted once
    assert {c[2] for c in env.portal.calls if c[0] != "read"} == {req.orbit_ref}
    assert len(env.portal.created) == 1
    assert repo.get_task(task.id).status == S.COMPLETED


async def test_crash_mid_resubmit_rechecks_instead_of_resubmitting(task, env, fresh_db):
    key, req = await _approve(task.id)
    _crash_mid_submit(task.id, key, req)
    sub = repo.get_action_by_key(key)
    repo.save_action(sub.model_copy(update={"status": "ambiguous"}))
    sb = _step(task.id, K.SUBMIT_BOOKING)
    coordinator.reconcile_interrupted_booking(repo.get_task(task.id), sb, sub, "test")
    repo.save_step(sb.model_copy(update={"state": StepState.FAILED}))
    rec = _step(task.id, K.RECONCILE_BOOKING)
    repo.save_step(rec.model_copy(update={"state": StepState.RUNNING, "attempts": 1}))
    repo.save_action(ToolAction(id=new_id("act"), task_id=task.id, step_id=rec.id,
                                adapter="fixture_browser", operation="find_booking",
                                idempotency_key=rec.idempotency_key, request={},
                                status="succeeded", result={"found": None}, started_at=utcnow()))
    repo.save_action(ToolAction(id=new_id("act"), task_id=task.id, step_id=rec.id,
                                adapter="fixture_browser", operation="submit_booking",
                                idempotency_key=f"{key}:resubmit", request=req.model_dump(mode="json"),
                                status="started", started_at=utcnow()))
    await env.portal.submit_booking(req)                         # the resubmission landed
    env.portal.calls.clear()

    _restart(fresh_db)
    await ticks(task.id, 3)

    assert env.portal.ops() == ["find"]                          # re-check only, no 3rd submit
    assert len(env.portal.created) == 1
    assert repo.get_task(task.id).status == S.COMPLETED


async def test_ambiguous_resubmit_rechecks_on_retry(task, env):
    env.portal.submit_mode = "timeout_not_booked"
    env.portal.mode_after_timeout = "timeout_booked"            # resubmit books, then times out
    await _approve(task.id)
    await ticks(task.id, 2)
    rec = _step(task.id, K.RECONCILE_BOOKING)
    assert rec.state == StepState.PENDING and rec.not_before is not None   # backing off
    repo.save_step(rec.model_copy(update={"not_before": rec.not_before - timedelta(seconds=60)}))
    await ticks(task.id, 2)

    assert env.portal.ops() == ["submit", "find", "submit", "find"]
    assert len(env.portal.created) == 1
    assert repo.get_task(task.id).status == S.COMPLETED


async def test_recovery_is_idempotent(task, env, fresh_db):
    key, req = await _approve(task.id)
    _crash_mid_submit(task.id, key, req)
    first = _restart(fresh_db)
    second = _restart(fresh_db)
    assert first["bookings_reconciling"] == 1
    assert {k: v for k, v in second.items() if k != "tasks"} == \
        {"actions_ambiguous": 0, "steps_reset": 0, "bookings_reconciling": 0}
    assert types(task.id).count("booking.ambiguous") == 1
