"""Owner: Karthik. Stub from CP0 — replace (cheapest within budget, first offered slot)."""
from __future__ import annotations

from datetime import datetime, timedelta

from app.core import repo
from app.core.schemas import Proposal


def eligibility(task_id: str) -> dict[str, list[str]]:
    budget = repo.get_task(task_id).constraints.max_visit_charge_cents
    out: dict[str, list[str]] = {}
    for p in repo.get_providers(task_id):
        reasons: list[str] = []
        charge = repo.get_active_fact(task_id, f"{p.id}.visit_charge_cents")
        if charge is None:
            reasons.append("no visit charge quoted")
        elif charge.value > budget:
            reasons.append(f"visit charge {charge.value} exceeds budget {budget}")
        no_reply = repo.get_active_fact(task_id, f"{p.id}.no_reply")
        if no_reply is not None and no_reply.value:
            reasons.append("no reply")
        out[p.id] = reasons
    return out


def build_proposal(task_id: str, provider_id: str) -> Proposal | None:
    task = repo.get_task(task_id)
    p = repo.get_provider(task_id, provider_id)
    charge = repo.get_active_fact(task_id, f"{provider_id}.visit_charge_cents")
    if charge is None:
        return None
    facts = [charge]
    slot_start, slot_end = task.constraints.window_start, task.constraints.window_start + timedelta(hours=1)
    for key in ("portal_slots", "slots_offered"):
        slots = repo.get_active_fact(task_id, f"{provider_id}.{key}")
        if slots is not None and slots.value:
            slot_start = datetime.fromisoformat(slots.value[0]["start"])
            slot_end = datetime.fromisoformat(slots.value[0]["end"])
            facts.append(slots)
            break
    terms = repo.get_active_fact(task_id, f"{provider_id}.cancellation_terms")
    if terms is not None:
        facts.append(terms)
    return Proposal(
        task_id=task_id, provider_id=provider_id, provider_name=p.name,
        service=task.constraints.service, slot_start=slot_start, slot_end=slot_end,
        visit_charge_cents=charge.value, fee_scope="visit",
        cancellation_terms=terms.value if terms else "unknown",
        terms_version=max(f.version for f in facts),
        source_fact_ids=[f.id for f in facts],
    )


def best_proposal(task_id: str) -> Proposal | None:
    props = [build_proposal(task_id, pid) for pid, r in eligibility(task_id).items() if not r]
    props = [p for p in props if p is not None]
    return min(props, key=lambda p: p.visit_charge_cents) if props else None


def approval_still_valid(task_id: str) -> tuple[bool, str]:
    a = repo.get_latest_approval(task_id)
    if a is None or a.status not in ("requested", "approved"):
        return False, "no active approval"
    if eligibility(task_id).get(a.proposal.provider_id):
        return False, "provider no longer eligible"
    current = build_proposal(task_id, a.proposal.provider_id)
    if current is None or current.compute_hash() != a.proposal_hash:
        return False, "terms changed since approval"
    return True, ""
