"""Text-only flow: the user texts a request (ORBIT_TEXT_INTAKE), approves with a plain YES
(ORBIT_TEXT_APPROVALS), and Orbit books only after the provider confirms (ORBIT_PROVIDER_CONFIRM)."""
from __future__ import annotations

import pytest

from app.core import inbound, repo
from app.core.config import get_settings
from app.core.schemas import InboundEvent, StepKind as K, TaskStatus as S, new_id, utcnow
from tests.core.fakes import A1, B1, events, reply, ticks

USER = "+15555550199"
REQUEST = ("My dishwasher needs a visit. Tuesday afternoon works. Keep it under $150, "
           "and ask me before booking.")


@pytest.fixture
def flags(monkeypatch):
    s = get_settings()
    for name, value in (("orbit_text_intake", True), ("orbit_text_approvals", True),
                        ("orbit_provider_confirm", True), ("live_user_handle", USER)):
        monkeypatch.setattr(s, name, value)


async def _user_says(text: str, handle: str = USER) -> None:
    await inbound.handle_inbound(InboundEvent(
        id=new_id("inb"), source="demo", external_id=new_id("ext"), sender_handle=handle,
        text=text, received_at=utcnow()))


def _texts(env, to: str) -> list[str]:
    return [t for p, t in env.messaging.texts if p == to]


async def _to_user_approval() -> str:
    await _user_says(REQUEST)
    tid = repo.find_task_by_user_contact(USER)
    assert tid is not None
    await ticks(tid)
    await reply(tid, "provider_a", A1)
    await reply(tid, "provider_b", B1)
    await ticks(tid)
    return tid


async def test_text_request_to_provider_confirmed_booking(flags, env):
    tid = await _to_user_approval()
    task = repo.get_task(tid)
    assert task.outcome_text == REQUEST and task.user_contact == USER
    assert task.constraints.max_visit_charge_cents == 15000
    ack, approval_text = _texts(env, "user")[:2]
    assert ack.startswith("Orbit: on it.") and "under $150.00" in ack
    assert "$120.00" in approval_text and "reply YES to approve" in approval_text

    await _user_says("Yes")
    assert repo.get_latest_approval(tid).status == "approved"
    await ticks(tid)
    assert repo.get_task(tid).status == S.WAITING_EXTERNAL
    assert env.portal.created == []                       # nothing booked before the provider says yes
    confirm = _texts(env, "provider_a")[-1]
    assert "Reply YES to confirm" in confirm and "$120.00" in confirm

    await reply(tid, "provider_a", "Yes, confirmed")
    await ticks(tid)
    assert repo.get_task(tid).status == S.COMPLETED
    assert len(env.portal.created) == 1
    kinds = [s.kind for s in repo.list_steps(tid)]
    assert kinds.index(K.REQUEST_APPROVAL) < kinds.index(K.CONFIRM_WITH_PROVIDER) < kinds.index(K.SUBMIT_BOOKING)
    assert events(tid, "provider.confirmed")[0]["provider_id"] == "provider_a"
    assert _texts(env, "user")[-1].startswith("Orbit: handled")


async def test_provider_saying_no_never_books(flags, env):
    tid = await _to_user_approval()
    await _user_says("yes")
    await ticks(tid)
    await reply(tid, "provider_a", "No, sorry, that slot is gone")
    await ticks(tid)
    assert env.portal.created == []
    assert repo.get_latest_approval(tid).status == "invalidated"
    assert repo.get_task(tid).status == S.BLOCKED


async def test_only_the_user_handle_and_real_requests_start_tasks(flags, env):
    await _user_says("thanks!")                                   # not a request
    await _user_says(REQUEST, handle="+15555550100")              # not the configured user
    assert repo.find_task_by_user_contact(USER) is None
    assert repo.find_task_by_user_contact("+15555550100") is None


async def test_without_the_flag_there_is_no_confirmation_step(task, env):
    await ticks(task.id)
    assert K.CONFIRM_WITH_PROVIDER not in [s.kind for s in repo.list_steps(task.id)]


async def test_single_live_provider_flow_books_ace(flags, env, monkeypatch):
    """Live intake keeps only providers with a live handle: here just Ace, quoting in one text."""
    from app.core.api import demo
    real = demo.resolve_seed

    def only_ace(*a, **kw):
        seed = real(*a, **kw)
        return seed.model_copy(update={"providers": [p for p in seed.providers if p.id == "provider_a"]})

    monkeypatch.setattr(demo, "resolve_seed", only_ace)
    await _user_says(REQUEST)
    tid = repo.find_task_by_user_contact(USER)
    assert [p.id for p in repo.get_providers(tid)] == ["provider_a"]
    await ticks(tid)
    await reply(tid, "provider_a", A1)
    await ticks(tid)
    assert repo.get_latest_approval(tid).proposal.provider_id == "provider_a"
    await _user_says("YES")
    await ticks(tid)
    await reply(tid, "provider_a", "yes")
    await ticks(tid)
    assert repo.get_task(tid).status == S.COMPLETED and len(env.portal.created) == 1
