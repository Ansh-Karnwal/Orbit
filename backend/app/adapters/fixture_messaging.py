"""Owner: Ansh. Stub from CP0 — replace. Echoes the canned first reply (§3.9) after 2 s."""
from __future__ import annotations

import asyncio
from typing import Awaitable, Callable

from app.core.evidence import save_evidence
from app.core.schemas import ClaimLevel, InboundEvent, ProviderSpec, SendResult, new_id, utcnow

CANNED_REPLIES = {
    "provider_a": "Hi! Dishwasher repair visit is $120. I can do Tuesday 3–4pm. "
                  "Free cancellation with 24 hours notice.",
    "provider_b": "Yes we repair dishwashers. Diagnostic visit is $145 including travel. "
                  "Tuesday 2:30–3:30pm or 4–5pm. Cancel free more than 12 hours ahead, "
                  "$25 inside 12 hours. Parts and labor are quoted after diagnosis.",
}


class FixtureMessagingAdapter:
    name = "fixture_messaging"
    is_fixture = True

    def __init__(self, reply_delay_s: float = 2.0) -> None:
        self.reply_delay_s = reply_delay_s
        self._on_inbound: Callable[[InboundEvent], Awaitable[None]] | None = None
        self._pending: set[asyncio.Task] = set()

    async def send(self, task_id: str, provider: ProviderSpec, text: str,
                   idempotency_key: str) -> SendResult:
        ev = save_evidence(task_id, "message_out", "fixture_messaging", is_fixture=True,
                           extracted={"text": text, "provider_id": provider.id},
                           claim_level=ClaimLevel.MESSAGE_DELIVERED)
        reply = CANNED_REPLIES.get(provider.id)
        if reply and self._on_inbound is not None:
            t = asyncio.create_task(self._reply_later(task_id, provider, reply, idempotency_key))
            self._pending.add(t)
            t.add_done_callback(self._pending.discard)
        return SendResult(provider_ref=f"fx_{idempotency_key}", status="delivered",
                          evidence_ids=[ev.id])

    async def _reply_later(self, task_id: str, provider: ProviderSpec, text: str, key: str) -> None:
        await asyncio.sleep(self.reply_delay_s)
        await self._on_inbound(InboundEvent(
            id=new_id("inb"), source="fixture", external_id=f"reply1:{key}", task_id=task_id,
            provider_id=provider.id, sender_handle=provider.handle, text=text, received_at=utcnow(),
        ))

    async def start(self, on_inbound: Callable[[InboundEvent], Awaitable[None]]) -> None:
        self._on_inbound = on_inbound

    async def stop(self) -> None:
        for t in list(self._pending):
            t.cancel()
        self._on_inbound = None
