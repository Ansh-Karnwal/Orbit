"""Owner: Victor. Per-task budgets: tool actions (ToolAction rows), runtime, LLM calls."""
from __future__ import annotations

from app.core import repo
from app.core.schemas import utcnow


def record_llm_call(task_id: str | None) -> None:
    """Called by the LLM client for every model call."""
    if task_id:
        repo.incr_llm_calls(task_id)


def check(task_id: str) -> tuple[bool, str]:
    """(within_budget, reason)."""
    task = repo.get_task(task_id)
    lim = task.limits
    actions = repo.count_actions(task_id)
    if actions > lim.max_tool_actions:
        return False, f"budget exceeded: {actions} tool actions (limit {lim.max_tool_actions})"
    calls = repo.get_llm_calls(task_id)
    if calls > lim.max_llm_calls:
        return False, f"budget exceeded: {calls} LLM calls (limit {lim.max_llm_calls})"
    runtime = (utcnow() - task.created_at).total_seconds()
    if runtime > lim.max_runtime_s:
        return False, f"budget exceeded: running {int(runtime)}s (limit {lim.max_runtime_s}s)"
    return True, ""
