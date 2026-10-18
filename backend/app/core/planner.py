"""Owner: Victor. Deterministic plan graph (no LLM free-planning).

Procedure (home_repair v1), per provider p:
    send_inquiry(p) -> await_reply(p) -> extract_quote(p)
then: compare_quotes -> read_availability -> request_approval -> submit_booking -> verify -> summarize

The tail is late-bound: compare_quotes picks the provider at run time, and submit_booking's key
is bound to the approved proposal hash. The coordinator calls bind_step() before executing.
Replans never resend an inquiry (send_inquiry keys are not plan-versioned) and never plan past a
booking that may already exist."""
from __future__ import annotations

import hashlib

from app.context.domain import load_pack
from app.context.proposals import best_proposal, eligibility
from app.core import questions, repo
from app.core.schemas import PlanStep, StepKind as K, StepState, new_id, utcnow

QUOTE_KINDS = {K.SEND_INQUIRY, K.AWAIT_REPLY, K.EXTRACT_QUOTE}
BOOKING_KINDS = {K.SUBMIT_BOOKING, K.RECONCILE_BOOKING}
TAIL = [K.READ_AVAILABILITY, K.REQUEST_APPROVAL, K.SUBMIT_BOOKING, K.VERIFY, K.SUMMARIZE]
OPEN_STATES = {StepState.PENDING, StepState.READY, StepState.RUNNING, StepState.BLOCKED}
MAX_FOLLOWUPS_PER_PROVIDER = 1


# ---------------------------------------------------------------- keys
def step_key(task_id: str, kind: K, provider_id: str | None = None, plan_version: int = 1, *,
             proposal_hash: str | None = None, followup_n: int | None = None) -> str:
    if kind == K.SEND_INQUIRY:
        if followup_n is not None:
            return f"{task_id}:followup:{provider_id}:{followup_n}"
        return f"{task_id}:send_inquiry:{provider_id}"          # never plan-versioned
    if kind == K.SUBMIT_BOOKING and proposal_hash:
        return f"{task_id}:submit_booking:{proposal_hash[:16]}"
    return f"{task_id}:{kind.value}:{provider_id or '-'}:v{plan_version}"


def orbit_ref(idempotency_key: str) -> str:
    return "ORB-" + hashlib.sha256(idempotency_key.encode()).hexdigest()[:10].upper()


def is_followup(step: PlanStep) -> bool:
    return step.kind == K.SEND_INQUIRY and ":followup:" in step.idempotency_key


def bind_step(step: PlanStep, *, provider_id: str | None = None,
              proposal_hash: str | None = None) -> PlanStep:
    """Late-bind provider / proposal hash and recompute the idempotency key. Caller saves it."""
    if step.kind == K.SEND_INQUIRY:
        return step
    pid = provider_id or step.provider_id
    key = step_key(step.task_id, step.kind, pid, step.plan_version, proposal_hash=proposal_hash)
    return step.model_copy(update={"provider_id": pid, "idempotency_key": key,
                                   "updated_at": utcnow()})


def current_plan_version(task_id: str) -> int:
    return max((s.plan_version for s in repo.list_steps(task_id)), default=0)


# ---------------------------------------------------------------- builders
def new_step(task_id: str, kind: K, pv: int, provider_id: str | None = None,
          depends_on: list[str] | None = None, key: str | None = None) -> PlanStep:
    now = utcnow()
    return PlanStep(id=new_id("stp"), task_id=task_id, kind=kind, provider_id=provider_id,
                    depends_on=depends_on or [],
                    idempotency_key=key or step_key(task_id, kind, provider_id, pv),
                    plan_version=pv, created_at=now, updated_at=now)


def _quote_chain(task_id: str, pv: int, provider_id: str,
                 followup_n: int | None = None) -> list[PlanStep]:
    send = new_step(task_id, K.SEND_INQUIRY, pv, provider_id,
                 key=step_key(task_id, K.SEND_INQUIRY, provider_id, pv, followup_n=followup_n))
    wait = new_step(task_id, K.AWAIT_REPLY, pv, provider_id, [send.id])
    extract = new_step(task_id, K.EXTRACT_QUOTE, pv, provider_id, [wait.id])
    return [send, wait, extract]


def _decision_chain(task_id: str, pv: int, compare_deps: list[str]) -> list[PlanStep]:
    steps = [new_step(task_id, K.COMPARE_QUOTES, pv, depends_on=compare_deps)]
    for kind in TAIL:
        steps.append(new_step(task_id, kind, pv, depends_on=[steps[-1].id]))
    return steps


def build_initial_plan(task_id: str) -> list[PlanStep]:
    """Plan v1. Idempotent: if the task already has steps, returns them unchanged."""
    existing = repo.list_steps(task_id)
    if existing:
        return existing
    steps: list[PlanStep] = []
    extract_ids: list[str] = []
    for p in repo.get_providers(task_id):
        chain = _quote_chain(task_id, 1, p.id)
        steps += chain
        extract_ids.append(chain[-1].id)
    steps += _decision_chain(task_id, 1, extract_ids)
    repo.save_steps(steps, events=[(
        "plan.created", f"Plan created with {len(steps)} steps",
        {"plan_version": 1, "step_ids": [s.id for s in steps]})])
    return steps


# ---------------------------------------------------------------- replanning
def doomed_step_ids(steps: list[PlanStep]) -> set[str]:
    """Ids of steps that can never succeed: failed/skipped, or open behind a doomed dependency."""
    doomed = {s.id for s in steps if s.state in (StepState.FAILED, StepState.SKIPPED)}
    changed = True
    while changed:
        changed = False
        for s in steps:
            if s.id not in doomed and s.state in OPEN_STATES and doomed.intersection(s.depends_on):
                doomed.add(s.id)
                changed = True
    return doomed


def descendants(steps: list[PlanStep], root_id: str) -> set[str]:
    """Ids of every step that transitively depends on `root_id`."""
    out: set[str] = set()
    frontier = {root_id}
    while frontier:
        frontier = {s.id for s in steps if frontier.intersection(s.depends_on)} - out
        out |= frontier
    return out


def _booking_attempted(task_id: str) -> bool:
    return any(a.operation == "submit_booking" and a.status in ("started", "succeeded", "ambiguous")
               for a in repo.list_actions(task_id))


def _followup_candidates(task_id: str, dead: set[str], steps: list[PlanStep]) -> list[tuple[str, list[str]]]:
    """Disqualified providers that only lack required facts (not over budget, not silent),
    and haven't used their follow-up yet."""
    task = repo.get_task(task_id)
    required = list(load_pack().required_facts_for_eligibility)
    out = []
    for pid in sorted(dead):
        used = sum(1 for s in steps if s.provider_id == pid and is_followup(s))
        if used >= MAX_FOLLOWUPS_PER_PROVIDER or _declined(task_id, pid):
            continue
        no_reply = repo.get_active_fact(task_id, f"{pid}.no_reply")
        if no_reply is not None and no_reply.value:
            continue
        charge = repo.get_active_fact(task_id, f"{pid}.visit_charge_cents")
        if charge is not None and charge.value > task.constraints.max_visit_charge_cents:
            continue
        missing = [k for k in required if repo.get_active_fact(task_id, f"{pid}.{k}") is None]
        if missing:
            out.append((pid, missing))
    return out


def _declined(task_id: str, provider_id: str) -> bool:
    """The user turned this provider down (whole provider, or every offered time)."""
    reasons = eligibility(task_id).get(provider_id, [])
    return any(r in ("Declined by you", "All offered times declined by you") for r in reasons)


def add_provider_chain(task_id: str, provider_id: str, reason: str) -> list[PlanStep]:
    """A provider added mid-task (user's answer): inquire, then decide again over everyone live."""
    pv = current_plan_version(task_id) + 1
    chain = _quote_chain(task_id, pv, provider_id)
    repo.save_steps(chain, events=[("plan.revised", f"Plan revised (v{pv}): {reason}",
                                    {"plan_version": pv, "added_step_ids": [s.id for s in chain],
                                     "skipped_step_ids": [], "reason": reason})], task_id=task_id)
    return chain + replan(task_id, reason)


def replan(task_id: str, reason: str) -> list[PlanStep]:
    """Skip open steps tied to a disqualified provider or a stale proposal, then add a fresh
    compare -> availability -> approval -> booking -> verify -> summarize chain (or a one-time
    follow-up inquiry, or BLOCKED + question.asked). Returns the added steps."""
    steps = repo.list_steps(task_id)
    if any(s.kind in BOOKING_KINDS and s.state == StepState.RUNNING for s in steps):
        return []        # booking in flight; verification decides, never plan around it
    if _booking_attempted(task_id):
        questions.ask(task_id, "Terms changed after a booking was submitted. Please review with "
                               "the provider before Orbit does anything else.",
                      "terms_changed_after_booking", {"reason": reason})
        return []

    pv = max((s.plan_version for s in steps), default=0) + 1
    elig = eligibility(task_id)
    providers = [p.id for p in repo.get_providers(task_id)]
    doomed = doomed_step_ids(steps)
    outstanding = {s.provider_id for s in steps if s.kind in QUOTE_KINDS
                   and s.state in OPEN_STATES and s.id not in doomed}
    dead = {p for p in providers if elig.get(p) and p not in outstanding}
    live = [p for p in providers if p not in dead]

    skipped = [s.model_copy(update={"state": StepState.SKIPPED, "updated_at": utcnow()})
               for s in steps
               if s.state in OPEN_STATES and (s.kind not in QUOTE_KINDS or s.provider_id in dead
                                              or s.id in doomed)]
    skipped_ids = {s.id for s in skipped}
    kept = [s for s in steps if s.id not in skipped_ids]

    added: list[PlanStep] = []
    question: str | None = None
    code = "no_eligible_provider"
    if live:   # someone is still quoting or is eligible: decide again over them
        deps = []
        for p in live:
            extracts = [s for s in kept if s.kind == K.EXTRACT_QUOTE and s.provider_id == p]
            if extracts:
                deps.append(max(extracts, key=lambda s: s.plan_version).id)
        added = _decision_chain(task_id, pv, deps)
    else:
        candidates = _followup_candidates(task_id, dead, steps)
        deps = []
        for pid, _missing in candidates:
            n = 1 + sum(1 for s in steps if s.provider_id == pid and is_followup(s))
            chain = _quote_chain(task_id, pv, pid, followup_n=n)
            added += chain
            deps.append(chain[-1].id)
        if candidates:
            added += _decision_chain(task_id, pv, deps)
        else:
            names = {p.id: p.name for p in repo.get_providers(task_id)}
            details = "; ".join(f"{names.get(p, p)}: {', '.join(r)}" for p, r in elig.items() if r)
            if dead and all(_declined(task_id, p) for p in dead):
                code = "user_rejected_all"
                question = (f"You've declined every option ({details}). Reconsider one, add "
                            "another provider, or stop?")
            else:
                question = (f"No provider meets your constraints ({details}). Raise the budget, "
                            "widen the time window, or add another provider?")

    best = best_proposal(task_id)
    events = [("step.skipped", f"Skipped {s.kind.value}" + (f" ({s.provider_id})" if s.provider_id else ""),
               {"step_id": s.id, "kind": s.kind.value, "provider_id": s.provider_id,
                "reason": reason})
              for s in skipped]
    events.append(("plan.revised", f"Plan revised (v{pv}): {reason}",
                   {"plan_version": pv, "added_step_ids": [s.id for s in added],
                    "skipped_step_ids": [s.id for s in skipped], "reason": reason,
                    "best_provider_id": best.provider_id if best else None,
                    "followup_provider_ids": sorted({s.provider_id for s in added if is_followup(s)})}))
    repo.save_steps(skipped + added, events=events, task_id=task_id)

    if question:
        questions.ask(task_id, question, code, {"eligibility": elig, "reason": reason})
    return added
