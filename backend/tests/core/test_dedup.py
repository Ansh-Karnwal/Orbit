"""A11: duplicate inbound events never duplicate actions."""
from __future__ import annotations

from app.context import extract as ctx_extract
from app.core import repo
from tests.core.fakes import A1, A2, B1, events, reply, ticks, types


async def test_same_external_id_twice_is_processed_once(task, env, monkeypatch):
    calls = []
    real = ctx_extract.extract_provider_facts

    async def spy(task_id, provider_id, text, source_id):
        calls.append(source_id)
        return await real(task_id, provider_id, text, source_id)
    monkeypatch.setattr(ctx_extract, "extract_provider_facts", spy)

    await ticks(task.id)
    await reply(task.id, "provider_a", A1, external_id="ext-a1")
    await reply(task.id, "provider_a", A1, external_id="ext-a1")
    await reply(task.id, "provider_b", B1, external_id="ext-b1")
    await ticks(task.id)
    await reply(task.id, "provider_a", A2, external_id="ext-a2")
    await reply(task.id, "provider_a", A2, external_id="ext-a2")
    await ticks(task.id)

    assert len(repo.list_inbound(task.id)) == 3
    assert len(calls) == 3 and len(set(calls)) == 3
    assert types(task.id).count("message.duplicate_ignored") == 2
    assert types(task.id).count("message.received") == 3
    assert len(events(task.id, "fact.superseded")) == 1
    assert len(repo.list_evidence(task.id, kind="message_in")) == 3
    assert types(task.id).count("approval.invalidated") == 1
