"""Owner: Victor. Timeline stream for SSE: replay from the DB, then live from pub/sub, with no
duplicates and no gaps (an out-of-order live event triggers a DB backfill)."""
from __future__ import annotations

from typing import AsyncIterator

from app.core import repo
from app.core.schemas import TimelineEvent


def resolve_start(after_seq: int, last_event_id: str | None) -> int:
    """Last-Event-ID (set by EventSource on reconnect) wins when it is further along."""
    start = max(after_seq, 0)
    if last_event_id:
        try:
            start = max(start, int(last_event_id))
        except ValueError:
            pass
    return start


async def stream_timeline(task_id: str, after_seq: int) -> AsyncIterator[TimelineEvent]:
    q = repo.subscribe(task_id)            # subscribe BEFORE replay so nothing falls between
    last = after_seq
    try:
        for ev in repo.list_timeline(task_id, after_seq=last):
            yield ev
            last = ev.seq
        while True:
            ev: TimelineEvent = await q.get()
            if ev.seq <= last:
                continue                    # already replayed / delivered
            if ev.seq > last + 1:           # published out of order: backfill from the DB
                for missed in repo.list_timeline(task_id, after_seq=last):
                    yield missed
                    last = missed.seq
                continue
            yield ev
            last = ev.seq
    finally:
        repo.unsubscribe(task_id, q)
