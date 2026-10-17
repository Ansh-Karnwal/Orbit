"""CP0 smoke tests: app boots, /health, /demo/seed, contract basics, state machine table."""
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

import pytest
from fastapi.testclient import TestClient

from app.core.api.demo import resolve_seed
from app.core.schemas import TaskStatus, new_id
from app.core.state import ALLOWED, IllegalTransition, check_transition
from app.main import app


def test_health():
    with TestClient(app) as c:
        r = c.get("/health")
    assert r.status_code == 200
    body = r.json()
    assert body["ok"] is True and "photon" in body["integrations"]


def test_seed_resolves_next_tuesday_window():
    # Tuesday 2026-10-20 -> must roll to the following Tuesday.
    seed = resolve_seed("fixture", now=datetime(2026, 10, 20, 18, 0, tzinfo=timezone.utc))
    la = ZoneInfo("America/Los_Angeles")
    start = seed.constraints.window_start.astimezone(la)
    assert start.weekday() == 1 and start.hour == 14 and start.date().isoformat() == "2026-10-27"
    assert seed.constraints.window_end.astimezone(la).hour == 17
    assert seed.constraints.max_visit_charge_cents == 15000
    assert [p.id for p in seed.providers] == ["provider_a", "provider_b"]
    assert seed.providers[0].handle == "fixture:provider_a"


def test_seed_endpoint():
    with TestClient(app) as c:
        r = c.get("/demo/seed")
    assert r.status_code == 200 and r.json()["source"] == "demo_seed"


def test_new_id_prefix():
    assert new_id("tsk").startswith("tsk_") and len(new_id("tsk")) == 20


def test_terminal_states_have_no_exits():
    for s in (TaskStatus.COMPLETED, TaskStatus.FAILED, TaskStatus.CANCELLED):
        assert ALLOWED[s] == set()
    with pytest.raises(IllegalTransition):
        check_transition(TaskStatus.DRAFT, TaskStatus.COMPLETED)
    check_transition(TaskStatus.VERIFYING, TaskStatus.COMPLETED)
