"""Owner: Victor. Per-task budgets: tool actions (ToolAction rows), runtime, LLM calls.

check() says whether a task has already gone over a limit (tick start). can_start() is the
gate before each wave: it projects the actions the next steps will need, so parallel steps
can't jointly overspend (audit gap c)."""
from __future__ import annotations

from collections.abc import Iterable

from app.core import repo
from app.core.schemas import StepKind as K, utcnow

# Upper bound on ToolAction rows a step of each kind can create in one attempt.
ACTION_COST = {K.SEND_INQUIRY: 1, K.READ_AVAILABILITY: 1, K.SUBMIT_BOOKING: 1, K.CONFIRM_WITH_PROVIDER: 1,
               K.RECONCILE_BOOKING: 3}         # find + (recheck | resubmit)
LLM_KINDS = {K.EXTRACT_QUOTE, K.VERIFY, K.SUMMARIZE}


def record_llm_call(task_id: str | None) -> None:
    """Called by the LLM client for every model call."""
    if task_id:
        repo.incr_llm_calls(task_id)


def check(task_id: str) -> tuple[bool, str]:
    """(within_budget, reason): False once any limit is already exceeded."""
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


def can_start(task_id: str, kinds: Iterable[K]) -> tuple[bool, str]:
    """Would starting steps of these kinds stay within the limits?"""
    kinds = list(kinds)
    lim = repo.get_task(task_id).limits
    actions = repo.count_actions(task_id)
    needed = sum(ACTION_COST.get(k, 0) for k in kinds)
    if needed and actions + needed > lim.max_tool_actions:
        return False, (f"budget exceeded: {actions} of {lim.max_tool_actions} tool actions used; "
                       f"the next steps need {needed} more")
    if any(k in LLM_KINDS for k in kinds) and repo.get_llm_calls(task_id) >= lim.max_llm_calls:
        return False, f"budget exceeded: all {lim.max_llm_calls} LLM calls used"
    return True, ""


def can_spend_actions(task_id: str, n: int = 1) -> bool:
    return repo.count_actions(task_id) + n <= repo.get_task(task_id).limits.max_tool_actions
