"""Owner: Ansh. Adapter protocols (contract §3.5) and shared helpers."""
from __future__ import annotations

import re
from datetime import date
from typing import Awaitable, Callable, Protocol

from app.core.schemas import (AdapterName, AvailabilityResult, BookingRequest, BookingResult,
                              InboundEvent, ProviderSpec, SendResult)


class MessagingAdapter(Protocol):
    name: AdapterName
    is_fixture: bool

    async def send(self, task_id: str, provider: ProviderSpec, text: str,
                   idempotency_key: str) -> SendResult: ...

    async def start(self, on_inbound: Callable[[InboundEvent], Awaitable[None]]) -> None: ...

    async def stop(self) -> None: ...


class BrowserAdapter(Protocol):
    name: AdapterName
    is_fixture: bool

    async def read_availability(self, task_id: str, provider: ProviderSpec, day_local: date,
                                tz: str) -> AvailabilityResult: ...

    async def submit_booking(self, req: BookingRequest) -> BookingResult: ...

    async def find_booking(self, task_id: str, provider: ProviderSpec,
                           orbit_ref: str) -> BookingResult | None: ...


class AdapterUnavailable(Exception):
    """Raised by a live adapter's constructor when it can't run (missing key, SDK, bridge…).
    The registry turns it into a BlockedAdapter and reports "blocked: <reason>"."""


# ---------------------------------------------------------------- handles
def normalize_handle(handle: str, default_country: str = "1") -> str:
    """Canonical form for sending and matching: E.164 for phone numbers, lowercased emails,
    anything else (e.g. "fixture:provider_a") unchanged apart from whitespace."""
    h = handle.strip()
    if not h or ":" in h:
        return h
    if "@" in h:
        return h.lower()
    digits = re.sub(r"\D", "", h)
    if not digits:
        return h
    if h.startswith("+"):
        return "+" + digits
    if len(digits) == 10:                      # bare national number, assume default country
        return f"+{default_country}{digits}"
    if len(digits) == 11 and digits.startswith(default_country):
        return "+" + digits
    return "+" + digits


def mask_handle(handle: str | None) -> str:
    """Safe-to-log form: +1•••••1234, j•••@example.com. Never log full handles."""
    if not handle:
        return "<none>"
    h = normalize_handle(handle)
    if h.startswith("fixture:"):
        return h
    if "@" in h:
        user, _, domain = h.partition("@")
        return f"{user[:1]}•••@{domain}"
    if h.startswith("+") and len(h) > 6:
        cc = h[1:-10] if len(h) > 11 else h[1:2]
        return f"+{cc}•••••{h[-4:]}"
    return "•••" + h[-2:]
