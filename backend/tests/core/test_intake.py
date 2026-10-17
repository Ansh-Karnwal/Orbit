"""A1: invalid intake -> 422 with readable, field-addressed messages; nothing is created."""
from __future__ import annotations

from datetime import datetime, timedelta

import pytest
from fastapi.testclient import TestClient

from app.core.api.demo import resolve_seed
from app.main import app

client = TestClient(app)          # no `with`: no lifespan, so no background worker


def _seed() -> dict:
    return resolve_seed("fixture").model_dump(mode="json")


def _shift(iso: str, delta: timedelta) -> str:
    return (datetime.fromisoformat(iso) + delta).isoformat()


def _end_before_start(b):
    b["constraints"]["window_end"] = _shift(b["constraints"]["window_start"], timedelta(hours=-1))


def _past_window(b):
    for k in ("window_start", "window_end"):
        b["constraints"][k] = _shift(b["constraints"][k], timedelta(days=-30))


def _naive(b):
    for k in ("window_start", "window_end"):
        b["constraints"][k] = b["constraints"][k].replace("Z", "").split("+")[0]


CASES = {
    "end_before_start": (_end_before_start, "window_end must be after window_start"),
    "past_window": (_past_window, "must be in the future"),
    "naive_datetimes": (_naive, "must include a UTC offset"),
    "bad_timezone": (lambda b: b["constraints"].update(timezone="Mars/Olympus_Mons"), "unknown timezone"),
    "zero_budget": (lambda b: b["constraints"].update(max_visit_charge_cents=0), "positive whole number"),
    "negative_budget": (lambda b: b["constraints"].update(max_visit_charge_cents=-100), "positive whole number"),
    "fractional_cents": (lambda b: b["constraints"].update(max_visit_charge_cents=150.5), "integer"),
    "no_providers": (lambda b: b.update(providers=[]), "at least one provider"),
    "duplicate_providers": (lambda b: b["providers"][1].update(id="provider_a"), "duplicate provider ids: provider_a"),
    "empty_handle": (lambda b: b["providers"][0].update(handle=" "), "handle must not be empty"),
    "live_with_fixture_handles": (lambda b: b.update(mode="live"), "live mode needs a real messaging handle"),
    "missing_field": (lambda b: b["constraints"].pop("max_visit_charge_cents"), "Field required"),
}


@pytest.mark.parametrize("name", CASES)
def test_invalid_intake_is_422(name):
    mutate, expected = CASES[name]
    body = _seed()
    mutate(body)
    r = client.post("/tasks", json=body)
    assert r.status_code == 422, r.text
    detail = r.json()["detail"]
    assert isinstance(detail, list) and detail
    assert any(expected in d["msg"] for d in detail), detail
    assert all(d["loc"][0] == "body" for d in detail)
    assert client.get("/tasks").json() == []


def test_all_errors_reported_at_once():
    body = _seed()
    body["constraints"]["timezone"] = "Nope/Nowhere"
    body["constraints"]["max_visit_charge_cents"] = 0
    body["providers"][1]["id"] = "provider_a"
    locs = {tuple(d["loc"]) for d in client.post("/tasks", json=body).json()["detail"]}
    assert {("body", "constraints", "timezone"), ("body", "constraints", "max_visit_charge_cents"),
            ("body", "providers")} <= locs


def test_valid_intake_creates_task():
    r = client.post("/tasks", json=_seed())
    assert r.status_code == 201, r.text
    view = r.json()
    assert view["task"]["status"] == "DRAFT" and view["task"]["source"] == "demo_seed"
    assert [p["id"] for p in view["providers"]] == ["provider_a", "provider_b"]
    assert [e["type"] for e in view["timeline"]] == ["task.created"]
    assert view["integrations"]["photon"] == "fixture"
    assert view["task"]["created_at"].endswith("Z")
