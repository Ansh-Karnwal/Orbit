"""Phase 8: Sentry reporting — tagged with task/step, scrubbed of PII and message bodies, and
silent for business outcomes. Uses an in-memory transport: nothing leaves the process."""
from __future__ import annotations

import json
import asyncio
from datetime import timedelta
from unittest.mock import AsyncMock

import pytest
import sentry_sdk
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from app.core import approvals, repo, telemetry
from app.core.api import views
from app.core.schemas import ApprovalDecisionIn, StepKind as K, TaskStatus as S
from app.main import app, lifespan
from tests.core.fakes import A1, B1, to_approval_for_a, ticks

FAKE_DSN = "https://public@sentry.invalid/1"


class MemoryTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []
        self.transactions: list[dict] = []
        self.logs: list[dict] = []

    def capture_envelope(self, envelope):
        ev = envelope.get_event()
        if ev is not None:
            self.events.append(ev)
        transaction = envelope.get_transaction_event()
        if transaction is not None:
            self.transactions.append(transaction)
        for item in envelope.items:
            if item.type == "log":
                self.logs.extend(json.loads(item.get_bytes())["items"])


@pytest.fixture
def sentry():
    t = MemoryTransport()
    assert telemetry.init(FAKE_DSN, transport=t)
    yield t
    telemetry.shutdown()


def _blob(ev: dict) -> str:
    return json.dumps(ev, default=str)


def test_disabled_without_dsn():
    assert telemetry.init("") is False
    telemetry.step_failed("tsk_x", None, "e", exc=None, retrying=False)   # no-op, no error


async def test_shutdown_delivers_the_final_log_batch(sentry, monkeypatch):
    monkeypatch.setattr("app.main.db.init_db", lambda: None)
    monkeypatch.setattr("app.main.recovery.recover", lambda: None)
    monkeypatch.setattr("app.main.worker.start", AsyncMock())
    monkeypatch.setattr("app.main.worker.stop", AsyncMock())
    async with lifespan(app):
        telemetry.record("shutdown.probe", "tsk_shutdown")
    assert any(item["body"] == "shutdown.probe" for item in sentry.logs)


def test_scrub_strips_pii():
    ev = telemetry.scrub({
        "request": {"method": "POST", "url": "http://x/tasks/1/approvals?token=abc",
                    "headers": {"Authorization": "Bearer sk-live-123456789"},
                    "cookies": {"s": "1"}, "data": {"text": "hi"}, "query_string": "token=abc"},
        "user": {"email": "a@b.co"},
        "message": "call +13105551234 or mail a.b@example.com",
        "extra": {"text": "SECRET BODY", "handle": "+13105551234", "ok": "fine"},
        "breadcrumbs": {"values": [{"message": "x", "data": {"text": "SECRET BODY"}}]},
    })
    assert ev["request"] == {"method": "POST", "url": "http://x/tasks/1/approvals"}
    assert "user" not in ev
    blob = _blob(ev)
    for leaked in ("SECRET BODY", "13105551234", "a.b@example.com", "sk-live", "token=abc"):
        assert leaked not in blob
    assert ev["extra"]["ok"] == "fine"


async def test_portal_down_is_reported_with_task_tags_then_recovers(task, env, sentry):
    env.portal.read_fail_next = 1                        # portal "down" for one read
    await to_approval_for_a(task.id)
    ra, = [s for s in repo.list_steps(task.id) if s.kind == K.READ_AVAILABILITY]
    assert ra.state.value == "pending"                   # backing off, not blocked

    failed, = sentry.events
    assert failed["level"] == "warning"
    assert failed["tags"]["task_id"] == task.id and failed["tags"]["step_kind"] == "read_availability"
    assert failed["tags"]["retrying"] == "true" and failed["tags"]["provider_id"] == "provider_a"
    assert failed["exception"]["values"][-1]["type"] == "ConnectionError"

    repo.save_step(ra.model_copy(update={"not_before": ra.not_before - timedelta(seconds=60)}))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.AWAITING_APPROVAL
    recovered = sentry.events[-1]
    assert recovered["level"] == "info" and "recovered after 2 attempts" in recovered["message"]
    assert recovered["tags"]["task_id"] == task.id

    for ev in sentry.events:                             # no message bodies or locals anywhere
        blob = _blob(ev)
        assert A1[:30] not in blob and B1[:30] not in blob
        for frame in ev.get("exception", {}).get("values", [{}])[-1].get("stacktrace", {}).get("frames", []):
            assert "vars" not in frame


async def test_business_outcomes_are_not_reported(task, env, sentry):
    env.portal.submit_mode = "mismatch"                  # verification FAIL -> BLOCKED
    await to_approval_for_a(task.id)
    a = repo.get_latest_approval(task.id)
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.BLOCKED
    assert sentry.events == []


async def test_ambiguous_booking_exception_is_reported(task, env, sentry):
    env.portal.submit_mode = "timeout_booked"
    await to_approval_for_a(task.id)
    a = repo.get_latest_approval(task.id)
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))
    await ticks(task.id, 3)
    assert repo.get_task(task.id).status == S.COMPLETED
    ev, = sentry.events
    assert ev["level"] == "error" and ev["tags"]["step_kind"] == "submit_booking"
    assert ev["exception"]["values"][-1]["type"] == "TimeoutError"


def test_unhandled_api_error_is_scrubbed(sentry, monkeypatch, task):
    def boom(task_id):
        raise RuntimeError("view exploded for +13105551234")
    monkeypatch.setattr("app.core.api.tasks.build_view", boom)
    client = TestClient(app, raise_server_exceptions=False)
    r = client.get(f"/tasks/{task.id}?secret=1", headers={"Authorization": "Bearer sk-live-123456789"})
    assert r.status_code == 500
    ev = sentry.events[-1]
    exc = ev["exception"]["values"][-1]
    assert exc["type"] == "RuntimeError" and exc["value"] == "view exploded for [phone]"
    assert set(ev["request"]) <= {"method", "url"} and "?" not in ev["request"].get("url", "")
    # runtime data only: frames carry source-code context (this file's literals), not data
    for frame in exc.get("stacktrace", {}).get("frames", []):
        assert "vars" not in frame
        for k in ("pre_context", "context_line", "post_context"):
            frame.pop(k, None)
    blob = _blob(ev)
    assert "13105551234" not in blob and "sk-live" not in blob and "secret=1" not in blob


async def test_logs_link_availability_and_step_timings_to_workflow_traces(task, env, sentry):
    await to_approval_for_a(task.id)
    sentry_sdk.flush(timeout=2)
    checks = [item for item in sentry.logs if item["body"] == "availability.checked"]
    assert checks
    check = checks[0]
    values = {key: value["value"] for key, value in check["attributes"].items()}
    assert values["task_id"] == task.id and values["provider_id"] == "provider_a"
    assert values["within_window_count"] == values["matching_count"] == 1
    assert values["portal_count"] == 1 and values["reason_code"] == "bookable"
    trace = next(transaction for transaction in sentry.transactions
                 if transaction["contexts"]["trace"]["trace_id"] == check["trace_id"])
    assert trace["transaction"] == "orbit.workflow.tick"
    span = next(span for span in trace["spans"] if span["span_id"] == check["span_id"])
    assert span["op"] == "orbit.step" and span["data"]["step_kind"] == "read_availability"
    assert any(item["body"] == "workflow.step.finished" for item in sentry.logs)
    blob = _blob({"logs": sentry.logs, "traces": sentry.transactions})
    assert A1 not in blob and B1 not in blob


async def test_missing_portal_slots_are_logged_without_becoming_an_error(task, env, sentry):
    original = env.portal.read_availability

    async def no_slots(*args, **kwargs):
        result = await original(*args, **kwargs)
        return result.model_copy(update={"slots": []})

    env.portal.read_availability = no_slots
    await to_approval_for_a(task.id)
    sentry_sdk.flush(timeout=2)
    checks = [item for item in sentry.logs if item["body"] == "availability.checked"]
    assert checks and sentry.events == []
    attrs = checks[0]["attributes"]
    assert attrs["within_window_count"]["value"] == 1
    assert attrs["portal_count"]["value"] == attrs["matching_count"]["value"] == 0
    assert attrs["reason_code"]["value"] == "no_matching_portal_slot"


async def test_parallel_tasks_keep_trace_and_log_context_separate(task, env, sentry):
    from app.core.api.demo import resolve_seed
    from app.core import coordinator
    other = repo.create_task(resolve_seed("fixture"))
    await asyncio.gather(coordinator.tick(task.id), coordinator.tick(other.id))
    sentry_sdk.flush(timeout=2)
    traces = {t["contexts"]["trace"]["trace_id"]: t for t in sentry.transactions}
    for item in sentry.logs:
        if item["body"] != "workflow.step.finished":
            continue
        task_id = item["attributes"]["task_id"]["value"]
        assert traces[item["trace_id"]]["tags"]["task_id"] == task_id
    assert {t["tags"]["task_id"] for t in traces.values()} == {task.id, other.id}


def test_workspace_trace_has_no_repeated_task_provider_or_fact_queries(task, sentry):
    response = TestClient(app).get(f"/tasks/{task.id}?secret=untrusted", headers={"X-Api-Key": "secret-value"})
    assert response.status_code == 200
    transaction = sentry.transactions[-1]
    queries = [span["description"] for span in transaction["spans"]
               if span["op"] == "db" and span.get("description", "").startswith("SELECT")]
    for table in ("tasks", "providers", "facts"):
        assert sum(f"FROM {table} " in query or f"FROM {table}\n" in query for query in queries) == 1
    assert transaction["tags"]["task_id"] == task.id
    assert "secret=untrusted" not in _blob(transaction) and "secret-value" not in _blob(transaction)
    count = len(sentry.transactions)
    health = TestClient(app).get("/health")
    assert health.json()["observability"]["logs"] is True
    assert len(sentry.transactions) == count            # no health-check sampling noise


def test_trace_and_log_filters_keep_metrics_and_drop_sensitive_fields():
    result = telemetry.scrub_transaction({
        "contexts": {"trace": {"trace_id": "123", "data": {"task_id": "tsk_1", "text": A1}}},
        "spans": [{"op": "http.client", "description": "GET https://user:password@example.org/slots?key=secret",
                   "data": {"portal_count": 0, "headers": {"Authorization": "secret"}, "text": B1}}],
        "user": {"email": "a@example.org"},
    })
    assert result["contexts"]["trace"]["data"] == {"task_id": "tsk_1"}
    assert result["spans"][0]["data"] == {"portal_count": 0}
    assert result["spans"][0]["description"] == "GET https://example.org/slots"
    item = telemetry.scrub_log({"body": "call +13105551234", "attributes": {
        "logger.name": "orbit.observability", "task_id": "tsk_1", "matching_count": 0,
        "text": A1, "customer_name": "Private person", "sentry.message.parameter.0": B1}})
    assert item["body"] == "call [phone]"
    assert set(item["attributes"]) == {"logger.name", "task_id", "matching_count"}
    assert telemetry.scrub_log({"body": A1, "attributes": {"logger.name": "httpx"}}) is None
