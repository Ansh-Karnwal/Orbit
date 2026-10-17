"""Published fixture adapters plus the full context/verifier path; no core worker."""
import asyncio
import json
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from app.adapters.fixture_browser import FixtureBrowserAdapter
from app.adapters.fixture_messaging import FixtureMessagingAdapter
from app.core import repo
from app.core.api.demo import resolve_seed
from app.core.schemas import BookingRequest, InboundEvent, TaskStatus, Verdict, new_id, utcnow
from app.context.booking import record_booking_request
from app.context.compose import compose_inquiry
from app.context.extract import extract_provider_facts
from app.context.facts import ingest_fact
from app.context.proposals import approval_still_valid, best_proposal, build_proposal
from app.context.summary import summarize
from app.verify.verifier import verify


async def run_fixture_story(fake):
    seed = resolve_seed("fixture")
    fake.task = fake.task.model_copy(update={"constraints": seed.constraints, "outcome_text": seed.outcome_text})
    fake.providers = seed.providers
    messaging = FixtureMessagingAdapter(reply_delay_s=0)
    browser = FixtureBrowserAdapter()
    received = asyncio.Event()

    async def on_inbound(event):
        saved, created = repo.record_inbound(event)
        if created:
            await extract_provider_facts(fake.task.id, saved.provider_id, saved.text, saved.id)
        if len(fake.inbound) >= 2:
            received.set()

    await messaging.start(on_inbound)
    try:
        for provider in fake.providers:
            result = await messaging.send(fake.task.id, provider, compose_inquiry(fake.task.id, provider.id), f"inquiry:{provider.id}")
            assert result.status == "delivered"
        await asyncio.wait_for(received.wait(), timeout=3)
    finally:
        await messaging.stop()
    cheapest = best_proposal(fake.task.id)
    assert cheapest.provider_id == "provider_a" and cheapest.visit_charge_cents == 12000
    pending_a = repo.create_approval_request(cheapest)
    script = json.loads((Path(__file__).parents[3] / "demo/fixture_script.json").read_text())
    correction = InboundEvent(id=new_id("inb"), source="demo", external_id="a-price-change", task_id=fake.task.id,
                              provider_id="provider_a", text=script["provider_a"][1]["text"], received_at=utcnow())
    await on_inbound(correction)
    assert approval_still_valid(fake.task.id)[0] is False
    invalidated = repo.invalidate_approvals(fake.task.id, "Visit charge increased above budget")
    assert invalidated[0].id == pending_a.id
    price_facts = [f for f in repo.list_facts(fake.task.id, include_inactive=True) if f.key == "provider_a.visit_charge_cents"]
    assert [(f.version, f.value, f.status.value) for f in price_facts] == [(1, 12000, "superseded"), (2, 19000, "confirmed")]
    before = len(fake.facts)
    await on_inbound(correction)
    assert len(fake.facts) == before

    proposal = best_proposal(fake.task.id)
    assert proposal.provider_id == "provider_b"
    provider = repo.get_provider(fake.task.id, proposal.provider_id)
    day = seed.constraints.window_start.astimezone(ZoneInfo(seed.constraints.timezone)).date()
    availability = await browser.read_availability(fake.task.id, provider, day, seed.constraints.timezone)
    ingest_fact(fake.task.id, "provider_b.portal_slots", [slot.model_dump(mode="json") for slot in availability.slots],
                source_id=availability.evidence_ids[0])
    proposal = build_proposal(fake.task.id, "provider_b")
    assert proposal.visit_charge_cents == 14500 and proposal.slot_start.astimezone(ZoneInfo(seed.constraints.timezone)).strftime("%H:%M") == "14:30"
    pending_b = repo.create_approval_request(proposal)
    approved = repo.decide_approval(pending_b.id, "approved", "fixture_user")
    request = BookingRequest(task_id=fake.task.id, proposal=proposal, approval_id=approved.id, orbit_ref=f"orbit:{fake.task.id}:booking:b")
    record_booking_request(request)
    booking = await browser.submit_booking(request)
    count = len(fake.evidence)
    duplicate = await browser.submit_booking(request)
    assert duplicate.confirmation.confirmation_id == booking.confirmation.confirmation_id
    assert len(fake.evidence) == count
    recovered = await browser.find_booking(fake.task.id, provider, request.orbit_ref)
    assert recovered.confirmation.confirmation_id == booking.confirmation.confirmation_id
    writes = list(fake.writes)
    verification = await verify(fake.task.id)
    assert verification.verdict == Verdict.PASS
    assert fake.writes == writes
    summary = await summarize(fake.task.id, verification)
    assert "$145.00" in summary and "including travel" in summary
    assert "Ace Appliance Repair was rejected" in summary and "$190.00 > $150.00" in summary
    assert "Parts and labor will be quoted after diagnosis" in summary and "fixture evidence" in summary
    return summary


def test_canonical_fixture_story_with_published_adapters(memory_repo):
    asyncio.run(run_fixture_story(memory_repo))
