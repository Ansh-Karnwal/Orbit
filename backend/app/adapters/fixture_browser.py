"""Owner: Ansh. Offline browser: talks to the real portal's JSON API over HTTP (no browser, no
screenshots). Everything it produces is is_fixture=True. It never "fixes" what the portal returns —
a mismatched confirmation is passed through for the verifier to catch.
"""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any
from urllib.parse import urlsplit

import httpx

from app.core import evidence
from app.core.config import get_settings
from app.core.schemas import (AvailabilityResult, BookingRequest, BookingResult, ClaimLevel,
                              ConfirmationExtract, ProviderSpec, Slot)

NO_SCREENSHOTS = "none (fixture adapter uses the portal JSON API, no browser)"
READ_TIMEOUT_S = 10.0
BOOK_TIMEOUT_S = 15.0                 # well under the portal's 90 s timeout_after_submit sleep
NOT_SENT = (httpx.ConnectError, httpx.ConnectTimeout, httpx.PoolTimeout, httpx.UnsupportedProtocol)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def origin(url: str) -> str:
    parts = urlsplit(url)
    return f"{parts.scheme}://{parts.netloc}"


def extract_from_booking(b: dict[str, Any]) -> ConfirmationExtract:
    return ConfirmationExtract(
        confirmation_id=b["confirmation_id"], provider_id=b["provider_id"], service=b["service"],
        slot_start=b["slot_start"], slot_end=b["slot_end"],
        visit_charge_cents=int(b["visit_charge_cents"]),
        cancellation_terms=b["cancellation_terms"], orbit_ref=b.get("reference", ""))


class FixtureBrowserAdapter:
    name = "fixture_browser"
    is_fixture = True

    def __init__(self, base_url: str | None = None, client: httpx.AsyncClient | None = None) -> None:
        self._base_url = base_url
        self._client = client

    def _base(self, provider: ProviderSpec | None = None) -> str:
        if self._base_url:
            return self._base_url.rstrip("/")
        if provider is not None and provider.portal_url:
            return origin(provider.portal_url)
        return get_settings().portal_base_url.rstrip("/")

    async def _request(self, method: str, url: str, timeout: float, **kw: Any) -> httpx.Response:
        if self._client is not None:
            return await self._client.request(method, url, timeout=timeout, **kw)
        async with httpx.AsyncClient() as c:
            return await c.request(method, url, timeout=timeout, **kw)

    async def read_availability(self, task_id: str, provider: ProviderSpec, day_local: date,
                                tz: str) -> AvailabilityResult:
        url = f"{self._base(provider)}/api/p/{provider.id}/slots"
        try:
            r = await self._request("GET", url, READ_TIMEOUT_S,
                                    params={"date": day_local.isoformat(), "demo_run_id": task_id})
            r.raise_for_status()
        except httpx.HTTPError as e:
            return AvailabilityResult(slots=[], error=f"portal availability failed: {e!r}")
        slots = [Slot(start=s["start"], end=s["end"], label=s.get("label", ""))
                 for s in r.json()["slots"]]
        ev = evidence.save_evidence(
            task_id, "availability", "fixture_browser", is_fixture=True,
            extracted={"provider_id": provider.id, "date": day_local.isoformat(), "timezone": tz,
                       "slots": [s.model_dump(mode="json") for s in slots], "url": url,
                       "demo_run_id": task_id,
                       "screenshots": NO_SCREENSHOTS},
            claim_level=ClaimLevel.SLOT_OFFERED)
        return AvailabilityResult(slots=slots, evidence_ids=[ev.id])

    async def submit_booking(self, req: BookingRequest) -> BookingResult:
        p = req.proposal
        url = f"{self._base()}/api/p/{p.provider_id}/book"
        body = {"slot_start": iso_z(p.slot_start), "service": p.service,
                "customer_name": req.customer_name, "customer_contact": req.customer_contact,
                "reference": req.orbit_ref, "notes": f"Booked by Orbit (approval {req.approval_id})",
                "demo_run_id": req.task_id}
        try:
            r = await self._request("POST", url, BOOK_TIMEOUT_S, json=body)
        except NOT_SENT as e:
            return BookingResult(status="failed", error=f"portal unreachable, nothing submitted: {e!r}")
        except httpx.TransportError as e:
            # The request may have reached the portal: never retry here, let the coordinator reconcile.
            return BookingResult(status="ambiguous",
                                 error=f"no response after submitting booking: {e!r}")

        if r.status_code == 201:
            conf = extract_from_booking(r.json()["booking"])
            ev = evidence.save_evidence(
                req.task_id, "portal_confirmation", "fixture_browser", is_fixture=True,
                extracted={**conf.model_dump(mode="json"), "screenshots": NO_SCREENSHOTS},
                claim_level=ClaimLevel.BOOKING_REQUEST_SUBMITTED, provider_ref=conf.confirmation_id)
            return BookingResult(status="confirmed", confirmation=conf, evidence_ids=[ev.id])
        if r.status_code == 202:
            ev = evidence.save_evidence(
                req.task_id, "portal_confirmation", "fixture_browser", is_fixture=True,
                extracted={"confirmation_id": None, "provider_id": p.provider_id,
                           "orbit_ref": req.orbit_ref, "portal_message": r.json().get("message", ""),
                           "screenshots": NO_SCREENSHOTS},
                claim_level=ClaimLevel.BOOKING_REQUEST_SUBMITTED)
            return BookingResult(status="submitted_unconfirmed", evidence_ids=[ev.id],
                                 error="portal accepted the request but returned no confirmation id")
        detail = r.json().get("error", r.text[:200]) if r.headers.get("content-type", "").startswith(
            "application/json") else r.text[:200]
        return BookingResult(status="failed", error=f"portal returned {r.status_code}: {detail}")

    async def find_booking(self, task_id: str, provider: ProviderSpec,
                           orbit_ref: str) -> BookingResult | None:
        """Returns the booking with this reference, None if the portal has none, or an
        `ambiguous` result if the portal couldn't be asked (so callers never resubmit blindly)."""
        url = f"{self._base(provider)}/api/p/{provider.id}/bookings"
        try:
            r = await self._request("GET", url, READ_TIMEOUT_S,
                                    params={"ref": orbit_ref, "demo_run_id": task_id})
            r.raise_for_status()
        except httpx.HTTPError as e:
            return BookingResult(status="ambiguous", error=f"booking lookup failed: {e!r}")
        bookings = r.json()["bookings"]
        if not bookings:
            return None
        conf = extract_from_booking(bookings[0])
        ev = evidence.save_evidence(
            task_id, "portal_confirmation", "fixture_browser", is_fixture=True,
            extracted={**conf.model_dump(mode="json"), "via": "lookup",
                       "match_count": len(bookings), "screenshots": NO_SCREENSHOTS},
            claim_level=ClaimLevel.BOOKING_REQUEST_SUBMITTED, provider_ref=conf.confirmation_id)
        return BookingResult(status="confirmed", confirmation=conf, evidence_ids=[ev.id])
