from datetime import timedelta

import pytest

pytest.importorskip("app.core.schemas", reason="Waiting for Victor's CP0")
from app.core.schemas import FactStatus, utcnow
from app.context.facts import ingest_fact


def test_source_required_and_evidence_must_exist(memory_repo):
    for source in ("", "made-up", "evd_missing"):
        with pytest.raises(ValueError):
            ingest_fact("tsk_test", "provider_a.visit_charge_cents", 12000, source_id=source)


def test_identical_values_do_not_create_versions(memory_repo):
    source = memory_repo.source()
    first = ingest_fact("tsk_test", "provider_a.visit_charge_cents", 12000, source_id=source)
    duplicate = ingest_fact("tsk_test", "provider_a.visit_charge_cents", "12000", source_id=source)
    assert not duplicate.changed
    assert duplicate.fact.id == first.fact.id
    assert len(memory_repo.facts) == 1


def test_price_change_preserves_versions_and_budget_conflict(memory_repo):
    source = memory_repo.source()
    first = ingest_fact("tsk_test", "provider_a.visit_charge_cents", 12000, source_id=source)
    second = ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id=source)
    assert second.fact.version == 2
    assert second.fact.supersedes == first.fact.id
    assert second.superseded.status == FactStatus.SUPERSEDED
    assert memory_repo.facts[0].status == FactStatus.SUPERSEDED
    assert {c.kind for c in second.conflicts} >= {"value_changed", "budget_violation"}


def test_stale_update_cannot_regress_current_fact(memory_repo):
    source = memory_repo.source()
    now = utcnow()
    ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id=source, observed_at=now)
    older = ingest_fact("tsk_test", "provider_a.visit_charge_cents", 12000, source_id=source, observed_at=now - timedelta(minutes=1))
    assert older.fact.status == FactStatus.REJECTED
    assert memory_repo.get_active_fact("tsk_test", "provider_a.visit_charge_cents").value == 19000
    assert older.conflicts[0].kind == "contradiction"


def test_money_is_never_float(memory_repo):
    with pytest.raises(ValueError):
        ingest_fact("tsk_test", "provider_a.visit_charge_cents", 120.0, source_id=memory_repo.source())


def test_slot_normalization_is_utc_sorted_and_deduplicated(memory_repo):
    fact = ingest_fact("tsk_test", "provider_a.slots_offered", [
        {"start": "2026-10-20T15:00:00-07:00", "end": "2026-10-20T16:00:00-07:00"},
        {"start": "2026-10-20T22:00:00Z", "end": "2026-10-20T23:00:00Z"}], source_id=memory_repo.source()).fact
    assert fact.value == [{"start": "2026-10-20T22:00:00Z", "end": "2026-10-20T23:00:00Z"}]


def test_evidence_for_another_task_cannot_source_a_fact(memory_repo):
    source_id = memory_repo.source()
    memory_repo.evidence[-1] = memory_repo.evidence[-1].model_copy(update={"task_id": "tsk_other"})
    with pytest.raises(ValueError, match="belong to this task"):
        ingest_fact("tsk_test", "provider_a.visit_charge_cents", 12000, source_id=source_id)
    assert memory_repo.facts == []


def test_inbound_lookup_is_validated_when_available(memory_repo):
    from app.core.schemas import InboundEvent, new_id
    event = InboundEvent(id=new_id("inb"), source="fixture", external_id="quote:one", task_id="tsk_test",
                         provider_id="provider_a", text="$120 visit", received_at=utcnow())
    memory_repo.record_inbound(event)
    assert ingest_fact("tsk_test", "provider_a.visit_charge_cents", 12000, source_id=event.id).fact.source_id == event.id
    with pytest.raises(ValueError, match="does not exist"):
        ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id="inb_unknown")
