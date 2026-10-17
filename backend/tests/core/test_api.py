"""Phase 5: HTTP API over the real coordinator (fake adapters). GET /tasks/{id} must be a valid
TaskView at every stage; approvals are hash-bound (409 stale_proposal)."""
from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from app.core import repo
from app.core.api.demo import resolve_seed
from app.core.evidence import save_evidence
from app.core.schemas import EvidenceArtifact, TaskView, new_id, utcnow
from app.main import app
from tests.core.fakes import A1, A2, B1, reply, ticks

client = TestClient(app)          # no lifespan -> no background worker; tests drive tick()


def _create() -> str:
    r = client.post("/tasks", json=resolve_seed("fixture").model_dump(mode="json"))
    assert r.status_code == 201, r.text
    return r.json()["task"]["id"]


def _view(task_id: str) -> TaskView:
    r = client.get(f"/tasks/{task_id}")
    assert r.status_code == 200, r.text
    return TaskView.model_validate(r.json())


def _approve(task_id: str, proposal_hash: str):
    return client.post(f"/tasks/{task_id}/approvals",
                       json={"proposal_hash": proposal_hash, "decision": "approved"})


async def test_view_is_valid_at_every_stage_through_completion(env):
    tid = _create()
    assert _view(tid).task.status == "DRAFT"

    await ticks(tid)
    v = _view(tid)
    assert v.task.status == "WAITING_EXTERNAL" and len(v.steps) == 12

    await reply(tid, "provider_a", A1)
    await reply(tid, "provider_b", B1)
    await ticks(tid)
    v = _view(tid)
    assert v.task.status == "AWAITING_APPROVAL"
    assert v.current_proposal.provider_id == "provider_a"
    assert v.approvals[-1].status == "requested"
    assert v.eligibility == {"provider_a": [], "provider_b": []}

    await reply(tid, "provider_a", A2)
    await ticks(tid)
    v = _view(tid)
    assert v.current_proposal.provider_id == "provider_b"
    a_charges = [f for f in v.facts if f.key == "provider_a.visit_charge_cents"]
    assert [(f.value, f.status.value) for f in a_charges] == [(12000, "superseded"), (19000, "confirmed")]
    assert v.eligibility["provider_a"] and v.eligibility["provider_b"] == []

    r = _approve(tid, v.approvals[-1].proposal_hash)
    assert r.status_code == 200 and r.json()["status"] == "approved"
    await ticks(tid)
    v = _view(tid)
    assert v.task.status == "COMPLETED" and v.task.summary
    assert v.verification.verdict == "PASS"
    assert v.current_proposal.provider_id == "provider_b"
    assert any(e.kind == "portal_confirmation" and e.is_fixture for e in v.evidence)
    seqs = [e.seq for e in v.timeline]
    assert seqs == sorted(seqs) and len(seqs) == len(set(seqs))


async def test_stale_proposal_is_409(env):
    tid = _create()
    await ticks(tid)
    await reply(tid, "provider_a", A1)
    await reply(tid, "provider_b", B1)
    await ticks(tid)
    a_hash = _view(tid).approvals[-1].proposal_hash

    r = _approve(tid, "f" * 64)
    assert r.status_code == 409
    assert r.json()["detail"] == {"code": "stale_proposal", "current_hash": a_hash,
                                  "reason": "proposal has changed since it was shown"}

    await reply(tid, "provider_a", A2)
    await ticks(tid)
    b_hash = _view(tid).approvals[-1].proposal_hash
    r = _approve(tid, a_hash)
    assert r.status_code == 409 and r.json()["detail"]["current_hash"] == b_hash

    assert _approve(tid, b_hash).status_code == 200
    r = _approve(tid, b_hash)                              # already decided
    assert r.status_code == 409 and r.json()["detail"]["code"] == "stale_proposal"


async def test_cancel(env):
    tid = _create()
    await ticks(tid)
    await reply(tid, "provider_a", A1)
    await reply(tid, "provider_b", B1)
    await ticks(tid)
    r = client.post(f"/tasks/{tid}/cancel")
    assert r.status_code == 200 and r.json()["status"] == "CANCELLED"
    assert repo.get_latest_approval(tid).status == "invalidated"
    assert client.post(f"/tasks/{tid}/cancel").status_code == 409
    await ticks(tid)
    assert env.portal.ops() == []


def test_list_newest_first_and_404s():
    t1, t2 = _create(), _create()
    assert [t["id"] for t in client.get("/tasks").json()] == [t2, t1]
    assert client.get("/tasks/tsk_nope").status_code == 404
    assert client.get("/tasks/tsk_nope/events").status_code == 404
    assert client.get("/tasks/tsk_nope/evidence").status_code == 404
    assert client.post("/tasks/tsk_nope/cancel").status_code == 404
    r = client.post("/tasks/tsk_nope/approvals", json={"proposal_hash": "x", "decision": "approved"})
    assert r.status_code == 404
    assert client.get("/artifacts/evd_nope").status_code == 404


def test_artifacts_served_with_mime_and_traversal_blocked(tmp_path):
    tid = _create()
    ev = save_evidence(tid, "screenshot", "fixture_browser", is_fixture=True,
                       data=b"\x89PNG fake", ext="png", mime_type="image/png")
    r = client.get(f"/artifacts/{ev.id}")
    assert r.status_code == 200 and r.content == b"\x89PNG fake"
    assert r.headers["content-type"] == "image/png"
    assert [e["id"] for e in client.get(f"/tasks/{tid}/evidence").json()] == [ev.id]

    (tmp_path / "secret.txt").write_text("nope")           # outside ARTIFACT_DIR
    evil = repo.add_evidence(EvidenceArtifact(
        id=new_id("evd"), task_id=tid, kind="screenshot", source="fixture_browser",
        uri="../secret.txt", is_fixture=True, captured_at=utcnow()))
    assert (Path(tmp_path / "artifacts") / evil.uri).resolve().is_file()
    assert client.get(f"/artifacts/{evil.id}").status_code == 404

    no_file = save_evidence(tid, "message_in", "demo", is_fixture=True, extracted={"text": "hi"})
    assert client.get(f"/artifacts/{no_file.id}").status_code == 404


def test_health_and_cors():
    r = client.get("/health", headers={"Origin": "http://localhost:3000"})
    assert r.status_code == 200 and r.json()["ok"] is True
    assert r.headers["access-control-allow-origin"] == "http://localhost:3000"
    r = client.get("/health", headers={"Origin": "http://evil.example"})
    assert "access-control-allow-origin" not in r.headers
