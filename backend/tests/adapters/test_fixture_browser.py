"""FixtureBrowserAdapter against the real portal app (in-process), incl. fault modes."""
from __future__ import annotations

from datetime import date

import httpx

from app.adapters.fixture_browser import FixtureBrowserAdapter
from app.core.schemas import ClaimLevel

from .fakes import PORTAL, booking_request, provider


async def test_read_availability(ev, portal_client):
    adapter = FixtureBrowserAdapter(client=portal_client)
    res = await adapter.read_availability("tsk_test", provider("provider_b"), date(2026, 10, 20),
                                          "America/Los_Angeles")
    assert res.error is None
    assert [s.start.isoformat() for s in res.slots] == ["2026-10-20T21:30:00+00:00",
                                                        "2026-10-20T23:00:00+00:00"]
    item = ev.items[0]
    assert item.kind == "availability" and item.is_fixture and item.claim_level == ClaimLevel.SLOT_OFFERED
    assert "none" in item.extracted["screenshots"] and res.evidence_ids == [item.id]


async def test_submit_booking_confirmed(ev, portal_client):
    res = await FixtureBrowserAdapter(client=portal_client).submit_booking(booking_request())
    assert res.status == "confirmed"
    c = res.confirmation
    assert c.confirmation_id.startswith("BK-") and c.orbit_ref == "ORB-test0001"
    assert c.visit_charge_cents == 14500 and c.slot_start.isoformat() == "2026-10-20T21:30:00+00:00"
    item = ev.of_kind("portal_confirmation")[0]
    assert item.is_fixture and item.claim_level == ClaimLevel.BOOKING_REQUEST_SUBMITTED
    assert item.provider_ref == c.confirmation_id


async def test_mismatch_is_passed_through_unchanged(ev, portal_client):
    await portal_client.post("/admin/fault", json={"mode": "mismatch"})
    res = await FixtureBrowserAdapter(client=portal_client).submit_booking(booking_request())
    assert res.status == "confirmed"
    assert res.confirmation.visit_charge_cents == 16500
    assert res.confirmation.slot_start.isoformat() == "2026-10-21T00:30:00+00:00"


async def test_no_confirmation_is_submitted_unconfirmed(ev, portal_client):
    await portal_client.post("/admin/fault", json={"mode": "no_confirmation"})
    res = await FixtureBrowserAdapter(client=portal_client).submit_booking(booking_request())
    assert res.status == "submitted_unconfirmed" and res.confirmation is None
    assert ev.of_kind("portal_confirmation")[0].extracted["confirmation_id"] is None


async def test_down_is_failed(ev, portal_client):
    await portal_client.post("/admin/fault", json={"mode": "down"})
    res = await FixtureBrowserAdapter(client=portal_client).submit_booking(booking_request())
    assert res.status == "failed" and "503" in res.error


async def test_taken_slot_is_failed(ev, portal_client):
    adapter = FixtureBrowserAdapter(client=portal_client)
    assert (await adapter.submit_booking(booking_request("ORB-first"))).status == "confirmed"
    res = await adapter.submit_booking(booking_request("ORB-second"))
    assert res.status == "failed" and "slot_unavailable" in res.error


async def test_unreachable_portal_is_failed_not_ambiguous(ev):
    def refuse(request):
        raise httpx.ConnectError("connection refused", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(refuse)) as c:
        res = await FixtureBrowserAdapter(client=c).submit_booking(booking_request())
    assert res.status == "failed"


async def test_timeout_after_submit_is_ambiguous_then_reconciled(ev, portal_app):
    """Portal records the booking but the response is lost: adapter must say ambiguous (no retry),
    and find_booking must then find exactly the booking that was made (A12)."""
    asgi = httpx.ASGITransport(app=portal_app)
    posts = 0

    async def lose_post_responses(request: httpx.Request) -> httpx.Response:
        nonlocal posts
        response = await asgi.handle_async_request(request)
        if request.method == "POST":
            posts += 1
            await response.aread()
            raise httpx.ReadTimeout("timed out waiting for portal", request=request)
        return response

    async with httpx.AsyncClient(transport=httpx.MockTransport(lose_post_responses),
                                 base_url=PORTAL) as c:
        adapter = FixtureBrowserAdapter(client=c)
        res = await adapter.submit_booking(booking_request("ORB-amb1"))
        assert res.status == "ambiguous" and res.confirmation is None and posts == 1
        assert ev.of_kind("portal_confirmation") == []

        found = await adapter.find_booking("tsk_test", provider("provider_b"), "ORB-amb1")
        assert found is not None and found.status == "confirmed"
        assert found.confirmation.orbit_ref == "ORB-amb1"
        assert found.confirmation.slot_start.isoformat() == "2026-10-20T21:30:00+00:00"
        assert ev.of_kind("portal_confirmation")[0].extracted["via"] == "lookup"
        state = (await c.get("/admin/state")).json()
        assert len(state["bookings"]) == 1                     # no duplicate


async def test_find_booking_none_when_absent(ev, portal_client):
    adapter = FixtureBrowserAdapter(client=portal_client)
    assert await adapter.find_booking("tsk_test", provider("provider_b"), "ORB-missing") is None


async def test_find_booking_lookup_error_is_ambiguous_not_none(ev):
    def boom(request):
        raise httpx.ConnectError("down", request=request)
    async with httpx.AsyncClient(transport=httpx.MockTransport(boom)) as c:
        res = await FixtureBrowserAdapter(client=c).find_booking(
            "tsk_test", provider("provider_b"), "ORB-x")
    assert res is not None and res.status == "ambiguous"
