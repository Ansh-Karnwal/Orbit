"""Evidence-bound final language; no model can inflate the claim level."""
from app.core import repo
from app.core.schemas import VerificationResult, Verdict
from app.context.proposals import approval_still_valid, eligibility
from app.context.values import local_window, money


async def summarize(task_id: str, verification: VerificationResult) -> str:
    if verification.task_id != task_id or verification.verdict != Verdict.PASS:
        raise ValueError("A PASS verification for this task is required")
    task = repo.get_task(task_id)
    approval = repo.get_latest_approval(task_id)
    valid, reason = approval_still_valid(task_id)
    if not valid or approval.status != "approved" or approval.id != verification.approval_id:
        raise ValueError("Current approved terms required: " + reason)
    proposal = approval.proposal
    ids = [eid for p in verification.predicates if p.name == "confirmation_present" and p.passed is True for eid in p.evidence_ids]
    confirmations = [repo.get_evidence(eid) for eid in ids]
    confirmation = next((e for e in confirmations if e.task_id == task_id and e.kind == "portal_confirmation"), None)
    if confirmation is None:
        raise ValueError("Verified portal confirmation is required")
    data = confirmation.extracted.get("confirmation", confirmation.extracted)
    confirmation_id = data.get("confirmation_id")
    if not confirmation_id:
        raise ValueError("Verified confirmation id is missing")
    window = task.constraints.model_copy(update={"window_start": proposal.slot_start, "window_end": proposal.slot_end})
    fixture = " (fixture evidence)" if confirmation.is_fixture else ""
    scope = {"diagnostic_visit_including_travel": "the diagnostic visit including travel",
             "diagnostic_visit_excluding_travel": "the diagnostic visit excluding travel",
             "flat_repair": "the quoted fixed repair"}.get(proposal.fee_scope, proposal.fee_scope)
    summary = f"Booking verified{fixture}: {proposal.provider_name}, {local_window(window)}. {money(proposal.visit_charge_cents)} covers {scope}. "
    summary += f"Cancellation terms: {proposal.cancellation_terms.rstrip('.') or 'not required by the user'}. Confirmation: {confirmation_id}."
    disqualified = eligibility(task_id)
    for provider in repo.get_providers(task_id):
        reasons = disqualified[provider.id]
        if provider.id != proposal.provider_id and reasons:
            summary += f" {provider.name} was rejected: {'; '.join(reasons)}."
    if not proposal.repair_cost_known:
        summary += f" Parts and labor will be quoted after diagnosis; the {money(proposal.visit_charge_cents)} covers the diagnostic visit only."
    return summary
