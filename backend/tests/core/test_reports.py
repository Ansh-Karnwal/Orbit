"""Roadmap G4: Orbit texts the user (user_contact) — approvals, questions, completion — once per
event; optional text approvals bound to the proposal hash and to the user's own handle."""
from __future__ import annotations

import pytest

from app.core import inbound, repo
from app.core.api.demo import resolve_seed
from app.core.config import get_settings
from app.core.schemas import InboundEvent, TaskStatus as S, new_id, utcnow
from tests.core.fakes import B1, events, reply, to_approval_for_a, ticks

USER = "fixture:you"


@pytest.fixture
def task_with_contact():
    body = resolve_seed("fixture")
    body.user_contact = USER
    return repo.create_task(body)


def _texts_to_user(env) -> list[str]:
    return [t for p, t in env.messaging.texts if p == "user"]


async def _user_says(task_id: str, text: str, handle: str = USER) -> None:
    await inbound.handle_inbound(InboundEvent(
        id=new_id("inb"), source="demo", external_id=new_id("ext"), sender_handle=handle,
        text=text, received_at=utcnow()))


async def test_reports_are_sent_once_per_event(task_with_contact, env):
    t = task_with_contact
    await to_approval_for_a(t.id)
    await ticks(t.id, 3)                                     # extra ticks must not resend
    texts = _texts_to_user(env)
    assert len(texts) == 1 and texts[0].startswith("Orbit: Ace Appliance Repair can come")
    assert "$120.00" in texts[0] and "reply YES" not in texts[0]
    sent, = events(t.id, "report.sent")
    assert sent["kind"] == "approval.requested" and sent["is_fixture"] is True


async def test_text_approval_requires_flag_hash_and_owner_handle(task_with_contact, env, monkeypatch):
    t = task_with_contact
    await to_approval_for_a(t.id)
    h8 = repo.get_latest_approval(t.id).proposal_hash[:8]

    await _user_says(t.id, f"YES {h8}")                     # flag off: recorded, not acted on
    assert repo.get_latest_approval(t.id).status == "requested"

    monkeypatch.setattr(get_settings(), "orbit_text_approvals", True)
    await _user_says(t.id, "YES deadbeef")                  # wrong hash
    assert repo.get_latest_approval(t.id).status == "requested"
    assert any("didn't match" in e.message for e in repo.list_timeline(t.id) if e.type == "error")

    await reply(t.id, "provider_b", f"YES {h8}")            # a provider can never approve
    assert repo.get_latest_approval(t.id).status == "requested"

    await _user_says(t.id, f"yes {h8}")
    assert repo.get_latest_approval(t.id).status == "approved"
    assert repo.get_latest_approval(t.id).approver == "text:user"
    await ticks(t.id)
    assert repo.get_task(t.id).status == S.COMPLETED
    assert _texts_to_user(env)[-1].startswith("Orbit: handled")   # completion report


async def test_question_is_reported(task_with_contact, env):
    env.messaging.must_text_first = {"provider_a"}
    await ticks(task_with_contact.id, 2)
    assert any(t.startswith("Orbit needs you:") for t in _texts_to_user(env))


def test_user_contact_validation():
    from fastapi.testclient import TestClient
    from app.main import app
    body = resolve_seed("fixture").model_dump(mode="json")
    body["user_contact"] = "fixture:provider_a"
    r = TestClient(app).post("/tasks", json=body)
    assert r.status_code == 422 and "can't be one of the providers" in r.text
