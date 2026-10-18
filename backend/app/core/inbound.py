"""Owner: Victor. The callback messaging adapters call for every inbound message.
Records + dedups the event, stores it as evidence and wakes the worker. Extraction happens in
the coordinator (extract_quote step, or tick-time processing for late updates).

Messages from a task's own user (TaskCreate.user_contact) are recorded too. When
ORBIT_TEXT_APPROVALS=1 a reply "YES <hash8>" / "NO <hash8>" decides the pending approval — but
only from that exact handle and only if <hash8> prefixes the pending proposal's hash, so a
provider (or anyone else) can never approve anything."""
from __future__ import annotations

import logging
import re

from app.core import approvals, repo, worker
from app.core.config import get_settings
from app.core.evidence import save_evidence
from app.core.schemas import AdapterName, ApprovalDecisionIn, InboundEvent

log = logging.getLogger("orbit.inbound")

_EVIDENCE_SOURCE: dict[str, AdapterName] = {
    "photon": "photon", "fixture": "fixture_messaging", "demo": "demo"}
TEXT_DECISION = re.compile(r"^\s*(yes|no)\s+([0-9a-f]{8})\b", re.I)


async def handle_inbound(ev: InboundEvent) -> None:
    from_user = False
    if (ev.task_id is None or ev.provider_id is None) and ev.sender_handle:
        found = repo.find_task_by_handle(ev.sender_handle)
        if found:
            ev = ev.model_copy(update={"task_id": found[0], "provider_id": found[1]})
        elif ev.task_id is None and (tid := repo.find_task_by_user_contact(ev.sender_handle)):
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
    if pending is None or pending.status != "requested" \
            or not pending.proposal_hash.startswith(m.group(2).lower()):
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
