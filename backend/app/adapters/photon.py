"""Owner: Ansh. Stub from CP0 — replace. Live Photon messaging adapter."""
from __future__ import annotations


class PhotonMessagingAdapter:
    name = "photon"
    is_fixture = False

    async def send(self, task_id, provider, text, idempotency_key):
        raise NotImplementedError("photon: Ansh")

    async def start(self, on_inbound) -> None:
        raise NotImplementedError("photon: Ansh")

    async def stop(self) -> None:
        return None
