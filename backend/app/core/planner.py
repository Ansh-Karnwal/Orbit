"""Owner: Victor. Deterministic plan graph from the domain pack. Stub from CP0 — Phase 3."""
from __future__ import annotations

from app.core.schemas import PlanStep


def build_initial_plan(task_id: str) -> list[PlanStep]:
    raise NotImplementedError("planner.build_initial_plan: Phase 3")


def replan(task_id: str, reason: str) -> list[PlanStep]:
    raise NotImplementedError("planner.replan: Phase 3")
