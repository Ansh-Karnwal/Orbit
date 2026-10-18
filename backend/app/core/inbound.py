"""Owner: Victor. The callback messaging adapters call for every inbound message.
Records + dedups the event, stores it as evidence and wakes the worker. Extraction happens in
the coordinator (extract_quote step, or tick-time processing for late updates).

Messages from a task's own user (TaskCreate.user_contact) are recorded too. When
ORBIT_TEXT_APPROVALS=1 a reply "YES" / "NO" (optionally "YES <hash8>") decides the pending approval —
but only from that exact handle, only for the approval Orbit actually texted them, and if <hash8>
is given only when it prefixes the pending proposal's hash. A provider (or anyone else) can never
approve anything.

With ORBIT_TEXT_INTAKE=1 a request texted from LIVE_USER_HANDLE, when that handle has no active
task, starts one."""
from __future__ import annotations

import logging
import re

from app.adapters.base import normalize_handle
from app.core import approvals, repo, worker
from app.core.config import get_settings
from app.core.evidence import save_evidence
from app.core.schemas import AdapterName, ApprovalDecisionIn, InboundEvent

log = logging.getLogger("orbit.inbound")

_EVIDENCE_SOURCE: dict[str, AdapterName] = {
    "photon": "photon", "fixture": "fixture_messaging", "demo": "demo"}
TEXT_DECISION = re.compile(r"^\W*(yes|no|y|n)\b(?:\W+([0-9a-f]{8})\b)?", re.I)
# A text only starts a task if it reads like a service request (not "thanks!" after a booking).
INTAKE_REQUEST = re.compile(r"\b(dishwasher|washer|washing machine|appliance|repair|fix|visit)\b", re.I)
BUDGET = re.compile(r"\$\s?(\d{2,5}(?:\.\d{1,2})?)")


async def handle_inbound(ev: InboundEvent) -> None:
    from_user = False
    if (ev.task_id is None or ev.provider_id is None) and ev.sender_handle:
        found = repo.find_task_by_handle(ev.sender_handle)
        if found:
            ev = ev.model_copy(update={"task_id": found[0], "provider_id": found[1]})
        elif ev.task_id is None and (tid := repo.find_task_by_user_contact(ev.sender_handle)):
            ev, from_user = ev.model_copy(update={"task_id": tid}), True
        elif ev.task_id is None and (tid := _start_task_from_text(ev)):
            ev, from_user = ev.model_copy(update={"task_id": tid}), True
    if ev.task_id is not None and ev.provider_id is not None:
        repo.get_provider(ev.task_id, ev.provider_id)          # NotFound if it isn't this task's

    stored, created = repo.record_inbound(ev)
    if ev.task_id is None:
        log.warning("inbound %s from %s matched no active task", stored.id, ev.source)
        return
    if not created:
        repo.emit(ev.task_id, "message.duplicate_ignored", "Duplicate message ignored",
                  {"inbound_id": stored.id, "provider_id": stored.provider_id,
                   "source": ev.source, "external_id": ev.external_id})
        return
    if from_user:
        await _handle_user_reply(stored)
        return

    provider = repo.get_provider(ev.task_id, ev.provider_id)
    evd = save_evidence(ev.task_id, "message_in", _EVIDENCE_SOURCE[ev.source],
                        is_fixture=ev.source != "photon",
                        extracted={"text": ev.text, "provider_id": ev.provider_id,
                                   "external_id": ev.external_id})
    repo.emit(ev.task_id, "message.received", f"Message from {provider.name}",
              {"inbound_id": stored.id, "provider_id": ev.provider_id, "evidence_id": evd.id,
               "text": ev.text, "source": ev.source, "is_fixture": evd.is_fixture})
    log.info("inbound %s recorded for task %s", stored.id, ev.task_id)
    worker.wake(ev.task_id)


def _start_task_from_text(ev: InboundEvent) -> str | None:
    """ORBIT_TEXT_INTAKE: the demo user's request text starts a task. Constraints come from the demo
    seed (service and next-Tuesday afternoon window); a "$N" in the text sets the budget. In live
    mode only providers with a live handle are contacted."""
    settings = get_settings()
    user = normalize_handle(settings.live_user_handle) if settings.live_user_handle else ""
    if not (settings.orbit_text_intake and user and ev.sender_handle == user
            and INTAKE_REQUEST.search(ev.text)):
        return None
    if repo.get_inbound_by_external(ev.source, ev.external_id) is not None:
        return None                                     # re-delivered after a restart
    from app.core.api.demo import resolve_seed         # api modules import this one
    from app.core.api.tasks import validate_intake
    from app.core.auth import DEMO_USER_ID
    seed = resolve_seed(settings.orbit_mode)
    constraints = seed.constraints
    if m := BUDGET.search(ev.text):
        constraints = constraints.model_copy(
            update={"max_visit_charge_cents": round(float(m.group(1)) * 100)})
    providers = [p for p in seed.providers if seed.mode == "fixture" or p.channel != "fixture"]
    body = seed.model_copy(update={"outcome_text": ev.text.strip()[:500], "constraints": constraints,
                                   "providers": providers, "user_contact": ev.sender_handle})
    errors = validate_intake(body)
    if errors:
        log.warning("text intake rejected: %s", "; ".join(e["msg"] for e in errors))
        return None
    task = repo.create_task(body, owner_id=DEMO_USER_ID)
    names = " and ".join(p.name for p in providers)
    budget = f"${constraints.max_visit_charge_cents / 100:,.2f}"
    repo.emit(task.id, "task.created_from_text", "Task started from your text",
              {"external_id": ev.external_id, "providers": [p.id for p in providers],
               "report": f"Orbit: on it. Asking {names} about a visit Tuesday afternoon, under "
                         f"{budget}. I'll text you before booking anything."})
    log.info("task %s started from a user text", task.id)
    worker.wake(task.id)
    return task.id


def _texted_to_user(task_id: str, proposal_hash: str) -> bool:
    """Was the approval request for this proposal actually texted to the user?"""
    for e in reversed(repo.list_timeline(task_id)):
        if e.type == "approval.requested" and e.data.get("proposal_hash") == proposal_hash:
            a = repo.get_action_by_key(f"{task_id}:report:{e.id}")
            return a is not None and a.status == "succeeded"
    return False


async def _handle_user_reply(ev: InboundEvent) -> None:
    """The task owner texted Orbit back (G4). Only a well-formed, hash-bound reply decides."""
    evd = save_evidence(ev.task_id, "message_in", _EVIDENCE_SOURCE[ev.source],
                        is_fixture=ev.source != "photon",
                        extracted={"text": ev.text, "from": "user", "external_id": ev.external_id})
    repo.emit(ev.task_id, "message.received", "Message from you",
              {"inbound_id": ev.id, "provider_id": None, "from_user": True,
               "evidence_id": evd.id, "text": ev.text, "source": ev.source,
               "is_fixture": evd.is_fixture})
    repo.mark_inbound_processed(ev.id)
    m = TEXT_DECISION.match(ev.text)
    if not get_settings().orbit_text_approvals or m is None:
        return
    pending = repo.get_latest_approval(ev.task_id)
    h8 = (m.group(2) or "").lower()
    if pending is None or pending.status != "requested" \
            or not pending.proposal_hash.startswith(h8) \
            or (not h8 and not _texted_to_user(ev.task_id, pending.proposal_hash)):
        repo.emit(ev.task_id, "error", "Your text reply didn't match the pending approval; "
                                       "nothing was decided", {"inbound_id": ev.id})
        return
    try:
        approvals.decide(ev.task_id, ApprovalDecisionIn(
            proposal_hash=pending.proposal_hash,
            decision="approved" if m.group(1).lower() == "yes" else "rejected"),
            approver="text:user")
    except approvals.StaleProposal as e:
        repo.emit(ev.task_id, "error", f"Your text reply came too late: {e.reason}",
                  {"inbound_id": ev.id})
