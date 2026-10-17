"""Logs are JSON lines and never carry phone numbers, emails, keys or message bodies."""
from __future__ import annotations

import json
import logging

from app.core.logs import JsonFormatter, redact
from tests.core.fakes import reply, ticks


def test_redaction():
    s = redact("call +13105551234 or 310-555-1234, mail a.b@example.com, key sk-abcdef123456789 "
               "x-api-key: hunter2hunter2 at 2026-10-20 14:00")
    for leaked in ("13105551234", "310-555-1234", "a.b@example.com", "sk-abcdef123456789", "hunter2"):
        assert leaked not in s
    assert "2026-10-20 14:00" in s                     # timestamps survive


def test_json_formatter():
    rec = logging.LogRecord("orbit.x", logging.INFO, __file__, 1, "hello %s", ("+13105551234",), None)
    rec.task_id = "tsk_1"
    out = json.loads(JsonFormatter().format(rec))
    assert out["msg"] == "hello [phone]" and out["task_id"] == "tsk_1" and out["ts"].endswith("Z")


async def test_message_bodies_never_logged(task, env):
    records: list[logging.LogRecord] = []
    handler = logging.Handler()
    handler.emit = records.append
    logger = logging.getLogger("orbit")
    logger.addHandler(handler)
    old = logger.level
    logger.setLevel(logging.DEBUG)
    try:
        await ticks(task.id)
        await reply(task.id, "provider_a", "SECRET-BODY $120, call me at +13105551234")
        await ticks(task.id)
    finally:
        logger.removeHandler(handler)
        logger.setLevel(old)
    formatted = [JsonFormatter().format(r) for r in records]
    assert records, "expected some orbit log lines"
    assert not any("SECRET-BODY" in line or "13105551234" in line for line in formatted)
