"""Owner: Victor. Questions Orbit asks the user when it can't continue on its own (roadmap F3).

ask() is the one way to block a task: it emits `question.asked` with a question id, a
machine-readable reason code and the options the user may pick, then sets BLOCKED with that code.
open_question() returns the latest question not yet answered, which the UI renders and
POST /tasks/{id}/answers resolves (see answers.py)."""
from __future__ import annotations

from typing import Any

from app.core import repo
from app.core.schemas import (TERMINAL_STATUSES, OpenQuestion, QuestionOption, TaskStatus as S,
                              new_id)
from app.core.state import ALLOWED

STOP = QuestionOption(id="stop", label="Stop here")


def _options(task_id: str, code: str, data: dict[str, Any]) -> list[QuestionOption]:
    task = repo.get_task(task_id)
    c = task.constraints
    providers = repo.get_providers(task_id)
    declined = [p.id for p in providers
                if (f := repo.get_active_fact(task_id, f"{p.id}.declined_by_user")) and f.value is True]
    charges = [f.value for p in providers
               if (f := repo.get_active_fact(task_id, f"{p.id}.visit_charge_cents"))]
    over = sorted(v for v in charges if v > c.max_visit_charge_cents)
    raise_budget = QuestionOption(
        id="raise_budget", label="Raise the budget",
        params={"current_cents": c.max_visit_charge_cents,
                "suggested_cents": over[0] if over else c.max_visit_charge_cents + 2500})
    widen = QuestionOption(id="widen_window", label="Widen the time window",
                           params={"window_start": c.window_start.isoformat(),
                                   "window_end": c.window_end.isoformat(), "timezone": c.timezone})
    reconsider = QuestionOption(id="reconsider", label="Reconsider a declined provider",
                                params={"provider_ids": declined})
    add_provider = QuestionOption(id="add_provider", label="Add another provider",
                                  params={"max_providers": 10, "current": len(providers)})
    retry = QuestionOption(id="retry", label="Try again")
    check_again = QuestionOption(id="check_again", label="Check the booking again")
    extend = QuestionOption(id="extend_limits", label="Let Orbit keep working",
                            params=task.limits.model_dump())
    by_code = {
        "no_eligible_provider": [raise_budget, widen] + ([reconsider] if declined else [])
                                + [add_provider],
        "user_rejected_all": [reconsider, add_provider, raise_budget],
        "verification_failed": [check_again],
        "verification_pending": [check_again],
        "booking_unknown": [check_again],
        "terms_changed_after_booking": [],
        "budget_exceeded": [extend],
        "integration_blocked": [retry],
        "step_failed": [retry] if data.get("step_id") or data.get("inbound_id") else [],
    }
    opts = list(by_code.get(code, []))
    if len(providers) >= 10:
        opts = [o for o in opts if o.id != "add_provider"]
    return opts + [STOP]


def ask(task_id: str, text: str, code: str, data: dict[str, Any] | None = None) -> str:
    """Emit question.asked and block the task with `code`. Returns the question id."""
    data = dict(data or {})
    task = repo.get_task(task_id)
    if task.status in TERMINAL_STATUSES:
        return ""
    qid = new_id("q")
    options = _options(task_id, code, data)
    repo.emit(task_id, "question.asked", text,
              {**data, "question_id": qid, "question": text, "reason_code": code,
               "options": [o.model_dump(mode="json") for o in options]})
    if task.status != S.BLOCKED and S.BLOCKED not in ALLOWED[task.status]:
        repo.set_status(task_id, S.PLANNING)           # only DRAFT can't block directly
    repo.set_status(task_id, S.BLOCKED, text, code=code)
    return qid


def open_question(task_id: str) -> OpenQuestion | None:
    """The latest question.asked not followed by its question.answered, while BLOCKED."""
    task = repo.get_task(task_id)
    if task.status != S.BLOCKED:
        return None
    asked = answered = None
    for ev in repo.list_timeline(task_id):
        if ev.type == "question.asked" and ev.data.get("question_id"):
            asked = ev
        elif ev.type == "question.answered":
            answered = ev.data.get("question_id")
    if asked is None or asked.data["question_id"] == answered:
        return None
    return OpenQuestion(question_id=asked.data["question_id"], text=asked.data["question"],
                        reason_code=asked.data["reason_code"],
                        options=[QuestionOption.model_validate(o) for o in asked.data["options"]],
                        asked_at=asked.at)


def withdraw(task_id: str, reason: str) -> None:
    """Orbit closes its own open question (e.g. a provider's new message may resolve it)."""
    q = open_question(task_id)
    if q is not None:
        repo.emit(task_id, "question.answered", f"Question withdrawn: {reason}",
                  {"question_id": q.question_id, "choice": "withdrawn", "by": "orbit",
                   "reason": reason})


def asked_data(task_id: str, question_id: str) -> dict[str, Any] | None:
    for ev in reversed(repo.list_timeline(task_id)):
        if ev.type == "question.asked" and ev.data.get("question_id") == question_id:
            return ev.data
    return None
