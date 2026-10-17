"""Deterministic stand-ins for adapters + verifier, so core tests don't depend on teammates' code
or timing. The portal fake behaves like a real portal: every submit creates a booking."""
from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo

from app.core import coordinator, inbound, repo
from app.core.evidence import save_evidence
from app.core.schemas import (AvailabilityResult, BookingRequest, BookingResult,
                              ConfirmationExtract, InboundEvent, PredicateResult, ProviderSpec,
                              SendResult, Slot, Verdict, VerificationResult, new_id, utcnow)

A1 = "Hi! Dishwasher repair visit is $120. I can do Tuesday 3–4pm. Free cancellation with 24 hours notice."
B1 = ("Yes we repair dishwashers. Diagnostic visit is $145 including travel. Tuesday 2:30–3:30pm "
      "or 4–5pm. Cancel free more than 12 hours ahead, $25 inside 12 hours. Parts and labor are "
      "quoted after diagnosis.")
A2 = "Sorry, I forgot — there's a $70 trip charge on top, so $190 total."


class FakeMessaging:
    name = "fixture_messaging"
    is_fixture = True

    def __init__(self) -> None:
        self.sent: list[tuple[str, str]] = []           # (provider_id, idempotency_key)
        self.fail_next = 0

    async def send(self, task_id: str, provider: ProviderSpec, text: str,
                   idempotency_key: str) -> SendResult:
        if self.fail_next:
            self.fail_next -= 1
            return SendResult(status="failed", error="carrier error")
        self.sent.append((provider.id, idempotency_key))
        ev = save_evidence(task_id, "message_out", "fixture_messaging", is_fixture=True,
                           extracted={"text": text, "provider_id": provider.id})
        return SendResult(provider_ref=f"msg-{len(self.sent)}", status="delivered",
                          evidence_ids=[ev.id])

    async def start(self, on_inbound) -> None:
        self.on_inbound = on_inbound

    async def stop(self) -> None:
        pass


class FakePortal:
    """submit_mode: ok | ambiguous_booked | timeout_booked | timeout_not_booked | failed |
    mismatch | no_confirmation"""
    name = "fixture_browser"
    is_fixture = True

    def __init__(self) -> None:
        self.submit_mode = "ok"
        self.calls: list[tuple[str, str, str | None]] = []   # (op, provider_id, orbit_ref)
        self.created: list[str] = []                         # one entry per real booking
        self.bookings: dict[str, BookingResult] = {}
        self.read_fail_next = 0

    async def read_availability(self, task_id: str, provider: ProviderSpec, day_local: date,
                                tz: str) -> AvailabilityResult:
        self.calls.append(("read", provider.id, None))
        if self.read_fail_next:
            self.read_fail_next -= 1
            raise ConnectionError("portal unreachable")
        z, utc = ZoneInfo(tz), ZoneInfo("UTC")
        slots = [Slot(start=datetime.combine(day_local, time(h, m), z).astimezone(utc),
                      end=datetime.combine(day_local, time(h + 1, m), z).astimezone(utc))
                 for h, m in ((14, 30), (16, 0))]
        ev = save_evidence(task_id, "availability", "fixture_browser", is_fixture=True,
                           extracted={"provider_id": provider.id})
        return AvailabilityResult(slots=slots, evidence_ids=[ev.id])

    async def submit_booking(self, req: BookingRequest) -> BookingResult:
        p = req.proposal
        self.calls.append(("submit", p.provider_id, req.orbit_ref))
        mode = self.submit_mode
        if mode == "failed":
            return BookingResult(status="failed", error="slot no longer available")
        if mode == "timeout_not_booked":
            self.submit_mode = "ok"
            raise TimeoutError("portal timed out before submit")
        conf = ConfirmationExtract(
            confirmation_id=f"BK-{len(self.created) + 1:04d}", provider_id=p.provider_id,
            service=p.service, slot_start=p.slot_start, slot_end=p.slot_end,
            visit_charge_cents=p.visit_charge_cents + (5000 if mode == "mismatch" else 0),
            cancellation_terms=p.cancellation_terms, orbit_ref=req.orbit_ref)
        self.created.append(req.orbit_ref)
        if mode == "no_confirmation":
            result = BookingResult(status="submitted_unconfirmed")
        else:
            ev = save_evidence(req.task_id, "portal_confirmation", "fixture_browser",
                               is_fixture=True, extracted=conf.model_dump(mode="json"),
                               provider_ref=conf.confirmation_id)
            result = BookingResult(status="confirmed", confirmation=conf, evidence_ids=[ev.id])
        self.bookings[req.orbit_ref] = result
        if mode == "ambiguous_booked":
            return BookingResult(status="ambiguous", error="no confirmation page")
        if mode == "timeout_booked":
            raise TimeoutError("timed out after submit")
        return result

    async def find_booking(self, task_id: str, provider: ProviderSpec,
                           orbit_ref: str) -> BookingResult | None:
        self.calls.append(("find", provider.id, orbit_ref))
        return self.bookings.get(orbit_ref)

    def ops(self) -> list[str]:
        return [c[0] for c in self.calls if c[0] != "read"]


async def fake_verify(task_id: str) -> VerificationResult:
    """Read-only, deterministic: latest portal confirmation vs the approved proposal."""
    a = repo.get_latest_approval(task_id)
    confs = repo.list_evidence(task_id, "portal_confirmation")
    if a is None or a.status != "approved" or not confs:
        verdict, why, preds = Verdict.INSUFFICIENT_EVIDENCE, "no confirmation evidence", []
    else:
        ex, p = confs[-1].extracted, a.proposal
        checks = {
            "provider_matches": ex["provider_id"] == p.provider_id,
            "charge_matches": ex["visit_charge_cents"] == p.visit_charge_cents,
            "slot_matches": datetime.fromisoformat(ex["slot_start"]) == p.slot_start,
        }
        preds = [PredicateResult(name=k, passed=v, detail="", evidence_ids=[confs[-1].id])
                 for k, v in checks.items()]
        ok = all(checks.values())
        verdict = Verdict.PASS if ok else Verdict.FAIL
        why = "confirmation matches approved terms" if ok else "confirmation differs from approved terms"
    return VerificationResult(id=new_id("ver"), task_id=task_id,
                              approval_id=a.id if a else None, predicates=preds, verdict=verdict,
                              explanation=why, created_at=utcnow())


# ---------------------------------------------------------------- scenario helpers
async def reply(task_id: str, provider_id: str, text: str, external_id: str | None = None) -> None:
    await inbound.handle_inbound(InboundEvent(
        id=new_id("inb"), source="demo", external_id=external_id or new_id("ext"),
        task_id=task_id, provider_id=provider_id, text=text, received_at=utcnow()))


async def ticks(task_id: str, n: int = 2) -> None:
    for _ in range(n):
        await coordinator.tick(task_id)


def types(task_id: str) -> list[str]:
    return [e.type for e in repo.list_timeline(task_id)]


def events(task_id: str, type_: str) -> list[dict]:
    return [e.data for e in repo.list_timeline(task_id) if e.type == type_]


async def to_approval_for_a(task_id: str) -> None:
    """Quotes in from A ($120) and B ($145); A chosen; approval for A pending."""
    await ticks(task_id)
    await reply(task_id, "provider_a", A1)
    await reply(task_id, "provider_b", B1)
    await ticks(task_id)
