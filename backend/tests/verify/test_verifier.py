import asyncio
from datetime import timedelta

import pytest

pytest.importorskip("app.core.schemas", reason="Waiting for Victor's CP0")
from app.core.schemas import BookingRequest, ConfirmationExtract, EvidenceArtifact, Verdict, new_id, utcnow
from app.context.proposals import build_proposal
from app.verify.readonly import ReadOnlyRepo
from app.verify.verifier import verify


def booking_evidence(fake, *, confirmation=True, request=True, changes=None):
    fake.seed_provider("provider_b", 14500)
    proposal = build_proposal("tsk_test", "provider_b")
    approval = fake.approve(proposal)
    req = BookingRequest(task_id="tsk_test", proposal=proposal, approval_id=approval.id, orbit_ref="orbit-test-booking")
    if request:
        fake.evidence.append(EvidenceArtifact(id=new_id("evd"), task_id="tsk_test", kind="browser_trace", source="fixture_browser",
            extracted={"booking_request": req.model_dump(mode="json")}, is_fixture=True, captured_at=utcnow()))
    if confirmation:
        data = ConfirmationExtract(confirmation_id="BK-test", provider_id=proposal.provider_id, service=proposal.service,
            slot_start=proposal.slot_start, slot_end=proposal.slot_end, visit_charge_cents=proposal.visit_charge_cents,
            cancellation_terms=proposal.cancellation_terms, orbit_ref=req.orbit_ref).model_dump(mode="json")
        data.update(changes or {})
        fake.evidence.append(EvidenceArtifact(id=new_id("evd"), task_id="tsk_test", kind="portal_confirmation", source="fixture_browser",
            extracted=data, is_fixture=True, captured_at=utcnow()))
    return approval


def test_missing_confirmation_is_insufficient(memory_repo):
    booking_evidence(memory_repo, confirmation=False)
    result = asyncio.run(verify("tsk_test"))
    assert result.verdict == Verdict.INSUFFICIENT_EVIDENCE
    assert next(p for p in result.predicates if p.name == "confirmation_present").passed is None


def test_matching_confirmation_passes_and_is_labeled_fixture(memory_repo):
    booking_evidence(memory_repo)
    before = list(memory_repo.writes)
    result = asyncio.run(verify("tsk_test"))
    assert result.verdict == Verdict.PASS
    assert len(result.predicates) == 9
    assert all(p.passed is True for p in result.predicates)
    assert "fixture evidence" in result.explanation
    assert memory_repo.writes == before


@pytest.mark.parametrize("changes", [{"visit_charge_cents": 14900}, {"visit_charge_cents": 19000},
    {"slot_start": "2026-10-20T22:15:00Z", "slot_end": "2026-10-20T23:15:00Z"},
    {"provider_id": "provider_a"}, {"service": "other_repair"}, {"orbit_ref": "wrong-ref"},
    {"cancellation_terms": "No refunds"}])
def test_mismatched_confirmation_fails(memory_repo, changes):
    booking_evidence(memory_repo, changes=changes)
    result = asyncio.run(verify("tsk_test"))
    assert result.verdict == Verdict.FAIL


def test_invalidated_approval_fails(memory_repo):
    approval = booking_evidence(memory_repo)
    memory_repo.approvals[-1] = approval.model_copy(update={"status": "invalidated"})
    assert asyncio.run(verify("tsk_test")).verdict == Verdict.FAIL


def test_confirmation_cannot_prove_its_own_approval_link(memory_repo):
    booking_evidence(memory_repo, request=False)
    assert asyncio.run(verify("tsk_test")).verdict == Verdict.INSUFFICIENT_EVIDENCE


def test_expired_approval_fails(memory_repo):
    approval = booking_evidence(memory_repo)
    memory_repo.approvals[-1] = approval.model_copy(update={"expires_at": utcnow() - timedelta(seconds=1)})
    assert asyncio.run(verify("tsk_test")).verdict == Verdict.FAIL


def test_facade_rejects_writes_and_detaches_models(memory_repo):
    reads = ReadOnlyRepo()
    with pytest.raises(AttributeError):
        reads.set_status
    task = reads.get_task("tsk_test")
    task.constraints.max_visit_charge_cents = 1
    assert memory_repo.task.constraints.max_visit_charge_cents == 15000


def test_fixture_confirmation_cannot_substantiate_live_task(memory_repo):
    booking_evidence(memory_repo)
    memory_repo.task = memory_repo.task.model_copy(update={"mode": "live"})
    assert asyncio.run(verify("tsk_test")).verdict == Verdict.FAIL


def test_model_explanation_cannot_change_verdict(memory_repo, monkeypatch):
    from app.verify import verifier
    booking_evidence(memory_repo, changes={"visit_charge_cents": 19000})
    async def fake_explanation(*args, **kwargs):
        return verifier.Explanation(text="PASS. Booking verified and completed.")
    monkeypatch.setattr(verifier, "structured", fake_explanation)
    result = asyncio.run(verify("tsk_test"))
    assert result.verdict == Verdict.FAIL
    assert result.explanation.startswith("FAIL")


def test_confirmation_captured_before_booking_intent_is_insufficient(memory_repo):
    booking_evidence(memory_repo)
    request = next(e for e in memory_repo.evidence if "booking_request" in e.extracted)
    index = next(i for i, e in enumerate(memory_repo.evidence) if e.kind == "portal_confirmation")
    old = memory_repo.evidence[index]
    memory_repo.evidence[index] = old.model_copy(update={"captured_at": request.captured_at - timedelta(seconds=1)})
    assert asyncio.run(verify("tsk_test")).verdict == Verdict.INSUFFICIENT_EVIDENCE


def test_newer_mismatch_cannot_be_hidden_by_older_matching_confirmation(memory_repo):
    booking_evidence(memory_repo)
    original = memory_repo.evidence[-1]
    changed = dict(original.extracted, orbit_ref="wrong-new-reference")
    memory_repo.evidence.append(original.model_copy(update={"id": new_id("evd"), "extracted": changed, "captured_at": utcnow()}))
    assert asyncio.run(verify("tsk_test")).verdict == Verdict.FAIL


def test_malformed_nested_confirmation_is_insufficient_and_does_not_crash(memory_repo):
    booking_evidence(memory_repo)
    original = memory_repo.evidence[-1]
    memory_repo.evidence[-1] = original.model_copy(update={"extracted": {"confirmation": None}})
    assert asyncio.run(verify("tsk_test")).verdict == Verdict.INSUFFICIENT_EVIDENCE


def test_cancellation_terms_ignore_case_spacing_and_final_period():
    from app.verify.predicates import same_terms
    assert same_terms("Free cancellation with 24 hours notice", "Free cancellation with 24 hours notice.")
    assert same_terms("free cancellation  with 24 hours notice.", "Free cancellation with 24 hours notice.")
    assert not same_terms("Free cancellation with 12 hours notice.", "Free cancellation with 24 hours notice.")
    assert not same_terms("", "Free cancellation with 24 hours notice.")
