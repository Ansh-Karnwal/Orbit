import pytest

pytest.importorskip("app.core.schemas", reason="Waiting for Victor's CP0")
from app.core.schemas import PlanStep, StepKind, utcnow
from app.context.assembler import assemble
from app.context.compose import compose_inquiry, compose_followup


def test_inquiry_is_short_and_has_constraints_and_questions(memory_repo):
    inquiry = compose_inquiry("tsk_test", "provider_a")
    assert len(inquiry) <= 480
    for fragment in ("Tuesday Oct 20", "PDT", "$150.00", "travel", "cancellation", "approval", "parts/labor"):
        assert fragment in inquiry


def test_followup_only_asks_missing_fields(memory_repo):
    text = compose_followup("tsk_test", "provider_a", ["cancellation_terms"])
    assert "cancellation" in text
    assert "total diagnostic visit charge" not in text
    assert "appointment slots" not in text


def test_packets_are_provider_scoped_and_exclude_old_facts(memory_repo):
    from app.context.facts import ingest_fact
    memory_repo.seed_provider("provider_a")
    memory_repo.seed_provider("provider_b", 14500)
    ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id=memory_repo.source())
    now = utcnow()
    step = PlanStep(id="stp_test", task_id="tsk_test", kind=StepKind.EXTRACT_QUOTE, provider_id="provider_a",
                    idempotency_key="test", created_at=now, updated_at=now)
    packet = assemble("tsk_test", step)
    assert all(f.key.startswith("provider_a.") for f in packet.facts)
    assert [f.value for f in packet.facts if f.key.endswith("visit_charge_cents")] == [19000]
    assert packet.allowed_scope == ["read_message", "propose_facts"]
    assert 3 <= len(packet.domain_rules) <= 8
    assert "total_visit_charge_usd" in packet.required_output["properties"]
