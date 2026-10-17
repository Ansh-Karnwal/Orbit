"""Owner: Victor. Startup recovery (A12/A13). Runs once before the worker starts; idempotent.

- ToolAction `started` -> `ambiguous`: we can't know whether the call took effect.
- Running steps -> `pending`, so executors re-run and their guards decide: an ambiguous send is
  treated as sent (never resent), a succeeded action is reused, reads simply re-run.
- A running submit_booking with an uncertain action -> FAILED + reconcile chain: the portal is
  checked before anything is ever resubmitted.
- Polled steps (await_reply, request_approval) stay `running`: every tick re-polls them.
- Pending approvals stay pending. The worker re-subscribes messaging and ticks everything."""
from __future__ import annotations

import logging

from app.core import coordinator, repo
from app.core.schemas import StepKind as K, StepState, utcnow

log = logging.getLogger("orbit.recovery")


def recover() -> dict[str, int]:
    stats = {"tasks": 0, "actions_ambiguous": 0, "steps_reset": 0, "bookings_reconciling": 0}
    for task in repo.list_active_tasks():
        stats["tasks"] += 1
        for a in repo.list_actions(task.id, status="started"):
            repo.save_action(a.model_copy(update={
                "status": "ambiguous",
                "result": {**(a.result or {}), "recovery": "in flight when the process stopped"}}))
            stats["actions_ambiguous"] += 1

        actions = {a.idempotency_key: a for a in repo.list_actions(task.id)}
        for s in repo.list_steps(task.id):
            if s.state != StepState.RUNNING or s.kind in coordinator.POLLED_KINDS:
                continue
            action = actions.get(s.idempotency_key)
            if s.kind == K.SUBMIT_BOOKING and action is not None and action.status == "ambiguous":
                coordinator.reconcile_interrupted_booking(
                    task, s, action, "booking was in flight when Orbit restarted")
                repo.save_step(s.model_copy(update={
                    "state": StepState.FAILED, "updated_at": utcnow(),
                    "error": "ambiguous: interrupted by restart; reconciling"}))
                stats["bookings_reconciling"] += 1
                continue
            repo.save_step(s.model_copy(update={"state": StepState.PENDING, "not_before": None,
                                                "updated_at": utcnow()}))
            stats["steps_reset"] += 1
    if any(v for k, v in stats.items() if k != "tasks"):
        log.info("recovery: %s", stats)
    return stats
