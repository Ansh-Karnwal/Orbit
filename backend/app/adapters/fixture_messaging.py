"""Owner: Ansh. Offline messaging: scripted provider replies from demo/fixture_script.json.

Everything this adapter produces is is_fixture=True. Nothing is sent anywhere.
"""
from __future__ import annotations

import asyncio
import json
import logging
from pathlib import Path
from typing import Any, Awaitable, Callable

from app.core import evidence
from app.core.config import get_settings
from app.core.schemas import ClaimLevel, InboundEvent, ProviderSpec, SendResult, new_id, utcnow

log = logging.getLogger(__name__)
SCRIPT_PATH = Path(__file__).resolve().parents[3] / "demo" / "fixture_script.json"


def load_script(path: Path = SCRIPT_PATH) -> dict[str, list[dict[str, Any]]]:
    raw = json.loads(path.read_text(encoding="utf-8"))
    return {k: v for k, v in raw.items() if not k.startswith("_")}


class FixtureMessagingAdapter:
    name = "fixture_messaging"
    is_fixture = True

    def __init__(self, script: dict[str, list[dict[str, Any]]] | None = None,
                 time_scale: float = 1.0, auto_followups: bool | None = None) -> None:
        self.script = script if script is not None else load_script()
        self.time_scale = time_scale                       # 0 in tests = replies fire immediately
        self.auto_followups = (get_settings().fixture_auto_followups
                               if auto_followups is None else auto_followups)
        self._on_inbound: Callable[[InboundEvent], Awaitable[None]] | None = None
        self._sent: dict[str, SendResult] = {}             # idempotency_key -> result
        self._scripted: set[tuple[str, str]] = set()       # (task_id, provider_id) already replying
        self._pending: set[asyncio.Task] = set()

    async def send(self, task_id: str, provider: ProviderSpec, text: str,
                   idempotency_key: str) -> SendResult:
        if idempotency_key in self._sent:
            return self._sent[idempotency_key]
        provider_ref = f"fx_msg_{len(self._sent) + 1}_{provider.id}"
        ev = evidence.save_evidence(
            task_id, "message_out", "fixture_messaging", is_fixture=True,
            extracted={"provider_id": provider.id, "to": provider.handle, "text": text,
                       "channel": "fixture", "idempotency_key": idempotency_key},
            claim_level=ClaimLevel.MESSAGE_SUBMITTED, provider_ref=provider_ref)
        result = SendResult(provider_ref=provider_ref, status="delivered", evidence_ids=[ev.id])
        self._sent[idempotency_key] = result
        if (task_id, provider.id) not in self._scripted:
            self._scripted.add((task_id, provider.id))
            self._schedule_replies(task_id, provider)
        return result

    def _schedule_replies(self, task_id: str, provider: ProviderSpec) -> None:
        for n, entry in enumerate(self.script.get(provider.id, []), start=1):
            if entry.get("trigger", "on_inquiry") == "auto_followup" and not self.auto_followups:
                continue
            t = asyncio.create_task(self._reply_later(task_id, provider, n, entry))
            self._pending.add(t)
            t.add_done_callback(self._pending.discard)

    async def _reply_later(self, task_id: str, provider: ProviderSpec, n: int,
                           entry: dict[str, Any]) -> None:
        await asyncio.sleep(float(entry.get("after_s", 0)) * self.time_scale)
        on_inbound = self._on_inbound                      # resolved at fire time, not send time
        if on_inbound is None:
            log.warning("fixture reply %s:%s dropped: adapter not started", provider.id, n)
            return
        await on_inbound(InboundEvent(
            id=new_id("inb"), source="fixture", external_id=f"fx:{task_id}:{provider.id}:{n}",
            task_id=task_id, provider_id=provider.id, sender_handle=provider.handle,
            text=entry["text"], payload={"trigger": entry.get("trigger", "on_inquiry"), "n": n},
            received_at=utcnow(),
        ))

    async def start(self, on_inbound: Callable[[InboundEvent], Awaitable[None]]) -> None:
        self._on_inbound = on_inbound

    async def stop(self) -> None:
        for t in list(self._pending):
            t.cancel()
        self._on_inbound = None

    def reset(self) -> None:
        """Forget sent keys and pending replies (used by /demo/reset)."""
        for t in list(self._pending):
            t.cancel()
        self._sent.clear()
        self._scripted.clear()
