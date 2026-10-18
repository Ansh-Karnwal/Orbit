"""Phase 6: demo endpoints — reset, inject-event, portal-fault. The portal is mocked at the
single proxy function; nothing leaves the process."""
from __future__ import annotations

import time

import httpx
import pytest
from fastapi.testclient import TestClient

from app.core import repo, worker
from app.core.api import demo
from app.core.config import get_settings
from app.core.evidence import save_evidence
from app.main import app
from tests.core.fakes import B1, events, types

client = TestClient(app)          # no lifespan -> no background worker


@pytest.fixture
def portal(monkeypatch):
    """Records proxy calls; set .down = True to simulate an unreachable portal."""
    class P:
        calls: list[tuple[str, dict]] = []
        down = False

    async def fake_post(path: str, body: dict) -> dict:
        if P.down:
            raise httpx.ConnectError("connection refused")
        P.calls.append((path, body))
        return {"mode": body["mode"]} if "mode" in body else {"ok": True}
    P.calls = []
    monkeypatch.setattr(demo, "_portal_post", fake_post)
    return P


def _seeded_task() -> str:
    return client.post("/demo/reset", json={"create_task": True}).json()["task_id"]


# ---------------------------------------------------------------- reset
def test_reset_is_gated(monkeypatch, portal):
    monkeypatch.setattr(get_settings(), "orbit_allow_reset", False)
    r = client.post("/demo/reset", json={"create_task": True})
    assert r.status_code == 403 and "ORBIT_ALLOW_RESET" in r.json()["detail"]
    assert portal.calls == []


def test_reset_wipes_db_artifacts_and_portal(portal, tmp_path):
    old = _seeded_task()
    ev = save_evidence(old, "screenshot", "fixture_browser", is_fixture=True, data=b"x", ext="png")
    art = tmp_path / "artifacts"
    assert (art / ev.uri).is_file()

    r = client.post("/demo/reset", json={"create_task": False})
    assert r.status_code == 200 and r.json() == {"task_id": None}
    assert client.get("/tasks").json() == []
    assert client.get(f"/tasks/{old}").status_code == 404
    assert art.exists() and list(art.iterdir()) == []
    assert portal.calls[-1] == ("/admin/reset", {})


def test_reset_creates_seeded_task(portal):
    r = client.post("/demo/reset", json={"create_task": True, "mode": "fixture"})
    tid = r.json()["task_id"]
    assert r.status_code == 200 and tid.startswith("tsk_")
    view = client.get(f"/tasks/{tid}").json()
    assert view["task"]["source"] == "demo_seed" and view["task"]["mode"] == "fixture"
    assert view["task"]["constraints"]["max_visit_charge_cents"] == 15000
    assert [t["id"] for t in client.get("/tasks").json()] == [tid]


def test_reset_survives_portal_down(portal):
    portal.down = True
    r = client.post("/demo/reset", json={"create_task": True})
    assert r.status_code == 200 and r.json()["task_id"]


def test_reset_live_without_handles_is_422(portal, monkeypatch):
    s = get_settings()
    monkeypatch.setattr(s, "live_provider_a_handle", "")
    monkeypatch.setattr(s, "live_provider_b_handle", "")
    _seeded_task()
    r = client.post("/demo/reset", json={"create_task": True, "mode": "live"})
    assert r.status_code == 422
    # Live seeds list only providers with a live handle, so none are left to contact.
    assert any("at least one provider is required" in d["msg"] for d in r.json()["detail"])
    assert len(client.get("/tasks").json()) == 1         # validation happens before wiping


def test_reset_refuses_unsafe_artifact_dir(portal, monkeypatch):
    tid = _seeded_task()
    monkeypatch.setattr(get_settings(), "artifact_dir", str(demo.BACKEND_DIR))
    r = client.post("/demo/reset", json={"create_task": False})
    assert r.status_code == 500 and "unsafe location" in r.json()["detail"]
    assert client.get(f"/tasks/{tid}").status_code == 200   # nothing was wiped


async def test_reset_with_running_worker_restarts_it(portal, env):
    with TestClient(app) as c:                               # lifespan: worker runs
        assert worker.is_running()
        tid = c.post("/demo/reset", json={"create_task": True}).json()["task_id"]
        assert worker.is_running()
        for _ in range(500):            # the worker runs in another thread: wait for both sends
            if len(env.messaging.sent) == 2 and repo.get_task(tid).status == "WAITING_EXTERNAL":
                break
            time.sleep(0.02)
        assert {p for p, _ in env.messaging.sent} == {"provider_a", "provider_b"}
        assert repo.get_task(tid).status == "WAITING_EXTERNAL"
    assert not worker.is_running()


# ---------------------------------------------------------------- inject-event
def test_inject_event_and_dedup(portal):
    tid = _seeded_task()
    body = {"task_id": tid, "provider_id": "provider_b", "text": B1, "external_id": "demo-1"}
    r1 = client.post("/demo/inject-event", json=body)
    r2 = client.post("/demo/inject-event", json=body)
    assert r1.status_code == r2.status_code == 200
    assert r1.json()["created"] is True and r2.json() == {"inbound_id": r1.json()["inbound_id"],
                                                          "created": False}
    assert types(tid).count("message.received") == 1
    assert types(tid).count("message.duplicate_ignored") == 1
    received, = events(tid, "message.received")
    assert received["source"] == "demo" and received["is_fixture"] is True
    assert len(repo.list_evidence(tid, kind="message_in")) == 1

    r3 = client.post("/demo/inject-event", json={**body, "external_id": None})
    assert r3.json()["created"] is True                     # no external_id -> always new


def test_inject_event_404s(portal):
    tid = _seeded_task()
    r = client.post("/demo/inject-event", json={"task_id": "tsk_nope", "provider_id": "provider_a",
                                                "text": "hi"})
    assert r.status_code == 404
    r = client.post("/demo/inject-event", json={"task_id": tid, "provider_id": "provider_z",
                                                "text": "hi"})
    assert r.status_code == 404
    assert repo.list_inbound(tid) == []


# ---------------------------------------------------------------- portal-fault
def test_portal_fault_proxies(portal):
    r = client.post("/demo/portal-fault", json={"mode": "mismatch"})
    assert r.status_code == 200 and r.json() == {"mode": "mismatch"}
    assert portal.calls[-1] == ("/admin/fault", {"mode": "mismatch"})


def test_portal_fault_validation_and_down(portal):
    assert client.post("/demo/portal-fault", json={"mode": "explode"}).status_code == 422
    portal.down = True
    r = client.post("/demo/portal-fault", json={"mode": "down"})
    assert r.status_code == 502 and "portal unreachable" in r.json()["detail"]
