"""Manual CP2 smoke test: real Photon (Beta) round trip with a consenting teammate.

1. Put PHOTON_API_KEY, PHOTON_PROJECT_ID, LIVE_PROVIDER_A_HANDLE in .env.
2. Run:  cd backend && RUN_LIVE=1 ../.venv/bin/python -m pytest -s tests/adapters/test_live_photon.py
3. When prompted, the teammate texts anything to the Orbit line (shared lines can't send first),
   then replies to Orbit's message.
"""
from __future__ import annotations

import asyncio
import time

import pytest

from app.adapters.base import normalize_handle
from app.adapters.photon import PhotonMessagingAdapter
from app.core.config import get_settings
from app.core.schemas import ProviderSpec

pytestmark = pytest.mark.live_photon


async def wait_for(predicate, timeout_s: float) -> bool:
    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if predicate():
            return True
        await asyncio.sleep(1)
    return False


async def test_live_round_trip(ev):
    handle = normalize_handle(get_settings().live_provider_a_handle)
    provider = ProviderSpec(id="provider_a", name="Ace Appliance Repair", channel="imessage",
                            handle=handle)
    adapter, inbound = PhotonMessagingAdapter(), []

    async def collect(e):
        inbound.append(e)

    await adapter.start(collect)
    try:
        print("\n>>> Teammate A: text anything to the Orbit line now (120 s)…")
        assert await wait_for(lambda: inbound, 120), "no inbound message from provider A"
        res = await adapter.send("tsk_live", provider,
                                 "Orbit live test: please reply with any message.",
                                 f"live-smoke-{int(time.time())}")
        print("send:", res.model_dump(mode="json"))
        assert res.status in ("submitted", "delivered") and res.provider_ref
        n = len(inbound)
        print(">>> Teammate A: reply to Orbit's message now (120 s)…")
        assert await wait_for(lambda: len(inbound) > n, 120), "no reply received"
        print("reply external_id:", inbound[-1].external_id)
        await wait_for(lambda: ev.of_kind("delivery_receipt"), 30)
        print("delivery receipts:", [e.provider_ref for e in ev.of_kind("delivery_receipt")])
    finally:
        await adapter.stop()
