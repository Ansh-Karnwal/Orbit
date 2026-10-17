"""Capture the approved booking intent before a browser action.

The coordinator calls this once it has built the shared BookingRequest. Keeping
the intent separate from portal content lets the read-only verifier check the
approval/reference link without extending any shared schema.
"""
from app.core import repo
from app.core.evidence import save_evidence
from app.core.schemas import BookingRequest, EvidenceArtifact
from app.context.proposals import approval_still_valid


def record_booking_request(request: BookingRequest) -> EvidenceArtifact:
    task = repo.get_task(request.task_id)
    approval = repo.get_latest_approval(task.id)
    valid, reason = approval_still_valid(task.id)
    if (not valid or approval is None or approval.status != "approved"
            or approval.id != request.approval_id or approval.decided_at is None):
        raise ValueError("A current granted approval is required: " + reason)
    if request.proposal.compute_hash() != approval.proposal_hash:
        raise ValueError("Booking request differs from the approved proposal")
    if not request.orbit_ref.strip() or request.orbit_ref != request.orbit_ref.strip():
        raise ValueError("A nonempty, exact booking reference is required")
    for artifact in repo.list_evidence(task.id, kind="browser_trace"):
        if artifact.source != "orbit":
            continue
        raw = artifact.extracted.get("booking_request")
        if not isinstance(raw, dict) or raw.get("approval_id") != approval.id:
            continue
        if raw.get("orbit_ref") != request.orbit_ref:
            raise ValueError("This approval already has a different booking reference; reconcile it before retrying")
        if raw.get("proposal") != request.proposal.model_dump(mode="json"):
            raise ValueError("Recorded booking request has inconsistent approved terms")
        return artifact
    # Customer contact data is unnecessary for independent verification.
    data = request.model_dump(mode="json", exclude={"customer_name", "customer_contact"})
    return save_evidence(task.id, "browser_trace", "orbit", is_fixture=task.mode == "fixture",
                         extracted={"booking_request": data})
