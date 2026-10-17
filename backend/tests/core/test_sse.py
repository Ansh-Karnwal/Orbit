"""SSE stream semantics: replay seq > after_seq, then live; Last-Event-ID resume; no duplicates
or gaps even when live events are published out of order."""
from __future__ import annotations

import asyncio

from app.core import repo
from app.core.api.stream import resolve_start, stream_timeline


async def _next(agen, timeout: float = 2.0):
    return await asyncio.wait_for(agen.__anext__(), timeout)


def test_resolve_start():
    assert resolve_start(0, None) == 0
    assert resolve_start(3, "7") == 7          # reconnect: Last-Event-ID is further along
    assert resolve_start(9, "7") == 9
    assert resolve_start(-5, "junk") == 0


async def test_replay_then_live_then_close(task):
    repo.emit(task.id, "plan.created", "p")                     # seq 2
    repo.emit(task.id, "step.started", "s")                     # seq 3
    agen = stream_timeline(task.id, after_seq=1)
    assert [(await _next(agen)).seq for _ in range(2)] == [2, 3]

    await asyncio.to_thread(repo.emit, task.id, "message.sent", "live")   # seq 4, other thread
    ev = await _next(agen)
    assert (ev.seq, ev.type) == (4, "message.sent")

    await agen.aclose()
    assert task.id not in repo._subs                           # unsubscribed on disconnect


async def test_resume_from_last_event_id_has_no_duplicates(task):
    for i in range(4):
        repo.emit(task.id, "error", f"e{i}")                    # seq 2..5
    agen = stream_timeline(task.id, after_seq=resolve_start(0, "3"))
    assert [(await _next(agen)).seq for _ in range(2)] == [4, 5]
    await agen.aclose()


async def test_out_of_order_publish_is_backfilled(task, monkeypatch):
    agen = stream_timeline(task.id, after_seq=0)
    assert (await _next(agen)).seq == 1                         # task.created replay

    held = []
    real_publish = repo._publish
    monkeypatch.setattr(repo, "_publish", held.append)
    repo.emit(task.id, "error", "first")                        # seq 2 (held)
    repo.emit(task.id, "error", "second")                       # seq 3 (held)
    monkeypatch.setattr(repo, "_publish", real_publish)
    real_publish(held[1])                                       # 3 arrives before 2
    real_publish(held[0])

    got = [(await _next(agen)).seq for _ in range(2)]
    assert got == [2, 3]
    repo.emit(task.id, "error", "third")                        # seq 4
    assert (await _next(agen)).seq == 4                         # late seq 2 was dropped, not re-sent
    await agen.aclose()
