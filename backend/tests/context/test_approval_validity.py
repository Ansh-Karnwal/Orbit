from datetime import timedelta

import pytest

pytest.importorskip("app.core.schemas", reason="Waiting for Victor's CP0")
from app.core.schemas import utcnow
from app.context.facts import ingest_fact
from app.context.proposals import approval_still_valid, build_proposal


def test_price_change_invalidates_exact_terms(memory_repo):
    memory_repo.seed_provider()
    memory_repo.approve(build_proposal("tsk_test", "provider_a"))
    assert approval_still_valid("tsk_test")[0]
    ingest_fact("tsk_test", "provider_a.visit_charge_cents", 19000, source_id=memory_repo.source())
    valid, reason = approval_still_valid("tsk_test")
    assert not valid
    assert "visit charge changed $120.00 → $190.00" in reason


def test_unchanged_b_valid_and_expiration_checked(memory_repo):
    memory_repo.seed_provider("provider_b", 14500)
    approval = memory_repo.approve(build_proposal("tsk_test", "provider_b"))
    assert approval_still_valid("tsk_test")[0]
    memory_repo.approvals[-1] = approval.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
    assert approval_still_valid("tsk_test") == (False, "expired")


@pytest.mark.parametrize("field,value", [("fee_scope", "flat_repair"), ("cancellation_terms", "No refunds"),
                                         ("slots_offered", [{"start": "2026-10-20T23:00:00Z", "end": "2026-10-21T00:00:00Z"}])])
def test_other_material_changes_invalidate(memory_repo, field, value):
    memory_repo.seed_provider()
    memory_repo.approve(build_proposal("tsk_test", "provider_a"))
    ingest_fact("tsk_test", "provider_a." + field, value, source_id=memory_repo.source())
    assert approval_still_valid("tsk_test")[0] is False


def test_invalidated_approval_is_never_revived(memory_repo):
    memory_repo.seed_provider()
    memory_repo.approve(build_proposal("tsk_test", "provider_a"), status="invalidated")
    assert approval_still_valid("tsk_test") == (False, "Approval is invalidated")
