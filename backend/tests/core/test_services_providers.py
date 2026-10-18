"""Roadmap D (services beyond dishwasher repair) and B (more than two providers)."""
from __future__ import annotations

from fastapi.testclient import TestClient

from app.core import approvals, repo
from app.core.api.demo import resolve_seed
from app.core.schemas import ApprovalDecisionIn, TaskStatus as S
from app.main import app
from tests.core.fakes import A1, A2, B1, events, reply, ticks

client = TestClient(app)

WASHER_A = ("Hi! Washing machine diagnostic visit is $110 including travel. Tuesday 3–4pm. "
            "Free cancellation with 24 hours notice.")
WASHER_B = ("Yes, we fix washers. Diagnostic visit is $135 including travel. Tuesday 2:30–3:30pm "
            "or 4–5pm. Cancel free more than 12 hours ahead, $25 inside 12 hours.")
DISHWASHER_ONLY = ("Yes we repair dishwashers. Diagnostic visit is $99 including travel. "
                   "Tuesday 3–4pm. Free cancellation with 24 hours notice.")
C_160 = ("Coastal Appliance Pros here. Dishwasher diagnostic visit is $160 including travel. "
         "Tuesday 2–3pm. Free cancellation with 48 hours notice.")


# ---------------------------------------------------------------- D. services
def test_service_catalog_seed_and_filters():
    services = client.get("/services").json()
    assert [s["id"] for s in services] == ["dishwasher_repair", "washer_repair"]
    assert services[1]["label"] == "Washing machine repair"
    assert services[1]["pack"] == "home_repair/v1"

    washer = client.get("/demo/seed", params={"service": "washer_repair"}).json()
    assert washer["constraints"]["service"] == "washer_repair"
    assert washer["outcome_text"].startswith("Arrange a washing machine repair visit")
    w = client.post("/tasks", json=washer).json()["task"]["id"]
    d = client.post("/tasks", json=client.get("/demo/seed").json()).json()["task"]["id"]
    assert [t["id"] for t in client.get("/tasks", params={"service": "washer_repair"}).json()] == [w]
    assert {t["id"] for t in client.get("/tasks", params={"status": "DRAFT"}).json()} == {w, d}
    assert client.get("/tasks", params={"status": "COMPLETED"}).json() == []

    bad = dict(washer)
    bad["constraints"] = {**washer["constraints"], "service": "roof_repair"}
    r = client.post("/tasks", json=bad)
    assert r.status_code == 422 and "unknown service 'roof_repair'" in r.json()["error"]["details"]["fields"][0]["msg"]


async def test_washer_search_runs_end_to_end(env):
    task = repo.create_task(resolve_seed("fixture", service="washer_repair"))
    await ticks(task.id)
    assert "washer" in env.messaging.texts[0][1]                     # the inquiry names the job
    await reply(task.id, "provider_a", DISHWASHER_ONLY)              # wrong appliance
    await reply(task.id, "provider_b", WASHER_B)
    await ticks(task.id)
    a = repo.get_latest_approval(task.id)
    assert a.proposal.provider_id == "provider_b" and a.proposal.service == "washer_repair"
    assert repo.get_active_fact(task.id, "provider_a.service_supported") is None
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.COMPLETED


# ---------------------------------------------------------------- B. more than two providers
def test_sandbox_catalog_and_provider_cap():
    sandbox = client.get("/demo/providers").json()
    assert [p["id"] for p in sandbox] == ["provider_a", "provider_b", "provider_c"]
    seed = client.get("/demo/seed", params={"extra": True}).json()
    assert [p["id"] for p in seed["providers"]] == ["provider_a", "provider_b", "provider_c"]
    assert [p["id"] for p in client.get("/demo/seed").json()["providers"]] == \
        ["provider_a", "provider_b"]                                  # canonical story unchanged
    too_many = dict(seed)
    too_many["providers"] = [{**seed["providers"][0], "id": f"p{i}", "handle": f"fixture:p{i}"}
                             for i in range(11)]
    r = client.post("/tasks", json=too_many)
    assert r.status_code == 422 and "at most 10 providers" in r.text


async def test_three_providers_story(env):
    task = repo.create_task(resolve_seed("fixture", extra=True))
    await ticks(task.id)
    assert {p for p, _ in env.messaging.sent} == {"provider_a", "provider_b", "provider_c"}
    await reply(task.id, "provider_a", A1)
    await reply(task.id, "provider_b", B1)
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.WAITING_EXTERNAL         # still waiting on Coastal
    await reply(task.id, "provider_c", C_160)
    await ticks(task.id)
    assert repo.get_latest_approval(task.id).proposal.provider_id == "provider_a"
    assert any(d["provider_id"] == "provider_c" for d in events(task.id, "provider.disqualified"))

    await reply(task.id, "provider_a", A2)                            # Ace's twist still works
    await ticks(task.id)
    a = repo.get_latest_approval(task.id)
    assert a.proposal.provider_id == "provider_b"
    view = client.get(f"/tasks/{task.id}").json()
    assert set(view["provider_summaries"]) == {"provider_a", "provider_b", "provider_c"}
    assert view["provider_summaries"]["provider_b"].startswith("$145.00 (diagnostic visit incl. travel)")
    assert "Not eligible: Over budget" in view["provider_summaries"]["provider_c"]
    approvals.decide(task.id, ApprovalDecisionIn(proposal_hash=a.proposal_hash, decision="approved"))
    await ticks(task.id)
    assert repo.get_task(task.id).status == S.COMPLETED
