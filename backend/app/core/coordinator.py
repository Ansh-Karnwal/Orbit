"""Owner: Victor. Adaptive coordination engine.

tick(task_id) is idempotent and reads everything from the DB:
  1. budgets            -> budget.exceeded + BLOCKED
  2. DRAFT/PLANNING     -> build plan v1, RUNNING
  3. inbound            -> late provider updates are extracted here (how A's $190 lands)
  4. fact changes       -> conflicts; invalid approval -> invalidate + replan
  5. waves of ready steps (parallel; submit/reconcile booking always alone)
  6. task status derived from the graph after each wave

Invariants: booking only with an approval whose hash equals the current best proposal (A6/A7);
an ambiguous booking is reconciled before any resubmit, and resubmits at most once (A12);
COMPLETED only through repo.set_status's completion gate; a timeout is never success."""
from __future__ import annotations

import asyncio
import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from time import perf_counter
from typing import Any, Awaitable, Callable, Literal
from zoneinfo import ZoneInfo

from app.adapters import registry
from app.context import booking as ctx_booking
from app.context import compose as ctx_compose
from app.context import conflicts as ctx_conflicts
from app.context import extract as ctx_extract
from app.context import facts as ctx_facts
from app.context import proposals as ctx_proposals
from app.context import summary as ctx_summary
from app.context.domain import load_pack
from app.context.values import slot_pairs
from app.core import budgets, planner, questions, repo, telemetry
from app.core import evidence as core_evidence
from app.core.config import get_settings
from app.core.schemas import (TERMINAL_STATUSES, AvailabilityResult, BookingRequest, BookingResult,
                              Conflict, IngestResult, PlanStep, ProviderSpec, StepKind as K,
                              StepState, Task, TaskStatus as S, ToolAction, Verdict, new_id, utcnow)
from app.core.state import ALLOWED, CompletionGateError
from app.verify import verifier

log = logging.getLogger("orbit.coordinator")

POLLED_KINDS = {K.AWAIT_REPLY, K.REQUEST_APPROVAL, K.CONFIRM_WITH_PROVIDER}
ACTIVE_STATES = {StepState.PENDING, StepState.READY, StepState.RUNNING}
MAX_WAVES = 25
MAX_RECONCILES = 2


@dataclass
class Outcome:
    kind: Literal["succeeded", "failed", "waiting", "skipped"]
    result: dict | None = None
    error: str | None = None
    retryable: bool = False      # failed: back off and retry while attempts remain
    block: bool = True           # failed for good: task -> BLOCKED
    question: str | None = None  # emitted as question.asked when blocking
    replan: str | None = None    # reason; replan runs after the wave
    facts_changed: bool = False
    exc: BaseException | None = None   # underlying error, for telemetry
    code: str | None = None      # ReasonCode when blocking (default: step_failed)


def _ok(result: dict | None = None, *, facts_changed: bool = False) -> Outcome:
    return Outcome("succeeded", result=result or {}, facts_changed=facts_changed)


# ---------------------------------------------------------------- formatting
def _iso(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat().replace("+00:00", "Z")


def _usd(cents: Any) -> str:
    return f"${cents / 100:,.2f}" if isinstance(cents, int) else str(cents)


def _fmt_value(key: str, value: Any) -> str:
    return _usd(value) if key.endswith("_cents") else json.dumps(value, default=str)[:120]


def _local(dt: datetime, tz: str) -> str:
    return dt.astimezone(ZoneInfo(tz)).strftime("%a %b %d, %I:%M %p %Z").replace(" 0", " ")


def _label(step: PlanStep) -> str:
    return step.kind.value.replace("_", " ") + (f" ({step.provider_id})" if step.provider_id else "")


# ---------------------------------------------------------------- status
def _move(task_id: str, target: S, reason: str = "") -> None:
    """Set status, hopping through RUNNING when the direct transition isn't allowed."""
    t = repo.get_task(task_id)
    if t.status in TERMINAL_STATUSES:
        return
    if t.status == target:
        if reason:
            repo.set_status(task_id, target, reason)
        return
    if target not in ALLOWED[t.status] and S.RUNNING in ALLOWED[t.status] \
            and target in ALLOWED[S.RUNNING]:
        repo.set_status(task_id, S.RUNNING)
    repo.set_status(task_id, target, reason)


def _active(steps: list[PlanStep]) -> list[PlanStep]:
    doomed = planner.doomed_step_ids(steps)
    return [s for s in steps if s.state in ACTIVE_STATES and s.id not in doomed]


def _deps_done(step: PlanStep, by_id: dict[str, PlanStep]) -> bool:
    return all(by_id[d].state == StepState.SUCCEEDED for d in step.depends_on if d in by_id)


def _derive_status(task_id: str) -> None:
    task = repo.get_task(task_id)
    if task.status in TERMINAL_STATUSES or _paused(task_id):
        return
    steps = repo.list_steps(task_id)
    active = _active(steps)
    if not active:
        if task.status != S.BLOCKED:
            questions.ask(task_id, "Orbit has nothing left it can do on its own for this task.",
                          "step_failed")
        return
    by_id = {s.id: s for s in steps}
    running = {s.kind for s in active if s.state == StepState.RUNNING}
    ready = [s for s in active if s.state == StepState.PENDING and _deps_done(s, by_id)]
    if K.REQUEST_APPROVAL in running:
        _move(task_id, S.AWAITING_APPROVAL, "waiting for your approval")
    elif K.CONFIRM_WITH_PROVIDER in running:
        _move(task_id, S.WAITING_EXTERNAL, "waiting for the provider to confirm the booking")
    elif K.VERIFY in running or any(s.kind == K.SUMMARIZE for s in ready):
        _move(task_id, S.VERIFYING, "verifying booking evidence")
    elif running and running <= {K.AWAIT_REPLY} and not ready:
        _move(task_id, S.WAITING_EXTERNAL, "waiting for provider replies")
    else:
        _move(task_id, S.RUNNING)


# ---------------------------------------------------------------- timeline helpers
def _emit_conflicts(task_id: str, conflicts: list[Conflict]) -> None:
    def sig(d: dict) -> tuple:
        return (d["kind"], d["key"], d.get("provider_id"),
                json.dumps(d.get("new_value"), sort_keys=True, default=str))
    if not conflicts:
        return
    seen = {sig(e.data) for e in repo.list_timeline(task_id) if e.type == "conflict.detected"}
    for c in conflicts:
        d = c.model_dump(mode="json")
        if sig(d) not in seen:
            seen.add(sig(d))
            repo.emit(task_id, "conflict.detected", c.detail, d)


def _emit_ingest(task_id: str, provider_id: str | None, results: list[IngestResult]) -> None:
    for r in results:
        f = r.fact
        if r.changed:
            if r.superseded is not None:
                repo.emit(task_id, "fact.superseded",
                          f"{f.key}: {_fmt_value(f.key, r.superseded.value)} → {_fmt_value(f.key, f.value)}",
                          {"fact_id": f.id, "old_fact_id": r.superseded.id, "key": f.key,
                           "provider_id": provider_id, "old_value": r.superseded.value,
                           "new_value": f.value, "version": f.version, "source_id": f.source_id})
            else:
                repo.emit(task_id, "fact.added", f"{f.key} = {_fmt_value(f.key, f.value)}",
                          {"fact_id": f.id, "key": f.key, "provider_id": provider_id,
                           "value": f.value, "version": f.version, "status": f.status.value,
                           "source_id": f.source_id})
        _emit_conflicts(task_id, r.conflicts)


# ---------------------------------------------------------------- tool actions
def _start_action(task_id: str, step: PlanStep, adapter: str, operation: str, key: str,
                  request: dict, prior: ToolAction | None) -> ToolAction:
    """Persist status=started BEFORE calling the adapter, so a crash leaves evidence of intent."""
    a = ToolAction(id=prior.id if prior else new_id("act"), task_id=task_id, step_id=step.id,
                   adapter=adapter, operation=operation, idempotency_key=key, request=request,
                   status="started", started_at=utcnow())
    return repo.save_action(a)


def _finish_action(a: ToolAction, status: str, *, result: dict | None = None,
                   provider_ref: str | None = None, evidence_ids: list[str] | None = None) -> ToolAction:
    return repo.save_action(a.model_copy(update={
        "status": status, "result": result if result is not None else a.result,
        "provider_ref": provider_ref or a.provider_ref,
        "evidence_ids": evidence_ids if evidence_ids is not None else a.evidence_ids,
        "finished_at": utcnow()}))


# ---------------------------------------------------------------- plan surgery
def _bind_downstream(task_id: str, root_id: str, provider_id: str) -> None:
    steps = repo.list_steps(task_id)
    below = planner.descendants(steps, root_id)
    bound = [planner.bind_step(s, provider_id=provider_id) for s in steps
             if s.id in below and s.state == StepState.PENDING and s.provider_id != provider_id]
    if bound:
        repo.save_steps(bound)


def _reconcile_count(steps: list[PlanStep]) -> int:
    return sum(1 for s in steps if s.kind == K.RECONCILE_BOOKING)


def _add_reconcile_chain(task_id: str, anchor: PlanStep, submit_key: str, reason: str) -> None:
    """Skip open steps below `anchor`, then add reconcile_booking -> verify -> summarize."""
    steps = repo.list_steps(task_id)
    below = planner.descendants(steps, anchor.id)
    now = utcnow()
    skipped = [s.model_copy(update={"state": StepState.SKIPPED, "updated_at": now})
               for s in steps if s.id in below and s.state in ACTIVE_STATES]
    n = _reconcile_count(steps) + 1
    p, pv = anchor.provider_id, anchor.plan_version
    rec = planner.new_step(task_id, K.RECONCILE_BOOKING, pv, p, key=f"{submit_key}:reconcile:{n}")
    ver = planner.new_step(task_id, K.VERIFY, pv, p, [rec.id],
                           key=f"{task_id}:verify:{p or '-'}:v{pv}:r{n}")
    summ = planner.new_step(task_id, K.SUMMARIZE, pv, p, [ver.id],
                            key=f"{task_id}:summarize:{p or '-'}:v{pv}:r{n}")
    added = [rec, ver, summ]
    events = [("step.skipped", f"Skipped {_label(s)}",
               {"step_id": s.id, "kind": s.kind.value, "provider_id": s.provider_id, "reason": reason})
              for s in skipped]
    events.append(("plan.revised", f"Reconciling booking: {reason}",
                   {"plan_version": pv, "added_step_ids": [s.id for s in added],
                    "skipped_step_ids": [s.id for s in skipped], "reason": reason}))
    repo.save_steps(skipped + added, events=events, task_id=task_id)


def _submit_actions(task_id: str) -> list[ToolAction]:
    return [a for a in repo.list_actions(task_id)
            if a.operation == "submit_booking" and ":resubmit" not in a.idempotency_key]


def _uncertain_booking(task_id: str) -> ToolAction | None:
    subs = _submit_actions(task_id)
    if not subs:
        return None
    a = subs[-1]
    if a.status in ("started", "ambiguous"):
        return a
    if a.status == "succeeded" and (a.result or {}).get("status") == "submitted_unconfirmed":
        return a
    return None


# ---------------------------------------------------------------- executors
def _orbit_observation(task: Task, provider_id: str, step: PlanStep, observation: str) -> str:
    """Facts must cite an evidence or inbound id (contract §3.4), so Orbit's own observations
    (send failed, reply timed out) are recorded as evidence and the fact points at that."""
    ev = core_evidence.save_evidence(
        task.id, "message_out", "orbit", is_fixture=task.mode == "fixture",
        extracted={"provider_id": provider_id, "step_id": step.id, "observation": observation})
    return ev.id


async def _send_inquiry(task: Task, step: PlanStep) -> Outcome:
    p = repo.get_provider(task.id, step.provider_id)
    key = step.idempotency_key
    followup = planner.is_followup(step)
    prior = repo.get_action_by_key(key)
    if prior is not None and prior.status == "succeeded":
        return _ok(prior.result)
    if prior is not None and prior.status in ("started", "ambiguous"):
        # It may already have gone out: never resend (A13). A missing reply times out instead.
        return _ok({"status": "assumed_sent", "sent_at": _iso(prior.started_at),
                    "action_id": prior.id})

    missing = None
    if followup:
        missing = [k for k in list(load_pack().required_facts_for_eligibility)
                   if repo.get_active_fact(task.id, f"{p.id}.{k}") is None]
    from app.llm.client import LLMUnavailable, LLMExtractionError
    try:
        text = await ctx_compose.draft_message(task.id, p.id, missing)
    except (LLMUnavailable, LLMExtractionError) as exc:
        return Outcome("failed", error=f"Message drafting blocked: {exc}")
    m = registry.messaging()
    action = _start_action(task.id, step, m.name, "send", key,
                           {"provider_id": p.id, "followup": followup, "text": text}, prior)
    exc: BaseException | None = None
    try:
        r = await m.send(task.id, p, text, key)
        error = r.error if r.status == "failed" else None
    except Exception as e:  # noqa: BLE001 — adapter boundary
        r, error, exc = None, f"{type(e).__name__}: {e}", e
    if error is not None:
        _finish_action(action, "failed", result={"error": error})
        if r is not None and r.error_code in ("must_text_first", "recipient_not_allowed"):
            # Retrying can't fix setup problems: ask the user instead of looping (Photon shared line).
            fix = (f"{p.name} must text the Orbit line once before Orbit can message them."
                   if r.error_code == "must_text_first" else
                   f"{p.name}'s handle isn't on Orbit's allowed list for live messaging.")
            return Outcome("failed", error=error, code="integration_blocked",
                           question=fix + " Then choose Try again.")
        if step.attempts >= step.max_attempts:
            res = ctx_facts.ingest_fact(task.id, f"{p.id}.no_reply", True,
                                        source_id=_orbit_observation(task, p.id, step, "send_failed"))
            _emit_ingest(task.id, p.id, [res])
            return Outcome("failed", error=error, block=False, exc=exc,
                           replan=f"could not message {p.name}", facts_changed=True)
        return Outcome("failed", error=error, retryable=True, exc=exc)

    claim = "message_delivered" if r.status == "delivered" else "message_submitted"
    result = {"status": r.status, "provider_ref": r.provider_ref, "sent_at": _iso(action.started_at),
              "action_id": action.id, "evidence_ids": r.evidence_ids}
    _finish_action(action, "succeeded", result=result, provider_ref=r.provider_ref,
                   evidence_ids=r.evidence_ids)
    repo.emit(task.id, "message.sent",
              f"Sent {'follow-up' if followup else 'inquiry'} to {p.name}"
              + (" (fixture)" if m.is_fixture else ""),
              {"provider_id": p.id, "step_id": step.id, "action_id": action.id, "text": text,
               "claim_level": claim, "evidence_ids": r.evidence_ids, "is_fixture": m.is_fixture})
    return _ok(result)


async def _await_reply(task: Task, step: PlanStep) -> Outcome:
    pid = step.provider_id
    send_step = repo.get_step(step.depends_on[0])
    since = datetime.fromisoformat((send_step.result or {})["sent_at"])
    replies = [e for e in repo.list_inbound(task.id, pid) if e.received_at >= since]
    if replies:
        return _ok({"inbound_ids": [e.id for e in replies]})
    if utcnow() - since > timedelta(seconds=task.limits.reply_timeout_s):
        res = ctx_facts.ingest_fact(task.id, f"{pid}.no_reply", True,
                                    source_id=_orbit_observation(task, pid, step, "reply_timeout"))
        _emit_ingest(task.id, pid, [res])
        name = repo.get_provider(task.id, pid).name
        return Outcome("failed", error=f"no reply within {task.limits.reply_timeout_s}s",
                       block=False, replan=f"{name} did not reply", facts_changed=True)
    return Outcome("waiting")


async def _extract_quote(task: Task, step: PlanStep) -> Outcome:
    pid = step.provider_id
    events = [e for e in repo.list_unprocessed_inbound(task.id) if e.provider_id == pid]
    fact_ids: list[str] = []
    for ev in events:
        results = await ctx_extract.extract_provider_facts(task.id, pid, ev.text, ev.id)
        _emit_ingest(task.id, pid, results)
        repo.mark_inbound_processed(ev.id)
        fact_ids += [r.fact.id for r in results if r.changed]
    return _ok({"inbound_ids": [e.id for e in events], "fact_ids": fact_ids},
               facts_changed=bool(fact_ids))


async def _compare_quotes(task: Task, step: PlanStep) -> Outcome:
    elig = ctx_proposals.eligibility(task.id)
    seen = {(e.data.get("provider_id"), tuple(e.data.get("reasons", [])))
            for e in repo.list_timeline(task.id) if e.type == "provider.disqualified"}
    for pid, reasons in elig.items():
        if reasons and (pid, tuple(reasons)) not in seen:
            name = repo.get_provider(task.id, pid).name
            repo.emit(task.id, "provider.disqualified", f"{name}: {'; '.join(reasons)}",
                      {"provider_id": pid, "reasons": reasons, "step_id": step.id})
    best = ctx_proposals.best_proposal(task.id)
    if best is None:
        return Outcome("failed", error="no eligible provider", block=False,
                       replan="no eligible provider after comparing quotes")
    _bind_downstream(task.id, step.id, best.provider_id)
    return _ok({"provider_id": best.provider_id, "visit_charge_cents": best.visit_charge_cents,
                "proposal_hash": best.compute_hash(), "eligibility": elig})


async def _read_availability(task: Task, step: PlanStep) -> Outcome:
    p = repo.get_provider(task.id, step.provider_id)
    tz = task.constraints.timezone
    day = task.constraints.window_start.astimezone(ZoneInfo(tz)).date()
    key = step.idempotency_key
    prior = repo.get_action_by_key(key)
    b = registry.browser()
    if prior is not None and prior.status == "succeeded":
        r, action = AvailabilityResult.model_validate(prior.result), prior
    else:
        action = _start_action(task.id, step, b.name, "read_availability", key,
                               {"provider_id": p.id, "day_local": day.isoformat(), "tz": tz}, prior)
        try:
            r = await b.read_availability(task.id, p, day, tz)
        except Exception as e:  # noqa: BLE001
            _finish_action(action, "failed", result={"error": f"{type(e).__name__}: {e}"})
            return Outcome("failed", error=f"{type(e).__name__}: {e}", retryable=True, exc=e)
        if r.error:
            _finish_action(action, "failed", result=r.model_dump(mode="json"))
            return Outcome("failed", error=r.error, retryable=True)
        action = _finish_action(action, "succeeded", result=r.model_dump(mode="json"),
                                provider_ref=r.session_ref, evidence_ids=r.evidence_ids)
    slots = [{"start": _iso(s.start), "end": _iso(s.end)} for s in r.slots]
    res = ctx_facts.ingest_fact(task.id, f"{p.id}.portal_slots", slots,
                                source_id=r.evidence_ids[0] if r.evidence_ids else action.id)
    _emit_ingest(task.id, p.id, [res])
    repo.emit(task.id, "availability.read",
              f"Read {len(slots)} open slot(s) on {p.name}'s booking page"
              + (" (fixture)" if b.is_fixture else ""),
              {"provider_id": p.id, "step_id": step.id, "slots": slots,
               "evidence_ids": r.evidence_ids, "is_fixture": b.is_fixture})
    offered_fact = repo.get_active_fact(task.id, f"{p.id}.slots_offered")
    offered = slot_pairs(offered_fact.value) if offered_fact else set()
    portal = slot_pairs(slots)
    within = {(a, z) for a, z in offered
              if task.constraints.window_start <= a < z <= task.constraints.window_end}
    telemetry.record("availability.checked", task.id, provider_id=p.id, step_id=step.id,
                     mode=task.mode, offered_count=len(offered), portal_count=len(portal),
                     within_window_count=len(within), matching_count=len(within & portal),
                     demo_run_id=task.id if b.is_fixture else "",
                     reason_code="bookable" if within & portal else "no_matching_portal_slot")
    return _ok({"slots": slots}, facts_changed=res.changed)


async def _request_approval(task: Task, step: PlanStep) -> Outcome:
    aid = (step.result or {}).get("approval_id")
    if aid is None:
        best = ctx_proposals.best_proposal(task.id)
        if best is None:
            return Outcome("failed", error="no eligible provider", block=False,
                           replan="no eligible provider when requesting approval")
        if step.provider_id and best.provider_id != step.provider_id:
            return Outcome("skipped", error=f"best option is now {best.provider_name}",
                           replan=f"best option changed to {best.provider_name}")
        h = best.compute_hash()
        latest = repo.get_latest_approval(task.id)
        if latest is not None and latest.status in ("requested", "approved") \
                and latest.proposal_hash == h:
            a = latest
        else:
            if latest is not None and latest.status in ("requested", "approved"):
                repo.invalidate_approvals(task.id, "superseded by a new proposal")
            a = repo.create_approval_request(best)
            tz = task.constraints.timezone
            repo.emit(task.id, "approval.requested",
                      f"Approval needed: {best.provider_name}, {_local(best.slot_start, tz)}, "
                      f"{_usd(best.visit_charge_cents)}",
                      {"approval_id": a.id, "provider_id": best.provider_id, "step_id": step.id,
                       "proposal": best.model_dump(mode="json"), "proposal_hash": a.proposal_hash})
        if a.status == "approved":
            return _ok({"approval_id": a.id, "proposal_hash": a.proposal_hash})
        return Outcome("waiting", result={"approval_id": a.id, "proposal_hash": a.proposal_hash})

    a = repo.get_approval(aid)
    if a.status == "requested":
        return Outcome("waiting")
    if a.status == "approved":
        return _ok({"approval_id": a.id, "proposal_hash": a.proposal_hash})
    if a.status == "rejected":
        # approvals.decide already recorded the decline as a fact; look for the next option.
        return Outcome("skipped", error=f"you declined {a.proposal.provider_name}",
                       replan=f"you declined {a.proposal.provider_name}; looking for another option")
    # Withdrawn or expired. Whoever withdrew it usually replanned already (and skipped this step);
    # if not (e.g. withdrawn while blocking), replan now so the plan always moves on.
    why = a.invalidated_reason or f"approval {a.status}"
    return Outcome("skipped", error=why, replan=f"approval withdrawn: {why}")


# Provider's answer to "Reply YES to confirm". Anything else is a normal message (extracted as usual).
CONFIRM_YES = re.compile(r"^\W*(yes|yep|yeah|y|confirm(ed)?|ok(ay)?|sure|sounds good)\b", re.I)
CONFIRM_NO = re.compile(r"^\W*(no|nope|n|decline[d]?|can'?t|cannot)\b", re.I)


def confirm_answer(text: str) -> str | None:
    if CONFIRM_YES.match(text):
        return "yes"
    if CONFIRM_NO.match(text):
        return "no"
    return None


async def _confirm_with_provider(task: Task, step: PlanStep) -> Outcome:
    """Text the provider the terms the user approved; succeed only on their YES (ORBIT_PROVIDER_CONFIRM)."""
    a = repo.get_latest_approval(task.id)
    asked = (step.result or {}).get("approval_id")
    if a is None or a.status != "approved" or (asked and asked != a.id):
        why = "the approval changed while waiting for the provider" if asked else "no approved proposal"
        return Outcome("skipped", error=why, replan=f"provider confirmation stopped: {why}")
    p = a.proposal
    provider = repo.get_provider(task.id, p.provider_id)
    if asked is None:
        step = planner.bind_step(step, provider_id=p.provider_id, proposal_hash=a.proposal_hash)
        repo.save_step(step)
        key = step.idempotency_key
        prior = repo.get_action_by_key(key)
        if prior is not None and prior.status in ("succeeded", "started", "ambiguous"):
            sent_at = prior.started_at                 # may already have gone out: never resend
        else:
            text = (f"Orbit here: your customer approved {_local(p.slot_start, task.constraints.timezone)} "
                    f"for {_usd(p.visit_charge_cents)} (ref {planner.orbit_ref(key)}). "
                    "Reply YES to confirm and Orbit will book it, or NO if that no longer works.")
            m = registry.messaging()
            action = _start_action(task.id, step, m.name, "send", key,
                                   {"provider_id": p.provider_id, "kind": "provider_confirm",
                                    "text": text}, prior)
            try:
                r = await m.send(task.id, provider, text, key)
                error = r.error if r.status == "failed" else None
            except Exception as e:  # noqa: BLE001 — adapter boundary
                r, error = None, f"{type(e).__name__}: {e}"
            if error is not None:
                _finish_action(action, "failed", result={"error": error})
                return Outcome("failed", error=error, retryable=True,
                               question=f"Orbit couldn't text {provider.name} to confirm ({error}). "
                                        "Try again, or stop?")
            _finish_action(action, "succeeded", result={"status": r.status, "provider_ref": r.provider_ref},
                           provider_ref=r.provider_ref, evidence_ids=r.evidence_ids)
            repo.emit(task.id, "message.sent", f"Asked {provider.name} to confirm the booking"
                      + (" (fixture)" if m.is_fixture else ""),
                      {"provider_id": p.provider_id, "step_id": step.id, "action_id": action.id,
                       "text": text, "claim_level": "message_delivered" if r.status == "delivered"
                       else "message_submitted", "evidence_ids": r.evidence_ids,
                       "is_fixture": m.is_fixture})
            sent_at = action.started_at
        return Outcome("waiting", result={"approval_id": a.id, "sent_at": _iso(sent_at),
                                          "waiting_since": _iso(utcnow())})

    since = datetime.fromisoformat(step.result["sent_at"])
    for ev in sorted(repo.list_inbound(task.id, p.provider_id), key=lambda e: e.received_at):
        answer = confirm_answer(ev.text) if ev.received_at >= since else None
        if answer is None:
            continue
        repo.mark_inbound_processed(ev.id)
        if answer == "yes":
            repo.emit(task.id, "provider.confirmed", f"{provider.name} confirmed the booking",
                      {"provider_id": p.provider_id, "inbound_id": ev.id, "approval_id": a.id})
            return _ok({**step.result, "inbound_id": ev.id})
        repo.invalidate_approvals(task.id, f"{provider.name} declined the approved booking")
        return Outcome("failed", error=f"{provider.name} said no", code="step_failed",
                       question=f"{provider.name} said no to the booking. Try again, or stop?")
    waiting_since = step.result.get("waiting_since")
    if waiting_since is None:                  # retried after a timeout: wait a full period again
        return Outcome("waiting", result={"waiting_since": _iso(utcnow())})
    if utcnow() - datetime.fromisoformat(waiting_since) > timedelta(seconds=task.limits.reply_timeout_s):
        repo.save_step(step.model_copy(update={"result": {k: v for k, v in step.result.items()
                                                          if k != "waiting_since"}}))
        return Outcome("failed", error=f"no confirmation within {task.limits.reply_timeout_s}s",
                       question=f"{provider.name} hasn't confirmed the booking. Try again to keep "
                                "waiting, or stop?")
    return Outcome("waiting")


async def _submit_booking(task: Task, step: PlanStep) -> Outcome:
    # Pre-flight (A6/A7): book only what the user approved, and only if it's still current.
    a = repo.get_latest_approval(task.id)
    reason = None
    if a is None or a.status != "approved":
        reason = "no approved proposal"
    else:
        valid, why = ctx_proposals.approval_still_valid(task.id)
        best = ctx_proposals.best_proposal(task.id)
        if not valid:
            reason = why
        elif best is None or best.compute_hash() != a.proposal_hash:
            reason = "current best proposal differs from the approved one"
        elif step.provider_id and a.proposal.provider_id != step.provider_id:
            reason = "approval is for a different provider"
    if reason is not None:
        repo.invalidate_approvals(task.id, reason)
        return Outcome("skipped", error=reason, replan=f"booking pre-flight failed: {reason}")

    step = planner.bind_step(step, provider_id=a.proposal.provider_id, proposal_hash=a.proposal_hash)
    repo.save_step(step)
    key = step.idempotency_key
    ref = planner.orbit_ref(key)
    prior = repo.get_action_by_key(key)
    if prior is not None and prior.status == "succeeded":
        return _ok(prior.result)
    if prior is not None and prior.status in ("started", "ambiguous"):
        if prior.status == "started":
            prior = _finish_action(prior, "ambiguous")
        return _booking_ambiguous(task, step, prior, "earlier submission outcome unknown")

    req = BookingRequest(task_id=task.id, proposal=a.proposal, approval_id=a.id, orbit_ref=ref)
    try:
        # Binds approval -> orbit_ref as evidence; the verifier needs it to tie the portal
        # confirmation to this approval. Refuses stale or changed terms (never book on error).
        ctx_booking.record_booking_request(req)
    except ValueError as e:
        repo.invalidate_approvals(task.id, str(e))
        return Outcome("skipped", error=str(e), replan=f"booking pre-flight failed: {e}")
    b = registry.browser()
    action = _start_action(task.id, step, b.name, "submit_booking", key,
                           req.model_dump(mode="json"), prior)
    try:
        r = await b.submit_booking(req)
    except Exception as e:  # noqa: BLE001 — may have submitted: never retry blind
        action = _finish_action(action, "ambiguous", result={"error": f"{type(e).__name__}: {e}"})
        out = _booking_ambiguous(task, step, action, f"{type(e).__name__} during submission")
        out.exc = e
        return out
    if r.status in ("confirmed", "submitted_unconfirmed"):
        return _booking_done(task, step, action, req, r, resubmitted=False)
    if r.status == "ambiguous":
        action = _finish_action(action, "ambiguous", result=r.model_dump(mode="json"),
                                evidence_ids=r.evidence_ids)
        return _booking_ambiguous(task, step, action, r.error or "portal response unclear")
    _finish_action(action, "failed", result=r.model_dump(mode="json"), evidence_ids=r.evidence_ids)
    return Outcome("failed", error=r.error or "booking failed", retryable=True,
                   question=f"Booking with {a.proposal.provider_name} failed ({r.error or 'unknown'}). "
                            "Retry or cancel?")


def _booking_done(task: Task, step: PlanStep, action: ToolAction, req: BookingRequest,
                  r: BookingResult, *, resubmitted: bool) -> Outcome:
    conf = r.confirmation
    _finish_action(action, "succeeded", result=r.model_dump(mode="json"),
                   provider_ref=conf.confirmation_id if conf else r.session_ref,
                   evidence_ids=r.evidence_ids)
    is_fixture = registry.browser().is_fixture
    telemetry.record("booking.submitted", task.id, provider_id=req.proposal.provider_id,
                     step_id=step.id, mode=task.mode, status=r.status)
    repo.emit(task.id, "booking.submitted",
              f"Booking {'confirmed' if r.status == 'confirmed' else 'submitted'} with "
              f"{req.proposal.provider_name}" + (f" ({conf.confirmation_id})" if conf else "")
              + (" (fixture)" if is_fixture else ""),
              {"provider_id": req.proposal.provider_id, "step_id": step.id,
               "approval_id": req.approval_id, "orbit_ref": req.orbit_ref, "status": r.status,
               "confirmation_id": conf.confirmation_id if conf else None,
               "evidence_ids": r.evidence_ids, "session_ref": r.session_ref,
               "resubmitted": resubmitted, "is_fixture": is_fixture})
    return _ok({"orbit_ref": req.orbit_ref, "approval_id": req.approval_id,
                "booking": r.model_dump(mode="json")})


def add_check_again_chain(task_id: str) -> bool:
    """User answer "check again": look the booking up again (if one was submitted), re-verify and
    summarize. Never resubmits — the reconcile step only resubmits when no resubmit happened yet,
    and it always looks first. Returns False if there's nothing to check."""
    steps = repo.list_steps(task_id)
    anchors = [s for s in steps if s.kind in (K.VERIFY, K.RECONCILE_BOOKING)
               and s.state == StepState.FAILED]
    subs = _submit_actions(task_id)
    if not anchors or not subs:
        return False
    _add_reconcile_chain(task_id, anchors[-1], subs[-1].idempotency_key,
                         "you asked Orbit to check the booking again")
    return True


def reconcile_interrupted_booking(task: Task, step: PlanStep, action: ToolAction, why: str) -> None:
    """Recovery hook: a submit_booking was in flight when the process died."""
    _booking_ambiguous(task, step, action, why)


def _booking_ambiguous(task: Task, step: PlanStep, action: ToolAction, why: str) -> Outcome:
    telemetry.record("booking.ambiguous", task.id, level=logging.WARNING, provider_id=step.provider_id,
                     step_id=step.id, mode=task.mode, reason_code="response_uncertain")
    repo.emit(task.id, "booking.ambiguous",
              f"Booking outcome unclear ({why}); checking the portal before doing anything else",
              {"provider_id": step.provider_id, "step_id": step.id, "action_id": action.id,
               "orbit_ref": planner.orbit_ref(action.idempotency_key), "detail": why})
    _add_reconcile_chain(task.id, step, action.idempotency_key, f"booking ambiguous: {why}")
    return Outcome("failed", error=f"ambiguous: {why}", block=False)


async def _lookup_booking(task_id: str, step: PlanStep, key: str, p, orbit_ref: str) -> BookingResult | None:
    """find_booking wrapped in a ToolAction (reused once it has succeeded). Raises adapter errors."""
    prior = repo.get_action_by_key(key)
    if prior is not None and prior.status == "succeeded":
        raw = (prior.result or {}).get("found")
        return BookingResult.model_validate(raw) if raw else None
    b = registry.browser()
    action = _start_action(task_id, step, b.name, "find_booking", key,
                           {"orbit_ref": orbit_ref, "provider_id": p.id}, prior)
    try:
        found = await b.find_booking(task_id, p, orbit_ref)
    except Exception as e:
        _finish_action(action, "failed", result={"error": f"{type(e).__name__}: {e}"})
        raise
    _finish_action(action, "succeeded",
                   result={"found": found.model_dump(mode="json") if found else None},
                   evidence_ids=found.evidence_ids if found else [])
    return found


def _is_booked(r: BookingResult | None) -> bool:
    return r is not None and r.status in ("confirmed", "submitted_unconfirmed")


def _adopt_booking(task: Task, step: PlanStep, action: ToolAction, found: BookingResult,
                   p, orbit_ref: str) -> Outcome:
    """The portal has the booking: record it on the uncertain action instead of resubmitting."""
    conf = found.confirmation
    _finish_action(action, "succeeded", result=found.model_dump(mode="json"),
                   provider_ref=conf.confirmation_id if conf else None,
                   evidence_ids=found.evidence_ids)
    repo.emit(task.id, "booking.reconciled",
              f"Found the existing booking with {p.name}"
              + (f" ({conf.confirmation_id})" if conf else "") + "; no resubmission needed",
              {"provider_id": p.id, "step_id": step.id, "orbit_ref": orbit_ref,
               "found": True, "confirmation_id": conf.confirmation_id if conf else None,
               "evidence_ids": found.evidence_ids})
    return _ok({"orbit_ref": orbit_ref, "booking": found.model_dump(mode="json"), "reconciled": True})


async def _reconcile_booking(task: Task, step: PlanStep) -> Outcome:
    submit_key = step.idempotency_key.split(":reconcile:")[0]
    sub = repo.get_action_by_key(submit_key)
    if sub is None:
        return Outcome("failed", error="no submission to reconcile")
    req = BookingRequest.model_validate(sub.request)
    p = repo.get_provider(task.id, req.proposal.provider_id)
    b = registry.browser()

    # 1. Look before resubmitting (A12).
    try:
        found = await _lookup_booking(task.id, step, step.idempotency_key, p, req.orbit_ref)
    except Exception as e:  # noqa: BLE001
        return Outcome("failed", error=f"{type(e).__name__}: {e}", retryable=True, exc=e)
    if _is_booked(found):
        return _adopt_booking(task, step, sub, found, p, req.orbit_ref)

    # 2. Not found: at most one resubmission with the same orbit_ref.
    re_key = f"{submit_key}:resubmit"
    unknown_q = (f"Orbit couldn't confirm whether the booking with {p.name} went through "
                 f"(reference {req.orbit_ref}). Please check with the provider.")
    re_prior = repo.get_action_by_key(re_key)
    if re_prior is not None and re_prior.status == "succeeded":
        return _ok({"orbit_ref": req.orbit_ref, "booking": re_prior.result, "resubmitted": True})
    if re_prior is not None:
        if re_prior.status in ("started", "ambiguous"):
            # The resubmission itself may have landed (e.g. we crashed mid-call): look once more.
            try:
                again = await _lookup_booking(task.id, step, f"{step.idempotency_key}:recheck",
                                              p, req.orbit_ref)
            except Exception as e:  # noqa: BLE001
                return Outcome("failed", error=f"{type(e).__name__}: {e}", retryable=True, exc=e)
            if _is_booked(again):
                return _adopt_booking(task, step, re_prior, again, p, req.orbit_ref)
        return Outcome("failed", error="booking state unknown after resubmission", question=unknown_q,
                       code="booking_unknown")
    approval = repo.get_approval(req.approval_id)
    valid, why = ctx_proposals.approval_still_valid(task.id)
    if approval.status != "approved" or not valid:
        return Outcome("failed", error=f"not resubmitting: {why or 'approval not current'}",
                       question=unknown_q, code="booking_unknown")
    repo.emit(task.id, "booking.reconciled",
              f"No booking found for {req.orbit_ref}; resubmitting once with the same reference",
              {"provider_id": p.id, "step_id": step.id, "orbit_ref": req.orbit_ref,
               "found": False, "resubmitting": True})
    action = _start_action(task.id, step, b.name, "submit_booking", re_key, sub.request, None)
    # If the resubmission is itself unclear, the retry never submits again: it re-checks (above).
    try:
        r = await b.submit_booking(req)
    except Exception as e:  # noqa: BLE001
        _finish_action(action, "ambiguous", result={"error": f"{type(e).__name__}: {e}"})
        return Outcome("failed", error=f"resubmission unclear: {type(e).__name__}", retryable=True,
                       question=unknown_q, exc=e, code="booking_unknown")
    if r.status in ("confirmed", "submitted_unconfirmed"):
        return _booking_done(task, step, action, req, r, resubmitted=True)
    if r.status == "ambiguous":
        _finish_action(action, "ambiguous", result=r.model_dump(mode="json"),
                       evidence_ids=r.evidence_ids)
        return Outcome("failed", error="resubmission unclear", retryable=True, question=unknown_q,
                       code="booking_unknown")
    _finish_action(action, "failed", result=r.model_dump(mode="json"), evidence_ids=r.evidence_ids)
    return Outcome("failed", error=f"resubmission failed: {r.error or r.status}", question=unknown_q,
                   code="booking_unknown")


async def _verify(task: Task, step: PlanStep) -> Outcome:
    _move(task.id, S.VERIFYING, "verifying booking evidence")
    v = await verifier.verify(task.id)
    repo.save_verification(v)
    telemetry.record("booking.verified", task.id, step_id=step.id, provider_id=step.provider_id,
                     mode=task.mode, verdict=v.verdict.value)
    repo.emit(task.id, "verification.completed", f"Verification: {v.verdict.value}. {v.explanation}",
              {"verification_id": v.id, "verdict": v.verdict.value, "approval_id": v.approval_id,
               "explanation": v.explanation,
               "predicates": [p.model_dump(mode="json") for p in v.predicates]})
    if v.verdict == Verdict.PASS:
        return _ok({"verification_id": v.id, "verdict": v.verdict.value})
    if v.verdict == Verdict.FAIL:
        return Outcome("failed", error=f"verification failed: {v.explanation}",
                       code="verification_failed",
                       question=f"The booking doesn't match what you approved: {v.explanation} "
                                "Orbit won't call it handled. Check again, or stop and contact "
                                "the provider.")
    uncertain = _uncertain_booking(task.id)
    if uncertain is not None and _reconcile_count(repo.list_steps(task.id)) < MAX_RECONCILES:
        _add_reconcile_chain(task.id, step, uncertain.idempotency_key,
                             "insufficient evidence for an unconfirmed booking")
        return Outcome("failed", error="insufficient evidence; reconciling booking", block=False)
    return Outcome("failed", error=f"verification pending: {v.explanation}",
                   code="verification_pending",
                   question="Orbit can't yet prove the booking went through, so it isn't marked "
                            f"handled. {v.explanation} Check again later, or stop.")


async def _summarize(task: Task, step: PlanStep) -> Outcome:
    _move(task.id, S.VERIFYING, "verifying booking evidence")
    v = repo.latest_verification(task.id)
    if v is None or v.verdict != Verdict.PASS:
        return Outcome("failed", error="no PASS verification to summarize")
    text = await ctx_summary.summarize(task.id, v)
    repo.set_summary(task.id, text)
    try:
        repo.set_status(task.id, S.COMPLETED, "handled: booking verified")
    except CompletionGateError as e:
        return Outcome("failed", error=f"completion gate: {e}", code="verification_pending")
    repo.emit(task.id, "task.completed", "Handled. Booking verified against the approved terms.",
              {"verification_id": v.id, "approval_id": v.approval_id, "summary": text})
    return _ok({"verification_id": v.id})


EXECUTORS: dict[K, Callable[[Task, PlanStep], Awaitable[Outcome]]] = {
    K.SEND_INQUIRY: _send_inquiry,
    K.AWAIT_REPLY: _await_reply,
    K.EXTRACT_QUOTE: _extract_quote,
    K.COMPARE_QUOTES: _compare_quotes,
    K.READ_AVAILABILITY: _read_availability,
    K.REQUEST_APPROVAL: _request_approval,
    K.CONFIRM_WITH_PROVIDER: _confirm_with_provider,
    K.SUBMIT_BOOKING: _submit_booking,
    K.RECONCILE_BOOKING: _reconcile_booking,
    K.VERIFY: _verify,
    K.SUMMARIZE: _summarize,
}


# ---------------------------------------------------------------- applying outcomes
def _apply(task_id: str, step_id: str, out: Outcome) -> None:
    cur = repo.get_step(step_id)
    if cur.state != StepState.RUNNING:
        return                              # superseded meanwhile (e.g. skipped)
    now = utcnow()
    data = {"step_id": cur.id, "kind": cur.kind.value, "provider_id": cur.provider_id}
    if out.kind == "waiting":
        if out.result:
            repo.save_step(cur.model_copy(update={"result": {**(cur.result or {}), **out.result},
                                                  "updated_at": now}))
        return
    if out.kind == "succeeded":
        repo.save_step(cur.model_copy(update={"state": StepState.SUCCEEDED, "result": out.result,
                                              "error": None, "updated_at": now}))
        repo.emit(task_id, "step.succeeded", f"Done: {_label(cur)}", data)
        if cur.attempts > 1 and cur.error:
            telemetry.step_recovered(task_id, cur)
        return
    if out.kind == "skipped":
        repo.save_step(cur.model_copy(update={"state": StepState.SKIPPED, "error": out.error,
                                              "updated_at": now}))
        repo.emit(task_id, "step.skipped", f"Skipped {_label(cur)}: {out.error}",
                  {**data, "reason": out.error})
        return
    # failed
    retrying = out.retryable and cur.attempts < cur.max_attempts
    if out.exc is not None or out.retryable:          # operational, not a business outcome
        telemetry.step_failed(task_id, cur, out.error, exc=out.exc, retrying=retrying)
    if retrying:
        delay = min(2 ** cur.attempts, 30)
        repo.save_step(cur.model_copy(update={"state": StepState.PENDING, "error": out.error,
                                              "not_before": now + timedelta(seconds=delay),
                                              "updated_at": now}))
        repo.emit(task_id, "step.failed", f"{_label(cur)} failed; retrying in {delay}s",
                  {**data, "error": out.error, "attempt": cur.attempts, "retrying": True,
                   "retry_in_s": delay})
        return
    repo.save_step(cur.model_copy(update={"state": StepState.FAILED, "error": out.error,
                                          "updated_at": now}))
    repo.emit(task_id, "step.failed", f"{_label(cur)} failed: {out.error}",
              {**data, "error": out.error, "attempt": cur.attempts, "retrying": False})
    if out.block:
        question = out.question or (
            f"Orbit couldn't {_label(cur)} after {cur.attempts} attempt"
            f"{'s' if cur.attempts != 1 else ''} ({out.error}). Try again, or stop?")
        questions.ask(task_id, question, out.code or "step_failed", data)


# ---------------------------------------------------------------- tick
INBOUND_MAX_ATTEMPTS = 3


def _paused(task_id: str) -> bool:
    """BLOCKED with an unanswered question: nothing runs until the user answers."""
    return (repo.get_task(task_id).status == S.BLOCKED
            and questions.open_question(task_id) is not None)


async def _execute_step(task: Task, step: PlanStep) -> Outcome:
    attributes = {"task_id": task.id, "step_id": step.id, "step_kind": step.kind.value,
                  "provider_id": step.provider_id or "", "attempt": step.attempts, "mode": task.mode}
    started = perf_counter()
    with telemetry.operation("orbit.step", step.kind.value, **attributes) as span:
        try:
            result = await EXECUTORS[step.kind](task, step)
        except Exception as exc:
            telemetry.record("workflow.step.failed", task.id, level=logging.WARNING,
                             **{k: v for k, v in attributes.items() if k != "task_id"},
                             error_type=type(exc).__name__, duration_ms=round((perf_counter() - started) * 1000, 2))
            raise
        if span is not None:
            span.set_data("outcome", result.kind)
            if result.kind == "failed":
                span.set_status("internal_error" if result.retryable or result.exc else "ok")
        if result.kind != "waiting":
            telemetry.record("workflow.step.finished", task.id,
                             **{k: v for k, v in attributes.items() if k != "task_id"},
                             outcome=result.kind, retrying=result.retryable and step.attempts < step.max_attempts,
                             facts_changed=result.facts_changed,
                             duration_ms=round((perf_counter() - started) * 1000, 2))
        return result


async def _process_inbound(task_id: str) -> bool:
    """Extract late updates (provider's quote step already done). Returns True if facts changed.
    Extraction errors back off (min(2**n, 30) s) like any transient step; after
    INBOUND_MAX_ATTEMPTS Orbit stops trusting that provider's terms and asks the user."""
    pending = repo.list_unprocessed_inbound(task_id)
    if not pending:
        return False
    steps = repo.list_steps(task_id)
    open_extract = {s.provider_id for s in _active(steps) if s.kind == K.EXTRACT_QUOTE}
    confirming = {s.provider_id for s in _active(steps)
                  if s.kind == K.CONFIRM_WITH_PROVIDER and s.state == StepState.RUNNING}
    changed = False
    now = utcnow()
    for ev in pending:
        pid = ev.provider_id
        if pid is None:
            repo.mark_inbound_processed(ev.id)
            continue
        if pid in open_extract:
            continue                         # its extract_quote step will consume it
        if pid in confirming and confirm_answer(ev.text):
            repo.mark_inbound_processed(ev.id)
            continue                         # a YES/NO to Orbit's confirmation text, not new terms
        retry_at = ev.payload.get("extract_retry_at")
        if retry_at and datetime.fromisoformat(retry_at) > now:
            continue
        if not budgets.can_start(task_id, [K.EXTRACT_QUOTE])[0]:
            continue                         # the wave gate asks the budget question
        try:
            results = await ctx_extract.extract_provider_facts(task_id, pid, ev.text, ev.id)
        except Exception as e:  # noqa: BLE001 — LLM/extraction boundary
            name = repo.get_provider(task_id, pid).name
            attempts = int(ev.payload.get("extract_attempts", 0)) + 1
            log.warning("extracting inbound %s failed (%s), attempt %d", ev.id,
                        type(e).__name__, attempts)
            telemetry.tick_failed(task_id, e)
            if attempts < INBOUND_MAX_ATTEMPTS:
                delay = min(2 ** attempts, 30)
                repo.update_inbound(ev.id, payload={
                    "extract_attempts": attempts, "extract_error": type(e).__name__,
                    "extract_retry_at": _iso(now + timedelta(seconds=delay))})
                repo.emit(task_id, "error",
                          f"Couldn't read a new message from {name}; retrying in {delay}s",
                          {"inbound_id": ev.id, "provider_id": pid, "error": type(e).__name__,
                           "attempt": attempts, "retry_in_s": delay})
                continue
            # A message we can't read may change this provider's terms: no approval for them
            # stands until the user decides.
            repo.update_inbound(ev.id, processed=True, payload={
                "extract_attempts": attempts, "extract_error": type(e).__name__})
            a = repo.get_latest_approval(task_id)
            if a is not None and a.status in ("requested", "approved") \
                    and a.proposal.provider_id == pid:
                repo.invalidate_approvals(task_id, f"unreadable new message from {name}")
            questions.ask(task_id, f"Orbit couldn't read a new message from {name} after "
                                   f"{attempts} attempts, and it may change their terms. "
                                   "Try again, or stop?",
                          "step_failed", {"inbound_id": ev.id, "provider_id": pid})
            return changed
        _emit_ingest(task_id, pid, results)
        no_reply = repo.get_active_fact(task_id, f"{pid}.no_reply")
        if no_reply is not None and no_reply.value:
            res = ctx_facts.ingest_fact(task_id, f"{pid}.no_reply", False, source_id=ev.id)
            _emit_ingest(task_id, pid, [res])
            changed = True
        repo.mark_inbound_processed(ev.id)
        changed |= any(r.changed for r in results)
    return changed


def _after_fact_change(task_id: str) -> list[str]:
    """Conflicts; invalidate an approval whose terms no longer hold. Returns replan reasons."""
    _emit_conflicts(task_id, ctx_conflicts.detect_conflicts(task_id))
    a = repo.get_latest_approval(task_id)
    if a is not None and a.status in ("requested", "approved"):
        valid, why = ctx_proposals.approval_still_valid(task_id)
        if not valid:
            repo.invalidate_approvals(task_id, why)
            return [f"approval for {a.proposal.provider_name} no longer valid ({why})"]
        return []
    task = repo.get_task(task_id)
    if task.status == S.BLOCKED and task.reason_code in ("no_eligible_provider", "user_rejected_all"):
        # A provider's new message may open an option again: withdraw the question and replan.
        questions.withdraw(task_id, "new information from a provider")
        return ["new information from a provider"]
    return []


async def _run_wave(task_id: str) -> tuple[bool, list[str]]:
    steps = repo.list_steps(task_id)
    by_id = {s.id: s for s in steps}
    doomed = planner.doomed_step_ids(steps)
    now = utcnow()
    ready = [s for s in steps if s.state == StepState.PENDING and s.id not in doomed
             and _deps_done(s, by_id) and (s.not_before is None or s.not_before <= now)]
    booking = [s for s in ready if s.kind in planner.BOOKING_KINDS]
    if booking:
        batch = booking[:1]                  # bookings always run alone
    else:
        batch = ready + [s for s in steps if s.state == StepState.RUNNING and s.kind in POLLED_KINDS]
    if not batch:
        return False, []
    ok, why = budgets.can_start(task_id, [s.kind for s in batch if s.state == StepState.PENDING])
    if not ok:
        _block_for_budget(task_id, why)
        return False, []

    task = repo.get_task(task_id)
    progressed = False
    running: list[PlanStep] = []
    for s in batch:
        if s.state == StepState.PENDING:
            s = s.model_copy(update={"state": StepState.RUNNING, "attempts": s.attempts + 1,
                                     "not_before": None, "updated_at": now})
            repo.save_step(s)
            repo.emit(task_id, "step.started", f"Started: {_label(s)}",
                      {"step_id": s.id, "kind": s.kind.value, "provider_id": s.provider_id,
                       "attempt": s.attempts})
            progressed = True
        running.append(s)

    outcomes = await asyncio.gather(*(_execute_step(task, s) for s in running),
                                    return_exceptions=True)
    reasons: list[str] = []
    facts_changed = False
    for s, out in zip(running, outcomes):
        if isinstance(out, asyncio.CancelledError):
            raise out
        if isinstance(out, BaseException):
            log.error("step %s (%s) raised %s", s.id, s.kind.value, type(out).__name__,
                      exc_info=out)
            out = Outcome("failed", error=f"{type(out).__name__}: {out}"[:300], retryable=True,
                          exc=out)
        if out.kind != "waiting" or out.result:
            progressed = True
        facts_changed |= out.facts_changed
        if out.replan:
            reasons.append(out.replan)
        _apply(task_id, s.id, out)
    if facts_changed:
        reasons += _after_fact_change(task_id)
    return progressed, reasons


def _block_for_budget(task_id: str, why: str) -> None:
    task = repo.get_task(task_id)
    if task.status == S.BLOCKED and task.reason_code == "budget_exceeded":
        return                                  # already asked
    repo.emit(task_id, "budget.exceeded", why, {"reason": why})
    questions.ask(task_id, f"Orbit stopped to stay within its limits ({why}). "
                           "Let it keep working, or stop?", "budget_exceeded")


# ---------------------------------------------------------------- reports to the user (G4)
REPORTABLE = {"task.created_from_text", "approval.requested", "question.asked", "task.completed"}


def _report_text(task: Task, ev) -> str:
    if ev.type == "approval.requested":
        p = ev.data["proposal"]
        h8 = ev.data["proposal_hash"][:8]
        text = (f"Orbit: {p['provider_name']} can come "
                f"{_local(datetime.fromisoformat(p['slot_start']), task.constraints.timezone)} "
                f"for {_usd(p['visit_charge_cents'])}. Approve or decline in Orbit.")
        if get_settings().orbit_text_approvals:
            text += " Or reply YES to approve / NO to decline."
        return text
    if ev.type == "task.created_from_text":
        return ev.data["report"]
    if ev.type == "question.asked":
        return f"Orbit needs you: {ev.data['question']}"
    return f"Orbit: handled ✓ {ev.data.get('summary', '')}".strip()


async def _send_reports(task_id: str) -> None:
    """Text the user (TaskCreate.user_contact) about approvals, questions and completion.
    One ToolAction per timeline event: a report is never sent twice and never retried blind."""
    task = repo.get_task(task_id)
    if not task.user_contact:
        return
    events = [e for e in repo.list_timeline(task_id) if e.type in REPORTABLE]
    if not events:
        return
    m = registry.messaging()
    to = ProviderSpec(id="user", name="You", handle=task.user_contact,
                      channel="fixture" if m.is_fixture else "imessage")
    for ev in events:
        key = f"{task_id}:report:{ev.id}"
        if repo.get_action_by_key(key) is not None:
            continue
        if not budgets.can_spend_actions(task_id):
            return
        text = _report_text(task, ev)
        action = repo.save_action(ToolAction(
            id=new_id("act"), task_id=task_id, step_id=f"report:{ev.id}", adapter=m.name,
            operation="send", idempotency_key=key, request={"event_id": ev.id, "kind": ev.type},
            status="started", started_at=utcnow()))
        try:
            r = await m.send(task_id, to, text, key)
        except Exception as e:  # noqa: BLE001 — adapter boundary
            _finish_action(action, "ambiguous", result={"error": type(e).__name__})
            continue
        if r.status == "failed":
            _finish_action(action, "failed", result={"error": r.error, "error_code": r.error_code})
            repo.emit(task_id, "integration.blocked", f"Couldn't text you: {r.error}",
                      {"event_id": ev.id, "error": r.error, "error_code": r.error_code,
                       "adapter": m.name})
            continue
        _finish_action(action, "succeeded", result=r.model_dump(mode="json"),
                       provider_ref=r.provider_ref, evidence_ids=r.evidence_ids)
        what = {"task.created_from_text": "acknowledgement", "approval.requested": "approval request",
                "question.asked": "question", "task.completed": "completion summary"}[ev.type]
        repo.emit(task_id, "report.sent", f"Texted you the {what}"
                  + (" (fixture)" if m.is_fixture else ""),
                  {"event_id": ev.id, "kind": ev.type, "evidence_ids": r.evidence_ids,
                   "claim_level": "message_delivered" if r.status == "delivered"
                   else "message_submitted", "is_fixture": m.is_fixture})


async def tick(task_id: str) -> None:
    with telemetry.workflow(task_id):
        try:
            await _tick(task_id)
        finally:
            try:
                await _send_reports(task_id)
            except Exception:  # noqa: BLE001 — reporting must never break coordination
                log.exception("sending reports failed for task %s", task_id)


async def _tick(task_id: str) -> None:
    task = repo.get_task(task_id)
    if task.status in TERMINAL_STATUSES:
        return
    within, why = budgets.check(task_id)
    if not within:
        _block_for_budget(task_id, why)
        return
    if task.status in (S.DRAFT, S.PLANNING):
        if task.status == S.DRAFT:
            repo.set_status(task_id, S.PLANNING, "building plan")
        planner.build_initial_plan(task_id)
        repo.set_status(task_id, S.RUNNING)

    if await _process_inbound(task_id):
        reasons = _after_fact_change(task_id)
        if reasons:
            planner.replan(task_id, "; ".join(dict.fromkeys(reasons)))
    for _ in range(MAX_WAVES):
        if repo.get_task(task_id).status in TERMINAL_STATUSES or _paused(task_id):
            return
        progressed, reasons = await _run_wave(task_id)
        if reasons:
            # Replan before deriving status: between a skipped step and its replacement chain
            # the graph briefly has nothing runnable, which must not read as "stuck".
            planner.replan(task_id, "; ".join(dict.fromkeys(reasons)))
            progressed = True
        _derive_status(task_id)
        if not progressed:
            break
