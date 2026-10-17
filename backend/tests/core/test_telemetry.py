"""Phase 8: Sentry reporting — tagged with task/step, scrubbed of PII and message bodies, and
silent for business outcomes. Uses an in-memory transport: nothing leaves the process."""
from __future__ import annotations

import json
from datetime import timedelta

import pytest
from fastapi.testclient import TestClient
from sentry_sdk.transport import Transport

from app.core import approvals, repo, telemetry
from app.core.api import views
from app.core.schemas import ApprovalDecisionIn, StepKind as K, TaskStatus as S
from app.main import app
from tests.core.fakes import A1, B1, to_approval_for_a, ticks

FAKE_DSN = "https://public@sentry.invalid/1"


class MemoryTransport(Transport):
    def __init__(self, options=None):
        super().__init__(options)
        self.events: list[dict] = []

    def capture_envelope(self, envelope):
        ev = envelope.get_event()
        if ev is not None:
            self.events.append(ev)


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
