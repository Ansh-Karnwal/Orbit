import pytest

from app.core.schemas import BookingRequest
from app.context.booking import record_booking_request
from app.context.facts import ingest_fact
from app.context.proposals import build_proposal


def request_for(fake, status="approved"):
    fake.seed_provider("provider_b", 14500)
    proposal = build_proposal("tsk_test", "provider_b")
    approval = fake.approve(proposal, status=status)
    return BookingRequest(task_id="tsk_test", proposal=proposal, approval_id=approval.id,
                          orbit_ref="orbit:booking:one", customer_contact="private@example.invalid")


def test_recorded_request_binds_approval_and_omits_customer_contact(memory_repo):
    request = request_for(memory_repo)
    artifact = record_booking_request(request)
    assert artifact.source == "orbit" and artifact.is_fixture
    assert artifact.claim_level is None
    raw = artifact.extracted["booking_request"]
    assert raw["approval_id"] == request.approval_id
    assert raw["orbit_ref"] == request.orbit_ref
    assert raw["proposal"] == request.proposal.model_dump(mode="json")
    assert "customer_contact" not in raw and "customer_name" not in raw


def test_retry_reuses_original_request_evidence(memory_repo):
    request = request_for(memory_repo)
    first = record_booking_request(request)
    before = len(memory_repo.evidence)
    assert record_booking_request(request).id == first.id
    assert len(memory_repo.evidence) == before


def test_same_approval_cannot_create_another_reference(memory_repo):
    request = request_for(memory_repo)
    record_booking_request(request)
    with pytest.raises(ValueError, match="different booking reference"):
        record_booking_request(request.model_copy(update={"orbit_ref": "orbit:booking:two"}))


@pytest.mark.parametrize("status", ["requested", "rejected", "invalidated", "expired"])
def test_only_granted_approval_can_record_booking_intent(memory_repo, status):
    request = request_for(memory_repo, status=status)
    before = len(memory_repo.evidence)
    with pytest.raises(ValueError, match="current granted approval"):
        record_booking_request(request)
    assert len(memory_repo.evidence) == before


def test_changed_terms_cannot_record_old_request(memory_repo):
    request = request_for(memory_repo)
    ingest_fact("tsk_test", "provider_b.visit_charge_cents", 19000, source_id=memory_repo.source())
    with pytest.raises(ValueError, match="visit charge changed"):
        record_booking_request(request)
