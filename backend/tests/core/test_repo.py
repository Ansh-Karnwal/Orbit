"""Phase 1: persistence and repository."""
from __future__ import annotations

import asyncio
from concurrent.futures import ThreadPoolExecutor
from datetime import timezone

import pytest
from sqlalchemy.exc import IntegrityError

from app.core import db, repo
from app.core.evidence import save_evidence
from app.core.schemas import (ContextFact, FactStatus, InboundEvent, PlanStep, Proposal, StepKind,
                              TaskStatus, ToolAction, new_id, utcnow)


def _fact(task_id: str, key: str, value, version: int, supersedes: str | None = None) -> ContextFact:
    return ContextFact(id=new_id("fct"), task_id=task_id, key=key, value=value, source_id="src",
                       observed_at=utcnow(), status=FactStatus.CONFIRMED, version=version,
                       supersedes=supersedes)


def _inbound(task_id: str, external_id: str) -> InboundEvent:
    return InboundEvent(id=new_id("inb"), source="demo", external_id=external_id, task_id=task_id,
                        provider_id="provider_a", text="hello", received_at=utcnow())


def _proposal(task_id: str, provider_id: str = "provider_b", cents: int = 14500) -> Proposal:
    now = utcnow()
    return Proposal(task_id=task_id, provider_id=provider_id, provider_name="Bayside",
                    service="dishwasher_repair", slot_start=now, slot_end=now,
                    visit_charge_cents=cents, fee_scope="diagnostic_visit_including_travel",
                    cancellation_terms="free >12h", terms_version=1, source_fact_ids=["fct_x"])


def test_create_task_roundtrip(task):
    got = repo.get_task(task.id)
    assert got == task and got.status == TaskStatus.DRAFT
    assert got.constraints.window_start.tzinfo is not None
    assert [p.id for p in repo.get_providers(task.id)] == ["provider_a", "provider_b"]
    assert repo.get_provider(task.id, "provider_b").name == "Bayside Appliance Service"
    assert [e.type for e in repo.list_timeline(task.id)] == ["task.created"]
    with pytest.raises(repo.NotFound):
        repo.get_task("tsk_missing")


def test_fact_versions_persist_across_reconnect(task, fresh_db):
    key = "provider_a.visit_charge_cents"
    v1 = repo.insert_fact(_fact(task.id, key, 12000, 1))
    v2 = repo.insert_fact(_fact(task.id, key, 19000, 2, supersedes=v1.id))
    repo.set_fact_status(v1.id, FactStatus.SUPERSEDED)

    db._engine.dispose()
    db._engine = None
    db.init_db(fresh_db)   # fresh engine on the same file

    assert repo.get_active_fact(task.id, key).id == v2.id
    assert [f.value for f in repo.list_facts(task.id, "provider_a.")] == [19000]
    every = repo.list_facts(task.id, "provider_a.", include_inactive=True)
    assert [(f.version, f.status) for f in every] == [(1, FactStatus.SUPERSEDED),
                                                      (2, FactStatus.CONFIRMED)]
    assert every[1].supersedes == v1.id
    with pytest.raises(IntegrityError):  # (task, key, version) is unique
        repo.insert_fact(_fact(task.id, key, 1, 2))


def test_record_inbound_dedup_concurrent(task):
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: repo.record_inbound(_inbound(task.id, "ext-1")), range(16)))
    assert sum(created for _, created in results) == 1
    assert len({ev.id for ev, _ in results}) == 1
    assert len(repo.list_inbound(task.id)) == 1
    # same external_id, different source -> distinct event
    other = _inbound(task.id, "ext-1").model_copy(update={"source": "fixture"})
    assert repo.record_inbound(other)[1] is True


def test_inbound_processing(task):
    ev, _ = repo.record_inbound(_inbound(task.id, "ext-2"))
    assert [e.id for e in repo.list_unprocessed_inbound(task.id)] == [ev.id]
    repo.mark_inbound_processed(ev.id)
    assert repo.list_unprocessed_inbound(task.id) == []


def test_timeline_seq_strictly_increasing_under_concurrency(task):
    with ThreadPoolExecutor(max_workers=8) as pool:
        list(pool.map(lambda i: repo.emit(task.id, "error", f"e{i}", {"i": i}), range(40)))
    seqs = [e.seq for e in repo.list_timeline(task.id)]
    assert seqs == list(range(1, 42))       # task.created + 40
    assert [e.seq for e in repo.list_timeline(task.id, after_seq=39)] == [40, 41]
    assert [e.seq for e in repo.list_timeline(task.id, last=3)] == [39, 40, 41]


async def test_emit_publishes_to_subscribers(task):
    q = repo.subscribe(task.id)
    try:
        ev = await asyncio.to_thread(repo.emit, task.id, "message.sent", "sent", {"provider_id": "a"})
        got = await asyncio.wait_for(q.get(), timeout=2)
        assert got == ev and got.at.tzinfo is not None
    finally:
        repo.unsubscribe(task.id, q)


def test_approvals_lifecycle_and_invalidation(task):
    a1 = repo.create_approval_request(_proposal(task.id, "provider_a", 12000))
    assert a1.proposal_hash == a1.proposal.compute_hash()
    assert repo.get_latest_approval(task.id).id == a1.id
    repo.decide_approval(a1.id, "approved", "demo_user")
    with pytest.raises(ValueError):
        repo.decide_approval(a1.id, "rejected", "demo_user")

    invalidated = repo.invalidate_approvals(task.id, "price changed")
    assert [a.id for a in invalidated] == [a1.id]
    assert repo.get_approval(a1.id).status == "invalidated"
    ev = repo.list_timeline(task.id)[-1]
    assert ev.type == "approval.invalidated" and ev.data["approval_id"] == a1.id

    a2 = repo.create_approval_request(_proposal(task.id))
    assert repo.get_latest_approval(task.id).id == a2.id
    assert [a.id for a in repo.list_approvals(task.id)] == [a1.id, a2.id]
    assert repo.invalidate_approvals(task.id, "noop") != []      # a2 was requested
    assert repo.invalidate_approvals(task.id, "noop") == []


def test_actions_unique_key_and_update(task):
    a = ToolAction(id=new_id("act"), task_id=task.id, step_id="stp_1", adapter="fixture_browser",
                   operation="submit_booking", idempotency_key="k1", request={}, status="started",
                   started_at=utcnow())
    repo.save_action(a)
    repo.save_action(a.model_copy(update={"status": "succeeded", "finished_at": utcnow()}))
    got = repo.get_action_by_key("k1")
    assert got.status == "succeeded" and got.finished_at.tzinfo == timezone.utc
    assert repo.count_actions(task.id) == 1
    with pytest.raises(IntegrityError):
        repo.save_action(a.model_copy(update={"id": new_id("act")}))


def test_steps_roundtrip(task):
    now = utcnow()
    st = PlanStep(id=new_id("stp"), task_id=task.id, kind=StepKind.SEND_INQUIRY,
                  provider_id="provider_a", idempotency_key=f"{task.id}:send_inquiry:provider_a",
                  created_at=now, updated_at=now)
    repo.save_step(st)
    repo.save_step(st.model_copy(update={"attempts": 1, "result": {"at": now}}))
    got = repo.get_step(st.id)
    assert got.attempts == 1 and got.kind == StepKind.SEND_INQUIRY
    assert [s.id for s in repo.list_steps(task.id)] == [st.id]


def test_evidence_saved_with_file(task, tmp_path):
    ev = save_evidence(task.id, "screenshot", "fixture_browser", is_fixture=True,
                       data=b"png-bytes", ext="png", mime_type="image/png")
    got = repo.get_evidence(ev.id)
    assert got.sha256 and got.uri == f"{task.id}/{ev.id}.png"
    assert (tmp_path / "artifacts" / got.uri).read_bytes() == b"png-bytes"
    assert [e.id for e in repo.list_evidence(task.id, kind="screenshot")] == [ev.id]
    assert repo.list_evidence(task.id, kind="message_in") == []


def test_find_task_by_handle_ignores_terminal(task):
    assert repo.find_task_by_handle("fixture:provider_b") == (task.id, "provider_b")
    assert repo.find_task_by_handle("nobody") is None
    repo.set_status(task.id, TaskStatus.CANCELLED, "user cancelled")
    assert repo.find_task_by_handle("fixture:provider_b") is None
    assert repo.list_active_tasks() == []


def test_llm_counter(task):
    assert repo.get_llm_calls(task.id) == 0
    repo.incr_llm_calls(task.id)
    assert repo.incr_llm_calls(task.id) == 2
