"""Worker loop + fixture messaging callbacks drive a seeded task to AWAITING_APPROVAL unattended."""
from __future__ import annotations

import asyncio

from app.adapters import registry
from app.adapters.fixture_messaging import FixtureMessagingAdapter
from app.core import repo, worker
from app.core.schemas import TaskStatus as S


async def _wait_for(pred, timeout: float = 10.0) -> None:
    deadline = asyncio.get_running_loop().time() + timeout
    while not pred():
        assert asyncio.get_running_loop().time() < deadline, "timed out"
        await asyncio.sleep(0.02)


async def test_worker_runs_task_to_approval(task, env, monkeypatch):
    monkeypatch.setattr(registry, "_messaging", FixtureMessagingAdapter(reply_delay_s=0.05))
    monkeypatch.setattr(worker, "TICK_INTERVAL_S", 0.05)
    await worker.start()
    try:
        worker.wake(task.id)
        await _wait_for(lambda: repo.get_task(task.id).status == S.AWAITING_APPROVAL)
    finally:
        await worker.stop()
    a = repo.get_latest_approval(task.id)
    assert a.proposal.provider_id == "provider_a" and a.status == "requested"
    assert len(repo.list_inbound(task.id)) == 2


async def test_worker_survives_a_failing_tick(task, env, monkeypatch):
    from app.core import coordinator
    calls = []

    async def boom(task_id):
        calls.append(task_id)
        raise RuntimeError("kaboom")
    monkeypatch.setattr(coordinator, "tick", boom)
    monkeypatch.setattr(worker, "TICK_INTERVAL_S", 0.02)
    await worker.start()
    try:
        await _wait_for(lambda: len(calls) >= 3)
    finally:
        await worker.stop()
    errors = [e for e in repo.list_timeline(task.id) if e.type == "error"]
    assert len(errors) == 1 and errors[0].data["error"] == "RuntimeError"
