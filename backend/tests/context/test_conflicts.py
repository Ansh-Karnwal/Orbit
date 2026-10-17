import pytest

pytest.importorskip("app.core.schemas", reason="Waiting for Victor's CP0")
from app.context.conflicts import detect_conflicts
from app.context.facts import ingest_fact


def test_budget_and_missing_requirements(memory_repo):
    ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id=memory_repo.source())
    conflicts = detect_conflicts("tsk_test")
    assert any(c.kind == "budget_violation" and "$190.00" in c.detail for c in conflicts)
    assert any(c.kind == "missing_required" and c.key.endswith("cancellation_terms") for c in conflicts)


def test_no_missing_required_before_reply(memory_repo):
    assert detect_conflicts("tsk_test") == []


def test_window_and_portal_disagreement(memory_repo):
    memory_repo.seed_provider()
    ingest_fact("tsk_test", "provider_a.portal_slots", [{"start": "2026-10-20T19:00:00Z", "end": "2026-10-20T20:00:00Z"}], source_id=memory_repo.source())
    kinds = {c.kind for c in detect_conflicts("tsk_test")}
    assert {"window_violation", "contradiction"} <= kinds


def test_fee_arithmetic_contradiction(memory_repo):
    memory_repo.seed_provider()
    source = memory_repo.source()
    ingest_fact("tsk_test", "provider_a.extra_fees", [{"name": "trip", "cents": 7000}], source_id=source)
    ingest_fact("tsk_test", "provider_a.visit_charge_cents", 18000, source_id=source)
    assert any(c.kind == "contradiction" and "$190.00" in c.detail for c in detect_conflicts("tsk_test"))
