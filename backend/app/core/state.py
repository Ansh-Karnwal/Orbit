"""Owner: Victor. Task state machine. The completion gate (PASS verification tied to the
current approved approval) is enforced in repo.set_status on top of this table."""
from __future__ import annotations

from app.core.schemas import TaskStatus as S


class IllegalTransition(Exception):
    pass


class CompletionGateError(IllegalTransition):
    """COMPLETED requested without a PASS verification tied to the current approved approval."""


ALLOWED: dict[S, set[S]] = {
    S.DRAFT: {S.PLANNING, S.CANCELLED},
    S.PLANNING: {S.RUNNING, S.BLOCKED, S.FAILED, S.CANCELLED},
    S.RUNNING: {S.AWAITING_APPROVAL, S.WAITING_EXTERNAL, S.BLOCKED, S.VERIFYING, S.PLANNING,
                S.FAILED, S.CANCELLED},
    S.AWAITING_APPROVAL: {S.RUNNING, S.PLANNING, S.BLOCKED, S.FAILED, S.CANCELLED},
    S.WAITING_EXTERNAL: {S.RUNNING, S.PLANNING, S.BLOCKED, S.FAILED, S.CANCELLED},
    S.BLOCKED: {S.RUNNING, S.PLANNING, S.FAILED, S.CANCELLED},
    S.VERIFYING: {S.COMPLETED, S.RUNNING, S.BLOCKED, S.FAILED, S.CANCELLED},
    S.COMPLETED: set(),
    S.FAILED: set(),
    S.CANCELLED: set(),
}


def check_transition(current: S, new: S) -> None:
    if new not in ALLOWED[current]:
        raise IllegalTransition(f"{current.value} -> {new.value} not allowed")
