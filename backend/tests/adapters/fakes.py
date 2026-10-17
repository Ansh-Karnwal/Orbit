"""In-memory stand-ins for Victor's evidence/repo layer so adapter tests run without a DB."""
from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.core.schemas import (BookingRequest, ClaimLevel, EvidenceArtifact, Proposal,
                              ProviderSpec, new_id, utcnow)

NOW = datetime(2026, 10, 17, 18, 0, tzinfo=timezone.utc)      # Sat 11:00 PDT
TUE = "2026-10-20"
B_SLOT_START = "2026-10-20T21:30:00Z"                           # Tue 14:30 PDT
B_SLOT_END = "2026-10-20T22:30:00Z"
PORTAL = "http://portal.test"


class FakeEvidence:
    def __init__(self) -> None:
        self.items: list[EvidenceArtifact] = []
        self.blobs: dict[str, bytes] = {}

    def save_evidence(self, task_id, kind, source, *, is_fixture, data=None, ext=None,
                      mime_type=None, extracted=None, claim_level: ClaimLevel | None = None,
                      provider_ref=None) -> EvidenceArtifact:
        ev_id = new_id("evd")
        ev = EvidenceArtifact(
            id=ev_id, task_id=task_id, kind=kind, source=source,
            uri=f"{task_id}/{ev_id}.{ext or 'bin'}" if data is not None else None,
            mime_type=mime_type, sha256=hashlib.sha256(data).hexdigest() if data else None,
            extracted=extracted or {}, claim_level=claim_level, is_fixture=is_fixture,
            provider_ref=provider_ref, captured_at=utcnow())
        self.items.append(ev)
        if data is not None:
            self.blobs[ev_id] = data
        return ev

    def of_kind(self, kind: str) -> list[EvidenceArtifact]:
        return [e for e in self.items if e.kind == kind]


def provider(pid: str = "provider_b", handle: str | None = None) -> ProviderSpec:
    names = {"provider_a": "Ace Appliance Repair", "provider_b": "Bayside Appliance Service"}
    return ProviderSpec(id=pid, name=names[pid], channel="fixture",
                        handle=handle or f"fixture:{pid}", portal_url=f"{PORTAL}/p/{pid}")


def booking_request(ref: str = "ORB-test0001", slot_start: str = B_SLOT_START,
                    slot_end: str = B_SLOT_END) -> BookingRequest:
    proposal = Proposal(
        task_id="tsk_test", provider_id="provider_b", provider_name="Bayside Appliance Service",
        service="dishwasher_repair", slot_start=slot_start, slot_end=slot_end,
        visit_charge_cents=14500, fee_scope="diagnostic_visit_including_travel",
        cancellation_terms="Cancel free more than 12 hours ahead, $25 inside 12 hours.",
        terms_version=1, source_fact_ids=["fct_1"])
    return BookingRequest(task_id="tsk_test", proposal=proposal, approval_id="apr_test",
                          orbit_ref=ref)
