"""Owner: Victor. TaskView assembly — the one place the UI's snapshot is built."""
from __future__ import annotations

import logging
from typing import Callable, TypeVar

from app.adapters import registry
from app.context import proposals as ctx_proposals
from app.context import summary as ctx_summary
from app.core import questions, repo
from app.core.schemas import TERMINAL_STATUSES, Proposal, TaskStatus, TaskView

log = logging.getLogger("orbit.api")

T = TypeVar("T")
TIMELINE_LIMIT = 200


def _safe(fn: Callable[[], T], default: T, what: str) -> T:
    """Teammate logic must never turn a snapshot into a 500."""
    try:
        return fn()
    except Exception:
        log.warning("view: %s failed", what, exc_info=True)
        return default


def _current_proposal(task_id: str, terminal: bool, approvals) -> Proposal | None:
    pending = next((a for a in reversed(approvals) if a.status == "requested"), None)
    if pending is not None:
        return pending.proposal                      # what the user is being asked to approve
    approved = next((a for a in reversed(approvals) if a.status == "approved"), None)
    if approved is not None:
        return approved.proposal                     # what's being / been booked
    if terminal:
        return None
    return _safe(lambda: ctx_proposals.best_proposal(task_id), None, "best_proposal")


def build_view(task_id: str) -> TaskView:
    task = repo.get_task(task_id)
    approvals = repo.list_approvals(task_id)
    return TaskView(
        task=task,
        providers=repo.get_providers(task_id),
        facts=repo.list_facts(task_id, include_inactive=True),
        eligibility=_safe(lambda: ctx_proposals.eligibility(task_id), {}, "eligibility"),
        steps=repo.list_steps(task_id),
        approvals=approvals,
        current_proposal=_current_proposal(task_id, task.status in TERMINAL_STATUSES, approvals),
        evidence=repo.list_evidence(task_id),
        verification=repo.latest_verification(task_id),
        timeline=repo.list_timeline(task_id, last=TIMELINE_LIMIT),
        integrations=_safe(registry.integration_status, {}, "integration_status"),
        provider_summaries=_safe(lambda: ctx_summary.provider_summaries(task_id), {},
                                 "provider_summaries"),
        # Tied to the status read above, so a snapshot never shows a question on a non-blocked task.
        open_question=(questions.open_question(task_id)
                       if task.status == TaskStatus.BLOCKED else None),
    )
