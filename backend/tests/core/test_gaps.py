"""Closes the Phase 4/5 audit gaps: (a) stale messages, (b) extraction retry policy,
DB migration for new columns, and (f) SSE over real HTTP. Budget (c), UTC (d) and limits (e) are
covered in test_reject_answers / test_auth_errors / test_coordinator."""
from __future__ import annotations

import asyncio
import json
import sqlite3
import threading
import time
from datetime import timedelta

import httpx
import pytest
import uvicorn

from app.context import extract as ctx_extract
from app.core import answers, db, inbound, questions, repo
from app.core.api import tasks as tasks_api
from app.core.schemas import AnswerIn, InboundEvent, TaskStatus as S, new_id, utcnow
from tests.core.fakes import A2, reply, to_approval_for_a, ticks


# ---------------------------------------------------------------- (a) stale message ordering
async def test_older_message_delivered_late_does_not_regress_facts(task, env):
    await to_approval_for_a(task.id)
    await reply(task.id, "provider_a", A2)                          # $190 total (newest)
    await ticks(task.id)
    newest = repo.get_active_fact(task.id, "provider_a.visit_charge_cents")
    assert newest.value == 19000
    late = InboundEvent(id=new_id("inb"), source="demo", external_id="late-1", task_id=task.id,
                        provider_id="provider_a",
                        text="Dishwasher repair visit is $120. Tuesday 3–4pm.",
                        received_at=newest.observed_at - timedelta(minutes=5))
    await inbound.handle_inbound(late)
    await ticks(task.id)
    assert repo.get_active_fact(task.id, "provider_a.visit_charge_cents").value == 19000
    history = repo.list_facts(task.id, "provider_a.visit_charge_cents", include_inactive=True)
    assert history[-1].status.value == "rejected"                  # recorded, not trusted


# ---------------------------------------------------------------- (b) extraction retry policy
async def test_unreadable_late_message_backs_off_then_asks(task, env, monkeypatch):
    await to_approval_for_a(task.id)
    real = ctx_extract.extract_provider_facts

    async def broken(*a, **k):
        raise TimeoutError("model timed out")
    monkeypatch.setattr(ctx_extract, "extract_provider_facts", broken)
    await reply(task.id, "provider_a", A2)
    ev = repo.list_unprocessed_inbound(task.id)[0]
    for attempt in (1, 2):
        await ticks(task.id, 1)
        ev = repo.get_inbound(ev.id)
        assert ev.payload["extract_attempts"] == attempt and not ev.processed
        await ticks(task.id, 1)                                    # still backing off: no attempt
        assert repo.get_inbound(ev.id).payload["extract_attempts"] == attempt
        repo.update_inbound(ev.id, payload={"extract_retry_at": (utcnow() - timedelta(seconds=1)).isoformat()})
    await ticks(task.id, 1)
    t = repo.get_task(task.id)
    assert t.status == S.BLOCKED and t.reason_code == "step_failed"
    assert repo.get_latest_approval(task.id).status == "invalidated"   # Ace's terms untrusted
    assert sum(1 for e in repo.list_timeline(task.id) if e.type == "error") == 2

    monkeypatch.setattr(ctx_extract, "extract_provider_facts", real)
    q = questions.open_question(task.id)
    answers.answer(task.id, AnswerIn(question_id=q.question_id, choice="retry"), "demo_user")
    await ticks(task.id)
    assert repo.get_active_fact(task.id, "provider_a.visit_charge_cents").value == 19000
    assert repo.get_latest_approval(task.id).proposal.provider_id == "provider_b"


# ---------------------------------------------------------------- migration
def test_old_database_gains_new_columns(tmp_path):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.execute("CREATE TABLE tasks (id VARCHAR PRIMARY KEY, outcome_text TEXT, constraints JSON, "
                "limits JSON, mode VARCHAR, status VARCHAR, status_reason TEXT, source VARCHAR, "
                "creao_ref VARCHAR, summary TEXT, created_at DATETIME, updated_at DATETIME)")
    con.execute("INSERT INTO tasks VALUES ('tsk_old','x','{}','{}','fixture','DRAFT','','manual',"
                "NULL,NULL,'2026-10-17 00:00:00','2026-10-17 00:00:00')")
    con.commit()
    con.close()
    db.init_db(f"sqlite:///{path.as_posix()}")
    con = sqlite3.connect(path)
    cols = {r[1] for r in con.execute("PRAGMA table_info(tasks)")}
    owner = con.execute("SELECT owner_id FROM tasks WHERE id='tsk_old'").fetchone()[0]
    tables = {r[0] for r in con.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    con.close()
    assert {"owner_id", "reason_code", "user_contact"} <= cols
    assert owner == "demo_user" and "sessions" in tables


# ---------------------------------------------------------------- (f) SSE over real HTTP
@pytest.fixture
def live_server(env, monkeypatch):
    from app.main import app
    monkeypatch.setattr(tasks_api, "PING_INTERVAL_S", 0.3)
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 10
    while not server.started:
        assert time.monotonic() < deadline, "server didn't start"
        time.sleep(0.02)
    port = server.servers[0].sockets[0].getsockname()[1]
    yield f"http://127.0.0.1:{port}"
    server.should_exit = True
    thread.join(10)


def _frames(url: str, n: int = 200, headers: dict | None = None, until=None) -> list[dict]:
    """Read SSE frames until `n` frames, or until a frame satisfies `until`."""
    frames, cur = [], {}
    with httpx.stream("GET", url, headers=headers or {}, timeout=10) as r:
        assert r.status_code == 200 and r.headers["content-type"].startswith("text/event-stream")
        for line in r.iter_lines():
            if line == "":
                if cur:
                    frames.append(cur)
                    cur = {}
                    if len(frames) >= n or (until and until(frames[-1])):
                        return frames
            elif ":" in line:
                k, v = line.split(":", 1)
                cur[k] = v.strip()
    return frames


def test_sse_frames_ping_and_resume_over_http(live_server):
    base = live_server
    from app.core.api.demo import resolve_seed
    tid = httpx.post(f"{base}/tasks", json=resolve_seed("fixture").model_dump(mode="json")).json()["task"]["id"]
    deadline = time.monotonic() + 10
    while len(repo.list_timeline(tid)) < 6:                       # the worker is planning/sending
        assert time.monotonic() < deadline
        time.sleep(0.05)
    frames = _frames(f"{base}/tasks/{tid}/events", until=lambda f: f.get("event") == "ping")
    timeline = [f for f in frames if f.get("event") == "timeline"]
    assert [int(f["id"]) for f in timeline] == list(range(1, len(timeline) + 1))
    first = json.loads(timeline[0]["data"])
    assert first["type"] == "task.created" and first["at"].endswith("Z")
    assert any(f.get("event") == "ping" for f in frames)          # keep-alive pings arrive
    resumed = _frames(f"{base}/tasks/{tid}/events", 1, headers={"Last-Event-ID": "3"})
    assert resumed[0]["id"] == "4"
    assert httpx.get(f"{base}/tasks/tsk_nope/events").status_code == 404
