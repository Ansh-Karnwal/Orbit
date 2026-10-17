"""Owner: Victor. Callback messaging adapters call for every inbound message. Stub from CP0 — Phase 4."""
from __future__ import annotations

from app.core.schemas import InboundEvent


async def handle_inbound(ev: InboundEvent) -> None:
    raise NotImplementedError("inbound.handle_inbound: Phase 4")
