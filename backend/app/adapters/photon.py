"""Owner: Ansh. Live Photon messaging adapter — Photon Beta API via `photonhq-api` (iMessage).

How it works (docs: https://photon.codes/docs/beta/get-started/imessage):
- Inbound: a background task polls `list_messages(direction="received")` every PHOTON_POLL_S
  (no public webhook needed). Each text from a configured provider handle becomes an
  InboundEvent(source="photon", external_id=<Photon message id>).
- Outbound: `send_message(spaceId, senderId, content)` with an `idempotency-key` header.
  A shared iMessage line can only reply in a direct Space whose human has texted it since the
  line was assigned — so each provider must text the Orbit line once before Orbit can message
  them. The (spaceId, agent user id) pair is learned from their inbound message.
- Delivery: sent ids are polled with `direction="sent"`; status "delivered" saves a
  delivery_receipt (MESSAGE_DELIVERED). Send itself only ever claims MESSAGE_SUBMITTED.
- Webhooks are not used: Beta webhook signature verification is undocumented (see
  docs/integrations.md), so photon_routes.router stays None.
Only consenting teammates' handles (LIVE_PROVIDER_A/B_HANDLE) are ever messaged. Handles are
masked in logs and message bodies are never logged.
"""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable

import httpx

from app.adapters.base import AdapterUnavailable, mask_handle, normalize_handle
from app.adapters.settings import get_integration_settings
from app.core import evidence
from app.core.config import get_settings
from app.core.schemas import ClaimLevel, InboundEvent, ProviderSpec, SendResult, new_id, utcnow

log = logging.getLogger(__name__)
INBOUND_OVERLAP = timedelta(seconds=10)      # list_messages is eventually consistent
DISCOVERY_LOOKBACK = timedelta(days=7)
MAX_BACKOFF_S = 30.0


# ---------------------------------------------------------------- SDK boundary
@dataclass(frozen=True)
class PhotonMsg:
    id: str
    status: str                       # received | dispatched | accepted | delivered | failed
    sender_handle: str | None
    sender_id: str | None
    receiver_id: str | None           # for inbound: the agent's user id (our senderId for replies)
    space_id: str
    space_kind: str | None
    text: str | None                  # None for non-text content (read receipts, typing, media)
    created_at: datetime
    received_at: datetime | None


def _ts(value: Any) -> datetime | None:
    if not isinstance(value, str):
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def _iso_ms(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def to_photon_msg(item: Any) -> PhotonMsg | None:
    """photon_api PlatformMessage / SentMessage -> PhotonMsg (None if not an iMessage)."""
    m = item.root.root
    if getattr(m, "platform", None) != "imessage":
        return None
    sender = getattr(m.sentBy, "root", None)
    receiver = getattr(getattr(m, "receivedBy", None), "root", None)
    space = m.space.root
    content = m.content
    text = getattr(content, "text", None) if getattr(content, "type", None) == "text" else None
    return PhotonMsg(
        id=m.id, status=m.status,
        sender_handle=getattr(sender, "handle", None), sender_id=getattr(sender, "id", None),
        receiver_id=getattr(receiver, "id", None), space_id=space.id,
        space_kind=getattr(space, "kind", None), text=text, created_at=_ts(m.createdAt),
        received_at=_ts(getattr(m.timestamps, "receivedAt", None)))


class PhotonClient:
    """The only code that touches photonhq-api (it changes often — keep this thin)."""

    def __init__(self, api_key: str, project_id: str,
                 http_client: httpx.AsyncClient | None = None) -> None:
        from photon_api import AsyncPhoton
        self.project_id = project_id
        self._photon = AsyncPhoton(headers={"Authorization": f"Bearer {api_key}"},
                                   client=http_client)

    async def list_messages(self, direction: str, since: datetime) -> list[PhotonMsg]:
        from photon_api.rpc_generated import ListMessagesInput
        query: dict[str, Any] = {"createdSince": _iso_ms(since), "direction": direction,
                                 "order": "asc", "pageSize": 100, "platform": "imessage"}
        out: list[PhotonMsg] = []
        while True:
            page = await self._photon.projects.list_messages(ListMessagesInput.model_validate(
                {"path": {"id": self.project_id}, "query": query}))
            out += [m for m in (to_photon_msg(i) for i in page.items) if m is not None]
            token = page.nextPageToken
            if not isinstance(token, str):
                return out
            query["pageToken"] = token

    async def send_text(self, space_id: str, sender_id: str, text: str,
                        idempotency_key: str) -> PhotonMsg | None:
        from photon_api.generated.models import SendMessageRequest, SendTextContent
        from photon_api.rpc_generated import SendMessageHeader, SendMessageInput, SendMessagePath
        sent = await self._photon.projects.send_message(SendMessageInput(
            path=SendMessagePath(id=self.project_id),
            headers=SendMessageHeader.model_validate({"idempotency-key": idempotency_key}),
            body=SendMessageRequest(spaceId=space_id, senderId=sender_id,
                                    content=SendTextContent(type="text", format="plain", text=text))))
        return to_photon_msg(sent)

    async def close(self) -> None:
        await self._photon.close()


# ---------------------------------------------------------------- adapter
class PhotonMessagingAdapter:
    name = "photon"
    is_fixture = False

    def __init__(self, client: PhotonClient | None = None) -> None:
        settings, isettings = get_settings(), get_integration_settings()
        if not settings.photon_api_key or not isettings.photon_project_id:
            raise AdapterUnavailable("set PHOTON_API_KEY and PHOTON_PROJECT_ID (Photon Beta)")
        if not isettings.photon_project_id.startswith("pho_prj_"):
            raise AdapterUnavailable("PHOTON_PROJECT_ID doesn't look like a Beta project "
                                     "(pho_prj_…); Stable/Spectrum credentials need a Node sidecar")
        self.allowed = {normalize_handle(h) for h in (settings.live_provider_a_handle,
                                                      settings.live_provider_b_handle) if h}
        if not self.allowed:
            raise AdapterUnavailable("set LIVE_PROVIDER_A_HANDLE / LIVE_PROVIDER_B_HANDLE "
                                     "(consenting teammates only)")
        try:
            self.client = client or PhotonClient(settings.photon_api_key,
                                                 isettings.photon_project_id)
        except ImportError as e:
            raise AdapterUnavailable(f"photonhq-api not installed: {e}") from e
        self.poll_s = isettings.photon_poll_s
        self._spaces: dict[str, tuple[str, str]] = {}      # handle -> (space_id, agent user id)
        self._sent: dict[str, SendResult] = {}             # idempotency_key -> result
        self._awaiting_receipt: dict[str, tuple[str, datetime]] = {}   # msg id -> (task, sent at)
        self._seen: set[str] = set()
        self._cursor = utcnow()
        self._on_inbound: Callable[[InboundEvent], Awaitable[None]] | None = None
        self._poller: asyncio.Task | None = None

    # ------------------------------------------------ outbound
    async def send(self, task_id: str, provider: ProviderSpec, text: str,
                   idempotency_key: str) -> SendResult:
        handle = normalize_handle(provider.handle)
        if handle not in self.allowed:
            log.warning("photon refused send to non-provider handle %s", mask_handle(handle))
            return SendResult(status="failed", error="refused: recipient is not a configured "
                              "consenting provider handle (LIVE_PROVIDER_*_HANDLE)")
        if idempotency_key in self._sent:
            return self._sent[idempotency_key]
        try:
            route = self._spaces.get(handle) or await self._discover_space(handle)
        except Exception as e:
            return SendResult(status="failed", error=f"photon lookup failed: {_err(e)}")
        if route is None:
            return SendResult(status="failed", error=(
                f"shared iMessage line can't send first: provider {mask_handle(handle)} must "
                "text the Orbit line once, then retry"))
        space_id, agent_id = route
        try:
            msg = await self.client.send_text(space_id, agent_id, text, f"orbit:{idempotency_key}")
        except Exception as e:
            # Photon dedups on the idempotency-key header, so a later retry with the same key
            # cannot double-send even if this request actually went through.
            log.warning("photon send to %s failed: %s", mask_handle(handle), _err(e))
            return SendResult(status="failed", error=f"photon send failed: {_err(e)}")
        if msg is None:
            return SendResult(status="failed", error="photon returned no message")
        ev = evidence.save_evidence(
            task_id, "message_out", "photon", is_fixture=False,
            extracted={"provider_id": provider.id, "to": mask_handle(handle), "text": text,
                       "channel": "imessage", "photon_message_id": msg.id,
                       "photon_status": msg.status, "space_id": space_id,
                       "idempotency_key": idempotency_key},
            claim_level=ClaimLevel.MESSAGE_SUBMITTED, provider_ref=msg.id)
        evidence_ids = [ev.id]
        if msg.status == "delivered":
            evidence_ids.append(self._save_receipt(task_id, msg).id)
        else:
            self._awaiting_receipt[msg.id] = (task_id, msg.created_at or utcnow())
        result = SendResult(provider_ref=msg.id, evidence_ids=evidence_ids,
                            status="delivered" if msg.status == "delivered" else "submitted")
        self._sent[idempotency_key] = result
        log.info("photon sent %s to %s (%s)", msg.id, mask_handle(handle), msg.status)
        return result

    async def _discover_space(self, handle: str) -> tuple[str, str] | None:
        """Find the direct Space where this provider last texted the Orbit line."""
        for m in reversed(await self.client.list_messages("received", utcnow() - DISCOVERY_LOOKBACK)):
            self._remember_route(m, overwrite=False)
            if handle in self._spaces:
                return self._spaces[handle]
        return None

    def _remember_route(self, m: PhotonMsg, overwrite: bool = True) -> None:
        h = normalize_handle(m.sender_handle or "")
        if h in self.allowed and m.receiver_id and m.space_kind in (None, "direct") \
                and (overwrite or h not in self._spaces):
            self._spaces[h] = (m.space_id, m.receiver_id)

    def _save_receipt(self, task_id: str, m: PhotonMsg):
        return evidence.save_evidence(
            task_id, "delivery_receipt", "photon", is_fixture=False,
            extracted={"photon_message_id": m.id, "photon_status": m.status},
            claim_level=ClaimLevel.MESSAGE_DELIVERED, provider_ref=m.id)

    # ------------------------------------------------ inbound
    async def start(self, on_inbound: Callable[[InboundEvent], Awaitable[None]]) -> None:
        self._on_inbound = on_inbound
        if self._poller is None or self._poller.done():
            self._poller = asyncio.create_task(self._poll_forever(), name="photon-poller")

    async def stop(self) -> None:
        if self._poller is not None:
            self._poller.cancel()
            try:
                await self._poller
            except (asyncio.CancelledError, Exception):
                pass
            self._poller = None
        self._on_inbound = None             # client stays open: the registry reuses this adapter

    async def _poll_forever(self) -> None:
        backoff = self.poll_s
        while True:
            try:
                await self.poll_once()
                backoff = self.poll_s
            except asyncio.CancelledError:
                raise
            except Exception as e:                    # never let the loop die
                backoff = min(backoff * 2, MAX_BACKOFF_S)
                log.warning("photon poll failed (retry in %.0fs): %s", backoff, _err(e))
            await asyncio.sleep(backoff)

    async def poll_once(self) -> None:
        received = await self.client.list_messages("received", self._cursor - INBOUND_OVERLAP)
        for m in received:
            if m.created_at and m.created_at > self._cursor:
                self._cursor = m.created_at
            if m.id in self._seen:
                continue
            self._seen.add(m.id)
            handle = normalize_handle(m.sender_handle or "")
            if handle not in self.allowed:
                continue                              # not a provider: never forwarded or logged
            self._remember_route(m)
            if m.text is None or self._on_inbound is None:
                continue
            await self._on_inbound(InboundEvent(
                id=new_id("inb"), source="photon", external_id=m.id, sender_handle=handle,
                text=m.text, received_at=m.received_at or m.created_at or utcnow(),
                payload={"photon_message_id": m.id, "space_id": m.space_id,
                         "status": m.status, "platform": "imessage"}))
            log.info("photon inbound %s from %s", m.id, mask_handle(handle))
        if self._awaiting_receipt:
            await self._check_receipts()

    async def _check_receipts(self) -> None:
        oldest = min(sent_at for _, sent_at in self._awaiting_receipt.values())
        for m in await self.client.list_messages("sent", oldest - INBOUND_OVERLAP):
            if m.id not in self._awaiting_receipt:
                continue
            task_id, _ = self._awaiting_receipt[m.id]
            if m.status == "delivered":
                self._save_receipt(task_id, m)
                del self._awaiting_receipt[m.id]
            elif m.status == "failed":
                log.warning("photon message %s failed to deliver", m.id)
                del self._awaiting_receipt[m.id]


def _err(e: Exception) -> str:
    """Error text without request bodies (which could contain message text or handles)."""
    status = getattr(e, "status", None)
    request_id = getattr(e, "request_id", None)
    if status is not None:
        return f"{type(e).__name__} status={status} request_id={request_id}"
    return type(e).__name__
