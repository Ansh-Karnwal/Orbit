"""Owner: Karthik. Stub from CP0 — replace."""
from __future__ import annotations

from app.context.conflicts import detect_conflicts
from app.context.domain import load_pack
from app.core import repo
from app.core.schemas import ContextPacket, PlanStep


def assemble(task_id: str, step: PlanStep) -> ContextPacket:
    task = repo.get_task(task_id)
    prefix = f"{step.provider_id}." if step.provider_id else None
    return ContextPacket(
        task_id=task_id, step_kind=step.kind, outcome=task.outcome_text,
        constraints=task.constraints, domain_rules=load_pack().rules,
        facts=repo.list_facts(task_id, key_prefix=prefix),
        unresolved=detect_conflicts(task_id), allowed_scope=[], required_output={},
        required_evidence=[],
    )
