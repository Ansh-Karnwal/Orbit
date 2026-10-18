"""Pure decisions shared by the coordinator-facing layer and read-only verifier."""
from app.core.schemas import FactStatus, Proposal, utcnow
from app.context.conflicts import conflicts_for, current_facts
from app.context.values import local_window, money, slot_pairs


def eligibility_for(task, providers, facts) -> dict[str, list[str]]:
    active = current_facts(facts)
    conflicts = conflicts_for(task.constraints, providers, facts)
    result = {}
    labels = {"service_supported": "Service support not confirmed", "visit_charge_cents": "Total visit charge not provided",
              "fee_scope": "Visit fee scope not provided", "slots_offered": "Appointment slots not provided",
              "cancellation_terms": "Cancellation terms not provided"}
    for p in providers:
        pf = {k.split(".", 1)[1]: f for k, f in active.items() if k.startswith(p.id + ".")}
        reasons = []
        if not pf or ("no_reply" in pf and pf["no_reply"].value is True):
            reasons.append("No reply")
        for conflict in conflicts:
            if conflict.provider_id != p.id:
                continue
            if conflict.kind == "budget_violation":
                reasons.append(f"Over budget: {money(pf['visit_charge_cents'].value)} > {money(task.constraints.max_visit_charge_cents)}")
            elif conflict.kind == "window_violation":
                location = "portal appointment" if conflict.key.endswith(".portal_slots") else "provider-offered appointment"
                reasons.append(f"No {location} inside {local_window(task.constraints)}")
            elif conflict.kind == "missing_required":
                reasons.append(labels.get(conflict.key.split(".", 1)[1], conflict.detail))
            elif conflict.kind == "contradiction":
                reasons.append(conflict.detail)
        if "service_supported" in pf and pf["service_supported"].value is not True:
            reasons.append("Provider does not support this service")
        for field in labels:
            if field == "cancellation_terms" and not task.constraints.require_cancellation_terms:
                continue
            if field not in pf:
                reasons.append(labels[field])
            elif pf[field].status != FactStatus.CONFIRMED:
                reasons.append(f"{field.replace('_', ' ')} is not confirmed")
        scope = pf.get("fee_scope")
        if scope and scope.value in {"", "unknown", "diagnostic_visit_excluding_travel"}:
            reasons.append("Total visit charge and fee scope including travel are not confirmed")
        result[p.id] = list(dict.fromkeys(reasons))
    return result


def proposal_for(task, provider, facts, providers=None) -> Proposal | None:
    providers = providers or [provider]
    if eligibility_for(task, providers, facts)[provider.id]:
        return None
    pf = {k.split(".", 1)[1]: f for k, f in current_facts(facts).items() if k.startswith(provider.id + ".")}
    slots = slot_pairs(pf["slots_offered"].value)
    if "portal_slots" in pf:
        slots &= slot_pairs(pf["portal_slots"].value)
    eligible_slots = sorted((a, b) for a, b in slots if task.constraints.window_start <= a < b <= task.constraints.window_end)
    if not eligible_slots:
        return None
    used = [f for key, f in sorted(pf.items()) if key != "no_reply"]
    return Proposal(task_id=task.id, provider_id=provider.id, provider_name=provider.name, service=task.constraints.service,
                    slot_start=eligible_slots[0][0], slot_end=eligible_slots[0][1],
                    visit_charge_cents=pf["visit_charge_cents"].value, fee_scope=pf["fee_scope"].value,
                    cancellation_terms=pf["cancellation_terms"].value if "cancellation_terms" in pf else "",
                    repair_cost_known=pf["repair_cost_known"].value if "repair_cost_known" in pf else False,
                    terms_version=max(f.version for f in used), source_fact_ids=[f.id for f in used])


def approval_validity(task, providers, facts, approval) -> tuple[bool, str]:
    if approval is None:
        return False, "No approval requested"
    if approval.task_id != task.id or approval.proposal.task_id != task.id:
        return False, "Approval belongs to a different task"
    if approval.status not in {"requested", "approved"}:
        return False, f"Approval is {approval.status}"
    if approval.expires_at and approval.expires_at <= utcnow():
        return False, "expired"
    if approval.proposal.compute_hash() != approval.proposal_hash:
        return False, "Approval proposal hash is inconsistent"
    provider = next((p for p in providers if p.id == approval.proposal.provider_id), None)
    if provider is None:
        return False, "Approved provider no longer exists"
    current = current_facts(facts)
    price = current.get(f"{provider.id}.visit_charge_cents")
    if price and price.value != approval.proposal.visit_charge_cents:
        return False, f"visit charge changed {money(approval.proposal.visit_charge_cents)} → {money(price.value)}"
    rebuilt = proposal_for(task, provider, facts, providers)
    if rebuilt is None:
        reasons = eligibility_for(task, providers, facts)[provider.id]
        return False, "Provider now ineligible: " + "; ".join(reasons or ["No jointly offered and bookable slot"])
    if rebuilt.compute_hash() != approval.proposal_hash:
        for field in ("provider_id", "provider_name", "service", "slot_start", "slot_end", "visit_charge_cents", "fee_scope", "cancellation_terms", "repair_cost_known", "terms_version", "source_fact_ids"):
            if getattr(rebuilt, field) != getattr(approval.proposal, field):
                return False, f"{field.replace('_', ' ')} changed"
        return False, "Proposal hash changed"
    return True, "Approval matches current proposal"
