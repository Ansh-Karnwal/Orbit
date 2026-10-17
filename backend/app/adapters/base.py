"""Owner: Ansh. Stub from CP0 — replace. Adapter protocols (contract §3.5)."""
from __future__ import annotations

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
