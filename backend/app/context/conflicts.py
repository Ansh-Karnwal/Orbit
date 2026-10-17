"""Deterministic diagnostics over the currently active observations."""
from app.core import repo
from app.core.schemas import Conflict, FactStatus, utcnow
from app.context.domain import load_pack
from app.context.values import instant, money, slot_pairs


def current_facts(facts) -> dict:
    current = {}
    now = utcnow()
    for fact in facts:
        if fact.status not in {FactStatus.CONFIRMED, FactStatus.PROPOSED}:
            continue
        if fact.valid_until and instant(fact.valid_until) <= now:
            continue
        if fact.key not in current or fact.version > current[fact.key].version:
            current[fact.key] = fact
    return current


def conflicts_for(constraints, providers, facts) -> list[Conflict]:
    active = current_facts(facts)
    result = []
    for provider in providers:
        pid = provider.id
        pf = {k.split(".", 1)[1]: f for k, f in active.items() if k.startswith(pid + ".")}
        if not pf:  # Silence before a reply is not yet a missing-fact conflict.
            continue
        def add(kind, field, detail, old_value=None, new_value=None):
            result.append(Conflict(kind=kind, key=f"{pid}.{field}", provider_id=pid,
                                   old_value=old_value, new_value=new_value, detail=detail))
        for field in load_pack().required_facts_for_eligibility:
            if field == "cancellation_terms" and not constraints.require_cancellation_terms:
                continue
            fact = pf.get(field)
            if fact is None or fact.value is None or fact.value == "" or fact.value == []:
                add("missing_required", field, f"{field.replace('_', ' ')} not provided")
        charge = pf.get("visit_charge_cents")
        if charge and charge.value > constraints.max_visit_charge_cents:
            add("budget_violation", "visit_charge_cents",
                f"{money(charge.value)} exceeds the {money(constraints.max_visit_charge_cents)} limit",
                new_value=charge.value)
        offered = slot_pairs(pf["slots_offered"].value) if "slots_offered" in pf else set()
        portal = slot_pairs(pf["portal_slots"].value) if "portal_slots" in pf else None
        for field, slots in (("slots_offered", offered), ("portal_slots", portal)):
            if slots is not None and not any(constraints.window_start <= a < b <= constraints.window_end for a, b in slots):
                add("window_violation", field, "No slot fully inside the requested window")
        if offered and portal is not None and not offered.intersection(portal):
            add("contradiction", "portal_slots", "Offered slots are not bookable on the portal")
        if all(k in pf for k in ("base_charge_cents", "extra_fees", "visit_charge_cents")):
            computed = pf["base_charge_cents"].value + sum(fee["cents"] for fee in pf["extra_fees"].value)
            if computed != charge.value:
                add("contradiction", "visit_charge_cents", f"Base plus extra fees is {money(computed)}; stated total is {money(charge.value)}",
                    old_value=computed, new_value=charge.value)
        scope = (str(pf["fee_scope"].value) + " " + (pf["fee_scope"].scope or "")).lower() if "fee_scope" in pf else ""
        if "diagnostic" in scope and "only" in scope and "includes repair" in scope:
            add("contradiction", "fee_scope", "Diagnostic-only scope conflicts with included repair")
    return result


def detect_conflicts(task_id: str) -> list[Conflict]:
    return conflicts_for(repo.get_task(task_id).constraints, repo.get_providers(task_id), repo.list_facts(task_id))
