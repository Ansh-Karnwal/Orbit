"""Roadmap E (sign-in seam, owner scoping) and F1 (one error envelope for every non-2xx)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import repo
from app.core.api.demo import resolve_seed
from app.core.config import get_settings
from app.main import app
from tests.core.fakes import to_approval_for_a


def _client() -> TestClient:
    return TestClient(app)        # no lifespan; a fresh cookie jar per client


def _seed() -> dict:
    return resolve_seed("fixture").model_dump(mode="json")


def _err(r) -> dict:
    body = r.json()
    assert set(body["error"]) == {"code", "message", "retryable", "field", "details"}, body
    return body["error"]


def test_signed_in_users_only_see_their_own_tasks():
    anon, alice = _client(), _client()
    t1 = anon.post("/tasks", json=_seed()).json()["task"]["id"]
    assert anon.get("/auth/me").json() == {"user_id": "demo_user", "display_name": "Demo user",
                                           "authenticated": False, "auth_mode": "demo"}

    r = alice.post("/auth/login", json={"display_name": "Alice Ng"})
    assert r.status_code == 200 and r.json()["user_id"] == "u_alice-ng"
    assert "httponly" in r.headers["set-cookie"].lower()
    assert alice.get("/auth/me").json()["authenticated"] is True
    assert alice.get("/tasks").json() == []
    r = alice.get(f"/tasks/{t1}")
    assert r.status_code == 404 and _err(r)["code"] == "not_found"     # not "forbidden": no leak
    t2 = alice.post("/tasks", json=_seed()).json()["task"]["id"]
    assert repo.get_task(t2).owner_id == "u_alice-ng"
    assert [t["id"] for t in alice.get("/tasks").json()] == [t2]
    assert [t["id"] for t in anon.get("/tasks").json()] == [t1]

    alice.post("/auth/logout")
    assert alice.get("/auth/me").json()["authenticated"] is False
    assert [t["id"] for t in alice.get("/tasks").json()] == [t1]       # back to the demo user


def test_required_mode_needs_sign_in(monkeypatch):
    monkeypatch.setattr(get_settings(), "orbit_auth_mode", "required")
    c = _client()
    r = c.get("/tasks")
    assert r.status_code == 401 and _err(r)["code"] == "unauthorized"
    assert c.get("/health").status_code == 200                         # health stays public
    c.post("/auth/login", json={"display_name": "Bo"})
    assert c.get("/tasks").status_code == 200


async def test_approver_is_the_signed_in_user_not_the_body(env):
    c = _client()
    c.post("/auth/login", json={"display_name": "Bob"})
    tid = c.post("/tasks", json=_seed()).json()["task"]["id"]
    await to_approval_for_a(tid)
    h = repo.get_latest_approval(tid).proposal_hash
    r = c.post(f"/tasks/{tid}/approvals",
               json={"proposal_hash": h, "decision": "approved", "approver": "mallory"})
    assert r.status_code == 200 and r.json()["approver"] == "u_bob"


async def test_error_envelope_shapes(env):
    c = _client()
    # 404
    r = c.get("/tasks/tsk_nope")
    assert r.status_code == 404 and _err(r)["code"] == "not_found"
    # 422 intake: envelope + legacy field list kept for older clients
    bad = _seed()
    bad["constraints"]["max_visit_charge_cents"] = 0
    r = c.post("/tasks", json=bad)
    e = _err(r)
    assert r.status_code == 422 and e["code"] == "invalid_intake"
    assert e["field"] == "constraints.max_visit_charge_cents"
    assert e["details"]["fields"][0]["msg"].startswith("max_visit_charge_cents must be")
    assert r.json()["detail"] == e["details"]["fields"]
    # 422 schema validation (pydantic)
    r = c.post("/tasks", json={"outcome_text": "x"})
    assert r.status_code == 422 and _err(r)["code"] == "invalid_request"
    # 422 limits must be positive (audit gap e)
    bad = _seed()
    bad["limits"] = {"max_tool_actions": 0}
    assert c.post("/tasks", json=bad).status_code == 422
    # 409 stale proposal: envelope + legacy detail object
    tid = c.post("/tasks", json=_seed()).json()["task"]["id"]
    await to_approval_for_a(tid)
    r = c.post(f"/tasks/{tid}/approvals", json={"proposal_hash": "0" * 64, "decision": "approved"})
    e = _err(r)
    assert r.status_code == 409 and e["code"] == "stale_proposal"
    assert e["details"]["current_hash"] == repo.get_latest_approval(tid).proposal_hash
    assert r.json()["detail"]["code"] == "stale_proposal"
    # 409 answering when there's no open question
    r = c.post(f"/tasks/{tid}/answers", json={"question_id": "q_x", "choice": "stop"})
    assert r.status_code == 409 and _err(r)["code"] == "stale_question"
    # 409 already terminal
    c.post(f"/tasks/{tid}/cancel")
    r = c.post(f"/tasks/{tid}/cancel")
    assert r.status_code == 409 and _err(r)["code"] == "already_terminal"
    # 403 reset disabled
    get_settings().orbit_allow_reset, old = False, get_settings().orbit_allow_reset
    try:
        r = c.post("/demo/reset", json={"create_task": False})
        assert r.status_code == 403 and _err(r)["code"] == "reset_disabled"
    finally:
        get_settings().orbit_allow_reset = old


def test_utc_normalisation_at_intake():
    body = _seed()
    body["constraints"]["window_start"] = "2027-03-02T14:00:00-08:00"
    body["constraints"]["window_end"] = "2027-03-02T17:00:00-08:00"
    view = _client().post("/tasks", json=body).json()
    assert view["task"]["constraints"]["window_start"] == "2027-03-02T22:00:00Z"
    assert view["task"]["constraints"]["window_end"] == "2027-03-03T01:00:00Z"
