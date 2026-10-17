import pytest

pytest.importorskip("app.core.schemas", reason="Waiting for Victor's CP0")
from app.context.facts import ingest_fact
from app.context.proposals import best_proposal, build_proposal, eligibility


def test_cheapest_then_replan_after_price_increase(memory_repo):
    memory_repo.seed_provider("provider_a", 12000)
    memory_repo.seed_provider("provider_b", 14500)
    assert eligibility("tsk_test")["provider_a"] == []
    assert best_proposal("tsk_test").provider_id == "provider_a"
    ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id=memory_repo.source())
    assert any("Over budget: $190.00 > $150.00" == x for x in eligibility("tsk_test")["provider_a"])
    assert best_proposal("tsk_test").provider_id == "provider_b"


def test_proposal_uses_earliest_offered_portal_intersection(memory_repo):
    memory_repo.seed_provider(slots=[{"start": "2026-10-20T21:30:00Z", "end": "2026-10-20T22:30:00Z"},
                                    {"start": "2026-10-20T23:00:00Z", "end": "2026-10-21T00:00:00Z"}])
    ingest_fact("tsk_test", "provider_a.portal_slots", [{"start": "2026-10-20T23:00:00Z", "end": "2026-10-21T00:00:00Z"}], source_id=memory_repo.source())
    assert build_proposal("tsk_test", "provider_a").slot_start.hour == 23


def test_no_proposal_when_terms_missing_or_no_reply(memory_repo):
    assert build_proposal("tsk_test", "provider_a") is None
    memory_repo.seed_provider()
    ingest_fact("tsk_test", "provider_a.no_reply", True, source_id=memory_repo.source())
    assert build_proposal("tsk_test", "provider_a") is None


def test_proposal_hash_stable_and_binds_every_material_field(memory_repo):
    from datetime import timedelta
    memory_repo.seed_provider()
    proposal = build_proposal("tsk_test", "provider_a")
    assert proposal.compute_hash() == build_proposal("tsk_test", "provider_a").compute_hash()
    changes = {"provider_id": "provider_b", "service": "other_repair", "slot_start": proposal.slot_start + timedelta(minutes=5),
               "slot_end": proposal.slot_end + timedelta(minutes=5), "visit_charge_cents": 13000, "fee_scope": "flat_repair",
               "cancellation_terms": "No cancellation", "terms_version": 2}
    for field, value in changes.items():
        assert proposal.model_copy(update={field: value}).compute_hash() != proposal.compute_hash()
