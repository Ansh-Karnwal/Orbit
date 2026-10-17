"""Manual CP2 smoke test: real Browser Use run against a running portal.

    cd portal && ../.venv/bin/python -m uvicorn main:app --port 8100     # terminal 1
    curl -X POST localhost:8100/admin/reset
    cd backend && RUN_LIVE=1 BROWSER_USE_API_KEY=... ../.venv/bin/python -m pytest -s \
        tests/adapters/test_live_browser_use.py
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
import pytest

from app.adapters.browser_use_adapter import BrowserUseAdapter
from app.core.config import get_settings
from app.core.schemas import ProviderSpec

from .fakes import booking_request

pytestmark = pytest.mark.live_browser_use
LA = ZoneInfo("America/Los_Angeles")


def next_weekday_after_today() -> date:
    d = datetime.now(LA).date() + timedelta(days=1)
    while d.weekday() >= 5:
        d += timedelta(days=1)
    return d


async def test_live_read_and_book(ev):
    base = get_settings().portal_base_url.rstrip("/")
    httpx.post(f"{base}/admin/reset").raise_for_status()
    day = next_weekday_after_today()
    provider = ProviderSpec(id="provider_b", name="Bayside Appliance Service", handle="x",
                            portal_url=f"{base}/p/provider_b")
    adapter = BrowserUseAdapter()

    avail = await adapter.read_availability("tsk_live", provider, day, "America/Los_Angeles")
    print("availability:", avail.model_dump(mode="json"))
    assert avail.error is None and avail.slots

    start = datetime.combine(day, time(14, 30), LA)
    req = booking_request(f"ORB-live{day:%m%d}", slot_start=start.isoformat(),
                          slot_end=(start + timedelta(hours=1)).isoformat())
    res = await adapter.submit_booking(req)
    print("booking:", res.model_dump(mode="json"))
    assert res.status == "confirmed" and res.confirmation.orbit_ref == req.orbit_ref
    kinds = {e.kind for e in ev.items}
    assert {"screenshot", "browser_trace", "portal_confirmation"} <= kinds
    assert all(e.is_fixture is False for e in ev.items)

    found = await adapter.find_booking("tsk_live", provider, req.orbit_ref)
    assert found and found.confirmation.confirmation_id == res.confirmation.confirmation_id
