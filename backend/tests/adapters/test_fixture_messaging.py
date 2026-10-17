"""FixtureMessagingAdapter: scripted replies, stable ids, idempotency, fixture labelling."""
from __future__ import annotations

import asyncio

from app.adapters.fixture_messaging import FixtureMessagingAdapter, load_script
from app.core.schemas import ClaimLevel, InboundEvent

from .fakes import provider


class Collector:
    def __init__(self) -> None:
        self.events: list[InboundEvent] = []

    async def __call__(self, e: InboundEvent) -> None:
        self.events.append(e)


async def settle(adapter: FixtureMessagingAdapter) -> None:
    while adapter._pending:
        await asyncio.sleep(0)


async def started(**kw) -> tuple[FixtureMessagingAdapter, Collector]:
    adapter, got = FixtureMessagingAdapter(time_scale=0, **kw), Collector()
    await adapter.start(got)
    return adapter, got


def test_script_has_canonical_texts():
    s = load_script()
    assert s["provider_a"][0]["text"].startswith("Hi! Dishwasher repair visit is $120.")
    assert s["provider_a"][1]["trigger"] == "auto_followup" and "$190 total" in s["provider_a"][1]["text"]
    assert "Parts and labor are quoted after diagnosis" in s["provider_b"][0]["text"]


async def test_send_saves_fixture_evidence_and_replies(ev):
    adapter, got = await started(auto_followups=False)
    res = await adapter.send("tsk_1", provider("provider_b"), "Hello Bayside", "k1")
    await settle(adapter)
    assert res.status == "delivered" and res.provider_ref and res.evidence_ids == [ev.items[0].id]
    out = ev.items[0]
    assert out.kind == "message_out" and out.is_fixture is True
    assert out.claim_level == ClaimLevel.MESSAGE_SUBMITTED and out.source == "fixture_messaging"
    assert [(e.source, e.external_id, e.provider_id, e.sender_handle) for e in got.events] == [
        ("fixture", "fx:tsk_1:provider_b:1", "provider_b", "fixture:provider_b")]


async def test_same_idempotency_key_does_not_duplicate(ev):
    adapter, got = await started(auto_followups=False)
    r1 = await adapter.send("tsk_1", provider("provider_a"), "hi", "k1")
    r2 = await adapter.send("tsk_1", provider("provider_a"), "hi", "k1")
    await settle(adapter)
    assert r1 == r2 and len(ev.items) == 1 and len(got.events) == 1


async def test_followup_message_does_not_replay_script(ev):
    adapter, got = await started(auto_followups=False)
    await adapter.send("tsk_1", provider("provider_a"), "hi", "k1")
    await adapter.send("tsk_1", provider("provider_a"), "what about cancellation?", "k2")
    await settle(adapter)
    assert len(ev.items) == 2 and len(got.events) == 1


async def test_auto_followup_only_when_enabled(ev):
    adapter, got = await started(auto_followups=True)
    await adapter.send("tsk_1", provider("provider_a"), "hi", "k1")
    await settle(adapter)
    assert [e.external_id for e in got.events] == ["fx:tsk_1:provider_a:1", "fx:tsk_1:provider_a:2"]
    assert "$190 total" in got.events[1].text


async def test_reply_uses_handler_registered_after_send(ev):
    adapter = FixtureMessagingAdapter(time_scale=0, auto_followups=False)
    await adapter.send("tsk_1", provider("provider_b"), "hi", "k1")
    got = Collector()
    await adapter.start(got)
    await settle(adapter)
    assert len(got.events) == 1
