"""Owner: Victor. The callback messaging adapters call for every inbound message.
Records + dedups the event, stores it as evidence and wakes the worker. Extraction happens in
the coordinator (extract_quote step, or tick-time processing for late updates)."""
from __future__ import annotations

import logging

from app.core import repo, worker
from app.core.evidence import save_evidence
from app.core.schemas import AdapterName, InboundEvent

log = logging.getLogger("orbit.inbound")

_EVIDENCE_SOURCE: dict[str, AdapterName] = {
    "photon": "photon", "fixture": "fixture_messaging", "demo": "demo"}


async def handle_inbound(ev: InboundEvent) -> None:
    if (ev.task_id is None or ev.provider_id is None) and ev.sender_handle:
        found = repo.find_task_by_handle(ev.sender_handle)
        if found:
            ev = ev.model_copy(update={"task_id": found[0], "provider_id": found[1]})
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
