"""Evidence-bound final language; no model can inflate the claim level."""
from app.core import repo
from app.core.schemas import VerificationResult, Verdict
from app.context.conflicts import current_facts
from app.context.decisions import eligibility_for, open_slots
from app.context.proposals import approval_still_valid, eligibility
from app.context.values import local_window, money

SCOPES = {"diagnostic_visit_including_travel": "diagnostic visit incl. travel",
          "diagnostic_visit_excluding_travel": "diagnostic visit, travel extra",
          "flat_repair": "fixed repair price", "unknown": "scope unclear"}


def provider_summaries(task_id: str) -> dict[str, str]:
    """One deterministic line per provider, built only from active facts (no model)."""
    return provider_summaries_for(repo.get_task(task_id), repo.get_providers(task_id),
                                  repo.list_facts(task_id))


def provider_summaries_for(task, providers, facts) -> dict[str, str]:
    """Pure form for callers that already loaded task/providers/facts (the workspace snapshot)."""
    reasons = eligibility_for(task, providers, facts)
    active = current_facts(facts)
    out = {}
    for p in providers:
        pf = {k.split(".", 1)[1]: f for k, f in active.items() if k.startswith(p.id + ".")}
        quote = {k: v for k, v in pf.items() if k not in {"declined_by_user", "declined_slots"}}
        if not quote:
            out[p.id] = "Waiting for a reply"
            continue
        if "no_reply" in pf and pf["no_reply"].value is True and len(quote) == 1:
            out[p.id] = "No reply"
            continue
        parts = []
        if "visit_charge_cents" in pf:
            scope = SCOPES.get(pf["fee_scope"].value, "") if "fee_scope" in pf else ""
            parts.append(money(pf["visit_charge_cents"].value) + (f" ({scope})" if scope else ""))
        if "slots_offered" in pf:
            n = len(open_slots(task, pf))
            parts.append(f"{n} open time{'s' if n != 1 else ''} in your window")
        if "cancellation_terms" in pf:
            terms = pf["cancellation_terms"].value
            parts.append(terms if len(terms) <= 70 else terms[:67].rstrip() + "…")
        if "repair_cost_known" in pf and pf["repair_cost_known"].value is False:
            parts.append("parts & labor quoted after diagnosis")
        if reasons[p.id]:
            parts.append("Not eligible: " + reasons[p.id][0])
        out[p.id] = " · ".join(parts) or "Replied; no quote details yet"
    return out


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
