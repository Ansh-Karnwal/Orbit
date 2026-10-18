"""Owner: Victor. Answers to Orbit's questions — POST /tasks/{id}/answers (roadmap F3).

Only the open question can be answered, only with one of its offered options. Every answer is
stored as user_decision evidence, emitted as `question.answered`, and unblocks the task
(BLOCKED -> PLANNING); choices that change what's possible (budget, window, providers) replan.
Changes here come from the signed-in user only — provider content never reaches this module."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import ValidationError

from app.context import facts as ctx_facts
from app.context.values import money
from app.core import coordinator, planner, questions, repo, worker
from app.core.evidence import save_evidence
from app.core.schemas import (TERMINAL_STATUSES, AnswerIn, Limits, ProviderSpec, StepState, Task,
                              TaskStatus as S, utcnow)

MAX_PROVIDERS = 10


class AnswerError(Exception):
    def __init__(self, status: int, code: str, message: str):
        super().__init__(message)
        self.status, self.code, self.message = status, code, message


def _int(params: dict[str, Any], key: str) -> int:
    v = params.get(key)
    if isinstance(v, bool) or not isinstance(v, int):
        raise AnswerError(422, "invalid_answer", f"{key} must be a whole number")
    return v


def _aware(params: dict[str, Any], key: str) -> datetime:
    try:
        dt = datetime.fromisoformat(str(params[key]).replace("Z", "+00:00"))
    except (KeyError, ValueError) as e:
        raise AnswerError(422, "invalid_answer", f"{key} must be an ISO date-time") from e
    if dt.tzinfo is None:
        raise AnswerError(422, "invalid_answer", f"{key} needs a UTC offset")
    return dt


def answer(task_id: str, body: AnswerIn, user_id: str) -> Task:
    task = repo.get_task(task_id)
    if task.status in TERMINAL_STATUSES:
        raise AnswerError(409, "already_terminal", f"task is already {task.status.value}")
    q = questions.open_question(task_id)
    if q is None or q.question_id != body.question_id:
        raise AnswerError(409, "stale_question", "That question is no longer open.")
    option = next((o for o in q.options if o.id == body.choice), None)
    if option is None:
        raise AnswerError(422, "invalid_answer", f"'{body.choice}' isn't one of the offered options")
    asked = questions.asked_data(task_id, q.question_id) or {}
    p = body.params
    evd = save_evidence(task_id, "user_decision", "orbit", is_fixture=False, extracted={
        "question_id": q.question_id, "reason_code": q.reason_code, "choice": body.choice,
        "params": p, "user": user_id})

    def answered(label: str) -> None:
        repo.emit(task_id, "question.answered", f"You chose: {label}",
                  {"question_id": q.question_id, "choice": body.choice, "params": p,
                   "by": user_id, "evidence_id": evd.id})

    if body.choice == "stop":
        answered(option.label)
        repo.invalidate_approvals(task_id, "you stopped the task")
        repo.set_status(task_id, S.CANCELLED, "stopped by you")
        return repo.get_task(task_id)

    c = task.constraints
    replan_reason: str | None = None
    new_provider: ProviderSpec | None = None
    label = option.label
    if body.choice == "raise_budget":
        cents = _int(p, "max_visit_charge_cents")
        if cents <= c.max_visit_charge_cents:
            raise AnswerError(422, "invalid_answer",
                              f"the new budget must be above {money(c.max_visit_charge_cents)}")
        repo.update_task_terms(task_id, constraints=c.model_copy(
            update={"max_visit_charge_cents": cents}))
        label = replan_reason = f"raise the budget to {money(cents)}"
    elif body.choice == "widen_window":
        start, end = _aware(p, "window_start"), _aware(p, "window_end")
        if end <= start or end <= utcnow():
            raise AnswerError(422, "invalid_answer", "the window must end after it starts, in the future")
        repo.update_task_terms(task_id, constraints=c.model_validate(
            {**c.model_dump(), "window_start": start, "window_end": end}))
        label = replan_reason = "widen the time window"
    elif body.choice == "reconsider":
        pid = p.get("provider_id")
        if pid not in option.params.get("provider_ids", []):
            raise AnswerError(422, "invalid_answer", "choose one of the providers you declined")
        ctx_facts.ingest_fact(task_id, f"{pid}.declined_by_user", False, source_id=evd.id)
        name = repo.get_provider(task_id, pid).name
        label = replan_reason = f"reconsider {name}"
    elif body.choice == "add_provider":
        try:
            new_provider = ProviderSpec.model_validate(p.get("provider") or {})
        except ValidationError as e:
            raise AnswerError(422, "invalid_answer", "provider needs id, name and handle") from e
        existing = repo.get_providers(task_id)
        if len(existing) >= MAX_PROVIDERS:
            raise AnswerError(422, "invalid_answer", f"at most {MAX_PROVIDERS} providers per task")
        if new_provider.id in {x.id for x in existing}:
            raise AnswerError(422, "invalid_answer", f"provider id {new_provider.id} is already used")
        if not new_provider.handle.strip():
            raise AnswerError(422, "invalid_answer", "provider handle must not be empty")
        if task.mode == "live" and (new_provider.channel == "fixture"
                                    or new_provider.handle.startswith("fixture:")):
            raise AnswerError(422, "invalid_answer", "live tasks need a real messaging handle")
        repo.add_provider(task_id, new_provider)
        label = f"add {new_provider.name}"
    elif body.choice == "retry":
        if asked.get("inbound_id"):
            repo.update_inbound(asked["inbound_id"], processed=False, payload={
                "extract_attempts": 0, "extract_retry_at": None})
        elif asked.get("step_id"):
            step = repo.get_step(asked["step_id"])
            repo.save_step(step.model_copy(update={"state": StepState.PENDING, "attempts": 0,
                                                   "not_before": None, "error": None,
                                                   "updated_at": utcnow()}))
        else:
            raise AnswerError(409, "invalid_answer", "nothing to retry for this question")
    elif body.choice == "check_again":
        if not coordinator.add_check_again_chain(task_id):
            raise AnswerError(409, "invalid_answer", "there's no booking to check")
    elif body.choice == "extend_limits":
        elapsed = int((utcnow() - task.created_at).total_seconds())
        cur = task.limits
        new = Limits(
            max_tool_actions=p.get("max_tool_actions", cur.max_tool_actions * 2),
            max_llm_calls=p.get("max_llm_calls", cur.max_llm_calls * 2),
            max_runtime_s=p.get("max_runtime_s", max(cur.max_runtime_s * 2, elapsed + 1800)),
            reply_timeout_s=cur.reply_timeout_s)
        if (new.max_tool_actions < cur.max_tool_actions or new.max_llm_calls < cur.max_llm_calls
                or new.max_runtime_s < cur.max_runtime_s):
            raise AnswerError(422, "invalid_answer", "limits can only be raised")
        repo.update_task_terms(task_id, limits=new)

    answered(label)
    repo.set_status(task_id, S.PLANNING, f"you chose: {label}")
    if new_provider is not None:
        planner.add_provider_chain(task_id, new_provider.id, f"you added {new_provider.name}")
    elif replan_reason:
        planner.replan(task_id, f"you chose to {replan_reason}")
    worker.wake(task_id)
    return repo.get_task(task_id)
