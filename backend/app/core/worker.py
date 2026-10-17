"""Owner: Victor. Durable background worker: one asyncio loop that ticks every active task on
wake() or every second. At most one tick per task runs at a time; a wake during a tick queues
one re-run. A failing tick is logged + emitted as `error` and never kills the loop."""
from __future__ import annotations

import asyncio
import logging

from app.adapters import registry
from app.core import coordinator, repo

log = logging.getLogger("orbit.worker")

TICK_INTERVAL_S = 1.0

_loop: asyncio.AbstractEventLoop | None = None
_event: asyncio.Event | None = None
_main: asyncio.Task | None = None
_inflight: set[asyncio.Task] = set()
_running: set[str] = set()
_rerun: set[str] = set()
_last_error: dict[str, str] = {}


def wake(task_id: str | None = None) -> None:
    """Thread-safe. Ask the worker to tick now (no-op if the worker isn't running)."""
    if _loop is None or _event is None:
        return
    try:
        _loop.call_soon_threadsafe(_event.set)
    except RuntimeError:          # loop already closed
        pass


async def start() -> None:
    global _loop, _event, _main
    if _main is not None:
        return
    from app.core.inbound import handle_inbound
    _loop, _event = asyncio.get_running_loop(), asyncio.Event()
    await registry.messaging().start(handle_inbound)
    _main = asyncio.create_task(_run(), name="orbit-worker")
    _event.set()


async def stop() -> None:
    global _loop, _event, _main
    if _main is None:
        return
    _main.cancel()
    for t in list(_inflight):
        t.cancel()
    await asyncio.gather(_main, *_inflight, return_exceptions=True)
    await registry.messaging().stop()
    _loop = _event = _main = None
    _running.clear()
    _rerun.clear()


async def _run() -> None:
    while True:
        try:
            await asyncio.wait_for(_event.wait(), timeout=TICK_INTERVAL_S)
        except TimeoutError:
            pass
        _event.clear()
        try:
            for task in repo.list_active_tasks():
                _schedule(task.id)
        except Exception:
            log.exception("worker: listing active tasks failed")


def _schedule(task_id: str) -> None:
    if task_id in _running:
        _rerun.add(task_id)
        return
    _running.add(task_id)
    t = asyncio.create_task(_tick_loop(task_id), name=f"tick-{task_id}")
    _inflight.add(t)
    t.add_done_callback(_inflight.discard)


async def _tick_loop(task_id: str) -> None:
    try:
        while True:
            _rerun.discard(task_id)
            await _tick_safe(task_id)
            if task_id not in _rerun:
                return
    finally:
        _running.discard(task_id)


async def _tick_safe(task_id: str) -> None:
    try:
        await coordinator.tick(task_id)
        _last_error.pop(task_id, None)
    except asyncio.CancelledError:
        raise
    except Exception as e:
        log.exception("tick failed for task %s", task_id)
        detail = f"{type(e).__name__}: {e}"[:300]
        if _last_error.get(task_id) != detail:          # don't spam the timeline every second
            _last_error[task_id] = detail
            try:
                repo.emit(task_id, "error", "Internal error while coordinating; will retry",
                          {"error": type(e).__name__, "detail": detail})
            except Exception:
                log.exception("could not emit error event for %s", task_id)
