"""Deterministic three-valued predicates. No model, adapters or database calls."""
from app.core.schemas import ConfirmationExtract, FactStatus, PredicateResult, Verdict
from app.context.conflicts import current_facts
from app.context.decisions import approval_validity
from app.context.values import cents, instant, money


def verdict_for(predicates: list[PredicateResult]) -> Verdict:
    if any(p.passed is False for p in predicates):
        return Verdict.FAIL
    if any(p.passed is None for p in predicates):
        return Verdict.INSUFFICIENT_EVIDENCE
    return Verdict.PASS


def confirmation_from(evidence) -> ConfirmationExtract | None:
    data = evidence.extracted.get("confirmation", evidence.extracted)
    try:
        if type(data.get("visit_charge_cents")) is not int:
            return None
        cents(data["visit_charge_cents"])
        confirmation = ConfirmationExtract.model_validate(data)
        for key in ("confirmation_id", "provider_id", "service", "orbit_ref"):
            if not getattr(confirmation, key).strip():
                return None
        if instant(confirmation.slot_start) >= instant(confirmation.slot_end):
            return None
        return confirmation
    except (ValueError, TypeError, KeyError, AttributeError):
        return None


def evaluate(task, providers, facts, approval, confirmation=None, evidence=None, expected_orbit_ref=None) -> list[PredicateResult]:
    proposal = approval.proposal if approval else None
    constraints = task.constraints
    ids = [evidence.id] if evidence else []
    fixture = " (fixture evidence)" if evidence and evidence.is_fixture else ""
    predicates = []
    def add(name, passed, detail, evidence_ids=None):
        predicates.append(PredicateResult(name=name, passed=passed, detail=detail + fixture,
                                           evidence_ids=ids if evidence_ids is None else evidence_ids))
    def confirmed(name, predicate, success, failure):
        if confirmation is None or proposal is None:
            add(name, None, "Confirmation or approved proposal is missing")
        else:
            passed = bool(predicate())
            add(name, passed, success if passed else failure)
    confirmed("provider_identified", lambda: confirmation.provider_id == proposal.provider_id,
              "Confirmation identifies the approved provider", "Confirmation provider differs from approval")
    confirmed("service_matches", lambda: confirmation.service == constraints.service == proposal.service,
              "Service matches user constraints and approval", "Confirmation service differs from requested service")
    confirmed("slot_within_window", lambda: constraints.window_start <= instant(confirmation.slot_start) < instant(confirmation.slot_end) <= constraints.window_end,
              "Confirmed slot is inside the requested window", "Confirmed slot is outside the requested window")
    confirmed("charge_within_budget", lambda: 0 <= confirmation.visit_charge_cents <= constraints.max_visit_charge_cents,
              "Confirmed charge is within budget", "Confirmed charge exceeds " + money(constraints.max_visit_charge_cents))
    active = current_facts(facts)
    scope = active.get(f"{proposal.provider_id}.fee_scope") if proposal else None
    charge = active.get(f"{proposal.provider_id}.visit_charge_cents") if proposal else None
    clear = bool(proposal and scope and scope.status == FactStatus.CONFIRMED and scope.value == proposal.fee_scope
                 and proposal.fee_scope not in {"", "unknown", "diagnostic_visit_excluding_travel"})
    if constraints.require_diagnostic_fee_confirmed:
        clear = clear and bool(charge and charge.status == FactStatus.CONFIRMED and charge.value == proposal.visit_charge_cents
                               and proposal.fee_scope.startswith("diagnostic_visit"))
    add("fee_scope_clear", clear, "Diagnostic visit fee and scope confirmed" if clear else "Required diagnostic fee or visit scope is unconfirmed", [])
    if not constraints.require_cancellation_terms:
        add("cancellation_terms_present", True, "Cancellation terms not required by user", [])
    elif proposal is None or not proposal.cancellation_terms.strip():
        add("cancellation_terms_present", False, "Approval lacks required cancellation terms", [])
    elif confirmation is None:
        add("cancellation_terms_present", None, "Confirmation cancellation terms unavailable")
    else:
        present = bool(confirmation.cancellation_terms.strip())
        add("cancellation_terms_present", present, "Cancellation terms present in approval and confirmation" if present else "Confirmation lacks cancellation terms")
    valid, reason = approval_validity(task, providers, facts, approval)
    valid = valid and approval.status == "approved"
    add("approval_matches_current_proposal", valid, reason if valid or not approval or approval.status != "requested" else "Approval has not been granted", [])
    if confirmation is None:
        add("confirmation_present", None, "No valid portal confirmation with a confirmation id")
    elif expected_orbit_ref is None:
        add("confirmation_present", None, "Approval-bound booking reference is not available in the shared contract")
    else:
        matched = confirmation.orbit_ref == expected_orbit_ref
        add("confirmation_present", matched, "Portal confirmation matches the approved booking reference" if matched else "Confirmation booking reference differs from the approved request")
    if confirmation is None or proposal is None or expected_orbit_ref is None:
        add("confirmation_consistent", None, "Exact confirmation comparison needs approval, confirmation and the bound booking reference")
    else:
        differences = [name for name in ("provider_id", "service", "slot_start", "slot_end", "visit_charge_cents", "cancellation_terms")
                       if getattr(confirmation, name) != getattr(proposal, name)]
        if confirmation.orbit_ref != expected_orbit_ref:
            differences.append("orbit_ref")
        add("confirmation_consistent", not differences, "Confirmation exactly matches approved terms" if not differences else "Confirmation differs in: " + ", ".join(differences))
    return predicates
