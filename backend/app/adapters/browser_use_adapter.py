"""Owner: Ansh. Stub from CP0 — replace. Live Browser Use adapter against the portal."""
from __future__ import annotations


class BrowserUseAdapter:
    name = "browser_use"
    is_fixture = False

    async def read_availability(self, task_id, provider, day_local, tz):
        raise NotImplementedError("browser_use: Ansh")

    async def submit_booking(self, req):
        raise NotImplementedError("browser_use: Ansh")

    async def find_booking(self, task_id, provider, orbit_ref):
        raise NotImplementedError("browser_use: Ansh")
