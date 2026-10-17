"""Owner: Karthik. Stub from CP0 — replace."""
from __future__ import annotations

from app.core import repo
from app.core.schemas import Conflict


def detect_conflicts(task_id: str) -> list[Conflict]:
    budget = repo.get_task(task_id).constraints.max_visit_charge_cents
    out: list[Conflict] = []
    for p in repo.get_providers(task_id):
        f = repo.get_active_fact(task_id, f"{p.id}.visit_charge_cents")
        if f is not None and f.value > budget:
            out.append(Conflict(kind="budget_violation", key=f.key, provider_id=p.id,
                                new_value=f.value, detail=f"{f.value} > budget {budget}"))
    return out
