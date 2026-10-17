"""Owner: Ansh. Stub from CP0 — replace. Fake availability + fake confirmation, no portal call."""
from __future__ import annotations

import hashlib
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core.evidence import save_evidence
from app.core.schemas import (AvailabilityResult, BookingRequest, BookingResult, ClaimLevel,
                              ConfirmationExtract, ProviderSpec, Slot)


class FixtureBrowserAdapter:
    name = "fixture_browser"
    is_fixture = True

    def __init__(self) -> None:
        self._bookings: dict[str, BookingResult] = {}   # orbit_ref -> result

    async def read_availability(self, task_id: str, provider: ProviderSpec, day_local: date,
                                tz: str) -> AvailabilityResult:
        z = ZoneInfo(tz)
        utc = ZoneInfo("UTC")
        slots = [Slot(start=datetime.combine(day_local, time(h, m), z).astimezone(utc),
                      end=datetime.combine(day_local, time(h + 1, m), z).astimezone(utc),
                      label=f"{h}:{m:02d}")
                 for h, m in ((14, 30), (16, 0))]
        ev = save_evidence(task_id, "availability", "fixture_browser", is_fixture=True,
                           extracted={"provider_id": provider.id,
                                      "slots": [s.model_dump(mode="json") for s in slots]},
                           claim_level=ClaimLevel.SLOT_OFFERED)
        return AvailabilityResult(slots=slots, evidence_ids=[ev.id])

    async def submit_booking(self, req: BookingRequest) -> BookingResult:
        if req.orbit_ref in self._bookings:
            return self._bookings[req.orbit_ref]
        p = req.proposal
        conf = ConfirmationExtract(
            confirmation_id="BK-" + hashlib.sha256(req.orbit_ref.encode()).hexdigest()[:6].upper(),
            provider_id=p.provider_id, service=p.service, slot_start=p.slot_start,
            slot_end=p.slot_end, visit_charge_cents=p.visit_charge_cents,
            cancellation_terms=p.cancellation_terms, orbit_ref=req.orbit_ref,
        )
        ev = save_evidence(req.task_id, "portal_confirmation", "fixture_browser", is_fixture=True,
                           extracted=conf.model_dump(mode="json"),
                           claim_level=ClaimLevel.BOOKING_REQUEST_SUBMITTED,
                           provider_ref=conf.confirmation_id)
        result = BookingResult(status="confirmed", confirmation=conf, evidence_ids=[ev.id])
        self._bookings[req.orbit_ref] = result
        return result

    async def find_booking(self, task_id: str, provider: ProviderSpec,
                           orbit_ref: str) -> BookingResult | None:
        return self._bookings.get(orbit_ref)
