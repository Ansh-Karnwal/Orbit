"""Photon adapter: SDK mapping (real photonhq-api models), recipient allow-list, shared-line
bootstrap, idempotency, inbound mapping, delivery receipts, masking."""
from __future__ import annotations

import json
import logging
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import httpx
import pytest

import app.adapters.photon as photon
from app.adapters.base import AdapterUnavailable
from app.adapters.photon import PhotonClient, PhotonMessagingAdapter, PhotonMsg
from app.adapters.settings import IntegrationSettings
from app.core.config import Settings
from app.core.schemas import ClaimLevel

from .fakes import provider

FIX = Path(__file__).parent / "photon"
A_HANDLE, B_HANDLE = "+14155550101", "+14155550102"
PROJECT = "pho_prj_demo0001"


def fixture(name: str) -> dict:
    return json.loads((FIX / f"{name}.json").read_text(encoding="utf-8"))


@pytest.fixture
def configured(monkeypatch):
    def use(project=PROJECT, key="pho_sk_test", a="(415) 555-0101", b="415.555.0102"):
        monkeypatch.setattr(photon, "get_settings", lambda: Settings(
            _env_file=None, photon_api_key=key, live_provider_a_handle=a, live_provider_b_handle=b))
        monkeypatch.setattr(photon, "get_integration_settings", lambda: IntegrationSettings(
            _env_file=None, photon_project_id=project, photon_poll_s=0.01))
    use()
    return use


# ---------------------------------------------------------------- fake SDK boundary
def pmsg(mid, handle=A_HANDLE, text="hi", status="received", kind="direct",
         created="2026-10-17T20:00:05+00:00") -> PhotonMsg:
    t = datetime.fromisoformat(created)
    return PhotonMsg(id=mid, status=status, sender_handle=handle, sender_id="pho_usr_h",
                     receiver_id="pho_usr_agent", space_id=f"pho_spc_{handle[-4:]}",
                     space_kind=kind, text=text, created_at=t, received_at=t)


class FakeClient:
    def __init__(self) -> None:
        self.received: list[PhotonMsg] = []
        self.sent_status: dict[str, str] = {}
        self.sends: list[tuple[str, str, str, str]] = []

    async def list_messages(self, direction, since):
        if direction == "received":
            return list(self.received)
        return [replace(pmsg(mid, status=st), sender_handle=None) for mid, st in self.sent_status.items()]

    async def send_text(self, space_id, sender_id, text, idempotency_key):
        mid = f"pho_msg_out{len(self.sends) + 1}"
        self.sends.append((space_id, sender_id, text, idempotency_key))
        self.sent_status[mid] = "dispatched"
        return replace(pmsg(mid, status="dispatched"), sender_handle=None)

    async def close(self):
        return None


class Collector:
    def __init__(self):
        self.events = []

    async def __call__(self, e):
        self.events.append(e)


def adapter_with(fake: FakeClient) -> PhotonMessagingAdapter:
    a = PhotonMessagingAdapter(client=fake)
    a._cursor = datetime(2026, 10, 17, 19, 0, tzinfo=timezone.utc)
    return a


# ---------------------------------------------------------------- SDK mapping
def test_mapping_from_real_sdk_models():
    from photon_api.generated.models import MessagePage
    msgs = [photon.to_photon_msg(i) for i in MessagePage.model_validate(fixture("received_page")).items]
    m = msgs[0]
    assert (m.id, m.status, m.sender_handle, m.space_id, m.receiver_id, m.space_kind) == (
        "pho_msg_in1", "received", A_HANDLE, "pho_spc_a1", "pho_usr_agent", "direct")
    assert m.text.startswith("Hi! Dishwasher repair visit is $120.")
    assert m.received_at == datetime(2026, 10, 17, 20, 0, 5, tzinfo=timezone.utc)


async def test_client_talks_documented_rest_shape():
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        if request.method == "POST":
            return httpx.Response(202, json=fixture("send_response"))
        page = "received_page" if request.url.params["direction"] == "received" else "sent_page"
        return httpx.Response(200, json=fixture(page))

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as http:
        client = PhotonClient("pho_sk_test", PROJECT, http_client=http)
        received = await client.list_messages("received", datetime(2026, 10, 17, tzinfo=timezone.utc))
        sent = await client.send_text("pho_spc_a1", "pho_usr_agent", "Hello", "orbit:k1")
    assert [m.id for m in received] == ["pho_msg_in1", "pho_msg_in2"]
    assert sent.id == "pho_msg_out2" and sent.status == "dispatched"
    get, post = seen[0], seen[-1]
    assert get.url.path == f"/v1/projects/{PROJECT}/messages"
    assert get.url.params["createdSince"] == "2026-10-17T00:00:00.000Z"
    assert get.headers["authorization"] == "Bearer pho_sk_test"
    assert post.headers["idempotency-key"] == "orbit:k1"
    body = json.loads(post.content)
    assert body == {"spaceId": "pho_spc_a1", "senderId": "pho_usr_agent",
                    "content": {"type": "text", "format": "plain", "text": "Hello"}}


# ---------------------------------------------------------------- construction
def test_unavailable_without_credentials(configured):
    configured(key="")
    with pytest.raises(AdapterUnavailable, match="PHOTON_API_KEY"):
        PhotonMessagingAdapter(client=FakeClient())


def test_unavailable_with_stable_project_id(configured):
    configured(project="0f3c-stable-project")
    with pytest.raises(AdapterUnavailable, match="Beta"):
        PhotonMessagingAdapter(client=FakeClient())


def test_unavailable_without_provider_handles(configured):
    configured(a="", b="")
    with pytest.raises(AdapterUnavailable, match="LIVE_PROVIDER"):
        PhotonMessagingAdapter(client=FakeClient())


# ---------------------------------------------------------------- outbound
async def test_refuses_non_provider_recipient(configured, ev):
    fake = FakeClient()
    res = await adapter_with(fake).send("tsk", provider("provider_a", handle="+19995550199"), "hi", "k")
    assert res.status == "failed" and "refused" in res.error
    assert fake.sends == [] and ev.items == []


async def test_cannot_send_first_on_shared_line(configured, ev):
    res = await adapter_with(FakeClient()).send("tsk", provider("provider_a", handle=A_HANDLE), "hi", "k")
    assert res.status == "failed" and "can't send first" in res.error
    assert "0101" in res.error and "555-0101" not in res.error and A_HANDLE not in res.error


async def test_send_after_provider_texted_first(configured, ev):
    fake = FakeClient()
    fake.received = [pmsg("pho_msg_hello", handle=A_HANDLE, text="Hi, this is Ace")]
    a = adapter_with(fake)
    res = await a.send("tsk", provider("provider_a", handle="415-555-0101"), "Quote please?", "k1")
    assert res.status == "submitted" and res.provider_ref == "pho_msg_out1"
    assert fake.sends == [("pho_spc_0101", "pho_usr_agent", "Quote please?", "orbit:k1")]
    out = ev.items[0]
    assert out.kind == "message_out" and out.is_fixture is False and out.source == "photon"
    assert out.claim_level == ClaimLevel.MESSAGE_SUBMITTED and out.provider_ref == "pho_msg_out1"
    assert A_HANDLE not in json.dumps(out.extracted)
    again = await a.send("tsk", provider("provider_a", handle=A_HANDLE), "Quote please?", "k1")
    assert again == res and len(fake.sends) == 1


# ---------------------------------------------------------------- inbound + receipts
async def test_poll_forwards_provider_texts_only(configured, ev):
    fake = FakeClient()
    fake.received = [pmsg("m1", handle=A_HANDLE, text="$120, Tue 3-4pm"),
                     pmsg("m2", handle="+19995550199", text="stranger"),
                     pmsg("m3", handle=B_HANDLE, text=None),             # read receipt / media
                     pmsg("m4", handle=B_HANDLE, text="$145 incl travel")]
    a, got = adapter_with(fake), Collector()
    await a.start(got)
    a._poller.cancel()
    await a.poll_once()
    await a.poll_once()                                                 # overlap: no duplicates
    assert [(e.source, e.external_id, e.sender_handle, e.text) for e in got.events] == [
        ("photon", "m1", A_HANDLE, "$120, Tue 3-4pm"), ("photon", "m4", B_HANDLE, "$145 incl travel")]
    assert "stranger" not in json.dumps([e.payload for e in got.events])
    assert set(a._spaces) == {A_HANDLE, B_HANDLE}


async def test_delivery_receipt_saved_when_delivered(configured, ev):
    fake = FakeClient()
    fake.received = [pmsg("hello", handle=A_HANDLE)]
    a = adapter_with(fake)
    res = await a.send("tsk", provider("provider_a", handle=A_HANDLE), "hi", "k1")
    await a.poll_once()
    assert ev.of_kind("delivery_receipt") == []
    fake.sent_status[res.provider_ref] = "delivered"
    await a.poll_once()
    receipt = ev.of_kind("delivery_receipt")[0]
    assert receipt.claim_level == ClaimLevel.MESSAGE_DELIVERED and receipt.provider_ref == res.provider_ref
    await a.poll_once()
    assert len(ev.of_kind("delivery_receipt")) == 1


async def test_logs_never_contain_full_numbers_or_bodies(configured, ev, caplog):
    caplog.set_level(logging.DEBUG)
    fake = FakeClient()
    fake.received = [pmsg("m1", handle=A_HANDLE, text="secret quote body")]
    a = adapter_with(fake)
    a._on_inbound = Collector()
    await a.poll_once()
    await a.send("tsk", provider("provider_a", handle=A_HANDLE), "outbound secret body", "k1")
    await a.send("tsk", provider("provider_a", handle="+19995550199"), "x", "k2")
    assert caplog.records
    assert "5550101" not in caplog.text and "5550199" not in caplog.text
    assert "secret" not in caplog.text
